import sqlite3
import tempfile
import unittest
from pathlib import Path

from ata.ledger import Ledger, ResetRequiredError
from ata.schema import envelope, parse_event


def opened(sid="s1", title="hello", ts=1787000000010, eid="e1"):
    return parse_event(envelope("pi", sid, "session.opened", {"title": title}, ts=ts, eid=eid))


def message(sid, eid, ts, run_id, turn_number, role="assistant"):
    return parse_event(envelope(
        "pi", sid, "message.upserted", {
            "message_id": eid, "role": role, "text": "x", "status": "completed",
            "request_no": 1, "usage": None, "started_at": ts,
            "duration_ms": 1, "output_text": "x",
        }, run_id=run_id, turn_number=turn_number, ts=ts, eid=eid,
    ))


class LedgerTest(unittest.TestCase):
    def test_append_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            self.addCleanup(led.close)
            self.assertEqual(led.append(opened()), 1)
            self.assertEqual(led.append(opened()), 1)
            self.assertEqual(len(led.read("s1")), 1)

    def test_run_identity_is_stored_and_run_index_projected(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            self.addCleanup(led.close)
            led.append(opened())
            led.append(parse_event(envelope(
                "pi", "s1", "run.started",
                {"external_lifecycle_id": "ext-1", "boundary_source": "test"},
                run_id=1, ts=1787000000020, eid="start",
            )))
            led.append(message("s1", "m1", 1787000000030, 1, 1))
            self.assertEqual(led.read("s1")[2]["event"]["turn_number"], 1)
            self.assertEqual(led.run("s1", 1)["max_turn_number"], 1)
            self.assertEqual(led.run("s1", 1)["status"], "open")

    def test_same_natural_key_isolated_by_run_namespace(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            self.addCleanup(led.close)
            led.append(message("s1", "m1", 1787000000010, 1, 1))
            led.append(message("s1", "m2", 1787000000020, 2, 1))
            self.assertEqual(len(led.read("s1")), 2)

    def test_legacy_schema_requires_explicit_reset(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.sqlite"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE events (
                    session_id TEXT, event_id TEXT, seq INTEGER, ts INTEGER,
                    type TEXT, turn INTEGER, event_json TEXT,
                    PRIMARY KEY (session_id, event_id)
                );
            """)
            conn.commit()
            conn.close()
            with self.assertRaisesRegex(ResetRequiredError, "reset required"):
                Ledger(path)

    def test_transaction_rolls_back_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            self.addCleanup(led.close)
            led.append(opened())
            with self.assertRaises(ValueError):
                with led.transaction() as tx:
                    tx.append_event(message("s1", "m1", 1787000000020, 1, 1))
                    raise ValueError("boom")
            # 回滚后事件流里只剩事务前的事实；单条 append/append_many 不受影响
            self.assertEqual(
                [r["event"]["type"] for r in led.read("s1")], ["session.opened"])
            led.append(message("s1", "m1", 1787000000020, 1, 1))
            self.assertEqual(len(led.read("s1")), 2)


if __name__ == "__main__":
    unittest.main()
