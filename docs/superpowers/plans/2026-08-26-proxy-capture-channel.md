# 代理采集通道（proxy capture channel）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 ata 新增「代理采集」通道：一个转发代理截获 agent↔LLM 的 HTTP 流量，解析出账本里缺失的事实（SYSTEM 快照、tools 目录、每轮真实 usage），以规范事件走事件追加门并入同一 session——首个受益者是 claude（transcript 采不到 system prompt / tools 目录 / 每轮 usage）。

**Architecture:** 从 ava（repos/agent-visualization-analysis）移植「解析内核」（parser + protocol_facts + anthropic_parser，纯函数、零 IO），在 ata 重写薄转发壳（进程内线程，仿 tail 线程的启动方式）；新增适配器 `plugins/capture.py` 把 wire 解析摘要翻译成规范事件。展示层零改动：`system.upserted` 与 `turn.ended` 的投影消费已存在（`ata/project.py:192-227`、`_usage_turns`）。身份合并走写入时收敛：优先从请求头恢复宿主 sessionId 追加到同一 session，恢复不了就丢弃并计数，绝不新建孤儿会话。

**Tech Stack:** Python 3 stdlib only（http.client / http.server / threading / hashlib / json）；unittest。

**Spec:**
- 架构评审（2026-08-26 会话）：候选 1「只搬解析内核」+ 候选 2「会话身份合并」+ 候选 4「新壳不复制已知脆弱点」。候选 3（CaptureWriter 队列语义）与非目标见下。
- `docs/superpowers/specs/2026-08-15-ata-v1-canonical-event-kernel-design.md` L19/L214：HTTP 抓包是合法补充来源，「要求每次 HTTP 都有 usage 会逼出代理」即本计划；其 L240-247「非目标：反向代理 / 搬旧 AVA 代理」是 v1 范围裁决，本计划重开该裁决，Task 7 以 ADR 记录理由。

## Global Constraints

- 写入只经 `Ledger.append/append_many`；任何地方不得 UPDATE events 表（单一 writer）。
- `schema.parse_event` 只增不改存量校验分支；本计划不改 `ALLOWED_TYPES`/`ALLOWED_AGENTS`（所需事件类型全部已在词表内）。
- 测试用 unittest：`python3 -m unittest discover -s tests -v`；不引入 pytest。
- 不引入任何第三方依赖。
- 脱敏红线：认证头（authorization / x-api-key / cookie）永不落账本；事件只存提取后的字段（prompt_text、tools_catalog、usage），不存原始请求/响应全文与 headers。
- 采集失败绝不影响被代理的请求：翻译/写账本抛异常时吞掉、打印、照常返回响应。
- 展示层（web/webapp/project.py 投影端点）不动。
- 所有提交在 repos/ata 子仓库内做，消息末尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 |
|---|---|
| `ata/wire/__init__.py` | 导出 `parse_request` / `parse_response` |
| `ata/wire/parser.py` | 从 ava 移植：协议分发入口，异常自吞 |
| `ata/wire/protocol_facts.py` | 从 ava 移植：协议适配器注册表（seam 所在） |
| `ata/wire/anthropic_parser.py` | 从 ava 原样移植：Anthropic Messages 协议纯函数解析 |
| `ata/plugins/capture.py` | 新适配器：wire 摘要 → 规范事件；会话身份规则归属地 |
| `ata/capture_proxy.py` | 转发壳：ThreadingHTTPServer 截获流量、流式回传、组装 record |
| `ata/http.py` | 加 `POST /api/captures`（外部壳/测试用，仿 `/api/pi-hooks`） |
| `ata/__main__.py` | 加 `--proxy-port/--proxy-upstream/--proxy-agent` 启动代理线程 |
| `tests/test_wire_parse.py` | 移植内核的行为锁定（从 ava 测试改写） |
| `tests/test_capture.py` | 适配器单测（翻译逻辑全在此测） |
| `tests/test_capture_http.py` | `/api/captures` 端点测试 |
| `tests/test_capture_proxy.py` | 端到端：假上游 + 真代理线程 + 临时账本 |
| `docs/adr/0001-proxy-capture-channel.md` | 记录重开 v1 非目标裁决 |

---

### Task 1: 移植解析内核到 ata/wire/

**Files:**
- Create: `ata/wire/__init__.py`, `ata/wire/parser.py`, `ata/wire/protocol_facts.py`, `ata/wire/anthropic_parser.py`
- Modify: （无）
- Test: `tests/test_wire_parse.py`

**Interfaces:**
- Consumes: 无（自包含）。
- Produces: `ata.wire.parse_request(path: str, headers: dict, body: bytes) -> dict` 与 `ata.wire.parse_response(path: str, headers: dict, content_type: str, body: bytes) -> dict`。摘要 dict 含 `parser.family`（`"anthropic-messages"`）、请求侧 `system_prompts: list[str]`、`tool_items: list[{index,name,type,description,parameters}]`、`messages`、`message_items`；响应侧 `response_text`、`usage: dict`、`finish_reasons`。不抛异常（内部错误转 `{"error": ...}`）。

- [ ] **Step 1: 复制三个源文件**

