from __future__ import annotations

import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ata.plugins.pi import translate_hook
from ata.project import audit_usage, list_compactions, list_tools, project_session, summarize_tools, summarize_usage, tail_preview
from ata.schema import ValidationError, parse_event


def make_server(ledger, webroot, host="127.0.0.1", port=8787):
    webroot = Path(webroot)

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
                    recs = ledger.read(sid)
                    page = project_session(sid, meta["agent"], recs, tail=limit, before=before)
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
                    recs = ledger.read(sid)
                    compactions = [{"turn": r["event"].get("turn"), "seq": r["seq"]}
                                   for r in recs if r["event"]["type"] == "compaction.boundary"]
                    return self._json(200, {"ok": True, **summarize_usage(recs),
                                            "audit": audit_usage(recs),
                                            "compactions": compactions})
                if sub == "tools":
                    full = qs.get("full", ["false"])[0] == "true"
                    rows = list_tools(ledger.read(sid),
                                      qs.get("status", [None])[0],
                                      qs.get("name", [None])[0])
                    for r in rows:
                        r["result"] = r["result"] if full else tail_preview(r["result"])
                    return self._json(200, {"ok": True, "tools": rows})
                if sub == "tool-stats":
                    return self._json(200, {"ok": True,
                                            **summarize_tools(ledger.read(sid))})
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
                    return self._bytes(404, b"missing web/index.html", "text/plain")
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
                events = translate_hook(raw["name"], raw.get("event") or {}, ctx, bucket)
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
