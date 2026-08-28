# 代理采集 user 消息修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修 v2 代理采集在真实 claude 流量下「user 消息没记录到 trace」的 4 个串起来的根因，让 user 消息能正确 emit、turn 1 之后还能 emit、跨进程重启不漏不重。

**Architecture:**
- **emit 路径加 `is_context_text` 过滤**（对齐 `count_real_user_turns` 的口径）：`<system-reminder>` 注入不再被当 user 消息写入。
- **mid 派生走 `message_items[i]["index"]`**：wire 解析给的 `index` 是稳定的全量数组下标，anthropic wire 真实消息没有 `id` 字段；派生从 `f"{sid}:user:"` 空尾巴改成 `f"{sid}:user:{turn}:{index}"`，唯一且不撞 assistant 的 `response_id`。
- **seen key 加 role 前缀**：`f"user:{mid}"` / `f"assistant:{resp_id}"`，避免 user/assistant 偶发 mid 撞车被吞；**seen 改走 `events.dedupe_key` UNIQUE 索引**实现跨进程持久化（`Ledger._dedupe_key` 接受 message.upserted 的 role 命名空间），零新表。
- 旧 sid `e6d514c5-...` 的残留不修（用户确认「让它过去」），新事件按新逻辑。

**Tech Stack:** Python 3 stdlib only；unittest。零新依赖。

**Spec:**
- 上一会话交接:本次 plan 由 debug sid `e6d514c5-c71b-4636-9282-b87173fe3277` 发现 3 个串联根因（emit 不过滤、mid fallback 空尾巴、seen 内存丢），本计划实施全部 4 条修复。
- 母计划: `docs/superpowers/plans/2026-08-26-proxy-capture-channel.md`（代理通道建设）。
- v2 升级: `docs/superpowers/plans/2026-08-27-proxy-message-tool-promotion.md`（代理主发 message/tool，transcript 收窄）——本计划是 v2 落地后第一个修 bug 计划。
- ADR: `docs/adr/0001-proxy-capture-channel.md` 已知限制列表（v2 收尾那个 ADR）——本计划修复「v2 已知限制 #N」中关于 user 消息相关的条目，修复后**更新**那个 ADR 删掉对应限制。

## Global Constraints

- 写入只经 `Ledger.append/append_many`；任何地方不得 UPDATE events 表（单一 writer）。
- `schema.parse_event` 校验规则不动；事件形状必须过它。
- 测试用 unittest：`python3 -m unittest discover -s tests -v`；不引入 pytest。
- 不引入任何第三方依赖。
- 脱敏红线:认证头（authorization / x-api-key / cookie）永不落账本；事件只存提取后的字段（role / message_id / text[:200] / thinking[:200]）。
- 采集失败绝不影响被代理的请求：翻译/写账本抛异常时吞掉、打印、照常返回响应（沿用 `translate_capture` try/except）。
- 展示层（web/webapp/project.py 投影端点）不动。
- 所有提交在 repos/ata 子仓库内做，消息末尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 |
|---|---|
| `ata/plugins/capture.py` | emit user 块加 `is_context_text` 过滤；mid 派生走 `message_items[i].index`；seen 改走 `events.dedupe_key` 持久化；role 命名空间加前缀 |
| `ata/ledger.py` | `_dedupe_key` 接受 message.upserted 的 role 命名空间前缀（user/assistant） |
| `tests/test_capture.py` | 补 4 个回归测试（不塞 id / system-reminder 过滤 / seen role 前缀 / 跨进程 seen 持久化） |
| `docs/adr/0001-proxy-capture-channel.md` | 增补一节「v2 已知限制解除: user 消息正确 emit + seen 跨进程持久化」 |

---

### Task 1: emit 路径加 is_context_text 过滤

**Files:**
- Modify: `ata/plugins/capture.py`（user emit 循环 L209-255）
- Test: `tests/test_capture.py`（追加 1 个新测试）

**Interfaces:**
- Consumes: `ata.project.is_context_text`（存量函数，懒加载避免循环导入，同 `count_real_user_turns`）。
- Produces: 同一 `translate_capture` 接口，行为变更: `role=user` 但 text 是 `<system-reminder>` / harness 注入的上下文文本，**不** emit `message.upserted`；但 `count_real_user_turns` 已经把这些排除，所以 turn 号不受影响。

