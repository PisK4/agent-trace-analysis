import tempfile
import unittest
from pathlib import Path

from ata.evaluation import (
    EvaluationStore,
    EvaluationValidationError,
    evaluation_envelope,
    fold_evaluation_events,
)
from ata.ledger import Ledger
from ata.schema import parse_event


def opened(sid="s1"):
    return parse_event({
        "v": 1, "id": f"{sid}:open", "agent_id": "pi", "session_id": sid,
        "ts": 1787000000001, "type": "session.opened", "run_id": None,
        "turn_number": None, "observed_turn_ordinal": None, "payload": {"title": sid},
    })


class EvaluationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name) / "ata.sqlite")
        self.store = EvaluationStore(self.ledger)
        self.ledger.append(opened())

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_create_read_and_fold_empty_evaluation(self):
        eid = self.store.create("人工回归", evaluation_id="e-1", ts=10)
        self.assertEqual(self.store.read(eid)[0]["seq"], 1)
        self.assertEqual(self.store.fold(eid), {
            "evaluation_id": "e-1", "title": "人工回归", "deleted": False, "members": [],
        })

    def test_add_updates_label_and_remove_is_latest_membership(self):
        eid = self.store.create("eval", evaluation_id="e-1", ts=10)
        self.store.add_session(eid, "s1", "first", ts=11)
        self.store.add_session(eid, "s1", "updated", ts=12)
        state = self.store.fold(eid)
        self.assertEqual(state["members"][0]["task_label"], "updated")
        self.store.remove_session(eid, "s1", ts=13)
        self.assertEqual(self.store.fold(eid)["members"], [])
        self.assertEqual(len(self.store.read(eid)), 4)

    def test_membership_is_exclusive_and_requires_existing_session(self):
        first = self.store.create("one", evaluation_id="e-1")
        second = self.store.create("two", evaluation_id="e-2")
        self.store.add_session(first, "s1")
        with self.assertRaises(EvaluationValidationError):
            self.store.add_session(second, "s1")
        with self.assertRaises(EvaluationValidationError):
            self.store.add_session(first, "missing")

    def test_delete_clears_active_membership_and_blocks_mutation(self):
        eid = self.store.create("eval", evaluation_id="e-1")
        self.store.add_session(eid, "s1")
        self.store.delete(eid)
        state = self.store.fold(eid)
        self.assertTrue(state["deleted"])
        self.assertEqual(state["members"], [])
        with self.assertRaises(EvaluationValidationError):
            self.store.rename(eid, "new")

    def test_ledger_sequence_is_independent(self):
        eid = self.store.create("eval", evaluation_id="e-1")
        self.assertEqual(self.store.read(eid)[0]["seq"], 1)
        self.ledger.append(opened("s2"))
        self.store.rename(eid, "renamed")
        self.assertEqual([r["seq"] for r in self.store.read(eid)], [1, 2])
        self.assertEqual(self.ledger.session("s2")["last_seq"], 1)

    def test_deleted_fact_payload_and_fold_accept_plain_events(self):
        with self.assertRaises(EvaluationValidationError):
            self.store.append(evaluation_envelope("e-1", "evaluation.deleted", {"x": 1}))
        self.assertIsNone(fold_evaluation_events("e-none", []))


if __name__ == "__main__":
    unittest.main()