从 ava 复制（保持函数体逐字不动，便于日后对照上游 diff）：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
mkdir -p ata/wire
cp ../agent-visualization-analysis/agent_visualization_analysis/anthropic_parser.py ata/wire/anthropic_parser.py
cp ../agent-visualization-analysis/agent_visualization_analysis/parser.py ata/wire/parser.py
cp ../agent-visualization-analysis/agent_visualization_analysis/protocol_facts.py ata/wire/protocol_facts.py
```

然后把两个文件的 import 改成包内相对导入：

- `ata/wire/parser.py` 第 3 行：`from agent_visualization_analysis.protocol_facts import ...` → `from .protocol_facts import PROTOCOL_FACTS_VERSION, select`
- `ata/wire/protocol_facts.py` 第 45-55 行：`from .anthropic_parser import ...` 保持不变（本来就是相对导入，确认即可）
- 删除 `protocol_facts.py` 里引用不存在测试的 docstring 段落（`tests/test_layering.py`、`tests/test_scope_expansion.py` 相关两段），其余注释保留。

创建 `ata/wire/__init__.py`：

```python
"""wire 协议解析内核（自 ava 移植，候选 1）。

parse_request/parse_response 是深接口：两个纯函数吸收 Anthropic/OpenAI
两族 wire 协议差异，异常自吞、零 IO。新增协议 = 在 protocol_facts 注册
一个 adapter；调用方不感知族数。
"""
from .parser import parse_request, parse_response

__all__ = ["parse_request", "parse_response"]
```

注意：本批只搬 Anthropic 族（claude 首个受益者）。`protocol_facts.py` 顶部对 `openai_parser` 的 import 要删掉，`_OpenAICompatible` 类改为不依赖它的最小 fallback：

```python
class _OpenAICompatible:
    """未注册协议的默认 reader：只标注 family，不做结构化解析。

    OpenAI 族（codex 可用）第二批移植时恢复为 ava 原版（接 openai_parser）；
    现在没有消费者，搬 1095 行进来违反 YAGNI。
    """

    family = "openai-compatible"
    provider = "openai"
    api_families = ()

    def handles(self, path: str) -> bool:
        return False

    def parse_request(self, path, headers, body):
        return {"api_family": "unknown", "json_valid": False}

    def parse_response(self, path, headers, content_type, body):
        return {"api_family": "unknown", "json_valid": False, "response_text": ""}
```

同时删除 `provider_for_api_family` 里对 `OPENAI_API_FAMILIES` 的引用路径不受影响（它遍历 adapter 的 `api_families` 元组，空元组自然不命中），但文件顶部 import 行 `API_FAMILIES as OPENAI_API_FAMILIES, parse_openai_request, parse_openai_response` 必须整体移除。

- [ ] **Step 2: 写失败测试**

创建 `tests/test_wire_parse.py`：

```python
import unittest

from ata.wire import parse_request, parse_response


REQ = (
    b'{"model":"claude-sonnet-5","stream":false,'
    b'"system":[{"type":"text","text":"You are ATA."}],'
    b'"tools":[{"name":"Read","description":"read a file",'
    b'"input_schema":{"type":"object"}}],'
    b'"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}'
)

RESP = (
    b'{"id":"msg_01","type":"message","role":"assistant",'
    b'"content":[{"type":"text","text":"hello"}],"stop_reason":"end_turn",'
    b'"usage":{"input_tokens":10,"output_tokens":5,'
    b'"cache_read_input_tokens":2,"cache_creation_input_tokens":1}}'
)


class WireParseTest(unittest.TestCase):
    def test_request_path_dispatch(self):
        s = parse_request("/v1/messages", {}, REQ)
        self.assertEqual(s["parser"]["family"], "anthropic-messages")
        self.assertEqual(s["parser"]["version"], 2)
        self.assertTrue(s["json_valid"])
        self.assertEqual(s["system_prompts"], ["You are ATA."])
        self.assertEqual([t["name"] for t in s["tool_items"]], ["Read"])

    def test_non_messages_path_falls_back(self):
        s = parse_request("/v1/unknown", {}, REQ)
        self.assertEqual(s["parser"]["family"], "openai-compatible")

    def test_response_json(self):
        s = parse_response("/v1/messages", {}, "application/json", RESP)
        self.assertEqual(s["response_id"], "msg_01")
        self.assertEqual(s["response_text"], "hello")
        self.assertEqual(s["usage"]["input_tokens"], 10)

    def test_response_sse_accumulates_blocks(self):
        body = (
            b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_02","usage":{"input_tokens":7}}}\n\n'
            b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}\n\n'
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"he"}}\n\n'
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"y"}}\n\n'
            b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}\n\n'
        )
        s = parse_response("/v1/messages", {}, "text/event-stream", body)
        self.assertEqual(s["response_id"], "msg_02")
        self.assertEqual(s["response_text"], "hey")
        self.assertEqual(s["usage"], {"input_tokens": 7, "output_tokens": 3})

    def test_garbage_body_never_raises(self):
        s = parse_request("/v1/messages", {}, b"not json")
        self.assertFalse(s["json_valid"])
        s2 = parse_response("/v1/messages", {}, "application/json", b"\xff\xfe")
        self.assertFalse(s2["json_valid"])
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd repos/ata && python3 -m unittest tests.test_wire_parse -v`
Expected: FAIL/ERROR（`No module named 'ata.wire'` 或 import 错误）

- [ ] **Step 4: 最小实现（即 Step 1 的文件落位）**

Run: `python3 -m unittest tests.test_wire_parse -v`
Expected: PASS（5 个测试）

再跑全量回归确认没有破坏存量：

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add ata/wire tests/test_wire_parse.py
git commit -m "feat(wire): 移植 ava 协议解析内核（anthropic 族）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: 会话身份规则与轮次推导（plugins/capture.py 第一半）

**Files:**
- Create: `ata/plugins/capture.py`
- Test: `tests/test_capture.py`

**Interfaces:**
- Consumes: `ata.project.is_context_text(texts: str) -> bool`（存量，CONTEXT 注入判定）。
- Produces:
  - `resolve_session_id(headers: dict[str, str], agent_id: str) -> str | None` — 大小写不敏感找宿主会话头；找不到返回 None（调用方丢弃该次采集，绝不造 sid）。
  - `count_real_user_turns(messages: list) -> int` — 请求上下文里的真实用户消息数 = 当前轮次号（与 `bump_turn_if_real_user` 同口径：真实用户文本才计数，CONTEXT 注入不算）。
  - `RECORD_KEYS` — record 形状的唯一声明：`{"agent_id","path","request_headers","request_body","response_content_type","response_body","started_at_ms","completed_at_ms"}`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_capture.py`：

