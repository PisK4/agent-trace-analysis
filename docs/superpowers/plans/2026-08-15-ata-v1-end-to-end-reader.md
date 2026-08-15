# Atatrace v1 首段打通 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本仓 `AGENTS.md` 禁止 `subagent-driven-development`；实现时先跑 `/ponytail full`，再按本计划改 `repos/ata/`。不要改 `sketches/002-beautiful-workbench/`。

**Goal:** 在空的 `repos/ata` 里做出可验收的本地阅读器：插件写出规范事件，内核落盘并分页，浏览器打开的 Atatrace 用 02 的表面把真实投影画出来。

**Architecture:** 一个 Python 3 标准库进程同时管账本、投影和静态页。Pi / Droid 插件只做方言翻译，经 `POST /api/events` 追加。阅读器只拉投影，不回源厂商文件。02 是像素合同，生产复制它的 HTML/CSS/手势，只换数据入口。

**Tech Stack:** Python 3.12 stdlib（`http.server` / `unittest` / `json` / `pathlib`）；浏览器端原样复制 02 的单文件 UI；Pi 官方 TypeScript extension（pin `845d6ff1`）；Droid 适配器读调用方显式传入的 JSONL 路径。

---

## 0. 本计划钉死的默认（实现时不要重开）

交接里还开着的问题，本切片全部给默认值。要改，先改本计划再写代码。

| 题目 | 默认 |
| --- | --- |
| spec 字段名 | 本计划第 1 节就是 v1 首段冻结名。未列出的键内核拒收 |
| SYSTEM / tools catalog 快照 | **不发射**。02 检查器代码保留，账本里没有 `kind:"system"` 行 |
| Compaction / Spawn | **不发射**。不挂 `before_agent_start` / `session_compact` / `session_start` 的父子字段 |
| Compare / AVA Evidence | 不做 |
| 实时通道 | 跟随尾部用 1s 轮询，不上 SSE |
| 前端框架 | 不引入 React/Vite。复制 02 |
| 内核是否打开 `~/.factory` | **否**。只有 Droid 适配器在传入 `--droid-path` 时打开该路径 |
| 验收是否依赖本机真实 Pi/Droid 会话 | **否**。主验收吃合成 fixture。真机是手工加分项 |
| `estimated` | 首段不产生。助手行要么 `reported`，要么 `missing`；非助手行 `n/a` |
| `message_update` / `tool_execution_update` | 首段不转发。只在 start/end 各写一次 upsert |
| 工具 Schema / subtool | 首段不填。检查器走 02 已有空态 |
| TTFT | 首段不填。检查器显示 `First token unavailable` |

本切片验收通过的定义：下面「验收门」每一条都能在本机复现。不是「骨架能跑」。

---

## 文件地图

实现后仓库长这样。`sketches/` 只读。

```text
repos/ata/
  ata/
    __init__.py
    __main__.py              # python -m ata serve
    schema.py                # 校验规范事件
    ledger.py                # 单 writer 追加 + 按 seq 分页
    project.py               # 事件 → 02 session.rows
    http.py                  # stdlib HTTP
    plugins/
      droid.py               # JSONL → 事件
      pi.py                  # Pi hook 字典 → 事件（纯函数，供测试与日后对照）
  extensions/pi-atatrace/
    index.ts                 # 真正挂进 Pi 的 extension
  web/
    index.html               # 02 的复制，只改数据入口
  testdata/
    events/pi-compact.jsonl
    events/droid-missing.jsonl
    events/pi-long.jsonl
    vendor/droid-sample.jsonl
    vendor/pi-hooks.json
  tests/
    test_schema.py
    test_ledger.py
    test_project.py
    test_droid.py
    test_pi.py
    test_http.py
```

---

## 1. 冻结的写路径：规范事件

一行事件就是内核收下的最小单位。插件写它，内核存它，阅读器不直接画它。

```json
{
  "v": 1,
  "id": "pi:sess1:msg:a1:end",
  "agent_id": "pi",
  "session_id": "pi-compact",
  "ts": 1786694320380,
  "type": "message.upserted",
  "turn": 1,
  "payload": {}
}
```

| 字段 | 规则 |
| --- | --- |
| `v` | 必须是 `1` |
| `id` | 插件生成，会话内唯一。重复 `id` 当幂等成功，不改已写入的那一行 |
| `agent_id` | `pi` 或 `droid`。缺了拒收 |
| `session_id` | 非空字符串。缺了拒收 |
| `ts` | Unix 毫秒。缺了拒收 |
| `type` | 下表六种之一 |
| `turn` | 整数或 `null`。`session.*` 用 `null`；其余必须是正整数 |
| `payload` | 必须是对象 |

`type` 与 `payload`：

| `type` | `payload` | 谁写 |
| --- | --- | --- |
| `session.opened` | `{ "title": "..." }` | 插件在第一次看见会话时 |
| `turn.started` | `{}` | Pi `turn_start`；Droid 在该轮第一条 `message` 之前补一条 |
| `message.upserted` | 见下 | 用户/助手消息的 start 与 end |
| `tool.upserted` | 见下 | 工具 start 与 end。按 `tool_call_id` 配对 |
| `turn.ended` | `{ "usage": Usage \| null }` | Pi `turn_end`；Droid `agent_turn_outcome`（`usage` 恒为 `null`） |
| `session.closed` | `{}` | Pi `agent_end`。Droid 首段可以不写 |

`message.upserted.payload`：

```json
{
  "message_id": "a1",
  "role": "assistant",
  "text": "JSONL 样本没有 token 字段，第一期标 Missing",
  "status": "completed",
  "request_no": 1,
  "usage": {
    "status": "reported",
    "input": 1840,
    "output": 612,
    "cache_read": 220,
    "cache_write": 48,
    "total_tokens": 2720,
    "cost": null
  },
  "started_at": 1786694320380,
  "duration_ms": 920,
  "output_text": "第一期标 Missing"
}
```

| 键 | 规则 |
| --- | --- |
| `message_id` | 稳定行 id，投影后就是 02 的 `row.id` |
| `role` | `user` / `assistant` |
| `text` | 账本文案，可截到 200 字；全文放 `output_text` |
| `status` | `pending` / `completed` / `failed` |
| `request_no` | 助手可填正整数；用户必须 `null` |
| `usage` | 仅助手。用户必须 `null` |
| `started_at` | 毫秒 |
| `duration_ms` | 进行中为 `null` |
| `output_text` | 可 `null` |

`tool.upserted.payload`：

