import unittest

from ata.plugins.common import (
    PLACEHOLDER_MS,
    bump_turn_if_real_user,
    tool_start_payload,
    tool_end_payload,
    usage_from_counts,
    usage_missing,
)
from ata.schema import envelope


class EnvelopeTest(unittest.TestCase):
    def test_seven_keys(self):
        ev = envelope(
            agent_id="claude", session_id="s1", type_="turn.started",
            payload={}, turn=1, ts=1000, eid="s:t1:start")
        self.assertEqual(ev, {
            "v": 1, "id": "s:t1:start", "agent_id": "claude",
            "session_id": "s1", "ts": 1000, "type": "turn.started",
            "turn": 1, "payload": {}})


class UsageTest(unittest.TestCase):
    def test_all_zero_is_missing(self):
        u = usage_from_counts(0, 0, 0, 0)
        self.assertEqual(u["status"], "missing")
        for k in ("input", "output", "cache_read", "cache_write", "total_tokens", "cost"):
            self.assertIsNone(u[k])

    def test_reported(self):
        u = usage_from_counts(10, 5, 2, 3, total_tokens=15)
        self.assertEqual(u, {"status": "reported", "input": 10, "output": 5,
                             "cache_read": 2, "cache_write": 3,
                             "total_tokens": 15, "cost": None})

    def test_usage_missing_shape(self):
        u = usage_missing()
        self.assertEqual(u["status"], "missing")


class ToolPairTest(unittest.TestCase):
    def test_start_then_end_roundtrip(self):
        state = {}
        start = tool_start_payload(
            "c1", "m1", "Bash", {"command": "ls"},
            "ls", 1000)
        state.setdefault("tools", {})["c1"] = start
        end = tool_end_payload(
            state["tools"].get("c1"), "c1", "fallback-m", "files", 1500)
        self.assertEqual(end["status"], "completed")
        self.assertEqual(end["parent_message_id"], "m1")   # 从 prev 回填，不走 fallback
        self.assertEqual(end["payload"], {"command": "ls"})
        self.assertEqual(end["started_at"], 1000)
        self.assertEqual(end["name"], "Bash")
        self.assertEqual(end["result"], "files")
        # end 行的 duration 是占位约定值
        self.assertEqual(end["duration_ms"], PLACEHOLDER_MS)

    def test_end_without_start_uses_fallback(self):
        end = tool_end_payload(None, "c9", "fb", "", 1500)
        self.assertEqual(end["parent_message_id"], "fb")
        self.assertEqual(end["name"], "tool")
        self.assertEqual(end["text"], "c9")
        self.assertEqual(end["started_at"], 1500)


class BumpTurnTest(unittest.TestCase):
    def test_real_user_message_starts_turn(self):
        state = {}
        events = []
        turn = bump_turn_if_real_user(state, "你好", "claude", "s1", 1000,
                                      lambda e: events.append(e))
        self.assertEqual(turn, 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "turn.started")

    def test_context_injection_does_not_start_turn(self):
        state = {}
        events = []
        turn = bump_turn_if_real_user(state, "<system-reminder>x", "claude", "s1", 1000,
                                      lambda e: events.append(e))
        self.assertIsNone(turn)
        self.assertEqual(events, [])

    def test_each_real_message_gets_one_started(self):
        # 连续两条真实用户消息是两个轮次，各发一次 turn.started；
        # 防重键是 started_turns——同号轮次不会重复发。
        events = []
        state = {}
        t1 = bump_turn_if_real_user(state, "a", "c", "s", 1, lambda e: events.append(e))
        t2 = bump_turn_if_real_user(state, "b", "c", "s", 2, lambda e: events.append(e))
        self.assertEqual((t1, t2), (1, 2))
        self.assertEqual([e["turn"] for e in events], [1, 2])
        state["started_turns"].add(2)
        t3 = bump_turn_if_real_user(state, "b", "c", "s", 3, lambda e: events.append(e))
        self.assertEqual(t3, 3)
        self.assertEqual(len(events), 3)


if __name__ == "__main__":
    unittest.main()
