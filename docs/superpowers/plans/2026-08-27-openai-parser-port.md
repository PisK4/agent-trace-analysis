# openai_parser 移植 + droid 反代系统补货 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 droid (走 OpenAI Chat Completions 协议) 走 17878 代理后,能在 `events` 流里产出 `system.upserted` + `tool.upserted` + `turn.ended`——核心是移植 `openai_parser.py` 并在 `protocol_facts.registered()` 挂出 `_OpenAI` adapter。

**Architecture:** 1:1 移植 ava `agent_visualization_analysis/openai_parser.py` (1095 行) 到 ata,新文件 `ata/wire/openai_parser.py`。在 `ata/wire/protocol_facts.py` 加 `_OpenAI` adapter class,匹配 `/v1/chat/completions` 与 `/v1/responses` 两条路径后缀,内部调用 ava 同款函数(它们内部按路径分流 `api_family` 字符串)。wrapper 函数把 ata seam 的 `(path, headers, body)` / `(path, headers, content_type, body)` 多参透传给 ava 形参 `(path, body)` / `(content_type, body)`。

**Tech Stack:** Python 3, ata/wire ProtocolParser 协议, ava `openai_parser.py` 解析逻辑, unittest。

**Spec:**
- `repos/ata/docs/adr/0001-proxy-capture-channel.md` 第 36 行"OpenAI 族解析（codex 可用）暂缓"是本计划**作废**的裁决。
- `repos/ata/ata/wire/protocol_facts.py` seam 已有 `_AnthropicMessages` 形态,新 adapter 同构。
- `repos/ata/ata/plugins/capture.py:164` `req.get("system_prompts")` 与 L165 `req.get("tool_items")` 是消费契约,parser 必须返回这俩字段。
- `/var/folders/ml/.../ata-capture-channel-handoff-2026-08-27.md` 第 71-79 行是上游交接给出的步骤。

---

## Global Constraints

- 移植**严格 1:1** ava `openai_parser.py` 的 1095 行,只删 ava 仓库私有引用(本文件无 import,只 stdlib `json` + `typing`)。
- 新增 `ata/wire/openai_parser.py` 顶部加版权注释标记**移植来源** + 行数差异,便于审计。
- ata seam 是 `(path, headers, body)` 三参; ava 是 `(path, body)` 二参。Adapter wrapper 用 `_ = headers` 吞掉,不改 ava 函数签名(avd 原版继续可用,移植版是 ata 内部快照)。
- 不动 `_OpenAICompatible` fallback——它是 protocol_facts 的显式 `register(fallback=True)` 替代品,本计划只**注册**新 adapter,不动 fallback 本身。
- `registered()` 顺序:`_AnthropicMessages` 在前、`_OpenAI` 在后;`test_protocol_facts.py` 已有非重叠断言,本计划复用之。
- droid session id 字段**本计划不预设**——从真实 droid 流量回填(Task 6 e2e 副产物),`_SESSION_HEADERS` 或 `_BODY_SESSION_FIELDS` 加具体提取规则。
- 每个 Task 收尾独立 `git commit`,commit message 不带 Co-Authored-By(用户偏好)。
- 测试用 `unittest.TestCase`,跑 `python -m pytest tests/<file>.py -v`(或 `python -m unittest tests.<file> -v`)。
- 行尾 LF,Python 3.11+ 语法(`dict[str, Any]`、`tuple[...]`、`from __future__ import annotations`)。
- 计划用 `make test`(`repos/ata/Makefile` 已有)做最终全量回归。

---

## File Structure

### 新增
- `repos/ata/ata/wire/openai_parser.py` — 1095 行 1:1 移植自 ava,顶部 5 行版权注释。
- `repos/ata/tests/test_openai_parser_port.py` — 本计划所有 parser 行为回归。

### 修改
- `repos/ata/ata/wire/protocol_facts.py` — 新增 `_OpenAI` adapter class,L147 `registered()` 把它加进返回 tuple;L65-72 import 新加 `parse_openai_request, parse_openai_response`。
- `repos/ata/ata/plugins/capture.py` — Task 6 e2e 后若发现 droid session id 字段,回填到 `_SESSION_HEADERS` 或 `_BODY_SESSION_FIELDS`。
- `repos/ata/docs/adr/0001-proxy-capture-channel.md` — 第 36 行"OpenAI 族解析（codex 可用）暂缓"标 ~~strikethrough~~,加"2026-08-27 已落地"备注指向本计划路径。

