import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from ata import capture_proxy
from ata.capture_proxy import start_capture_proxy
from ata.ledger import Ledger
from ata.plugins.capture import resolve_session_id


UPSTREAM_RESP = {
    "id": "msg_01", "type": "message", "role": "assistant",
    "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


CODEX_UPSTREAM_RESP = {
    "id": "resp-proxy-codex-1",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "proxy answer"}],
        },
        {
            "type": "function_call",
            "id": "fc-proxy-codex-1",
            "call_id": "call-proxy-codex-1",
            "name": "Read",
            "arguments": '{"path":"README.md"}',
        },
    ],
    "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
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
        self.ledger.close()
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
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def close_proxy():
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        self.addCleanup(close_proxy)
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
        # Round 2: 代理主发 message.upserted (user + assistant)。
        self.assertEqual(SEEN_HEADERS.get("x-api-key"),
                         "sk-secret-must-not-leak")
        self.assertEqual(types,
                         ["message.upserted", "message.upserted",
                          "system.upserted", "turn.ended"])
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


class VirtualSidTest(unittest.TestCase):
    def setUp(self):
        # 测试间清空模块级 cache + lock
        with capture_proxy._virtual_sid_lock:
            capture_proxy._virtual_sid_cache.clear()

    def test_same_client_port_within_window_reuses_sid(self):
        # 同一 client_port 在 5min 内复用同一 sid
        t0 = 1_700_000_000_000
        a = capture_proxy._virtual_sid("droid", 52345, t0)
        b = capture_proxy._virtual_sid("droid", 52345, t0 + 60_000)  # 1min 后
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("droid-wire-52345-"))

    def test_different_client_port_gets_different_sid(self):
        # 不同 client_port → 不同 sid
        t0 = 1_700_000_000_000
        a = capture_proxy._virtual_sid("droid", 52345, t0)
        b = capture_proxy._virtual_sid("droid", 52346, t0)  # 同一时刻不同 port
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("droid-wire-52345-"))
        self.assertTrue(b.startswith("droid-wire-52346-"))

    def test_window_exceeded_yields_new_sid(self):
        # 跨 5min 窗口拿新 sid
        t0 = 1_700_000_000_000
        a = capture_proxy._virtual_sid("droid", 52345, t0)
        b = capture_proxy._virtual_sid(
            "droid", 52345, t0 + capture_proxy._VIRTUAL_SID_WINDOW_MS + 1)
        self.assertNotEqual(a, b)
        # 边界: b 之后 c 在窗口内仍复用最近一次 (b) 的 sid
        c = capture_proxy._virtual_sid(
            "droid", 52345, t0 + capture_proxy._VIRTUAL_SID_WINDOW_MS)
        self.assertEqual(b, c)

    def test_sid_format_stable(self):
        # sid 格式: {agent}-wire-{port}-{8hex}
        sid = capture_proxy._virtual_sid("droid", 12345, 1_700_000_000_000)
        parts = sid.split("-")
        # "droid-wire-12345-abcd1234" → 4 段
        self.assertEqual(parts[0], "droid")
        self.assertEqual(parts[1], "wire")
        self.assertEqual(parts[2], "12345")
        self.assertEqual(len(parts[3]), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in parts[3]))

    def test_resolve_session_id_prefers_caller_injected(self):
        # caller 注入的 sid 优先于 headers/body 解析
        rec = {
            "session_id": "droid-wire-52345-abcd1234",
            "request_headers": {"x-droid-session-id": "should-be-ignored"},
            "request_body": b'{"metadata": {"session_id": "should-be-ignored-too"}}',
        }
        self.assertEqual(
            resolve_session_id(rec, "droid"),
            "droid-wire-52345-abcd1234")

    def test_resolve_session_id_falls_back_when_no_injection(self):
        # 没注入时仍走原 headers/body 路径
        rec = {
            "request_headers": {"x-claude-code-session-id": "real-sid"},
            "request_body": b'{}',
        }
        self.assertEqual(resolve_session_id(rec, "claude"), "real-sid")
        # claude 不在 _VIRTUAL_SID_AGENTS, 走原解析


class NeedsVirtualSidTest(unittest.TestCase):
    """path-触发的兜底判断: 代理壳不知道发起方是哪个 host, 只能按 path
    推测。 任何走到 /v1/chat/completions 或 /v1/responses 的请求都触发
    虚拟 sid 注入(无论 agent_id 是 claude 还是 droid / codex)。
    """

    def test_chat_completions_triggers(self):
        self.assertTrue(capture_proxy._needs_virtual_sid("/v1/chat/completions"))

    def test_responses_triggers(self):
        self.assertTrue(capture_proxy._needs_virtual_sid("/v1/responses"))

    def test_backend_api_codex_responses_triggers(self):
        self.assertTrue(
            capture_proxy._needs_virtual_sid(
                "/backend-api/codex/responses"
            )
        )

    def test_claude_messages_does_not_trigger(self):
        # claude 走 /v1/messages, 由 headers 提供 sid, 不需要兜底
        self.assertFalse(capture_proxy._needs_virtual_sid("/v1/messages"))

    def test_query_string_ignored(self):
        self.assertTrue(capture_proxy._needs_virtual_sid(
            "/v1/chat/completions?stream=true"))

    def test_trailing_slash_ignored(self):
        self.assertTrue(capture_proxy._needs_virtual_sid("/v1/chat/completions/"))

    def test_empty_path_returns_false(self):
        self.assertFalse(capture_proxy._needs_virtual_sid(""))
        self.assertFalse(capture_proxy._needs_virtual_sid(None))


class CodexCaptureProxyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name))
        self.upstream = make_upstream([CODEX_UPSTREAM_RESP])
        self.upstream_port = self.upstream.server_address[1]
        threading.Thread(
            target=self.upstream.serve_forever,
            daemon=True,
        ).start()
        with capture_proxy._virtual_sid_lock:
            capture_proxy._virtual_sid_cache.clear()

        from ata.plugins.capture import ingest_capture

        self.proxy = start_capture_proxy(
            "127.0.0.1",
            0,
            f"http://127.0.0.1:{self.upstream_port}",
            "codex",
            lambda record: ingest_capture(self.ledger, record),
        )
        self.proxy_thread = threading.Thread(
            target=self.proxy.serve_forever,
            daemon=True,
        )
        self.proxy_thread.start()

    def tearDown(self):
        self.proxy.shutdown()
        self.proxy.server_close()
        self.proxy_thread.join(timeout=2)
        self.upstream.shutdown()
        self.upstream.server_close()
        self.ledger.close()
        self.tmp.cleanup()
        with capture_proxy._virtual_sid_lock:
            capture_proxy._virtual_sid_cache.clear()

    def _post(self, body):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.proxy.server_address[1]}/v1/responses",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-secret",
            },
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            response.read()

    def _wait_records(self, sid, predicate=None, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            records = self.ledger.read(sid)
            if records and (predicate is None or predicate(records)):
                return records
            time.sleep(0.05)
        return self.ledger.read(sid)

    def test_codex_responses_lands_in_body_session_and_completes_tool(self):
        request = {
            "model": "gpt-5",
            "instructions": "You are Codex.",
            "metadata": {"session_id": "codex-proxy-session"},
            "input": [{
                "role": "user",
                "content": [{"type": "input_text", "text": "read README"}],
            }],
        }
        self._post(request)
        first = self._wait_records("codex-proxy-session")
        self.assertTrue(first)
        first_types = [record["event"]["type"] for record in first]
        self.assertIn("system.upserted", first_types)
        self.assertIn("message.upserted", first_types)
        self.assertIn("turn.ended", first_types)
        assistant = next(
            record["event"] for record in first
            if record["event"]["type"] == "message.upserted"
            and record["event"]["payload"]["role"] == "assistant"
        )
        self.assertEqual(assistant["payload"]["text"], "proxy answer")

        self._post({
            **request,
            "input": [
                *request["input"],
                {
                    "type": "function_call_output",
                    "call_id": "call-proxy-codex-1",
                    "output": "README contents",
                },
            ],
        })
        records = self._wait_records(
            "codex-proxy-session",
            predicate=lambda rows: any(
                row["event"]["type"] == "tool.upserted"
                and row["event"]["id"].endswith(":end")
                for row in rows
            ),
        )
        ended = [
            record["event"] for record in records
            if record["event"]["type"] == "tool.upserted"
            and record["event"]["id"].endswith(":end")
        ]
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0]["payload"]["result"], "README contents")
        self.assertNotIn("test-secret", json.dumps(records))

    def test_codex_without_body_session_uses_explicit_wire_only_sid(self):
        self._post({
            "model": "gpt-5",
            "input": [{
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            }],
        })
        deadline = time.time() + 5
        sessions = []
        while time.time() < deadline:
            sessions = self.ledger.sessions()
            if sessions:
                break
            time.sleep(0.05)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0]["id"].startswith("codex-wire-"))


class OpenAIProxyPathTest(unittest.TestCase):
    """集成验证: 代理壳跑起来, 发到 /v1/chat/completions 的无 sid 请求
    应该走虚拟 sid 兜底, 事件落账; /v1/messages 没 sid 时按原逻辑不采集。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name))
        self.upstream = make_upstream([UPSTREAM_RESP])
        self.upstream_port = self.upstream.server_address[1]
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        # 清虚拟 sid cache 避免跨测试污染
        with capture_proxy._virtual_sid_lock:
            capture_proxy._virtual_sid_cache.clear()

    def tearDown(self):
        self.upstream.shutdown()
        self.upstream.server_address  # noqa
        self.upstream.server_close()
        self.ledger.close()
        self.tmp.cleanup()
        with capture_proxy._virtual_sid_lock:
            capture_proxy._virtual_sid_cache.clear()

    def _start_proxy(self):
        from ata.plugins.capture import ingest_capture

        httpd = start_capture_proxy(
            "127.0.0.1", 0, f"http://127.0.0.1:{self.upstream_port}",
            "claude", lambda rec: ingest_capture(self.ledger, rec))
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def close_proxy():
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        self.addCleanup(close_proxy)
        return port

    def test_openai_path_injects_virtual_sid_and_lands_events(self):
        port = self._start_proxy()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({
                "model": "claude-sonnet-5",
                "messages": [{"role": "user", "content": "hi"}],
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
        # 等虚拟 sid 注入的 record 落账 (≤5s)
        deadline = time.time() + 5
        sids = []
        while time.time() < deadline:
            sids = self.ledger.sessions()
            if sids:
                break
            time.sleep(0.05)
        self.assertEqual(len(sids), 1, f"expected 1 session, got {sids}")
        virtual_sid = sids[0]["id"]
        self.assertTrue(
            virtual_sid.startswith("claude-wire-"),
            f"unexpected sid format: {virtual_sid}")
        recs = self.ledger.read(virtual_sid)
        types = sorted(r["event"]["type"] for r in recs)
        self.assertIn("turn.ended", types)

    def test_claude_path_without_sid_still_drops(self):
        # /v1/messages 没有 x-claude-code-session-id → 仍按原契约不采集
        port = self._start_proxy()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/messages",
            data=json.dumps({"messages": []}).encode(),
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
        time.sleep(0.3)  # 给 ingest 一点时间跑(它会抛错被吞)
        self.assertEqual(self.ledger.sessions(), [])


if __name__ == "__main__":
    unittest.main()
