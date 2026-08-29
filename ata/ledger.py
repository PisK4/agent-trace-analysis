from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from ata.fold import REAL_TS_FLOOR, fold_session_meta
from ata.schema import parse_event
from ata.evaluation import fold_evaluation_events

_REAL_TS_FLOOR = REAL_TS_FLOOR


class ResetRequiredError(RuntimeError):
    """旧版全局 turn / regression schema 不能被静默解释为新版数据。"""



def _namespace(event: dict) -> str:
    """为自然键建立显式 run namespace，避免不同 Run 互相吞事件。"""
    run_id = event.get("run_id")
    if run_id is not None:
        return f"run:{run_id}"
    if event.get("observed_turn_ordinal") is not None:
        return "observed"
    return "runless"


def _dedupe_key(event: dict) -> str | None:
    """同一 namespace 内 latest-wins；没有自然键的事实保持追加。"""
    typ = event.get("type")
    payload = event.get("payload") or {}
    ns = _namespace(event)
    if typ == "message.upserted" and payload.get("message_id"):
        role = payload.get("role") or "unknown"
        return f"{ns}:{typ}:{role}:{payload['message_id']}"
    if typ == "tool.upserted" and payload.get("tool_call_id"):
        return f"{ns}:{typ}:{payload['tool_call_id']}"
    if typ == "session.opened":
        return f"runless:{typ}"
    if typ in {"run.started", "run.ended"} and event.get("run_id") is not None:
        external = payload.get("external_lifecycle_id")
        return f"{ns}:{typ}:{external if external is not None else event['id']}"
    if typ in {"turn.started", "turn.ended"}:
        turn = event.get("turn_number")
        if turn is not None:
            return f"{ns}:{typ}:{turn}"
    return None


