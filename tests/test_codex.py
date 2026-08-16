import unittest
from pathlib import Path

from ata.plugins.codex import translate_file
from ata.project import project_session


class CodexTest(unittest.TestCase):
    def test_maps_verified_types(self):
        evs, _ = translate_file(Path("testdata/vendor/codex-sample.jsonl"))
        types = [e["type"] for e in evs]
        self.assertIn("session.opened", types)
        self.assertIn("system.upserted", types)
        self.assertIn("turn.started", types)
        self.assertIn("message.upserted", types)
        self.assertIn("tool.upserted", types)
        self.assertIn("turn.ended", types)
        self.assertIn("compaction.boundary", types)
        self.assertEqual(sum(1 for e in evs if e["type"] == "message.upserted"), 2)
        asst = next(e for e in evs if e["type"] == "message.upserted" and e["payload"]["role"] == "assistant")
        self.assertEqual(asst["payload"]["model"], "gpt-5")
        self.assertEqual(asst["payload"]["effort"], "high")
        # 标题来自 originator
        titles = [e["payload"]["title"] for e in evs if e["type"] == "session.opened"]
        self.assertEqual(titles[0], "implement the codex adapter")
        # system 快照
        sys = next(e for e in evs if e["type"] == "system.upserted")
        self.assertEqual(sys["payload"]["prompt_text"], "You are Codex, the command line tool for OpenAI.")
        self.assertEqual(sys["payload"]["tools_catalog"], [])
        # 工具 start/end 拆 id
        tools = [e for e in evs if e["type"] == "tool.upserted"]
        self.assertEqual(len(tools), 2)
        self.assertTrue(tools[0]["id"].endswith(":start"))
        self.assertTrue(tools[1]["id"].endswith(":end"))
        self.assertNotEqual(tools[0]["id"], tools[1]["id"])
        # turn.ended 带 reported usage（token_count 对齐）
        ended = next(e for e in evs if e["type"] == "turn.ended")
        self.assertEqual(ended["payload"]["usage"]["status"], "reported")
        self.assertEqual(ended["payload"]["usage"]["cache_read"], 100)
        self.assertEqual(ended["payload"]["usage"]["output"], 120)
        self.assertEqual(ended["payload"]["usage"]["total_tokens"], 650)

    def test_turn_aborted_marks_cancelled(self):
        from ata.plugins.codex import translate_line
        state = {"session_id": "codex-verify"}
        evs = []
        evs += translate_line({"timestamp": "2026-08-16T09:00:00Z", "type": "event_msg",
                               "payload": {"type": "task_started", "turn_id": "t9"}}, state)
        evs += translate_line({"timestamp": "2026-08-16T09:00:01Z", "type": "response_item",
                               "payload": {"type": "message", "role": "assistant", "id": "ax",
                                           "content": [{"type": "output_text", "text": "partial"}]}}, state)
        evs += translate_line({"timestamp": "2026-08-16T09:00:02Z", "type": "event_msg",
                               "payload": {"type": "turn_aborted", "turn_id": "t9", "reason": "interrupted"}}, state)
        recs = [{"seq": i + 1, "event": e} for i, e in enumerate(evs)]
        sess = project_session("codex-verify", "codex", recs)
        asst = next(r for r in sess["rows"] if r["kind"] == "assistant")
        self.assertEqual(asst["status"], "cancelled")

    def test_zero_usage_is_missing(self):
        from ata.plugins.codex import _usage
        missing = _usage({"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
                          "cache_write_input_tokens": 0, "total_tokens": 0})
        self.assertEqual(missing["status"], "missing")
        self.assertIsNone(missing["input"])

    def test_projection(self):
        evs, _ = translate_file(Path("testdata/vendor/codex-sample.jsonl"))
        recs = [{"seq": i + 1, "event": e} for i, e in enumerate(evs)]
        sess = project_session("codex-verify", "codex", recs)
        self.assertEqual(sess["title"], "implement the codex adapter")
        kinds = [r["kind"] for r in sess["rows"]]
        self.assertEqual(kinds, ["system", "user", "assistant", "tool", "compacted"])
        tool = next(r for r in sess["rows"] if r["kind"] == "tool")
        self.assertEqual(tool["status"], "completed")
        self.assertEqual(tool["result"], "fixture\n")
        self.assertEqual(tool["parentId"], "m2")
        self.assertEqual(tool["payload"], {"command": "ls"})
        asst = next(r for r in sess["rows"] if r["kind"] == "assistant")
        self.assertEqual(asst["usage"]["status"], "reported")
        self.assertEqual(asst["usage"]["cacheRead"], 100)
        self.assertEqual(asst["model"], "gpt-5")
        self.assertEqual(asst["effort"], "high")
        self.assertEqual(sess["turns"], 1)
        self.assertEqual(sess["rows"][-1]["kind"], "compacted")


if __name__ == "__main__":
    unittest.main()
