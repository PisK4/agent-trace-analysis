from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import re

from ata.ingest import PiHookStates
from ata.plugins.pi import translate_hook
from ata.projection_cache import ProjectionCache
from ata.queries import audit_usage, list_compactions, list_tools, project_session, summarize_timing, summarize_tools, summarize_usage, tail_preview
from ata.schema import ValidationError, envelope, parse_event
from ata.evaluation import EvaluationStore, EvaluationValidationError


def _fallback_runs(ledger, sid):
    rows = {}
    for rec in ledger.read(sid):
        event = rec["event"]
        run_id = event.get("run_id")
        if event["type"] == "run.started" and type(run_id) is int and run_id > 0:
            rows.setdefault(run_id, {"run_id": run_id, "status": "open",
                                     "started_seq": rec["seq"], "ended_seq": None})
        elif event["type"] == "run.ended" and run_id in rows:
            rows[run_id]["status"] = "ended"
            rows[run_id]["ended_seq"] = rec["seq"]
    return [rows[run_id] for run_id in sorted(rows)]


def _fallback_turns(ledger, sid):
    rows = {}
    for rec in ledger.read(sid):
        event = rec["event"]
        run_id, turn_number = event.get("run_id"), event.get("turn_number")
        if type(run_id) is not int or run_id < 1 or type(turn_number) is not int or turn_number < 1:
            continue
        key = (run_id, turn_number)
        row = rows.setdefault(key, {"run_id": run_id, "turn_number": turn_number,
                                    "status": "open", "first_seq": rec["seq"],
                                    "last_seq": rec["seq"]})
        row["last_seq"] = rec["seq"]
        if event["type"] == "turn.ended":
            row["status"] = event["payload"].get("status", "ended")
    return [rows[key] for key in sorted(rows)]


def _fallback_run_detail(ledger, sid, run_id):
    try:
        run_id = int(run_id)
    except (TypeError, ValueError):
        return None
    run = next((row for row in _fallback_runs(ledger, sid) if row["run_id"] == run_id), None)
    if run is not None:
        run["turns"] = [row for row in _fallback_turns(ledger, sid) if row["run_id"] == run_id]
    return run


def _runtime_query(name, ledger, sid, fallback, *extra):
    try:
        from ata import queries
        fn = getattr(queries, name)
    except (ImportError, AttributeError):
        return fallback(ledger, sid, *extra)
    return fn(ledger, sid, *extra)


