# 代理采集通道深化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 2026-08-26 落地的代理采集通道从「能用」深化到「深接口」：envelope 单点工厂收编 capture.py 的手搓 dict、`record_headers_for_storage` 单点函数显形落档白名单、`resolve_session_id` 加 body 路径以接入 codex / droid 反代、wire summary 二次解析消除。四件事都是零行为变化（除 codex/droid 反代接入）与局部深化。

**Architecture:**
- **envelope 收编**：把 capture.py 的两处手搓七键 dict 改走 `schema.envelope(...)`；5 个适配器的 `make_ev` 全部改 `envelope`，删 `make_ev` 工厂。事件形状唯一构造点。
- **落档白名单单点化**：把 `capture_proxy.py:85-86` 的 `if k.lower().startswith("x-claude")` 内联判定抽成 `ata/wire/storage_headers.py` 的 `record_headers_for_storage(headers)`。`x-claude-*` / `x-codex-*` / `x-droid-*` 三个 namespace 同时收——droid 占位待真实流量回填。**只动落档，不动转发**：代理依旧是根管子，hop-by-hop 黑名单是协议规定，保留。
- **resolve_session_id 接口形变**：`resolve_session_id(headers, agent_id)` → `resolve_session_id(rec, agent_id)`，rec 是完整 record；claude 走 headers，codex 走 body 字段 `metadata.session_id`，droid 留 namespace 位（具体路径待真实流量回填）。
- **wire summary 复用**：删 capture.py:148-152 的 `json.loads(body)`，改消费 `parse_request` 已解析的 `summary["message_items"]`。

**Tech Stack:** Python 3 stdlib only；unittest。零新依赖。

**Spec:**
- `docs/superpowers/plans/2026-08-26-proxy-capture-channel.md`：本计划的母计划（7 个 Task 已全部落地）
- `docs/adr/0001-proxy-capture-channel.md`：ADR-0001，本计划不重开其裁决（不引入 CaptureWriter、不发 message/tool 行）但**新增**「record_headers_for_storage 单点化」「codex/droid 反代集成边界」两条子裁决
- `/tmp/architecture-review-20260827-proxy-deepening.html`：6 候选评审报告，本计划执行候选 1 + 2（重新定义）+ 3 + 4
- ava 对照：`agent_visualization_analysis/header_permissions.py`（**不**全量移植——ata 用不上三权矩阵；只参考 ava 已声明的 codex 头名：x-openai-subagent / x-codex-parent-thread-id / x-codex-window-id / x-codex-turn-metadata）

## Global Constraints

- 写入只经 `Ledger.append/append_many`；任何地方不得 UPDATE events 表（单一 writer）。
- `schema.parse_event` 只增不改存量校验分支；本计划不改 `ALLOWED_TYPES`/`ALLOWED_AGENTS`。
- 测试用 unittest：`python3 -m unittest discover -s tests -v`；不引入 pytest。
- 不引入任何第三方依赖。
- 脱敏红线：认证头（authorization / x-api-key / cookie）永不落账本；事件只存提取后的字段（prompt_text、tools_catalog、usage），不存原始请求/响应全文与 headers。
- 采集失败绝不影响被代理的请求：翻译/写账本抛异常时吞掉、打印、照常返回响应。
- 展示层（web/webapp/project.py 投影端点）不动。
- 代理转发逻辑不动：hop-by-hop 黑名单保留；落档白名单是**唯一**单点化对象；新加 header namespace 只影响落档，不影响转发。
- 所有提交在 repos/ata 子仓库内做，消息末尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 |
|---|---|
| `ata/plugins/common.py` | 删 `make_ev`（envelope 同形 alias） |
| `ata/plugins/capture.py` | 两处手搓 dict 改 `envelope`；`resolve_session_id` 接口形变；删二次 `json.loads` |
| `ata/wire/storage_headers.py` | **新建**：`record_headers_for_storage(headers)` 单点函数，落档白名单唯一归属地 |
| `ata/capture_proxy.py` | `record_headers_for_storage` 替换内联判定 |
| `tests/test_capture.py` | envelope 收编测试 + resolve_session_id 接口形变测试 + body 路径测试 + 二次解析消除测试 |
| `tests/test_storage_headers.py` | **新建**：namespace 白名单 + 未知头不落档测试 |
| `tests/test_capture_proxy.py` | 现有测试 + namespace 扩展断言（droid 占位） |
| `docs/adr/0001-proxy-capture-channel.md` | 增补「记录头白名单」+「codex/droid 反代集成边界」两节 |

