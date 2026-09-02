import unittest
from ata.project import summarize_usage, summarize_tools, list_tools, list_compactions, tail_preview


def ev(seq, typ, turn, payload):
    return {"seq": seq, "event": {"v": 1, "id": f"e{seq}", "agent_id": "pi",
            "session_id": "s", "ts": seq, "type": typ, "observed_turn_ordinal": turn, "payload": payload}}


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


class TestSummarizeTools(unittest.TestCase):
    def _recs(self):
        return [
            ev(1, "tool.upserted", 1, {"tool_call_id": "c1", "parent_message_id": "a1",
               "name": "Bash", "status": "pending", "result": None,
               "payload": {"cmd": "ls"}, "started_at": 100}),
            ev(2, "tool.upserted", 1, {"tool_call_id": "c1", "parent_message_id": "a1",
               "name": "Bash", "status": "failed", "result": "EACCES",
               "payload": {"cmd": "ls"}, "started_at": 100}),
            ev(3, "tool.upserted", 2, {"tool_call_id": "c2", "parent_message_id": "a2",
               "name": "Read", "status": "completed", "result": "ok",
               "payload": {"path": "a.md"}, "started_at": 200}),
            ev(4, "tool.upserted", 2, {"tool_call_id": "c3", "parent_message_id": "a2",
               "name": "Read", "status": "completed", "result": "ok",
               "payload": {"path": "b.md"}, "started_at": 300}),
        ]

    def test_counts_dedup_order_and_summary(self):
        out = summarize_tools(self._recs())
        self.assertEqual(out["summary"], {"tools": 2, "calls": 3, "failed": 1,
                                          "mounted": None, "usage_rate": None})
        bash, read = out["tools"]
        self.assertEqual(bash["name"], "Bash")  # 按首次出现排序
        self.assertEqual(bash["total"], 1)      # pending+failed 去重为一次
        self.assertEqual(bash["failed"], 1)
        self.assertEqual(read["total"], 2)
        self.assertEqual([c["seq"] for c in read["calls"]], [3, 4])  # 保序
        # 跳转锚点、时间与入参预览字段在调用序列里
        self.assertEqual(set(out["tools"][0]["calls"][0]),
                         {"seq", "ts", "status", "duration_ms", "text"})

    def test_usage_rate_from_catalog(self):
        recs = self._recs() + [
            ev(9, "system.upserted", None, {"prompt_text": "p", "tools_catalog": [
                {"name": "Bash"}, {"name": "Read"}, {"name": "Grep"}, {"name": "WebFetch"}]}),
        ]
        out = summarize_tools(recs)
        self.assertEqual(out["summary"]["mounted"], 4)
        self.assertEqual(out["summary"]["usage_rate"], 50)  # 已用 2 / 挂载 4

    def test_empty_session(self):
        self.assertEqual(summarize_tools([]),
                         {"tools": [], "summary": {"tools": 0, "calls": 0, "failed": 0,
                                                   "mounted": None, "usage_rate": None}})


class TestSessionEvents(unittest.TestCase):
    """HTTP events 端点与 CLI --ledger events 共用同一份游标分页口径。"""

    class _Store:
        def __init__(self, seqs):
            self.recs = [{"seq": seq, "event": {"type": "note"}} for seq in seqs]

        def read(self, session_id):
            return list(self.recs)

    @classmethod
    def _page(cls, after=None, limit=None, seqs=(1, 2, 3)):
        from ata.queries import session_events
        return session_events(cls._Store(seqs), "s", after=after, limit=limit)

    def test_from_head_returns_all_and_last_seq(self):
        picked, nxt = self._page()
        self.assertEqual([r["seq"] for r in picked], [1, 2, 3])
        self.assertEqual(nxt, 3)

    def test_after_is_strictly_greater(self):
        picked, nxt = self._page(after=2)
        self.assertEqual([r["seq"] for r in picked], [3])
        self.assertEqual(nxt, 3)

    def test_limit_caps_page_and_cursor(self):
        picked, nxt = self._page(after=0, limit=2)
        self.assertEqual([r["seq"] for r in picked], [1, 2])
        self.assertEqual(nxt, 2)

    def test_empty_page_keeps_after_as_cursor(self):
        picked, nxt = self._page(after=9)
        self.assertEqual(picked, [])
        self.assertEqual(nxt, 9)


if __name__ == "__main__":
    unittest.main()
