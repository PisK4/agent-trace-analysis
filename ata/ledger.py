from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


class Ledger:
    def __init__(self, root: Path):
        root = Path(root)
        if root.suffix in {".sqlite", ".db"}:
            self.path = root
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            root.mkdir(parents=True, exist_ok=True)
            self.path = root / "ata.sqlite"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._boot()

    def _boot(self):
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                title TEXT NOT NULL,
                turns INTEGER NOT NULL DEFAULT 0,
                last_seq INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_title ON sessions(title);
            CREATE TABLE IF NOT EXISTS events (
                session_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                type TEXT NOT NULL,
                turn INTEGER,
                event_json TEXT NOT NULL,
                PRIMARY KEY (session_id, event_id),
                UNIQUE (session_id, seq)
            );
            CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq);
            """
        )
        self._conn.commit()

    def append(self, event: dict) -> int:
        with self._lock:
            seq = self._append_locked(event)
            self._conn.commit()
            return seq

    def _append_locked(self, event: dict) -> int:
        """调用方必须已持有 _lock。返回 seq（重复 id 返回原 seq）。"""
        sid = event["session_id"]
        found = self._conn.execute(
            "SELECT seq FROM events WHERE session_id=? AND event_id=?",
            (sid, event["id"]),
        ).fetchone()
        if found:
            return int(found["seq"])
        row = self._conn.execute(
            "SELECT last_seq, title, turns FROM sessions WHERE session_id=?",
            (sid,),
        ).fetchone()
        seq = (int(row["last_seq"]) if row else 0) + 1
        title = (row["title"] if row else sid)
        turns = int(row["turns"]) if row else 0
        if event["type"] == "session.opened":
            title = event["payload"].get("title") or title
        turn = event.get("turn")
        if isinstance(turn, int) and turn > turns:
            turns = turn
        if row:
            self._conn.execute(
                "UPDATE sessions SET agent_id=?, title=?, turns=?, last_seq=? WHERE session_id=?",
                (event["agent_id"], title, turns, seq, sid),
            )
        else:
            self._conn.execute(
                "INSERT INTO sessions(session_id, agent_id, title, turns, last_seq) VALUES (?,?,?,?,?)",
                (sid, event["agent_id"], title, turns, seq),
            )
        self._conn.execute(
            "INSERT INTO events(session_id, event_id, seq, ts, type, turn, event_json) VALUES (?,?,?,?,?,?,?)",
            (sid, event["id"], seq, event["ts"], event["type"], turn, json.dumps(event, ensure_ascii=False)),
        )
        return seq

    def read(self, session_id: str) -> list[dict]:
        # 与 append 共用同一把锁：tail 线程持续写、HTTP 线程读，同一连接并发
        # execute 在 WAL 大写入时会段错误（本机复现过）。
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, event_json FROM events WHERE session_id=? ORDER BY seq",
                (session_id,),
            ).fetchall()
            return [{"seq": int(r["seq"]), "event": json.loads(r["event_json"])} for r in rows]

    def sessions(self) -> list[dict]:
        with self._lock:
            # last_ts = 该会话最新事件的毫秒时间戳，列表按最近活动倒序（新会话置顶）。
            rows = self._conn.execute(
                """
                SELECT s.session_id, s.agent_id, s.title, s.turns,
                       COALESCE((SELECT MAX(ts) FROM events e WHERE e.session_id = s.session_id), 0) AS last_ts
                FROM sessions s
                ORDER BY last_ts DESC, s.title
                """
            ).fetchall()
            return [
                {
                    "id": r["session_id"],
                    "agent": r["agent_id"],
                    "title": r["title"],
                    "turns": int(r["turns"]),
                    "last_ts": int(r["last_ts"]),
                }
                for r in rows
            ]

    def append_many(self, events: list[dict]) -> None:
        """一批事件一次事务提交；等价的重复 id 仍然返回，不重复写。"""
        self._lock.acquire()
        try:
            for event in events:
                self._append_locked(event)
            self._conn.commit()
        finally:
            self._lock.release()

    def close(self):
        self._conn.close()
