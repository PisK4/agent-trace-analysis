import tempfile
import unittest
from pathlib import Path

from ata.ledger import Ledger
from ata.schema import parse_event

EV = parse_event({
    "v": 1, "id": "e1", "agent_id": "pi", "session_id": "s1",
    # 毫秒级真实量级 ts；ledger 会把异常小值当作脏数据忽略
    "ts": 1787000000010, "type": "session.opened", "turn": None,
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
            # event_count/error_count 供侧栏卡片 meta 行（卡片分诊列）
            self.assertEqual(listing, [{
                "id": "s1",
                "agent": "pi",
                "title": "hello",
                "turns": 0,
                "last_seq": 1,
                "last_ts": 1787000000010,
                "first_ts": 1787000000010,
                "parent_session_id": None,
                "event_count": 1,
                "error_count": 0,
            }])

    def test_sessions_count_events_and_failed_tools(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            led.append(EV)
            led.append(parse_event({
                "v": 1, "id": "t1", "agent_id": "pi", "session_id": "s1",
                "ts": 1787000000020, "type": "tool.upserted", "turn": 1,
                "payload": {"tool_call_id": "c1", "name": "Bash", "status": "failed"},
            }))
            led.append(parse_event({
                "v": 1, "id": "t2", "agent_id": "pi", "session_id": "s1",
                "ts": 1787000000025, "type": "tool.upserted", "turn": 1,
                "payload": {"tool_call_id": "c2", "name": "Read", "status": "completed"},
            }))
            row = led.sessions()[0]
            self.assertEqual(row["event_count"], 3)
            self.assertEqual(row["error_count"], 1)

    def test_sessions_ordered_by_created_desc(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            led.append(EV)  # s1, 创建于 1787000000010
            led.append(parse_event({
                "v": 1, "id": "e1", "agent_id": "droid", "session_id": "s2",
                "ts": 1787000000030, "type": "session.opened", "turn": None,
                "payload": {"title": "newer"},
            }))
            # s1 追加更晚事件：列表按创建时间倒序，s2 仍在前；last_ts 各自跟踪最新活动
            led.append(parse_event({
                "v": 1, "id": "a1", "agent_id": "pi", "session_id": "s1",
                "ts": 1787000000040, "type": "message.upserted", "turn": 1,
                "payload": {"message_id": "m1", "role": "assistant", "text": "x",
                            "status": "completed", "request_no": 1, "usage": None,
                            "started_at": 1787000000040, "duration_ms": 1, "output_text": "x"},
            }))
            ids = [s["id"] for s in led.sessions()]
            self.assertEqual(ids, ["s2", "s1"])
            self.assertEqual([s["first_ts"] for s in led.sessions()], [1787000000030, 1787000000010])
            self.assertEqual([s["last_ts"] for s in led.sessions()], [1787000000030, 1787000000040])
            self.assertEqual(led.session("s1")["agent"], "pi")
            self.assertIsNone(led.session("nope"))

    def test_first_ts_ignores_bogus_small_ts(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            led.append(parse_event({
                "v": 1, "id": "bad", "agent_id": "pi", "session_id": "sb",
                "ts": 1, "type": "session.opened", "turn": None,
                "payload": {"title": "bogus"},
            }))
            self.assertEqual(led.session("sb")["first_ts"], 0)
            # 随后到达的真实事件成为创建时间
            led.append(parse_event({
                "v": 1, "id": "good", "agent_id": "pi", "session_id": "sb",
                "ts": 1787000000050, "type": "message.upserted", "turn": 1,
                "payload": {"message_id": "m1", "role": "assistant", "text": "x",
                            "status": "completed", "request_no": 1, "usage": None,
                            "started_at": 1787000000050, "duration_ms": 1, "output_text": "x"},
            }))
            self.assertEqual(led.session("sb")["first_ts"], 1787000000050)

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
            # first_ts 回填：无更早信息时以 MIN(events.ts) 为创建时间
            self.assertEqual(led.session("s1")["first_ts"], 77)


if __name__ == "__main__":
    unittest.main()
