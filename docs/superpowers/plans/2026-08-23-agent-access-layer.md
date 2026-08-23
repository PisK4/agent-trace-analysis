# Agent Access Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给外部 Agent 打开 ATA 轨迹的机器读路径：扩展捕获增强（全文/耗时/失败状态/血缘/通道）、五个只读 API 端点、CLI `read`/`rate` 子命令、`session.scored` 标注事件。

**Architecture:** 全部改动落在现有三层上：`extensions/pi-atatrace/index.ts` 只加字段透传；`ata/plugins/pi.py` 翻译器补捕获语义；`ata/ledger.py` 加一列迁移；`ata/project.py` 加查询辅助函数；`ata/http.py` 挂新路由；新建 `ata/cli.py` 承载 CLI。写路径仍只有事件追加门一条。

**Tech Stack:** Python 3 标准库（sqlite3/http.server/urllib/unittest），TypeScript（pi 扩展，无构建步骤）。零新依赖。

**Spec:** `docs/specs/agent-read-interface.md`（接口形状以此为准）；决策背景见 `docs/wayfinder/tickets/T8-extension-capture.md` 与 `T9-human-annotation.md`。

## Global Constraints

- 纯 Python 标准库，禁止引入任何第三方依赖（含测试）。
- 事件 `v` 保持 `1`；schema 只做增量（新类型、payload 新可选字段、sessions 加列），不做破坏性变更。
- 同一账本同一时刻只有一个 writer：所有写入走服务进程的事件追加门，CLI 不直写 SQLite。
- 密钥、真实会话正文不得进入代码、fixture、日志、文档。
- 生产代码改动后必须：`make test` 全量通过 → `./scripts/install-service.sh restart` → `curl -s http://127.0.0.1:8787/api/health` 返回 `{"ok": true}`。
- 本机生产部署端口 17877、账本 `~/.ata/ata.sqlite`；开发默认 8787。
- 测试命令统一：`python3 -m unittest discover -s tests -v`（即 `make test`）。

---

### Task 1: Ledger 血缘列与查询方法

**Files:**
- Modify: `ata/ledger.py`（`_boot` 迁移段、`_append_locked` 的 session.opened 分支、`session`/`_session_row`、文件末尾新增两个方法）
- Test: `tests/test_lineage_ledger.py`（新建）

**Interfaces:**
- Produces: `Ledger.children(session_id: str) -> list[dict]`、`Ledger.ancestry(session_id: str) -> list[dict]`（行形状同 `_session_row`，另含 `"parent_session_id"` 键，可为 None）。后续 Task 8 的 lineage 端点消费这两个方法。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_lineage_ledger.py
import tempfile, unittest
from pathlib import Path
from ata.ledger import Ledger


def opened_ev(sid, title="t", parent=None):
    payload = {"title": title}
    if parent:
        payload["parent_session"] = parent
    return {"v": 1, "id": f"{sid}:opened", "agent_id": "pi", "session_id": sid,
            "ts": 1000, "type": "session.opened", "turn": None, "payload": payload}


