# Codex Proxy Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Codex 的 OpenAI Responses 代理流量经现有 capture seam 进入 ATA 账本，正确记录 assistant、tool、usage，并提供可复现的 Codex 代理启动方式。

**Architecture:** 保留 `ata/wire/` 的 Anthropic / OpenAI parser adapter 和 `plugins/capture.py` 的单一外部 interface，不引入第二套代理、第二个 writer 或新的投影归并层。在 capture implementation 内增加最小的协议摘要归一化，把 OpenAI Responses 的 `assistant_text`、`message_items`、`function_call_output` 和 usage 字段翻译成已有 canonical event。这个 seam 让 capture module 获得足够的 depth：协议知识集中在一个地方，调用方获得 leverage，维护和测试保有 locality。代理启动层增加 Codex profile，但 session identity 只使用 wire 中实际观察到的稳定字段；没有稳定字段时保留显式 wire-only 虚拟 session，不猜测合并第一方 rollout。

**Tech Stack:** Python 3 标准库、`http.server` / `http.client`、SQLite Ledger、`unittest`、现有 OpenAI Responses parser。

**Spec:** `docs/features/proxy-capture-channel.md`、`docs/adr/0001-proxy-capture-channel.md`、`CONTEXT.md`。

## Global Constraints

- 生产代码只在 `repos/ata/` 独立仓库内修改；父仓库只在需要时记录新的 submodule gitlink。
- 写入只经 `Ledger.append/append_many`；任何地方不得 UPDATE `events` 表，保持单一 writer。
- 不引入第三方依赖；复用已有 `ata/wire/openai_parser.py`、`ata/plugins/common.py`、`ata/capture_proxy.py`。
- 代理采集失败不得影响被代理请求；翻译或写账本异常继续吞掉并打印，响应仍按现有 relay 行为返回。
- 认证头（`authorization` / `x-api-key` / `cookie`）只透传给上游，永不进入账本或测试 fixture；测试只使用显式假值并断言不落档。
- 不修改 canonical event schema、`ALLOWED_TYPES`、`ALLOWED_AGENTS`、projection 或前端；Codex 所需事件类型已经存在。
- Codex capture 的外部 interface 保持 `translate_capture(rec, state) -> list[dict]`；新增逻辑放在 implementation 内部，调用方继续只面对 canonical event。
- `metadata.session_id`、已声明的 Codex 业务头或 caller 注入的 session id 才能用于 merge-on-write；没有稳定身份时只使用现有虚拟 sid 兜底，不把它写成第一方 rollout session。
- 生产代码改动完成后必须运行 `make test`、执行 `./scripts/install-service.sh restart`，并用 `curl -s http://127.0.0.1:17877/api/health` 确认常驻服务恢复。
- 测试使用 `unittest`；每个生产改动任务都先写失败测试，再实现最小改动，再运行该任务测试。
- 注释只记录代码本身读不出的外部约束或协议事实，不写阶段性状态、临时计划或未来重构口号。

## File Structure

### Modify

- `ata/plugins/capture.py`：在现有 capture implementation 内归一化 OpenAI usage、assistant 文本与 Responses 工具结果；不改变 `translate_capture` 的外部 interface。
- `ata/__main__.py`：允许 `--proxy-agent codex`，并按 agent 选择默认 upstream；显式 `--proxy-upstream` 继续优先。
- `scripts/serve-dev.sh`：透传 `ATA_PROXY_AGENT`，使开发启动方式能复现 Claude 或 Codex profile。
- `tests/test_capture.py`：锁定 Codex Responses 的 assistant、usage、tool start/end 行为。
- `tests/test_capture_proxy.py`：锁定 Codex 真实代理壳、session id body 恢复、认证头透传但不落账本、无身份时虚拟 sid 行为。
- `docs/features/proxy-capture-channel.md`：补充 Codex profile、已覆盖的 OpenAI 事实与 wire-only identity 限制。
- `docs/adr/0001-proxy-capture-channel.md`：追加 Codex capture 已完成的裁决和 session identity 未猜测的边界。

### Create

- `tests/test_cli_proxy.py`：用纯函数测试锁定 Claude / Codex 默认 upstream 及显式 upstream 覆盖；不启动 HTTP server。

### Do not modify

