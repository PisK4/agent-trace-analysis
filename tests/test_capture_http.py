import base64
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger


REQ1 = {
    "model": "claude-sonnet-5",
    "system": [{"type": "text", "text": "You are ATA."}],
    "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
}
RESP1 = {
    "id": "msg_01", "type": "message", "role": "assistant",
    "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


class CaptureHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name))
        self.httpd = make_server(self.ledger, Path(self.tmp.name), "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.tmp.cleanup()

    def post(self, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/captures",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_ingest_via_http(self):
        payload = {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": "sess-9"},
            "request_body": base64.b64encode(json.dumps(REQ1).encode()).decode(),
            "response_content_type": "application/json",
            "response_body": base64.b64encode(json.dumps(RESP1).encode()).decode(),
            "started_at_ms": 1000, "completed_at_ms": 1900,
        }
        status, body = self.post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["ok"], True)
        # Round 2: 代理主发 message.upserted (user + assistant), count 从 2 变 4。
        self.assertEqual(body["count"], 4)
        recs = self.ledger.read("sess-9")
        self.assertEqual(sorted(r["event"]["type"] for r in recs),
                         ["message.upserted", "message.upserted",
                          "system.upserted", "turn.ended"])

    def test_missing_session_header_is_400(self):
        payload = {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {},
            "request_body": base64.b64encode(json.dumps(REQ1).encode()).decode(),
            "response_content_type": "application/json",
            "response_body": base64.b64encode(json.dumps(RESP1).encode()).decode(),
            "started_at_ms": 1000, "completed_at_ms": 1900,
        }
        status, body = self.post(payload)
        self.assertEqual(status, 400)
        self.assertIn("session", body["error"])


if __name__ == "__main__":
    unittest.main()
