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
- ~~OpenAI 族解析（codex 可用）暂缓，ata/wire 的注册表 seam 已预留。~~
  **2026-08-27 已落地**——见 `docs/superpowers/plans/2026-08-27-openai-parser-port.md`,
  `ata/wire/openai_parser.py` 1:1 移植自 ava 1095 行,
  `protocol_facts._OpenAI` 注册到 `/v1/chat/completions` 与 `/v1/responses`。
  droid 走 17878 代理能产出 `system.upserted` / `turn.ended`（e2e 验证通过）。
  codex 走 Responses API 解析已就位,只需 codex 端把 `OPENAI_BASE_URL` 切到 17878
  (用户已说明先不做,本计划不动 codex 配置)。

### 已知限制

- **轮次口径可能漂移**：代理侧轮次号是对请求上下文的静态计数
  （count_real_user_turns），transcript 侧是流式递增计数器
  （bump_turn_if_real_user）。两者对齐的前提是「每次请求带全量历史」；
  宿主做 context 编辑 / microcompact（不落盘）裁掉早期用户消息时，
  代理算出的轮次会小于真实轮次，该轮 usage 挂错位置。幂等键收敛不了
  口径漂移。缓解路径：轮次推导以 transcript 侧已开的最大轮为下限，
  但那需要跨通道读账本状态——等真实数据里观察到漂移再上。
- **新会话可见性空窗**：代理通道从不发 session.opened（sid 是宿主真 id，
  发 opened 会与 transcript 适配器的 opened 抢同键）。刚开的会话里代理
  事件已入账、sessions 列表却还没有行——要等 transcript tail 扫到文件
  才浮出。这是裁决内行为，不是 bug。

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

### v2 升级：代理主发 message / tool（2026-08-27 增补）

v1 明确「代理不发 message / tool」的理由（双通道 natural-key 写序竞态）
在 transcript 跨 step state 持久化（2026-08-27 Round 1，commit fb74ff2）
落地后被重新审视：两条通道拿到的是**两形态 message_id** —— 代理拿
`resp.response_id`（`msg_01xxx`），transcript 拿 `gen-...`。dedupe 按
message_id 不去重，投影会出现重复行。Round 1 只解决了 jsonl 侧
`turn` 累加器丢失 + `pending` 攒齐 block，但根因 #3（jsonl tail 的
mtime/offset 检测失活导致 tool 行漂到 seq 2000+ 之后）仍存在。

裁决（v2）：

- 代理主发 `message.upserted`（user 从 `req.messages`，assistant 从
  `resp.response_blocks`）/ `tool.upserted`（start 从 `resp.response_tool_calls`，
  end 从下一轮 request 的 `tool_result` 块）。
- transcript `claude.py` 收窄为元数据通道：ai-title → `session.opened` /
  `compact_boundary` / `system.api_error` 兜底 / attachment / mode / last-prompt。
  `translate_line` 对 user / assistant 行直接 return，不再 emit
  `message.upserted` / `tool.upserted` / `turn.started`。
- `state["turn"]` 累加器从 transcript 迁到代理端 capture state，jsonl 侧
  state dict 仍保留 turn 字段（不影响行为，后续清理）。
- `project.py:last_user_turn` remap 删除（代理主发后无孤儿 turn；老 remap
  是 handoff §1 根因 #4 的污染源）。

后果：

- 长 session 上 tool 行不再集中漂到 seq 2000+（根因 #3 根治）。
- 投影层 assistant 行 turn 字段与 ingest 端发出的 turn 一致（无 remap
  压回 turn=1 的污染）。
- `tool.upserted` 双行 eid（`{sid}:tool:{cid}:start` / `:end`）与 dedupe_key
  冲突是已知遗留：dedupe 按 `tool.upserted:{cid}` 折叠，start 行被吞；
  投影层只看到 end 状态。待 tool dedupe_key 拆成 `None`（下轮）。
- 不再依赖 transcript tail 的 mtime/offset 检测：long session 上 tool
  漂到 seq 2000+ 的根因 #3 自此不再可能。

### v2 已知限制（2026-08-27 增补）