- `ata/wire/openai_parser.py`：解析器已经提供 `assistant_text`、`response_tool_calls`、`message_items`、`usage`，本计划只修它的下游消费者。
- `ata/wire/protocol_facts.py`：OpenAI adapter 已注册并覆盖 `/v1/chat/completions` 与 `/v1/responses`。
- `ata/capture_proxy.py`：现有 relay、hop-by-hop 过滤和虚拟 sid 兜底已经可承载 Codex；由 e2e 测试验证，不复制其实现。
- `ata/plugins/codex.py`：Codex rollout adapter 已覆盖第一方文件 tail，本计划不把 proxy 事实混入 rollout 生命周期。
- `ata/schema.py`、`ata/project.py`、`webapp/`：canonical event 与投影无需为 Codex 另开路径。

---

### Task 1: 完成 Codex Responses capture 翻译

**Files:**

- Modify: `ata/plugins/capture.py:223-409`
- Test: `tests/test_capture.py`

**Interfaces:**

- Consumes: `ata.wire.parse_request(path, headers, body) -> dict` 与 `ata.wire.parse_response(path, headers, content_type, body) -> dict`。
- Produces: 保持 `translate_capture(rec, state) -> list[dict]` 不变；新增私有读取器 `_capture_usage(raw) -> dict | None`、`_assistant_parts(resp) -> tuple[str, str | None]`、`_request_tool_results(req) -> list[tuple[str, str]]`。
- Canonical output: `message.upserted` 的 assistant payload 使用 parser 摘要中的 assistant 文本，`tool.upserted` 的 end 行使用 Responses `call_id` 和 output，`turn.ended` 与 assistant message 使用同一份归一化 usage。
- Depth / locality / leverage: 外部 interface 仍只有一个 capture translation seam；OpenAI 与 Anthropic 的差异留在 implementation，调用方不再学习两套 wire 形状。

- [ ] **Step 1: 在 `tests/test_capture.py` 追加失败测试**

在文件末尾、`if __name__ == "__main__":` 之前加入以下完整测试类：

```python
class CodexResponsesCaptureTest(unittest.TestCase):
    def _record(self, request, response, sid="codex-wire-1"):
        return {
            "agent_id": "codex",
            "path": "/v1/responses",
            "request_headers": {},
            "request_body": json.dumps(request).encode(),
            "response_content_type": "application/json",
            "response_body": json.dumps(response).encode(),
            "started_at_ms": 1000,
            "completed_at_ms": 2000,
            "session_id": sid,
        }

    def _request(self, input_items):
        return {
            "model": "gpt-5",
            "instructions": "You are Codex.",
            "metadata": {"session_id": "codex-wire-1"},
            "input": input_items,
            "tools": [{
                "type": "function",
                "name": "Read",
                "description": "read a file",
                "parameters": {"type": "object"},
            }],
        }

    def _response(self, response_id="resp-codex-1"):
        return {
            "id": response_id,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{
                        "type": "output_text",
                        "text": "I will read it.",
                    }],
                },
                {
                    "type": "function_call",
                    "id": "fc-codex-1",
                    "call_id": "call-codex-1",
                    "name": "Read",
                    "arguments": '{"path":"README.md"}',
                },
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
        }

    def test_responses_summary_emits_assistant_usage_and_tool_start(self):
        from ata.plugins.capture import translate_capture

        events = translate_capture(
            self._record(
                self._request([{
                    "role": "user",
                    "content": [{"type": "input_text", "text": "read README"}],
                }]),
                self._response(),
            ),
            {"session_id": "codex-wire-1"},
        )
        assistant = next(
            event for event in events
            if event["type"] == "message.upserted"
            and event["payload"]["role"] == "assistant"
        )
        self.assertEqual(assistant["payload"]["text"], "I will read it.")
        self.assertEqual(assistant["payload"]["output_text"], "I will read it.")
        self.assertEqual(assistant["payload"]["usage"]["input"], 100)
        self.assertEqual(assistant["payload"]["usage"]["output"], 20)
        self.assertEqual(assistant["payload"]["usage"]["total_tokens"], 120)

        started = next(
            event for event in events
            if event["type"] == "tool.upserted"
            and event["id"].endswith(":start")
        )
        self.assertEqual(started["payload"]["tool_call_id"], "call-codex-1")
        self.assertEqual(started["payload"]["name"], "Read")
        self.assertEqual(started["payload"]["payload"], {"path": "README.md"})

    def test_responses_function_call_output_emits_tool_end(self):
        from ata.plugins.capture import translate_capture

        state = {"session_id": "codex-wire-1"}
        first_input = [{
            "role": "user",
            "content": [{"type": "input_text", "text": "read README"}],
        }]
        translate_capture(
            self._record(self._request(first_input), self._response()), state
        )

        second_input = [
            *first_input,
            {
                "type": "function_call_output",
                "call_id": "call-codex-1",
                "output": "README contents",
            },
        ]
        events = translate_capture(
            self._record(
                self._request(second_input),
                self._response("resp-codex-2"),
            ),
            state,
        )
        ended = next(
            event for event in events
            if event["type"] == "tool.upserted"
            and event["id"].endswith(":end")
        )
        self.assertEqual(ended["payload"]["tool_call_id"], "call-codex-1")
        self.assertEqual(ended["payload"]["status"], "completed")
        self.assertEqual(ended["payload"]["result"], "README contents")

    def test_chat_completion_usage_aliases_are_reported(self):
        from ata.plugins.capture import translate_capture

        record = self._record(
            {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
            },
            {
                "id": "chatcmpl-codex-1",
                "choices": [{
                    "message": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 4,
                    "total_tokens": 16,
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
            },
            sid="codex-chat-1",
        )
        events = translate_capture(record, {"session_id": "codex-chat-1"})
        ended = next(event for event in events if event["type"] == "turn.ended")
        self.assertEqual(ended["payload"]["usage"], {
            "status": "reported",
            "input": 12,
            "output": 4,
            "cache_read": 3,
            "cache_write": 0,
            "total_tokens": 16,
            "cost": None,
        })
```

