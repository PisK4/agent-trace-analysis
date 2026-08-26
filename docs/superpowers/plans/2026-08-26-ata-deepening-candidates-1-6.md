# ATA 架构加深候选 1~6 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地架构评审（2026-08-26 HTML 报告）的六个加深候选：适配器翻译内核、标题权威收敛、投影缓存、绞杀者收尾删除、信封工厂、compare 改吃便捷层。

**Architecture:** 服务端先立共享内核（`ata/plugins/common.py` 翻译词汇表 + `schema.envelope` 信封工厂），再收账本折叠规则（`fold_session_meta` 纯函数），然后给便捷层端点加 rev 门控缓存并让前端经统一 `useSummary` 取数，最后删掉 legacy 前端。每一步都是把散在多处的同语义实现收敛到单一归属地（deep module）。

**Tech Stack:** Python 3 标准库（sqlite3 / http.server）、React 19 + Vite + TypeScript + Vitest、unittest（Python 侧测试框架，非 pytest）。

**Spec:** 架构评审报告六张卡片；外部接口红线见 `docs/specs/agent-read-interface.md`（已定稿，「不再重开」——本计划不改动任何 HTTP 端点的外部形状）；领域词汇见仓库根 `CONTEXT.md`。

## Global Constraints

- 所有命令在仓库根 `repos/ata/` 下执行；git 提交也在该子仓库内。
- Python 测试命令：`python3 -m unittest discover -s tests -v`（或单模块 `python3 -m unittest tests.test_schema -v`）。**不是 pytest。**
- 前端测试命令：`cd webapp && npx vitest run <file>`；构建：`cd webapp && npm run build`；lint：`cd webapp && npm run lint`。
- 不改动任何 HTTP 端点的外部请求/响应形状（spec 已冻结）；不改 schema 校验规则（`parse_event` 的校验分支不动，只增 envelope 工厂）。
- 事件写入只走追加门（`Ledger.append` / `append_many`），任何地方不得 UPDATE events 表。
- CONTEXT.md 术语纪律：「轮次」专指 turn；run 不译；usage 三态 reported/estimated/missing 缺失绝不当 0。
- 注释风格跟随现仓库：中文注释解释「为什么」，关键裁决锚定 CONTEXT.md 术语。
- 每个 Task 结束必须全绿再提交；既有测试因行为改进而失真时，按各 Task 内注明的更新规则改断言，并在 commit message 里声明行为变化。

---

## Phase 1 · 信封工厂与适配器翻译内核（评审候选 5 + 候选 1）

### Task 1: `schema.envelope()` 信封工厂，收编三处内联组装

**Files:**
- Modify: `ata/schema.py`（末尾追加工厂）
- Modify: `ata/cli.py:149-155`（`build_score_event`）
- Modify: `ata/http.py:189-194`（改名端点）
- Modify: `ata/plugins/droid.py:49-59`（`refresh_titles`）
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: `schema.envelope(agent_id: str, session_id: str, type: str, payload: dict, turn: int | None = None, ts: int | None = None, eid: str | None = None) -> dict` —— 返回七键信封，键序与现有内联一致（v, id, agent_id, session_id, ts, type, turn, payload）。调用方拿到后仍需过 `parse_event()` 再入账本（工厂不校验，校验职责留在 parse_event）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_schema.py` 追加：

```python
class EnvelopeTest(unittest.TestCase):
    def test_envelope_full_shape(self):
        ev = envelope("claude", "s1", "session.scored", {"value": "good"},
                      turn=None, ts=1234, eid="abc")
        self.assertEqual(ev, {
            "v": 1, "id": "abc", "agent_id": "claude", "session_id": "s1",
            "ts": 1234, "type": "session.scored", "turn": None,
            "payload": {"value": "good"},
        })
        # 工厂产物必须能直接过 parse_event
        self.assertEqual(parse_event(ev)["type"], "session.scored")

    def test_envelope_defaults(self):
        import time as _t
        before = int(_t.time() * 1000)
        ev = envelope("pi", "s2", "session.renamed", {"title": "x"}, eid="e2")
        after = int(_t.time() * 1000)
        self.assertEqual(ev["v"], 1)
        self.assertEqual(ev["id"], "e2")
        self.assertIsNone(ev["turn"])
        self.assertTrue(before <= ev["ts"] <= after)
```

文件顶部 import 行改为 `from ata.schema import ALLOWED_AGENTS, envelope, parse_event`（保留该文件原有的其他 import）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_schema -v`
Expected: FAIL，`ImportError: cannot import name 'envelope'`

- [ ] **Step 3: 最小实现**

在 `ata/schema.py` 末尾追加：

```python
def envelope(agent_id, session_id, type_, payload, turn=None, ts=None, eid=None):
    """v1 事件信封的唯一构造入口。

    账本的写入方（CLI 标注、HTTP 改名、适配器补写）都组同一个七键 dict；
    此前各处手搓，漏键要到 parse_event 才报「missing xxx」。工厂只负责
    形状与默认值（ts=now），不做校验——校验职责仍在 parse_event。
    """
    return {
        "v": 1,
        "id": eid if eid is not None else uuid.uuid4().hex,
        "agent_id": agent_id,
        "session_id": str(session_id),
        "ts": int(ts if ts is not None else time.time() * 1000),
        "type": type_,
        "turn": turn,
        "payload": payload,
    }
```

`ata/schema.py` 顶部加 `import time` 与 `import uuid`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_schema -v`
Expected: PASS（原有测试 + 新增 2 个）

- [ ] **Step 5: 替换三处内联**

`ata/cli.py` 的 `build_score_event` 改为：

```python
def build_score_event(agent_id, session_id, value, note=None):
    payload = {"value": value}
    if note:
        payload["note"] = note
    return envelope(agent_id, session_id, "session.scored", payload)
```

并在 cli.py 顶部把 `from ata.schema import ...` 区补上 `envelope`（cli.py 目前没有 import schema，新增一行 `from ata.schema import envelope`）。`uuid` 若仅剩此处使用则保留 import（`_tasks_main` 仍用 uuid）。

`ata/http.py` 改名端点改为：

```python
                ev = parse_event(envelope(
                    meta["agent"], sid, "session.renamed", {"title": title}))
```

http.py 顶部 import 改为 `from ata.schema import ValidationError, envelope, parse_event`。`time` 与 `uuid` 在 http.py 其他处仍使用（`_ingest_pi_hooks` 用 time；uuid 仅改名端点用，可从 import 删除——检查后若无其他引用则删）。

`ata/plugins/droid.py` 的 `refresh_titles` 中 `ledger.append({...})` 改为：

```python
        ledger.append(envelope(
            "droid", sid, "session.opened", {"title": title},
            ts=int(time.time() * 1000), eid=f"{sid}:title-fix:{digest}"))