- [ ] **Step 1: 写失败测试**

在 `tests/test_capture.py` 追加：

```python
class UserContextFilterTest(unittest.TestCase):
    """emit 路径必须跟 count_real_user_turns 同口径过滤 CONTEXT 注入,
    否则 <system-reminder> 会被当 user 消息写入账本,投影层显示错乱。"""

    def _rec(self, messages, sid="ctx-1"):
        return {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": sid},
            "request_body": json.dumps({
                "model": "claude-3-5-sonnet", "messages": messages,
            }).encode(),
            "response_content_type": "application/json",
            "response_body": json.dumps({
                "id": "msg_resp_ctx", "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode(),
            "started_at_ms": 1000, "completed_at_ms": 2000,
        }

    def test_system_reminder_user_not_emitted(self):
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text",
                "text": "<system-reminder>\nctx</system-reminder>"}]},
        ]
        events = translate_capture(self._rec(msgs), {"session_id": "ctx-1"})
        user_upserts = [e for e in events
                        if e["type"] == "message.upserted"
                        and e["payload"].get("role") == "user"]
        self.assertEqual(user_upserts, [])

    def test_real_user_emitted_after_context(self):
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text",
                "text": "<system-reminder>\nctx</system-reminder>"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "ack"}]},
            {"role": "user", "content": [{"type": "text",
                "text": "真 user 问题"}]},
        ]
        events = translate_capture(self._rec(msgs), {"session_id": "ctx-2"})
        user_upserts = [e for e in events
                        if e["type"] == "message.upserted"
                        and e["payload"].get("role") == "user"]
        self.assertEqual(len(user_upserts), 1)
        self.assertEqual(user_upserts[0]["payload"]["text"], "真 user 问题")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_capture.UserContextFilterTest -v`
Expected: 第一个 FAIL（system-reminder 被 emit），第二个 FAIL（真 user 消息里没 emit,或 emit 但跟期望对不上）

- [ ] **Step 3: 最小修复**

在 `ata/plugins/capture.py` L209 之前（user emit 循环开头）加：

```python
    # user messages from request (跟 count_real_user_turns 同口径过滤
    # CONTEXT 注入, 避免 <system-reminder> 被当 user 消息写入)
    from ata.project import is_context_text as _is_ctx
    for m in req.get("messages") or []:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        # 先把 content 拼成 text 串, 跟 count_real_user_turns 一致判断
        content = m.get("content")
        if isinstance(content, str):
            preview_text = content
        elif isinstance(content, list):
            preview_text = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
                and isinstance(b.get("text"), str)
            )
        else:
            preview_text = ""
        if not preview_text or _is_ctx(preview_text):
            continue
```

然后把原 L209-255 循环里的 `content = m.get("content")` 后面那段 `texts` 提取复用同一个 `preview_text`(避免重复 `for b in content` 一遍):

把原 L217-228 的：
```python
        content = m.get("content")
        if isinstance(content, str):
            texts = [content]
            blocks = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            texts, blocks = [], []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                    texts.append(b["text"])
                if isinstance(b, dict):
                    blocks.append(b)
        else:
            texts, blocks = [], []
        text_joined = "\n".join(texts)
```

改为复用 `preview_text`:
```python
        if isinstance(content, str):
            blocks = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            blocks = [b for b in content if isinstance(b, dict)]
        else:
            blocks = []
        text_joined = preview_text
```

> **执行者注意**: 必须在过滤前计算 `preview_text`,这样 `_is_ctx` 才能正确判断;在过滤后才开始用 `blocks` 组装 envelope 字段。

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `python3 -m unittest tests.test_capture -v && python3 -m unittest discover -s tests -v`
Expected: UserContextFilterTest 全 PASS；全量回归 PASS

- [ ] **Step 5: Commit**

