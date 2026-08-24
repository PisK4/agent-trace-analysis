from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

# 毫秒时间戳低于此值的视为脏数据（历史推送端写过 ts=1 的 opened 事件），
# 不参与创建时间的判定。
_REAL_TS_FLOOR = 10 ** 12


def _dedupe_key(event: dict) -> str | None:
    """自然键幂等：同实体的多次快照只留最新一行。翻译层对不同阶段发的
    确定性 event id（:message_start/:message_end/:end）由此收敛；
    session.opened 的标题纠正同键折叠，与投影层 last-write-wins 一致。
    无自然键的事件保持追加式。"""
    typ = event.get("type")
    payload = event.get("payload") or {}
    if typ == "message.upserted" and payload.get("message_id"):
        return f"{typ}:{payload['message_id']}"
    if typ == "tool.upserted" and payload.get("tool_call_id"):
        return f"{typ}:{payload['tool_call_id']}"
    if typ == "session.opened":
        return f"{typ}:"
    return None


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
        if "dedupe_key" not in {row[1] for row in self._conn.execute("PRAGMA table_info(events)")}:
            # 存量迁移：补自然键并把同键旧行坍缩为最新一条（已确认不保留快照史），
            # 再用部分唯一索引约束后续写入。只在新列首次加入时执行一次。
            self._conn.execute("ALTER TABLE events ADD COLUMN dedupe_key TEXT")
            self._conn.execute(
                """
                UPDATE events SET dedupe_key = CASE
                    WHEN type='message.upserted'
                         AND json_extract(event_json,'$.payload.message_id') IS NOT NULL
                        THEN type || ':' || json_extract(event_json,'$.payload.message_id')
                    WHEN type='tool.upserted'
                         AND json_extract(event_json,'$.payload.tool_call_id') IS NOT NULL
                        THEN type || ':' || json_extract(event_json,'$.payload.tool_call_id')
                    WHEN type='session.opened' THEN type || ':'
                    ELSE NULL
                END
                """
            )
            self._conn.execute(
                """
                DELETE FROM events WHERE dedupe_key IS NOT NULL AND seq < (
                    SELECT MAX(e2.seq) FROM events e2
                    WHERE e2.session_id = events.session_id
                      AND e2.dedupe_key = events.dedupe_key)
                """
            )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedupe"
            " ON events(session_id, dedupe_key) WHERE dedupe_key IS NOT NULL"
        )
        self._conn.commit()

    def append(self, event: dict) -> int:
        with self._lock:
            seq = self._append_locked(event)
            self._conn.commit()
            return seq

    def _has_renamed(self, session_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM events WHERE session_id=? AND type='session.renamed' LIMIT 1",
            (session_id,)).fetchone()
        return row is not None

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
        renamed = title != sid and bool(row) and self._has_renamed(sid)
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
            # 用户改过名（renamed）后，opened 的标题只做兜底，不再覆盖
            if not renamed:
                title = event["payload"].get("title") or title
            parent = event["payload"].get("parent_session")
        elif event["type"] == "session.renamed":
            # 用户改名：与 opened 同走投影索引 latest-wins，后续 opened 不再覆盖
            title = event["payload"].get("title") or title
            renamed = True
        elif event["type"] == "session.renamed":
            # 用户改名：与 opened 同走投影索引 latest-wins，后续 opened 不再覆盖
            # （opened 只在 title 为空时兜底，见上）。
            title = event["payload"].get("title") or title
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
        dk = _dedupe_key(event)
        existed = None
        if dk:
            existed = self._conn.execute(
                "SELECT seq FROM events WHERE session_id=? AND dedupe_key=?",
                (sid, dk),
            ).fetchone()
        if existed:
            # 同自然键：整行替换为最新快照。seq 用新号保证 read 按 seq 排序时
            # 最新态排在最后；旧行的 event_id 列保留原值，读方一律以 event_json 为准。
            self._conn.execute(
                "UPDATE events SET seq=?, ts=?, turn=?, event_json=? WHERE session_id=? AND dedupe_key=?",
                (seq, event["ts"], turn, json.dumps(event, ensure_ascii=False), sid, dk),
            )
        else:
            self._conn.execute(
                "INSERT INTO events(session_id, event_id, seq, ts, type, turn, event_json, dedupe_key)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (sid, event["id"], seq, event["ts"], event["type"], turn,
                 json.dumps(event, ensure_ascii=False), dk),
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
            # 侧栏卡片 meta 行要事件数与失败工具数：json_extract 走 event_json，
            # 单行扫描；会话量大时这里仍是 O(全部事件)，可接受（本机账本量级）。
            counts = self._conn.execute(
                """
                SELECT session_id,
                       COUNT(*) AS event_count,
                       SUM(CASE WHEN type='tool.upserted'
                                 AND json_extract(event_json,'$.payload.status')='failed'
                            THEN 1 ELSE 0 END) AS error_count
                FROM events
                GROUP BY session_id
                """
            ).fetchall()
        by_sid = {r["session_id"]: r for r in counts}
        out = []
        for r in rows:
            c = by_sid.get(r["session_id"])
            out.append({
                **self._session_row(r),
                "event_count": int(c["event_count"]) if c else 0,
                "error_count": int(c["error_count"] or 0) if c else 0,
            })
        return out

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

    def annotations(self) -> dict:
        """标注板聚合读取：latest-wins 折叠墓碑后的有效标注/归组，附会话元信息。

        返回 {scores: [{session_id, value, note, ts, agent, title, event_count,
        error_count}], assignments: [{session_id, run_id, task_id, ts, agent,
        title, event_count, error_count}]}，各自按 ts 倒序。
        墓碑：session.score.cleared 清标注；session.unassigned 清归组
        （run_id+session_id 粒度，同会话同 run 的全部 task 一起移除）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, seq, ts, type, event_json FROM events"
                " WHERE type IN ('session.scored','session.score.cleared',"
                "                'session.assigned','session.unassigned')"
                " ORDER BY seq").fetchall()
            metas = {
                r["session_id"]: r for r in self._conn.execute(
                    "SELECT s.session_id, s.agent_id, s.title, s.last_ts, s.first_ts,"
                    " COALESCE(c.event_count,0) AS event_count,"
                    " COALESCE(c.error_count,0) AS error_count"
                    " FROM sessions s LEFT JOIN ("
                    "   SELECT session_id, COUNT(*) AS event_count,"
                    "   SUM(CASE WHEN type='tool.upserted'"
                    "              AND json_extract(event_json,'$.payload.status')='failed'"
                    "            THEN 1 ELSE 0 END) AS error_count"
                    "   FROM events GROUP BY session_id) c"
                    " ON c.session_id = s.session_id").fetchall()
            }
        scores: dict[str, dict] = {}
        # 归组键 run_id+session_id：unassigned 墓碑按此粒度整组撤销
        assigns: dict[tuple, dict] = {}
        for r in rows:
            payload = json.loads(r["event_json"])["payload"]
            sid = r["session_id"]
            if r["type"] == "session.scored":
                scores[sid] = {"session_id": sid, "value": payload.get("value"),
                               "note": payload.get("note"), "ts": int(r["ts"]),
                               "seq": int(r["seq"])}
            elif r["type"] == "session.score.cleared":
                scores.pop(sid, None)
            elif r["type"] == "session.assigned":
                assigns[(payload.get("run_id"), sid)] = {
                    "session_id": sid, "run_id": payload.get("run_id"),
                    "task_id": payload.get("task_id"), "ts": int(r["ts"]),
                    "seq": int(r["seq"])}
            elif r["type"] == "session.unassigned":
                assigns.pop((payload.get("run_id"), sid), None)
        def enrich(item):
            m = metas.get(item["session_id"])
            if m:
                item.update({"agent": m["agent_id"], "title": m["title"],
                             "event_count": int(m["event_count"]),
                             "error_count": int(m["error_count"])})
            else:
                # 会话元数据缺失（理论不可达）：仍返回条目，前端按未知渲染
                item.update({"agent": None, "title": item["session_id"],
                             "event_count": 0, "error_count": 0})
            return item
        return {
            "scores": sorted((enrich(s) for s in scores.values()),
                             key=lambda s: s["ts"], reverse=True),
            "assignments": sorted((enrich(a) for a in assigns.values()),
                                  key=lambda a: a["ts"], reverse=True),
        }