- [ ] **Step 2: 运行失败测试确认当前缺口**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
python3 -m unittest tests.test_capture.CodexResponsesCaptureTest -v
```

预期：失败至少包含以下两类现象：assistant 的 `text` 为空、第二次 Responses 请求没有 `tool.upserted` end 行；Chat Completions usage 也不能从 `prompt_tokens` / `completion_tokens` 得到 reported usage。

- [ ] **Step 3: 在 `ata/plugins/capture.py` 增加最小归一化读取器**

在 `_system_hash` 后、`translate_capture` 前加入以下 implementation。它只把协议差异收口在 capture module，不改 `openai_parser` 或 canonical schema：

```python
def _nonnegative_int(value):
    return value if type(value) is int and value >= 0 else 0


def _capture_usage(raw):
    if not isinstance(raw, dict):
        return None

    inp = _nonnegative_int(raw.get("input_tokens"))
    if not inp:
        inp = _nonnegative_int(raw.get("prompt_tokens"))
    outp = _nonnegative_int(raw.get("output_tokens"))
    if not outp:
        outp = _nonnegative_int(raw.get("completion_tokens"))

    cache_read = _nonnegative_int(raw.get("cache_read_input_tokens"))
    if not cache_read:
        cache_read = _nonnegative_int(raw.get("cached_input_tokens"))
    for key in ("input_tokens_details", "prompt_tokens_details"):
        details = raw.get(key)
        if not cache_read and isinstance(details, dict):
            cache_read = _nonnegative_int(details.get("cached_tokens"))

    cache_write = _nonnegative_int(raw.get("cache_creation_input_tokens"))
    if not cache_write:
        cache_write = _nonnegative_int(raw.get("cache_write_input_tokens"))

    if not any((inp, outp, cache_read, cache_write)):
        return None

    total = _nonnegative_int(raw.get("total_tokens"))
    if not total:
        total = inp + outp + cache_read + cache_write
    return usage_from_counts(inp, outp, cache_read, cache_write, total_tokens=total)


def _assistant_parts(resp):
    text_parts = []
    thinking_parts = []
    blocks = resp.get("response_blocks") or []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
        elif block.get("type") == "thinking" and isinstance(block.get("thinking"), str):
            thinking_parts.append(block["thinking"])

    text = "\n".join(text_parts)
    if not text:
        for key in ("assistant_text", "response_text"):
            value = resp.get(key)
            if isinstance(value, str):
                text = value
                break
    thinking = "\n".join(thinking_parts) or None
    return text, thinking


def _capture_result_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            item.get("text", "")
            for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""


def _request_tool_results(req):
    results = []

    # OpenAI Chat Completions and Responses are represented by message_items;
    # both use role=tool and expose the pairing id in one of these two fields.
    for item in req.get("message_items") or []:
        if not isinstance(item, dict) or item.get("role") != "tool":
            continue
        cid = item.get("tool_call_id") or item.get("call_id")
        if isinstance(cid, str) and cid:
            results.append((cid, item.get("text") or ""))

    # Anthropic keeps tool_result inside a role=user content block; this is the
    # only request shape not represented as role=tool by the shared summary.
    for message in req.get("messages") or []:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            cid = block.get("tool_use_id")
            if isinstance(cid, str) and cid:
                results.append((cid, _capture_result_text(block.get("content"))))
    return results
