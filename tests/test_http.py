import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        led = Ledger(root)
        led.append({
            "v":1,"id":"o","agent_id":"droid","session_id":"droid-missing","ts":1,
            "type":"session.opened","turn":None,"payload":{"title":"missing"},
        })
        led.append({
            "v":1,"id":"a","agent_id":"droid","session_id":"droid-missing","ts":2,
            "type":"message.upserted","turn":1,"payload":{
                "message_id":"a1","role":"assistant","text":"x","status":"completed",
                "request_no":1,"usage":None,"started_at":2,"duration_ms":1,"output_text":"x"},
        })
        self.httpd = make_server(led, webroot=Path("web"), host="127.0.0.1", port=0)
        self.port = self.httpd.server_port
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.td.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read().decode())

    def test_missing_usage(self):
        data = self.get("/api/sessions/droid-missing")
        self.assertEqual(data["rows"][0]["usage"]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