落地后跑 fbc74609-c590-4261-8c12-2904acbb3200 复测，识别出两条
已知限制，明确不在本轮修复：

- **SSE thinking 块未还原**：`anthropic_parser._finalize_sse_block`
  把 `text_delta` 与 `thinking_delta` 合并到 `text` 字段（行 358-361
  把两者都写进 `_text_parts`），所以 `response_blocks` 走到
  `capture.py:_translate` 提取 thinking 时永远拿不到 `b["thinking"]`
  —— 只能拿到 `b["text"]`（其中已混着 thinking）。代理端
  `thinking=None` 是这一行的必然结果。如需还原，单独立项：让
  `_finalize_sse_block` 把 thinking 拆到 `b["thinking"]` 字段。
- **tool dedupe_key 折叠**（已在上面"后果"节末段提过）：本轮没修。
  投影层 `fbc74609` 的 tool 行全部 `status=completed` 看不到 pending 状态。
  修法：把 `tool.upserted:{cid}` 的 dedupe_key 拆成 `None`，让 ledger
  保留多行同 cid 的 eid 折叠（start / end 共存）。

### v2.1 解除: user 消息正确 emit + seen 跨进程持久化 (2026-08-27 增补)

复测 fbc74609-... 识别出 user 消息丢失的三个串联根因, 在 2026-08-27
`fix(capture)` 系列 commit 落地:

- **emit 不过滤 CONTEXT 注入** → `fix(capture): emit user 消息时过滤 CONTEXT 注入`
  (commit adbbc31) emit 路径加 is_context_text 过滤, 跟
  count_real_user_turns 同口径, 避免 `<system-reminder>` / harness
  注入的上下文文本被当 user 消息写入账本。
- **mid fallback 空尾巴撞车** → `fix(capture): user mid 派生走
  message_items index` (commit b2f79cd) anthropic wire 真实 user
  消息没有 id 字段, 旧 fallback `f'{sid}:user:{m.get("index", "")}'`
  在 index 也缺失时产出空尾巴 mid, 改 `f'{sid}:user:{turn}:{user_idx}'`
  用 turn + user 消息下标双键。
- **seen 跨进程丢** → `fix(capture): seen 走 events.dedupe_key
  跨进程持久` (commit 80a247f) `_capture_emit` 内存 set 跨进程丢,
  ata 重启后空 mid 又能 emit 一次, 跟历史去重键冲突。改走
  `events.dedupe_key` UNIQUE 索引兜底(零新表), 同时 dedupe_key
  加 role 段 (`:user:mID` / `:assistant:mID`), 避免 user/assistant
  偶发撞同 message_id 被一起吞。

旧 sid `e6d514c5-...` 的账本残留不修(用户确认「让它过去」); 修复后
产生的事件按新逻辑, 旧事件留在原处。

### v2 待办（按收益 / 风险排序）

1. **tool dedupe_key 拆 `None`**：解锁投影层 pending → completed 状态机。
   工作量小，收益直接（fbc74609 立刻可看 tool 状态变化）。
2. **SSE thinking 还原**：把 `_finalize_sse_block` 的 `text_delta` /
   `thinking_delta` 分流。capture 端不需要改，代理 emit 即时获得
   `thinking` 字段。
3. **droid / codex 走代理**：`droid` 真实流量在 wire 上无 sid（无
   `x-droid-*` 头、body 无 `metadata.session_id`），代理 `resolve_session_id`
   失败 → `ingest_capture` 抛 `ValueError` 被吞 → 走 `capture_proxy._VIRTUAL_SID_AGENTS`
   兜底产生 `droid-wire-<ts>-<rand>` 虚拟 sid，归并失败，droid 仍走
   jsonl。codex 走 OpenAI Responses API，`openai_parser` 已移植但
   `system/tools` 提取走 fallback。本轮无影响（jsonl 仍发 message），
   但 droid / codex 走代理后才算"完整 v2"覆盖。
4. **capture.py 拆小函数**：`_translate` 现在 ~200 行嵌套 4 层
   （message → content → block → text），可拆 `_user_messages(req)` /
   `_assistant_text_thinking(blocks)` / `_tool_results(req)` 三个
   私有函数,降低维护成本。不紧急。
