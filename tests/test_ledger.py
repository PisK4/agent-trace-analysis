import tempfile
import unittest
from pathlib import Path

from ata.ledger import Ledger
from ata.schema import parse_event

EV = parse_event({
    "v": 1, "id": "e1", "agent_id": "pi", "session_id": "s1",
    "ts": 10, "type": "session.opened", "turn": None,
    "payload": {"title": "hello"},
})


class LedgerTest(unittest.TestCase):
    def test_append_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            a = led.append(EV)
            b = led.append(EV)
            self.assertEqual(a, 1)
            self.assertEqual(b, 1)
            self.assertEqual(len(led.read("s1")), 1)

    def test_unknown_session_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(Ledger(Path(td)).read("nope"), [])

    def test_session_title_comes_from_index(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            led.append(EV)
            listing = led.sessions()
            self.assertEqual(listing, [{
                "id": "s1",
                "agent": "pi",
                "title": "hello",
                "turns": 0,
                "last_ts": 10,
            }])

    def test_sessions_ordered_by_latest_event(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            led.append(EV)  # s1, ts=10
            led.append(parse_event({
                "v": 1, "id": "e1", "agent_id": "droid", "session_id": "s2",
                "ts": 30, "type": "session.opened", "turn": None,
                "payload": {"title": "newer"},
            }))
            # s1 追加一条更晚的事件，应回到最前
            led.append(parse_event({
                "v": 1, "id": "a1", "agent_id": "pi", "session_id": "s1",
                "ts": 40, "type": "message.upserted", "turn": 1,
                "payload": {"message_id": "m1", "role": "assistant", "text": "x",
                            "status": "completed", "request_no": 1, "usage": None,
                            "started_at": 40, "duration_ms": 1, "output_text": "x"},
            }))
            ids = [s["id"] for s in led.sessions()]
            self.assertEqual(ids, ["s1", "s2"])
            self.assertEqual([s["last_ts"] for s in led.sessions()], [40, 30])
            self.assertEqual(led.session("s1")["agent"], "pi")
            self.assertIsNone(led.session("nope"))

    def test_backfills_last_ts_on_old_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.sqlite"
            import sqlite3
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    turns INTEGER NOT NULL DEFAULT 0,
                    last_seq INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE events (
                    session_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    ts INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    turn INTEGER,
                    event_json TEXT NOT NULL,
                    PRIMARY KEY (session_id, event_id)
                );
                INSERT INTO sessions VALUES ('s1','pi','old',0,1);
                INSERT INTO events VALUES ('s1','e1',1,77,'session.opened',NULL,'{}');
                """
            )
            conn.commit()
            conn.close()
            led = Ledger(path)
            self.assertEqual(led.session("s1")["last_ts"], 77)


if __name__ == "__main__":
    unittest.main()
