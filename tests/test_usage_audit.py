import unittest

from ata.project import audit_usage, summarize_usage
from ata.schema import parse_event


def rec(seq, ev):
    return {"seq": seq, "event": parse_event(ev)}


def opened(seq, ts=1):
    return rec(seq, {"v": 1, "id": "o", "agent_id": "claude", "session_id": "s", "ts": ts,
                     "type": "session.opened", "observed_turn_ordinal": None, "payload": {"title": "t"}})


def assistant(seq, turn, usage, ts=None):
    return rec(seq, {"v": 1, "id": f"a{turn}", "agent_id": "claude", "session_id": "s",
                     "ts": ts or turn, "type": "message.upserted", "observed_turn_ordinal": turn, "payload": {
                         "message_id": f"m{turn}", "role": "assistant", "text": "ok",
                         "status": "completed", "request_no": turn, "usage": usage,
                         "started_at": turn, "duration_ms": 10, "output_text": "ok"}})


def reported(inp, out, cache_read=0, total=None, cost=None):
    return {"status": "reported", "input": inp, "output": out, "cache_read": cache_read,
            "cache_write": 0, "total_tokens": total if total is not None else inp + out,
            "cost": cost}


class UsageAuditTest(unittest.TestCase):
    def test_clean_session_no_findings(self):
        recs = [opened(1),
                assistant(2, 1, reported(1000, 10)),
                assistant(3, 2, reported(2000, 10))]
        a = audit_usage(recs)
        self.assertEqual(a["findings"], [])
        self.assertEqual((a["reported_turns"], a["expected_turns"]), (2, 2))

    def test_missing_turn(self):
        recs = [opened(1),
                assistant(2, 1, reported(1000, 10)),
                # 第 2 轮 usage 全 None：assistant 消息在但无计量
                rec(3, {"v": 1, "id": "a2", "agent_id": "claude", "session_id": "s", "ts": 3,
                        "type": "message.upserted", "observed_turn_ordinal": 2, "payload": {
                            "message_id": "m2", "role": "assistant", "text": "x",
                            "status": "completed", "request_no": 2, "usage": None,
                            "started_at": 3, "duration_ms": 1, "output_text": "x"}}),
                assistant(4, 3, reported(3000, 10))]
        a = audit_usage(recs)
        rules = [(f["rule"], f["turn"]) for f in a["findings"]]
        self.assertIn(("missing", 2), rules)

    def test_placeholder(self):
        recs = [opened(1), assistant(2, 1, reported(0, 0, total=0))]
        rules = [f["rule"] for f in audit_usage(recs)["findings"]]
        self.assertEqual(rules, ["placeholder"])

    def test_duplicate_adjacent_turns(self):
        recs = [opened(1),
                assistant(2, 1, reported(5000, 100, cache_read=4000)),
                assistant(3, 2, reported(5000, 100, cache_read=4000))]
        rules = [(f["rule"], f["turn"]) for f in audit_usage(recs)["findings"]]
        self.assertIn(("duplicate", 2), rules)

    def test_cliff_without_compaction(self):
        recs = [opened(1),
                assistant(2, 1, reported(50000, 100)),
                assistant(3, 2, reported(20000, 100))]
        rules = [(f["rule"], f["turn"]) for f in audit_usage(recs)["findings"]]
        self.assertIn(("cliff", 2), rules)

    def test_cliff_exempt_by_compaction(self):
        recs = [opened(1),
                assistant(2, 1, reported(50000, 100)),
                rec(3, {"v": 1, "id": "c", "agent_id": "claude", "session_id": "s", "ts": 3,
                        "type": "compaction.boundary", "observed_turn_ordinal": None, "payload": {"summary": "s"}}),
                assistant(4, 2, reported(20000, 100), ts=4)]
        # compaction.boundary 不再携带旧顶层 turn；无法把边界归因到某个
        # observed ordinal，审计应诚实保留 cliff，而不是猜测归属。
        rules = [f["rule"] for f in audit_usage(recs)["findings"]]
        self.assertEqual(rules, ["cliff"])

    def test_cliff_uses_context_for_claude(self):
        # Anthropic 系 input 不含缓存：input 骤降但 cache_read 等量上升，
        # 上下文没掉，不应报 cliff。
        recs = [opened(1),
                assistant(2, 1, reported(23259, 236, cache_read=0)),
                rec(3, {"v": 1, "id": "a2", "agent_id": "claude", "session_id": "s", "ts": 3,
                        "type": "message.upserted", "observed_turn_ordinal": 2, "payload": {
                            "message_id": "m2", "role": "assistant", "text": "x",
                            "status": "completed", "request_no": 2,
                            "usage": {"status": "reported", "input": 1278, "output": 84,
                                      "cache_read": 27392, "cache_write": 0,
                                      "total_tokens": None, "cost": None},
                            "started_at": 3, "duration_ms": 1, "output_text": "x"}})]
        rules = [f["rule"] for f in audit_usage(recs)["findings"]]
        self.assertNotIn("cliff", rules)
        self.assertNotIn("placeholder", rules)  # claude 的 total_tokens 恒 None，不算占位

    def test_placeholder_only_on_explicit_zero(self):
        # claude 行 total_tokens=None：不报占位；显式 0 才报。
        recs = [opened(1),
                rec(2, {"v": 1, "id": "a1", "agent_id": "claude", "session_id": "s", "ts": 2,
                        "type": "message.upserted", "observed_turn_ordinal": 1, "payload": {
                            "message_id": "m1", "role": "assistant", "text": "x",
                            "status": "completed", "request_no": 1,
                            "usage": {"status": "reported", "input": 500, "output": 10,
                                      "cache_read": 0, "cache_write": 0,
                                      "total_tokens": None, "cost": None},
                            "started_at": 2, "duration_ms": 1, "output_text": "x"}})]
        self.assertEqual([f["rule"] for f in audit_usage(recs)["findings"]], [])

    def test_summarize_rows_carry_seq(self):
        recs = [opened(1), assistant(2, 1, reported(1000, 10))]
        rows = summarize_usage(recs)["turns"]
        self.assertEqual(rows[0]["seq"], 2)


if __name__ == "__main__":
    unittest.main()