```python
import unittest

from ata.plugins.capture import count_real_user_turns, resolve_session_id


def user_msg(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


class ResolveSessionTest(unittest.TestCase):
    def test_claude_header_case_insensitive(self):
        h = {"x-claude-code-session-id": "abc-123"}
        self.assertEqual(resolve_session_id(h, "claude"), "abc-123")

    def test_missing_header_returns_none(self):
        self.assertIsNone(resolve_session_id({}, "claude"))
        self.assertIsNone(resolve_session_id({"user-agent": "claude-cli"}, "claude"))


class CountTurnsTest(unittest.TestCase):
    def test_counts_real_user_messages(self):
        msgs = [
            user_msg("first"),
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            user_msg("second"),
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            user_msg("third"),
        ]
        self.assertEqual(count_real_user_turns(msgs), 3)

    def test_context_injection_does_not_count(self):
        msgs = [
            user_msg("first"),
            user_msg("<system-reminder>context noise</system-reminder>"),
            user_msg("second"),
        ]
        self.assertEqual(count_real_user_turns(msgs), 2)

    def test_empty_and_malformed(self):
        self.assertEqual(count_real_user_turns([]), 0)
        self.assertEqual(count_real_user_turns([{"role": "user"}, None, "junk"]), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_capture -v`
Expected: ERROR（`No module named 'ata.plugins.capture'`）

- [ ] **Step 3: 最小实现**

创建 `ata/plugins/capture.py`：

```python
"""代理采集适配器（架构评审候选 1+2）：wire 流量 → 规范事件。

身份规则（候选 2，本模块的 interface 一部分）：从请求头恢复宿主
sessionId，往同一 session 追加，幂等键吸收重复；恢复不了就丢弃，
绝不新建孤儿会话——ava 把会话归并推迟到读取侧，ata 是写入时收敛，
平行会话会让投影/usage 合计翻倍。

v1 只发账本里别处拿不到的事实：system.upserted（prompt_text +
tools_catalog，transcript 侧 claude 永远发不出）与 turn.ended（每轮
真实 usage，spec L214 的立项痛点）。message/tool 行 transcript 已有，
代理重复发会在两条通道间产生 natural-key 写序竞态，刻意不发。
"""
from __future__ import annotations

import hashlib
import json

# 各家宿主携带会话 id 的请求头（小写）。cue/pi 若走代理，加行即可。
_SESSION_HEADERS = {
    "claude": ("x-claude-code-session-id",),
}


def resolve_session_id(headers, agent_id):
    low = {str(k).lower(): v for k, v in (headers or {}).items()}
    for name in _SESSION_HEADERS.get(agent_id, ()):
        sid = low.get(name)
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    return None


def _block_texts(content):
    """消息 content 里的文本拼接；字符串/块数组/裸字符串数组都吃。"""
    if isinstance(content, str):
        return content
    parts = []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts)


def count_real_user_turns(messages):
    """请求上下文的真实用户消息数 = 当前轮次号。

    与 jsonl 侧 bump_turn_if_real_user 同口径：CONTEXT 注入不开轮
    （复用 ata.project.is_context_text，懒加载避免循环导入，同 common.py）。
    """
    from ata.project import is_context_text

    count = 0
    for msg in messages if isinstance(messages, list) else []:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        if is_context_text(_block_texts(msg.get("content"))):
            continue
        count += 1
    return count
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_capture -v`
Expected: PASS（5 个测试）

- [ ] **Step 5: Commit**

```bash
git add ata/plugins/capture.py tests/test_capture.py
git commit -m "feat(capture): 代理通道会话身份规则与轮次推导

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: translate_capture —— system 快照 + 每轮 usage

**Files:**
- Modify: `ata/plugins/capture.py`
- Test: `tests/test_capture.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `ata.wire.parse_request/parse_response`；Task 2 的 `count_real_user_turns`；`ata.plugins.common.usage_from_counts`。
- Produces:
  - `translate_capture(record: dict, state: dict) -> list[dict]` — record 见 `RECORD_KEYS`；state 为按 session 分桶的可变 dict（跨请求持有 `system_hash`）。产出事件列表（可为空），每个都过得了 `schema.parse_event`。
  - `state_bucket(ledger, sid: str) -> dict` — 在 ledger 对象上挂 `._capture_states[sid]`（与 `http.py` `_pi_states` 同款约定）。

事件形状（后续任务与测试都依赖）：
- `system.upserted`，turn=None，payload `{"prompt_text": <str>, "tools_catalog": [{"name","description","parameters"},...]}`，eid `f"{sid}:system:{hash12}"`（确定性 id：同内容不重发）。
- `turn.ended`，turn=N，payload `{"usage": usage_from_counts(inp, outp, cache_read, cache_write, total_tokens=和)}`，eid `f"{sid}:turn:{N}:ended:{response_id or completed_at_ms}"`。usage 缺失或全空则不发（诚实缺失，不硬凑）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_capture.py` 追加：

```python
import json

from ata.plugins.capture import RECORD_KEYS, translate_capture
from ata.schema import parse_event