```json
{
  "tool_call_id": "t4",
  "parent_message_id": "a3",
  "name": "Grep",
  "text": "pattern: \"cue\"",
  "status": "completed",
  "payload": { "pattern": "cue", "path": "ledger.md" },
  "result": "Found 1 match",
  "started_at": 1786694323378,
  "duration_ms": 233
}
```

`Usage`：

```json
{
  "status": "reported",
  "input": 1840,
  "output": 612,
  "cache_read": 220,
  "cache_write": 48,
  "total_tokens": 2720,
  "cost": null
}
```

Pi 的 `turn_end.message.usage` 是 `reported` 的唯一来源。若 `stopReason` 为 `error` / `aborted` 且 `input/output/cacheRead/cacheWrite` 全是 `0`，写成 `status:"missing"`，四个计数为 `null`。禁止把 `AgentToolResult.usage` 或 Droid `*.settings.json` 写进这条。

内核落盘时给每一行盖 `seq`（从 1 起的单调整数）。存储是一份 SQLite：`<ledger_dir>/ata.sqlite`。默认目录 `./data`，测试传入临时目录。

两张表：`sessions(session_id, agent_id, title, turns, last_seq)` 带 `title` 索引；`events` 按 `(session_id, seq)` 追加。会话列表只读 `sessions`，不再为 title 扫事件。

---

## 2. 冻结的读路径：02 投影

`project.py` 把一个会话的事件扫成 02 已经在画的 `session` 对象。前端不再认识规范事件。

```js
{
  id: "pi-compact",
  agent: "pi",
  title: "synthetic pi turn",
  crumb: "pi · <b>synthetic pi turn</b>",
  has_older: false,
  cursor: 18,
  rows: [ /* 02 row */ ]
}
```

行映射：

| 02 字段 | 来源 |
| --- | --- |
| `id` | `message_id` 或 `tool_call_id` |
| `index` | 本页投影后的数组下标，每次返回都重算 |
| `turn` | 事件上的 `turn` |
| `step` | 该 turn 里第几次 `role=assistant` 的 upsert；工具继承当前 step |
| `start` | 该 turn 投影出的第一行 |
| `kind` / `tag` | `user`/`USER`，`assistant`/`ASSISTANT`，`tool`/`TOOL` |
| `text` | payload.`text` |
| `name` | 工具名 |
| `parentId` | `parent_message_id` |
| `requestNo` | `request_no` |
| `group` | `"Step " + step`（step 为 0 则省略） |
| `startedAt` | `started_at` |
| `durationMs` | `duration_ms ?? 0` |
| `status` | 原样 |
| `usage` | 助手：把 `cache_read` 写成 `cacheRead`；无 usage 则 `{status:"missing",...null}`。其它行 `{status:"n/a",...null}` |
| `payload` / `result` / `outputText` / `payloadText` | 工具用 `payload`/`result`；用户 `payloadText=text`；助手 `outputText` |
| `ttftMs` / `decodingMs` / `schema` / `promptText` | 首段不填 |

投影规则：

1. 按 `seq` 扫。同一 `message_id` / `tool_call_id` 后写覆盖前写（upsert）。
2. 行顺序 = 该实体第一次出现的 `seq`。
3. 没看见 `turn.started` 就遇到消息时，用该事件的 `turn` 补一条虚拟 turn 边界，只影响 `start`，不发明事件。
4. `turn.ended.usage` 若助手行还没有 `reported`，写到该 turn 最后一条助手行上。
5. 不输出 `kind:"summary"`。折叠摘要仍由 02 前端现场生成。

---

## 3. HTTP（进程内唯一 writer）

`python -m ata serve --port 8787 --ledger ./data`

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/` | `web/index.html` |
| `GET` | `/api/health` | `{"ok":true}` |
| `GET` | `/api/sessions` | 会话索引 |
| `GET` | `/api/sessions/{id}?limit=80` | 尾页投影 |
| `GET` | `/api/sessions/{id}?before={seq}&limit=36` | 更早一页 |
| `POST` | `/api/events` | 追加一条或 `{"events":[...]}` |

`GET /api/sessions`：

```json
[
  { "id": "pi-compact", "agent": "pi", "title": "synthetic pi turn", "turns": 2 }
]
```

`turns` = 投影里 `start===true` 的行数。

`POST /api/events` 成功：`{"ok":true,"seq":4}`。校验失败：`400` + `{"ok":false,"error":"..."}`。重复 `id`：`200` + 原 `seq`。

内核线程对同一个 `session_id` 的写要加锁。阅读器只读。

不要做鉴权、CORS 放开即可（本机）。不要在日志里打印 `payload.text` 全文，只打 `type/id/session_id`。

---

## 验收门（做完必须全绿）

在仓库根目录：

```bash
python -m unittest discover -s tests -v
python -m ata serve --port 8787 --ledger testdata/events
```

另开一个壳：

```bash
curl -s localhost:8787/api/health
curl -s localhost:8787/api/sessions
curl -s localhost:8787/api/sessions/pi-compact | python -c 'import json,sys; d=json.load(sys.stdin); assert d["rows"]; assert any(r["kind"]=="assistant" and r["usage"]["status"]=="reported" for r in d["rows"])'
curl -s localhost:8787/api/sessions/droid-missing | python -c 'import json,sys; d=json.load(sys.stdin); assert any(r["kind"]=="assistant" and r["usage"]["status"]=="missing" for r in d["rows"])'
curl -s localhost:8787/api/sessions/pi-long | python -c 'import json,sys; d=json.load(sys.stdin); assert d["has_older"] is True; assert len(d["rows"])==80'
curl -s 'localhost:8787/api/sessions/pi-long?before='$(curl -s localhost:8787/api/sessions/pi-long | python -c 'import json,sys; print(min(r["_seq"] for r in json.load(sys.stdin)["rows"]))') | python -c 'import json,sys; d=json.load(sys.stdin); assert d["rows"]'
```

浏览器打开 `http://127.0.0.1:8787/`，对照 02，不对照 dsh 产品名：