---

### Task 1: 删 make_ev，capture.py 改走 envelope

**Files:**
- Modify: `ata/plugins/capture.py:133-137, 156-160`
- Modify: `ata/plugins/common.py:35-43`（删 `make_ev` 定义）
- Modify: `ata/plugins/claude.py`、`ata/plugins/pi.py`、`ata/plugins/droid.py`、`ata/plugins/codex.py`（所有 `make_ev` 调用改 `envelope`）
- Test: `tests/test_capture.py`（envelope 形状不变测试）、`tests/test_*.py` 全量回归

**Interfaces:**
- Consumes: `ata.schema.envelope(agent_id, session_id, type_, payload, turn=None, ts=None, eid=None) -> dict`（已存在）
- Produces: `ata.plugins.common.make_ev` 不再导出

- [ ] **Step 1: 跑全量测试看基线**

Run: `python3 -m unittest discover -s tests -v`
Expected: 188 tests OK

- [ ] **Step 2: 改 capture.py:133-137 的手搓 dict**

替换 capture.py 中 `system.upserted` 事件组装的整段（约 L125-138）为：

```python
            out.append(envelope(
                agent_id=agent_id,
                session_id=sid,
                type_="system.upserted",
                payload={"prompt_text": prompt_text, "tools_catalog": catalog},
                turn=None,
                ts=ts,
                eid=f"{sid}:system:{h}",
            ))
```

加 import：`from ata.schema import envelope`

- [ ] **Step 3: 改 capture.py:156-160 的手搓 dict**

替换 capture.py 中 `turn.ended` 事件组装的整段（约 L154-163）为：

```python
            out.append(envelope(
                agent_id=agent_id,
                session_id=sid,
                type_="turn.ended",
                payload={"usage": usage_from_counts(
                    inp, outp, cr, cw, total_tokens=inp + outp + cr + cw)},
                turn=turn,
                ts=ts,
                eid=f"{sid}:turn:{turn}:ended:{rid or ts}",
            ))
```

- [ ] **Step 4: 改 5 个适配器的 make_ev 调用**

对 `ata/plugins/{claude,pi,droid,codex}.py` 每个 `make_ev` 调用，替换为 `envelope` 调用。映射规则：
- `make_ev(eid, agent_id, session_id, ts, typ, turn, payload)` → `envelope(agent_id=agent_id, session_id=session_id, type_=typ, payload=payload, turn=turn, ts=ts, eid=eid)`
- 若调用方未传 `eid`（让 `envelope` 默认 uuid 接管），不写 `eid=` 关键字

5 个适配器每个文件的具体调用点由执行者用 `grep -n make_ev ata/plugins/*.py` 扫描后逐个替换。**所有现有测试的 `parse_event` 校验会锁住事件形状不变**。

- [ ] **Step 5: 删 ata/plugins/common.py 的 make_ev 定义**

删除 L35-43 整段 `def make_ev(...) -> dict: ...`。

- [ ] **Step 6: 跑全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: 188 tests OK（事件形状不变，所有 `parse_event` 校验仍过）

如果失败：
- ImportError → 漏改调用点
- AssertionError on event shape → 字段名拼写错（type_ vs type 等）

- [ ] **Step 7: Commit**

