import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger
from ata.plugins.droid import translate_file
from ata.schema import parse_event


def post(port, ev):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/events",
        data=json.dumps(ev).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


class AcceptTest(unittest.TestCase):
    def test_vendor_to_ui_json(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            httpd = make_server(led, Path("web/dist"), "127.0.0.1", 0)
            th = threading.Thread(target=httpd.serve_forever, daemon=True)
            th.start()
            port = httpd.server_port
            try:
                hooks = json.loads(Path("testdata/vendor/pi-hooks.json").read_text())
                for h in hooks:
                    body = {
                        "name": h["name"],
                        "session_id": (h.get("ctx") or {}).get("session_id") or "pi-compact",
                        "title": (h.get("ctx") or {}).get("title") or "synthetic pi turn",
                        "event": h["event"],
                    }
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/pi-hooks",
                        data=json.dumps(body).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req) as r:
                        self.assertTrue(json.loads(r.read().decode())["ok"])
                evs, _ = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
                for ev in evs:
                    post(port, parse_event(ev))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions") as r:
                    listing = json.loads(r.read().decode())
                ids = {x["id"] for x in listing}
                self.assertIn("pi-compact", ids)
                self.assertIn("droid-missing", ids)
                listed = next(x for x in listing if x["id"] == "pi-compact")
                self.assertEqual(listed["title"], "ask about usage")
                self.assertEqual(listed["turns"], 2)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions/droid-missing") as r:
                    droid = json.loads(r.read().decode())
                asst = next(x for x in droid["rows"] if x["kind"] == "assistant")
                self.assertEqual(asst["usage"]["status"], "missing")
            finally:
                httpd.shutdown()

    # web/dist 是构建产物不入库（见 .gitignore）；fresh clone 上跳过而非红，
    # 构建方式在 skip 理由里给出。
    @unittest.skipUnless(
        Path("web/dist/index.html").exists(),
        "web/dist 未构建（cd webapp && npm run build）",
    )
    def test_static_serves_react_dist(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            httpd = make_server(led, Path("web/dist"), "127.0.0.1", 0)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/") as r:
                    html = r.read().decode()
                self.assertIn("<!doctype html>", html.lower())
                # React 版（webapp build 产物）是唯一前端；静态分支伺服 dist 产物
                self.assertIn("/assets/", html)
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
