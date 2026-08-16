import unittest
from ata.schema import ValidationError, parse_event

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


if __name__ == "__main__":
    unittest.main()