| # | 动作 | 必须看见 |
| --- | --- | --- |
| B1 | 左侧会话列表 | `pi-compact` 与 `droid-missing`（以及 `pi-long`）来自 API，不是写死在 HTML 里 |
| B2 | 打开 `pi-compact` | 账本停在尾部；三列；有 T 芯片；助手 usage 在检查器里是数字 |
| B3 | 打开 `droid-missing` | 助手 Usage 格子写 `Missing`，不是 `0` |
| B4 | Duration / Actual time | `modeChip` 依次变成 `duration` / `time` / `actual` / `sequence`；切投影清掉时间窗 |
| B5 | 滚轮缩放、放大后右键拖、横拖闭区间 | 窗外行变淡；Escape 清除 |
| B6 | Turns / Calls、双击 | 折叠摘要行出现 |
| B7 | 打开 `pi-long`，点 `Load earlier history` 或左侧 `…` | 更早行前置，滚动位置不跳到顶 |
| B8 | 事件列小圆点 | Request 检查器打开，行选中不变 |
| B9 | `POST` 一条新 `message.upserted` 到当前会话 | 跟随开启时 1s 内账本尾部出现新行 |

合成 fixture 只许用占位句子（`user asks to mark missing usage` 这种），不许粘贴真实 session / `~/.factory` / AVA `records.jsonl` 正文。

---

### Task 1: 事件校验

**Files:**
- Create: `ata/__init__.py`
- Create: `ata/schema.py`
- Create: `tests/test_schema.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_schema.py
import unittest
from ata.schema import ValidationError, parse_event

MIN = {
    "v": 1,
    "id": "e1",
    "agent_id": "pi",
    "session_id": "s1",
    "ts": 1,
    "type": "session.opened",
    "turn": None,
    "payload": {"title": "t"},
}


class SchemaTest(unittest.TestCase):
    def test_ok(self):
        ev = parse_event(MIN)
        self.assertEqual(ev["type"], "session.opened")

    def test_reject_missing_agent(self):
        bad = dict(MIN)
        del bad["agent_id"]
        with self.assertRaises(ValidationError):
            parse_event(bad)

    def test_reject_unknown_type(self):
        bad = dict(MIN, type="hook.PreToolUse")
        with self.assertRaises(ValidationError):
            parse_event(bad)

    def test_reject_user_usage(self):
        bad = dict(
            MIN,
            type="message.upserted",
            turn=1,
            payload={
                "message_id": "u1",
                "role": "user",
                "text": "hi",
                "status": "completed",
                "request_no": None,
                "usage": {"status": "reported", "input": 1, "output": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 1, "cost": None},
                "started_at": 1,
                "duration_ms": 1,
                "output_text": None,
            },
        )
        with self.assertRaises(ValidationError):
            parse_event(bad)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m unittest tests.test_schema -v`

Expected: `ModuleNotFoundError` 或 `ValidationError` 未定义。

- [ ] **Step 3: 最小实现**

`ata/__init__.py` 留空。`ata/schema.py`：

```python
ALLOWED_TYPES = {
    "session.opened",
    "turn.started",
    "message.upserted",
    "tool.upserted",
    "turn.ended",
    "session.closed",
}
ALLOWED_AGENTS = {"pi", "droid"}
USAGE_KEYS = ("status", "input", "output", "cache_read", "cache_write", "total_tokens", "cost")


class ValidationError(ValueError):
    pass


def parse_event(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("event must be object")
    for key in ("v", "id", "agent_id", "session_id", "ts", "type", "payload"):
        if key not in raw:
            raise ValidationError(f"missing {key}")
    if raw["v"] != 1:
        raise ValidationError("v must be 1")
    if raw["agent_id"] not in ALLOWED_AGENTS:
        raise ValidationError("bad agent_id")
    if not raw["session_id"] or not raw["id"]:
        raise ValidationError("empty id")
    if not isinstance(raw["ts"], (int, float)):
        raise ValidationError("bad ts")
    if raw["type"] not in ALLOWED_TYPES:
        raise ValidationError("bad type")
    if not isinstance(raw["payload"], dict):
        raise ValidationError("payload must be object")
    turn = raw.get("turn", None)
    if raw["type"].startswith("session."):
        if turn is not None:
            raise ValidationError("session turn must be null")
    elif not isinstance(turn, int) or turn < 1:
        raise ValidationError("turn must be positive int")
    _check_payload(raw["type"], raw["payload"])
    return {
        "v": 1,
        "id": str(raw["id"]),
        "agent_id": raw["agent_id"],
        "session_id": str(raw["session_id"]),
        "ts": int(raw["ts"]),
        "type": raw["type"],
        "turn": turn,
        "payload": raw["payload"],
    }


def _check_payload(typ, p):
    if typ == "session.opened" and not p.get("title"):
        raise ValidationError("title required")
    if typ == "message.upserted":
        if p.get("role") not in {"user", "assistant"}:
            raise ValidationError("bad role")
        if not p.get("message_id"):
            raise ValidationError("message_id required")
        if p["role"] == "user" and p.get("usage") is not None:
            raise ValidationError("user usage must be null")
        if p["role"] == "assistant" and p.get("usage") is not None:
            _check_usage(p["usage"])
    if typ == "tool.upserted" and not p.get("tool_call_id"):
        raise ValidationError("tool_call_id required")
    if typ == "turn.ended" and p.get("usage") is not None:
        _check_usage(p["usage"])


def _check_usage(u):
    if not isinstance(u, dict) or u.get("status") not in {"reported", "estimated", "missing"}:
        raise ValidationError("bad usage")
    for k in USAGE_KEYS:
        if k not in u:
            raise ValidationError(f"usage missing {k}")
```

- [ ] **Step 4: 再跑测试**

Run: `python -m unittest tests.test_schema -v`

Expected: OK。

- [ ] **Step 5: Commit**

```bash
git add ata/__init__.py ata/schema.py tests/test_schema.py
git commit -m "$(cat <<'EOF'
feat(kernel): validate v1 canonical events

Reject missing identity fields, unknown types, and user-row usage so
plugins cannot write dialect leftovers into the ledger.
EOF
)"
```

---

### Task 2: 账本追加与分页

**Files:**
- Create: `ata/ledger.py`
- Create: `tests/test_ledger.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_ledger.py
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m unittest tests.test_ledger -v`

Expected: `ModuleNotFoundError: ata.ledger`。

- [ ] **Step 3: 最小实现**

