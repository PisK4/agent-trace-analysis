import tempfile
import unittest
from pathlib import Path

from ata.ledger import Ledger, _dedupe_key
from ata.schema import envelope, parse_event


def ev(sid, eid, ts, typ, payload, *, run_id=None, turn_number=None,
       observed_turn_ordinal=None):
    return parse_event(envelope(
        "pi", sid, typ, payload, run_id=run_id, turn_number=turn_number,
        observed_turn_ordinal=observed_turn_ordinal, ts=ts, eid=eid,
    ))


class DedupeIngestTests(unittest.TestCase):
    def setUp(self):
        self.led = Ledger(Path(tempfile.mkdtemp()))

    def test_message_snapshots_collapse_to_latest(self):
        payload = {"message_id": "m1", "role": "assistant", "status": "pending",
                   "usage": None}
        self.led.append(ev("s1", "e1", 10, "message.upserted", payload, run_id=1, turn_number=1))
        seq2 = self.led.append(ev("s1", "e2", 20, "message.upserted",
                                  {**payload, "status": "completed"}, run_id=1, turn_number=1))
        rows = self.led.read("s1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"]["payload"]["status"], "completed")
        self.assertEqual(rows[0]["seq"], seq2)

    def test_same_event_id_still_idempotent(self):
        e = ev("s1", "e1", 10, "message.upserted",
                {"message_id": "m1", "role": "assistant", "status": "pending", "usage": None},
                run_id=1, turn_number=1)
        self.assertEqual(self.led.append(e), self.led.append(e))
        self.assertEqual(len(self.led.read("s1")), 1)

    def test_same_message_id_in_different_runs_is_not_deduped(self):
        payload = {"message_id": "m1", "role": "assistant", "status": "completed", "usage": None}
        self.led.append(ev("s1", "e1", 10, "message.upserted", payload, run_id=1, turn_number=1))
        self.led.append(ev("s1", "e2", 20, "message.upserted", payload, run_id=2, turn_number=1))
        self.assertEqual(len(self.led.read("s1")), 2)

    def test_observed_and_runless_namespaces_are_explicit(self):
        payload = {"message_id": "m1", "role": "assistant", "status": "completed", "usage": None}
        a = ev("s1", "e1", 10, "message.upserted", payload, observed_turn_ordinal=1)
        b = ev("s1", "e2", 20, "message.upserted", payload, run_id=1, turn_number=1)
        self.assertNotEqual(_dedupe_key(a), _dedupe_key(b))


if __name__ == "__main__":
    unittest.main()
