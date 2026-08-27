import tempfile
import time
import unittest
from pathlib import Path

from ata.ledger import Ledger
from ata.plugins.claude import translate_file
from ata.plugins.jsonl import step_tail


def _line(typ, mid, text):
    import json
    return json.dumps({
        "type": typ, "uuid": mid, "sessionId": "tail-sess",
        "timestamp": "2026-08-16T10:00:00Z",
        "message": {"role": "user" if typ == "user" else "assistant", "content": [{"type": "text", "text": text}]},
    }) + "\n"


class JsonlTailTest(unittest.TestCase):
    def test_directory_tail_discovers_new_and_appended_lines(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            state = {}
            # 第一轮：目录里一个文件
            (root / "a.jsonl").write_text(_line("user", "u1", "first"))
            batch1 = step_tail(root, translate_file, led, state)
            self.assertTrue(any(e["type"] == "message.upserted" for e in batch1))
            # 第二轮：既有文件追加 + 新文件出现
            with open(root / "a.jsonl", "a") as f:
                f.write(_line("assistant", "a1", "reply"))
            (root / "b.jsonl").write_text(_line("user", "u2", "second"))
            step_tail(root, translate_file, led, state)
            self.assertEqual(len(led.sessions()), 1)
            events = led.read("tail-sess")
            ev_ids = [r["event"]["id"] for r in events]
            # 幂等账本无重复：opened / turn:1:start / u1 / a1 / u2
            self.assertEqual(len(ev_ids), len(set(ev_ids)))
            self.assertEqual(len(events), 5)
            mids = {r["event"]["payload"]["message_id"] for r in events if r["event"]["type"] == "message.upserted"}
            self.assertEqual(mids, {"u1", "a1", "u2"})

    def test_max_age_days_skips_historical_files(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            state = {}
            new = root / "new.jsonl"
            new.write_text(_line("user", "u-new", "recent"))
            old = root / "old.jsonl"
            old.write_text(_line("user", "u-old", "ancient"))
            past = time.time() - 30 * 86400
            os.utime(old, (past, past))
            step_tail(root, translate_file, led, state, max_age_days=7)
            mids = {r["event"]["payload"]["message_id"] for r in led.read("tail-sess")
                    if r["event"]["type"] == "message.upserted"}
            self.assertEqual(mids, {"u-new"})

    def test_state_persists_across_step_tail_calls(self):
        """跨 step 持久: 同文件分两次 step_tail, assistant turn 字段必须递增。

        模拟 trace 显示异常的根因 #1: 每次 translate_file 都重建 state, turn 累
        加器全丢, 全部 assistant 写 turn=1。本测试期望 step_tail 的 per-file
        桶在两次调用之间保留 turn。
        """
        import json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            state = {}
            f = root / "session.jsonl"
            # 第一批: 2 条 user 消息 → turn=1, turn=2
            with open(f, "w") as fp:
                fp.write(_line("user", "u1", "first user"))
                fp.write(_line("assistant", "a1", "first reply"))
            step_tail(root, translate_file, led, state)
            # 第二批: 追加 1 条 user 消息 → turn 应该是 3 (state 累积)
            with open(f, "a") as fp:
                fp.write(_line("user", "u2", "second user"))
                fp.write(_line("assistant", "a2", "second reply"))
            step_tail(root, translate_file, led, state)
            events = led.read("tail-sess")
            msg_upserts = [r for r in events if r["event"]["type"] == "message.upserted"]
            turns = [r["event"].get("turn") for r in msg_upserts
                     if r["event"]["payload"].get("role") == "assistant"]
            # 两次 step_tail 后, 两条 assistant 的 turn 字段必须递增(不是全 1)
            self.assertEqual(turns, [1, 2], f"assistant turns must increment, got {turns}")
            # user 行 turn 字段也对应: 1, 2
            user_turns = [r["event"].get("turn") for r in msg_upserts
                         if r["event"]["payload"].get("role") == "user"]
            self.assertEqual(user_turns, [1, 2], f"user turns must increment, got {user_turns}")

    def test_same_message_id_multiple_blocks_emit_once(self):
        """同 message_id 跨多 block 行只发一次 message.upserted。

        模拟根因 #2: jsonl 把同 assistant 的 thinking + text + tool_use 拆成多行,
        每行单独 upsert 会后写覆盖前写。本测试期望: 多 block 行合并为单条
        message.upserted, 含全部 texts/thinking。
        """
        import json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            state = {}
            f = root / "multi.jsonl"
            with open(f, "w") as fp:
                # 1 条 user, 3 行同 mid="msg-mixed": thinking + text + tool_use
                fp.write(_line("user", "u-mix", "ask"))
                fp.write(json.dumps({
                    "type": "assistant", "uuid": "asst-line-1", "sessionId": "tail-sess",
                    "timestamp": "2026-08-16T10:00:01Z",
                    "message": {"id": "msg-mixed", "role": "assistant",
                                "content": [{"type": "thinking", "thinking": "let me reason"}]},
                }) + "\n")
                fp.write(json.dumps({
                    "type": "assistant", "uuid": "asst-line-2", "sessionId": "tail-sess",
                    "timestamp": "2026-08-16T10:00:02Z",
                    "message": {"id": "msg-mixed", "role": "assistant",
                                "content": [{"type": "text", "text": "answer text"}]},
                }) + "\n")
                fp.write(json.dumps({
                    "type": "assistant", "uuid": "asst-line-3", "sessionId": "tail-sess",
                    "timestamp": "2026-08-16T10:00:03Z",
                    "message": {"id": "msg-mixed", "role": "assistant",
                                "content": [{"type": "tool_use", "id": "tool-1",
                                             "name": "Read", "input": {"path": "/x"}}]},
                }) + "\n")
            step_tail(root, translate_file, led, state)
            events = led.read("tail-sess")
            msg_upserts = [r for r in events if r["event"]["type"] == "message.upserted"]
            # 用户消息 u-mix + 合并后的 msg-mixed = 2 条
            self.assertEqual(len(msg_upserts), 2, f"expected 2 upserts, got {len(msg_upserts)}")
            mixed = next(r for r in msg_upserts if r["event"]["payload"]["message_id"] == "msg-mixed")
            payload = mixed["event"]["payload"]
            # texts + thinking 都合并进来了
            self.assertIn("answer text", payload["text"])
            self.assertIn("let me reason", (payload.get("thinking") or ""))


if __name__ == "__main__":
    unittest.main()
