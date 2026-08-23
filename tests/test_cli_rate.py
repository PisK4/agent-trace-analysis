import unittest
from ata.cli import build_score_event
from ata.schema import parse_event


class TestBuildScoreEvent(unittest.TestCase):
    def test_valid_event_passes_schema(self):
        ev = build_score_event("cue", "s1", "good", note="卡片可用")
        parsed = parse_event(ev)
        self.assertEqual(parsed["payload"]["value"], "good")
        self.assertEqual(parsed["payload"]["note"], "卡片可用")

    def test_no_note_key_when_absent(self):
        ev = build_score_event("cue", "s1", "bad")
        self.assertNotIn("note", ev["payload"])

    def test_invalid_value_rejected_by_schema(self):
        from ata.schema import ValidationError
        ev = build_score_event("cue", "s1", "meh")
        with self.assertRaises(ValidationError):
            parse_event(ev)


if __name__ == "__main__":
    unittest.main()