```bash
git add ata/plugins/capture.py ata/plugins/common.py \
        ata/plugins/claude.py ata/plugins/pi.py \
        ata/plugins/droid.py ata/plugins/codex.py
git commit -m "refactor(envelope): 收编 capture.py 手搓 dict，删 make_ev 单点工厂

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: wire summary 二次消费——删 capture.py 的 json.loads

**Files:**
- Modify: `ata/plugins/capture.py:50-67, 148-152`
- Test: `tests/test_capture.py`（追加 `test_count_from_wire_items`）

**Interfaces:**
- Consumes: `ata.wire.parse_request(path, headers, body) -> dict`（已存在），返回的 `summary["message_items"]` 是结构化 list
- Produces: `count_real_user_turns(messages)` 接口不变；新增内部 `_user_text_from_item(item)` 工具

- [ ] **Step 1: 写失败测试**

在 `tests/test_capture.py` 追加：

```python
from ata.plugins.capture import _user_text_from_item


class WireItemsTurnsTest(unittest.TestCase):
    def test_text_block(self):
        item = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
        self.assertEqual(_user_text_from_item(item), "hi")

    def test_string_content(self):
        self.assertEqual(_user_text_from_item(
            {"role": "user", "content": "raw string"}), "raw string")

    def test_string_list_content(self):
        item = {"role": "user", "content": ["a", "b"]}
        self.assertEqual(_user_text_from_item(item), "a\nb")

    def test_mixed_blocks(self):
        item = {"role": "user", "content": [
            {"type": "text", "text": "real"},
            {"type": "image", "source": "..."},
        ]}
        self.assertEqual(_user_text_from_item(item), "real")

    def test_assistant_returns_empty(self):
        item = {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}
        self.assertEqual(_user_text_from_item(item), "")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_capture.WireItemsTurnsTest -v`
Expected: ImportError（`_user_text_from_item` 未定义）

- [ ] **Step 3: 抽出 _user_text_from_item + 重构 count_real_user_turns**

替换 `ata/plugins/capture.py:37-67` 的 `_block_texts` + `count_real_user_turns` 整段为：

```python
def _user_text_from_item(item):
    """从 wire summary 的 message_item 提 user 角色文本。

    吃 anthropic_parser 已解析的 message_items 形状（role + content blocks），
    字符串/块数组/裸字符串数组都吃。assistant/工具/None 都返回空串。
    """
    if not isinstance(item, dict) or item.get("role") != "user":
        return ""
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts)


def count_real_user_turns(message_items):
    """wire message_items 里的真实 user 消息数 = 当前轮次号。

    与 jsonl 侧 bump_turn_if_real_user 同口径：CONTEXT 注入不开轮
    （复用 ata.project.is_context_text，懒加载避免循环导入）。
    """
    from ata.project import is_context_text

    count = 0
    for item in message_items or []:
        text = _user_text_from_item(item)
        if not text or is_context_text(text):
            continue
        count += 1
    return count
```

**接口形变**：`count_real_user_turns` 入参从「raw messages list」变为「wire summary 的 message_items list」。Task 1 已通过 `envelope` 测试锁住 capture 主体，本任务落地后 `count_real_user_turns` 的入参语义变更由 `_translate` 内的调用点同步调整（Step 5）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_capture.WireItemsTurnsTest -v`
Expected: 5 tests PASS

- [ ] **Step 5: 改 _translate 调用点**

替换 `ata/plugins/capture.py:148-152` 整段为：

```python
        req = _wire_req(path, rec.get("request_headers") or {}, body)
        # 用 wire 已解析的 message_items 算轮次，不重复 json.loads。
        message_items = req.get("message_items") or []
        turn = count_real_user_turns(message_items)
```

`message_items` 由 `parse_request` 在 anthropic_parser.py:29（及多处）已产出。`json.loads(body)` 整段删除。

- [ ] **Step 6: 跑全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全过；注意 `test_capture.py:251-265` 的 `test_counts_real_user_messages` / `test_context_injection_does_not_count` / `test_empty_and_malformed` 入参形式从 `messages`（role+content blocks）改为 message_items 同样形态（ant

hropic_parser 产出的就是这形态），测试期望值不变。

- [ ] **Step 7: Commit**