REQ1 = {
    "model": "claude-sonnet-5",
    "system": [{"type": "text", "text": "You are ATA."}],
    "tools": [{"name": "Read", "description": "read a file",
               "input_schema": {"type": "object"}}],
    "messages": [user_msg("hi")],
}
RESP1 = {
    "id": "msg_01", "type": "message", "role": "assistant",
    "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 5,
              "cache_read_input_tokens": 2, "cache_creation_input_tokens": 1},
}


def record(req_body, resp_body, sid="s1", ct="application/json",
           started=1000, completed=1900):
    return {
        "agent_id": "claude",
        "path": "/v1/messages",
        "request_headers": {"x-claude-code-session-id": sid},
        "request_body": req_body,
        "response_content_type": ct,
        "response_body": resp_body,
        "started_at_ms": started,
        "completed_at_ms": completed,
    }


class TranslateCaptureTest(unittest.TestCase):
    def setUp(self):
        # ingest 路径由 ingest_capture 负责 set；单测直呼 translate 时自己给。
        self.state = {"session_id": "s1"}

    def test_first_capture_emits_system_and_turn_end(self):
        evs = translate_capture(record(json.dumps(REQ1).encode(),
                                       json.dumps(RESP1).encode()), self.state)
        self.assertEqual([e["type"] for e in evs], ["system.upserted", "turn.ended"])
        sys_ev, end_ev = (parse_event(e) for e in evs)
        self.assertIsNone(sys_ev["turn"])
        self.assertEqual(sys_ev["payload"]["prompt_text"], "You are ATA.")
        self.assertEqual(sys_ev["payload"]["tools_catalog"][0]["name"], "Read")
        self.assertEqual(end_ev["turn"], 1)
        u = end_ev["payload"]["usage"]
        self.assertEqual(u["status"], "reported")
        self.assertEqual((u["input"], u["output"], u["cache_read"],
                          u["cache_write"], u["total_tokens"]),
                         (10, 5, 2, 1, 18))
        self.assertIsNone(u["cost"])

    def test_system_not_reemitted_when_unchanged(self):
        r = record(json.dumps(REQ1).encode(), json.dumps(RESP1).encode())
        translate_capture(r, self.state)
        evs = translate_capture(r, self.state)
        self.assertEqual([e["type"] for e in evs], ["turn.ended"])

    def test_system_reemitted_when_prompt_changes(self):
        translate_capture(record(json.dumps(REQ1).encode(),
                                 json.dumps(RESP1).encode()), self.state)
        req2 = dict(REQ1, system=[{"type": "text", "text": "New prompt."}])
        evs = translate_capture(record(json.dumps(req2).encode(),
                                       json.dumps(RESP1).encode()), self.state)
        self.assertIn("system.upserted", [e["type"] for e in evs])

    def test_turn_number_tracks_real_user_count(self):
        msgs = [user_msg("first"),
                {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
                user_msg("second")]
        req2 = dict(REQ1, messages=msgs)
        _, end = (parse_event(e) for e in translate_capture(
            record(json.dumps(req2).encode(), json.dumps(RESP1).encode()),
            self.state))
        self.assertEqual(end["turn"], 2)

    def test_missing_usage_emits_nothing(self):
        resp = dict(RESP1, usage={})
        evs = translate_capture(record(json.dumps(REQ1).encode(),
                                       json.dumps(resp).encode()), self.state)
        # system 快照仍要发；turn.ended 没有 usage 就不发
        self.assertEqual([e["type"] for e in evs], ["system.upserted"])

    def test_sse_response_parses(self):
        sse = (
            b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_09","usage":{"input_tokens":7}}}\n\n'
            b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}\n\n'
        )
        evs = translate_capture(record(json.dumps(REQ1).encode(), sse,
                                       ct="text/event-stream"), self.state)
        types = [e["type"] for e in evs]
        self.assertIn("system.upserted", types)
        self.assertIn("turn.ended", types)
        end = parse_event(next(e for e in evs if e["type"] == "turn.ended"))
        self.assertEqual((end["payload"]["usage"]["input"],
                          end["payload"]["usage"]["output"]), (7, 3))

    def test_record_shape_declared(self):
        self.assertEqual(
            sorted(RECORD_KEYS),
            sorted(["agent_id", "path", "request_headers", "request_body",
                    "response_content_type", "response_body",
                    "started_at_ms", "completed_at_ms"]))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_capture -v`
Expected: FAIL（`ImportError: cannot import name 'translate_capture'`）

- [ ] **Step 3: 实现**

在 `ata/plugins/capture.py` 追加：

```python
from ata.plugins.common import usage_from_counts
from ata.wire import parse_request as _wire_req
from ata.wire import parse_response as _wire_resp

#: record 形状的唯一声明（shell 与 HTTP 端点共同遵守）。
RECORD_KEYS = frozenset({
    "agent_id", "path", "request_headers", "request_body",
    "response_content_type", "response_body",
    "started_at_ms", "completed_at_ms",
})


def state_bucket(ledger, sid):
    """按 session 分桶的翻译状态，挂在 ledger 上（与 _pi_states 同款约定）。"""
    states = getattr(ledger, "_capture_states", None)
    if states is None:
        ledger._capture_states = {}
        states = ledger._capture_states
    return states.setdefault(sid, {"session_id": sid})


def _catalog(tool_items):
    return [
        {
            "name": item.get("name"),
            "description": item.get("description"),
            "parameters": item.get("parameters"),
        }
        for item in (tool_items or [])
        if isinstance(item, dict) and item.get("name")
    ]