### 不动
- `repos/ata/ata/wire/anthropic_parser.py` — 现有解析器,本次不重构。
- `repos/ata/ata/wire/storage_headers.py` — 已含 `x-droid-` 占位 namespace,无需新增。
- `repos/ata/ata/capture_proxy.py` — 转发壳,白名单与身份提取解耦。
- `~/.factory/settings.json` / `~/.claude/settings.json` — droid 配置已切到 17878,本计划不改配置。

---

### Task 1: 失败测试——`_OpenAI` adapter 识别 chat-completions 路径并解析

**Files:**
- Modify: `repos/ata/tests/test_wire_parse.py`(追加 1 个测试)
- Test: `repos/ata/tests/test_wire_parse.py::WireParseTest::test_chat_completions_path_dispatches_to_openai`

**Interfaces:**
- Consumes: `ata.wire.parse_request(path, headers, body)` — 现有 seam。
- Produces: 失败输出 `AssertionError`(当前 `_OpenAICompatible` fallback,family 是 `openai-compatible`,无 `system_prompts`)。

- [ ] **Step 1: 在 `tests/test_wire_parse.py` 末尾追加测试**

在 `WireParseTest` 类内、`test_garbage_body_never_raises` 之后追加:

```python
CHAT_REQ = (
    b'{"model":"gpt-4o","stream":false,'
    b'"messages":[{"role":"system","content":"You are droid."},'
    b'{"role":"user","content":"hello"}],'
    b'"tools":[{"type":"function","function":{"name":"Read",'
    b'"description":"read a file","parameters":{"type":"object"}}}]}'
)

def test_chat_completions_path_dispatches_to_openai(self):
    s = parse_request("/v1/chat/completions", {}, CHAT_REQ)
    self.assertEqual(s["parser"]["family"], "openai")
    self.assertEqual(s["api_family"], "openai-chat-completions")
    self.assertTrue(s["json_valid"])
    self.assertEqual(s["system_prompts"], ["You are droid."])
    self.assertEqual([t["name"] for t in s["tool_items"]], ["Read"])
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_wire_parse.py::WireParseTest::test_chat_completions_path_dispatches_to_openai -v
```

Expected: **FAIL** with `AssertionError: 'openai-compatible' != 'openai'`(当前 fallback family 是 `openai-compatible`)。

- [ ] **Step 3: 跑全量 wire_parse 测试确认不破坏现有**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_wire_parse.py -v
```

Expected: 5 个原测试 PASS + 新测试 1 个 FAIL。

- [ ] **Step 4: 暂不 commit**(RED 状态,等 Task 2 变绿再合一个 commit)。

---

### Task 2: 移植 ava `openai_parser.py` 到 `ata/wire/openai_parser.py`

**Files:**
- Create: `repos/ata/ata/wire/openai_parser.py`(从 ava 1:1 复制,顶部加版权注释)

**Interfaces:**
- Produces: `parse_openai_request(path: str, body: bytes) -> dict[str, Any]` 与 `parse_openai_response(content_type: str, body: bytes) -> dict[str, Any]`(与 ava 同款函数签名)。
- 这两个函数是 ava 1:1 移植,**不**接受 headers 形参(ata adapter 在 wrapper 里吞掉)。

- [ ] **Step 1: 复制 ava 原文件到 ata 目标路径**

```bash
cp /Users/pis/workspace_intelligence/creator-intelligence/repos/agent-visualization-analysis/agent_visualization_analysis/openai_parser.py \
   /Users/pis/workspace_intelligence/creator-intelligence/repos/ata/ata/wire/openai_parser.py
```

- [ ] **Step 2: 在新文件顶部加版权/移植注释(在 `import json` 之前)**

替换 `repos/ata/ata/wire/openai_parser.py` 的第 1-3 行(原 `import json` / `from typing ...` / 空行)为:

```python
"""OpenAI Chat Completions + Responses API 解析内核（移植自 ava）。

源: agent_visualization_analysis/agent_visualization_analysis/openai_parser.py
移植日期: 2026-08-27
差异: 1:1 移植,行数 ~1095;未来 ava 上游改动需手动同步。
公开函数: parse_openai_request(path, body) -> dict
         parse_openai_response(content_type, body) -> dict
两者**不**吃 headers——ata seam 多给的 headers 在 protocol_facts._OpenAI wrapper 吞掉,
ava 的 metadata 提取走 payload["metadata"],不读 request header。
"""