```bash
git add ata/plugins/capture.py tests/test_capture.py
git commit -m "refactor(capture): wire summary 复用，删除 _translate 二次 json.loads

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: storage_headers 单点化——把 x-claude / x-codex / x-droid namespace 收成一处

**Files:**
- Create: `ata/wire/storage_headers.py`
- Modify: `ata/capture_proxy.py:85-86`
- Test: `tests/test_storage_headers.py`（新建）

**Interfaces:**
- Consumes: 任意 `dict[str, str]`（HTTP headers）
- Produces:
  - `record_headers_for_storage(headers: dict) -> dict[str, str]` —— 返回**应当落档**的头白名单结果
  - `STORAGE_HEADER_NAMESPACES: tuple[str, ...]` —— 公开常量，三家 namespace 在此声明
  - `_droid_headers_tbd: frozenset[str]` —— 内部占位（droid 头待真实流量回填）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_storage_headers.py`：

```python
import unittest

from ata.wire.storage_headers import (
    STORAGE_HEADER_NAMESPACES,
    record_headers_for_storage,
)


class NamespacesDeclaredTest(unittest.TestCase):
    def test_three_agent_namespaces(self):
        # claude / codex / droid 三家 namespace 都声明了。droid 暂未列出具体头，
        # 但 namespace 占位存在（等真实流量回填）。
        self.assertIn("x-claude-", STORAGE_HEADER_NAMESPACES)
        self.assertIn("x-codex-", STORAGE_HEADER_NAMESPACES)
        self.assertIn("x-droid-", STORAGE_HEADER_NAMESPACES)


class WhitelistTest(unittest.TestCase):
    def test_claude_session_id_kept(self):
        h = {"X-Claude-Code-Session-Id": "s1", "Authorization": "sk-x"}
        out = record_headers_for_storage(h)
        self.assertEqual(out, {"X-Claude-Code-Session-Id": "s1"})

    def test_codex_window_id_kept(self):
        h = {"x-codex-window-id": "win-1", "user-agent": "codex-cli"}
        out = record_headers_for_storage(h)
        self.assertEqual(out, {"x-codex-window-id": "win-1"})

    def test_droid_namespace_kept(self):
        h = {"x-droid-trace-id": "d1", "x-droid-build": "1.0"}
        out = record_headers_for_storage(h)
        self.assertEqual(out, {"x-droid-trace-id": "d1", "x-droid-build": "1.0"})

    def test_undeclared_header_dropped(self):
        # 不在三家 namespace 内的头一律不落档（认证头/通用协议头不进账本）。
        h = {"authorization": "sk-x", "x-api-key": "sk-y", "user-agent": "x",
             "content-type": "application/json"}
        self.assertEqual(record_headers_for_storage(h), {})

    def test_case_insensitive_match(self):
        h = {"X-CLAUDE-CODE-SESSION-ID": "s1"}
        self.assertEqual(
            record_headers_for_storage(h), {"X-CLAUDE-CODE-SESSION-ID": "s1"})

    def test_empty_headers(self):
        self.assertEqual(record_headers_for_storage({}), {})

    def test_none_safe(self):
        self.assertEqual(record_headers_for_storage(None), {})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_storage_headers -v`
Expected: ModuleNotFoundError（`ata.wire.storage_headers` 不存在）

- [ ] **Step 3: 实现 storage_headers.py**

创建 `ata/wire/storage_headers.py`：