```bash
git add ata/plugins/capture.py tests/test_capture.py
git commit -m "fix(capture): emit user 消息时过滤 CONTEXT 注入

跟 count_real_user_turns 同口径调 is_context_text, 避免
<system-reminder> / harness 注入的上下文文本被当 user 消息写入账本,
投影层 user_message 字段显示错乱。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: mid 派生走 message_items[i].index

**Files:**
- Modify: `ata/plugins/capture.py`（user emit 循环里 mid 派生 + assistant emit 循环里 seen key）
- Test: `tests/test_capture.py`（追加 1 个新测试）

**Interfaces:**
- Consumes: `req.get("message_items")`（wire 解析已提供 `index` 字段，`anthropic_parser._message_items` L173-228）。
- Produces: 同一 `translate_capture` 接口，行为变更: user 消息 mid 从 `f"{sid}:user:"`（空尾巴，撞车）改成 `f"{sid}:user:{turn}:{index}"`（turn + 数组下标双键,同 turn 同 index 必然同 mid,跨 turn 不会撞）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_capture.py` 追加：

```python
class UserMidDerivationTest(unittest.TestCase):
    """anthropic wire 真实 user 消息没有 id 字段; 测试必须不手工塞 id,
    派生 mid 必须从 message_items[i].index 拿, 避免 f'{sid}:user:' 空尾巴
    导致所有 user 撞同一 mid 一起被 seen 吞。"""

    def _rec(self, messages, sid="mid-1", resp_id="msg_r"):
        return {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": sid},
            "request_body": json.dumps({
                "model": "claude-3-5-sonnet", "messages": messages,
            }).encode(),
            "response_content_type": "application/json",
            "response_body": json.dumps({
                "id": resp_id, "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode(),
            "started_at_ms": 1000, "completed_at_ms": 2000,
        }

    def test_user_mid_includes_index(self):
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "first"}]},
        ]
        events = translate_capture(
            self._rec(msgs, sid="mid-A", resp_id="r1"),
            {"session_id": "mid-A"})
        user_ev = next(e for e in events
                       if e["type"] == "message.upserted"
                       and e["payload"].get("role") == "user")
        # mid 必须包含 index=0, 不能是空尾巴
        self.assertIn("mid-A:user:1:0", user_ev["payload"]["message_id"])

    def test_two_user_messages_get_different_mids(self):
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "first"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "ack"}]},
            {"role": "user", "content": [{"type": "text", "text": "second"}]},
        ]
        events = translate_capture(
            self._rec(msgs, sid="mid-B", resp_id="r2"),
            {"session_id": "mid-B"})
        user_evs = [e for e in events
                    if e["type"] == "message.upserted"
                    and e["payload"].get("role") == "user"]
        mids = [e["payload"]["message_id"] for e in user_evs]
        self.assertEqual(len(mids), 2)
        # 不撞同 mid
        self.assertNotEqual(mids[0], mids[1])
        # 都含 :user:N:index 形状
        for m in mids:
            self.assertRegex(m, r"mid-B:user:\d+:\d+")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_capture.UserMidDerivationTest -v`
Expected: 第一个 FAIL（mid 形如 `mid-A:user:`，缺 `:1:0`）；第二个 FAIL（两个 user 同 mid）

- [ ] **Step 3: 最小修复**

在 `ata/plugins/capture.py` user emit 循环里，把：

```python
        mid = str(m.get("id") or f"{sid}:user:{m.get('index', '')}")
```

改为：

```python
        # wire 真实 user 消息没有 id 字段; 从 message_items[i].index 派生
        # mid。 turn + index 双键保证唯一性, 跨 turn 也不撞。
        raw_mid = m.get("id")
        if not raw_mid:
            # req.get("message_items") 是按 messages 顺序压平的, role 过滤后
            # 跟当前 user 消息的下标对得上. 没有 message_items 兜底用 ?.
            mi = req.get("message_items") or []
            user_idx = sum(1 for x in (req.get("messages") or [])[:req["messages"].index(m)]
                            if isinstance(x, dict) and x.get("role") == "user")
            raw_mid = f"{turn}:{user_idx}"
        mid = f"{sid}:user:{raw_mid}"
```

> **执行者注意**: 上面 `req["messages"].index(m)` 用 identity 匹配（dict 身份比较）不安全；实际更稳的写法是 zip 起来用 enumerate。考虑改成：