def make_server(ledger, webroot, host="127.0.0.1", port=8787, pi_states=None):
    webroot = Path(webroot)
    cache = ProjectionCache()
    pi_states = PiHookStates() if pi_states is None else pi_states
    evaluations = EvaluationStore(ledger)

    def cached_summary(sid):
        """便捷层统一入口：rev 门控 + read。rev 取自 session 行，调用前已确保
        会话存在；缓存的是事件记录（键即 session_id——四个端点的 compute 是
        同一份 read，同会话同 rev 只持一份快照），body 组装每请求执行。"""
        meta = ledger.session(sid)
        return cache.get_or_compute(sid, int(meta["last_seq"]),
                                    lambda: ledger.read(sid))

    # ── 路由表（架构评审二轮候选 4）：(method, pattern) → handler。
    # handler(match, qs, body) 返回 (code, payload)；qs 已 parse_qs。
    # 新端点 = 表里加一行；404/400/CORS 纪律在 dispatch 一处。外部形状冻结。

    def h_health(m, qs, body):
        return 200, {"ok": True}

    def h_session_runs(m, qs, body):
        sid = m["sid"]
        if ledger.session(sid) is None:
            return 404, {"ok": False, "error": "unknown session"}
        result = _runtime_query("list_runs", ledger, sid, _fallback_runs)
        return 200, {"ok": True, "runs": result if isinstance(result, list) else result.get("runs", [])}

    def h_session_run_detail(m, qs, body):
        sid, rid = m["sid"], m["rid"]
        if ledger.session(sid) is None:
            return 404, {"ok": False, "error": "unknown session"}
        result = _runtime_query("run_detail", ledger, sid, _fallback_run_detail, rid)
        if result is None:
            return 404, {"ok": False, "error": "unknown run"}
        return 200, {"ok": True, **(result.get("detail", result) if isinstance(result, dict) else {})}

    def h_session_turns(m, qs, body):
        sid = m["sid"]
        if ledger.session(sid) is None:
            return 404, {"ok": False, "error": "unknown session"}
        result = _runtime_query("list_turns", ledger, sid, _fallback_turns)
        return 200, {"ok": True, "turns": result if isinstance(result, list) else result.get("turns", [])}

    def _evaluation_detail(evaluation_id):
        state = evaluations.fold(evaluation_id)
        if state is None:
            return None
        members = []
        for member in state["members"]:
            sid = member["session_id"]
            meta = ledger.session(sid)
            row = dict(member)
            if meta is not None:
                row["session"] = meta
                # 评分仍是 Session fact；Evaluation 只展示最新值，不复制事实。
                projected = project_session(sid, meta["agent"], ledger.read(sid))
                row["score"] = (projected.get("scores") or [None])[-1]
            members.append(row)
        return {**state, "members": members}

    def h_evaluations(m, qs, body):
        return 200, {"ok": True, "evaluations": evaluations.evaluations()}

    def h_create_evaluation(m, qs, body):
        title = (body.get("title") or "").strip() if isinstance(body, dict) else ""
        if not title:
            return 400, {"ok": False, "error": "title required"}
        try:
            eid = evaluations.create(title)
        except (EvaluationValidationError, TypeError, ValueError) as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "evaluation_id": eid}

    def h_rename_evaluation(m, qs, body):
        title = (body.get("title") or "").strip() if isinstance(body, dict) else ""
        if not title:
            return 400, {"ok": False, "error": "title required"}
        try:
            evaluations.rename(m["eid"], title)
        except EvaluationValidationError as exc:
            if str(exc) == "evaluation not found":
                return 404, {"ok": False, "error": "unknown evaluation"}
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "title": title}

    def h_evaluation(m, qs, body):
        eid = m["eid"]
        state = _evaluation_detail(eid)
        if state is None:
            return 404, {"ok": False, "error": "unknown evaluation"}
        sub = m.get("sub") or ""
        if sub == "":
            return 200, {"ok": True, **state}
        if sub == "history":
            return 200, {"ok": True, "evaluation_id": eid,
                         "events": evaluations.read(eid)}
        return 404, {"ok": False, "error": "not found"}

    def h_delete_evaluation(m, qs, body):
        try:
            evaluations.delete(m["eid"])
        except EvaluationValidationError as exc:
            if str(exc) == "evaluation not found":
                return 404, {"ok": False, "error": "unknown evaluation"}
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "evaluation_id": m["eid"]}

    def h_add_evaluation_session(m, qs, body):
        if not isinstance(body, dict) or not body.get("session_id"):
            return 400, {"ok": False, "error": "session_id required"}
        try:
            evaluations.add_session(m["eid"], body["session_id"], body.get("task_label", ""))
        except EvaluationValidationError as exc:
            if str(exc) in {"evaluation not found", "session not found"}:
                return 404, {"ok": False, "error": str(exc)}
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "evaluation_id": m["eid"], "session_id": body["session_id"]}

    def h_remove_evaluation_session(m, qs, body):
        try:
            evaluations.remove_session(m["eid"], m["sid"])
        except EvaluationValidationError as exc:
            if str(exc) in {"evaluation not found", "session membership not found"}:
                return 404, {"ok": False, "error": str(exc)}
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "evaluation_id": m["eid"], "session_id": m["sid"]}

    def h_sessions(m, qs, body):
        return 200, ledger.sessions()

    def h_annotations(m, qs, body):
        return 200, {"ok": True, **ledger.annotations()}

    def h_session(m, qs, body):
        # 与旧版 rest.partition("/") 同语义：sub 只取第一段
        sid, _, sub = m["rest"].partition("/")
        meta = ledger.session(sid)
        if meta is None:
            return 404, {"ok": False, "error": "unknown session"}
        if sub == "":
            limit = int(qs.get("limit", ["80"])[0])
            before = qs.get("before", [None])[0]
            before = int(before) if before not in (None, "") else None
            # rev 门控：last_seq 未变（无任何事件追加/幂等折叠/改名/标注）时
            # 跳过全量投影，返回几十字节的 unchanged；前端据此零重绘。
            # last_seq 随每次 append 单调递增，天然是会话级版本号。
            rev = qs.get("rev", [None])[0]
            if not before and rev not in (None, ""):
                try:
                    if int(rev) == int(meta["last_seq"]):
                        return 200, {"ok": True, "unchanged": True,
                                     "rev": int(meta["last_seq"])}
                except ValueError:
                    pass
            recs = ledger.read(sid)
            page = project_session(sid, meta["agent"], recs, tail=limit, before=before)
            page["rev"] = int(meta["last_seq"])
            return 200, page
        if sub == "events":
            after = int(qs.get("after_seq", ["0"])[0])
            limit = min(int(qs.get("limit", ["100"])[0]), 500)
            picked = [r for r in ledger.read(sid) if r["seq"] > after][:limit]
            nxt = picked[-1]["seq"] if picked else after
            return 200, {"ok": True, "events": picked, "next_after_seq": nxt}
        if sub == "lineage":
            return 200, {"ok": True,
                         "ancestors": ledger.ancestry(sid),
                         "children": ledger.children(sid)}
        if sub == "usage":
            def usage_body(recs):
                compactions = [{"turn": r["event"].get("turn"), "seq": r["seq"]}
                               for r in recs if r["event"]["type"] == "compaction.boundary"]
                return {"ok": True, **summarize_usage(recs),
                        "audit": audit_usage(recs),
                        "compactions": compactions}
            return 200, summary_body(sid, usage_body)
        if sub == "tools":
            full = qs.get("full", ["false"])[0] == "true"
            def tools_body(recs):
                rows = list_tools(recs,
                                  qs.get("status", [None])[0],
                                  qs.get("name", [None])[0])
                for r in rows:
                    r["result"] = r["result"] if full else tail_preview(r["result"])
                return {"ok": True, "tools": rows}
            return 200, summary_body(sid, tools_body)
        if sub == "tool-stats":
            return 200, summary_body(sid, lambda recs: {"ok": True, **summarize_tools(recs)})
        if sub == "timing":
            return 200, summary_body(sid, lambda recs: {"ok": True, **summarize_timing(recs)})
        if sub == "compactions":
            full = qs.get("full", ["false"])[0] == "true"
            rows = list_compactions(ledger.read(sid))
            for r in rows:
                r["summary"] = r["summary"] if full else tail_preview(r["summary"])
            return 200, {"ok": True, "compactions": rows}
        return 404, {"ok": False, "error": "not found"}

    def summary_body(sid, fn):
        return fn(cached_summary(sid))

    def h_pi_hooks(m, qs, body):
        if not isinstance(body, dict) or "name" not in body:
            return 400, {"ok": False, "error": "hook name required"}
        sid = body.get("session_id")
        if not sid:
            return 400, {"ok": False, "error": "session_id required"}
        bucket = pi_states.bucket(sid)
        event = body.get("event") or {}
        # pi 运行时多数 hook 事件不带 timestamp（类型上只有 turn_start 有），
        # 翻译层只能回退 state 里的旧 ts，start/end 会拿到同一时刻、duration
        # 恒 0。hook 按到达序处理即事件序，缺 timestamp 时打上到达时刻。
        if not event.get("timestamp"):
            event = {**event, "timestamp": int(time.time() * 1000)}
        ctx = {
            "session_id": sid,
            "title": body.get("title") or sid,
            "agent_id": body.get("agent_id"),
            "host": body.get("host"),
            "runtime": body.get("runtime"),
            "channel": body.get("channel"),
            "lineage": body.get("lineage") or {},
        }
        try:
            events = translate_hook(body["name"], event, ctx, bucket)
            seqs = []
            for ev in events:
                parsed = parse_event(ev)
                print("append %s %s %s" % (parsed["type"], parsed["id"], parsed["session_id"]))
                seqs.append(ledger.append(parsed))
        except (ValidationError, TypeError, ValueError) as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "count": len(seqs), "seq": seqs[-1] if seqs else None}

    def h_legacy_runs(m, qs, body):
        return 404, {"ok": False, "error": "not found"}

    def h_rename_session(m, qs, body):
        # 会话改名：服务端组一个 session.renamed 事件入账本，前端不必自己造 id/ts。
        sid = m["sid"]
        title = (body.get("title") or "").strip() if isinstance(body, dict) else ""
        if not title:
            return 400, {"ok": False, "error": "title required"}
        meta = ledger.session(sid)
        if meta is None:
            return 404, {"ok": False, "error": "unknown session"}
        ev = parse_event(envelope(
            meta["agent"], sid, "session.renamed", {"title": title}))
        ledger.append(ev)
        return 200, {"ok": True, "title": title}

    def h_append_events(m, qs, body):
        items = body.get("events") if isinstance(body, dict) and "events" in body else [body]
        seqs = []
        try:
            for item in items:
                ev = parse_event(item)
                print("append %s %s %s" % (ev["type"], ev["id"], ev["session_id"]))
                seqs.append(ledger.append(ev))
        except (ValidationError, TypeError, ValueError) as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "seq": seqs[-1] if seqs else 0, "seqs": seqs}

    def h_droid_hooks(m, qs, body):
        """Droid CLI 7 类 hook 事件接收器。

        droid hooks.json command 用 `curl ... --data-binary @-` 把
        整个 JSON payload POST 到这里。 ata 不实时落账（避免与 file
        watcher 的 droid transcript 通道产生幂等竞态），仅追加一行
        audit log 到 ~/.ata/droid_hooks.jsonl，后续异步分析用。
        必须 200 fast —— PreToolUse 钩子超时或非零退出 droid 会
        AgentAbortError 杀 agent（binary 硬编码）。
        """
        audit_path = Path.home() / ".ata" / "droid_hooks.jsonl"
        from ata.wire.droid_hooks import write_hook_event
        if isinstance(body, dict):
            write_hook_event(audit_path, body)
            return 200, {"ok": True, "received_at_ms": int(time.time() * 1000)}
        return 400, {"ok": False, "error": "expected JSON object body"}

    def h_capture(m, qs, body):
        # 代理采集通道的 HTTP 入口（外部壳/测试用）：record 的 JSON 形式，
        # request_body/response_body 为 base64（JSON 不安全字节）。
        from ata.plugins.capture import RECORD_KEYS, ingest_capture
        if not isinstance(body, dict):
            return 400, {"ok": False, "error": "capture record must be object"}
        missing = RECORD_KEYS - set(body)
        if missing:
            return 400, {"ok": False, "error": f"missing {sorted(missing)}"}
        import base64
        rec = dict(body)
        for key in ("request_body", "response_body"):
            try:
                rec[key] = base64.b64decode(body.get(key) or "")
            except Exception:
                return 400, {"ok": False, "error": f"{key} must be base64"}
        try:
            count = ingest_capture(ledger, rec)
        except (ValidationError, TypeError, ValueError) as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "count": count}

    ROUTES = [
        ("GET", re.compile(r"^/api/health$"), h_health),
        ("GET", re.compile(r"^/api/runs$"), h_legacy_runs),
        ("GET", re.compile(r"^/api/sessions/(?P<sid>[^/]+)/runs$"), h_session_runs),
        ("GET", re.compile(r"^/api/sessions/(?P<sid>[^/]+)/runs/(?P<rid>[^/]+)$"), h_session_run_detail),
        ("GET", re.compile(r"^/api/sessions/(?P<sid>[^/]+)/turns$"), h_session_turns),
        ("GET", re.compile(r"^/api/evaluations$"), h_evaluations),
        ("POST", re.compile(r"^/api/evaluations$"), h_create_evaluation),
        ("GET", re.compile(r"^/api/evaluations/(?P<eid>[^/]+)/(?P<sub>history)$"), h_evaluation),
        ("GET", re.compile(r"^/api/evaluations/(?P<eid>[^/]+)$"), h_evaluation),
        ("PATCH", re.compile(r"^/api/evaluations/(?P<eid>[^/]+)$"), h_rename_evaluation),
        ("POST", re.compile(r"^/api/evaluations/(?P<eid>[^/]+)/(?P<sub>title|rename)$"), h_rename_evaluation),
        ("DELETE", re.compile(r"^/api/evaluations/(?P<eid>[^/]+)$"), h_delete_evaluation),
        ("POST", re.compile(r"^/api/evaluations/(?P<eid>[^/]+)/sessions$"), h_add_evaluation_session),
        ("DELETE", re.compile(r"^/api/evaluations/(?P<eid>[^/]+)/sessions/(?P<sid>[^/]+)$"), h_remove_evaluation_session),
        ("GET", re.compile(r"^/api/sessions$"), h_sessions),
        ("GET", re.compile(r"^/api/annotations$"), h_annotations),
        ("GET", re.compile(r"^/api/sessions/(?P<rest>.+)$"), h_session),
        ("POST", re.compile(r"^/api/captures$"), h_capture),
        ("POST", re.compile(r"^/api/pi-hooks$"), h_pi_hooks),
        ("POST", re.compile(r"^/api/hooks/droid$"), h_droid_hooks),
        ("POST", re.compile(r"^/api/sessions/(?P<sid>[^/]+)/title$"), h_rename_session),
        ("POST", re.compile(r"^/api/events$"), h_append_events),
    ]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print("%s - %s" % (self.address_string(), fmt % args))

        def _json(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _bytes(self, code, body, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            # 本地开发工具，前端文件改动频繁；禁缓存避免浏览器吃旧页面。
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.end_headers()

        def _dispatch(self, method):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            body = None
            if method in {"POST", "PATCH"}:
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError as exc:
                    return self._json(400, {"ok": False, "error": str(exc)})
            for route_method, pattern, handler in ROUTES:
                if route_method != method:
                    continue
                m = pattern.match(parsed.path)
                if m:
                    code, payload = handler(m.groupdict(), qs, body)
                    return self._json(code, payload)
            if method != "GET":
                return self._json(404, {"ok": False, "error": "not found"})
            return self._serve_static(parsed.path)

        do_GET = lambda self: self._dispatch("GET")
        do_POST = lambda self: self._dispatch("POST")
        do_PATCH = lambda self: self._dispatch("PATCH")
        do_DELETE = lambda self: self._dispatch("DELETE")

        def _serve_static(self, path):
            if path in ("/", "/index.html"):
                target = webroot / "index.html"
                if not target.exists():
                    return self._bytes(404, b"missing web/dist/index.html (run: cd webapp && npm run build)", "text/plain")
                return self._bytes(200, target.read_bytes(), "text/html; charset=utf-8")
            target = (webroot / path.lstrip("/")).resolve()
            if webroot.resolve() not in target.parents and target != webroot.resolve():
                return self._bytes(404, b"not found", "text/plain")
            if not target.is_file():
                return self._bytes(404, b"not found", "text/plain")
            ctype = "text/plain"
            if target.suffix == ".js":
                ctype = "text/javascript"
            elif target.suffix == ".css":
                ctype = "text/css"
            elif target.suffix in (".html", ".svg", ".png", ".ico"):
                ctype = "text/html; charset=utf-8" if target.suffix == ".html" else f"image/{target.suffix.lstrip('.')}"
            return self._bytes(200, target.read_bytes(), ctype)

    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd
