import unittest
from ata.schema import parse_event, ValidationError


def scored(value, note=None):
    payload = {"value": value}
    if note is not None:
        payload["note"] = note
    return {"v": 1, "id": "x1", "agent_id": "cue", "session_id": "s1",
            "ts": 1000, "type": "session.scored", "turn": None, "payload": payload}


class TestScored(unittest.TestCase):
    def test_accepts_valid(self):
        ev = parse_event(scored("good", note="意图卡片方向对"))
        self.assertEqual(ev["type"], "session.scored")

    def test_rejects_bad_value(self):
        with self.assertRaises(ValidationError):
            parse_event(scored("excellent"))

    def test_rejects_missing_value(self):
        with self.assertRaises(ValidationError):
            parse_event(scored(None))

    def test_scored_requires_no_turn(self):
        raw = scored("bad")
        raw["turn"] = 2
        with self.assertRaises(ValidationError):
            parse_event(raw)


if __name__ == "__main__":
    unittest.main()