```python
        if not raw_mid:
            mi = req.get("message_items") or []
            user_idx = 0
            for m2 in req.get("messages") or []:
                if m2 is m:
                    break
                if isinstance(m2, dict) and m2.get("role") == "user":
                    user_idx += 1
            raw_mid = f"{turn}:{user_idx}"
        mid = f"{sid}:user:{raw_mid}"
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `python3 -m unittest tests.test_capture -v && python3 -m unittest discover -s tests -v`
Expected: UserMidDerivationTest 全 PASS；全量回归 PASS

- [ ] **Step 5: Commit**

```bash
git add ata/plugins/capture.py tests/test_capture.py
git commit -m "fix(capture): user mid 派生走 message_items index, 避免空尾巴撞车

anthropic wire 真实 user 消息没有 id 字段, 旧代码 fallback
f'{sid}:user:{m.get(\"index\", \"\")}' 在 index 也缺失时产出空尾巴
mid (e6d514c5-...:user:), seen set 命中后所有真 user 一起被吞。

新派生 f'{sid}:user:{turn}:{user_idx}' 用 turn + user 消息下标
双键, 跨 turn 也不撞, 跟 wire 真实形态一致。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: seen 改走 events.dedupe_key 跨进程持久化 + dedupe_key role 命名空间

**Files:**
- Modify: `ata/ledger.py`（`_dedupe_key` 接受 message.upserted role 命名空间）
- Modify: `ata/plugins/capture.py`（不再用内存 `seen` 集合,改用 `Ledger.dedupe_key` 兜底）
- Test: `tests/test_capture.py`（追加跨进程 seen 持久化测试）
- Test: `tests/test_ledger_dedupe.py`（追加 role 命名空间测试）

**Interfaces:**
- Consumes: `Ledger._dedupe_key`（现有函数）。
- Produces: message.upserted 的 dedupe_key 形如 `f"message.upserted:{role}:{message_id}"`，保证 `UNIQUE(session_id, dedupe_key)` 索引能在跨进程重启后继续挡重复 emit；capture.py 删掉 `_capture_emit` 这个内存 set。

- [ ] **Step 1: 写失败测试**

在 `tests/test_ledger_dedupe.py` 追加：

```python
class DedupeKeyRoleTest(unittest.TestCase):
    def test_message_user_dedupe_key(self):
        from ata.ledger import _dedupe_key
        ev = {"type": "message.upserted",
              "payload": {"role": "user", "message_id": "abc"}}
        self.assertEqual(_dedupe_key(ev), "message.upserted:user:abc")

    def test_message_assistant_dedupe_key(self):
        from ata.ledger import _dedupe_key
        ev = {"type": "message.upserted",
              "payload": {"role": "assistant", "message_id": "xyz"}}
        self.assertEqual(_dedupe_key(ev), "message.upserted:assistant:xyz")
```

在 `tests/test_capture.py` 追加：

```python
class SeenPersistedAcrossInstancesTest(unittest.TestCase):
    """seen 不能只在 capture.py 内存 set, ata 重启后空 mid 又能 emit
    一次会跟历史去重键冲突。seen 必须走 events.dedupe_key UNIQUE 索引
    跨进程持久。"""

    def test_second_ledger_instance_dedupes_via_dedupe_key(self):
        import tempfile
        from pathlib import Path
        from ata.ledger import Ledger
        from ata.plugins.capture import ingest_capture

        rec = lambda sid, mid: {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": sid},
            "request_body": json.dumps({
                "model": "claude-3-5-sonnet",
                "messages": [{"role": "user",
                              "content": [{"type": "text", "text": "hi"}]}],
            }).encode(),
            "response_content_type": "application/json",
            "response_body": json.dumps({
                "id": "msg_r", "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode(),
            "started_at_ms": 1000, "completed_at_ms": 2000,
        }
        with tempfile.TemporaryDirectory() as d:
            led1 = Ledger(Path(d))
            ingest_capture(led1, rec("pers-1", "user-msg-1"))
            recs1 = led1.read("pers-1")
            user_upserts1 = [r for r in recs1
                             if r["type"] == "message.upserted"
                             and r["payload"].get("role") == "user"]
            self.assertEqual(len(user_upserts1), 1)

            # 同一账本文件, 全新 Ledger 实例 (模拟 ata 重启)
            led2 = Ledger(Path(d))
            ingest_capture(led2, rec("pers-1", "user-msg-1"))
            recs2 = led2.read("pers-1")
            user_upserts2 = [r for r in recs2
                             if r["type"] == "message.upserted"
                             and r["payload"].get("role") == "user"]
            # 第二次没新行, dedupe_key UNIQUE 拦了
            self.assertEqual(len(user_upserts2), 1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_ledger_dedupe.DedupeKeyRoleTest tests.test_capture.SeenPersistedAcrossInstancesTest -v`