```python
# ata/ledger.py
from __future__ import annotations

import json
import threading
from pathlib import Path


class Ledger:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._seq = {}
        self._ids = {}
        self._boot()

    def _file(self, agent_id: str, session_id: str) -> Path:
        return self.root / agent_id / f"{session_id}.jsonl"

    def _boot(self):
        if not self.root.exists():
            return
        for path in self.root.glob("*/*.jsonl"):
            sid = path.stem
            ids = {}
            last = 0
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                last = rec["seq"]
                ids[rec["event"]["id"]] = rec["seq"]
            self._seq[sid] = last
            self._ids[sid] = ids

    def append(self, event: dict) -> int:
        with self._lock:
            sid = event["session_id"]
            known = self._ids.setdefault(sid, {})
            if event["id"] in known:
                return known[event["id"]]
            seq = self._seq.get(sid, 0) + 1
            self._seq[sid] = seq
            known[event["id"]] = seq
            path = self._file(event["agent_id"], sid)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(json.dumps({"seq": seq, "event": event}, ensure_ascii=False) + "\n")
            return seq

    def read(self, session_id: str) -> list[dict]:
        for path in self.root.glob(f"*/{session_id}.jsonl"):
            out = []
            for line in path.read_text().splitlines():
                if line.strip():
                    out.append(json.loads(line))
            return out
        return []

    def sessions(self) -> list[dict]:
        items = []
        for path in sorted(self.root.glob("*/*.jsonl")):
            items.append({
                "id": path.stem,
                "agent": path.parent.name,
            })
        return items
```

- [ ] **Step 4: 再跑测试**

Run: `python -m unittest tests.test_ledger -v`

Expected: OK。

- [ ] **Step 5: Commit**

```bash
git add ata/ledger.py tests/test_ledger.py
git commit -m "$(cat <<'EOF'
feat(kernel): append canonical events to per-session jsonl

Give each accepted event a monotonic seq and treat duplicate ids as
idempotent writes so plugins can retry without doubling the ledger.
EOF
)"
```

---

### Task 3: 事件投影成 02 行

**Files:**
- Create: `ata/project.py`
- Create: `tests/test_project.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_project.py
import unittest
from ata.project import project_session
from ata.schema import parse_event


def rec(seq, ev):
    return {"seq": seq, "event": parse_event(ev)}


class ProjectTest(unittest.TestCase):
    def test_usage_and_order(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"pi","session_id":"s","ts":1,"type":"session.opened","turn":None,"payload":{"title":"t"}}),
            rec(2, {"v":1,"id":"ts","agent_id":"pi","session_id":"s","ts":2,"type":"turn.started","turn":1,"payload":{}}),
            rec(3, {"v":1,"id":"u","agent_id":"pi","session_id":"s","ts":3,"type":"message.upserted","turn":1,"payload":{
                "message_id":"u1","role":"user","text":"hello","status":"completed","request_no":None,
                "usage":None,"started_at":3,"duration_ms":10,"output_text":None}}),
            rec(4, {"v":1,"id":"a","agent_id":"pi","session_id":"s","ts":4,"type":"message.upserted","turn":1,"payload":{
                "message_id":"a1","role":"assistant","text":"ok","status":"completed","request_no":1,
                "usage":{"status":"reported","input":10,"output":2,"cache_read":1,"cache_write":0,"total_tokens":13,"cost":None},
                "started_at":4,"duration_ms":20,"output_text":"ok"}}),
            rec(5, {"v":1,"id":"t","agent_id":"pi","session_id":"s","ts":5,"type":"tool.upserted","turn":1,"payload":{
                "tool_call_id":"c1","parent_message_id":"a1","name":"Read","text":"f","status":"completed",
                "payload":{"path":"f"},"result":"ok","started_at":5,"duration_ms":5}}),
        ]
        sess = project_session("s", "pi", recs)
        kinds = [r["kind"] for r in sess["rows"]]
        self.assertEqual(kinds, ["user", "assistant", "tool"])
        self.assertTrue(sess["rows"][0]["start"])
        self.assertEqual(sess["rows"][1]["usage"]["cacheRead"], 1)
        self.assertEqual(sess["rows"][2]["parentId"], "a1")
        self.assertEqual(sess["rows"][2]["usage"]["status"], "n/a")

    def test_droid_missing(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"droid","session_id":"d","ts":1,"type":"session.opened","turn":None,"payload":{"title":"d"}}),
            rec(2, {"v":1,"id":"a","agent_id":"droid","session_id":"d","ts":2,"type":"message.upserted","turn":1,"payload":{
                "message_id":"a1","role":"assistant","text":"x","status":"completed","request_no":1,
                "usage":None,"started_at":2,"duration_ms":1,"output_text":"x"}}),
        ]
        row = project_session("d", "droid", recs)["rows"][0]
        self.assertEqual(row["usage"]["status"], "missing")
        self.assertIsNone(row["usage"]["input"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m unittest tests.test_project -v`

Expected: `ModuleNotFoundError: ata.project`。

- [ ] **Step 3: 最小实现**

```python
# ata/project.py
NA = {"status": "n/a", "input": None, "output": None, "cacheRead": None, "cacheWrite": None}
MISS = {"status": "missing", "input": None, "output": None, "cacheRead": None, "cacheWrite": None}


def _usage(raw):
    if not raw:
        return None
    if raw["status"] != "reported":
        return dict(MISS)
    return {
        "status": "reported",
        "input": raw["input"],
        "output": raw["output"],
        "cacheRead": raw["cache_read"],
        "cacheWrite": raw["cache_write"],
    }


def project_session(session_id, agent, recs, *, tail=None, before=None):
    title = session_id
    entities = {}
    order = []
    turn_usage = {}
    for rec in recs:
        ev = rec["event"]
        seq = rec["seq"]
        p = ev["payload"]
        if ev["type"] == "session.opened":
            title = p.get("title") or title
            continue
        if ev["type"] == "turn.ended" and p.get("usage"):
            turn_usage[ev["turn"]] = _usage(p["usage"])
            continue
        if ev["type"] == "message.upserted":
            key = ("m", p["message_id"])
            row = entities.get(key) or {"_first": seq, "_seq": seq}
            row.update({
                "id": p["message_id"],
                "_seq": seq,
                "turn": ev["turn"],
                "kind": p["role"],
                "tag": p["role"].upper(),
                "text": p["text"],
                "startedAt": p["started_at"],
                "durationMs": p.get("duration_ms") or 0,
                "status": p["status"],
                "requestNo": p.get("request_no"),
                "outputText": p.get("output_text"),
                "payloadText": p["text"] if p["role"] == "user" else None,
                "usage": _usage(p.get("usage")) if p["role"] == "assistant" else dict(NA),
            })
            entities[key] = row
            if key not in order:
                order.append(key)
        elif ev["type"] == "tool.upserted":
            key = ("t", p["tool_call_id"])
            row = entities.get(key) or {"_first": seq, "_seq": seq}
            row.update({
                "id": p["tool_call_id"],
                "_seq": seq,
                "turn": ev["turn"],
                "kind": "tool",
                "tag": "TOOL",
                "name": p["name"],
                "text": p["text"],
                "startedAt": p["started_at"],
                "durationMs": p.get("duration_ms") or 0,
                "status": p["status"],
                "parentId": p.get("parent_message_id"),
                "payload": p.get("payload"),
                "result": p.get("result"),
                "usage": dict(NA),
            })
            entities[key] = row
            if key not in order:
                order.append(key)

    rows = [entities[k] for k in sorted(order, key=lambda k: entities[k]["_first"])]
    step = 0
    seen_turn = set()
    for row in rows:
        if row["kind"] == "assistant":
            step += 1
            row["step"] = step
            row["group"] = f"Step {step}"
            if (not row.get("usage") or row["usage"]["status"] != "reported") and row["turn"] in turn_usage:
                row["usage"] = turn_usage[row["turn"]] or dict(MISS)
            if row.get("usage") is None:
                row["usage"] = dict(MISS)
        else:
            row["step"] = step
            if step:
                row["group"] = f"Step {step}"
        if row["turn"] not in seen_turn:
            row["start"] = True
            seen_turn.add(row["turn"])
        else:
            row["start"] = False

    has_older = False
    cursor = rows[0]["_seq"] if rows else 0
    if before is not None:
        rows = [r for r in rows if r["_seq"] < before]
        if tail:
            has_older = len(rows) > tail
            rows = rows[-tail:]
    elif tail:
        has_older = len(rows) > tail
        rows = rows[-tail:]
    if rows:
        cursor = rows[0]["_seq"]
    for i, row in enumerate(rows):
        row["index"] = i
    return {
        "id": session_id,
        "agent": agent,
        "title": title,
        "crumb": f"{agent} · <b>{title}</b>",
        "has_older": has_older,
        "cursor": cursor,
        "turns": len(seen_turn),
        "rows": rows,
    }
```