import json
from typing import Any, Iterable, Optional
```

(原 `import json` 移到第 14 行,空行变 13 行)

- [ ] **Step 3: 跑 Task 1 的测试确认仍 RED**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_wire_parse.py::WireParseTest::test_chat_completions_path_dispatches_to_openai -v
```

Expected: 仍 FAIL(`openai_parser` 文件存在但 `protocol_facts` 还没接,select 仍走 `_OpenAICompatible` fallback)。

- [ ] **Step 4: 用 `python -c` 隔离验证函数本身能跑**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -c "
from ata.wire import openai_parser
out = openai_parser.parse_openai_request('/v1/chat/completions', b'{\"messages\":[{\"role\":\"system\",\"content\":\"hi\"}]}')
assert out['system_prompts'] == ['hi'], out
print('ok')
"
```

Expected: 输出 `ok`(无错误)。

- [ ] **Step 5: 暂不 commit**(等 Task 3 adapter 接入后才合一个 commit)。

---

### Task 3: 在 `protocol_facts` 注册 `_OpenAI` adapter

**Files:**
- Modify: `repos/ata/ata/wire/protocol_facts.py`(L41-46 import 增; L103 后加 `_OpenAI` class; L155 `registered()` 加入)

**Interfaces:**
- Consumes: `parse_openai_request(path, body)`, `parse_openai_response(content_type, body)` —— Task 2 移植产物。
- Produces: `class _OpenAI: family="openai"`, `handles(path)` 匹配 `/v1/chat/completions` 或 `/v1/responses` 后缀,`parse_request` 透传 headers(`_ = headers`),`parse_response` 同理透传。

- [ ] **Step 1: 替换 `protocol_facts.py` 的 import 段(L37-46)**

把:

```python
from .anthropic_parser import (
    API_FAMILY as ANTHROPIC_API_FAMILY,
    is_anthropic_messages_path,
    parse_anthropic_request,
    parse_anthropic_response,
)
```

改为:

```python
from .anthropic_parser import (
    API_FAMILY as ANTHROPIC_API_FAMILY,
    is_anthropic_messages_path,
    parse_anthropic_request,
    parse_anthropic_response,
)
from .openai_parser import (
    parse_openai_request,
    parse_openai_response,
)

#: openai 族的 api_family 字符串集合,从 ava openai_parser.API_FAMILIES 反查以避免漂移。
#: ata seam 不消费此集合,只用其作 _OpenAI.api_families 声明。
OPENAI_API_FAMILIES = ("openai-chat-completions", "openai-responses")
```

- [ ] **Step 2: 在 `_AnthropicMessages` 类后、`_OpenAICompatible` 前插入 `_OpenAI` 类**

在 `protocol_facts.py` L121 (`class _OpenAICompatible:` 那一行) 之前插入:

```python
class _OpenAI:
    """OpenAI Chat Completions + Responses API 的 ata seam 适配器。

    内部委托给 ava 同款解析函数(ata/wire/openai_parser.py),wrapper 把
    ata seam 多给的 headers 透传丢弃——ava 的 metadata 从 payload 走,
    不读 request header,headers 在 ata 暂未消费。
    """

    family = "openai"
    provider = "openai"
    api_families = OPENAI_API_FAMILIES

    @staticmethod
    def _claims(path: str) -> bool:
        normalized = path.split("?", 1)[0].rstrip("/")
        return (
            normalized.endswith("/chat/completions")
            or normalized.endswith("/responses")
        )

    def handles(self, path: str) -> bool:
        return self._claims(path)

    def parse_request(
        self, path: str, headers: dict[str, str], body: bytes
    ) -> dict[str, Any]:
        # headers: ata seam 形参;ava parse_openai_request 不消费,占位显式标注。
        _ = headers
        return parse_openai_request(path, body)

    def parse_response(
        self, path: str, headers: dict[str, str], content_type: str, body: bytes
    ) -> dict[str, Any]:
        # path/headers: ata seam 形参;ava parse_openai_response 不消费。
        _ = path, headers
        return parse_openai_response(content_type, body)
```

- [ ] **Step 3: 改 `registered()`(L147-155)把 `_OpenAI` 加进 tuple**

把:

```python
    return (_AnthropicMessages(),)
```

改为:

```python
    return (_AnthropicMessages(), _OpenAI())
