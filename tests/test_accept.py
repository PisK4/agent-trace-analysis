import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger
from ata.plugins.droid import translate_file
from ata.plugins.pi import translate_hook
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
            httpd = make_server(led, Path("web"), "127.0.0.1", 0)
            th = threading.Thread(target=httpd.serve_forever, daemon=True)
            th.start()
            port = httpd.server_port
            try:
                hooks = json.loads(Path("testdata/vendor/pi-hooks.json").read_text())
                state = {}
                for h in hooks:
                    for ev in translate_hook(h["name"], h["event"], h.get("ctx") or {}, state):
                        post(port, parse_event(ev))
                evs, _ = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
                for ev in evs:
                    post(port, parse_event(ev))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions") as r:
                    listing = json.loads(r.read().decode())
                ids = {x["id"] for x in listing}
                self.assertIn("pi-compact", ids)
                self.assertIn("droid-missing", ids)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions/droid-missing") as r:
                    droid = json.loads(r.read().decode())
                asst = next(x for x in droid["rows"] if x["kind"] == "assistant")
                self.assertEqual(asst["usage"]["status"], "missing")
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r:
                    html = r.read().decode()
                self.assertIn("Atatrace", html)
                self.assertIn("/api/sessions", html)
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