- [ ] **Step 4: 再跑测试**

Run: `python -m unittest tests.test_project -v`

Expected: OK。

- [ ] **Step 5: Commit**

```bash
git add ata/project.py tests/test_project.py
git commit -m "$(cat <<'EOF'
feat(kernel): project canonical events into 02 ledger rows

Keep Atatrace on the sketch row contract so the copied workbench can
render turns, tools, and Missing usage without learning the write schema.
EOF
)"
```

---

### Task 4: stdlib HTTP + 预装 fixture

**Files:**
- Create: `ata/http.py`
- Create: `ata/__main__.py`
- Create: `testdata/events/pi-compact.jsonl`
- Create: `testdata/events/droid-missing.jsonl`
- Create: `testdata/events/pi-long.jsonl`
- Create: `tests/test_http.py`

- [ ] **Step 1: 写三条合成账本（不要用真实会话）**

`testdata/events/pi-compact.jsonl` 至少含：`session.opened`、`turn.started`、user、assistant（`reported` usage）、两个 tool（一个 `failed`）、第二条 assistant。文案用占位句。

`testdata/events/droid-missing.jsonl`：user、assistant（`usage: null`）、一个 tool。

`testdata/events/pi-long.jsonl`：用脚本生成 120 条 `message.upserted`（交替 user/assistant），保证 `has_older` 为真。生成脚本可以写在 `tests/test_http.py` 的 `setUpModule`，或一次性手写进仓库。手写太长就在 `ata/__main__.py` 提供 `python -m ata seed-long`，测试里调用。

最小 seed（可放进测试，不必提交 120 行手写）：