class TestLineage(unittest.TestCase):
    def setUp(self):
        self.led = Ledger(Path(tempfile.mkdtemp()) / "t.sqlite")

    def test_parent_captured_on_open(self):
        self.led.append(opened_ev("child", parent="parent-1"))
        self.assertEqual(self.led.session("child")["parent_session_id"], "parent-1")

    def test_children_and_ancestry(self):
        self.led.append(opened_ev("root"))
        self.led.append(opened_ev("mid", parent="root"))
        self.led.append(opened_ev("leaf", parent="mid"))
        kids = self.led.children("root")
        self.assertEqual([r["id"] for r in kids], ["mid"])
        chain = self.led.ancestry("leaf")
        self.assertEqual([r["id"] for r in chain], ["mid", "root"])

    def test_no_parent_is_none_and_empty(self):
        self.led.append(opened_ev("solo"))
        self.assertIsNone(self.led.session("solo")["parent_session_id"])
        self.assertEqual(self.led.children("solo"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_lineage_ledger -v`
Expected: FAIL（KeyError: 'parent_session_id' 或 AttributeError: children）

- [ ] **Step 3: 最小实现**

`ata/ledger.py` `_boot` 迁移段（紧跟现有 `last_ts` 迁移之后追加）：

```python
        if "parent_session_id" not in {row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")}:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN parent_session_id TEXT")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id)")
```

`_append_locked` 中 session.opened 分支改为同时取父引用：

```python
        if event["type"] == "session.opened":
            title = event["payload"].get("title") or title
            parent = event["payload"].get("parent_session")
```

INSERT 与 UPDATE 两处语句各加一列 `parent_session_id`（INSERT 值用 `parent`，UPDATE 里 `parent_session_id=?` 参数同样传 `parent`——opened 重到时以后到者为准）。

`_session_row` 增加一字段：

```python
            "parent_session_id": r["parent_session_id"],
```

注意 `session()`/`sessions()` 的 SELECT 列清单要补 `parent_session_id`。

文件末尾（`close` 之前）新增：

```python
    def children(self, session_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, agent_id, title, turns, last_ts, parent_session_id"
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
        return [self.session(p) for p in reversed(ids)]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: 全部 PASS（含既有 27 个）

- [ ] **Step 5: Commit**

```bash
git add ata/ledger.py tests/test_lineage_ledger.py
git commit -m "feat(ledger): capture parent_session lineage with children/ancestry queries"
```

---

### Task 2: schema 增加 session.scored 标注事件

**Files:**
- Modify: `ata/schema.py`（`ALLOWED_TYPES`、`_check_payload`）
- Test: `tests/test_score_schema.py`（新建）

**Interfaces:**
- Produces: 事件类型 `"session.scored"` 合法；payload 必须含 `value ∈ {"good","bad","partial"}`，可选 `note` 字符串。Task 9 的 `build_score_event` 与 Task 11 的 rate 子命令依赖此校验。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_score_schema.py
import unittest
from ata.schema import parse_event, ValidationError


def scored(value, note=None):
    payload = {"value": value}
    if note is not None:
        payload["note"] = note
    return {"v": 1, "id": "x1", "agent_id": "cue", "session_id": "s1",
            "ts": 1000, "type": "session.scored", "turn": None, "payload": payload}


class TestScored(unittest.TestCase):
    def test_accepts_valid(self):
        ev = parse_event(scored("good", note="意图卡片方向对"))
        self.assertEqual(ev["type"], "session.scored")

    def test_rejects_bad_value(self):
        with self.assertRaises(ValidationError):
            parse_event(scored("excellent"))

    def test_rejects_missing_value(self):
        with self.assertRaises(ValidationError):
            parse_event(scored(None))

    def test_scored_requires_no_turn(self):
        raw = scored("bad")
        raw["turn"] = 2
        with self.assertRaises(ValidationError):
            parse_event(raw)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_score_schema -v`
Expected: FAIL（ValidationError: bad type）

- [ ] **Step 3: 最小实现**

`ata/schema.py`：

```python
ALLOWED_TYPES = {
    "session.opened",
    "turn.started",
    "message.upserted",
    "tool.upserted",
    "turn.ended",
    "session.closed",
    "system.upserted",
    "compaction.boundary",
    "session.scored",
}
```

`_check_payload` 末尾追加：

```python
    if typ == "session.scored":
        if p.get("value") not in {"good", "bad", "partial"}:
            raise ValidationError("bad score value")
        if "note" in p and not isinstance(p["note"], str):
            raise ValidationError("score note must be string")
```

注意：`parse_event` 已规定 `session.` 前缀类型 turn 必须为 null（`raw["type"].startswith("session.")` 分支），`session.scored` 自动落入该约束，测试第 4 例无需额外代码。

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ata/schema.py tests/test_score_schema.py
git commit -m "feat(schema): add session.scored annotation event type"
```

---

### Task 3: 翻译器 P0 —— 消息正文全文入库

**Files:**
- Modify: `ata/plugins/pi.py`（`translate_hook` 中两处 `[:200]` 截断）
- Test: `tests/test_pi_fulltext.py`（新建）

**Interfaces:**
- Produces: `message.upserted` 的 `payload.text` 为全文（user 与 assistant 一致）；无签名变化，Task 7 的查询函数直接受益。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pi_fulltext.py
import unittest
from ata.plugins.pi import translate_hook


def hook(name, event, state, **ctx):
    base = {"session_id": "s", "title": "s", "agent_id": "pi"}
    base.update(ctx)
    return translate_hook(name, event, base, state)


class TestFullText(unittest.TestCase):
    def test_user_text_not_truncated(self):
        long = "字" * 500
        st = {"opened": True, "turn": 0}
        hook("agent_start", {"timestamp": 1}, st)
        evs = hook("message_start", {"timestamp": 2,
                   "message": {"role": "user", "content": long}}, st)
        texts = [e["payload"]["text"] for e in evs if e["type"] == "message.upserted"]
        self.assertTrue(texts and len(texts[0]) == 500)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_pi_fulltext -v`
Expected: FAIL（长度为 200）

- [ ] **Step 3: 最小实现**

`ata/plugins/pi.py` 中两处改动：

```python
                "text": text,          # 原：(text or "")[:200]
```

（user 分支与 assistant 分支各一处；`output_text` 本就是全文，不动。）删除截断后 `text` 变量可能为空串，保持原 `(text or "")` 语义即可：`"text": text or ""`。

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: PASS（若既有断言依赖 200 截断，按新语义修正该断言并注明）

- [ ] **Step 5: Commit**

```bash
git add ata/plugins/pi.py tests/test_pi_fulltext.py
git commit -m "fix(pi): store full message text instead of 200-char preview"
```

---

### Task 4: 翻译器 P1 —— 真实耗时

**Files:**
- Modify: `ata/plugins/pi.py`
- Test: `tests/test_pi_duration.py`（新建）

**Interfaces:**
- Produces: `tool.upserted`（end 行）与 assistant `message.upserted`（end 行）的 `duration_ms` 为毫秒差值整数；pending 行保持 None。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pi_duration.py
import unittest
from ata.plugins.pi import translate_hook


def hook(name, event, state, **ctx):
    base = {"session_id": "s", "title": "s", "agent_id": "pi"}
    base.update(ctx)
    return translate_hook(name, event, base, state)


class TestDuration(unittest.TestCase):
    def test_tool_duration_from_ts_diff(self):
        st = {"opened": True, "turn": 1}
        hook("tool_execution_start",
             {"timestamp": 1000, "toolCallId": "c1", "toolName": "read", "args": {}}, st)
        evs = hook("tool_execution_end",
                   {"timestamp": 1250, "toolCallId": "c1", "toolName": "read",
                    "result": "ok", "isError": False}, st)
        end = [e for e in evs if e["type"] == "tool.upserted"][0]
        self.assertEqual(end["payload"]["duration_ms"], 250)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_pi_duration -v`
Expected: FAIL（得到占位值 1）

- [ ] **Step 3: 最小实现**

`ata/plugins/pi.py`：

tool start 分支，存参那行旁加：

```python
        state.setdefault("tool_start_ts", {})[cid] = ts
```

tool end 分支：

```python
        start_ts = state.get("tool_start_ts", {}).pop(cid, None)
        duration = max(int(ts) - int(start_ts), 0) if start_ts else 0
```

该分支 payload 的 `"duration_ms": 1` 改为 `"duration_ms": duration`；start 行保持 None。

assistant 消息：`message_start`（assistant 分支）定下 `mid` 后加：

```python
                state.setdefault("msg_start_ts", {})[mid] = ts
```

`message_end`（assistant 分支）在算完 usage 后加：

```python
        m_start = state.get("msg_start_ts", {}).get(mid)
        msg_dur = max(int(ts) - int(m_start), 0) if m_start else 0
```

该行 payload `"duration_ms": 1` 改为 `"duration_ms": msg_dur`。`turn_end` 的 assistant 复发行把 `"duration_ms": 1` 改为：

```python
                        "duration_ms": state.get("msg_dur", {}).get(mid),
```

并在 `message_end` 计算处顺带 `state.setdefault("msg_dur", {})[mid] = msg_dur`。

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ata/plugins/pi.py tests/test_pi_duration.py
git commit -m "feat(pi): derive real durations from hook timestamps"
```

---

### Task 5: 翻译器 P1 —— stopReason 映射 turn 失败状态

**Files:**
- Modify: `ata/plugins/pi.py`（`turn_end` 分支）
- Test: `tests/test_pi_turn_status.py`（新建）

**Interfaces:**
- Produces: `turn.ended.payload.status ∈ {"failed","cancelled"}`（仅当 stopReason 对应时才出现该键）。投影层 `project.py` 已消费该键，无需改。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pi_turn_status.py
import unittest
from ata.plugins.pi import translate_hook


def hook(name, event, state, **ctx):
    base = {"session_id": "s", "title": "s", "agent_id": "pi"}
    base.update(ctx)
    return translate_hook(name, event, base, state)


class TestTurnStatus(unittest.TestCase):
    def test_aborted_maps_to_cancelled(self):
        st = {"opened": True, "turn": 1}
        evs = hook("turn_end", {"timestamp": 9,
                   "message": {"role": "assistant", "stopReason": "aborted"}}, st)
        ended = [e for e in evs if e["type"] == "turn.ended"][0]
        self.assertEqual(ended["payload"]["status"], "cancelled")

    def test_normal_end_has_no_status_key(self):
        st = {"opened": True, "turn": 1}
        evs = hook("turn_end", {"timestamp": 9,
                   "message": {"role": "assistant", "stopReason": "stop"}}, st)
        ended = [e for e in evs if e["type"] == "turn.ended"][0]
        self.assertNotIn("status", ended["payload"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_pi_turn_status -v`
Expected: FAIL（KeyError: 'status'）

- [ ] **Step 3: 最小实现**

`ata/plugins/pi.py` `turn_end` 分支，组装 turn.ended 事件处：

```python
        stop = (msg.get("stopReason") if isinstance(msg, dict) else None)
        status = {"error": "failed", "aborted": "cancelled"}.get(stop)
        ended_payload = {"usage": usage}
        if status:
            ended_payload["status"] = status
        out.append(_ev(
            f"{session_id}:turn:{turn}:end", agent_id, session_id, ts,
            "turn.ended", turn, ended_payload,
        ))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ata/plugins/pi.py tests/test_pi_turn_status.py
git commit -m "feat(pi): surface failed/cancelled turn status from stopReason"
```

---

### Task 6: 血缘与通道透传（翻译器 + http + 扩展）

**Files:**
- Modify: `ata/http.py`（`_ingest_pi_hooks` 的 ctx 组装）、`ata/plugins/pi.py`（`agent_start` 分支）、`extensions/pi-atatrace/index.ts`
- Test: `tests/test_pi_lineage_channel.py`（新建）

**Interfaces:**
- Consumes: hook 请求体新增可选键 `channel: str`、`lineage: dict[str,str]`（由扩展发送）。
- Produces: `session.opened.payload` 可选键 `channel`、`parent_session`、`subagent`（dict）。Ledger（Task 1）消费 `parent_session`；下游数据集导出消费三者。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pi_lineage_channel.py
import unittest
from ata.plugins.pi import translate_hook


LINEAGE = {
    "PI_SUBAGENT_CHILD": "1",
    "PI_SUBAGENT_ORCHESTRATOR_SESSION_ID": "parent-abc",
    "PI_SUBAGENT_RUN_ID": "run-1",
    "PI_SUBAGENT_CHILD_AGENT": "scout",
    "PI_SUBAGENT_PARENT_DEPTH": "2",
}


def hook(name, event, state, **ctx):
    base = {"session_id": "s", "title": "s", "agent_id": "pi"}
    base.update(ctx)
    return translate_hook(name, event, base, state)


class TestLineageChannel(unittest.TestCase):
    def test_opened_carries_channel_parent_subagent(self):
        st = {}
        evs = hook("agent_start", {"timestamp": 1}, st,
                   channel="respond", lineage=LINEAGE)
        opened = [e for e in evs if e["type"] == "session.opened"][0]
        self.assertEqual(opened["payload"]["channel"], "respond")
        self.assertEqual(opened["payload"]["parent_session"], "parent-abc")
        sa = opened["payload"]["subagent"]
        self.assertEqual(sa["child_agent"], "scout")
        self.assertEqual(sa["depth"], "2")

    def test_absent_fields_omitted(self):
        st = {}
        evs = hook("agent_start", {"timestamp": 1}, st)
        opened = [e for e in evs if e["type"] == "session.opened"][0]
        for key in ("channel", "parent_session", "subagent"):
            self.assertNotIn(key, opened["payload"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_pi_lineage_channel -v`
Expected: FAIL（KeyError: 'channel'）

- [ ] **Step 3: 实现**

`ata/http.py` `_ingest_pi_hooks` 的 ctx 字典追加两个透传键：

```python
                "channel": raw.get("channel"),
                "lineage": raw.get("lineage") or {},
```

`ata/plugins/pi.py` `agent_start` 分支，组装 payload 处：

```python
        if name == "agent_start":
            if not state.get("opened"):
                state["opened"] = True
                title = ctx.get("title") or session_id
                state["title_set"] = title != session_id
                payload = {"title": title, **identity}
                if ctx.get("channel"):
                    payload["channel"] = str(ctx["channel"])
                lin = ctx.get("lineage") or {}
                parent = lin.get("PI_SUBAGENT_ORCHESTRATOR_SESSION_ID")
                if parent:
                    payload["parent_session"] = str(parent)
                if lin:
                    payload["subagent"] = {
                        "orchestrator_session": lin.get("PI_SUBAGENT_ORCHESTRATOR_SESSION_ID"),
                        "run_id": lin.get("PI_SUBAGENT_RUN_ID"),
                        "child_agent": lin.get("PI_SUBAGENT_CHILD_AGENT"),
                        "depth": lin.get("PI_SUBAGENT_PARENT_DEPTH"),
                    }
                out.append(_ev(
                    f"{session_id}:opened", agent_id, session_id, ts,
                    "session.opened", None, payload,
                ))
            return out
```

（原 payload 内联写法替换为此结构化版本。）

`extensions/pi-atatrace/index.ts`：常量区之后新增：

```typescript
const LINEAGE_ENV_KEYS = [
  "PI_SUBAGENT_CHILD",
  "PI_SUBAGENT_ORCHESTRATOR_SESSION_ID",
  "PI_SUBAGENT_RUN_ID",
  "PI_SUBAGENT_PARENT_ROOT_RUN_ID",
  "PI_SUBAGENT_PARENT_RUN_ID",
  "PI_SUBAGENT_CHILD_AGENT",
  "PI_SUBAGENT_PARENT_DEPTH",
  "PI_SUBAGENT_PARENT_PATH",
] as const;

function lineageFromEnv(): Record<string, string> | undefined {
  const out: Record<string, string> = {};
  for (const k of LINEAGE_ENV_KEYS) {
    const v = process.env[k];
    if (v) out[k] = v;
  }
  return Object.keys(out).length ? out : undefined;
}
```

`postHook` 调用处请求体追加两个字段（`JSON.stringify` 自动丢弃 undefined）：

```typescript
      await postHook({
        name,
        session_id,
        title,
        agent_id: ATA_CONFIG.agentId,
        host: ATA_CONFIG.host,
        runtime: ATA_CONFIG.runtime,
        channel: process.env.ATA_CHANNEL || undefined,
        lineage: lineageFromEnv(),
        event: jsonSafe(event),
      });
```

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ata/http.py ata/plugins/pi.py extensions/pi-atatrace/index.ts tests/test_pi_lineage_channel.py
git commit -m "feat(pi): propagate channel tag and subagent lineage through hooks"
```

---

### Task 7: 查询辅助函数（usage 汇总 / 工具清单 / 压缩清单 / 尾部预览）

**Files:**
- Modify: `ata/project.py`（文件末尾追加四个函数）
- Test: `tests/test_query_helpers.py`（新建）

**Interfaces:**
- Produces（Task 8/9/10 的 HTTP 层与 CLI 直接调用，签名如下）：
  - `summarize_usage(recs: list[dict]) -> dict`（recs 即 `ledger.read` 返回的 `[{"seq","event"}]`）
  - `list_tools(recs: list[dict], status: str|None, name: str|None) -> list[dict]`
  - `list_compactions(recs: list[dict]) -> list[dict]`
  - `tail_preview(text: str, n: int = 200) -> str`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_query_helpers.py
import unittest
from ata.project import summarize_usage, list_tools, list_compactions, tail_preview


def ev(seq, typ, turn, payload):
    return {"seq": seq, "event": {"v": 1, "id": f"e{seq}", "agent_id": "pi",
            "session_id": "s", "ts": seq, "type": typ, "turn": turn, "payload": payload}}


USAGE_OK = {"status": "reported", "input": 100, "output": 20, "cache_read": 5,
            "cache_write": 1, "total_tokens": 126, "cost": None}
USAGE_MISSING = {"status": "missing", "input": None, "output": None,
                 "cache_read": None, "cache_write": None, "total_tokens": None, "cost": None}


class TestSummarizeUsage(unittest.TestCase):
    def test_rows_totals_and_missing_count(self):
        recs = [
            ev(1, "message.upserted", 1, {"message_id": "a1", "role": "assistant",
               "model": "m", "usage": USAGE_OK}),
            ev(2, "message.upserted", 2, {"message_id": "a2", "role": "assistant",
               "model": "m", "usage": USAGE_MISSING}),
            ev(3, "turn.ended", 2, {"usage": USAGE_OK}),
        ]
        out = summarize_usage(recs)
        self.assertEqual(len(out["turns"]), 2)
        self.assertEqual(out["missing_turns"], 0)  # turn2 被 turn.ended 回填为 reported
        self.assertEqual(out["total"]["input"], 200)

    def test_permanent_missing_counts(self):
        recs = [ev(1, "message.upserted", 1, {"message_id": "a1", "role": "assistant",
                "usage": USAGE_MISSING})]
        out = summarize_usage(recs)
        self.assertEqual(out["missing_turns"], 1)
        self.assertEqual(out["total"]["input"], 0)


class TestLists(unittest.TestCase):
    def test_tools_filter_latest_wins(self):
        recs = [
            ev(1, "tool.upserted", 1, {"tool_call_id": "c1", "name": "read",
               "status": "pending", "result": None}),
            ev(2, "tool.upserted", 1, {"tool_call_id": "c1", "name": "read",
               "status": "failed", "result": "EACCES"}),
            ev(3, "tool.upserted", 1, {"tool_call_id": "c2", "name": "grep",
               "status": "completed", "result": "1 match"}),
        ]
        self.assertEqual(len(list_tools(recs, None, None)), 2)
        failed = list_tools(recs, "failed", None)
        self.assertEqual(failed[0]["id"], "c1")
        self.assertEqual(list_tools(recs, None, "grep")[0]["name"], "grep")

    def test_compactions(self):
        recs = [ev(5, "compaction.boundary", 3,
                {"trigger": "auto", "pre_tokens": 900, "post_tokens": 300,
                 "summary": "s" * 500})]
        rows = list_compactions(recs)
        self.assertEqual(rows[0]["trigger"], "auto")
        self.assertIn("…", rows[0]["summary"])

    def test_tail_preview(self):
        self.assertEqual(tail_preview("short"), "short")
        out = tail_preview("x" * 300)
        self.assertEqual(len(out), 201)
        self.assertTrue(out.startswith("…"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_query_helpers -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 最小实现**

`ata/project.py` 文件末尾追加：

```python
def tail_preview(text, n=200):
    if not isinstance(text, str) or len(text) <= n:
        return text
    return "…" + text[-n:]


def summarize_usage(recs):
    turn_rows = {}
    turn_fallback = {}
    for rec in recs:
        e = rec["event"]
        p = e["payload"]
        if e["type"] == "message.upserted" and p.get("role") == "assistant":
            t = e.get("turn")
            u = _usage(p.get("usage"))
            if t is None or u is None:
                continue
            if t not in turn_rows or turn_rows[t]["status"] != "reported":
                turn_rows[t] = {
                    "turn": t, "model": p.get("model"), "effort": p.get("effort"),
                    "status": u["status"], "input": u["input"], "output": u["output"],
                    "cache_read": u["cacheRead"], "cache_write": u["cacheWrite"],
                    "total_tokens": u["totalTokens"], "cost": u["cost"],
                }
        elif e["type"] == "turn.ended" and e.get("turn") is not None:
            u = _usage(p.get("usage"))
            if u is not None:
                turn_fallback[e["turn"]] = u
    for t, u in turn_fallback.items():
        row = turn_rows.setdefault(t, {"turn": t, "model": None, "effort": None})
        if row.get("status") != "reported":
            row.update({"status": u["status"], "input": u["input"], "output": u["output"],
                        "cache_read": u["cacheRead"], "cache_write": u["cacheWrite"],
                        "total_tokens": u["totalTokens"], "cost": u["cost"]})
    rows = [turn_rows[t] for t in sorted(turn_rows)]
    total = {"input": 0, "output": 0, "total_tokens": 0}
    missing = 0
    for r in rows:
        if r.get("status") == "reported":
            total["input"] += r["input"] or 0
            total["output"] += r["output"] or 0
            total["total_tokens"] += r["total_tokens"] or 0
        else:
            missing += 1
    return {"turns": rows, "total": total, "missing_turns": missing}


def list_tools(recs, status=None, name=None):
    latest = {}
    for rec in recs:
        e = rec["event"]
        if e["type"] != "tool.upserted":
            continue
        p = e["payload"]
        cid = p.get("tool_call_id")
        row = {
            "id": cid, "turn": e.get("turn"), "name": p.get("name"),
            "status": p.get("status"), "duration_ms": p.get("duration_ms"),
            "result": p.get("result"), "started_at": e["ts"],
        }
        if latest.get(cid, {}).get("status") == "pending" or cid not in latest:
            latest[cid] = row
        else:
            latest[cid].update(row)
    rows = [latest[c] for c in sorted(latest, key=lambda c: latest[c]["started_at"])]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if name:
        rows = [r for r in rows if r["name"] == name]
    return rows


def list_compactions(recs):
    rows = []
    for rec in recs:
        e = rec["event"]
        if e["type"] != "compaction.boundary":
            continue
        p = e["payload"]
        rows.append({"trigger": p.get("trigger"), "pre_tokens": p.get("pre_tokens"),
                     "post_tokens": p.get("post_tokens"), "summary": p.get("summary"),
                     "ts": e["ts"]})
    return rows
```

（注：测试 `test_tools_filter_latest_wins` 断言 failed 行保留——实现里 `latest[cid].update(row)` 保证 end 行覆盖 start 行。）

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ata/project.py tests/test_query_helpers.py
git commit -m "feat(project): add usage/tool/compaction query helpers with tail previews"
```

---

### Task 8: HTTP 端点 —— events 与 lineage

**Files:**
- Modify: `ata/http.py`（`do_GET` 的 `/api/sessions/` 分支重构 + 两个子路由）
- Test: `tests/test_http_new_routes.py`（新建，起临时端口打真实 HTTP）

**Interfaces:**
- Consumes: `Ledger.children/ancestry`（Task 1）、`ledger.read`。
- Produces: `GET /api/sessions/{sid}/events`、`GET /api/sessions/{sid}/lineage`，响应形状照 spec。Task 10 的 CLI 消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_http_new_routes.py
import json, tempfile, threading, unittest
import urllib.request
from pathlib import Path
from ata.http import make_server
from ata.ledger import Ledger


def opened(sid, parent=None):
    payload = {"title": sid}
    if parent:
        payload["parent_session"] = parent
    return {"v": 1, "id": f"{sid}:o", "agent_id": "pi", "session_id": sid,
            "ts": 1000, "type": "session.opened", "turn": None, "payload": payload}


class TestRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        led = Ledger(cls.tmp / "t.sqlite")
        led.append(opened("root"))
        led.append(opened("kid", parent="root"))
        led.append({"v": 1, "id": "m1", "agent_id": "pi", "session_id": "root",
                    "ts": 1001, "type": "message.upserted", "turn": 1,
                    "payload": {"message_id": "m1", "role": "user", "text": "hi",
                                "status": "completed"}})
        cls.httpd = make_server(led, cls.tmp, "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_events_cursor(self):
        code, out = self.get("/api/sessions/root/events?after_seq=1&limit=10")
        self.assertEqual(code, 200)
        self.assertEqual(out["ok"], True)
        self.assertEqual([e["seq"] for e in out["events"]], [2])
        self.assertEqual(out["next_after_seq"], 2)

    def test_events_unknown_session_404(self):
        code, out = self.get("/api/sessions/nope/events")
        self.assertEqual(code, 404)
        self.assertEqual(out["error"], "unknown session")

    def test_lineage_empty_is_ok(self):
        code, out = self.get("/api/sessions/root/lineage")
        self.assertEqual((code, out["ancestors"], out["children"]), (200, [], []))
        code, out = self.get("/api/sessions/kid/lineage")
        self.assertEqual([a["id"] for a in out["ancestors"]], ["root"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_http_new_routes -v`
Expected: FAIL（404 not found）

- [ ] **Step 3: 实现**

`ata/http.py` `do_GET` 中把现有 `path.startswith("/api/sessions/"):` 分支整体替换为：

```python
            if path.startswith("/api/sessions/"):
                rest = path[len("/api/sessions/"):]
                sid, _, sub = rest.partition("/")
                qs = parse_qs(parsed.query)
                meta = ledger.session(sid)
                if meta is None:
                    return self._json(404, {"ok": False, "error": "unknown session"})
                if sub == "":
                    limit = int(qs.get("limit", ["80"])[0])
                    before = qs.get("before", [None])[0]
                    before = int(before) if before not in (None, "") else None
                    recs = ledger.read(sid)
                    page = project_session(sid, meta["agent"], recs, tail=limit, before=before)
                    return self._json(200, page)
                if sub == "events":
                    after = int(qs.get("after_seq", ["0"])[0])
                    limit = min(int(qs.get("limit", ["100"])[0]), 500)
                    picked = [r for r in ledger.read(sid) if r["seq"] > after][:limit]
                    nxt = picked[-1]["seq"] if picked else after
                    return self._json(200, {"ok": True, "events": picked, "next_after_seq": nxt})
                if sub == "lineage":
                    return self._json(200, {"ok": True,
                                            "ancestors": ledger.ancestry(sid),
                                            "children": ledger.children(sid)})
                return self._json(404, {"ok": False, "error": "not found"})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: PASS（既有 Web 投影行为由 `sub == ""` 分支原样保留）

- [ ] **Step 5: Commit**

```bash
git add ata/http.py tests/test_http_new_routes.py
git commit -m "feat(http): raw-events cursor endpoint and lineage endpoint"
```

---

### Task 9: HTTP 端点 —— usage / tools / compactions

**Files:**
- Modify: `ata/http.py`（Task 8 分支里续接三个子路由）
- Test: 追加进 `tests/test_http_new_routes.py`

**Interfaces:**
- Consumes: `summarize_usage/list_tools/list_compactions/tail_preview`（Task 7）。
- Produces: 三个便捷层端点，响应形状照 spec（tools/compactions 的长文本默认尾部 200 预览，`full=true` 取全文）。

- [ ] **Step 1: 写失败测试（追加到 test_http_new_routes.py）**

```python
    def test_convenience_endpoints(self):
        led_events = [
            {"v": 1, "id": "u1", "agent_id": "pi", "session_id": "conv",
             "ts": 10, "type": "message.upserted", "turn": 1,
             "payload": {"message_id": "a1", "role": "assistant", "text": "done",
                         "status": "completed", "model": "m",
                         "usage": {"status": "reported", "input": 10, "output": 2,
                                   "cache_read": 0, "cache_write": 0,
                                   "total_tokens": 12, "cost": None}}},
            {"v": 1, "id": "t1", "agent_id": "pi", "session_id": "conv",
             "ts": 11, "type": "tool.upserted", "turn": 1,
             "payload": {"tool_call_id": "c1", "name": "read", "status": "failed",
                         "result": "EACCES", "duration_ms": 5}},
        ]
        # 直接经账本灌入（setUpClass 的 ledger 引用换成模块级持有）
```

说明：为让测试能灌事件，把 `setUpClass` 里 `led = Ledger(...)` 提升为 `cls.led`，再在本测试开头 `for e in led_events: cls.led.append(e)`，然后：

```python
        code, out = self.get("/api/sessions/conv/usage")
        self.assertEqual(code, 200)
        self.assertEqual(out["total"]["total_tokens"], 12)
        self.assertEqual(out["turns"][0]["model"], "m")
        code, out = self.get("/api/sessions/conv/tools?status=failed")
        self.assertEqual(out["tools"][0]["result"], "EACCES")
        code, out = self.get("/api/sessions/conv/compactions")
        self.assertEqual(out["compactions"], [])
```

（`compactions` 空数组断言依赖该会话没有压缩事件——返回 200 空列表即"存在但为空"。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_http_new_routes -v`
Expected: FAIL（404 not found）

- [ ] **Step 3: 实现**

`ata/http.py` 文件头部导入追加：

```python
from ata.project import list_compactions, list_tools, summarize_usage, tail_preview
```

Task 8 分支的 `return self._json(404, ...)` 之前续接：

```python
                if sub == "usage":
                    return self._json(200, {"ok": True,
                                            **summarize_usage(ledger.read(sid))})
                if sub == "tools":
                    full = qs.get("full", ["false"])[0] == "true"
                    rows = list_tools(ledger.read(sid),
                                      qs.get("status", [None])[0],
                                      qs.get("name", [None])[0])
                    for r in rows:
                        r["result"] = r["result"] if full else tail_preview(r["result"])
                    return self._json(200, {"ok": True, "tools": rows})
                if sub == "compactions":
                    full = qs.get("full", ["false"])[0] == "true"
                    rows = list_compactions(ledger.read(sid))
                    for r in rows:
                        r["summary"] = r["summary"] if full else tail_preview(r["summary"])
                    return self._json(200, {"ok": True, "compactions": rows})
```

（`parse_qs` 对 `?status=failed` 这类无值键返回字符串，对缺失键取 `[None][0]` 得 None——过滤逻辑兼容两者。）

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ata/http.py tests/test_http_new_routes.py
git commit -m "feat(http): usage, tools, compactions convenience endpoints"
```

---

### Task 10: CLI —— read 子命令（HTTP 默认 + --ledger 兜底）

**Files:**
- Create: `ata/cli.py`
- Modify: `ata/__main__.py`（`main()` 入口拦截）
- Test: `tests/test_cli_read.py`（新建）

**Interfaces:**
- Consumes: HTTP 端点（Task 8/9）；`--ledger` 模式复用 `Ledger` + Task 7 函数 + `project.project_session`。
- Produces: `python3 -m ata read <sessions|events|lineage|usage|tools|compactions> [...args]`，JSON 输出到 stdout；非零退出码表错误。

- [ ] **Step 1: 写失败测试（只测可离线跑的部分：参数解析与 --ledger 模式）**

```python
# tests/test_cli_read.py
import io, json, tempfile, contextlib, unittest
from pathlib import Path
from ata import cli
from ata.ledger import Ledger


class TestCliRead(unittest.TestCase):
    def setUp(self):
        self.led_dir = Path(tempfile.mkdtemp())
        led = Ledger(self.led_dir / "t.sqlite")
        led.append({"v": 1, "id": "o1", "agent_id": "pi", "session_id": "s1",
                    "ts": 1000, "type": "session.opened", "turn": None,
                    "payload": {"title": "demo"}})

    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["read", *argv, "--ledger", str(self.led_dir / "t.sqlite")])
        return json.loads(buf.getvalue())

    def test_sessions_local_mode(self):
        out = self.run_cli("sessions")
        self.assertEqual(out["sessions"][0]["id"], "s1")

    def test_usage_local_mode_shape(self):
        out = self.run_cli("usage", "s1")
        self.assertEqual(out["total"], {"input": 0, "output": 0, "total_tokens": 0})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_cli_read -v`
Expected: FAIL（ModuleNotFoundError: ata.cli）

- [ ] **Step 3: 实现**

新建 `ata/cli.py`：

```python
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8787"


def build_parser():
    p = argparse.ArgumentParser(prog="ata read")
    p.add_argument("what", choices=[
        "sessions", "events", "lineage", "usage", "tools", "compactions"])
    p.add_argument("sid", nargs="?", help="session id（sessions 子命令不需要）")
    p.add_argument("--agent")
    p.add_argument("--since-days", type=int)
    p.add_argument("--limit", type=int)
    p.add_argument("--after-seq", type=int)
    p.add_argument("--status", choices=["failed", "completed"])
    p.add_argument("--name")
    p.add_argument("--full", action="store_true")
    p.add_argument("--url", default=os.environ.get("ATA_URL") or DEFAULT_URL)
    p.add_argument("--ledger")
    return p


def _local(ledger_path, args):
    from ata.ledger import Ledger
    from ata.project import list_compactions, list_tools, summarize_usage
    led = Ledger(ledger_path)
    if args.what == "sessions":
        rows = led.sessions()
        if args.agent:
            rows = [r for r in rows if r["agent"] == args.agent]
        return {"ok": True, "sessions": rows}
    if not args.sid:
        sys.exit("error: sid required")
    if led.session(args.sid) is None:
        sys.exit('error: {"ok": false, "error": "unknown session"}')
    if args.what == "events":
        recs = [r for r in led.read(args.sid)
                if args.after_seq is None or r["seq"] > args.after_seq]
        if args.limit:
            recs = recs[: args.limit]
        return {"ok": True, "events": recs,
                "next_after_seq": recs[-1]["seq"] if recs else (args.after_seq or 0)}
    if args.what == "lineage":
        return {"ok": True, "ancestors": led.ancestry(args.sid),
                "children": led.children(args.sid)}
    if args.what == "usage":
        return {"ok": True, **summarize_usage(led.read(args.sid))}
    if args.what == "tools":
        rows = list_tools(led.read(args.sid), args.status, args.name)
        return {"ok": True, "tools": rows}
    return {"ok": True, "compactions": list_compactions(led.read(args.sid))}


def _remote(base, what, sid, args):
    q = []
    if args.after_seq is not None:
        q.append(f"after_seq={args.after_seq}")
    if args.limit:
        q.append(f"limit={args.limit}")
    if args.status:
        q.append(f"status={args.status}")
    if args.name:
        q.append(f"name={args.name}")
    if args.full:
        q.append("full=true")
    path = "/api/sessions" if what == "sessions" else f"/api/sessions/{sid}/{what}"
    url = base.rstrip("/") + path + ("?" + "&".join(q) if q else "")
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"error: {e.read().decode()}")
    except urllib.error.URLError as e:
        sys.exit(f"error: service unreachable ({e.reason}); "
                 f"try --ledger ~/.ata/ata.sqlite")


def apply_client_filters(data, args):
    if args.what == "sessions" and args.agent and "sessions" in data:
        data["sessions"] = [r for r in data["sessions"] if r["agent"] == args.agent]
    return data


def main(argv):
    args = build_parser().parse_args(argv)
    if args.ledger:
        data = _local(args.ledger, args)
    else:
        data = apply_client_filters(_remote(args.url, args.what, args.sid, args), args)
    print(json.dumps(data, ensure_ascii=False))
```

`ata/__main__.py` 的 `main(argv=None)` 第一行插入拦截：

```python
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"read", "rate"}:
        from ata.cli import main as cli_main
        return cli_main(argv)
    p = argparse.ArgumentParser()
```

（原 `argv=None` 时的处理保持不变，只是提前物化 argv。文件顶部需 `import sys`。）

- [ ] **Step 4: 跑测试确认通过 + 手动冒烟**

Run: `make test`
Expected: PASS

Run: `ATA_URL=http://127.0.0.1:17877 python3 -m ata read sessions --limit 2`
Expected: 打印生产账本的 JSON（服务在跑时）

- [ ] **Step 5: Commit**

```bash
git add ata/cli.py ata/__main__.py tests/test_cli_read.py
git commit -m "feat(cli): read subcommands over HTTP with --ledger offline fallback"
```

---

### Task 11: CLI —— rate 子命令（人工标注写入）

**Files:**
- Modify: `ata/cli.py`（追加 rate 解析与执行）、`ata/__main__.py`（拦截集合加 `"rate"`，已在 Task 10 完成）
- Test: `tests/test_cli_rate.py`（新建，测纯函数 build_score_event）

**Interfaces:**
- Consumes: `POST /api/events`（已有端点，schema 校验来自 Task 2）。
- Produces: `python3 -m ata rate <sid> --value good|bad|partial [--note "..."]`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli_rate.py
import unittest
from ata.cli import build_score_event
from ata.schema import parse_event


class TestBuildScoreEvent(unittest.TestCase):
    def test_valid_event_passes_schema(self):
        ev = build_score_event("cue", "s1", "good", note="卡片可用")
        parsed = parse_event(ev)
        self.assertEqual(parsed["payload"]["value"], "good")
        self.assertEqual(parsed["payload"]["note"], "卡片可用")

    def test_no_note_key_when_absent(self):
        ev = build_score_event("cue", "s1", "bad")
        self.assertNotIn("note", ev["payload"])

    def test_invalid_value_rejected_by_schema(self):
        from ata.schema import ValidationError
        ev = build_score_event("cue", "s1", "meh")
        with self.assertRaises(ValidationError):
            parse_event(ev)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_cli_rate -v`
Expected: FAIL（ImportError: build_score_event）

- [ ] **Step 3: 实现**

`ata/cli.py` 追加：

```python
import time
import uuid


def build_score_event(agent_id, session_id, value, note=None):
    payload = {"value": value}
    if note:
        payload["note"] = note
    return {"v": 1, "id": uuid.uuid4().hex, "agent_id": agent_id,
            "session_id": str(session_id), "ts": int(time.time() * 1000),
            "type": "session.scored", "turn": None, "payload": payload}


def post_json(base, path, body):
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)
```

`build_parser` 改造为两级：把现有 parser 包成 `parents` 或直接新建独立 parser。最小改法——`main` 开头分流：

```python
def main(argv):
    if argv and argv[0] == "rate":
        p = argparse.ArgumentParser(prog="ata rate")
        p.add_argument("sid")
        p.add_argument("--value", required=True, choices=["good", "bad", "partial"])
        p.add_argument("--note")
        p.add_argument("--url", default=os.environ.get("ATA_URL") or DEFAULT_URL)
        p.add_argument("--ledger")
        a = p.parse_args(argv[1:])
        if a.ledger:
            sys.exit("error: rate 是写操作，只能走服务（去掉 --ledger）")
        meta = _remote(a.url, "sessions", None, argparse.Namespace(
            what="sessions", sid=None, after_seq=None, limit=None,
            status=None, name=None, full=False))
        mine = next((r for r in meta.get("sessions", []) if r["id"] == a.sid), None)
        agent = mine["agent"] if mine else "pi"
        ev = build_score_event(agent, a.sid, a.value, a.note)
        result = post_json(a.url, "/api/events", {"events": [ev]})
        print(json.dumps(result, ensure_ascii=False))
        return
    args = build_parser().parse_args(argv)
    # …原有 read 流程不变…
```

（`_remote` 在 what=sessions 且 sid=None 时拼出的路径正确；Namespace 补齐了 read 用到的全部属性避免 AttributeError。）

- [ ] **Step 4: 跑测试确认通过 + 手动冒烟**

Run: `make test`
Expected: PASS

Run（服务在跑时）: `ATA_URL=http://127.0.0.1:17877 python3 -m ata rate <某个真实sid> --value good --note smoke && sqlite3 -readonly ~/.ata/ata.sqlite "SELECT type FROM events ORDER BY seq DESC LIMIT 1"`
Expected: 输出 `{"ok": true, ...}` 且末条事件为 `session.scored`

- [ ] **Step 5: Commit**

```bash
git add ata/cli.py tests/test_cli_rate.py
git commit -m "feat(cli): rate subcommand appends session.scored annotations"
```

---

### Task 12: 收尾 —— 全量回归、服务重建、真机验证

**Files:** 无新增改动；验证性任务。

- [ ] **Step 1: 全量测试**

Run: `make test`
Expected: 全部 PASS

- [ ] **Step 2: 重建常驻服务**

Run: `./scripts/install-service.sh restart && sleep 2 && curl -s http://127.0.0.1:8787/api/health`
Expected: `{"ok": true}`

- [ ] **Step 3: 真机验证清单（逐项记录结果）**

```bash
# ① 读路径冒烟
ATA_URL=http://127.0.0.1:17877 python3 -m ata read sessions --limit 3
# ② 带 subagent 委托的 Cue 会话：让 Cue 跑一次委托任务后，
#    查子会话是否带 parent_session：
sqlite3 -readonly ~/.ata/ata.sqlite \
  "SELECT session_id, event_json LIKE '%parent_session%' FROM events WHERE type='session.opened' ORDER BY seq DESC LIMIT 3"
# ③ 全文验证：新会话首条用户消息长度应 > 200 若原文更长
# ④ 标注闭环：ata rate <sid> --value good 后，Web UI 与 events 端点都能看到 session.scored
```

Expected: 四项全过；任何一项不过，回到对应 Task 修复后重跑 Step 1-2。

- [ ] **Step 4: 更新 wayfinder 票状态**

把 T8 各事项标记完成情况、T9 实施落地记录写回对应票文件的 Progress notes。

- [ ] **Step 5: Commit**

```bash
git add docs/wayfinder/
git commit -m "docs(wayfinder): record implementation verification results"
```

---

## Self-Review 记录

1. **Spec 覆盖**：spec 五端点（Task 8/9）、CLI 六子命令（Task 10）、rate（Task 11）、血缘列（Task 1）、session.scored（Task 2）、扩展五项增强（Task 3-6）——全覆盖。Skill 五节文档不在本计划（纯文档，随实施收尾单独成文）；Web UI 标注控件留待第二份计划（需先摸前端现状）。
2. **占位符扫描**：无 TBD/TODO；Task 12 为显式验证任务，允许无代码。
3. **类型一致性**：`_session_row` 新增键名 `parent_session_id` 在 Task 1 定义、Task 8 lineage 端点未直接引用该键（children/ancestry 返回行含它，向前兼容）；`tail_preview` 返回类型 str，Task 9 直接赋值回 result/summary；`summarize_usage` 输出键 `turns/total/missing_turns` 与 spec 响应一致。