class Ledger:
    """SQLite 事实账本；Session、Run projection 与事件共用一个 writer。"""

    def __init__(self, root: Path):
        root = Path(root)
        if root.suffix in {".sqlite", ".db"}:
            self.path = root
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            root.mkdir(parents=True, exist_ok=True)
            self.path = root / "ata.sqlite"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        try:
            self._boot()
        except Exception:
            self._conn.close()
            raise

    def _boot(self):
        """只允许新 schema；旧库必须由调用方备份后显式 reset。"""
        existing = {r[0] for r in self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "events" in existing:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(events)")}
            required = {"run_id", "turn_number", "observed_turn_ordinal"}
            if "turn" in cols or not required.issubset(cols):
                raise ResetRequiredError(
                    "legacy ledger schema detected; reset required before run-aware ledger starts"
                )
        if "sessions" in existing:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(sessions)")}
            if not {"last_ts", "first_ts", "parent_session_id"}.issubset(cols):
                raise ResetRequiredError(
                    "legacy session schema detected; reset required before run-aware ledger starts"
                )
        if "runs" in existing and "run_index" not in existing:
            raise ResetRequiredError(
                "legacy regression runs schema detected; reset required before run-aware ledger starts"
            )
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                title TEXT NOT NULL,
                turns INTEGER NOT NULL DEFAULT 0,
                last_seq INTEGER NOT NULL DEFAULT 0,
                last_ts INTEGER NOT NULL DEFAULT 0,
                first_ts INTEGER NOT NULL DEFAULT 0,
                parent_session_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_title ON sessions(title);
            CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
            CREATE TABLE IF NOT EXISTS events (
                session_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                type TEXT NOT NULL,
                run_id INTEGER,
                turn_number INTEGER,
                observed_turn_ordinal INTEGER,
                event_json TEXT NOT NULL,
                dedupe_key TEXT,
                PRIMARY KEY (session_id, event_id),
                UNIQUE (session_id, seq)
            );
            CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedupe
                ON events(session_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_events_run
                ON events(session_id, run_id, turn_number, seq);
            CREATE TABLE IF NOT EXISTS run_index (
                session_id TEXT NOT NULL,
                run_id INTEGER NOT NULL,
                external_lifecycle_id TEXT,
                status TEXT NOT NULL,
                started_seq INTEGER,
                ended_seq INTEGER,
                started_ts INTEGER,
                ended_ts INTEGER,
                max_turn_number INTEGER NOT NULL DEFAULT 0,
                conflict_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (session_id, run_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_run_external
                ON run_index(session_id, external_lifecycle_id)
                WHERE external_lifecycle_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS evaluation_events (
                evaluation_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                type TEXT NOT NULL,
                event_json TEXT NOT NULL,
                PRIMARY KEY (evaluation_id, event_id),
                UNIQUE (evaluation_id, seq)
            );
            CREATE INDEX IF NOT EXISTS idx_evaluation_events_id_seq
                ON evaluation_events(evaluation_id, seq);
            """
        )
        self._conn.commit()

    def append(self, event: dict) -> int:
        with self._lock:
            # 入口统一校验，保留旧调用方的 envelope 兼容但不接受旧字段。
            event = parse_event(event)
            seq = self._append_locked(event)
            self._conn.commit()
            return seq

    def _append_locked(self, event: dict) -> int:
        """调用方持有锁；重复 event_id 返回原 seq。"""
        if "turn" in event:
            raise ValueError("legacy turn field removed; use turn_number")
        sid = str(event["session_id"])
        event_id = str(event["id"])
        found = self._conn.execute(
            "SELECT seq FROM events WHERE session_id=? AND event_id=?", (sid, event_id)
        ).fetchone()
        if found:
            return int(found["seq"])
        row = self._conn.execute(
            "SELECT agent_id, last_seq, title, turns, last_ts, first_ts, parent_session_id "
            "FROM sessions WHERE session_id=?", (sid,)
        ).fetchone()
        seq = (int(row["last_seq"]) if row else 0) + 1
        existing = None if row is None else {
            "title": row["title"], "renamed": False,
            "turns": int(row["turns"]), "last_ts": int(row["last_ts"] or 0),
            "first_ts": int(row["first_ts"] or 0),
            "parent_session_id": row["parent_session_id"],
        }
        folded = fold_session_meta(existing, event)
        if row:
            self._conn.execute(
                "UPDATE sessions SET agent_id=?, title=?, turns=?, last_seq=?, "
                "last_ts=?, first_ts=?, parent_session_id=? WHERE session_id=?",
                (row["agent_id"], folded["title"], folded.get("turns", 0), seq,
                 folded["last_ts"], folded["first_ts"], folded.get("parent_session_id"), sid),
            )
        else:
            self._conn.execute(
                "INSERT INTO sessions(session_id,agent_id,title,turns,last_seq,last_ts,first_ts,parent_session_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (sid, event["agent_id"], folded["title"], 0, seq,
                 folded["last_ts"], folded["first_ts"], folded.get("parent_session_id")),
            )
        dk = _dedupe_key(event)
        old = None if dk is None else self._conn.execute(
            "SELECT seq FROM events WHERE session_id=? AND dedupe_key=?", (sid, dk)
        ).fetchone()
        values = (sid, event_id, seq, int(event["ts"]), event["type"], event.get("run_id"),
                  event.get("turn_number"), event.get("observed_turn_ordinal"),
                  json.dumps(event, ensure_ascii=False), dk)
        if old:
            # 新 seq 代表最新投影；event_id 保留旧事实身份以避免重复重放扩散。
            self._conn.execute(
                "UPDATE events SET seq=?,ts=?,type=?,run_id=?,turn_number=?,"
                "observed_turn_ordinal=?,event_json=? WHERE session_id=? AND dedupe_key=?",
                (seq, int(event["ts"]), event["type"], event.get("run_id"),
                 event.get("turn_number"), event.get("observed_turn_ordinal"), values[8], sid, dk),
            )
        else:
            self._conn.execute(
                "INSERT INTO events(session_id,event_id,seq,ts,type,run_id,turn_number,"
                "observed_turn_ordinal,event_json,dedupe_key) VALUES (?,?,?,?,?,?,?,?,?,?)", values
            )
        self._refresh_turn_count_locked(sid)
        self._project_run_locked(sid, event.get("run_id"))
        return seq

    def _refresh_turn_count_locked(self, session_id: str):
        """刷新兼容的 Session turns 聚合，不把它当作 Turn identity。"""
        rows = self._conn.execute(
            "SELECT run_id,turn_number,observed_turn_ordinal FROM events "
            "WHERE session_id=? AND (turn_number IS NOT NULL OR observed_turn_ordinal IS NOT NULL)",
            (session_id,),
        ).fetchall()
        identities = {
            (r["run_id"], r["turn_number"])
            for r in rows if r["run_id"] is not None and r["turn_number"] is not None
        }
        identities.update(
            (None, r["observed_turn_ordinal"])
            for r in rows if r["run_id"] is None and r["observed_turn_ordinal"] is not None
        )
        self._conn.execute(
            "UPDATE sessions SET turns=? WHERE session_id=?",
            (len(identities), session_id),
        )

    def _project_run_locked(self, session_id: str, run_id: int | None):
        """从事实重建 Run projection，避免乱序事件污染增量索引。"""
        run_ids = [r[0] for r in self._conn.execute(
            "SELECT DISTINCT run_id FROM events WHERE session_id=? AND run_id IS NOT NULL",
            (session_id,),
        )]
        if not run_ids:
            return
        later_started = {rid: any(
            r["type"] == "run.started" and int(r["run_id"]) > rid
            for r in self._conn.execute(
                "SELECT type,run_id FROM events WHERE session_id=? AND run_id IS NOT NULL",
                (session_id,),
            )) for rid in run_ids}
        conflict_rows = self._conn.execute(
            "SELECT event_json FROM events WHERE session_id=? AND type='run.lifecycle.conflict'",
            (session_id,),
        ).fetchall()
        for current_id in run_ids:
            rows = self._conn.execute(
                "SELECT seq,ts,type,event_json,turn_number FROM events "
                "WHERE session_id=? AND run_id=? ORDER BY seq", (session_id, current_id)
            ).fetchall()
            starts = [r for r in rows if r["type"] == "run.started"]
            if not starts:
                continue
            ends = [r for r in rows if r["type"] == "run.ended"]
            start, end = starts[-1], (ends[-1] if ends else None)
            external = (json.loads(start["event_json"]).get("payload") or {}).get("external_lifecycle_id")
            max_turn = max((int(r["turn_number"]) for r in rows if r["turn_number"] is not None), default=0)
            status = "ended" if end else ("incomplete" if later_started[current_id] else "open")
            conflict_count = sum(
                1 for r in conflict_rows
                if external is not None
                and (json.loads(r["event_json"]).get("payload") or {}).get("external_lifecycle_id") == external
            )
            self._conn.execute(
                "INSERT INTO run_index(session_id,run_id,external_lifecycle_id,status,started_seq,ended_seq,"
                "started_ts,ended_ts,max_turn_number,conflict_count) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(session_id,run_id) DO UPDATE SET external_lifecycle_id=excluded.external_lifecycle_id,"
                "status=excluded.status,started_seq=excluded.started_seq,ended_seq=excluded.ended_seq,"
                "started_ts=excluded.started_ts,ended_ts=excluded.ended_ts,max_turn_number=excluded.max_turn_number,"
                "conflict_count=excluded.conflict_count",
                (session_id, int(current_id), external, status, int(start["seq"]),
                 int(end["seq"]) if end else None, int(start["ts"]), int(end["ts"]) if end else None,
                 max_turn, conflict_count),
            )

    def append_many(self, events: list[dict]) -> list[int]:
        with self._lock:
            try:
                seqs = [self._append_locked(parse_event(event)) for event in events]
                self._conn.commit()
                return seqs
            except Exception:
                self._conn.rollback()
                raise

    def read(self, session_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq,event_json FROM events WHERE session_id=? ORDER BY seq", (session_id,)
            ).fetchall()
        return [{"seq": int(r["seq"]), "event": json.loads(r["event_json"])} for r in rows]

    def session(self, session_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id,agent_id,title,turns,last_seq,last_ts,first_ts,parent_session_id "
                "FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        return None if row is None else self._session_row(row)

    def sessions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id,agent_id,title,turns,last_seq,last_ts,first_ts,parent_session_id "
                "FROM sessions ORDER BY first_ts DESC,title"
            ).fetchall()
            counts = self._conn.execute(
                "SELECT session_id,COUNT(*) event_count,SUM(CASE WHEN type='tool.upserted' "
                "AND json_extract(event_json,'$.payload.status')='failed' THEN 1 ELSE 0 END) error_count "
                "FROM events GROUP BY session_id"
            ).fetchall()
        by_sid = {r["session_id"]: r for r in counts}
        return [{**self._session_row(r), "event_count": int(by_sid[r["session_id"]]["event_count"]) if r["session_id"] in by_sid else 0,
                 "error_count": int(by_sid[r["session_id"]]["error_count"] or 0) if r["session_id"] in by_sid else 0} for r in rows]

    @staticmethod
    def _session_row(row) -> dict:
        return {"id": row["session_id"], "agent": row["agent_id"], "title": row["title"],
                "turns": int(row["turns"] or 0), "last_seq": int(row["last_seq"] or 0),
                "last_ts": int(row["last_ts"] or 0), "first_ts": int(row["first_ts"] or 0),
                "parent_session_id": row["parent_session_id"]}

    def children(self, session_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id,agent_id,title,turns,last_seq,last_ts,first_ts,parent_session_id "
                "FROM sessions WHERE parent_session_id=? ORDER BY last_ts", (session_id,)
            ).fetchall()
        return [self._session_row(r) for r in rows]

    def ancestry(self, session_id: str) -> list[dict]:
        out, seen, current = [], {session_id}, session_id
        while True:
            row = self.session(current)
            parent = (row or {}).get("parent_session_id")
            if not parent or parent in seen:
                return out
            seen.add(parent)
            current = parent
            parent_row = self.session(parent)
            if parent_row:
                out.append(parent_row)

    def runs(self, session_id: str | None = None) -> list[dict]:
        with self._lock:
            sql = "SELECT * FROM run_index"
            args: tuple = ()
            if session_id is not None:
                sql += " WHERE session_id=?"
                args = (session_id,)
            sql += " ORDER BY session_id,run_id"
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def run(self, session_id: str, run_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM run_index WHERE session_id=? AND run_id=?", (session_id, run_id)).fetchone()
        return None if row is None else dict(row)

    def open_runs(self, session_id: str) -> list[dict]:
        return [r for r in self.runs(session_id) if r["status"] == "open"]

    def _score_rows(self) -> list[dict]:
        """折叠 Session score facts，并附带只读会话统计。"""
        with self._lock:
            metas = self._conn.execute(
                "SELECT s.session_id,s.agent_id,s.title,COALESCE(c.event_count,0) event_count,"
                "COALESCE(c.error_count,0) error_count FROM sessions s LEFT JOIN ("
                "SELECT session_id,COUNT(*) event_count,SUM(CASE WHEN type='tool.upserted' "
                "AND json_extract(event_json,'$.payload.status')='failed' THEN 1 ELSE 0 END) error_count "
                "FROM events GROUP BY session_id) c ON c.session_id=s.session_id"
            ).fetchall()
            events = self._conn.execute(
                "SELECT session_id,seq,ts,type,event_json FROM events "
                "WHERE type IN ('session.scored','session.score.cleared') ORDER BY seq"
            ).fetchall()
        by_session = {}
        for row in metas:
            by_session[row["session_id"]] = {
                "session_id": row["session_id"], "agent": row["agent_id"],
                "title": row["title"], "event_count": int(row["event_count"]),
                "error_count": int(row["error_count"] or 0), "score": None,
            }
        for row in events:
            item = by_session.get(row["session_id"])
            if item is None:
                continue
            if row["type"] == "session.score.cleared":
                item["score"] = None
            else:
                payload = json.loads(row["event_json"]).get("payload") or {}
                item["score"] = {
                    "value": payload.get("value"), "note": payload.get("note"),
                    "ts": int(row["ts"]), "seq": int(row["seq"]),
                }
        result = []
        for item in by_session.values():
            score = item.pop("score")
            if score is not None:
                result.append({**item, **score})
        return sorted(result, key=lambda item: item["ts"], reverse=True)

    def scores(self) -> list[dict]:
        """返回每个 Session 的最新 score；score 是 Session-level fact。"""
        return self._score_rows()

    def score_events(self) -> list[dict]:
        """返回 score facts 的最新 Session-level 视图。"""
        return self._score_rows()

    def assign_events(self) -> list[dict]:
        """历史内部调用的空结果；assignment 已不属于公开 Runtime API。"""
        return []

    def _append_evaluation_locked(self, fact: dict) -> int:
        """调用方必须持有 _lock；Evaluation seq 独立于 Session seq。"""
        eid = fact["evaluation_id"]
        found = self._conn.execute(
            "SELECT seq FROM evaluation_events WHERE evaluation_id=? AND event_id=?",
            (eid, fact["id"]),
        ).fetchone()
        if found:
            return int(found["seq"])
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM evaluation_events WHERE evaluation_id=?",
            (eid,),
        ).fetchone()
        seq = int(row["seq"]) + 1
        self._conn.execute(
            "INSERT INTO evaluation_events(evaluation_id, event_id, seq, ts, type, event_json)"
            " VALUES (?,?,?,?,?,?)",
            (eid, fact["id"], seq, fact["ts"], fact["type"],
             json.dumps(fact, ensure_ascii=False)),
        )
        return seq

    def append_evaluation(self, fact: dict) -> int:
        """追加 Evaluation fact，并应用 EvaluationStore 的状态守卫。"""
        from ata.evaluation import EvaluationStore

        return EvaluationStore(self).append(fact)

    def append_evaluation_event(self, fact: dict) -> int:
        """Evaluation fact 追加的显式名称。"""
        return self.append_evaluation(fact)

    def read_evaluation_events(self, evaluation_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, event_json FROM evaluation_events"
                " WHERE evaluation_id=? ORDER BY seq", (evaluation_id,)
            ).fetchall()
        return [{"seq": int(row["seq"]), "event": json.loads(row["event_json"])} for row in rows]

    # 兼容较短的领域名；facts 仍以带 seq 的记录返回，便于审计与折叠。
    def evaluation_events(self, evaluation_id: str) -> list[dict]:
        return self.read_evaluation_events(evaluation_id)

    def read_evaluation(self, evaluation_id: str) -> list[dict]:
        """Evaluation facts 的公开短名。"""
        return self.read_evaluation_events(evaluation_id)

    def _all_evaluation_records_locked(self):
        rows = self._conn.execute(
            "SELECT evaluation_id, seq, event_json FROM evaluation_events ORDER BY evaluation_id, seq"
        ).fetchall()
        records = {}
        for row in rows:
            records.setdefault(row["evaluation_id"], []).append({
                "seq": int(row["seq"]), "event": json.loads(row["event_json"])
            })
        return records.items()

    def _fold_evaluation_locked(self, evaluation_id: str):
        records = [records for eid, records in self._all_evaluation_records_locked()
                    if eid == evaluation_id]
        return fold_evaluation_events(evaluation_id, records[0] if records else [])

    def fold_evaluation(self, evaluation_id: str) -> dict | None:
        with self._lock:
            return self._fold_evaluation_locked(evaluation_id)

    def close(self):
        self._conn.close()


# 兼容旧调用方的名称；自然键实现仍只有上面的一个入口。
__all__ = ["Ledger", "ResetRequiredError", "_dedupe_key"]