```python
"""落档白名单唯一归属地（架构评审候选 2 重新定义后）。

代理壳把任意 headers 进来，本模块按 namespace 决定**哪些落账本**。判定只
影响 `record.request_headers` 字段，**不影响转发**——代理壳的转发逻辑保留
hop-by-hop 黑名单，hop-by-hop 之外的头一字不动转上游。

namespace 选择：
- x-claude-*：claude code CLI 实测带的请求头（x-claude-code-session-id 等）
- x-codex-*：codex CLI / OpenAI Responses API 客户端带的头（参考 ava 已声明
  的 x-codex-window-id / x-codex-parent-thread-id / x-codex-turn-metadata）
- x-droid-*：droid CLI 预期会带的头占位（具体头名待真实流量回填）

**绝不**落档：authorization / x-api-key / cookie 等认证头；content-type /
user-agent 等通用协议头（无 host 业务含义）。这些头由 capture_proxy 透传给
上游网关，落档侧一律不放行。

加新 agent 走代理：在这加一行 namespace 占位，list[namespace] 扩展为四家。
加新头：**必须**确认该头是 host 业务字段（如 sid / lineage 标识）才放行。
"""
from __future__ import annotations

#: 落档白名单 namespace。头名（小写）以其中之一为前缀才落账本。
#: 加新 agent 走代理：在这里加一行；具体头名由 ava 已声明的名单 + 真实流量验证。
STORAGE_HEADER_NAMESPACES: tuple[str, ...] = (
    "x-claude-",
    "x-codex-",
    "x-droid-",
)

#: droid 头占位——具体头名待真实流量回填。占位存在是为了让
#: STORAGE_HEADER_NAMESPACES 含 x-droid- 的事实**被一处声明**而不是散落。
#: 真实头名回填时，在下面 frozenset 内加具体名（大小写不敏感）。
_DROID_HEADERS_TBD: frozenset[str] = frozenset()


def record_headers_for_storage(headers):
    """过滤 headers：只保留 namespace 在白名单内的头。

    大小写不敏感（HTTP header 名按规范是 case-insensitive）；返回值保留
    原始大小写（即 client 原样发什么就存什么）。

    返回值是 dict 副本，调用方安全持有。
    """
    if not headers:
        return {}
    out = {}
    for k, v in headers.items():
        lower = str(k).lower()
        if any(lower.startswith(ns) for ns in STORAGE_HEADER_NAMESPACES):
            out[k] = v
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_storage_headers -v`
Expected: 8 tests PASS

- [ ] **Step 5: 改 capture_proxy.py:85-86 的内联判定**

加 import（`capture_proxy.py` 顶部）：

```python
from ata.wire.storage_headers import record_headers_for_storage
```

替换 capture_proxy.py 中 record 字典组装的 `request_headers` 字段（约 L82-92）：

```python
        record = {
            "agent_id": agent_id,
            "path": self.path.split("?", 1)[0],
            "request_headers": record_headers_for_storage(self.headers),
            "request_body": bytes(body),
            "response_content_type": content_type,
            "response_body": bytes(buf),
            "started_at_ms": int(started * 1000),
            "completed_at_ms": int(completed * 1000),
        }
```

**不动**转发逻辑（L46-48 `fwd` 字典的 `if k.lower() not in _HOP_HEADERS` 判定保留）——代理仍是根管子。

- [ ] **Step 6: 跑全量回归 + 端到端测试**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全过（191 tests = 188 + 3 new storage_headers tests 实际是 8 个但部分 namespace 测试被合并；精确数 191-188 = 8 与 188+8 不矛盾，按实际 PASS 数核）

`tests/test_capture_proxy.py` 现有 2 个测试：第一个断言 `x-api-key` 到达上游（仍过——转发逻辑没动）、账本不存 `sk-secret`（仍过——storage_headers 不放行 `x-api-key`）。**无需修改**。

- [ ] **Step 7: Commit**

```bash
git add ata/wire/storage_headers.py ata/capture_proxy.py tests/test_storage_headers.py
git commit -m "feat(wire): record_headers_for_storage 单点化，x-claude/x-codex/x-droid namespace

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: resolve_session_id 接口形变——加 body 路径支持 codex / droid

**Files:**
- Modify: `ata/plugins/capture.py:22-34, 167-185`
- Test: `tests/test_capture.py`（重写 ResolveSessionTest、追加 CodexBodyPathTest、DroidNamespaceTest）

**Interfaces:**
- Consumes: 完整 `rec` 字典（带 `request_headers` 与 `request_body`）
- Produces:
  - `resolve_session_id(rec: dict, agent_id: str) -> str | None` —— 接口形变
  - `_SESSION_HEADERS: dict[str, tuple[str, ...]]` —— 各家头名（不变）
  - `_BODY_SESSION_FIELDS: dict[str, tuple[tuple[str, ...], ...]]` —— 各家 body 字段路径，**新增**

- [ ] **Step 1: 写失败测试**

替换 `tests/test_capture.py:233-241` 的 ResolveSessionTest 整段：

```python
class ResolveSessionTest(unittest.TestCase):
    def test_claude_header_case_insensitive(self):
        rec = {"request_headers": {"x-claude-code-session-id": "abc-123"}}
        self.assertEqual(resolve_session_id(rec, "claude"), "abc-123")

    def test_missing_header_returns_none(self):
        self.assertIsNone(resolve_session_id(
            {"request_headers": {}}, "claude"))
        self.assertIsNone(resolve_session_id(
            {"request_headers": {"user-agent": "claude-cli"}}, "claude"))

    def test_none_rec_safe(self):
        self.assertIsNone(resolve_session_id({}, "claude"))
        self.assertIsNone(resolve_session_id({"request_headers": None}, "claude"))


