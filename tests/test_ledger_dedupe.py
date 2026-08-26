import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ata.ledger import Ledger


def ev(sid, eid, ts, typ, payload, turn=1):
    return {"v": 1, "id": eid, "agent_id": "pi", "session_id": sid,
            "ts": ts, "type": typ, "turn": turn, "payload": payload}


class DedupeIngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.led = Ledger(Path(self.tmp))

    def test_message_snapshots_collapse_to_latest(self):
        sid = "s1"
        self.led.append(ev(sid, "e1", 10, "message.upserted",
                           {"message_id": "m1", "status": "pending"}))
        seq2 = self.led.append(ev(sid, "e2", 20, "message.upserted",
                                  {"message_id": "m1", "status": "completed"}))
        rows = self.led.read(sid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"]["payload"]["status"], "completed")
        self.assertEqual(rows[0]["seq"], seq2)

    def test_same_event_id_still_idempotent(self):
        e = ev("s1", "e1", 10, "message.upserted", {"message_id": "m1", "status": "pending"})
        s1 = self.led.append(dict(e))
        s2 = self.led.append(dict(e))
        self.assertEqual(s1, s2)
        self.assertEqual(len(self.led.read("s1")), 1)

    def test_tool_and_opened_collapse_to_latest(self):
        sid = "s1"
        self.led.append(ev(sid, "t1", 10, "tool.upserted", {"tool_call_id": "c1", "status": "pending"}))
        self.led.append(ev(sid, "t2", 20, "tool.upserted", {"tool_call_id": "c1", "status": "completed"}))
        self.led.append(ev(sid, "o1", 5, "session.opened", {"title": "New Session"}, turn=None))
        self.led.append(ev(sid, "o2", 15, "session.opened", {"title": "fixed title"}, turn=None))
        got = [(r["event"]["type"],
                r["event"]["payload"].get("status") or r["event"]["payload"].get("title"))
               for r in self.led.read(sid)]
        self.assertEqual(sorted(got),
                         [("session.opened", "fixed title"), ("tool.upserted", "completed")])

    def test_unkeyed_events_stay_append_only(self):
        self.led.append(ev("s1", "u1", 10, "turn.started", {}, turn=1))
        self.led.append(ev("s1", "u2", 20, "turn.started", {}, turn=2))
        self.assertEqual(len(self.led.read("s1")), 2)


class MigrationTests(unittest.TestCase):
    def test_legacy_duplicates_collapse_on_boot(self):
        tmp = Path(tempfile.mkdtemp())
        conn = sqlite3.connect(str(tmp / "ata.sqlite"))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, title TEXT NOT NULL,
                turns INTEGER NOT NULL DEFAULT 0, last_seq INTEGER NOT NULL DEFAULT 0,
                last_ts INTEGER NOT NULL DEFAULT 0, first_ts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events (
                session_id TEXT NOT NULL, event_id TEXT NOT NULL, seq INTEGER NOT NULL,
                ts INTEGER NOT NULL, type TEXT NOT NULL, turn INTEGER, event_json TEXT NOT NULL,
                PRIMARY KEY (session_id, event_id), UNIQUE (session_id, seq));
        """)
        import time as _t
        base = {"v": 1, "agent_id": "pi", "session_id": "s1"}
        for eid, ts, status in (("e1", 10, "pending"), ("e2", 20, "completed")):
            conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                ("s1", eid, {"e1": 1, "e2": 2}[eid], ts, "message.upserted", 1,
                 json.dumps({**base, "id": eid, "ts": ts, "type": "message.upserted",
                             "turn": 1, "payload": {"message_id": "m1", "status": status}},
                            ensure_ascii=False)))
        conn.commit()
        conn.close()

        led = Ledger(tmp)  # 打开即触发 _boot 迁移
        rows = led.read("s1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"]["payload"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
