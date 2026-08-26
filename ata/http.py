from __future__ import annotations

import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import re

from ata.plugins.pi import translate_hook
from ata.projection_cache import ProjectionCache
from ata.project import audit_usage, list_compactions, list_tools, project_session, summarize_timing, summarize_tools, summarize_usage, tail_preview
from ata.schema import ValidationError, envelope, parse_event

_RE_RENAME = re.compile(r"^/api/sessions/([^/]+)/title$")
_RE_RUN_RENAME = re.compile(r"^/api/runs/([^/]+)/name$")


def make_server(ledger, webroot, host="127.0.0.1", port=8787):
    webroot = Path(webroot)
    cache = ProjectionCache()

    def cached_summary(sid, kind):
        """便捷层统一入口：rev 门控 + read。rev 取自 session 行，
        调用前已确保会话存在；缓存的是事件记录，body 组装每请求执行。"""
        meta = ledger.session(sid)
        return cache.get_or_compute(sid, int(meta["last_seq"]), kind,
                                    lambda: ledger.read(sid))

    def summary_response(sid, kind, fn):
        recs = cached_summary(sid, kind)
        return fn(recs)

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
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/health":
                return self._json(200, {"ok": True})
            if path == "/api/runs":
                assigns = ledger.assign_events()
                out = []
                for r in ledger.runs():
                    r["assignment_count"] = sum(
                        1 for a in assigns if a.get("run_id") == r["run_id"])
                    out.append(r)
                return self._json(200, out)
            if path.startswith("/api/runs/"):
                rid = path[len("/api/runs/"):]
                run = ledger.run(rid)
                if run is None:
                    return self._json(404, {"ok": False, "error": "unknown run"})
                run["assignments"] = [
                    a for a in ledger.assign_events() if a.get("run_id") == rid]
                return self._json(200, {"ok": True, **run})
            if path == "/api/sessions":
                return self._json(200, _list_sessions(ledger))
            if path == "/api/annotations":
                return self._json(200, {"ok": True, **ledger.annotations()})
            if path.startswith("/api/sessions/"):
                rest = path[len("/api/sessions/"):]
                sid, _, sub = rest.partition("/")
                qs = parse_qs(parsed.query)
                meta = ledger.session(sid)
                if meta is None:
                    return self._json(404, {"ok": False, "error": "unknown session"})
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
                                return self._json(200, {"ok": True, "unchanged": True,
                                                        "rev": int(meta["last_seq"])})
                        except ValueError:
                            pass
                    recs = ledger.read(sid)
                    page = project_session(sid, meta["agent"], recs, tail=limit, before=before)
                    page["rev"] = int(meta["last_seq"])
                    return self._json(200, page)
                if sub == "events":
                    after = int(qs.get("after_seq", ["0"])[0])
                    limit = min(int(qs.get("limit", ["100"])[0]), 500)
                    picked = [r for r in ledger.read(sid) if r["seq"] > after][:limit]
                    nxt = picked[-1]["seq"] if picked else after
                    return self._json(200, {"ok": True, "events": picked, "next_after_seq": nxt})
                if sub == "lineage":
                    return self._json(200, {"ok": True,
                                            "ancestors": ledger.ancestry(sid),
                                            "children": ledger.children(sid)})
                if sub == "usage":
                    def usage_body(recs):
                        compactions = [{"turn": r["event"].get("turn"), "seq": r["seq"]}
                                       for r in recs if r["event"]["type"] == "compaction.boundary"]
                        return {"ok": True, **summarize_usage(recs),
                                "audit": audit_usage(recs),
                                "compactions": compactions}
                    return self._json(200, summary_response(sid, "usage", usage_body))
                if sub == "tools":
                    full = qs.get("full", ["false"])[0] == "true"
                    def tools_body(recs):
                        rows = list_tools(recs,
                                          qs.get("status", [None])[0],
                                          qs.get("name", [None])[0])
                        for r in rows:
                            r["result"] = r["result"] if full else tail_preview(r["result"])
                        return {"ok": True, "tools": rows}
                    return self._json(200, summary_response(sid, "tools", tools_body))
                if sub == "tool-stats":
                    return self._json(200, summary_response(sid, "tool-stats",
                                                            lambda recs: {"ok": True, **summarize_tools(recs)}))
                if sub == "timing":
                    return self._json(200, summary_response(sid, "timing",
                                                            lambda recs: {"ok": True, **summarize_timing(recs)}))
                if sub == "compactions":
                    full = qs.get("full", ["false"])[0] == "true"
                    rows = list_compactions(ledger.read(sid))
                    for r in rows:
                        r["summary"] = r["summary"] if full else tail_preview(r["summary"])
                    return self._json(200, {"ok": True, "compactions": rows})
                return self._json(404, {"ok": False, "error": "not found"})
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

        def do_POST(self):
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                raw = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            if parsed.path == "/api/pi-hooks":
                return self._ingest_pi_hooks(raw)
            if parsed.path == "/api/runs":
                if not isinstance(raw, dict) or not (raw.get("description") or "").strip():
                    return self._json(400, {"ok": False, "error": "description required"})
                rid = "r-" + uuid.uuid4().hex[:8]
                try:
                    ledger.create_run(rid, raw["description"].strip(),
                                      raw.get("taskset_fingerprint"))
                except ValueError as exc:
                    return self._json(400, {"ok": False, "error": str(exc)})
                return self._json(200, {"ok": True, "run_id": rid})
            # 会话改名：服务端组一个 session.renamed 事件入账本，前端不必自己造 id/ts。
            m = _RE_RENAME.match(parsed.path)
            if m:
                sid = m.group(1)
                title = (raw.get("title") or "").strip() if isinstance(raw, dict) else ""
                if not title:
                    return self._json(400, {"ok": False, "error": "title required"})
                meta = ledger.session(sid)
                if meta is None:
                    return self._json(404, {"ok": False, "error": "unknown session"})
                ev = parse_event(envelope(
                    meta["agent"], sid, "session.renamed", {"title": title}))
                ledger.append(ev)
                return self._json(200, {"ok": True, "title": title})
            m = _RE_RUN_RENAME.match(parsed.path)
            if m:
                name = (raw.get("name") or "").strip() if isinstance(raw, dict) else ""
                # 允许清空：空组名回退显示 run_id
                if not ledger.rename_run(m.group(1), name):
                    return self._json(404, {"ok": False, "error": "unknown run"})
                return self._json(200, {"ok": True, "name": name})
            if parsed.path != "/api/events":
                return self._json(404, {"ok": False, "error": "not found"})
            items = raw.get("events") if isinstance(raw, dict) and "events" in raw else [raw]
            seqs = []
            try:
                for item in items:
                    ev = parse_event(item)
                    print("append %s %s %s" % (ev["type"], ev["id"], ev["session_id"]))
                    seqs.append(ledger.append(ev))
            except (ValidationError, TypeError, ValueError) as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            return self._json(200, {"ok": True, "seq": seqs[-1] if seqs else 0, "seqs": seqs})

        def _ingest_pi_hooks(self, raw):
            if not isinstance(raw, dict) or "name" not in raw:
                return self._json(400, {"ok": False, "error": "hook name required"})
            sid = raw.get("session_id")
            if not sid:
                return self._json(400, {"ok": False, "error": "session_id required"})
            state = getattr(ledger, "_pi_states", None)
            if state is None:
                ledger._pi_states = {}
                state = ledger._pi_states
            bucket = state.setdefault(sid, {"session_id": sid})
            event = raw.get("event") or {}
            # pi 运行时多数 hook 事件不带 timestamp（类型上只有 turn_start 有），
            # 翻译层只能回退 state 里的旧 ts，start/end 会拿到同一时刻、duration
            # 恒 0。hook 按到达序处理即事件序，缺 timestamp 时打上到达时刻。
            if not event.get("timestamp"):
                event = {**event, "timestamp": int(time.time() * 1000)}
            ctx = {
                "session_id": sid,
                "title": raw.get("title") or sid,
                "agent_id": raw.get("agent_id"),
                "host": raw.get("host"),
                "runtime": raw.get("runtime"),
                "channel": raw.get("channel"),
                "lineage": raw.get("lineage") or {},
            }
            try:
                events = translate_hook(raw["name"], event, ctx, bucket)
                seqs = []
                for ev in events:
                    parsed = parse_event(ev)
                    print("append %s %s %s" % (parsed["type"], parsed["id"], parsed["session_id"]))
                    seqs.append(ledger.append(parsed))
            except (ValidationError, TypeError, ValueError) as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            return self._json(200, {"ok": True, "count": len(seqs), "seq": seqs[-1] if seqs else None})

    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def _list_sessions(ledger):
    return ledger.sessions()