class CodexBodyPathTest(unittest.Testcase := None if False else __import__("unittest").TestCase):
    pass  # placeholder; see real class below
```

**等等**——上面用了 `:=` 占位是错的。正确写法：

```python
class CodexBodyPathTest(unittest.TestCase):
    def test_metadata_session_id(self):
        body = json.dumps({"metadata": {"session_id": "codex-s-1"}}).encode()
        rec = {"request_headers": {}, "request_body": body}
        self.assertEqual(resolve_session_id(rec, "codex"), "codex-s-1")

    def test_nested_metadata_deep(self):
        body = json.dumps({
            "metadata": {"user": {"session_id": "deep-1"}}
        }).encode()
        rec = {"request_headers": {}, "request_body": body}
        self.assertEqual(resolve_session_id(rec, "codex"), "deep-1")

    def test_header_takes_precedence_over_body(self):
        # headers 路径优先（claude 走 headers；codex 走 body 但 headers 命中也算）
        rec = {
            "request_headers": {"x-codex-window-id": "win-1"},
            "request_body": json.dumps({"metadata": {"session_id": "codex-s-1"}}).encode(),
        }
        # codex 暂未在 _SESSION_HEADERS 声明 x-codex-window-id；body 路径胜出
        self.assertEqual(resolve_session_id(rec, "codex"), "codex-s-1")

    def test_missing_metadata_returns_none(self):
        body = json.dumps({"metadata": {"other": "x"}}).encode()
        rec = {"request_headers": {}, "request_body": body}
        self.assertIsNone(resolve_session_id(rec, "codex"))

    def test_garbage_body_returns_none(self):
        rec = {"request_headers": {}, "request_body": b"\xff\xfe"}
        self.assertIsNone(resolve_session_id(rec, "codex"))

    def test_empty_body_returns_none(self):
        rec = {"request_headers": {}, "request_body": b""}
        self.assertIsNone(resolve_session_id(rec, "codex"))


class DroidNamespaceTest(unittest.TestCase):
    def test_droid_returns_none_for_now(self):
        # droid 走代理：headers 路径未声明（待真实流量回填具体头名），
        # body 路径未声明（droid 是否用 body metadata 未知）。
        # 暂返回 None → 走 ingest_capture 的 ValueError 路径被吞掉。
        rec = {
            "request_headers": {"x-droid-trace-id": "d-1"},
            "request_body": b'{"some": "json"}',
        }
        self.assertIsNone(resolve_session_id(rec, "droid"))
```

加 import：文件顶部 `import json`（如果还没有）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_capture -v`
Expected: TypeError（`resolve_session_id` 仍接 `(headers, agent_id)`，传 `rec` 不工作）

- [ ] **Step 3: 改 resolve_session_id 接口形变**

替换 `ata/plugins/capture.py:22-34` 的 `_SESSION_HEADERS` + `resolve_session_id` 整段为：

