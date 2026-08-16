import unittest
from pathlib import Path

from ata.plugins.claude import translate_file
from ata.project import project_session


class ClaudeTest(unittest.TestCase):
    def test_maps_verified_types(self):
        evs, _ = translate_file(Path("testdata/vendor/claude-sample.jsonl"))
        types = [e["type"] for e in evs]
        self.assertIn("session.opened", types)
        self.assertIn("turn.started", types)
        self.assertIn("message.upserted", types)
        self.assertIn("tool.upserted", types)
        self.assertNotIn("system.upserted", types)
        self.assertNotIn("turn.ended", types)
        # title 被 ai-title 覆盖
        titles = [e["payload"]["title"] for e in evs if e["type"] == "session.opened"]
        self.assertEqual(titles[-1], "claude fixture title")
        # 5 条消息：u1 / a1 / a2 / u3 / api_error（u2 是 tool_result-only，不算新轮不产消息行）
        msgs = [e for e in evs if e["type"] == "message.upserted"]
        self.assertEqual(len(msgs), 5)
        self.assertEqual(msgs[2]["payload"]["message_id"], "msg-a2")
        # 工具 start/end 拆 id
        tools = [e for e in evs if e["type"] == "tool.upserted"]
        self.assertEqual(len(tools), 2)
        self.assertTrue(tools[0]["id"].endswith(":start"))
        self.assertTrue(tools[1]["id"].endswith(":end"))
        self.assertNotEqual(tools[0]["id"], tools[1]["id"])
        # usage 驼峰 → ATA 蛇形
        asst = next(e for e in evs if e["type"] == "message.upserted" and e["payload"]["role"] == "assistant")
        self.assertEqual(asst["payload"]["usage"]["status"], "reported")
        self.assertEqual(asst["payload"]["usage"]["cache_read"], 10)
        self.assertEqual(asst["payload"]["usage"]["cache_write"], 5)
        self.assertEqual(asst["payload"]["usage"]["total_tokens"], None)
        self.assertEqual(asst["payload"]["model"], "claude-opus-4")
        compact = next(e for e in evs if e["type"] == "compaction.boundary")
        self.assertEqual(compact["payload"]["pre_tokens"], 8000)
        self.assertEqual(compact["payload"]["post_tokens"], 1200)
        err = next(e for e in evs if e["type"] == "message.upserted" and e["payload"].get("status") == "failed")
        self.assertIn("503", err["payload"]["text"])
        self.assertIn("retry 1/10", err["payload"]["text"])

    def test_projection(self):
        evs, _ = translate_file(Path("testdata/vendor/claude-sample.jsonl"))
        recs = [{"seq": i + 1, "event": e} for i, e in enumerate(evs)]
        sess = project_session("claude-verify", "claude", recs)
        self.assertEqual(sess["title"], "claude fixture title")
        kinds = [r["kind"] for r in sess["rows"]]
        self.assertEqual(kinds, ["user", "assistant", "assistant", "tool", "user", "compacted", "assistant"])
        tool = next(r for r in sess["rows"] if r["kind"] == "tool")
        self.assertEqual(tool["status"], "completed")
        self.assertEqual(tool["result"], "type=user")
        self.assertEqual(tool["parentId"], "msg-a2")
        self.assertEqual(sess["turns"], 2)
        asst = next(r for r in sess["rows"] if r["kind"] == "assistant")
        self.assertEqual(asst["model"], "claude-opus-4")
        compacted = next(r for r in sess["rows"] if r["kind"] == "compacted")
        self.assertIn("8000 → 1200", compacted["note"])
        failed = next(r for r in sess["rows"] if r["status"] == "failed")
        self.assertEqual(failed["kind"], "assistant")


if __name__ == "__main__":
    unittest.main()
