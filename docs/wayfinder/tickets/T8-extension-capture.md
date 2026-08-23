---
title: pi 扩展捕获增强
labels: [wayfinder:task]
status: open
assignee: none
blocked_by: []
---

## Question

2026-08-23 对 `extensions/pi-atatrace` 与 `ata/plugins/pi.py` 的评估结论：当前捕获面对飞轮不够用，按优先级补齐。这张票记录评估清单与实施规划，实施走 ata 仓库的正常开发流程（`/ponytail full`、`make test`、重启服务）。

## 实施规划（2026-08-23 定稿，用户已同意）

### 背景发现

Cue 的子代能力来自第三方包 pi-subagents v0.54.0（本机装于 `~/.cue/pi-config/npm/node_modules/`）。它启动的子代理是**独立 Pi 进程**，但会注入一整套血缘环境变量，我们的扩展在子进程里同样加载、同样能读：

| 环境变量 | 含义 |
| --- | --- |
| `PI_SUBAGENT_CHILD` | 存在即标记这是子代理进程 |
| `PI_SUBAGENT_ORCHESTRATOR_SESSION_ID` | **父会话 id**（血缘的关键） |
| `PI_SUBAGENT_RUN_ID` / `PI_SUBAGENT_PARENT_RUN_ID` / `PI_SUBAGENT_PARENT_ROOT_RUN_ID` | 运行层级 |
| `PI_SUBAGENT_CHILD_AGENT` | 子代理角色名（scout/worker 等） |
| `PI_SUBAGENT_PARENT_DEPTH` / `PI_SUBAGENT_PARENT_PATH` | 嵌套深度与路径 |

结论：捕获子代逻辑不需要改 Cue 或 pi-subagents，扩展读环境变量随钩子上报即可。

### 改动清单

1. **扩展侧 `extensions/pi-atatrace/index.ts`**：读上表环境变量加 `ATA_CHANNEL`（通道标记），组装成可选的 `lineage` 与 `channel` 字段，随每个 hook 请求体发送；缺了就不发，不报错。
2. **服务端 `ata/http.py` 的 `_ingest_pi_hooks`**：把请求体新增的 `channel`、`lineage` 字段放进 ctx 透传给翻译器。
3. **翻译器 `ata/plugins/pi.py`**：
   - P0 全文入库：去掉 `_message_text` 结果的 `[:200]` 截断，user 消息存全文（assistant 的 output_text 本来就是全文）；部署后目测 Web UI 长消息渲染；
   - P1 真实耗时：state 按 tool_call_id 记 start ts，end 时算差值写 duration_ms；assistant 消息同理用 message_start/end 差值替换占位值 1；
   - P1 失败状态：turn_end 时读 msg.stopReason，error→failed、aborted→cancelled，写入 turn.ended.payload.status（投影层已支持）；
   - 血缘：session.opened payload 增加可选 `parent_session` 及 subagent 元数据（agent 名、深度、run id）；schema 不动；
   - 通道：session.opened payload 增加可选 `channel`。
4. **测试与验证**：tests/ 增补四个单测（全文入库、duration 计算、stopReason 映射、血缘与通道透传）；`make test` → `./scripts/install-service.sh restart` → health 探活；真机跑一条带委托的 Cue 会话，确认账本里子会话的 parent_session 指向父会话 id。

### 已知边界（诚实声明）

- 环境变量名来自本机安装的 pi-subagents v0.54.0，属第三方包实现细节，升级可能变；代码按"缺了就不写"降级；
- 本机 Cue 实际运行 pi-coding-agent **0.84.1**，比研究档案锚定的 845d6ff1（0.83.0）新，钩子行为以实测为准；
- fork 型子会话（context=fork）上报的父引用指向分支文件还是会话 id，待实测确认。

### 评估原表（保留备查）

| 优先级 | 事项 | 说明 |
| --- | --- | --- |
| P0 | 用户消息全文入库 | 翻译器把所有正文截断在 200 字符，assistant 有 output_text 全文而 user 没有；T3 回归集的 input 字段因此拿不到原料 |
| P1 | 真实 duration_ms | 现在全是占位值 1；start/end 事件都有 ts，服务端按差值计算即可 |
| P1 | turn 失败/中止状态 | stopReason 为 error/aborted 时写入 turn.ended 的 status，投影层已支持 failed/cancelled |
| P2 | 通道标记 | 扩展透传环境变量（如 ATA_CHANNEL），兑现 T3 决议里"channel 先标 unknown"的欠账 |
| P2 | 血缘 parent_session | 已核实可行：经 pi-subagents 注入的环境变量，见上方规划 |
| P3 | 压缩事件、审批记录 | 受 pi 钩子面限制短期做不了：前者靠提示词变化间接推断，后者归 Cue 侧产出账 |

## Progress notes

- 2026-08-23 更正：入账链路正常（用户实测新消息即时捕获），此前"GUI 读不到 ATA_URL"猜测撤回。
- 2026-08-23 实施落地（计划：`docs/superpowers/plans/2026-08-23-agent-access-layer.md`，Task 1-12）：
  - 改动清单 1-3 全部完成并逐项提交（ledger 血缘列与 children/ancestry 查询、schema 加 `session.scored`、翻译器全文/真实耗时/stopReason 状态映射/血缘通道透传、扩展读 `PI_SUBAGENT_*` 与 `ATA_CHANNEL` 随钩子上报）；
  - `make test` 全量通过（72 个，含新增 8 个单测），服务已 restart 且 `/api/health` 返回 `{"ok": true}`；
  - 实施偏差两处，均以测试/spec 为准：① `Ledger.ancestry` 不做 reverse（最近祖先在前，方案代码与其自身测试矛盾）；② 非 opened 事件的 UPDATE 保留已存 `parent_session_id`，防止后续事件把血缘抹成 NULL（方案代码有此缺陷）。
  - 待验证项（依赖真实 Cue 委托会话）：子会话 `parent_session` 落库、fork 型父引用形状、长消息 Web UI 渲染。存量账本无血缘数据属预期（均在扩展更新前采集）。