```python
def write_long(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = 1
    lines = []
    def put(ev):
        nonlocal seq
        lines.append(json.dumps({"seq": seq, "event": ev}))
        seq += 1
    put({"v":1,"id":"o","agent_id":"pi","session_id":"pi-long","ts":1,"type":"session.opened","turn":None,"payload":{"title":"long"}})
    for i in range(1, 121):
        role = "user" if i % 2 else "assistant"
        put({"v":1,"id":f"m{i}","agent_id":"pi","session_id":"pi-long","ts":i,"type":"message.upserted","turn": (i+1)//2,
             "payload":{"message_id":f"m{i}","role":role,"text":f"row {i}","status":"completed",
                        "request_no": None if role=="user" else i, "usage": None,
                        "started_at": 1000+i, "duration_ms": 10, "output_text": f"row {i}"}})
    path.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 2: HTTP 测试**

```python
# tests/test_http.py
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        led = Ledger(root)
        led.append({
            "v":1,"id":"o","agent_id":"droid","session_id":"droid-missing","ts":1,
            "type":"session.opened","turn":None,"payload":{"title":"missing"},
        })
        led.append({
            "v":1,"id":"a","agent_id":"droid","session_id":"droid-missing","ts":2,
            "type":"message.upserted","turn":1,"payload":{
                "message_id":"a1","role":"assistant","text":"x","status":"completed",
                "request_no":1,"usage":None,"started_at":2,"duration_ms":1,"output_text":"x"},
        })
        self.httpd = make_server(led, webroot=Path("web"), host="127.0.0.1", port=0)
        self.port = self.httpd.server_port
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.td.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read().decode())

    def test_missing_usage(self):
        data = self.get("/api/sessions/droid-missing")
        self.assertEqual(data["rows"][0]["usage"]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 跑测试，确认失败**

Run: `python -m unittest tests.test_http -v`

Expected: `ModuleNotFoundError: ata.http`。

- [ ] **Step 4: 实现 `ata/http.py` 与 `ata/__main__.py`**

要点：

- `do_GET`：`/api/health`、`/api/sessions`、`/api/sessions/{id}`，其余从 `web/` 读静态文件。
- `do_POST /api/events`：读 JSON，`parse_event` 后 `ledger.append`。
- 查询参数 `limit` 默认 80，`before` 有则向前翻。
- `make_server(ledger, webroot, host, port)` 返回 `HTTPServer`，测试才能选 `port=0`。

```python
# ata/__main__.py
import argparse
from pathlib import Path
from ata.http import make_server
from ata.ledger import Ledger

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["serve"])
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--ledger", default="./data")
    p.add_argument("--web", default="web")
    args = p.parse_args(argv)
    httpd = make_server(Ledger(Path(args.ledger)), Path(args.web), "127.0.0.1", args.port)
    print(f"atatrace http://127.0.0.1:{args.port}")
    httpd.serve_forever()

if __name__ == "__main__":
    main()
```

`http.py` 用 `pathlib` 拼 `web/index.html`。目录不存在时 `/` 返回 404 文本，先不要为了页面去改 02。

- [ ] **Step 5: 再跑测试**

Run: `python -m unittest tests.test_http tests.test_schema tests.test_ledger tests.test_project -v`

Expected: OK。

- [ ] **Step 6: Commit**

```bash
git add ata/http.py ata/__main__.py testdata tests/test_http.py
git commit -m "$(cat <<'EOF'
feat(kernel): serve session projections over localhost HTTP

Expose health, session list, paged rows, and event append so the
reader and both plugins share one writer without opening vendor files.
EOF
)"
```

---

### Task 5: 复制 02，只换数据入口

**Files:**
- Create: `web/index.html`（从 02 复制，**不要**改 `sketches/002-beautiful-workbench/index.html`）
- Modify: 复制后的 `web/index.html` 数据段与 `loadOlder` / 启动段

- [ ] **Step 1: 复制**

```bash
mkdir -p web
cp sketches/002-beautiful-workbench/index.html web/index.html
```

不要复制 `preview*.png`、`export-ava-window.py`、`local/`。删掉复制稿里的：

```html
<script src="./local/ava-window.js"></script>
```

以及整段 `window.ATA_LOCAL_PROJECTION` 分支。

- [ ] **Step 2: 删掉写死的 `piLive` / `droidRows` / `sessions = [...]`，换成 API**

在原 `const at = ...` 到 `const sessions = [` 整块替换为：

```javascript
    const API = "";
    let sessions = [];
    let olderCursor = null;

    const emptyUsage = () => ({ status: "n/a", input: null, output: null, cacheRead: null, cacheWrite: null });

    async function fetchJSON(path) {
      const res = await fetch(API + path);
      if (!res.ok) throw new Error(path + " " + res.status);
      return res.json();
    }

    async function loadSession(id, query = "") {
      const page = await fetchJSON("/api/sessions/" + encodeURIComponent(id) + query);
      return {
        id: page.id,
        agent: page.agent,
        title: page.title,
        crumb: page.crumb,
        rows: page.rows,
        older: page.has_older,
        cursor: page.cursor
      };
    }

    async function boot() {
      const list = await fetchJSON("/api/sessions");
      sessions = [];
      for (const item of list) {
        sessions.push(await loadSession(item.id));
      }
      if (!sessions.length) {
        document.getElementById("crumb").textContent = "no sessions";
        return;
      }
      current = sessions[0];
      olderCursor = current.cursor;
      selected = { type: "record", id: current.rows[current.rows.length - 1].id };
      document.getElementById("crumb").innerHTML = current.crumb;
      paintSessions();
      paint();
      requestAnimationFrame(() => { scroller.scrollTop = scroller.scrollHeight; });
    }
```

`let current = sessions[0];` 改成 `let current = { id:"", agent:"", title:"", crumb:"", rows:[], older:false };`，避免 `boot` 完成前取 `[0]` 崩掉。

`paintSessions` 里 turn 计数改成 `session.rows.filter(row => row.start).length`，保持原样即可。

- [ ] **Step 3: `loadOlder` 改成真请求**

把 `setTimeout` + `current.older.shift()` 换成：

```javascript
    async function loadOlder() {
      if (loadingOlder || !current.older) return;
      loadingOlder = true;
      paint();
      const prevHeight = scroller.scrollHeight;
      const prevTop = scroller.scrollTop;
      const page = await loadSession(current.id, `?before=${current.cursor}&limit=36`);
      const have = new Set(current.rows.map(r => r.id));
      const prepend = page.rows.filter(r => !have.has(r.id));
      current.rows = [...prepend, ...current.rows].map((row, i) => ({ ...row, index: i }));
      current.older = page.has_older;
      current.cursor = page.cursor;
      loadingOlder = false;
      paint();
      scroller.scrollTop = prevTop + (scroller.scrollHeight - prevHeight);
    }
```

`paintOverview` / `virtualRows` / `paintTable` 里所有 `current.older && current.older.length` 改成 `current.older === true`。02 把 `older` 当数组；生产把它当布尔。这是复制稿里唯一允许的手势以外改动。

- [ ] **Step 4: 跟随尾部轮询**

在 `boot()` 末尾加：

```javascript
    setInterval(async () => {
      if (!follow || !current.id || loadingOlder) return;
      const page = await loadSession(current.id);
      const last = current.rows.length ? current.rows[current.rows.length - 1].id : null;
      const nextLast = page.rows.length ? page.rows[page.rows.length - 1].id : null;
      if (nextLast === last && page.rows.length === current.rows.filter(r => !String(r.id).startsWith("old-")).length) {
        // 仍替换尾页，避免 pending → completed 丢更新
      }
      const olderKeep = current.rows.filter(r => r._keptOlder);
      // ponytail: 已加载的更早行打标记，尾页刷新时留下
      const tailIds = new Set(page.rows.map(r => r.id));
      const kept = current.rows.filter(r => r._keptOlder && !tailIds.has(r.id));
      current.rows = [...kept, ...page.rows].map((row, i) => ({ ...row, index: i }));
      current.older = page.has_older;
      paint();
      if (follow) scroller.scrollTop = scroller.scrollHeight;
    }, 1000);
```

`loadOlder` 给前置行打 `row._keptOlder = true`。

把文件底部 `defaultRange(); selectRecord("t4"); paint();` 改成 `boot();`。02 里写死选中 `t4` 和 Turn 2 窗口，生产不要保留。

Request 检查器里 `Provider: pi` / `Model: demo-ledger` 改成 `current.agent` 与 `Not present`。不要编模型名。

- [ ] **Step 5: 手工点一遍验收门 B1–B8**

Run: `python -m ata serve --port 8787 --ledger testdata/events`

Expected: 浏览器手势与 02 一致；数据来自 fixture。

- [ ] **Step 6: Commit**

```bash
git add web/index.html
git commit -m "$(cat <<'EOF'
feat(atatrace): copy 02 workbench and bind it to kernel pages

Keep the frozen sketch untouched and replace only the demo session
arrays plus older-page loading so the shipped UI reads live projections.
EOF
)"
```

---

### Task 6: Droid JSONL → 事件

**Files:**
- Create: `ata/plugins/__init__.py`
- Create: `ata/plugins/droid.py`
- Create: `testdata/vendor/droid-sample.jsonl`
- Create: `tests/test_droid.py`

厂商 fixture（合成，字段只用 spec 已核实的名字）：

```json
{"type":"session_start","sessionId":"droid-missing"}
{"type":"message","id":"m1","role":"user","content":[{"type":"text","text":"open first-party jsonl"}]}
{"type":"message","id":"m2","role":"assistant","content":[{"type":"text","text":"no token fields"},{"type":"tool_use","id":"tu1","name":"Read","input":{"path":"session.jsonl"}}]}
{"type":"message","id":"m3","role":"user","content":[{"type":"tool_result","tool_use_id":"tu1","content":"type=message"}]}
{"type":"agent_turn_outcome","resultKind":"success","reason":"completed"}
{"type":"todo_state","todos":[]}
{"type":"compaction_state","summaryKind":"llm_summary"}
```

- [ ] **Step 1: 测试**

```python
# tests/test_droid.py
import unittest
from pathlib import Path
from ata.plugins.droid import translate_file
from ata.project import project_session

class DroidTest(unittest.TestCase):
    def test_maps_verified_types(self):
        evs = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
        types = [e["type"] for e in evs]
        self.assertIn("session.opened", types)
        self.assertIn("message.upserted", types)
        self.assertIn("tool.upserted", types)
        self.assertIn("turn.ended", types)
        self.assertNotIn("compaction.boundary", types)
        recs = [{"seq": i+1, "event": e} for i, e in enumerate(evs)]
        sess = project_session("droid-missing", "droid", recs)
        asst = next(r for r in sess["rows"] if r["kind"] == "assistant")
        self.assertEqual(asst["usage"]["status"], "missing")
        tool = next(r for r in sess["rows"] if r["kind"] == "tool")
        self.assertEqual(tool["name"], "Read")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m unittest tests.test_droid -v`

Expected: `ModuleNotFoundError`。

- [ ] **Step 3: `translate_file` / `translate_line`**

规则：

| JSONL `type` | 动作 |
| --- | --- |
| `session_start` | `session.opened`，`session_id=sessionId`，`title=sessionId` |
| `message` + `role=user/assistant` 的 text | `message.upserted` |
| `content[]` 里 `tool_use` | `tool.upserted` pending→随后同一 id 的 `tool_result` 再 upsert completed |
| `agent_turn_outcome` | `turn.ended`，`usage: null` |
| `todo_state` / `compaction_state` / 不认识的 type | **跳过**，不要标成 Turn |
| 任何 token / settings 字段 | 忽略 |

`session_id` 缺省用文件名。`turn`：每遇到一条 `role=user` 的非 `tool_result` 消息 +1。`tool_result` 不算新 turn。

配对：`tool_use.id` == `tool_result.tool_use_id`。只有 result 没有 use：仍写 `tool.upserted`，`status` 保持 `completed`，`parent_message_id` 为 `null`（缺口留给检查器空态，不补猜助手）。

增量 tail：`translate_file(path, offset=0) -> (events, new_offset)`。按字节偏移读，半行留到下次。`serve --droid-path FILE` 时在后台线程每秒 tail；**默认不传，内核不会碰 `~/.factory`**。

- [ ] **Step 4: 再跑测试**

Run: `python -m unittest tests.test_droid -v`

Expected: OK。

- [ ] **Step 5: Commit**

```bash
git add ata/plugins testdata/vendor/droid-sample.jsonl tests/test_droid.py ata/http.py ata/__main__.py
git commit -m "$(cat <<'EOF'
feat(droid): translate verified JSONL types into canonical events

Map session_start, message, tool_use/tool_result, and
agent_turn_outcome only. Leave per-turn usage Missing and skip
compaction/todo lines so the adapter cannot invent turns.
EOF
)"
```

---

### Task 7: Pi hook → 事件 + extension 壳

**Files:**
- Create: `ata/plugins/pi.py`
- Create: `testdata/vendor/pi-hooks.json`
- Create: `tests/test_pi.py`
- Create: `extensions/pi-atatrace/index.ts`

- [ ] **Step 1: 合成 hook 记录（按 pin `845d6ff1` 文档字段，不是漂了的 HEAD）**

`testdata/vendor/pi-hooks.json`：

```json
[
  {"name":"agent_start","event":{},"ctx":{"session_id":"pi-compact","title":"synthetic pi turn"}},
  {"name":"turn_start","event":{"turnIndex":0,"timestamp":1000}},
  {"name":"message_end","event":{"message":{"role":"user","content":"ask about usage","timestamp":1001}}},
  {"name":"message_end","event":{"message":{"role":"assistant","content":[{"type":"text","text":"reported"}],"usage":{"input":10,"output":2,"cacheRead":1,"cacheWrite":0,"totalTokens":13,"cost":{"total":0}},"stopReason":"stop"}}},
  {"name":"tool_execution_start","event":{"toolCallId":"c1","toolName":"Read","args":{"path":"f"}}},
  {"name":"tool_execution_end","event":{"toolCallId":"c1","toolName":"Read","result":{"content":[{"type":"text","text":"ok"}]},"isError":false}},
  {"name":"turn_end","event":{"turnIndex":0,"message":{"role":"assistant","usage":{"input":10,"output":2,"cacheRead":1,"cacheWrite":0,"totalTokens":13,"cost":{"total":0}},"stopReason":"stop"},"toolResults":[]}},
  {"name":"agent_end","event":{"messages":[]}},
  {"name":"turn_end","event":{"turnIndex":1,"message":{"role":"assistant","usage":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"totalTokens":0,"cost":{"total":0}},"stopReason":"error"},"toolResults":[]}}
]
```

- [ ] **Step 2: 测试**

```python
# tests/test_pi.py
import json
import unittest
from pathlib import Path
from ata.plugins.pi import translate_hook, usage_from_assistant

class PiTest(unittest.TestCase):
    def test_zero_error_is_missing(self):
        u = usage_from_assistant({
            "usage": {"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"totalTokens":0,"cost":{"total":0}},
            "stopReason": "error",
        })
        self.assertEqual(u["status"], "missing")
        self.assertIsNone(u["input"])

    def test_hook_stream(self):
        hooks = json.loads(Path("testdata/vendor/pi-hooks.json").read_text())
        evs = []
        state = {}
        for h in hooks:
            evs.extend(translate_hook(h["name"], h["event"], h.get("ctx") or {}, state))
        types = [e["type"] for e in evs]
        self.assertEqual(types[0], "session.opened")
        self.assertIn("tool.upserted", types)
        last = [e for e in evs if e["type"]=="turn.ended"][-1]
        self.assertEqual(last["payload"]["usage"]["status"], "missing")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 跑测试，确认失败**

Run: `python -m unittest tests.test_pi -v`

Expected: `ModuleNotFoundError`。

- [ ] **Step 4: 实现纯函数**

`translate_hook(name, event, ctx, state) -> list[event]`。

| hook | 事件 |
| --- | --- |
| `agent_start` | `session.opened`（每个 session 一次） |
| `turn_start` | `turn.started`，`turn=turnIndex+1` |
| `message_start` | `message.upserted` `pending`（只要 user/assistant） |
| `message_end` | `message.upserted` `completed`；从 `content` 抽 text |
| `tool_execution_start` | `tool.upserted` `pending` |
| `tool_execution_end` | `tool.upserted` `completed` 或 `failed`（`isError`） |
| `turn_end` | 再 upsert 一次助手消息（带 usage）+ `turn.ended` |
| `agent_end` | `session.closed` |
| 其它名字 | 空列表 |

`usage_from_assistant(message)`：读 `message.usage`；`stopReason in {"error","aborted"}` 且四计数全 0 → `missing`。

`state` 里记 `session_id`、`turn`、`last_assistant_id`。工具的 `parent_message_id` 用最后一条助手 `message_id`。`message_id` 用 `message.responseId` 或 `f"{session}:{turn}:{role}"`。

- [ ] **Step 5: `extensions/pi-atatrace/index.ts`**

Pi 自己加载 TS。这个文件只做：读 `process.env.ATA_URL || "http://127.0.0.1:8787"`，对上表 hook `pi.on(...)`，`fetch(ATA_URL+"/api/events",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(event)})`。

映射逻辑允许在 TS 里再写一遍，但必须以 `tests/test_pi.py` 的 Python 纯函数为对照表；字段名不得分叉。不要在 extension 里读 Pi session 文件。

- [ ] **Step 6: 再跑测试**

Run: `python -m unittest tests.test_pi -v`

Expected: OK。

- [ ] **Step 7: Commit**

```bash
git add ata/plugins/pi.py testdata/vendor/pi-hooks.json tests/test_pi.py extensions/pi-atatrace/index.ts
git commit -m "$(cat <<'EOF'
feat(pi): map pin 845d6ff1 hooks to canonical events