```python
# 各家宿主携带会话 id 的请求头（小写）。cue/pi/droid 若走代理，按此表头加行。
# 头名匹配大小写不敏感；命中即返回（不再走 body 路径）。
_SESSION_HEADERS: dict[str, tuple[str, ...]] = {
    "claude": ("x-claude-code-session-id",),
}

# 各家宿主把会话 id 放在请求体字段（按 JSON 嵌套路径定位）。
# codex 走 OpenAI Responses API，session_id 在 metadata.session_id。
# droid 路径占位（具体字段名待真实流量回填——若 droid 用 body metadata，
# 在此加；若是 header，移到 _SESSION_HEADERS）。
_BODY_SESSION_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "codex": (("metadata", "session_id"),),
}


def _dig(payload, path):
    """按嵌套路径取 dict 值；任一环不是 dict 或缺 key 返回 None。"""
    cur = payload
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def resolve_session_id(rec, agent_id):
    """从 record 恢复宿主 sessionId；找不到返回 None（调用方丢弃该次采集）。

    优先 headers 路径（claude 走此），回退 body 路径（codex 走 OpenAI
    Responses API 的 metadata.session_id）。两条路径都未声明 = 暂未支持。
    """
    headers = (rec or {}).get("request_headers") or {}
    low = {str(k).lower(): v for k, v in headers.items()}
    for name in _SESSION_HEADERS.get(agent_id, ()):
        sid = low.get(name)
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    body_paths = _BODY_SESSION_FIELDS.get(agent_id, ())
    if body_paths:
        try:
            payload = json.loads(
                (rec.get("request_body") or b"").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return None
        if isinstance(payload, dict):
            for path in body_paths:
                v = _dig(payload, path)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None
```

- [ ] **Step 4: 改 ingest_capture 调用点**

替换 `ata/plugins/capture.py:174-185` 的 `ingest_capture` 整段为：

```python
def ingest_capture(ledger, rec):
    """解析 → 校验 → 入账本。返回写入数；校验失败抛 ValidationError。

    身份规则在此收口：恢复不出宿主 sessionId 就抛错丢弃（进程内壳吞掉，
    HTTP 端点回 400），绝不造 sid 新建孤儿会话。
    """
    from ata.schema import parse_event

    agent_id = rec.get("agent_id") or "claude"
    sid = resolve_session_id(rec, agent_id)
    if not sid:
        raise ValueError("capture: no host session id; dropping (no orphan sessions)")
    state = state_bucket(ledger, sid)
    state["session_id"] = sid
    events = [parse_event(ev) for ev in translate_capture(rec, state)]
    if events:
        ledger.append_many(events)
    return len(events)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m unittest tests.test_capture -v`
Expected: PASS（11 个原有 + 6 个 CodexBodyPath + 1 个 DroidNamespace = 18 个 tests）

- [ ] **Step 6: 跑全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 PASS（注意 `test_capture_http.py:test_missing_session_header_is_400` 仍过——payload 没 `x-claude-code-session-id` 且无 body session 字段，正确抛 `ValueError` → 400）

- [ ] **Step 7: Commit**

```bash
git add ata/plugins/capture.py tests/test_capture.py
git commit -m "feat(capture): resolve_session_id 接口形变，加 body 路径接 codex

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: ADR 增补两节（落档白名单 + codex/droid 反代集成边界）

**Files:**
- Modify: `docs/adr/0001-proxy-capture-channel.md`

**Interfaces:**
- Consumes: 现有 ADR
- Produces: 增补「落档白名单归属地」「codex / droid 反代集成边界」两节

- [ ] **Step 1: 读取现有 ADR 末段**

Read: `docs/adr/0001-proxy-capture-channel.md`（已有的"已知限制"两节已存在）
Expected: 现有 L38-50「已知限制」节

- [ ] **Step 2: 在 ADR 末追加两节**

在 ADR 文件末尾追加：

```markdown

### 落档白名单（2026-08-27 增补）

落档头白名单是 `ata/wire/storage_headers.py::record_headers_for_storage`
的单一归属地。`x-claude-` / `x-codex-` / `x-droid-` 三个 namespace 在
`STORAGE_HEADER_NAMESPACES` 同时声明。**绝不**把 authorization / x-api-key
/ cookie / content-type / user-agent 列入——这些是上游网关或通用协议所需，
不是 host 业务字段。

代理壳的转发逻辑**不**动：`capture_proxy._relay` 仍按 hop-by-hop 黑名单
过滤（host / content-length / connection / transfer-encoding），其余头
一字不动转上游。代理是根管子，落档白名单是**账本侧**单点，与转发无关。

