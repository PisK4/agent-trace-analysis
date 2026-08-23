from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

# 毫秒时间戳低于此值的视为脏数据（历史推送端写过 ts=1 的 opened 事件），
# 不参与创建时间的判定。
_REAL_TS_FLOOR = 10 ** 12


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
                last_seq INTEGER NOT NULL DEFAULT 0,
                last_ts INTEGER NOT NULL DEFAULT 0,
                first_ts INTEGER NOT NULL DEFAULT 0
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
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                taskset_fingerprint TEXT,
                created_ts INTEGER NOT NULL
            );
            """
        )
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")}
        if "last_ts" not in cols:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN last_ts INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.execute(
                """
                UPDATE sessions SET last_ts = COALESCE(
                    (SELECT MAX(ts) FROM events e WHERE e.session_id = sessions.session_id), 0)
                """
            )
        if "first_ts" not in {row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")}:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN first_ts INTEGER NOT NULL DEFAULT 0"
            )
            # 部分历史 session.opened 事件带异常小 ts，回填时忽略，
            # 只信正常量级的 ts；全无则退回 last_ts，保证卡片有值可显。
            self._conn.execute(
                """
                UPDATE sessions SET first_ts = COALESCE(
                    (SELECT MIN(ts) FROM events e WHERE e.session_id = sessions.session_id
                     AND e.ts > ?), last_ts)
                """,
                (_REAL_TS_FLOOR,),
            )
        if "parent_session_id" not in {row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")}:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN parent_session_id TEXT")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id)")
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
            "SELECT last_seq, title, turns, last_ts, first_ts, parent_session_id FROM sessions WHERE session_id=?",
            (sid,),
        ).fetchone()
        seq = (int(row["last_seq"]) if row else 0) + 1
        title = (row["title"] if row else sid)
        turns = int(row["turns"]) if row else 0
        last_ts = int(event["ts"])
        if row:
            last_ts = max(int(row["last_ts"] or 0), last_ts)
        # 创建时间取最早的真实事件 ts；异常小值（如 1）不参与，避免显示成 1970 年，
        # 已存在的异常存量值也一并设防。
        first_ts = int(event["ts"]) if int(event["ts"]) > _REAL_TS_FLOOR else 0
        if row:
            existing_first = int(row["first_ts"] or 0)
            if existing_first > _REAL_TS_FLOOR:
                first_ts = min(existing_first, first_ts) if first_ts else existing_first
        # 非 opened 事件必须保留已有父引用，否则后续 UPDATE 会把血缘抹成 NULL。
        parent = row["parent_session_id"] if row else None
        if event["type"] == "session.opened":
            title = event["payload"].get("title") or title
            parent = event["payload"].get("parent_session")
        turn = event.get("turn")
        if isinstance(turn, int) and turn > turns:
            turns = turn
        if row:
            self._conn.execute(
                "UPDATE sessions SET agent_id=?, title=?, turns=?, last_seq=?, last_ts=?, first_ts=?, parent_session_id=? WHERE session_id=?",
                (event["agent_id"], title, turns, seq, last_ts, first_ts, parent, sid),
            )
        else:
            self._conn.execute(
                "INSERT INTO sessions(session_id, agent_id, title, turns, last_seq, last_ts, first_ts, parent_session_id) VALUES (?,?,?,?,?,?,?,?)",
                (sid, event["agent_id"], title, turns, seq, last_ts, first_ts, parent),
            )
        self._conn.execute(
            "INSERT INTO events(session_id, event_id, seq, ts, type, turn, event_json) VALUES (?,?,?,?,?,?,?)",
            (sid, event["id"], seq, event["ts"], event["type"], turn, json.dumps(event, ensure_ascii=False)),
        )
        return seq

    def read(self, session_id: str) -> list[dict]:
        # 与 append 共用同一把锁：tail 线程持续写、HTTP 线程读，同一连接并发
        # execute 在 WAL 大写入时会段错误（本机复现过）。json.loads 放到锁外。
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, event_json FROM events WHERE session_id=? ORDER BY seq",
                (session_id,),
            ).fetchall()
        return [{"seq": int(r["seq"]), "event": json.loads(r["event_json"])} for r in rows]

    def session(self, session_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id, agent_id, title, turns, last_ts, first_ts, parent_session_id FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        return None if row is None else self._session_row(row)

    def sessions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT session_id, agent_id, title, turns, last_ts, first_ts, parent_session_id
                FROM sessions
                ORDER BY first_ts DESC, title
                """
            ).fetchall()
        return [self._session_row(r) for r in rows]

    @staticmethod
    def _session_row(r) -> dict:
        return {
            "id": r["session_id"],
            "agent": r["agent_id"],
            "title": r["title"],
            "turns": int(r["turns"]),
            "last_ts": int(r["last_ts"] or 0),
            "first_ts": int(r["first_ts"] or 0),
            "parent_session_id": r["parent_session_id"],
        }

    def children(self, session_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, agent_id, title, turns, last_ts, first_ts, parent_session_id"
                " FROM sessions WHERE parent_session_id=? ORDER BY last_ts",
                (session_id,),
            ).fetchall()
        return [self._session_row(r) for r in rows]

    def ancestry(self, session_id: str) -> list[dict]:
        ids: list[str] = []
        seen = {session_id}
        cur = session_id
        while True:
            row = self.session(cur)
            parent = (row or {}).get("parent_session_id")
            if not parent or parent in seen:
                break
            seen.add(parent)
            ids.append(parent)
            cur = parent
        # ids 按收集顺序即最近祖先在前，与 children 的就近语义一致。
        return [self.session(p) for p in ids]

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

    # ---- 实验轮次（run）：轮次级事实不属于任何会话，落专用表；
    # 写入仍只经 Ledger 这一个 writer，与事件追加门同级。

    def create_run(self, run_id: str, description: str,
                   taskset_fingerprint: str | None = None, ts: int | None = None) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO runs(run_id, description, taskset_fingerprint, created_ts)"
                    " VALUES (?,?,?,?)",
                    (run_id, description, taskset_fingerprint,
                     int(ts if ts is not None else time.time() * 1000)),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError("duplicate run_id") from None

    def run(self, run_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id, description, taskset_fingerprint, created_ts"
                " FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return None if row is None else {
            "run_id": row["run_id"], "description": row["description"],
            "taskset_fingerprint": row["taskset_fingerprint"],
            "created_ts": int(row["created_ts"]),
        }

    def runs(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, description, taskset_fingerprint, created_ts"
                " FROM runs ORDER BY created_ts").fetchall()
        return [{"run_id": r["run_id"], "description": r["description"],
                 "taskset_fingerprint": r["taskset_fingerprint"],
                 "created_ts": int(r["created_ts"])} for r in rows]

    def assign_events(self) -> list[dict]:
        """全部 session.assigned 事件的展平视图：{session_id, seq, ts, run_id, task_id}。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, seq, ts, event_json FROM events"
                " WHERE type='session.assigned' ORDER BY seq").fetchall()
        out = []
        for r in rows:
            payload = json.loads(r["event_json"])["payload"]
            out.append({"session_id": r["session_id"], "seq": int(r["seq"]),
                        "ts": int(r["ts"]), **payload})
        return out