```

然后在 `_translate` 中做三处替换：

1. 将现有的 `usage` 四字段读取替换为：

```python
    usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
    normalized_usage = _capture_usage(usage)
```

2. 将 assistant message 构造前的 `response_blocks` 手工循环替换为：

```python
        text_joined, thinking_joined = _assistant_parts(resp)
```

并把 assistant payload 的 `usage` 改为 `normalized_usage`、`output_text` 改为 `text_joined or None`、`thinking` 改为 `thinking_joined`；`turn.ended` 的发送条件改为 `if normalized_usage and turn >= 1:`，payload 直接使用 `{"usage": normalized_usage}`。

3. 将从 `req.get("messages")` 扫描 `tool_result` 的整段替换为：

```python
    for cid, res_text in _request_tool_results(req):
        if cid not in tools_state:
            continue
        prev = tools_state.pop(cid)
        out.append(envelope(
            agent_id=agent_id,
            session_id=sid,
            type_="tool.upserted",
            payload=tool_end_payload(prev, cid, response_id, res_text, completed),
            observed_turn_ordinal=turn,
            ts=ts,
            eid=f"{sid}:tool:{cid}:end",
        ))
```

保留 start 行的 `response_tool_calls` 路径；它已经用 `call_id` 建立 `tools_state`，不新增另一份工具状态。

- [ ] **Step 4: 运行任务测试与既有相关测试**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
python3 -m unittest tests.test_capture.CodexResponsesCaptureTest -v
python3 -m unittest tests.test_capture tests.test_codex tests.test_wire_parse -v
```

预期：新测试与既有 62 个纯 capture / Codex / wire 测试全部 PASS；Claude 的 Anthropic `tool_result`、全 0 usage 和 CONTEXT 过滤测试不改变行为。

- [ ] **Step 5: 提交 capture 翻译改动**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
git add ata/plugins/capture.py tests/test_capture.py
git commit -m "feat(capture): translate Codex Responses summaries into canonical events"
```

---

### Task 2: 增加 Codex 代理启动 profile

**Files:**

- Modify: `ata/__main__.py:55-102`
- Modify: `scripts/serve-dev.sh:8-15`
- Create: `tests/test_cli_proxy.py`

**Interfaces:**

- Consumes: CLI 的 `--proxy-agent`、`--proxy-upstream` 与 `start_capture_proxy(host, port, upstream, agent_id, ingest)`。
- Produces: `resolve_proxy_upstream(agent_id: str, explicit: str | None) -> str`；Claude 默认 `https://api.anthropic.com`，Codex 默认 `https://api.openai.com`，显式 upstream 永远优先。
- Existing relay interface remains unchanged; one ATA process continues to serve one selected proxy profile. Concurrent Claude + Codex requires two explicitly configured proxy processes and is outside this plan.
- Depth / locality / leverage: profile 只收启动选择，不复制 relay implementation；agent 与 upstream 的配置 locality 集中，现有 relay 获得 leverage。

- [ ] **Step 1: 创建失败的纯配置测试**

创建 `tests/test_cli_proxy.py`：

```python
import unittest

from ata.__main__ import resolve_proxy_upstream


class ProxyUpstreamTest(unittest.TestCase):
    def test_claude_default_upstream(self):
        self.assertEqual(
            resolve_proxy_upstream("claude", None),
            "https://api.anthropic.com",
        )

    def test_codex_default_upstream(self):
        self.assertEqual(
            resolve_proxy_upstream("codex", None),
            "https://api.openai.com",
        )

    def test_explicit_upstream_wins(self):
        self.assertEqual(
            resolve_proxy_upstream("codex", "http://127.0.0.1:9000"),
            "http://127.0.0.1:9000",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认当前 CLI 没有 profile resolver**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
python3 -m unittest tests.test_cli_proxy -v
```

预期：FAIL，当前 `ata.__main__` 没有 `resolve_proxy_upstream`，且当前 argparse 只允许 `claude`。

- [ ] **Step 3: 实现最小 profile 选择**

在 `ata/__main__.py` 的 import 后加入：

```python
_PROXY_UPSTREAMS = {
    "claude": "https://api.anthropic.com",
    "codex": "https://api.openai.com",
}


def resolve_proxy_upstream(agent_id, explicit):
    return explicit or _PROXY_UPSTREAMS[agent_id]
```

把现有参数：

```python
    p.add_argument("--proxy-upstream", default="https://api.anthropic.com")
    p.add_argument("--proxy-agent", choices=["claude"], default="claude")
```

替换为：

