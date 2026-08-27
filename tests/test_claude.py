import unittest
from pathlib import Path

from ata.plugins.claude import translate_file
from ata.project import project_session


class ClaudeTest(unittest.TestCase):
    """Round 2 收窄后, transcript 只发元数据 (session.opened / compaction.boundary /
    system.api_error)。message / tool / turn.started 走代理主发, transcript 不再发。
    本测试反映新行为, 不再断言 message.upserted / turn.started / tool.upserted 的
    数量/字段 (那些由 capture 端单测覆盖)。"""

    def test_maps_verified_types(self):
        evs, _ = translate_file(Path("testdata/vendor/claude-sample.jsonl"))
        types = [e["type"] for e in evs]
        # 元数据通道
        self.assertIn("session.opened", types)
        self.assertIn("compaction.boundary", types)
        # transcript 不再发
        self.assertNotIn("turn.started", types)
        self.assertNotIn("turn.ended", types)
        self.assertNotIn("tool.upserted", types)
        self.assertNotIn("system.upserted", types)
        # title 被 ai-title 覆盖
        titles = [e["payload"]["title"] for e in evs if e["type"] == "session.opened"]
        self.assertEqual(titles[-1], "claude fixture title")
        # compaction.boundary 字段透传
        compact = next(e for e in evs if e["type"] == "compaction.boundary")
        self.assertEqual(compact["payload"]["pre_tokens"], 8000)
        self.assertEqual(compact["payload"]["post_tokens"], 1200)
        # system.api_error 仍以 message.upserted(failed) 兜底, 便于人工定位
        err = next(e for e in evs if e["type"] == "message.upserted"
                   and e["payload"].get("status") == "failed")
        self.assertIn("503", err["payload"]["text"])
        self.assertIn("retry 1/10", err["payload"]["text"])

    def test_projection(self):
        """Round 2 投影只剩 compacted + api_error 兜底 message。代理发的 message
        走另一条 ingest 路径, 不进入本 fixture 的 projection 数据。"""
        evs, _ = translate_file(Path("testdata/vendor/claude-sample.jsonl"))
        recs = [{"seq": i + 1, "event": e} for i, e in enumerate(evs)]
        sess = project_session("claude-verify", "claude", recs)
        self.assertEqual(sess["title"], "claude fixture title")
        kinds = [r["kind"] for r in sess["rows"]]
        # transcript 这条路径只剩 compacted + api_error 那条 assistant
        self.assertEqual(kinds, ["compacted", "assistant"])
        compacted = next(r for r in sess["rows"] if r["kind"] == "compacted")
        self.assertIn("8000 → 1200", compacted["note"])
        failed = next(r for r in sess["rows"] if r["status"] == "failed")
        self.assertEqual(failed["kind"], "assistant")


if __name__ == "__main__":
    unittest.main()
