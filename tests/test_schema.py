import unittest
from ata.schema import ALLOWED_AGENTS, ValidationError, envelope, parse_event

MIN = {
    "v": 1,
    "id": "e1",
    "agent_id": "pi",
    "session_id": "s1",
    "ts": 1,
    "type": "session.opened",
    "turn": None,
    "payload": {"title": "t"},
}


class SchemaTest(unittest.TestCase):
    def test_ok(self):
        ev = parse_event(MIN)
        self.assertEqual(ev["type"], "session.opened")

    def test_reject_missing_agent(self):
        bad = dict(MIN)
        del bad["agent_id"]
        with self.assertRaises(ValidationError):
            parse_event(bad)

    def test_reject_unknown_type(self):
        bad = dict(MIN, type="hook.PreToolUse")
        with self.assertRaises(ValidationError):
            parse_event(bad)

    def test_reject_user_usage(self):
        bad = dict(
            MIN,
            type="message.upserted",
            turn=1,
            payload={
                "message_id": "u1",
                "role": "user",
                "text": "hi",
                "status": "completed",
                "request_no": None,
                "usage": {"status": "reported", "input": 1, "output": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 1, "cost": None},
                "started_at": 1,
                "duration_ms": 1,
                "output_text": None,
            },
        )
        with self.assertRaises(ValidationError):
            parse_event(bad)

    def test_compaction_requires_summary(self):
        bad = dict(MIN, type="compaction.boundary", turn=1, payload={})
        with self.assertRaises(ValidationError):
            parse_event(bad)
        ok = dict(MIN, type="compaction.boundary", turn=1, payload={"summary": "Context compacted"})
        self.assertEqual(parse_event(ok)["type"], "compaction.boundary")


class EnvelopeTest(unittest.TestCase):
    def test_envelope_full_shape(self):
        ev = envelope("claude", "s1", "session.scored", {"value": "good"},
                      turn=None, ts=1234, eid="abc")
        self.assertEqual(ev, {
            "v": 1, "id": "abc", "agent_id": "claude", "session_id": "s1",
            "ts": 1234, "type": "session.scored", "turn": None,
            "payload": {"value": "good"},
        })
        # 工厂产物必须能直接过 parse_event
        self.assertEqual(parse_event(ev)["type"], "session.scored")

    def test_envelope_defaults(self):
        import time as _t
        before = int(_t.time() * 1000)
        ev = envelope("pi", "s2", "session.renamed", {"title": "x"}, eid="e2")
        after = int(_t.time() * 1000)
        self.assertEqual(ev["v"], 1)
        self.assertEqual(ev["id"], "e2")
        self.assertIsNone(ev["turn"])
        self.assertTrue(before <= ev["ts"] <= after)

    def test_allowed_agents_unchanged(self):
        self.assertIn("pi", ALLOWED_AGENTS)


if __name__ == "__main__":
    unittest.main()
