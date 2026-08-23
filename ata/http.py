from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ata.plugins.pi import translate_hook
from ata.project import project_session
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
            if path == "/api/sessions":
                return self._json(200, _list_sessions(ledger))
            if path.startswith("/api/sessions/"):
                sid = path[len("/api/sessions/"):]
                qs = parse_qs(parsed.query)
                limit = int(qs.get("limit", ["80"])[0])
                before = qs.get("before", [None])[0]
                before = int(before) if before not in (None, "") else None
                meta = ledger.session(sid)
                if meta is None:
                    return self._json(404, {"ok": False, "error": "unknown session"})
                recs = ledger.read(sid)
                page = project_session(sid, meta["agent"], recs, tail=limit, before=before)
                return self._json(200, page)
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