Subscribe to agent/turn/message/tool hooks only, take usage from
turn_end.message.usage, and treat all-zero error/abort usage as Missing.
EOF
)"
```

---

### Task 8: 端到端验收（自动 + 手工）

**Files:**
- Create: `tests/test_accept.py`
- Modify: `ata/__main__.py`（如需 `seed` 把 vendor fixture 灌进 ledger）

- [ ] **Step 1: 验收测试**

```python
# tests/test_accept.py
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger
from ata.plugins.droid import translate_file
from ata.plugins.pi import translate_hook
from ata.schema import parse_event


def post(port, ev):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/events",
        data=json.dumps(ev).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


class AcceptTest(unittest.TestCase):
    def test_vendor_to_ui_json(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            httpd = make_server(led, Path("web"), "127.0.0.1", 0)
            th = threading.Thread(target=httpd.serve_forever, daemon=True)
            th.start()
            port = httpd.server_port
            try:
                hooks = json.loads(Path("testdata/vendor/pi-hooks.json").read_text())
                state = {}
                for h in hooks:
                    for ev in translate_hook(h["name"], h["event"], h.get("ctx") or {}, state):
                        post(port, parse_event(ev))
                for ev in translate_file(Path("testdata/vendor/droid-sample.jsonl")):
                    post(port, parse_event(ev))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions") as r:
                    listing = json.loads(r.read().decode())
                ids = {x["id"] for x in listing}
                self.assertIn("pi-compact", ids)
                self.assertIn("droid-missing", ids)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions/droid-missing") as r:
                    droid = json.loads(r.read().decode())
                asst = next(x for x in droid["rows"] if x["kind"] == "assistant")
                self.assertEqual(asst["usage"]["status"], "missing")
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r:
                    html = r.read().decode()
                self.assertIn("Atatrace", html)
                self.assertIn("/api/sessions", html)
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑全量**

Run: `python -m unittest discover -s tests -v`

Expected: 全部 OK。

- [ ] **Step 3: 手工 B9**

服务起来后：

```bash
curl -s -X POST localhost:8787/api/events -H 'content-type: application/json' -d '{
  "v":1,"id":"live-1","agent_id":"pi","session_id":"pi-compact","ts":999999,
  "type":"message.upserted","turn":99,
  "payload":{"message_id":"live-1","role":"user","text":"live append",
             "status":"completed","request_no":null,"usage":null,
             "started_at":999999,"duration_ms":1,"output_text":null}
}'
```

Expected: 浏览器跟随开启时，一秒内账本尾部出现 `live append`。

- [ ] **Step 4: 对照验收门把 B1–B8 勾完。** 02 原文件 `git status` 必须干净（未改）。

- [ ] **Step 5: Commit**

```bash
git add tests/test_accept.py
git commit -m "$(cat <<'EOF'
test(ata): accept vendor fixtures through HTTP into Atatrace

Drive Pi and Droid translators through the single writer and assert
the reader payload still carries reported vs Missing usage.
EOF
)"
```

---

## 明确不做（看见就停）

- 改 `sketches/002-beautiful-workbench/`
- 引入 Node 工作区、Vite、React、嵌套 git
- 内核读取 `~/.factory` / `~/.pi` / AVA `records.jsonl`
- 把真实 session 正文写进 `testdata/`
- SYSTEM 快照、Compare、SSE、会话合计摊销、sub2api / TTFT 计费
- 把 `inclusiveTokenUsage` 或工具 usage 写成 Turn usage
- 用漂了的 Pi `b1efcf7d7` 当字段依据

## 做完再考虑（本计划不包含）

- 把本计划冻结的键名回写进 spec
- 给 SYSTEM 加规范行（那是 spec 修订，不是 UI 修订）
- 真机装 `extensions/pi-atatrace` 到 `~/.pi/agent/extensions/`
- `--droid-path` 对真实第一方 JSONL 做一次授权审计

---

## Self-review

1. **Spec coverage:** v1 首段（空阅读器 + Pi 参考插件 + Droid tail）有任务。视觉合同靠复制 02。usage / Missing / 单 writer / 内核不打开厂商路径都有测试。SYSTEM、Compare、反向代理按 spec 非目标排除。
2. **Placeholder scan:** 无 TBD。fixture 文案给定；HTTP 路径给定；02 替换点给定。
3. **Type consistency:** 写路径蛇形 `cache_read`，读路径 02 驼峰 `cacheRead`，只在 `project.py` 转换。`session_id` / `agent_id` / `tool_call_id` 全计划一致。

Plan complete and saved to `docs/superpowers/plans/2026-08-15-ata-v1-end-to-end-reader.md`.