```python
    p.add_argument("--proxy-upstream", default=None)
    p.add_argument(
        "--proxy-agent",
        choices=tuple(_PROXY_UPSTREAMS),
        default="claude",
    )
```

再把启动代理的调用由：

```python
        proxy_httpd = start_capture_proxy(
            "127.0.0.1", args.proxy_port, args.proxy_upstream, args.proxy_agent,
            lambda rec: ingest_capture(led, rec))
```

替换为：

```python
        proxy_httpd = start_capture_proxy(
            "127.0.0.1",
            args.proxy_port,
            resolve_proxy_upstream(args.proxy_agent, args.proxy_upstream),
            args.proxy_agent,
            lambda rec: ingest_capture(led, rec),
        )
```

在 `scripts/serve-dev.sh` 把现有 proxy 参数段：

```bash
# 代理采集通道：默认开 17878（agent 的 API base 指过来就补采）；设 ATA_PROXY_PORT=0 关闭
PROXY_PORT="${ATA_PROXY_PORT:-17878}"
PROXY_ARGS=(--proxy-port "$PROXY_PORT")
[ -n "${ATA_PROXY_UPSTREAM:-}" ] && PROXY_ARGS+=(--proxy-upstream "$ATA_PROXY_UPSTREAM")
```

替换为：

```bash
# 代理采集通道：默认开 17878；设 ATA_PROXY_PORT=0 关闭。
PROXY_PORT="${ATA_PROXY_PORT:-17878}"
PROXY_AGENT="${ATA_PROXY_AGENT:-claude}"
PROXY_ARGS=(--proxy-port "$PROXY_PORT" --proxy-agent "$PROXY_AGENT")
[ -n "${ATA_PROXY_UPSTREAM:-}" ] && PROXY_ARGS+=(--proxy-upstream "$ATA_PROXY_UPSTREAM")
```

- [ ] **Step 4: 运行配置与静态 CLI 检查**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
python3 -m unittest tests.test_cli_proxy -v
python3 -m ata --help
```

预期：3 个配置测试 PASS；帮助输出包含 `--proxy-agent {claude,codex}`。不启动真实服务，不触发端口绑定。

- [ ] **Step 5: 提交 Codex profile 改动**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
git add ata/__main__.py scripts/serve-dev.sh tests/test_cli_proxy.py
git commit -m "feat(proxy): add Codex capture profile and OpenAI upstream default"
```

---

### Task 3: 用代理级 e2e 锁定 Codex identity 与事件闭环

**Files:**

- Modify: `tests/test_capture_proxy.py`

**Interfaces:**

- Consumes: `start_capture_proxy("127.0.0.1", 0, upstream, "codex", ingest)`、现有假上游和临时 `Ledger`。
- Produces: 代理请求 `/v1/responses` 时，body 内有 `metadata.session_id` 就把事件写入该真实 session；没有稳定 session id 时，使用已有 `codex-wire-*` 虚拟 sid，并明确它不是 rollout session 合并结果。
- Depth / locality / leverage: 测试穿过代理的外部 seam，验证 relay、capture adapter 与 Ledger 的组合；身份事实集中在 resolve session seam，避免 projection 重新猜测。

- [ ] **Step 1: 在代理测试中加入 Codex Responses 假上游与失败 e2e**

在 `tests/test_capture_proxy.py` 顶部 `UPSTREAM_RESP` 后加入：

```python
CODEX_UPSTREAM_RESP = {
    "id": "resp-proxy-codex-1",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "proxy answer"}],
        },
        {
            "type": "function_call",
            "id": "fc-proxy-codex-1",
            "call_id": "call-proxy-codex-1",
            "name": "Read",
            "arguments": '{"path":"README.md"}',
        },
    ],
    "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
}
```

在文件末尾新增以下测试类：