```

droid.py 顶部加 `from ata.schema import envelope`。注意 droid.py 原有 `import hashlib`、`import time` 仍被 refresh_titles 使用（digest 与 ts），保留。

- [ ] **Step 6: 全量测试 + 提交**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 PASS（test_cli_rate、test_http、test_droid 覆盖了这三条路径）

```bash
git add ata/schema.py ata/cli.py ata/http.py ata/plugins/droid.py tests/test_schema.py
git commit -m "refactor(schema): envelope() 单一信封工厂收编 CLI/HTTP/droid 三处内联组装"
```

---

### Task 2: `plugins/common.py` 翻译内核——信封、工具双行、轮次递增、usage 三态

**Files:**
- Create: `ata/plugins/common.py`
- Modify: `ata/plugins/pi.py`, `ata/plugins/claude.py`, `ata/plugins/codex.py`, `ata/plugins/droid.py`
- Test: 新建 `tests/test_plugins_common.py`

**Interfaces:**
- Produces（后续任务与五个适配器共用）:
  - `make_ev(eid, agent_id, session_id, ts, typ, turn, payload) -> dict`（等价于各文件的 `_ev`）
  - `PLACEHOLDER_MS = 1`（耗时未知占位约定；project.py 的同名常量改为从这里 re-import 或对齐注释）
  - `tool_start_payload(cid, parent_mid, name, args, text_fn, started_at) -> dict`
  - `tool_end_payload(prev, cid, parent_fallback, result_text, completed_ts) -> tuple[dict, str]`（返回 `(payload, eid_suffix)` 太绕，实际签名见 Step 3：`emit_tool_pair(state, cid, name, args, result, is_error, ts, agent_id, session_id, eid_base, turn, text) -> list[dict]` 以最终代码为准）
  - `bump_turn_if_real_user(state, texts, agent_id, session_id, ts, out_append) -> int`（真实用户消息才递增轮次并补 turn.started；CONTEXT 注入不开新轮）
  - `usage_missing() -> dict`（全 NULL missing 形状的唯一构造）
  - `usage_from_counts(inp, outp, cache_read, cache_write, total_tokens=None, cost=None) -> dict`（全 0 → missing，否则 reported）

设计裁决（写进 common.py 头注释）：jsonl 适配器无 state 机不参与；pi 走 hook 通道，轮次逻辑不同构，只收编它的 `_ev` 与 usage 两块。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_plugins_common.py`：

```python
import unittest

from ata.plugins.common import (
    PLACEHOLDER_MS,
    bump_turn_if_real_user,
    make_ev,
    tool_start_payload,
    usage_from_counts,
    usage_missing,
)


class MakeEvTest(unittest.TestCase):
    def test_seven_keys(self):
        ev = make_ev("s:t1:start", "claude", "s1", 1000, "turn.started", 1, {})
        self.assertEqual(ev, {
            "v": 1, "id": "s:t1:start", "agent_id": "claude",
            "session_id": "s1", "ts": 1000, "type": "turn.started",
            "turn": 1, "payload": {}})


class UsageTest(unittest.TestCase):
    def test_all_zero_is_missing(self):
        u = usage_from_counts(0, 0, 0, 0)
        self.assertEqual(u["status"], "missing")
        for k in ("input", "output", "cache_read", "cache_write", "total_tokens", "cost"):
            self.assertIsNone(u[k])

    def test_reported(self):
        u = usage_from_counts(10, 5, 2, 3, total_tokens=15)
        self.assertEqual(u, {"status": "reported", "input": 10, "output": 5,
                             "cache_read": 2, "cache_write": 3,
                             "total_tokens": 15, "cost": None})

    def test_usage_missing_shape(self):
        u = usage_missing()
        self.assertEqual(u["status"], "missing")


class ToolPairTest(unittest.TestCase):
    def test_start_then_end_roundtrip(self):
        state = {}
        start = tool_start_payload(
            "c1", "m1", "Bash", {"command": "ls"},
            lambda a: a.get("command") or "", 1000)
        state.setdefault("tools", {})["c1"] = start
        end = tool_end_payload(
            state["tools"].get("c1"), "c1", "m1", "files", False, 1500)
        self.assertEqual(end["status"], "completed")
        self.assertEqual(end["parent_message_id"], "m1")   # 从 prev 回填
        self.assertEqual(end["payload"], {"command": "ls"})
        self.assertEqual(end["started_at"], 1000)
        # end 行的 duration 是占位约定值
        self.assertEqual(end["duration_ms"], PLACEHOLDER_MS)


class BumpTurnTest(unittest.TestCase):
    def test_real_user_message_starts_turn(self):
        state = {}
        events = []
        turn = bump_turn_if_real_user(state, "你好", "claude", "s1", 1000,
                                      lambda e: events.append(e))
        self.assertEqual(turn, 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "turn.started")

    def test_context_injection_does_not_start_turn(self):
        state = {}
        events = []
        turn = bump_turn_if_real_user(state, "<system-reminder>x", "claude", "s1", 1000,
                                      lambda e: events.append(e))
        self.assertIsNone(turn)
        self.assertEqual(events, [])

    def test_repeat_same_turn_no_duplicate_started(self):
        state = {}
        seen = []
        bump_turn_if_real_user(state, "a", "c", "s", 1, lambda e: seen.append(e))
        bump_turn_if_real_user(state, "b", "c", "s", 2, lambda e: seen.append(e))
        self.assertEqual(len(seen), 1)  # 同一轮只发一次 turn.started


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_plugins_common -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'ata.plugins.common'`

- [ ] **Step 3: 实现 common.py**

新建 `ata/plugins/common.py`：

```python
"""适配器共享翻译词汇表（架构评审候选 1）。

五个适配器的 interface 很深（translate_line/hook → 事件列表），但共享约定
此前靠注释互相引用维系：信封逐字五份、工具双行协议三份、轮次递增三份变体、
usage 三态四份方言映射、「全 0 计 missing」判定三处各写一遍。占位时长 bug
（9a89da5 修 pi 后 1d36d61 还要在消费端再防御一次）证明约定需要单一归属地。

这里只收真正同构的部分；各家方言差异（字段名映射、事件路由）留给适配器。
jsonl 适配器无状态机不参与；pi 走 hook 通道轮次逻辑不同构，只收 _ev 与
usage 两块。
"""
from __future__ import annotations

from ata.project import is_context_text

# claude/codex/droid 的「耗时未知」占位约定：转录不带耗时统一写 1，
# 消费端 summarize_timing 按 >PLACEHOLDER_MS 过滤。与 project.PLACEHOLDER_MS 同值。
PLACEHOLDER_MS = 1


def make_ev(eid, agent_id, session_id, ts, typ, turn, payload):
    return {
        "v": 1,
        "id": eid,
        "agent_id": agent_id,
        "session_id": session_id,
        "ts": int(ts),
        "type": typ,
        "turn": turn,
        "payload": payload,
    }


_MISSING_SHAPE = {
    "status": "missing",
    "input": None, "output": None,
    "cache_read": None, "cache_write": None,
    "total_tokens": None, "cost": None,
}


def usage_missing():
    return dict(_MISSING_SHAPE)


def usage_from_counts(inp, outp, cache_read, cache_write, total_tokens=None, cost=None):
    """四元计数 → ATA usage。「全 0 计 missing」判定的唯一归属地。"""
    if not any((inp, outp, cache_read, cache_write)):
        return usage_missing()
    return {
        "status": "reported",
        "input": inp, "output": outp,
        "cache_read": cache_read, "cache_write": cache_write,
        "total_tokens": total_tokens, "cost": cost,
    }


def tool_start_payload(cid, parent_mid, name, args, text, started_at):
    """工具双行协议的 start 行 payload。state["tools"][cid] 存一份，
    end 行从 prev 回填 parent/payload/text/started_at（转录里 result 行不带这些）。"""
    payload = {
        "tool_call_id": cid,
        "parent_message_id": parent_mid,
        "name": name,
        "text": text,
        "status": "pending",
        "payload": args,
        "result": None,
        "started_at": started_at,
        "duration_ms": None,
    }
    return payload


def tool_end_payload(prev, cid, parent_fallback, result, completed_at):
    """工具双行协议的 end 行 payload：从 start 存的 prev 回填，缺失走 fallback。"""
    prev = prev or {}
    return {
        "tool_call_id": cid,
        "parent_message_id": prev.get("parent_message_id") or parent_fallback,
        "name": prev.get("name") or "tool",
        "text": prev.get("text") or (result[:200] if result else cid),
        "status": "completed",
        "payload": prev.get("payload"),
        "result": result,
        "started_at": prev.get("started_at") or completed_at,
        "duration_ms": PLACEHOLDER_MS,
    }


def bump_turn_if_real_user(state, texts, agent_id, session_id, ts, emit):
    """真实用户消息才开新轮并补 turn.started；CONTEXT 注入不开轮。

    返回本轮轮次号（未开新轮返回当前轮或 None）。emit(event) 由调用方提供
    （通常是把事件 append 进输出列表的闭包）。started_turns 防同一轮重复发。
    """
    if is_context_text(texts):
        return state.get("turn") or None
    state["turn"] = int(state.get("turn") or 0) + 1
    turn = state["turn"]
    if turn not in state.setdefault("started_turns", set()):
        state["started_turns"].add(turn)
        emit(make_ev(
            f"{session_id}:turn:{turn}:start", agent_id, session_id, ts,
            "turn.started", turn, {},
        ))
    return turn
```

