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
        self.led = Ledger(root)
        led = self.led
        led.append({
            "v":1,"id":"o","agent_id":"droid","session_id":"droid-missing","ts":1,
            "type":"session.opened","observed_turn_ordinal":None,"payload":{"title":"missing"},
        })
        led.append({
            "v":1,"id":"a","agent_id":"droid","session_id":"droid-missing","ts":2,
            "type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"a1","role":"assistant","text":"x","status":"completed",
                "request_no":1,"usage":None,"started_at":2,"duration_ms":1,"output_text":"x"},
        })
        self.httpd = make_server(led, webroot=Path("web"), host="127.0.0.1", port=0)
        self.port = self.httpd.server_port
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.th.join(timeout=2)
        self.led.close()
        self.td.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read().decode())

    def test_missing_usage(self):
        data = self.get("/api/sessions/droid-missing")
        self.assertEqual(data["rows"][0]["usage"]["status"], "missing")

    def test_unknown_session_is_404(self):
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get("/api/sessions/nope")
            self.assertEqual(ctx.exception.code, 404)
        finally:
            ctx.exception.close()

    def test_list_includes_last_ts(self):
        data = self.get("/api/sessions")
        self.assertEqual(data[0]["id"], "droid-missing")
        self.assertEqual(data[0]["last_ts"], 2)


if __name__ == "__main__":
    unittest.main()