```python
class CodexCaptureProxyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name))
        self.upstream = make_upstream([CODEX_UPSTREAM_RESP])
        self.upstream_port = self.upstream.server_address[1]
        threading.Thread(
            target=self.upstream.serve_forever,
            daemon=True,
        ).start()
        with capture_proxy._virtual_sid_lock:
            capture_proxy._virtual_sid_cache.clear()

        from ata.plugins.capture import ingest_capture

        self.proxy = start_capture_proxy(
            "127.0.0.1",
            0,
            f"http://127.0.0.1:{self.upstream_port}",
            "codex",
            lambda record: ingest_capture(self.ledger, record),
        )
        self.proxy_thread = threading.Thread(
            target=self.proxy.serve_forever,
            daemon=True,
        )
        self.proxy_thread.start()

    def tearDown(self):
        self.proxy.shutdown()
        self.proxy.server_close()
        self.proxy_thread.join(timeout=2)
        self.upstream.shutdown()
        self.upstream.server_close()
        self.ledger.close()
        self.tmp.cleanup()
        with capture_proxy._virtual_sid_lock:
            capture_proxy._virtual_sid_cache.clear()

    def _post(self, body):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.proxy.server_address[1]}/v1/responses",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-secret",
            },
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            response.read()

    def _wait_records(self, sid, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            records = self.ledger.read(sid)
            if records:
                return records
            time.sleep(0.05)
        return []

    def test_codex_responses_lands_in_body_session_and_completes_tool(self):
        request = {
            "model": "gpt-5",
            "instructions": "You are Codex.",
            "metadata": {"session_id": "codex-proxy-session"},
            "input": [{
                "role": "user",
                "content": [{"type": "input_text", "text": "read README"}],
            }],
        }
        self._post(request)
        first = self._wait_records("codex-proxy-session")
        self.assertTrue(first)
        first_types = [record["event"]["type"] for record in first]
        self.assertIn("system.upserted", first_types)
        self.assertIn("message.upserted", first_types)
        self.assertIn("turn.ended", first_types)
        assistant = next(
            record["event"] for record in first
            if record["event"]["type"] == "message.upserted"
            and record["event"]["payload"]["role"] == "assistant"
        )
        self.assertEqual(assistant["payload"]["text"], "proxy answer")

        self._post({
            **request,
            "input": [
                *request["input"],
                {
                    "type": "function_call_output",
                    "call_id": "call-proxy-codex-1",
                    "output": "README contents",
                },
            ],
        })
        records = self._wait_records("codex-proxy-session")
        ended = [
            record["event"] for record in records
            if record["event"]["type"] == "tool.upserted"
            and record["event"]["id"].endswith(":end")
        ]
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0]["payload"]["result"], "README contents")
        self.assertNotIn("test-secret", json.dumps(records))

    def test_codex_without_body_session_uses_explicit_wire_only_sid(self):
        self._post({
            "model": "gpt-5",
            "input": [{
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            }],
        })
        deadline = time.time() + 5
        sessions = []
        while time.time() < deadline:
            sessions = self.ledger.sessions()
            if sessions:
                break
            time.sleep(0.05)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0]["id"].startswith("codex-wire-"))
```

同时在 `NeedsVirtualSidTest` 加入：

```python
    def test_backend_api_codex_responses_triggers(self):
        self.assertTrue(
            capture_proxy._needs_virtual_sid(
                "/backend-api/codex/responses"
            )
        )
```

- [ ] **Step 2: 运行新增代理测试确认它们先暴露当前行为**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
python3 -m unittest tests.test_capture_proxy.CodexCaptureProxyTest -v
```

预期：在允许本地 TCP bind 的环境中，第一条测试先因 assistant / tool end 缺失而失败；若当前环境报 `PermissionError: [Errno 1] Operation not permitted`，这是测试环境禁止绑定 `127.0.0.1:0`，不是断言结果，需保留该输出并在有本地端口权限的环境重跑。

- [ ] **Step 3: 运行代理 e2e 与相关纯测试确认闭环**

Task 1 和 Task 2 的生产改动已经提供实现，本步不再增加 production workaround；运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
python3 -m unittest tests.test_capture_proxy tests.test_capture tests.test_cli_proxy -v
```

预期：允许 bind 时全部 PASS；账本 session id 为 `codex-proxy-session` 的测试证明 body identity 走 merge-on-write，缺失 identity 的测试证明虚拟 sid 仍被显式限制为 wire-only。

- [ ] **Step 4: 提交代理 e2e 回归测试**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
git add tests/test_capture_proxy.py
git commit -m "test(proxy): cover Codex Responses capture and session identity"
```

---

### Task 4: 更新代理通道文档与 ADR

**Files:**

- Modify: `README.md` 的“代理采集通道”与支持表
- Modify: `docs/features/proxy-capture-channel.md` 的 OpenAI 限制、启用与 identity 章节
- Modify: `docs/adr/0001-proxy-capture-channel.md`，追加 2026-08-31 Codex activation decision

**Interfaces:**

- Consumes: Task 1 的 canonical event 行为、Task 2 的 CLI profile、Task 3 的真实 session / wire-only e2e 事实。
- Produces: 用户可以只根据 README 启动 Codex proxy；文档明确 Claude 与 Codex 共享 relay implementation、每个进程选择一个 profile、缺失稳定 session id 时不宣称已与 rollout 合并。

- [ ] **Step 1: 在 README 加入 Codex 启用命令**

在代理采集通道示例后加入以下文案：

```markdown
Codex 使用 OpenAI Responses 时：

    python3 -m ata serve --proxy-port 8319 --proxy-agent codex

