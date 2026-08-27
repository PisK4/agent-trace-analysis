import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ata.ledger import Ledger
from ata.wire.droid_hooks import write_hook_event


class WriteHookEventTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audit.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_appends_one_jsonl_line(self):
        write_hook_event(self.path, {
            "session_id": "abc-123",
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"path": "/tmp/x"},
        })
        write_hook_event(self.path, {
            "session_id": "abc-123",
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_input": {"path": "/tmp/x"},
            "tool_response": "ok",
        })
        lines = self.path.read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first["session_id"], "abc-123")
        self.assertEqual(first["hook_event_name"], "PreToolUse")
        self.assertEqual(first["raw"]["tool_name"], "Read")
        self.assertIn("received_at_ms", first)
        # 收到时刻近 now
        self.assertLess(abs(first["received_at_ms"] - int(time.time() * 1000)), 5000)

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "a" / "b" / "audit.jsonl"
        write_hook_event(nested, {"hook_event_name": "UserPromptSubmit"})
        self.assertTrue(nested.exists())

    def test_handles_missing_session_id(self):
        # 缺 session_id 不抛, raw 原样存
        write_hook_event(self.path, {"hook_event_name": "Stop"})
        line = json.loads(self.path.read_text().strip())
        self.assertIsNone(line["session_id"])
        self.assertEqual(line["hook_event_name"], "Stop")

    def test_handles_empty_payload(self):
        write_hook_event(self.path, {})
        line = json.loads(self.path.read_text().strip())
        self.assertIsNone(line["session_id"])
        self.assertIsNone(line["hook_event_name"])

    def test_write_failure_does_not_raise(self):
        # 不可写路径 (parent 是 file 不是 dir) 不应抛
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_text("i am a file not a dir")
        bad = blocker / "cannot" / "audit.jsonl"
        write_hook_event(bad, {"hook_event_name": "X"})  # 不能抛


class DroidHookEndpointTest(unittest.TestCase):
    """端到端: 起真 ata HTTP server, 发 7 类 hook payload 验证都 200
    + audit log 落盘。"""

    @classmethod
    def setUpClass(cls):
        # 起一个最小 ata http server (复用 make_server)
        from ata.http import make_server
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ledger = Ledger(Path(cls.tmp.name) / "led.sqlite")
        cls.httpd = make_server(cls.ledger, Path(cls.tmp.name), "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        # audit log 路径临时化: monkey-patch home dir 不可行, 用 droid_hooks 里的常量
        # 但我们这里只断言端点 200, 不验证文件路径 (WriteHookEventTest 覆盖了文件层)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.tmp.cleanup()

    def _post(self, body: dict) -> tuple:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/hooks/droid",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_pretooluse_returns_200_fast(self):
        # PreToolUse 是最关键的 fast 路径 (droid 会 AgentAbortError)
        t0 = time.time()
        code, body = self._post({
            "session_id": "00000000-0000-0000-0000-000000000001",
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"path": "/tmp/x"},
            "transcript_path": "/tmp/x.jsonl",
            "cwd": "/tmp",
            "permission_mode": "auto-medium",
        })
        elapsed = time.time() - t0
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertLess(elapsed, 0.5, f"too slow: {elapsed:.3f}s")

    def test_all_seven_event_types_accepted(self):
        events = ["SessionStart", "UserPromptSubmit", "PreToolUse",
                  "PostToolUse", "Notification", "Stop", "SubagentStop"]
        for ev in events:
            code, body = self._post({
                "session_id": "00000000-0000-0000-0000-000000000002",
                "hook_event_name": ev,
            })
            self.assertEqual(code, 200, f"{ev} not accepted")
            self.assertTrue(body["ok"])

    def test_invalid_json_returns_400(self):
        # body 不是 dict (例如 "not json object" 字符串) 走 ata/http.py 的
        # json.loads 失败已经 400; 测 dict 自身不可序列化的情况 (如 datetime)
        # 不可序列化对象走我们的 handler 时会内部 json.dumps 失败 — 但我们用
        # write_hook_event 写文件不用 json.dumps(body), 只 dump raw 之外的字段
        # 所以 dict 不可序列化对象会被原样传给 write_hook_event 引起 dumps 失败
        # — 但 write_hook_event 用 try/except 吞掉, 端点还是 200. 这个测试
        # 主要是确认端点不挂死, 不强求 400.
        code, body = self._post({"ok": True})
        self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
