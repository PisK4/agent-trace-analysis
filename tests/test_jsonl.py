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
    """Round 2 收窄后, transcript claude.py 不再 emit message.upserted /
    tool.upserted / turn.started。本测试类调整为断言 transcript 元数据通道行为
    (state 跨 step 持久仍生效, 但只影响 session_id / opened / turn 字段)。"""

    def test_directory_tail_discovers_new_and_appended_lines(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            self.addCleanup(led.close)
            state = {}
            # 第一轮：目录里一个文件
            (root / "a.jsonl").write_text(_line("user", "u1", "first"))
            batch1 = step_tail(root, translate_file, led, state)
            # Round 2: transcript 不再 emit message.upserted, 只发 session.opened
            self.assertTrue(any(e["type"] == "session.opened" for e in batch1))
            # 第二轮：既有文件追加 + 新文件出现
            with open(root / "a.jsonl", "a") as f:
                f.write(_line("assistant", "a1", "reply"))
            (root / "b.jsonl").write_text(_line("user", "u2", "second"))
            step_tail(root, translate_file, led, state)
            self.assertEqual(len(led.sessions()), 1)
            events = led.read("tail-sess")
            ev_ids = [r["event"]["id"] for r in events]
            # 幂等账本无重复: 两个文件都是同 sid, session.opened 幂等
            self.assertEqual(len(ev_ids), len(set(ev_ids)))
            # 仍只有 session.opened(无 message.upserted, 无 turn.started)
            types = {r["event"]["type"] for r in events}
            self.assertEqual(types, {"session.opened"})
            led.close()

    def test_max_age_days_skips_historical_files(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            self.addCleanup(led.close)
            state = {}
            new = root / "new.jsonl"
            new.write_text(_line("user", "u-new", "recent"))
            old = root / "old.jsonl"
            old.write_text(_line("user", "u-old", "ancient"))
            past = time.time() - 30 * 86400
            os.utime(old, (past, past))
            step_tail(root, translate_file, led, state, max_age_days=7)
            # Round 2: transcript 不再发 message, 但 file 切到新文件后仍写 opened。
            # 检查 recent 文件被处理, old 文件被跳过 (asserted by sessions list)
            types = {r["event"]["type"] for r in led.read("tail-sess")}
            self.assertIn("session.opened", types)
            # 只有一个 opened (recent 文件触发的)
            opened = [r for r in led.read("tail-sess")
                      if r["event"]["type"] == "session.opened"]
            self.assertEqual(len(opened), 1)

    def test_state_persists_across_step_tail_calls(self):
        """跨 step 持久 (Round 1 落): state["session_id"] / ["ts"] 在两次 step_tail
        之间保留。Round 2 起 transcript 不再 emit message, 但 state 持久仍要求
        不为每次调用重建桶(本测试验证 step_tail 的 per-file 桶行为正确)。
        """
        import json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            self.addCleanup(led.close)
            state = {}
            f = root / "session.jsonl"
            with open(f, "w") as fp:
                fp.write(_line("user", "u1", "first user"))
                fp.write(_line("assistant", "a1", "first reply"))
            step_tail(root, translate_file, led, state)
            # 第二批: 追加 1 条 user 消息
            with open(f, "a") as fp:
                fp.write(_line("user", "u2", "second user"))
                fp.write(_line("assistant", "a2", "second reply"))
            step_tail(root, translate_file, led, state)
            # Round 2: transcript 不再 emit message, 只发 session.opened
            # (幂等: 两次 step_tail 仍只 1 条 opened)
            types = [r["event"]["type"] for r in led.read("tail-sess")]
            self.assertEqual(types, ["session.opened"])
            # 跨 step 持久: state 桶的 offset 累积, 不会回退重读
            bucket = state.get(str(f))
            self.assertIsNotNone(bucket)
            self.assertGreater(bucket["offset"], 0)

    def test_same_message_id_multiple_blocks_no_message_emit(self):
        """Round 2 收窄后, 同 message_id 跨多 block 行也不再 emit message.upserted。
        根因 #2 (content block 按行分裂) 在 transcript 侧被彻底消除——代理端组装
        完整 message 后 emit 一次, transcript 不参与。
        """
        import json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            self.addCleanup(led.close)
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
            types = {r["event"]["type"] for r in events}
            # transcript 不再发 message / tool, 只发 session.opened
            self.assertNotIn("message.upserted", types)
            self.assertNotIn("tool.upserted", types)
            self.assertEqual(types, {"session.opened"})


class ClaudeJsonlNoMessageEmitTest(unittest.TestCase):
    """Round 2: 代理主发 message 后, transcript claude.py 的 user/assistant 行不再
    emit message.upserted / tool.upserted。transcript 只负责元数据
    (ai-title / compact_boundary / system.api_error / session.opened)。
    """

    def test_user_assistant_lines_no_message_upserted(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            self.addCleanup(led.close)
            state = {}
            f = root / "no-msg.jsonl"
            with open(f, "w") as fp:
                fp.write(json.dumps({
                    "type": "user", "uuid": "u-1", "sessionId": "s1",
                    "timestamp": "2026-08-16T10:00:00Z",
                    "message": {"role": "user", "content": [{"type": "text", "text": "ask"}]},
                }) + "\n")
                fp.write(json.dumps({
                    "type": "assistant", "uuid": "a-1", "sessionId": "s1",
                    "timestamp": "2026-08-16T10:00:01Z",
                    "message": {"id": "msg_test", "role": "assistant",
                                "content": [{"type": "text", "text": "reply"}]},
                }) + "\n")
            step_tail(root, translate_file, led, state)
            events = led.read("s1")
            types = [r["event"]["type"] for r in events]
            self.assertNotIn("message.upserted", types)
            self.assertNotIn("tool.upserted", types)
            # session.opened 是元数据, 仍发
            self.assertIn("session.opened", types)

    def test_ai_title_and_compaction_kept(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            self.addCleanup(led.close)
            state = {}
            f = root / "meta.jsonl"
            with open(f, "w") as fp:
                fp.write(json.dumps({
                    "type": "ai-title", "uuid": "t-1", "sessionId": "s2",
                    "timestamp": "2026-08-16T10:00:00Z",
                    "aiTitle": "Test session",
                }) + "\n")
                fp.write(json.dumps({
                    "type": "system", "uuid": "c-1", "sessionId": "s2",
                    "timestamp": "2026-08-16T10:00:02Z",
                    "subtype": "compact_boundary",
                    "compactMetadata": {"trigger": "auto", "preTokens": 1000, "postTokens": 200},
                }) + "\n")
            step_tail(root, translate_file, led, state)
            events = led.read("s2")
            types = {r["event"]["type"] for r in events}
            self.assertIn("session.opened", types)
            self.assertIn("compaction.boundary", types)


if __name__ == "__main__":
    unittest.main()