Expected: 全 FAIL（`_dedupe_key` 返回 `"message.upserted:user-msg-1"` 没 role 段；内存 set 拦不住新 Ledger 实例）

- [ ] **Step 3: 最小修复 (ledger.py)**

`ata/ledger.py` `_dedupe_key` 把：

```python
    if typ == "message.upserted" and payload.get("message_id"):
        return f"{typ}:{payload['message_id']}"
```

改为：

```python
    if typ == "message.upserted" and payload.get("message_id"):
        # role 命名空间: user / assistant 撞同 message_id 时不互吞
        role = payload.get("role") or "unknown"
        return f"{typ}:{role}:{payload['message_id']}"
```

并把存量迁移 SQL（`_migrate_dedupe_column` 那段）里同样路径的 CASE WHEN 改 role 前缀：

```sql
    WHEN type='message.upserted'
         AND json_extract(event_json,'$.payload.message_id') IS NOT NULL
        THEN type || ':' || COALESCE(json_extract(event_json,'$.payload.role'),'unknown')
             || ':' || json_extract(event_json,'$.payload.message_id')
```

> **执行者注意**: 存量迁移只在新列首次加时跑一次；现有 db 已迁移过 tool 行的话这条会失效。需要先 `git diff ata/ledger.py` 确认 schema migration 段没在 v2 里被改过；如已改过则跳过 SQL 段，只改 `_dedupe_key` 函数体。

- [ ] **Step 4: 最小修复 (capture.py)**

`ata/plugins/capture.py` 把 L202 的 `seen = state.setdefault("_capture_emit", set())` 和 user emit 循环里 L215 `seen.add(mid)` + L260-261 assistant 的 `if resp_id not in seen: seen.add(resp_id)` 全部删掉。

`_translate` 末尾保持 `return out` 不变（translate 保持纯函数，append 由 `ingest_capture` 入口统一做，便于测试）。

新增 `_append_with_dedupe` 顶层辅助（吃 Ledger.append 单条,IntegrityError 静默跳过）：

```python
def _append_with_dedupe(ledger, events):
    """逐条 append; 命中 events.dedupe_key UNIQUE 索引时静默跳过。
    跨进程 seen 持久化兜底; 不再在内存维护 seen set。"""
    import sqlite3
    written = 0
    for ev in events:
        try:
            ledger.append(ev)
            written += 1
        except sqlite3.IntegrityError:
            continue
    return written
```

`ingest_capture` (L381) 末尾的：

```python
    if events:
        ledger.append_many(events)
    return len(events)
```

改为：

```python
    if events:
        return _append_with_dedupe(ledger, events)
    return 0
```

> **设计理由**: seen 不放 `state` 内存 set 而是放 `events.dedupe_key` UNIQUE 索引的好处 — translate 本身保持纯函数（state 不再被它改），同一 rec 多次 translate 不会漏写也不会重写；进程重启也对账本无影响。代价: 翻译 + 落库多一次 IntegrityError roundtrip，但 events 量级是 O(session turn),可忽略。

- [ ] **Step 5: 跑测试确认通过 + 回归**

Run: `python3 -m unittest tests.test_capture tests.test_ledger_dedupe -v && python3 -m unittest discover -s tests -v`
Expected: SeenPersistedAcrossInstancesTest PASS；DedupeKeyRoleTest PASS；全量回归 PASS

- [ ] **Step 6: Commit**

