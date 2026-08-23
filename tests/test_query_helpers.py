import unittest
from ata.project import summarize_usage, list_tools, list_compactions, tail_preview


def ev(seq, typ, turn, payload):
    return {"seq": seq, "event": {"v": 1, "id": f"e{seq}", "agent_id": "pi",
            "session_id": "s", "ts": seq, "type": typ, "turn": turn, "payload": payload}}


USAGE_OK = {"status": "reported", "input": 100, "output": 20, "cache_read": 5,
            "cache_write": 1, "total_tokens": 126, "cost": None}
USAGE_MISSING = {"status": "missing", "input": None, "output": None,
                 "cache_read": None, "cache_write": None, "total_tokens": None, "cost": None}


class TestSummarizeUsage(unittest.TestCase):
    def test_rows_totals_and_missing_count(self):
        recs = [
            ev(1, "message.upserted", 1, {"message_id": "a1", "role": "assistant",
               "model": "m", "usage": USAGE_OK}),
            ev(2, "message.upserted", 2, {"message_id": "a2", "role": "assistant",
               "model": "m", "usage": USAGE_MISSING}),
            ev(3, "turn.ended", 2, {"usage": USAGE_OK}),
        ]
        out = summarize_usage(recs)
        self.assertEqual(len(out["turns"]), 2)
        self.assertEqual(out["missing_turns"], 0)  # turn2 被 turn.ended 回填为 reported
        self.assertEqual(out["total"]["input"], 200)

    def test_permanent_missing_counts(self):
        recs = [ev(1, "message.upserted", 1, {"message_id": "a1", "role": "assistant",
                "usage": USAGE_MISSING})]
        out = summarize_usage(recs)
        self.assertEqual(out["missing_turns"], 1)
        self.assertEqual(out["total"]["input"], 0)


class TestLists(unittest.TestCase):
    def test_tools_filter_latest_wins(self):
        recs = [
            ev(1, "tool.upserted", 1, {"tool_call_id": "c1", "name": "read",
               "status": "pending", "result": None}),
            ev(2, "tool.upserted", 1, {"tool_call_id": "c1", "name": "read",
               "status": "failed", "result": "EACCES"}),
            ev(3, "tool.upserted", 1, {"tool_call_id": "c2", "name": "grep",
               "status": "completed", "result": "1 match"}),
        ]
        self.assertEqual(len(list_tools(recs, None, None)), 2)
        failed = list_tools(recs, "failed", None)
        self.assertEqual(failed[0]["id"], "c1")
        self.assertEqual(list_tools(recs, None, "grep")[0]["name"], "grep")

    def test_compactions(self):
        recs = [ev(5, "compaction.boundary", 3,
                {"trigger": "auto", "pre_tokens": 900, "post_tokens": 300,
                 "summary": "s" * 500})]
        rows = list_compactions(recs)
        self.assertEqual(rows[0]["trigger"], "auto")
        # 预览截断是 HTTP 层职责（full=true 取全文），helper 返回原文。
        self.assertEqual(len(rows[0]["summary"]), 500)

    def test_tail_preview(self):
        self.assertEqual(tail_preview("short"), "short")
        out = tail_preview("x" * 300)
        self.assertEqual(len(out), 201)
        self.assertTrue(out.startswith("…"))


if __name__ == "__main__":
    unittest.main()