```

- [ ] **Step 4: 跑 Task 1 测试确认变绿**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_wire_parse.py::WireParseTest::test_chat_completions_path_dispatches_to_openai -v
```

Expected: **PASS**(`parser.family == "openai"`,`api_family == "openai-chat-completions"`,`system_prompts == ["You are droid."]`,`tool_items[0].name == "Read"`)。

- [ ] **Step 5: 跑全量 wire_parse 测试确认不破坏现有**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_wire_parse.py -v
```

Expected: 全部 6 个测试 PASS(5 个原 + 1 个新)。

- [ ] **Step 6: 跑 protocol_facts 测试确认非重叠断言通过**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_protocol_facts.py -v
```

Expected: 全部 PASS(若测试不存在或不存在非重叠断言,改为跑全量 tests 套件)。

- [ ] **Step 7: 提交**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && git add ata/wire/openai_parser.py ata/wire/protocol_facts.py tests/test_wire_parse.py && git commit -m "feat(wire): port openai_parser from ava; register _OpenAI adapter for /v1/chat/completions and /v1/responses"
```

---

### Task 4: 失败测试——`_OpenAI` 同时吃 `/v1/responses` 路径

**Files:**
- Modify: `repos/ata/tests/test_wire_parse.py`(追加 1 个测试)

**Interfaces:**
- Consumes: `ata.wire.parse_request(path, headers, body)`。
- Produces: 失败输出 `AssertionError`(若只测 chat,无法保证 responses 也路由正确)。

- [ ] **Step 1: 在 `test_chat_completions_path_dispatches_to_openai` 后追加**

```python
RESPONSES_REQ = (
    b'{"model":"o3","stream":false,'
    b'"instructions":"You are codex.",'
    b'"input":[{"role":"user","content":[{"type":"input_text","text":"hi"}]}],'
    b'"tools":[{"type":"function","name":"Bash",'
    b'"description":"run shell","parameters":{"type":"object"}}]}'
)

def test_responses_path_dispatches_to_openai(self):
    s = parse_request("/v1/responses", {}, RESPONSES_REQ)
    self.assertEqual(s["parser"]["family"], "openai")
    self.assertEqual(s["api_family"], "openai-responses")
    self.assertTrue(s["json_valid"])
    self.assertIn("You are codex.", s["system_prompts"])
    self.assertEqual([t["name"] for t in s["tool_items"]], ["Bash"])
```

- [ ] **Step 2: 跑测试确认 PASS(已注册)**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_wire_parse.py::WireParseTest::test_responses_path_dispatches_to_openai -v
```

Expected: **PASS**(Task 3 已注册 `/v1/responses` 路径,本测试是回归保护,不是新功能验证)。

- [ ] **Step 3: 跑全量 wire_parse 测试**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_wire_parse.py -v
```

Expected: 全部 7 个测试 PASS。

- [ ] **Step 4: 提交**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && git add tests/test_wire_parse.py && git commit -m "test(wire): pin /v1/responses dispatch to _OpenAI adapter"
```

---

### Task 5: 失败测试——响应侧 SSE 与 usage 透传

**Files:**
- Modify: `repos/ata/tests/test_wire_parse.py`(追加 2 个测试)

**Interfaces:**
- Consumes: `ata.wire.parse_response(path, headers, content_type, body)`。
- Produces: SSE 累积的 response_text + usage;非 messages 路径也走通。

- [ ] **Step 1: 追加 chat completions SSE 测试**

```python
def test_chat_completions_sse_response_parses(self):
    body = (
        b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"he"}}]}\n\n'
        b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"llo"}}],'
        b'"finish_reason":"stop"}\n\n'
        b'data: [DONE]\n\n'
    )
    s = parse_response("/v1/chat/completions", {}, "text/event-stream", body)
    self.assertEqual(s["response_id"], "chatcmpl-1")
    self.assertEqual(s["response_text"], "hello")
    self.assertEqual(s["finish_reasons"], ["stop"])

def test_chat_completions_json_response_usage(self):
    body = (
        b'{"id":"chatcmpl-2","choices":[{"message":{"role":"assistant","content":"ok"},'
        b'"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":12,"completion_tokens":4}}'
    )
    s = parse_response("/v1/chat/completions", {}, "application/json", body)
    self.assertEqual(s["response_id"], "chatcmpl-2")
    self.assertEqual(s["response_text"], "ok")
    self.assertEqual(s["usage"]["prompt_tokens"], 12)
    self.assertEqual(s["usage"]["completion_tokens"], 4)
```