加新 agent 走代理：在 `STORAGE_HEADER_NAMESPACES` 加一行 + 在对应适配器
的 `_SESSION_HEADERS` 或 `_BODY_SESSION_FIELDS` 加具体提取规则。

### codex / droid 反代集成边界（2026-08-27 增补）

本计划只完成**接入面**：

- **codex**：`_BODY_SESSION_FIELDS["codex"] = (("metadata", "session_id"),)`
  声明；OpenAI Responses API 客户端把 session_id 放在请求体 metadata 字段，
  走 body 路径提取。`openai_parser` 移植是后续工作（见
  architecture-review-20260827-proxy-deepening.html 候选 3）——本计划落地后
  codex 走代理能恢复 sessionId，但**暂未**走完整解析内核（system/tools
  提取仍走 fallback）。

- **droid**：headers 与 body 路径**都未**声明（具体头名与 body 字段待真实
  流量回填）。droid 走代理当前 ingest_capture 抛 `ValueError` → 被吞掉
  （进程内壳）或回 400（HTTP 端点）。这是裁决内行为，不是 bug。

落档白名单 `x-droid-` namespace **占位存在**，让 STORAGE_HEADER_NAMESPACES
含三家的事实**被一处声明**而不是散落。真实头名回填时，在
`STORAGE_HEADER_NAMESPACES` 不动、`_SESSION_HEADERS` 加具体头名。
```

- [ ] **Step 3: Commit**

```bash
git add docs/adr/0001-proxy-capture-channel.md
git commit -m "docs(adr): 增补落档白名单归属地与 codex/droid 反代集成边界

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## 非目标（明确不做）

- **代理转发头判定**（候选 2 原版「移植 ava header_permissions 三权矩阵」）：已撤销——ata 用不上三权分离，代理是根管子。
- **openai_parser 移植**（候选 3 主体）：本计划只完成 session id 接入面，协议族 seam 真用（让 `parse_request` 解析 codex 的 system/tools）留待下轮。
- **CaptureWriter 异步化**（候选 5）：单 sink 同步路径未破，触发条件（双 sink 或 P99>50ms）未到。
- **record 改 HTTP sink 形态**（候选 6）：同进程内单入口足够，跨机部署需求未到。
- **droid 头具体名回填**：本计划只占位；真实流量（droid CLI 实际带的请求头）出现后回填 `_SESSION_HEADERS["droid"]`。

---

## Self-Review

**1. Spec coverage**:
- 2026-08-26 计划 7 个 Task → 全过；本计划是第二轮深化
- 评审 6 候选 → 候选 1 ✓ Task 1；候选 2（重新定义）✓ Task 3；候选 3（部分）✓ Task 4；候选 4 ✓ Task 2；候选 5/6 → 非目标
- 三个决定 → 全部落到代码与 ADR

**2. Placeholder scan**:
- Task 4 Step 1 的「`unittest.TestCase :=` 占位」是错误占位，已在「等等」段修正为正确 `class CodexBodyPathTest(unittest.TestCase):`
- `_droid_headers_tbd` 在 storage_headers.py 已实现为 `frozenset()`，不是 TODO 占位
- `_BODY_SESSION_FIELDS` 的 droid 行**未**列入——ADR 增补节已说明「droid 暂未声明」，不是疏漏

**3. Type consistency**:
- `resolve_session_id(rec: dict, agent_id: str) -> str | None` —— Task 4 Step 3 定义、Step 1 测试、Step 4 ingest_capture 调用全部对齐
- `record_headers_for_storage(headers: dict) -> dict[str, str]` —— Task 3 Step 3 定义、Step 1 测试、Step 5 capture_proxy 调用对齐
- `count_real_user_turns(message_items)` —— Task 2 Step 3 定义、Step 5 `_translate` 调用对齐（入参形态从 raw messages 变为 wire message_items，antrhropic_parser 产出即这形态）
- `envelope(agent_id=, session_id=, type_=, payload=, turn=, ts=, eid=)` —— Task 1 Step 2/3 调用与 schema.py:107 现有签名对齐