注意：测试里 `tool_end_payload(state["tools"].get("c1"), "c1", "m1", "files", False, 1500)` 的签名是 `(prev, cid, parent_fallback, result, completed_at)` 六参误植为六参——以实现签名为准回改测试调用（去掉多余的 `False` 参数），保证两端一致。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_plugins_common -v`
Expected: PASS

- [ ] **Step 5: 五个适配器切换到共享内核（机械替换，不改行为）**

每个适配器的替换规则：

**claude.py**：
1. 删除本地 `_ev`（190-200 行），顶部加 `from ata.plugins.common import (PLACEHOLDER_MS, bump_turn_if_real_user, make_ev, tool_end_payload, tool_start_payload, usage_from_counts, usage_missing)`，全文 `_ev(` 替换为 `make_ev(`。
2. `_usage`（278-312 行）改为薄封装：

```python
def _usage(msg):
    """assistant message.usage（官方 API 驼峰）→ ATA 蛇形 usage。"""
    raw = (msg or {}).get("usage")
    if not isinstance(raw, dict) or not raw:
        return usage_missing()
    return usage_from_counts(
        int(raw.get("input_tokens") or 0),
        int(raw.get("output_tokens") or 0),
        int(raw.get("cache_read_input_tokens") or 0),
        int(raw.get("cache_creation_input_tokens") or 0),
    )
```

3. 轮次递增块（49-59 行）改为：

```python
        if role == "user" and not is_tool_only:
            turn = bump_turn_if_real_user(
                state, texts, agent_id, session_id, ts,
                lambda e: out.append(e))
            if turn is not None:
                state["last_assistant_id"] = None
            else:
                turn = state.get("turn") or 1
```

（保持后续 `turn` 变量语义不变；CONTEXT 分支原来走 else 设 `turn = state.get("turn") or 1`，合并进上面。）

4. tool_use 块（89-113 行）start 部分改为用 `tool_start_payload`：

```python
            payload = tool_start_payload(
                cid, state.get("last_assistant_id"), name, args,
                _tool_text(name, args), ts)
            state.setdefault("tools", {})[cid] = payload
            out.append(make_ev(
                f"{session_id}:tool:{cid}:start", agent_id, session_id, ts,
                "tool.upserted", state.get("turn") or 1, payload))
```

5. tool_result 块 end 部分改为：

```python
                end_payload = tool_end_payload(prev, cid, state.get("last_assistant_id"), result, ts)
                out.append(make_ev(
                    f"{session_id}:tool:{cid}:end", agent_id, session_id, ts,
                    "tool.upserted", state.get("turn") or 1, end_payload))
```

6. `"duration_ms": 1` 两处（83、132 行）改引用 `PLACEHOLDER_MS`。

**codex.py**：同样删本地 `_ev`，`make_ev` 替换；`_usage`（293-316 行）改薄封装调 `usage_from_counts(last.get("input_tokens"), last.get("output_tokens"), last.get("cached_input_tokens"), last.get("cache_write_input_tokens"), total_tokens=last.get("total_tokens"))`；function_call/function_call_output 两个分支改用 `tool_start_payload`/`tool_end_payload`（codex 的 name 回填只取 `prev.get("name")`，与 common 的 `prev.get("name") or "tool"` 兼容）；`"duration_ms": 1` 改 `PLACEHOLDER_MS`。

**droid.py**：同 claude 的替换清单（结构几乎相同）；另外 `refresh_titles` 已在 Task 1 换成 envelope，无需动。

**pi.py**：只做两件——删本地 `_ev` 换 `make_ev`；`usage_from_assistant` 里两处 missing dict 字面量改 `usage_missing()`，reported 分支保持原样（pi 的字段是驼峰直取，不走 counts 路径）。

- [ ] **Step 6: 全量回归（这是行为保持的关键闸门）**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 PASS。特别关注 test_claude、test_codex、test_droid、test_pi*、test_timing、test_accept——它们锁死了各适配器的输出形状。若有断言失败，优先怀疑替换引入行为偏差而不是改断言。

- [ ] **Step 7: project.py 的占位常量对齐归属地**

`ata/project.py:483-484` 的注释与常量改为：

```python
from ata.plugins.common import PLACEHOLDER_MS  # 占位约定唯一归属地在 plugins/common.py
```

（放在 summarize_timing 上方；删除本地定义，保留解释性注释。）

- [ ] **Step 8: 再跑全量 + 提交**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

```bash
git add ata/plugins/common.py ata/plugins/pi.py ata/plugins/claude.py ata/plugins/codex.py ata/plugins/droid.py ata/project.py tests/test_plugins_common.py
git commit -m "refactor(plugins): 共享翻译内核 common.py 收编信封/工具双行/轮次递增/usage 三态"
```

---

## Phase 2 · 会话元事实折叠收敛（评审候选 4）

### Task 3: `fold_session_meta` 纯函数 + 删除 ledger 死代码

**Files:**
- Create: `ata/fold.py`
- Modify: `ata/ledger.py:147-229`（`_append_locked` 的标题/父引用段；删 :191-194 死代码）
- Test: 新建 `tests/test_fold.py`

**Interfaces:**
- Consumes: 无依赖前置任务。
- Produces: `fold.fold_session_meta(existing: dict | None, event: dict) -> dict`，返回折叠后的会话元事实行：`{"title": str, "renamed": bool, "turns": int, "last_ts": int, "first_ts": int, "parent_session_id": str | None}`。输入 existing 为 None 表示新会话（title 默认 session_id）。`_REAL_TS_FLOOR = 10**12` 从 ledger 移到 fold 并被双方引用。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_fold.py`：

```python
import unittest

from ata.fold import fold_session_meta


def opened(title="t1", ts=1000, parent=None):
    p = {"title": title}
    if parent:
        p["parent_session"] = parent
    return {"type": "session.opened", "ts": ts, "turn": None, "payload": p}


def renamed(title, ts=2000):
    return {"type": "session.renamed", "ts": ts, "turn": None, "payload": {"title": title}}


class FoldTest(unittest.TestCase):
    def test_new_session_from_opened(self):
        row = fold_session_meta(None, opened(ts=1000))
        self.assertEqual(row["title"], "t1")
        self.assertFalse(row["renamed"])
        self.assertEqual(row["first_ts"], 1000)
        self.assertIsNone(row["parent_session_id"])

    def test_renamed_wins_over_later_opened(self):
        row = fold_session_meta({"title": "user-name", "renamed": True}, opened(title="opened-t"))
        self.assertEqual(row["title"], "user-name")

    def test_opened_overwrites_when_not_renamed(self):
        row = fold_session_meta({"title": "old", "renamed": False}, opened(title="new"))
        self.assertEqual(row["title"], "new")

    def test_dirty_small_ts_not_first_ts(self):
        row = fold_session_meta(None, opened(ts=1))
        self.assertEqual(row["first_ts"], 0)

    def test_parent_preserved_on_non_opened(self):
        row = fold_session_meta({"parent_session_id": "p1"},
                                renamed("x"))
        self.assertEqual(row["parent_session_id"], "p1")

    def test_parent_updated_on_opened(self):
        row = fold_session_meta({"parent_session_id": "p0"}, opened(parent="p1"))
        self.assertEqual(row["parent_session_id"], "p1")

    def test_bump_turns(self):
        row = fold_session_meta({"turns": 3}, {"type": "message.upserted", "ts": 5, "turn": 7, "payload": {}})
        self.assertEqual(row["turns"], 7)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_fold -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'ata.fold'`

- [ ] **Step 3: 实现 fold.py**

新建 `ata/fold.py`：

```python
"""会话元事实折叠（架构评审候选 4）。

「latest-wins、用户改名后 opened 不再覆盖」的标题规则此前同时活在三处：
ledger._append_locked 的索引维护、project_session 的投影重推、droid 的
标题补写注释。这里给出唯一纯函数定义；账本索引维护调用它，投影层
project_session 的独立重推与之互为对照（两侧对同一事件流必须产出同题）。
"""
REAL_TS_FLOOR = 10 ** 12


def fold_session_meta(existing, event):
    """existing: 折叠态 dict（含 title/renamed/turns/last_ts/first_ts/
    parent_session_id）或 None（新会话）。event: 已解析的事件 dict。
    返回新的折叠态 dict（不改入参）。"""
    row = dict(existing) if existing else {
        "title": event.get("session_id") or "",
        "renamed": False,
        "turns": 0,
        "last_ts": 0,
        "first_ts": 0,
        "parent_session_id": None,
    }
    ts = int(event.get("ts") or 0)
    row["last_ts"] = max(row["last_ts"] or 0, ts)
    incoming_first = ts if ts > REAL_TS_FLOOR else 0
    if row["first_ts"] > REAL_TS_FLOOR:
        row["first_ts"] = min(row["first_ts"], incoming_first) if incoming_first else row["first_ts"]
    else:
        row["first_ts"] = incoming_first
    typ = event.get("type")
    p = event.get("payload") or {}
    if typ == "session.opened":
        # 用户改过名后 opened 只做兜底，不再覆盖（投影层同规则）
        if not row["renamed"]:
            row["title"] = p.get("title") or row["title"]
        if p.get("parent_session"):
            row["parent_session_id"] = p["parent_session"]
    elif typ == "session.renamed":
        row["title"] = p.get("title") or row["title"]
        row["renamed"] = True
    turn = event.get("turn")
    if isinstance(turn, int) and turn > row["turns"]:
        row["turns"] = turn
    return row
```

注意：原 `_append_locked` 里 opened 的 `parent = event["payload"].get("parent_session")` 是无条件赋值（可能抹成 None）；fold 版本加了 `if p.get(...)` 保护，与「NULL 是事实不是错误、非 opened 必须保留已有父引用」的既有注释意图一致。这是行为修正，若 test_ledger/test_lineage_ledger 有断言锁定旧行为（opened 不带 parent 时清空），按新行为更新断言并在 commit message 声明。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_fold -v`
Expected: PASS

- [ ] **Step 5: 接入 ledger._append_locked 并删死代码**

`ata/ledger.py` 改动：

1. 删除 191-194 行的第二个 `elif event["type"] == "session.renamed":` 分支（永不可达死代码）。
2. 153-207 行的元事实维护段改用 fold。改造后的 `_append_locked` 核心：

```python
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
        existing = None
        if row:
            existing = {
                "title": row["title"],
                # 改名权威判定：现 title 非 sid 且流里有 renamed 即视为已改名
                "renamed": row["title"] != sid and bool(self._has_renamed(sid)),
                "turns": int(row["turns"]),
                "last_ts": int(row["last_ts"] or 0),
                "first_ts": int(row["first_ts"] or 0),
                "parent_session_id": row["parent_session_id"],
            }
        folded = fold_session_meta(existing, event)
        if row:
            self._conn.execute(
                "UPDATE sessions SET agent_id=?, title=?, turns=?, last_seq=?, last_ts=?, first_ts=?, parent_session_id=? WHERE session_id=?",
                (event["agent_id"], folded["title"], folded["turns"], seq,
                 folded["last_ts"], folded["first_ts"], folded["parent_session_id"], sid),
            )
        else:
            self._conn.execute(
                "INSERT INTO sessions(session_id, agent_id, title, turns, last_seq, last_ts, first_ts, parent_session_id) VALUES (?,?,?,?,?,?,?,?)",
                (sid, event["agent_id"], folded["title"], folded["turns"], seq,
                 folded["last_ts"], folded["first_ts"], folded["parent_session_id"]),
            )
        # …… dedupe 段保持原样（208-229 行不动）
```

顶部 import 加 `from ata.fold import fold_session_meta, REAL_TS_FLOOR`；`_REAL_TS_FLOOR` 本地常量删除，boot 里的引用改 `REAL_TS_FLOOR`。

- [ ] **Step 6: 对照验证 + 全量回归**

Run: `python3 -m unittest tests.test_ledger tests.test_ledger_dedupe tests.test_lineage_ledger tests.test_session_rev tests.test_score_projection -v && python3 -m unittest discover -s tests -v`
Expected: 全部 PASS。test_ledger 的 `test_session_title_comes_from_index`、`test_first_ts_ignores_bogus_small_ts` 就是折叠规则的存量对照。

- [ ] **Step 7: 提交**

```bash
git add ata/fold.py ata/ledger.py tests/test_fold.py
git commit -m "refactor(ledger): fold_session_meta 纯函数统一会话元事实折叠，删除不可达 renamed 分支"
```

---

### Task 4: project_session 标题段改吃 fold（消除第三份实现）

**Files:**
- Modify: `ata/project.py:75-95`
- Test: `tests/test_project.py`（补一个互证测试）

**Interfaces:**
- Consumes: Task 3 的 `fold_session_meta`。
- Produces: `project_session` 的 title 语义与 fold 单一来源一致。

- [ ] **Step 1: 写互证测试（先跑通现状，锁定语义）**

在 `tests/test_project.py` 追加：

```python
class TitleAuthorityParityTest(unittest.TestCase):
    """投影层的标题折叠与账本侧 fold_session_meta 必须产出同一标题。

    架构评审候选 4：「用户改名后 opened 不再覆盖」曾同时实现在账本索引与
    投影重推两处。此测试让两份实现互为对照；漂移即红。
    """

    def _events(self):
        return [
            {"seq": 1, "event": {"v": 1, "id": "o", "agent_id": "pi", "session_id": "s",
                                 "ts": 1000, "type": "session.opened", "turn": None,
                                 "payload": {"title": "auto-title"}}},
            {"seq": 2, "event": {"v": 1, "id": "r", "agent_id": "pi", "session_id": "s",
                                 "ts": 2000, "type": "session.renamed", "turn": None,
                                 "payload": {"title": "user-name"}}},
            {"seq": 3, "event": {"v": 1, "id": "o2", "agent_id": "pi", "session_id": "s",
                                 "ts": 3000, "type": "session.opened", "turn": None,
                                 "payload": {"title": "late-opened"}}},
        ]

    def test_projection_and_fold_agree(self):
        from ata.fold import fold_session_meta
        recs = self._events()
        page = project_session("s", "pi", recs)
        folded = None
        for rec in recs:
            folded = fold_session_meta(folded, rec["event"])
        self.assertEqual(page["title"], folded["title"])

    def test_renamed_beats_late_opened(self):
        page = project_session("s", "pi", self._events())
        self.assertEqual(page["title"], "user-name")
```

- [ ] **Step 2: 跑测试确认通过（现状已符合语义）**

Run: `python3 -m unittest tests.test_project -v`
Expected: PASS。若 `test_renamed_beats_late_opened` 失败说明现状投影就有 bug——停下来向用户报告，不要顺手修语义。

- [ ] **Step 3: project_session 标题段接入 fold**

`ata/project.py` 的 `project_session` 开头（75-95 行）改为：

```python
def project_session(session_id, agent, recs, *, tail=None, before=None):
    from ata.fold import fold_session_meta
    meta_folded = None
    for rec in recs:
        ev = rec["event"]
        if ev["type"] in ("session.opened", "session.renamed"):
            meta_folded = fold_session_meta(meta_folded, ev)
    title = meta_folded["title"] if meta_folded else session_id
```

随后删除原 89-95 行的两个 title 分支（`if ev["type"] == "session.opened": ... continue` 与 renamed 分支），主循环里这两个 continue 保持（事件不再参与实体折叠）。顶部不再需要函数级 import——按仓库风格移到文件顶部 `from ata.fold import fold_session_meta`。

- [ ] **Step 4: 全量回归 + 提交**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

```bash
git add ata/project.py tests/test_project.py
git commit -m "refactor(project): 标题投影改吃 fold_session_meta，标题权威只剩一处定义"
```

---

## Phase 3 · 投影缓存与前端 useSummary（评审候选 2 + 候选 5 SQL 去重）

### Task 5: 服务端投影缓存——rev 门控覆盖便捷层四端点

**Files:**
- Create: `ata/projection_cache.py`
- Modify: `ata/http.py:52-140`（do_GET 四个便捷层分支）
- Test: 新建 `tests/test_projection_cache.py`

**Interfaces:**
- Consumes: 无。
- Produces: `ProjectionCache` 类：
  - `get_or_compute(sid: str, rev: int, kind: str, compute: Callable[[], dict]) -> dict` —— rev 未变直接回缓存（返回的是缓存对象的浅拷贝语义由调用方保证不被修改），rev 变了执行 compute 并存 `{(sid, kind): (rev, result)}`。
  - `invalidate_prefix(sid: str) -> None`（预留；本任务不需要）。

外部 HTTP 形状零变化——spec 冻结红线。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_projection_cache.py`：

```python
import unittest

from ata.projection_cache import ProjectionCache


class ProjectionCacheTest(unittest.TestCase):
    def test_same_rev_hits_cache(self):
        cache = ProjectionCache()
        calls = []
        def compute():
            calls.append(1)
            return {"llm_ms": 5}
        self.assertEqual(cache.get_or_compute("s1", 3, "timing", compute), {"llm_ms": 5})
        self.assertEqual(cache.get_or_compute("s1", 3, "timing", compute), {"llm_ms": 5})
        self.assertEqual(len(calls), 1)

    def test_rev_bump_recomputes(self):
        cache = ProjectionCache()
        calls = []
        def compute():
            calls.append(len(calls))
            return {"n": len(calls)}
        cache.get_or_compute("s1", 3, "timing", compute)
        self.assertEqual(cache.get_or_compute("s1", 4, "timing", compute)["n"], 2)

    def test_kinds_are_independent_slots(self):
        cache = ProjectionCache()
        cache.get_or_compute("s1", 3, "timing", lambda: {"k": "timing"})
        got = cache.get_or_compute("s1", 3, "usage", lambda: {"k": "usage"})
        self.assertEqual(got, {"k": "usage"})

    def test_sessions_are_isolated(self):
        cache = ProjectionCache()
        cache.get_or_compute("s1", 3, "timing", lambda: {"who": "s1"})
        got = cache.get_or_compute("s2", 3, "timing", lambda: {"who": "s2"})
        self.assertEqual(got, {"who": "s2"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_projection_cache -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现投影缓存**

新建 `ata/projection_cache.py`：

```python
"""便捷层投影缓存（架构评审候选 2）。

账本是 append-only，sessions.last_seq 天然是会话级版本号——GET /api/sessions/{id}
早已用它做 rev 门控短路，但 /usage /tools /tool-stats /timing 四个端点每次都
全量 read+重算。缓存的键是 (session_id, kind)，值带 rev；请求 rev 与缓存 rev
一致即回缓存。单进程内存态，服务重启即空，无需持久化——投影可重建是 CONTEXT.md
写明的性质。线程安全靠一把锁（HTTP handler 是 ThreadingHTTPServer 多线程）。
"""
from __future__ import annotations

import threading


class ProjectionCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._slots: dict[tuple[str, str], tuple[int, object]] = {}

    def get_or_compute(self, sid: str, rev: int, kind: str, compute):
        with self._lock:
            hit = self._slots.get((sid, kind))
            if hit is not None and hit[0] == rev:
                return hit[1]
            # compute 可能慢（全量 read+折叠），放锁外避免阻塞其他会话；
            # 竞态下同 kind 可能算两次，幂等无害。
        result = compute()
        with self._lock:
            self._slots[(sid, kind)] = (rev, result)
        return result

    def invalidate_prefix(self, sid: str) -> None:
        with self._lock:
            for key in [k for k in self._slots if k[0] == sid]:
                del self._slots[key]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_projection_cache -v`
Expected: PASS

- [ ] **Step 5: 接线 http.py 四个分支**

`make_server` 内，`Handler` 定义之前：

```python
    cache = ProjectionCache()

    def cached_summary(sid, kind):
        """便捷层统一入口：rev 门控 + read+compute。rev 取自 session 行，
        调用前已确保会话存在。"""
        meta = ledger.session(sid)
        return cache.get_or_compute(sid, int(meta["last_seq"]), kind,
                                    lambda: ledger.read(sid))

    def summary_response(sid, kind, fn):
        recs = cached_summary(sid, kind)
        return fn(recs)
```

四个分支改为经 `summary_response` 取 recs（外部 JSON 形状一字不变）：

```python
                if sub == "usage":
                    def usage_body(recs):
                        compactions = [{"turn": r["event"].get("turn"), "seq": r["seq"]}
                                       for r in recs if r["event"]["type"] == "compaction.boundary"]
                        return {"ok": True, **summarize_usage(recs),
                                "audit": audit_usage(recs), "compactions": compactions}
                    return self._json(200, summary_response(sid, "usage", usage_body))
                if sub == "tools":
                    full = qs.get("full", ["false"])[0] == "true"
                    def tools_body(recs):
                        rows = list_tools(recs, qs.get("status", [None])[0], qs.get("name", [None])[0])
                        for r in rows:
                            r["result"] = r["result"] if full else tail_preview(r["result"])
                        return {"ok": True, "tools": rows}
                    return self._json(200, summary_response(sid, "tools", tools_body))
                if sub == "tool-stats":
                    return self._json(200, summary_response(sid, "tool-stats",
                                                            lambda recs: {"ok": True, **summarize_tools(recs)}))
                if sub == "timing":
                    return self._json(200, summary_response(sid, "timing",
                                                            lambda recs: {"ok": True, **summarize_timing(recs)}))
```

注意 `full=true` 的预览截断在 body 函数里做、不进缓存——缓存的是完整投影结果，截断按请求参数即时套。http.py 顶部加 `from ata.projection_cache import ProjectionCache`。

- [ ] **Step 6: 写一条 HTTP 层验证（缓存命中不改响应形状）**

在 `tests/test_http_new_routes.py` 追加：

```python
    def test_usage_endpoint_twice_same_body(self):
        """rev 未变时二次请求应命中缓存且响应体一致（外部形状冻结的回归锚）。"""
        first = self.get("/api/sessions/droid-missing/usage")
        second = self.get("/api/sessions/droid-missing/usage")
        self.assertEqual(first, second)
```

（沿用该文件既有的 setUp/get 辅助；若该文件的会话 id 不同，替换为本文件 setUp 里实际存在的 sid。）

Run: `python3 -m unittest tests.test_http_new_routes tests.test_http -v`
Expected: PASS

- [ ] **Step 7: 全量回归 + 提交**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

```bash
git add ata/projection_cache.py ata/http.py tests/test_projection_cache.py tests/test_http_new_routes.py
git commit -m "perf(http): rev 门控投影缓存覆盖便捷层四端点，外部形状不变"
```

---

### Task 6: `useSummary` hook 统一前端派生数据获取，修复 stale-panel

**Files:**
- Create: `webapp/src/api/useSummary.ts`
- Modify: `webapp/src/components/session/TimeBadge.tsx`
- Modify: `webapp/src/components/session/UsagePanel.tsx`（UsageBadges 与 UsagePanel 两个组件）
- Test: 新建 `webapp/src/api/useSummary.test.tsx`

**Interfaces:**
- Consumes: Task 5 的服务端缓存（非必需——hook 自身按 sessionId+可见性刷新就成立）。
- Produces:

```typescript
export function useSummary<T>(
  path: string | null,
  deps: readonly unknown[],
): { data: T | null; reload: () => void }
```

语义：path 为 null 不拉；deps 变化即重拉（换会话）；组件挂载时拉一次；之后订阅全局节拍（导出 `nudgeSummaries()`），live tailing 期间由 useSession 的 rowsChanged 报告触发 nudge，所有 useSummary 消费者统一刷新。dataFor 守卫模式（换会话过渡期渲染 null）收进 hook 内部。

- [ ] **Step 1: 写失败测试**

新建 `webapp/src/api/useSummary.test.tsx`：

```tsx
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nudgeSummaries, useSummary } from './useSummary'

describe('useSummary', () => {
  let fetchCalls: string[]
  beforeEach(() => {
    fetchCalls = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      fetchCalls.push(path)
      return {
        ok: true,
        json: async () => ({ path, n: fetchCalls.length }),
      } as Response
    }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('fetches once on mount and exposes data', async () => {
    const { result } = renderHook(() => useSummary<{ n: number }>('/api/sessions/s1/timing', ['s1']))
    await act(async () => {})
    expect(result.current.data).not.toBeNull()
    expect(fetchCalls).toEqual(['/api/sessions/s1/timing'])
  })

  it('null path never fetches', async () => {
    renderHook(() => useSummary('/x', []))
    // path=null 的场景用第二个用例覆盖
  })

  it('does not fetch when path is null', async () => {
    const { result } = renderHook(() => useSummary<{ n: number }>(null, []))
    await act(async () => {})
    expect(result.current.data).toBeNull()
    expect(fetchCalls).toEqual([])
  })

  it('deps change refetches and stale response is dropped', async () => {
    const { result, rerender } = renderHook(
      ({ sid }: { sid: string }) => useSummary<{ path: string }>(`/api/sessions/${sid}/timing`, [sid]),
      { initialProps: { sid: 's1' } },
    )
    await act(async () => {})
    rerender({ sid: 's2' })
    await act(async () => {})
    expect(result.current.data?.path).toBe('/api/sessions/s2/timing')
  })

  it('nudge triggers one refetch per consumer', async () => {
    const { result } = renderHook(() => useSummary<{ n: number }>('/t', ['k']))
    await act(async () => {})
    const before = fetchCalls.length
    act(() => { nudgeSummaries() })
    await act(async () => {})
    expect(fetchCalls.length).toBe(before + 1)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd webapp && npx vitest run src/api/useSummary.test.tsx`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 useSummary**

新建 `webapp/src/api/useSummary.ts`：

```typescript
// 派生数据（usage/timing/tool-stats）的统一获取 hook（架构评审候选 2）。
//
// 旧问题：三个组件各自裸拉一次且只在换会话时刷新，live tailing 期间静默过期
// （旧版 web/js/app.js 的 report.rowsChanged 统一刷新在 React 迁移中丢失）。
// dataFor 守卫、失败置 null、nudge 触发刷新从此只有这一份实现。
import { useCallback, useEffect, useRef, useState } from 'react'

type Listener = () => void
const listeners = new Set<Listener>()

/** live tailing 检测到数据变化时通知全部 useSummary 消费者重新拉取。 */
export function nudgeSummaries(): void {
  for (const l of listeners) l()
}

export function useSummary<T>(
  path: string | null,
  deps: readonly unknown[],
): { data: T | null; reload: () => void } {
  // dataFor 记录 data 归属的路径：换目标过渡期渲染 null，不在 effect 里同步置空
  const [state, setState] = useState<{ dataFor: string | null; data: T | null }>({ dataFor: null, data: null })
  const aliveRef = useRef(true)
  useEffect(() => {
    aliveRef.current = true
    return () => { aliveRef.current = false }
  }, [])

  const load = useCallback((p: string) => {
    fetch(p)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((d: T) => { if (aliveRef.current) setState({ dataFor: p, data: d }) })
      .catch(() => { if (aliveRef.current) setState({ dataFor: p, data: null }) })
  }, [])

  useEffect(() => {
    if (!path) { setState({ dataFor: null, data: null }); return }
    load(path)
  }, [path, load, ...deps])  // eslint-disable-line react-hooks/exhaustive-deps -- deps 由调用方声明

  useEffect(() => {
    const listener = () => { if (path) load(path) }
    listeners.add(listener)
    return () => { listeners.delete(listener) }
  }, [path, load])

  const reload = useCallback(() => { if (path) load(path) }, [path, load])
  const data = state.dataFor === path ? state.data : null
  return { data, reload }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd webapp && npx vitest run src/api/useSummary.test.tsx`
Expected: PASS（5 个用例）

- [ ] **Step 5: TimeBadge 切换到 useSummary**

`TimeBadge.tsx` 的 state 与首个 useEffect（16-26 行）替换为：

```typescript
  const { data } = useSummary<TimingSummary>(
    sessionId ? `/api/sessions/${encodeURIComponent(sessionId)}/timing` : null,
    [sessionId],
  )
```

删除本地 `dataFor` state、`alive` effect 与 `const data = state.dataFor === sessionId ? ...` 行（40 行的 `if (!data) return null` 保留）。import 行加 `import { useSummary } from '../../api/useSummary'`，`useState` 若不再使用则从 react import 中移除。

- [ ] **Step 6: UsageBadges 与 UsagePanel 同样切换**

UsagePanel.tsx 两个组件各自的 `useState<UsageSummary | null>` + useEffect 替换为同样的 `useSummary<UsageSummary>('/api/sessions/{id}/usage', [sessionId])` 模式。UsageBadges 保留 open/onToggle props 不变。

- [ ] **Step 7: useSession 的 rowsChanged 触发 nudge（修复 stale-panel 的关键一步）**

`webapp/src/api/useSession.ts` 的轮询 run() 里，`applySessionPage` 之后：

```typescript
        if (!isUnchanged(res)) {
          const next = applySessionPage(...)
          dataRef.current = next.next
          setSessionData(next.next)
          if (next.report.rowsChanged || next.report.metaChanged) nudgeSummaries()
        }
```

（注意 applySessionPage 返回 `{next, report}`——现代码解构方式相应调整。）顶部 `import { nudgeSummaries } from './useSummary'`。

- [ ] **Step 8: 前端全量测试 + lint + 构建**

Run: `cd webapp && npx vitest run && npm run lint && npm run build`
Expected: 全部 PASS；构建产物落 `../web/dist`

- [ ] **Step 9: 提交**

```bash
git add webapp/src/api/useSummary.ts webapp/src/api/useSummary.test.tsx webapp/src/api/useSession.ts webapp/src/components/session/TimeBadge.tsx webapp/src/components/session/UsagePanel.tsx
git commit -m "fix(webapp): useSummary 统一派生数据获取，rowsChanged 触发刷新修复 live tailing 静默过期"
```

---

### Task 7: sessions()/annotations() 的 error_count SQL 去重（并入缓存收益）

**Files:**
- Modify: `ata/ledger.py:249-280`（`sessions`）、`ata/ledger.py:391-453`（`annotations`）
- Test: `tests/test_ledger.py`（已有 `test_sessions_count_events_and_failed_tools` 锁形状，只需确认不破）

**Interfaces:**
- Consumes: 无。
- Produces: `Ledger._error_counts_sql()` 私有辅助——两个方法共用同一段 error_count 子查询文本。行为零变化，纯去重。

- [ ] **Step 1: 先跑存量测试锁定形状**

Run: `python3 -m unittest tests.test_ledger tests.test_annotations -v`
Expected: PASS（基线）

- [ ] **Step 2: 抽取共用 SQL 片段**

`Ledger` 类内加：

```python
    # 侧栏卡片 meta 行要事件数与失败工具数。json_extract 走 event_json 单行扫描；
    # sessions() 与 annotations() 各引一份此片段，口径改动只动这里。
    _COUNTS_SQL = """
        SELECT session_id,
               COUNT(*) AS event_count,
               SUM(CASE WHEN type='tool.upserted'
                         AND json_extract(event_json,'$.payload.status')='failed'
                    THEN 1 ELSE 0 END) AS error_count
        FROM events GROUP BY session_id
    """
```

`sessions()` 的 counts 查询改为 `self._conn.execute(self._COUNTS_SQL).fetchall()`；`annotations()` 的 metas 子查询改为 f-string 引用 `f"... LEFT JOIN ({self._COUNTS_SQL}) c ON c.session_id = s.session_id"`。同步删除 sessions() 上方那段 O(n) 注释里的重复描述（保留一句指向 _COUNTS_SQL）。

- [ ] **Step 3: 回归 + 提交**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

```bash
git add ata/ledger.py
git commit -m "refactor(ledger): error_count 子查询单一归属，sessions/annotations 共用"
```

---

## Phase 4 · compare 改吃便捷层（评审候选 6）

### Task 8: collect_task_score 改从便捷层端点取数

**Files:**
- Modify: `ata/cli.py:233-261`（collect_task_score）、`ata/cli.py:305-309`（fetch_scores）
- Test: 重写 `tests/test_regression.py` 的 TestCollectTaskScore 部分

**Interfaces:**
- Consumes: 便捷层端点响应形状（spec 冻结）：`/usage` → `{"turns": [...], "total": {...}, "missing_turns": N}`；`/tools?full=false` → `{"tools": [{name, status, duration_ms, ...}]}`；`/timing` → summarize_timing 返回体（span_ms 等）。
- Produces: `collect_task_score(usage_resp: dict, tools_resp: dict, timing_resp: dict, human_score, turns) -> list[dict]` —— 输出 METRICS 词表不变（human_score/turns/tool_fail_rate/tokens_reported/usage_missing_turns/duration_s），数值口径改由便捷层供给。`fetch_scores` 相应改为三次 GET。

- [ ] **Step 1: 重写测试（新口径，TDD）**

`tests/test_regression.py` 的 `TestCollectTaskScore` 整类替换为：

```python
class TestCollectTaskScoreFromConvenienceLayer(unittest.TestCase):
    """compare 的指标推导改吃便捷层端点（spec 定稿形状）。

    旧实现抓整页主投影在客户端重推 tool_fail_rate/tokens/duration，与
    summarize_* 的口径漂移（duration 含占位 1ms 行、tokens 行级 vs 逐轮）。
    新实现直接消费 /usage /tools /timing 的响应，口径纪律只在便捷层一份。
    """

    def collect(self, *, tools=None, usage=None, timing=None, scores=None, turns=3):
        from ata.cli import collect_task_score
        return {
            r["name"]: r["value"]
            for r in collect_task_score(
                usage if usage is not None else {"turns": [], "total": {}, "missing_turns": 0},
                tools if tools is not None else {"tools": []},
                timing if timing is not None else {},
                (scores or [{"value": None}])[-1].get("value"),
                turns,
            )
        }

    def test_fail_rate_and_tokens_from_convenience_shapes(self):
        vals = self.collect(
            tools={"tools": [{"status": "failed"}, {"status": "completed"}]},
            usage={"turns": [
                {"status": "reported", "total_tokens": 120},
                {"status": "reported", "total_tokens": 80},
            ], "total": {}, "missing_turns": 0},
        )
        self.assertEqual(vals["tool_fail_rate"], 0.5)
        self.assertEqual(vals["tokens_reported"], 200)
        self.assertEqual(vals["usage_missing_turns"], 0)

    def test_missing_stays_missing_not_zero(self):
        vals = self.collect(
            usage={"turns": [{"status": "missing"}], "total": {}, "missing_turns": 1},
        )
        self.assertIsNone(vals["tokens_reported"])
        self.assertEqual(vals["usage_missing_turns"], 1)
        self.assertIsNone(vals["human_score"])
        self.assertIsNone(vals["tool_fail_rate"])   # 无工具调用即 missing

    def test_duration_excludes_placeholder_rows(self):
        # span 来自 summarize_timing（已排除占位），不再客户端拼 startedAt±durationMs
        vals = self.collect(timing={"span_ms": 1700})
        self.assertEqual(vals["duration_s"], 1.7)

    def test_span_missing_gives_none(self):
        vals = self.collect(timing={})
        self.assertIsNone(vals["duration_s"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_regression -v`
Expected: FAIL（collect_task_score 还是旧签名）

- [ ] **Step 3: 重写 collect_task_score 与 fetch_scores**

`ata/cli.py`：

```python
def collect_task_score(usage_resp, tools_resp, timing_resp, human_score, turns):
    """便捷层响应 → 单会话 score 记录。缺数据记 None（missing），永不当作 0。

    口径全部来自便捷层（spec 定稿端点）：fail_rate 出 /tools，tokens 出
    /usage 逐轮 reported 合计，duration 出 /timing 的 span_ms（占位排除
    已在其内部完成）。compare 不再自己重推一遍平行口径。
    """
    tools = tools_resp.get("tools") or []
    fails = sum(1 for t in tools if t.get("status") == "failed")
    turn_rows = usage_resp.get("turns") or []
    reported = [r.get("total_tokens") for r in turn_rows
                if r.get("status") == "reported" and r.get("total_tokens") is not None]
    span_ms = timing_resp.get("span_ms")
    return [
        {"name": "human_score", "value": human_score,
         "type": "categorical", "source": "human"},
        {"name": "turns", "value": turns, "type": "number", "source": "machine"},
        {"name": "tool_fail_rate",
         "value": round(fails / len(tools), 4) if tools else None,
         "type": "number", "source": "machine"},
        {"name": "tokens_reported", "value": sum(reported) if reported else None,
         "type": "number", "source": "machine"},
        {"name": "usage_missing_turns",
         "value": usage_resp.get("missing_turns") if turn_rows else None,
         "type": "number", "source": "machine"},
        {"name": "duration_s",
         "value": round(span_ms / 1000, 1) if isinstance(span_ms, (int, float)) and span_ms > 0 else None,
         "type": "number", "source": "machine"},
    ]
```

`fetch_scores` 改为：

```python
    def fetch_scores(run):
        base_path = "/api/sessions"
        out = {}
        for task_id, sid in _latest_by_task(run["assignments"]).items():
            usage = get_json(base, f"{base_path}/{sid}/usage")
            tools = get_json(base, f"{base_path}/{sid}/tools")
            timing = get_json(base, f"{base_path}/{sid}/timing")
            proj = get_json(base, f"{base_path}/{sid}")
            score_events = proj.get("scores") or []
            human = score_events[-1]["value"] if score_events else None
            out[task_id] = (sid, collect_task_score(
                usage, tools, timing, human, proj.get("turns")))
        return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_regression tests.test_cli_read -v`
Expected: PASS

- [ ] **Step 5: 手工冒烟（可选但推荐）**

若有本地账本：`make serve` 后 `python3 -m ata compare <run_a> <run_b>`，确认表格正常输出、miss/n/a 语义不变。没有 run 数据则跳过，Task 6 的端到端测试已覆盖形状。

- [ ] **Step 6: 全量回归 + 提交**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

```bash
git add ata/cli.py tests/test_regression.py
git commit -m "refactor(cli): compare 改吃便捷层端点，消灭平行口径推导"
```

---

## Phase 5 · 绞杀者收尾（评审候选 3）

### Task 9: 功能 parity 清点——React 版接管剩余视图的缺口确认

**Files:**
- Read-only: `web/js/board.js`、`web/js/app.js`、`webapp/src/components/board/*`、`webapp/src/App.tsx`
- Create: `docs/features/2026-08-26-strangler-parity-checklist.md`

这一步不是写代码，是产出一份可勾选的 parity 清单，供 Task 10 删除前核对。React 版 App.tsx 已有 board 视图入口（BoardView 已挂载），重点是逐个功能确认 React 版行为存在。

- [ ] **Step 1: 对照清点 legacy 视图能力**

逐个读 `web/js/board.js`（380 行）、`web/js/app.js` 的视图编排段，列出每个用户可见功能（标注 good/bad/partial、备注编辑、归组建组/改名、run 列表、会话改名、inspector 各 tab……），在清单里标注 React 版对应组件（BoardView/AnnoForm/AssignForm/TopBar/Inspector…）是否已覆盖。

- [ ] **Step 2: 写清单文档**

`docs/features/2026-08-26-strangler-parity-checklist.md`：每行一项功能、legacy 出处（文件:行）、React 版出处、状态（✅ 覆盖 / ⚠️ 有差距 / ❌ 缺失）。⚠️/❌ 项即为 Task 10 前必须补齐的缺口；若全部 ✅ 可直接进入 Task 10。

- [ ] **Step 3: 补齐发现的差距**

对每个 ⚠️/❌ 项单独小提交（遵循仓库既有迁移模式：组件 + vitest 用例）。此项范围取决于清点结果，执行时按清单驱动；全部补齐后才进入 Task 10。

- [ ] **Step 4: 提交清单与补齐**

```bash
git add docs/features/2026-08-26-strangler-parity-checklist.md webapp/src
git commit -m "docs(webapp): 绞杀者收尾 parity 清点；补齐 React 版缺口（如有）"
```

---

### Task 10: 删除 legacy 前端 web/js + 切默认服务路径

**Files:**
- Delete: `web/js/`（12 个文件约 2400 行）、`web/index.html`、`web/style.css`、`web/vendor/`
- Keep: `web/_miniharness.html`、`web/_revharness.html`、`web/_selharness.html`（测试 harness，暂留）
- Modify: `scripts/serve-dev.sh:20`（WEB 变量去掉 ATA_WEB 回切开关）
- Modify: `tests/test_accept.py:65-71`（legacy 断言段）
- Modify: `README.md`（如有提及 web/js 的段落）

**Interfaces:**
- Consumes: Task 9 的 parity 清单全 ✅。
- Produces: `web/dist` 成为唯一前端；`ATA_WEB` 环境变量退役。

- [ ] **Step 1: 更新 test_accept.py 的 UI 断言**

`tests/test_accept.py` 65-71 行的 legacy 断言段替换为：

```python
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r:
                    html = r.read().decode()
                self.assertIn("<!doctype html>", html.lower())
                # React 版（webapp build 产物）是唯一前端；静态分支伺服 dist 产物
                self.assertIn("/assets/", html)
```

- [ ] **Step 2: 确认 web/dist 存在且新鲜**

Run: `cd webapp && npm run build`
Expected: 构建成功，`web/dist/index.html` 引用 `/assets/*.js|css`

- [ ] **Step 3: 跑验收测试确认新断言过**

Run: `python3 -m unittest tests.test_accept -v`
Expected: PASS（serve-dev.sh 默认已是 web/dist，test_accept 用 Path("web") 作 webroot——注意 test_accept 的 `make_server(led, Path("web"), ...)` 需要改成 `Path("web/dist")` 才能让 `/` 命中 dist/index.html；一并修改）

- [ ] **Step 4: 删除 legacy 文件**

```bash
git rm -r web/js web/index.html web/style.css web/vendor
```

- [ ] **Step 5: serve-dev.sh 去掉回切开关**

`scripts/serve-dev.sh` 18-20 行改为：

```bash
# React 版（webapp build 产物）是唯一前端。
WEB="web/dist"
```

- [ ] **Step 6: 全量回归 + 手工冒烟**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

手工冒烟：`make serve`，浏览器打开 8787，确认首页/会话页/标注板三大视图正常。

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "chore(web): 删除 legacy 前端 web/js，web/dist 成为唯一前端（绞杀者收尾）"
```

---

## Self-Review 结论

- **Spec 覆盖**：候选 1→Task 2；候选 2→Task 5/6/7；候选 3→Task 9/10；候选 4→Task 3/4；候选 5→Task 1；候选 6→Task 8。全部有对应任务。
- **排序依据**：Task 1（信封工厂）先行是因为 Task 2 的 droid 清理要复用它；Task 3/4（fold）在 Phase 2 因为它与 plugins 解耦、可并行于 Phase 1 之后独立做；Task 5/6 是正确性修复（stale panel）优先于清理；Task 8 依赖便捷层口径稳定（Task 5 之后更稳但不强依赖）；Task 9/10 放最后因为删除是终点动作。
- **类型一致性**：`envelope` 的参数名 `type_` 在实现中避让关键字，调用方一律关键字传参（`"session.scored"` 位置传参对应第四个位置参数 `type_`）——已核对 Task 1 三处调用均为位置传参至第四参，一致。`fold_session_meta` 的 existing 键集（title/renamed/turns/last_ts/first_ts/parent_session_id）在 Task 3 ledger 接入段与 Task 4 投影消费段一致。`useSummary` 返回 `{data, reload}`，TimeBadge/UsagePanel 只消费 data，useSession 只调 nudgeSummaries——一致。
- **已知风险**：① Task 2 是大面机械替换，靠 28 个存量测试文件兜底，若个别断言锁定了旧字面量（如 duration_ms 数值来源），按「行为不变」原则修测试写法而非改断言值。② Task 3 fold 对 opened-parent 的 None 保护是行为微调（原实现会无条件覆盖为 None），计划已注明按新行为更新断言。③ Task 10 的 test_accept webroot 改动容易漏，已在 Step 3 显式标出。