- [ ] **Step 2: 跑新增 2 个测试确认 PASS**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_wire_parse.py::WireParseTest::test_chat_completions_sse_response_parses tests/test_wire_parse.py::WireParseTest::test_chat_completions_json_response_usage -v
```

Expected: 2 个 PASS。

- [ ] **Step 3: 跑全量 wire_parse**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_wire_parse.py -v
```

Expected: 9 个测试全 PASS。

- [ ] **Step 4: 提交**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && git add tests/test_wire_parse.py && git commit -m "test(wire): pin chat completions SSE and JSON response shapes"
```

---

### Task 6: e2e 验证——droid 走 17878 后事件流有 `system.upserted`

**Files:**
- 可能 Modify: `repos/ata/ata/plugins/capture.py`(若 droid session id 字段回填到 `_SESSION_HEADERS` 或 `_BODY_SESSION_FIELDS`)

**Interfaces:**
- Consumes: 真实 droid 流量(用户用 droid 发起一次对话)、`ata read events SID` CLI。
- Produces: 新 droid session 的 events 流含 `system.upserted` + `tool.upserted`(若 droid 声明工具)+ `turn.ended`。

- [ ] **Step 1: 重启 ATA 服务(代码改动影响 serve 进程)**

```bash
launchctl kickstart -k gui/$(id -u)/com.ata.atatrace
sleep 2
curl -s http://127.0.0.1:17877/api/health
```

Expected: `{"ok": true}`(服务重启完毕,pick up 新 protocol_facts)。

- [ ] **Step 2: 起新 droid 会话**

在 droid CLI 中发任意一句"hello"——用 `~/.factory/settings.json` 已配的 `customModels[].baseUrl=http://127.0.0.1:17878/v1` 模型;droid 会发请求到 17878,代理壳转发到上游 + 写账本。

- [ ] **Step 3: 查最新一条 droid session id**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m ata read sessions --agent droid --limit 1
```

Expected: JSON 数组,`id` 字段是新 droid sid。

- [ ] **Step 4: 读 events 验证 `system.upserted`**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m ata read events <NEW_SID> --limit 20
```

Expected: events 列表里至少一条 `type=="system.upserted"`,payload 含 `prompt_text` 与 `tools_catalog`。

- [ ] **Step 5: 若 step 4 失败,定位 droid session id 字段**

观察 `~/.ata/atatrace.log` 是否有 `capture: no host session id; dropping` 错误:

```bash
grep "capture" ~/.ata/atatrace.log | tail -20
```

若有,在 `repos/ata/ata/plugins/capture.py` 的 `_SESSION_HEADERS` 或 `_BODY_SESSION_FIELDS` 加具体提取规则(头名或 body 字段路径从真实请求体读出),**再**走 step 2-4 重试。

- [ ] **Step 6: 若 step 5 改了 capture.py,跑 capture 测试 + 提交**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m pytest tests/test_capture.py -v
git add ata/plugins/capture.py tests/test_capture.py
git commit -m "feat(capture): droid session id field discovered in real traffic"
```

(若未改 capture.py,跳过此步)

- [ ] **Step 7: 验证 `turn.ended` 出现**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m ata read events <NEW_SID> --limit 50
```

Expected: events 列表含 `type=="turn.ended"`,payload 含 `usage` 字段(input/output tokens)。

- [ ] **Step 8: 跑全量回归**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && make test
```

Expected: 全部 210+ tests PASS(含 capture / wire_parse / storage_headers)。

---

### Task 7: ADR-0001 更新——「OpenAI 族解析暂缓」作废

**Files:**
- Modify: `repos/ata/docs/adr/0001-proxy-capture-channel.md`(L36 段落标作废 + 指向本计划)

**Interfaces:**
- Consumes: ADR-0001 当前文本。
- Produces: 作废标注 + 链接到本计划,审计者能看到裁决从"暂缓"到"已落地"的日期。

- [ ] **Step 1: 改 L36 段**

把:

```
- OpenAI 族解析（codex 可用）暂缓，ata/wire 的注册表 seam 已预留。
```

改为:

```
- ~~OpenAI 族解析（codex 可用）暂缓，ata/wire 的注册表 seam 已预留。~~
  **2026-08-27 已落地**——见 `docs/superpowers/plans/2026-08-27-openai-parser-port.md`,
  `ata/wire/openai_parser.py` 1:1 移植自 ava 1095 行,
  `protocol_facts._OpenAI` 注册到 `/v1/chat/completions` 与 `/v1/responses`。
  droid 走 17878 代理能产出 `system.upserted` / `turn.ended`。
  codex 走 Responses API 解析已就位,只需 codex 端把 `OPENAI_BASE_URL` 切到 17878
  (用户已说明先不做,本计划不动 codex 配置)。
