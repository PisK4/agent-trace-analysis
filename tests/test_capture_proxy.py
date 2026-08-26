import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from ata.capture_proxy import start_capture_proxy
from ata.ledger import Ledger


UPSTREAM_RESP = {
    "id": "msg_01", "type": "message", "role": "assistant",
    "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


#: 假上游收到的头（模块级，测试断言转发侧契约用）。
SEEN_HEADERS = {}


def make_upstream(responses):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            SEEN_HEADERS.update(
                {k.lower(): v for k, v in self.headers.items()})
            body = json.dumps(responses[0]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    return srv


class CaptureProxyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name))
        self.upstream = make_upstream([UPSTREAM_RESP])
        self.upstream_port = self.upstream.server_address[1]
        # 假上游必须真跑起来：只 bind 不 accept 会让代理连接进 backlog 挂死。
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()

    def tearDown(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        self.tmp.cleanup()

    def _wait_ledger(self, sid, timeout=5.0):
        # ingest 在响应回传完成后才执行，客户端读到响应时账本可能还没落；
        # 轮询等一小会儿（采集是异步收尾，不是响应的一部分）。
        deadline = time.time() + timeout
        while time.time() < deadline:
            recs = self.ledger.read(sid)
            if recs:
                return recs
            time.sleep(0.05)
        return []

    def _start_proxy(self):
        from ata.plugins.capture import ingest_capture

        httpd = start_capture_proxy(
            "127.0.0.1", 0, f"http://127.0.0.1:{self.upstream_port}",
            "claude", lambda rec: ingest_capture(self.ledger, rec))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        return port

    def test_end_to_end_events_land_in_ledger(self):
        port = self._start_proxy()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/messages",
            data=json.dumps({
                "model": "claude-sonnet-5",
                "system": [{"type": "text", "text": "You are ATA."}],
                "messages": [{"role": "user",
                              "content": [{"type": "text", "text": "hi"}]}],
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json",
                     "x-claude-code-session-id": "prox-1",
                     "x-api-key": "sk-secret-must-not-leak"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("hello", resp.read().decode())
        recs = self._wait_ledger("prox-1")
        types = sorted(r["event"]["type"] for r in recs)
        # 转发侧契约：认证头必须能到上游（上游网关靠它鉴权）；
        # 落档侧红线：认证头不进 record（sk-secret 断言在下方）。
        self.assertEqual(SEEN_HEADERS.get("x-api-key"),
                         "sk-secret-must-not-leak")
        self.assertEqual(types, ["system.upserted", "turn.ended"])
        dumped = json.dumps(recs)
        self.assertNotIn("sk-secret", dumped)

    def test_no_session_header_still_proxies(self):
        port = self._start_proxy()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/messages",
            data=json.dumps({"messages": []}).encode(), method="POST")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)  # 代理照常工作
        self.assertEqual(self.ledger.sessions(), [])  # 只是不采集


if __name__ == "__main__":
    unittest.main()