此时默认上游为 `https://api.openai.com`；如使用兼容网关，显式传入
`--proxy-upstream`。再把 Codex 的 OpenAI base URL 指向
`http://127.0.0.1:8319`。请求体带有 `metadata.session_id` 时，代理事件会
按该值 merge-on-write 到同一 session；没有稳定 session id 时，ATA 只建立
`codex-wire-*` 的 wire-only session，不把它冒充成第一方 rollout session。
Claude 与 Codex 同时采集时，为每个 profile 使用独立 proxy port 和独立
ATA 进程；当前 relay interface 不做多 profile 路由。
```

把支持表中的 Codex 行补成：

```markdown
| Codex | 第一方 rollout / 文件 tail；可选 OpenAI Responses proxy | `originator`；proxy 使用 wire session id | rollout 有 `base_instructions`；proxy 可补完整 tools | reported（rollout 或 proxy usage） |
```

- [ ] **Step 2: 更新 proxy capture feature 文档**

将“OpenAI 族解析暂缓”改为以下事实：

```markdown
| 上游 OpenAI 族 | `wire/openai_parser.py` 已覆盖 `/v1/chat/completions`、`/v1/responses` 及 `/backend-api/codex/responses` 后缀；capture 会消费其 assistant、tool result 与 usage 摘要 |
| Codex session identity | `metadata.session_id` 可直接 merge-on-write；wire 没有稳定 session id 时只落 `codex-wire-*` wire-only session，不做时间窗猜测合并 |
| 单进程 profile | 一个 `serve` 进程的 proxy 使用一个静态 `agent_id` 与 upstream；Claude/Codex 并行采集需独立端口/进程 |
```

并在“启用与排错”表加入：

```markdown
| Codex proxy 启动 | `python3 -m ata serve --proxy-port 8319 --proxy-agent codex` |
| Codex upstream 覆盖 | `--proxy-upstream https://<gateway-host>` |
| Codex session 分裂 | 检查请求体是否有稳定 `metadata.session_id`；没有则预期为 wire-only，不在 projection 层补猜测归并 |
```

- [ ] **Step 3: 在 ADR-0001 追加正式裁决**

在现有 ADR 的最后加入：

```markdown
### Codex capture activation（2026-08-31）

Codex 走 OpenAI Responses 的解析与 capture 消费已经接入既有代理通道：
`openai_parser` 负责 wire 摘要，`plugins/capture.py` 负责把
`assistant_text`、Responses `function_call` / `function_call_output` 与
OpenAI usage 翻译成 canonical event，账本 writer 和 projection 不新增路径。

代理启动用 `--proxy-agent codex` 选择 Codex profile，默认上游为
`https://api.openai.com`，显式 `--proxy-upstream` 优先。一个进程仍只有一个
静态 profile，不引入隐含的多 agent 路由。

身份裁决保持严格：请求体声明的 `metadata.session_id` 才能用于
merge-on-write；缺少稳定字段时继续使用 `codex-wire-*` 作为 wire-only
session。不得根据 client port、时间窗或 rollout 文件名猜测它与第一方
Codex session 相同；除非未来的真实 wire 物证证明稳定 correlation 字段，
才可以单独重开 identity seam。
```

- [ ] **Step 4: 检查文档事实和禁用词**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
rg -n "OpenAI 族解析.*暂缓|codex.*暂未走完整|Codex.*只能.*jsonl|proxy-agent|wire-only|metadata.session_id" README.md docs/features/proxy-capture-channel.md docs/adr/0001-proxy-capture-channel.md
```

预期：旧的“OpenAI 解析暂缓”事实不再作为当前状态出现；新的启用命令、identity 边界和单 profile 限制各至少有一处明确声明。不要删除历史 ADR 叙述，只追加当前裁决，保留决策时间线。