```

- [ ] **Step 2: 提交**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && git add docs/adr/0001-proxy-capture-channel.md && git commit -m "docs(adr): mark OpenAI parser deferral as superseded by 2026-08-27 port"
```

---

### Task 8: 主仓 bump ata 子模块到新 commit

**Files:**
- Modify: 主仓 `repos/ata` 子模块引用(commit hash 由 Task 3/4/5/6/7 的 commit 链末位决定)

**Interfaces:**
- Consumes: `repos/ata` 末位 commit。
- Produces: 主仓 HEAD 指向新 ata commit,所有依赖方下次 `git submodule update` 拿到。

- [ ] **Step 1: 查 ata 末位 commit**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && git log --oneline -1
```

记录 commit hash(短 hash 7 位即可)。

- [ ] **Step 2: 回到主仓 bump 子模块**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence && git add repos/ata && git commit -m "chore(submodule): bump repos/ata to openai_parser port + droid 17878 system补货"
```

(commit message 模板与近期 `49f6a356 chore(submodule): bump repos/ata to ...` 一致)

- [ ] **Step 3: 跑 ATA 服务健康检查 + 一次 smoke**

```bash
curl -s http://127.0.0.1:17877/api/health
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata && python -m ata read sessions --limit 3
```

Expected: 健康 OK,sessions 列表含 droid 新 session(由 Task 6 创建)。

---

## Self-Review

### 1. Spec 覆盖
- ✅ ava openai_parser 1:1 移植 — Task 2。
- ✅ protocol_facts 注册 _OpenAI adapter — Task 3。
- ✅ 两条路径(chat + responses)都被覆盖 — Task 1 / Task 4。
- ✅ SSE 与 JSON 响应回归 — Task 5。
- ✅ e2e 验证 droid 17878 — Task 6。
- ✅ ADR 更新 — Task 7。
- ✅ 主仓 bump — Task 8。
- ✅ droid session id 字段回填 — Task 6 step 5 兜底(可选)。

### 2. Placeholder 扫描
- 无 "TBD" / "TODO" / "implement later" / "similar to Task N" 占位。
- Task 6 step 5 故意写成"读真实流量",而非"TBD"——它有明确兜底动作(grep atatrace.log + 改 capture.py)。

### 3. 类型一致性
- `protocol_facts._OpenAI.handles/parse_request/parse_response` 与 `_AnthropicMessages` 同构(`ProtocolParser` Protocol 的 3 个方法 + 3 个 class 字段 family/provider/api_families)。
- `parse_openai_request(path, body)` 与 ava 1:1;`parse_openai_response(content_type, body)` 与 ava 1:1。
- 消费方 `capture.py:164-165` 读 `req.get("system_prompts")` 与 `req.get("tool_items")` —— ava parser 已返回同名字段,契约一致。

### 4. 风险
- **大文件风险**: `openai_parser.py` 1095 行,单文件略超 ata 现有单文件 437 行上限。但拆多文件需要 1095 行行号映射与共享辅助函数的二次 import——YAGNI 优先。若 reviewer 拒绝,可拆为 `openai_chat_parser.py` + `openai_responses_parser.py` + `_openai_shared.py`。
- **droid session id 未知**: 真实流量字段名待 Task 6 跑出来;若字段不在常见位(`metadata.session_id` / `X-Droid-Session-Id`),可能要多花 5-10 分钟反代 droid UI 找具体路径。计划已把 grep atatrace.log 作为 step 5 兜底。

---

## Execution Handoff

**Plan complete and saved to `repos/ata/docs/superpowers/plans/2026-08-27-openai-parser-port.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - 调度 subagent 逐 Task 实施,Task 间有 review gate,迭代快。

**2. Inline Execution** - 在本会话顺序执行 Task,批量推进 + checkpoint 回顾。

**走哪条?**
