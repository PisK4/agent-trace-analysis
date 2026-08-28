import tempfile
import unittest
from pathlib import Path

from ata.ledger import Ledger
from ata.runtime import RuntimeCoordinator, RuntimeScope


class RuntimeCoordinatorTest(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(Path(tempfile.mkdtemp()))
        self.runtime = RuntimeCoordinator(self.ledger)

    def test_start_allocates_persistent_run_and_turn(self):
        first = self.runtime.start("s1", external_lifecycle_id="x", boundary_source="hook", ts=10)
        self.assertEqual(first["status"], "created")
        self.assertEqual(first["scope"], RuntimeScope(run_id=1))
        self.assertEqual(self.runtime.allocate_turn("s1"), RuntimeScope(run_id=1, turn_number=1))
        self.runtime.emit(agent_id="pi", session_id="s1", type_="turn.started", payload={},
                          scope=RuntimeScope(run_id=1, turn_number=1), ts=20, eid="turn-1")
        self.assertEqual(self.runtime.allocate_turn("s1"), RuntimeScope(run_id=1, turn_number=2))

    def test_restart_continues_run_ordinal(self):
        self.runtime.start("s1", external_lifecycle_id="x", boundary_source="hook", ts=10)
        self.runtime.end("s1", external_lifecycle_id="x", boundary_source="hook", ts=20)
        restarted = RuntimeCoordinator(self.ledger)
        result = restarted.start("s1", external_lifecycle_id="y", boundary_source="hook", ts=30)
        self.assertEqual(result["scope"], RuntimeScope(run_id=2))

    def test_lifecycle_retry_and_conflict(self):
        self.assertEqual(self.runtime.start("s1", external_lifecycle_id="x", boundary_source="hook", ts=10)["status"], "created")
        self.assertEqual(self.runtime.start("s1", external_lifecycle_id="x", boundary_source="hook", ts=10)["status"], "duplicate")
        self.assertEqual(self.runtime.start("s1", external_lifecycle_id="x", boundary_source="hook", payload={"changed": True}, ts=10)["status"], "conflict")
        self.assertEqual(len([e for e in self.ledger.read("s1") if e["event"]["type"] == "run.lifecycle.conflict"]), 1)

    def test_end_without_match_is_conflict_not_guessed(self):
        result = self.runtime.end("s1", external_lifecycle_id="missing", boundary_source="hook", ts=10)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self.ledger.runs("s1"), [])

    def test_ambiguous_end_is_conflict_and_runless_events_are_observed(self):
        self.runtime.start("s1", external_lifecycle_id="x", boundary_source="hook", ts=10)
        self.runtime.start("s1", external_lifecycle_id="y", boundary_source="hook", ts=20)
        # 后续 Run 建立后，前一个未结束 Run 为 incomplete；唯一 open Run 可被继承。
        self.assertEqual(self.runtime.scope_for_event("s1"), RuntimeScope(run_id=2))
        result = self.runtime.end("s1", boundary_source="hook", ts=30)
        self.assertEqual(result["status"], "conflict")


if __name__ == "__main__":
    unittest.main()