def _system_hash(prompt_text, catalog):
    blob = json.dumps(
        {"p": prompt_text, "t": catalog}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def translate_capture(rec, state):
    """一次截获的请求/响应对 → 规范事件列表。永不抛（坏输入返回 []）。"""
    try:
        return _translate(rec, state)
    except Exception as exc:  # noqa: BLE001 —— 采集绝不弄挂被代理请求
        print(f"capture translate error: {exc}")
        return []


def _translate(rec, state):
    path = rec.get("path") or ""
    body = rec.get("request_body") or b""
    req = _wire_req(path, rec.get("request_headers") or {}, body)
    resp = _wire_resp(path, {}, rec.get("response_content_type") or "",
                      rec.get("response_body") or b"")
    out = []
    ts = int(rec.get("completed_at_ms") or rec.get("started_at_ms") or 1)
    agent_id = rec.get("agent_id") or "claude"
    sid = state.get("session_id")

    # SYSTEM 快照 + tools 目录：只在内容变化时发（system.upserted 无自然键，
    # 每次请求都带全文，不去重会把账本灌爆）。
    prompt_text = "\n\n".join(req.get("system_prompts") or [])
    catalog = _catalog(req.get("tool_items"))
    if prompt_text:
        h = _system_hash(prompt_text, catalog)
        if h != state.get("system_hash"):
            state["system_hash"] = h
            out.append({
                "v": 1, "id": f"{sid}:system:{h}", "agent_id": agent_id,
                "session_id": sid, "ts": ts, "type": "system.upserted",
                "turn": None,
                "payload": {"prompt_text": prompt_text, "tools_catalog": catalog},
            })

    # 每轮真实 usage：轮次号 = 请求上下文真实用户消息数（与 transcript 侧
    # bump_turn_if_real_user 同口径，两条通道才能落在同一 turn 上）。
    usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
    inp = int(usage.get("input_tokens") or 0)
    outp = int(usage.get("output_tokens") or 0)
    cr = int(usage.get("cache_read_input_tokens") or 0)
    cw = int(usage.get("cache_creation_input_tokens") or 0)
    if inp or outp or cr or cw:
        messages = []
        try:
            messages = json.loads(body.decode("utf-8")).get("messages") or []
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
        turn = count_real_user_turns(messages)
        if turn >= 1:
            rid = resp.get("response_id")
            out.append({
                "v": 1,
                "id": f"{sid}:turn:{turn}:ended:{rid or ts}",
                "agent_id": agent_id, "session_id": sid, "ts": ts,
                "type": "turn.ended", "turn": turn,
                "payload": {"usage": usage_from_counts(
                    inp, outp, cr, cw, total_tokens=inp + outp + cr + cw)},
            })
    return out
```

注：`_translate` 不 import `ata.project`——CONTEXT 判定只在 `count_real_user_turns` 内部懒加载，避免顶层循环导入（同 `common.py` 的做法）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_capture -v`
Expected: PASS（11 个测试）

- [ ] **Step 5: Commit**

```bash
git add ata/plugins/capture.py tests/test_capture.py
git commit -m "feat(capture): system 快照与每轮 usage 翻译

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: ingest_capture 与 POST /api/captures

**Files:**
- Modify: `ata/plugins/capture.py`（加 `ingest_capture`）
- Modify: `ata/http.py`（路由分支，仿 `_ingest_pi_hooks`）
- Test: `tests/test_capture_http.py`（新建）

**Interfaces:**
- Consumes: Task 3 全部；`Ledger.append_many`；`schema.parse_event`。
- Produces:
  - `ingest_capture(ledger, record: dict) -> int`（写入事件数；校验失败抛 `ValidationError`，由调用方决定吞不吞——进程内壳吞，HTTP 端点回 400）。
  - `POST /api/captures`，请求体：record 的 JSON 形式，其中 `request_body`/`response_body` 为 base64 字符串（JSON 不安全字节）。响应 `{"ok":true,"count":N}`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_capture_http.py`（仿 `tests/test_cue.py` 的真起服务风格）：

```python
import base64
import json
import tempfile
import unittest
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger


REQ1 = {
    "model": "claude-sonnet-5",
    "system": [{"type": "text", "text": "You are ATA."}],
    "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
}
RESP1 = {
    "id": "msg_01", "type": "message", "role": "assistant",
    "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


class CaptureHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name))
        self.httpd = make_server(self.ledger, Path(self.tmp.name), "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        import threading
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.tmp.cleanup()

    def post(self, payload):
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/captures",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())

    def test_ingest_via_http(self):
        payload = {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": "sess-9"},
            "request_body": base64.b64encode(json.dumps(REQ1).encode()).decode(),
            "response_content_type": "application/json",
            "response_body": base64.b64encode(json.dumps(RESP1).encode()).decode(),
            "started_at_ms": 1000, "completed_at_ms": 1900,
        }
        status, body = self.post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["count"], 2)
        recs = self.ledger.read("sess-9")
        self.assertEqual(sorted(r["type"] for r in recs),
                         ["system.upserted", "turn.ended"])

    def test_missing_session_header_is_400(self):
        payload = {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {},
            "request_body": base64.b64encode(json.dumps(REQ1).encode()).decode(),
            "response_content_type": "application/json",
            "response_body": base64.b64encode(json.dumps(RESP1).encode()).decode(),
            "started_at_ms": 1000, "completed_at_ms": 1900,
        }
        status, body = self.post(payload)
        self.assertEqual(status, 400)
        self.assertIn("session", body["error"])


if __name__ == "__main__":
    unittest.main()
```

先确认 `Ledger` 的读方法名（本计划用 `ledger.read(sid)`，`ata/ledger.py:228` 已存在；`append_many` 在 L305）——以现有代码为准，不要新加读方法。

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_capture_http -v`
Expected: FAIL（404 not found）

- [ ] **Step 3: 实现**

`ata/plugins/capture.py` 追加：

```python
def ingest_capture(ledger, rec):
    """解析 → 校验 → 入账本。返回写入数；校验失败抛 ValidationError。"""
    from ata.schema import parse_event

    headers = rec.get("request_headers") or {}
    agent_id = rec.get("agent_id") or "claude"
    sid = resolve_session_id(headers, agent_id)
    if not sid:
        raise ValueError("capture: no host session id; dropping (no orphan sessions)")
    state = state_bucket(ledger, sid)
    state["session_id"] = sid
    events = [parse_event(ev) for ev in translate_capture(rec, state)]
    if events:
        ledger.append_many(events)
    return len(events)
```

`ata/http.py`：在 `_ingest_pi_hooks` 定义之后加同款分支（缩进同级）：

```python
        def _ingest_capture(self, raw):
            from ata.plugins.capture import RECORD_KEYS, ingest_capture
            if not isinstance(raw, dict):
                return self._json(400, {"ok": False, "error": "capture record must be object"})
            missing = RECORD_KEYS - set(raw)
            if missing:
                return self._json(400, {"ok": False, "error": f"missing {sorted(missing)}"})
            rec = dict(raw)
            # JSON 传输形态里 body 是 base64；转回 bytes 后与进程内 record 同形。
            for key in ("request_body", "response_body"):
                import base64
                try:
                    rec[key] = base64.b64decode(raw.get(key) or "")
                except Exception:
                    return self._json(400, {"ok": False, "error": f"{key} must be base64"})
            try:
                count = ingest_capture(ledger, rec)
            except (ValidationError, TypeError, ValueError) as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            return self._json(200, {"ok": True, "count": count})
```

并在 `do_POST` 的路由链里（`/api/events` 判定之前）加：

```python
            if parsed.path == "/api/captures":
                return self._ingest_capture(raw)
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `python3 -m unittest tests.test_capture_http tests.test_capture -v && python3 -m unittest discover -s tests -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add ata/plugins/capture.py ata/http.py tests/test_capture_http.py
git commit -m "feat(http): POST /api/captures 代理采集入账通道

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: 转发壳 ata/capture_proxy.py

**Files:**
- Create: `ata/capture_proxy.py`
- Test: `tests/test_capture_proxy.py`

**Interfaces:**
- Consumes: `ata.plugins.capture.ingest_capture`。
- Produces:
  - `start_capture_proxy(host: str, port: int, upstream: str, agent_id: str, ingest) -> ThreadingHTTPServer` — `ingest(record_dict)` 由调用方注入（生产传 `lambda rec: ingest_capture(led, rec)`，测试注入假账本）。返回已绑定未 serve 的 server，调用方自行 `serve_forever`/`shutdown`（与 `make_server` 同约定）。
  - 行为契约：POST 一律转发到 upstream；响应流式（chunked）回传客户端的同时累积留档（上限 `MAX_CAPTURE_BYTES = 8MB`）；完成后组 record 调 `ingest`，**ingest 抛任何异常都吞掉打印**，不影响已回传的响应。非 POST 直接透传不采集。认证头只转发、不留档（record 里根本不含 headers 原文，只有提取结果）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_capture_proxy.py`：

```python
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ata.capture_proxy import start_capture_proxy
from ata.ledger import Ledger


UPSTREAM_RESP = {
    "id": "msg_01", "type": "message", "role": "assistant",
    "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


def make_upstream(responses):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            body = json.dumps(responses[0]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    return srv


class CaptureProxyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name))
        self.upstream = make_upstream([UPSTREAM_RESP])
        self.upstream_port = self.upstream.server_address[1]

    def tearDown(self):
        self.upstream.shutdown()
        self.tmp.cleanup()

    def _start_proxy(self):
        from ata.plugins.capture import ingest_capture

        httpd = start_capture_proxy(
            "127.0.0.1", 0, f"http://127.0.0.1:{self.upstream_port}",
            "claude", lambda rec: ingest_capture(self.ledger, rec))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        return port

    def test_end_to_end_events_land_in_ledger(self):
        port = self._start_proxy()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/messages",
            data=json.dumps({
                "model": "claude-sonnet-5",
                "system": [{"type": "text", "text": "You are ATA."}],
                "messages": [{"role": "user",
                              "content": [{"type": "text", "text": "hi"}]}],
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json",
                     "x-claude-code-session-id": "prox-1",
                     "x-api-key": "sk-secret-must-not-leak"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("hello", resp.read().decode())
        recs = self.ledger.read("prox-1")
        types = sorted(r["type"] for r in recs)
        self.assertEqual(types, ["system.upserted", "turn.ended"])
        dumped = json.dumps(recs)
        self.assertNotIn("sk-secret", dumped)

    def test_no_session_header_still_proxies(self):
        port = self._start_proxy()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/messages",
            data=json.dumps({"messages": []}).encode(), method="POST")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)  # 代理照常工作
        self.assertEqual(self.ledger.sessions(), [])  # 只是不采集


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_capture_proxy -v`
Expected: ERROR（`No module named 'ata.capture_proxy'`）

- [ ] **Step 3: 实现**

创建 `ata/capture_proxy.py`：

```python
"""转发式采集代理壳（架构评审候选 1 的「壳在 ata 重写」半边）。

职责只有三件：把 agent 的 LLM 流量原样转发给上游、把响应流式回传、
事后把截获的字节交给 ingest 翻译入账。 ava 的对应壳住在 2158 行上帝
模块里且有三处已知脆弱点（locals().get 计时、writer 类属性侧信道、
frozen dataclass 贴 property），这里全部不复制：计时显式测量、ingest
显式注入、配置显式传参。

采集失败绝不弄挂被代理的请求：ingest 抛什么异常都吞掉打印。
"""
from __future__ import annotations

import http.client
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_CAPTURE_BYTES = 8 * 1024 * 1024
_CHUNK = 65536
# 只转发不留档的头（record 不含 headers 原文，这是第二道保险）。
_HOP_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}


def start_capture_proxy(host, port, upstream, agent_id, ingest):
    parts = urlsplit(upstream if "//" in upstream else f"https://{upstream}")
    secure = parts.scheme == "https"
    upstream_port = parts.port or (443 if secure else 80)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _relay(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            conn_cls = http.client.HTTPSConnection if secure else http.client.HTTPConnection
            conn = conn_cls(parts.hostname, upstream_port, timeout=600)
            started = time.time()
            completed = started
            content_type = ""
            buf = bytearray()
            try:
                # 只转发会话识别需要的头，认证头（x-api-key 等）不出代理进程。
                fwd = {k: v for k, v in self.headers.items()
                       if k.lower().startswith("x-claude")
                       or k.lower() == "content-type"}
                conn.request(self.command, self.path, body=body, headers=fwd)
                resp = conn.getresponse()
                content_type = resp.getheader("Content-Type") or ""
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() in _HOP_HEADERS:
                        continue
                    self.send_header(k, v)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    room = MAX_CAPTURE_BYTES - len(buf)
                    if room > 0:
                        buf.extend(chunk[:room])
                    self.wfile.write(f"{len(chunk):x}\r\n".encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            except Exception as exc:
                print(f"capture proxy relay error: {exc}")
                try:
                    self.send_error(502, str(exc))
                except Exception:
                    pass
            finally:
                completed = time.time()
                conn.close()
            # 转发成功后才组 record；ingest 抛什么异常都不影响已回传的响应。
            if self.command != "POST":
                return
            record = {
                "agent_id": agent_id,
                "path": self.path.split("?", 1)[0],
                "request_headers": {k: v for k, v in self.headers.items()
                                    if k.lower().startswith("x-claude")},
                "request_body": bytes(body),
                "response_content_type": content_type,
                "response_body": bytes(buf),
                "started_at_ms": int(started * 1000),
                "completed_at_ms": int(completed * 1000),
            }
            try:
                ingest(record)
            except Exception as exc:  # noqa: BLE001
                print(f"capture ingest error: {exc}")

        do_POST = _relay
        do_GET = _relay
        do_PUT = _relay
        do_DELETE = _relay
        do_PATCH = _relay

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, port), Handler)
```

实现说明（执行者必读）：
- 认证头隔离是壳的责任：转发头只放行 `x-claude-*` 与 `content-type`，record 的 `request_headers` 同样只收 `x-claude-*`——`x-api-key` / `authorization` 物理上不进 ingest，测试里的 `sk-secret-must-not-leak` 断言锁的就是这个。
- 非 POST 也走 `_relay` 但不组 record（`self.command == "POST"` 门控）。
- 响应整体缓冲上限 8MB，超出部分照常转发但不留档（解析用前 8MB 足够）。
- 上游连不通时回 502 并打印，绝不崩线程（ThreadingHTTPServer 单请求异常只影响该连接，但显式处理让冒烟输出干净）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_capture_proxy -v`
Expected: PASS（2 个测试）

- [ ] **Step 5: Commit**

```bash
git add ata/capture_proxy.py tests/test_capture_proxy.py
git commit -m "feat(proxy): 转发式采集壳，流式回传 + 进程内 ingest

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: CLI 接线 --proxy-port

**Files:**
- Modify: `ata/__main__.py:62-110`
- Test: 手动冒烟（自动化已被 Task 5 端到端覆盖，此处只验证接线）

**Interfaces:**
- Consumes: `start_capture_proxy`、`ingest_capture`。
- Produces: `ata serve --proxy-port 8319 [--proxy-upstream URL] [--proxy-agent claude]`。默认不开；开了就在 `127.0.0.1:proxy-port` 挂转发代理线程，随主进程退出。

- [ ] **Step 1: 加参数**

`ata/__main__.py` 参数区（`--tail-max-age-days` 之后）追加：

```python
    # 代理采集通道：默认关。开起来后把 agent 的 API base 指到这里即可补采。
    p.add_argument("--proxy-port", type=int, default=None)
    p.add_argument("--proxy-upstream", default="https://api.anthropic.com")
    p.add_argument("--proxy-agent", choices=["claude"], default="claude")
```

- [ ] **Step 2: 接线**

在 `start_tail(args.codex_path, codex_tf)` 之后、`make_server(...)` 之前加：

```python
    if args.proxy_port:
        from ata.capture_proxy import start_capture_proxy
        from ata.plugins.capture import ingest_capture
        proxy_httpd = start_capture_proxy(
            "127.0.0.1", args.proxy_port, args.proxy_upstream, args.proxy_agent,
            lambda rec: ingest_capture(led, rec))
        threading.Thread(target=proxy_httpd.serve_forever, daemon=True).start()
        print(f"capture proxy http://127.0.0.1:{args.proxy_port} -> {args.proxy_upstream}")
```

- [ ] **Step 3: 冒烟验证**

```bash
python3 -m ata serve --ledger ./data-smoke --port 8899 --proxy-port 8319 &
sleep 1
curl -s -X POST http://127.0.0.1:8319/v1/messages \
  -H 'Content-Type: application/json' \
  -H 'x-claude-code-session-id: smoke-1' \
  -H 'x-api-key: dummy' \
  -d '{"system":[{"type":"text","text":"smoke"}],"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}' -o /dev/null -w '%{http_code}\n'
# 预期：非 2xx（上游真的会拒 dummy key），但这证明转发链路通；
# 真值验证用 Task 5 的自动化测试即可。然后：
curl -s http://127.0.0.1:8899/api/sessions | grep -o smoke-1 || echo "（上游拒绝时不采集属预期）"
kill %1
```

Expected: 代理端口能连、转发报错来自上游而非代理崩溃；无 Python traceback 打到终端。

- [ ] **Step 4: 全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add ata/__main__.py
git commit -m "feat(cli): --proxy-port 开启代理采集通道

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: 文档与 ADR —— 正式重开 v1 非目标裁决

**Files:**
- Create: `docs/adr/0001-proxy-capture-channel.md`
- Modify: `CONTEXT.md`（Language 区加术语；数据边界表更新 claude 行）
- Modify: `README.md`（运行方式加一段，若无合适章节则放「可选」小节）

**Interfaces:**
- Consumes: 无。
- Produces: 未来探索者读到「代理」时的单一出处。

- [ ] **Step 1: 写 ADR**

创建 `docs/adr/0001-proxy-capture-channel.md`：

```markdown
# ADR-0001: 引入代理采集通道（重开 v1 非目标裁决）

日期: 2026-08-26
状态: 已接受

## 背景

v1 kernel design（docs/superpowers/specs/2026-08-15-ata-v1-canonical-event-kernel-design.md
L240-247）把「实现反向代理」「把旧 AVA 的 Python 代理搬进本仓库」列为非目标，
L19 同时裁决「权威平面=规范事件，来源可以是 live 流或第一方账本适配器；
HTTP 抓包可选」。同一份 spec L214 承认：「要求每次 HTTP 都有 usage 会逼出代理」。

## 裁决

重开非目标中的「反向代理」一条，但收窄范围：

1. 代理是**补充通道**，不是权威平面。它只发账本里别处拿不到的事件
   （system.upserted、turn.ended），从不替代第一方 transcript 适配器。
2. 只搬 ava 的**解析内核**（ata/wire/，纯函数）；转发壳在 ata 重写
   （ata/capture_proxy.py），不搬 ava 的上帝模块与存储层。
3. 身份规则：能恢复宿主 sessionId 就并入同一 session；不能就丢弃，
   绝不新建孤儿会话（与「血缘 NULL 即事实」同一哲学）。

## 为什么现在重开

claude transcript 侧永久缺失 SYSTEM 快照、tools 目录、每轮 usage
（官方 transcript 不落盘这些事实，features/2026-08-17 文档确认旁路目录
也没有）。hook 路线已被 spec 否决（27 个 hook 无每轮 token）。代理是
这些事实的唯一可得来源——这正是 spec L214 自己预言的「逼出代理」。

## 后果

- 数据边界速记表中 claude 的 SYSTEM 快照从「无」变为「代理通道开启时有」。
- 两条采集通道写同一 session，靠幂等键收敛；代理刻意不发 message/tool
  行以避免 natural-key 写序竞态。
- OpenAI 族解析（codex 可用）暂缓，ata/wire 的注册表 seam 已预留。
```

- [ ] **Step 2: 更新 CONTEXT.md**

在「飞轮」章节前插入一节：

```markdown
### 代理采集

**代理通道（capture）**：
转发式采集代理：截获 agent↔LLM 的 HTTP 流量，解析出账本别处拿不到的事实（SYSTEM 快照、tools 目录、每轮 usage）作为规范事件并入账本。补充通道，不是权威平面；只发增量事实，从不替代第一方 transcript 适配器。
_Avoid_: 万能代理、以代理流量当账本、把代理叫「反向代理组件」

**并入（merge-on-write）**：
代理截获的流量恢复出宿主 sessionId 后往同一 session 追加，靠幂等键收敛；恢复不了就丢弃并放弃该次采集，绝不新建孤儿会话。
_Avoid_: 平行会话、读取侧归并
```

数据边界速记表 claude 行改为：

```markdown
| claude | 无（代理通道开启时有） | reported（缺失或全 0 → missing）；每轮 usage 经代理通道补全 |
```

- [ ] **Step 3: README 补运行段**

在 README 的运行/用法合适位置加：

```markdown
### 代理采集通道（可选）

transcript 采不到的事实（claude 的系统提示、工具目录、每轮 token）可以从
流量侧补：

    python3 -m ata serve --proxy-port 8319

把 agent 的 API base 指向 `http://127.0.0.1:8319`（上游默认
api.anthropic.com，可用 `--proxy-upstream` 改）。代理只记录解析后的
事实，认证头不留档；无法识别所属会话的流量直接放行不采集。
```

- [ ] **Step 4: Commit**

```bash
git add docs/adr/0001-proxy-capture-channel.md CONTEXT.md README.md
git commit -m "docs: 代理采集通道 ADR 与领域词汇

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## 非目标（明确不做）

- **CaptureWriter 队列语义（评审候选 3）**：进程内同步 ingest 与 pi-hooks 先例一致，本地 SQLite append 是毫秒级，队列/溢出降级是为慢 sink 准备的。等出现第二个慢 sink 再引入——那时才是真 seam。
- **OpenAI 族解析器移植**：1095 行，当前没有 codex 代理需求；`ata/wire/protocol_facts` 的注册表 seam 已预留位置。
- **代理发 message.upserted / tool.upserted**：transcript 适配器已覆盖，双通道写同自然键有竞态；等出现消费端「择优合并」策略再说。
- **流式增量解析**：壳整体缓冲（≤8MB）后解析；SSE 累积逻辑在内核里本来就能吃完整流。
