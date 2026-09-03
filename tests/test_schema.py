import unittest
from ata.schema import ALLOWED_AGENTS, ValidationError, envelope, parse_event

BASE = {
    "v": 1,
    "id": "e1",
    "agent_id": "pi",
    "session_id": "s1",
    "ts": 1,
    "type": "session.opened",
    "run_id": None,
    "turn_number": None,
    "observed_turn_ordinal": None,
    "payload": {"title": "t"},
}


def message(**identity):
    return dict(BASE, type="message.upserted", payload={
        "message_id": "m1", "role": "user", "text": "hi", "usage": None,
    }, **identity)


class SchemaTest(unittest.TestCase):
    def test_ok(self):
        ev = parse_event(BASE)
        self.assertEqual(ev["type"], "session.opened")

    def test_runtime_identity_shapes(self):
        started = dict(BASE, type="run.started", run_id=1,
                       payload={"external_lifecycle_id": "x", "boundary_source": "pi"})
        self.assertEqual(parse_event(started)["run_id"], 1)
        scoped = parse_event(message(run_id=1, turn_number=1))
        self.assertEqual((scoped["run_id"], scoped["turn_number"]), (1, 1))
        observed = parse_event(message(observed_turn_ordinal=3))
        self.assertEqual(observed["observed_turn_ordinal"], 3)

    def test_reject_missing_agent(self):
        bad = dict(BASE)
        del bad["agent_id"]
        with self.assertRaises(ValidationError):
            parse_event(bad)

    def test_reject_unknown_type(self):
        with self.assertRaises(ValidationError):
            parse_event(dict(BASE, type="hook.PreToolUse"))

    def test_reject_legacy_turn_and_bad_identity(self):
        with self.assertRaises(ValidationError):
            parse_event(dict(BASE, turn=1))
        with self.assertRaises(ValidationError):
            parse_event(message(run_id=0, turn_number=1))
        with self.assertRaises(ValidationError):
            parse_event(message(turn_number=1))
        with self.assertRaises(ValidationError):
            parse_event(message(run_id=1, turn_number=1, observed_turn_ordinal=2))

    def test_reject_user_usage(self):
        bad = message(run_id=1, turn_number=1)
        bad["payload"] = dict(bad["payload"], usage={"status": "reported"})
        with self.assertRaises(ValidationError):
            parse_event(bad)

    def test_compaction_requires_summary_and_no_turn(self):
        bad = dict(BASE, type="compaction.boundary", payload={})
        with self.assertRaises(ValidationError):
            parse_event(bad)
        ok = dict(BASE, type="compaction.boundary", payload={"summary": "Context compacted"})
        self.assertEqual(parse_event(ok)["type"], "compaction.boundary")
        with self.assertRaises(ValidationError):
            parse_event(dict(ok, observed_turn_ordinal=1))

    def test_run_boundaries_and_conflict(self):
        payload = {"external_lifecycle_id": None, "boundary_source": "pi"}
        self.assertEqual(parse_event(dict(BASE, type="run.ended", run_id=1, payload=payload))["turn_number"], None)
        conflict = dict(BASE, type="run.lifecycle.conflict", payload={
            "external_lifecycle_id": None, "hook_name": "agent_end",
            "reason": "missing lifecycle id", "semantic_fingerprint": "f",
            "boundary_source": "pi",
        })
        self.assertIsNone(parse_event(conflict)["run_id"])
        with self.assertRaises(ValidationError):
            parse_event(dict(conflict, run_id=1))

    def test_removed_assignment_types(self):
        with self.assertRaises(ValidationError):
            parse_event(dict(BASE, type="session.assigned"))
        with self.assertRaises(ValidationError):
            parse_event(dict(BASE, type="session.unassigned"))


class EnvelopeTest(unittest.TestCase):
    def test_envelope_full_shape(self):
        ev = envelope("claude", "s1", "session.scored", {"value": "good"},
                      ts=1234, eid="abc")
        self.assertEqual(ev, {
            "v": 1, "id": "abc", "agent_id": "claude", "session_id": "s1",
            "ts": 1234, "type": "session.scored", "run_id": None,
            "turn_number": None, "observed_turn_ordinal": None,
            "payload": {"value": "good"},
        })
        self.assertEqual(parse_event(ev)["type"], "session.scored")

    def test_envelope_defaults(self):
        import time as _t
        before = int(_t.time() * 1000)
        ev = envelope("pi", "s2", "session.renamed", {"title": "x"}, eid="e2")
        after = int(_t.time() * 1000)
        self.assertEqual(ev["v"], 1)
        self.assertEqual(ev["id"], "e2")
        self.assertIsNone(ev["run_id"])
        self.assertTrue(before <= ev["ts"] <= after)
    def test_allowed_agents_unchanged(self):
        self.assertIn("pi", ALLOWED_AGENTS)

    def test_omp_is_whitelisted(self):
        # omp 与 pi 共用同一扩展(attach-omp-pi.sh),事件契约同 pi,故在
        # ALLOWED_AGENTS 中独立成项,产品身份与 Pi/Cue 平级。
        self.assertIn("omp", ALLOWED_AGENTS)


if __name__ == "__main__":
    unittest.main()