- [ ] **Step 5: 提交文档改动**

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
git add README.md docs/features/proxy-capture-channel.md docs/adr/0001-proxy-capture-channel.md
git commit -m "docs(proxy): document Codex capture profile and wire-only identity"
```

---

### Task 5: 全量验证、常驻服务重启与仓库收口

**Files:**

- Test: `tests/test_capture.py`
- Test: `tests/test_capture_proxy.py`
- Test: `tests/test_cli_proxy.py`
- Test: `tests/test_codex.py`
- Test: `tests/test_wire_parse.py`
- Production verification: `ata/`、`scripts/`、`webapp/` 已修改文件

**Interfaces:**

- Consumes: Tasks 1–4 的 production code、tests、README 与 ADR。
- Produces: Codex proxy 的 acceptance evidence：OpenAI Responses request/response 经 relay 返回后，assistant、tool start/end、usage、system catalog 和 session identity 行为都可验证；Claude 现有代理行为保持不变。

- [ ] **Step 1: 运行纯测试回归**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
python3 -m unittest tests.test_capture tests.test_codex tests.test_wire_parse tests.test_cli_proxy -v
```

预期：所有不需要本地 TCP bind 的测试 PASS；这些测试覆盖 Codex rollout adapter、OpenAI wire parser、capture 翻译和默认 upstream。

- [ ] **Step 2: 运行代理与 HTTP 测试**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
python3 -m unittest tests.test_capture_proxy tests.test_capture_http tests.test_http -v
```

预期：在允许本地临时端口的环境中全部 PASS。如果环境仍返回 `PermissionError: [Errno 1] Operation not permitted`，记录为测试环境限制，不能把它解释为代理断言失败；需在具备本地 TCP bind 权限的主机重新执行这一命令。

- [ ] **Step 3: 运行项目要求的全量测试**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
make test
```

预期：正常主机上全量 PASS；如只剩本机 TCP bind 限制，保留失败测试名称和异常作为验证记录，不修改生产代码绕过沙箱。

- [ ] **Step 4: 重启本机 ATA 常驻服务并检查健康状态**

运行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
./scripts/install-service.sh restart
curl -s http://127.0.0.1:17877/api/health
```

预期：服务由新代码拉起，health endpoint 返回成功 JSON；不把真实 API key、请求正文或用户采集内容写入命令输出、日志或文档。

- [ ] **Step 5: 检查两个仓库的归属并分别提交**

先确认 ATA 子仓库只包含本计划的代码、测试与文档：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence/repos/ata
git status --short
git log --oneline -5
```

如果父知识库需要记录新的 submodule gitlink，在父仓库执行：

```bash
cd /Users/pis/workspace_intelligence/creator-intelligence
git add repos/ata
git commit -m "chore(submodule): bump ata for Codex proxy capture"
```

ATA 子仓库的实现提交与父仓库的 gitlink 提交分开归类；不把 `repos/ata` 的生产源码展开提交到父仓库。

## Self-review

### Spec coverage

- Codex Responses assistant 文本：Task 1 的 `_assistant_parts` 与断言覆盖。
- Responses `function_call` / `function_call_output`：Task 1 的 start/end 测试和 Task 3 代理级回归覆盖。
- Responses / Chat Completions usage：Task 1 的 `_capture_usage` 和 alias 测试覆盖。
- Codex proxy 启动入口：Task 2 的 CLI resolver、argparse choices、dev script 和 Task 4 文档覆盖。
- 认证头透传与不落档：Task 3 的代理 e2e 断言覆盖。
- `metadata.session_id` merge-on-write：Task 3 的真实 session id 断言覆盖。
- 缺失 identity 不猜测合并：Task 3 的虚拟 sid 测试与 Task 4 的 ADR 裁决覆盖。
- Claude 兼容性：Task 1 运行既有 capture 测试，Task 5 运行代理回归和全量测试。
- 常驻服务恢复：Task 5 的 restart + health 检查覆盖。

### Deliberate scope boundary

本计划不实现“根据 client port / 时间窗 / rollout 文件名把 wire-only session 读取侧归并到 Codex rollout session”。现有 `CONTEXT.md` 要求 merge-on-write 且禁止猜测 session identity；在没有新的真实 wire 物证前，扩大 identity adapter 会降低事实强度而不是增加 depth。未来若真实流量证明稳定 correlation 字段，再以独立计划重开 identity seam。

### Placeholder scan

计划中的每个生产步骤都给出具体文件、符号、测试命令和预期结果；没有未定义的后续事项、模糊的邻接任务引用或空泛的错误处理要求。

### Type consistency

- `resolve_proxy_upstream(agent_id, explicit)` 在 Task 2 定义并由 `tests/test_cli_proxy.py` 直接消费。
- `translate_capture(rec, state)` 的外部 interface 在 Task 1 保持不变，Task 3 只经 `ingest_capture` 调用它。
- `_capture_usage`、`_assistant_parts`、`_request_tool_results` 都是 Task 1 内部 implementation helper，不被后续任务作为公共 interface 使用。
