import unittest
from ata.project import summarize_timing


def rec(seq, typ, ts, payload, turn=1):
    return {"seq": seq, "event": {"v": 1, "id": f"e{seq}", "agent_id": "pi",
            "session_id": "s", "ts": TS0 + ts, "type": typ, "turn": turn,
            "payload": payload}}


# fixture 时间戳基线：summarize_timing 只认 > 10^12 的真实毫秒 ts（脏数据过滤）
TS0 = 1_700_000_000_000


class TestSummarizeTiming(unittest.TestCase):
    def test_measured_split(self):
        # 同 id 多次 upsert：字典 last-wins，end 行的 duration 覆盖 start 行的 None
        recs = [
            rec(1, "message.upserted", 1000, {"message_id": "u1", "role": "user",
                "text": "hi", "status": "completed"}),
            rec(2, "message.upserted", 1100, {"message_id": "a1", "role": "assistant",
                "text": "", "status": "pending", "duration_ms": None}),
            rec(3, "tool.upserted", 2000, {"tool_call_id": "c1", "name": "read",
                "status": "pending", "duration_ms": None}),
            rec(4, "tool.upserted", 2300, {"tool_call_id": "c1", "name": "read",
                "status": "completed", "duration_ms": 300}),
            rec(5, "message.upserted", 7300, {"message_id": "a1", "role": "assistant",
                "text": "done", "status": "completed", "duration_ms": 5000}),
        ]
        out = summarize_timing(recs)
        self.assertEqual(out["span_ms"], 6300)
        self.assertEqual(out["llm_ms"], 5000)
        self.assertEqual(out["tool_ms"], 300)
        self.assertEqual(out["other_ms"], 1000)
        self.assertEqual(out["llm_quality"], "measured")
        self.assertEqual(out["tool_quality"], "measured")
        self.assertEqual(out["steps"], 1)
        self.assertEqual(out["calls"], 1)
        self.assertEqual(out["turns"], 1)
        self.assertEqual(out["per_turn"][0]["llm_ms"], 5000)
        self.assertEqual(out["per_turn"][0]["tool_ms"], 300)
        self.assertEqual(out["per_turn"][0]["steps"], 1)
        self.assertEqual(out["per_turn"][0]["calls"], 1)

    def test_placeholder_durations_excluded(self):
        # duration_ms=1 是适配器占位：不计入总量，quality 降级 placeholder
        recs = [
            rec(1, "message.upserted", 1000, {"message_id": "a1", "role": "assistant",
                "status": "completed", "duration_ms": 1}),
            rec(2, "tool.upserted", 1100, {"tool_call_id": "c1",
                "status": "completed", "duration_ms": 1}),
        ]
        out = summarize_timing(recs)
        self.assertEqual(out["llm_ms"], 0)
        self.assertEqual(out["tool_ms"], 0)
        self.assertEqual(out["llm_quality"], "placeholder")
        self.assertEqual(out["tool_quality"], "placeholder")

    def test_missing_duration_is_placeholder_too(self):
        # duration 字段整个缺失（如 /usage 测试里的 conv fixture）同样不算实测
        recs = [rec(1, "message.upserted", 1000, {"message_id": "a1",
                "role": "assistant", "status": "completed"})]
        out = summarize_timing(recs)
        self.assertEqual(out["llm_ms"], 0)
        self.assertEqual(out["llm_quality"], "placeholder")

    def test_empty_session(self):
        out = summarize_timing([])
        self.assertEqual(out["span_ms"], 0)
        self.assertEqual(out["first_ts"], None)
        self.assertEqual(out["steps"], 0)
        self.assertEqual(out["llm_quality"], "n/a")
        self.assertEqual(out["per_turn"], [])

    def test_multi_turn_per_turn_rows(self):
        recs = [
            rec(1, "message.upserted", 1000, {"message_id": "a1", "role": "assistant",
                "status": "completed", "duration_ms": 4000}, turn=1),
            rec(2, "message.upserted", 9000, {"message_id": "a2", "role": "assistant",
                "status": "completed", "duration_ms": 6000}, turn=2),
        ]
        out = summarize_timing(recs)
        self.assertEqual(out["turns"], 2)
        self.assertEqual([t["turn"] for t in out["per_turn"]], [1, 2])
        self.assertEqual(out["llm_ms"], 10000)

    def test_dirty_ts_excluded_from_span(self):
        # ts=1 脏行（历史推送端 bug 的存量数据）不参与墙钟跨度，
        # 否则 span 被拉成 50+ 年（与 ledger._REAL_TS_FLOOR 同一约定）
        recs = [
            rec(1, "system.upserted", -TS0 + 1, {}),
            rec(2, "message.upserted", 0, {"message_id": "a1",
                "role": "assistant", "status": "completed", "duration_ms": 1}),
            rec(3, "tool.upserted", 5000, {"tool_call_id": "c1",
                "status": "completed", "duration_ms": 1}),
        ]
        out = summarize_timing(recs)
        self.assertEqual(out["span_ms"], 5000)
        self.assertEqual(out["first_ts"], TS0)


if __name__ == "__main__":
    unittest.main()