```bash
git add ata/ledger.py ata/plugins/capture.py tests/test_capture.py tests/test_ledger_dedupe.py
git commit -m "fix(capture): seen 走 events.dedupe_key 跨进程持久 + role 命名空间

旧实现 _capture_emit 内存 set 跨进程丢, ata 重启后空 mid 又能 emit
一次, 跟历史去重键冲突。改走 events.dedupe_key UNIQUE 索引兜底
(零新表), Ledger.append 抛 IntegrityError 时 capture 翻译层吞掉。

同时 dedupe_key 加 role 段 (message.upserted:user:mID / :assistant:mID),
避免 user / assistant 偶发撞同 message_id 被一起吞。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 文档收尾 — 解除 v2 已知限制

**Files:**
- Modify: `docs/adr/0001-proxy-capture-channel.md`（v2 已知限制列表, 删「user 消息相关」条目）
- Modify: `docs/features/proxy-capture-channel.md`（调试段补「user 消息丢失」条目, 指向修复 commit）

- [ ] **Step 1: 更新 ADR**

打开 `docs/adr/0001-proxy-capture-channel.md`, 找 v2 已知限制列表 (大概率是 ADR 末尾的 "v2 已知限制 + 待办清单" 段,或者 doc body 里的限制子节)。找到关于 user 消息丢失 / 空 mid 撞车 / seen 跨进程丢的条目, 改成:

```markdown
- ~~user 消息丢失~~ **已修** (2026-08-27, `fix(capture): seen 走 events.dedupe_key` 系列 commit)
  emit 加 is_context_text 过滤, mid 走 message_items index, dedupe_key 加 role 段 + 跨进程持久化。
  旧 sid 残留不修 (用户确认「让它过去」)。
```

或对应位置替换为「**已修**」标记 + 一行 commit 引用。

- [ ] **Step 2: 更新调试段**

`docs/features/proxy-capture-channel.md` 调试表里加一行:

```markdown
| 账本里 user 消息只剩 1 条且是 `<system-reminder>` | `fix(capture): emit user 消息时过滤 CONTEXT 注入` + `fix(capture): user mid 派生走 message_items index` | 旧 sid 不修,新事件按新逻辑 |
```

- [ ] **Step 3: Commit**

```bash
git add docs/adr/0001-proxy-capture-channel.md docs/features/proxy-capture-channel.md
git commit -m "docs(adr): 解除 v2 user 消息丢失限制, 指向修复 commit

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## 非目标（明确不做）

- **旧 sid `e6d514c5-...` 的账本修变**：用户确认「让它过去」；本计划不提供删行 / 重放 / 标记脚本。修复后产生的事件按新逻辑，旧事件留在原处。
- **assistant mid 派生改造**：assistant 走 `response_id`（`msg_01xxx` 或 `gen-...`），wire 真实响应必带，不存在 fallback 空尾巴问题；本计划不动。
- **tool_use / tool_result 的 seen 跨进程持久化**：tool.upserted 走 start + end 双行 eid（v2 设计），dedupe 暂不挡 tool 行；本计划只覆盖 message.upserted 跨进程 seen。
- **CaptureWriter 队列语义**：评审候选 3，v1 仍非目标；本计划不引入。
- **OpenAI 族 message 消息修复**：codex / droid 走的 OpenAI 协议 message 形状另有自己的 mid 派生路径，bug 表现不同；本计划只覆盖 anthropic-messages（claude）。

---

## 验证清单

修复后用以下命令自验：

```bash
# 1. 全量回归
python3 -m unittest discover -s tests -v
# 预期: 全 PASS

# 2. 4 个回归测试单独跑
python3 -m unittest tests.test_capture.UserContextFilterTest tests.test_capture.UserMidDerivationTest tests.test_capture.SeenPersistedAcrossInstancesTest tests.test_ledger_dedupe.DedupeKeyRoleTest -v
# 预期: 全 PASS

# 3. 端到端冒烟（可选, 需要上游可连通）
python3 -m ata serve --ledger ./data-smoke --port 8899 --proxy-port 8319 &
sleep 1
curl -s -X POST http://127.0.0.1:8319/v1/messages \
  -H 'Content-Type: application/json' \
  -H 'x-claude-code-session-id: smoke-fix' \
  -H 'x-api-key: dummy' \
  -d '{"system":[{"type":"text","text":"smoke"}],"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}' \
  -o /dev/null -w '%{http_code}\n'
# 预期: 4xx (dummy key), 但账本 smoke-fix 已有 system.upserted + (可能) message.upserted
sqlite3 ./data-smoke/ata.sqlite "SELECT type, json_extract(event_json,'\$.payload.role') FROM events WHERE session_id='smoke-fix';"
kill %1
```
