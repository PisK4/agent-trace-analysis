# Atatrace 手动测试指南

在 Pi / Droid / Claude Code / Codex 里发起真实会话，然后在 Atatrace 里核对投影是否正确。检查点统一是：**标题、轮次、工具完成态、usage 状态、无 pending 幽灵**。

## 前置

```bash
cd repos/ata
make serve                      # 端口 8787，账本 ~/.ata/dev.sqlite，近 7 天会话
# 浏览器打开 http://127.0.0.1:8787
```

页面启动后保持打开：新会话 5 秒内出现在左侧列表顶（无需刷新，列表按最近活动倒序）；已打开的会话尾部 1 秒内跟随（上滚后自动暂停跟随，点「跟随尾部」恢复）。

左侧列表上方有 Agent 筛选 tab（全部 / Droid / Pi / Claude Code / Codex）：点某个 tab 只显示该 agent 的会话，再点「全部」恢复完整列表。tab 由当前账本里实际存在的 agent 动态生成。

## 每个 agent 测什么

### Pi

1. 到 Pi 里发起两轮以上对话，其中一轮点出工具
2. 回 Atatrace：会话出现在列表，标题 = 首条用户消息
3. 打开会话检查：

| 检查点 | 正常现象 |
| --- | --- |
| SYSTEM 行 | 首行出现「SYSTEM」，检查器里有 System Prompt / Tools / Diff 页签 |
| 轮次 | `T1`/`T2` 分段，turns 数与真实用户消息轮数一致 |
| 工具 | 行渲染「工具名 → 结果」，状态 completed，无 pending |
| usage | 助手行 Usage 格子是数字（reported） |
| 幽灵行 | 无永远转圈的行；`agent_end` 后没有提前关闭的会话 |

依赖：extension 已装（`~/.pi/agent/extensions/pi-atatrace`）且 ATA 服务在 8787。

### Droid

1. 在 Droid（Factory）里发起一轮对话
2. 回 Atatrace：新会话出现在列表，标题 = `session_start.title`

| 检查点 | 正常现象 |
| --- | --- |
| 工具 | 全部 completed（有结果），无 pending |
| usage | 助手行 Usage 格子写 `Missing`——**预期行为**（JSONL 无 token 字段），不是 bug |
| 轮次 | 用户消息到达时递增；纯 tool_result 消息不新增轮次 |
| COMPACTED 行 | 有过 `compaction_state` 的会话会出现；`llm_summary` 与 `provider_switch_serialization` 都画，后者 Note 写明切模型序列化 |
| 取消 / 失败 | `agent_turn_outcome.reason=cancelled/error` 时该轮助手行标 Cancelled / Failed |

### Claude Code

1. 在 Claude Code 里发起一轮对话（可让工具跑一次）
2. 回 Atatrace：新会话出现在列表，标题 = `ai-title`（AI 生成的标题）

| 检查点 | 正常现象 |
| --- | --- |
| SYSTEM 行 | **没有**——预期（transcript 不落盘系统提示），检查器无 System 页签不为异常 |
| 工具 | completed（`tool_use_id` 与 `tool_use` 配对） |
| usage | Usage 格子有数字（官方 API usage 驼峰键已映射）；个别旧会话无 usage 显示 `Missing` |
| 轮次 | 与用户消息数一致 |
| Model | 点 Request 圆点：Model 为 `message.model`；`<synthetic>` 不当模型名 |
| COMPACTED 行 | 有 `compact_boundary` 的会话会出现，Note 写 `auto · pre → post tokens` |
| 失败 | `api_error` 画一条 Failed 助手行，正文含 HTTP 状态和 `retry n/m` |

### Codex

1. 在 Codex（TUI / VS Code / Desktop 任一）发起一轮对话
2. 回 Atatrace：新会话出现在列表，标题 = `originator`（首条 prompt）

| 检查点 | 正常现象 |
| --- | --- |
| SYSTEM 行 | 有（来自 `base_instructions`） |
| 工具 | completed（`function_call` / `custom_tool_call` 与 `_output` 配对） |
| usage | Usage 格子有数字（`token_count.last_token_usage` 对齐最近一轮） |
| 轮次 | 与 `task_started` / `task_complete` 对齐 |
| Model | 点 Request 圆点：Model 为 `turn_context.model`，有 `effort` 时写在后面 |
| COMPACTED 行 | 有 `compacted` / `context_compacted` 的会话会出现 |
| 取消 | `turn_aborted` 时该轮助手行标 Cancelled |

## 会话统计面板（工具统计 / Usage / 过滤 chips）

打开任一会话：Timeline 顶栏有**常驻徽章**（`N calls`，failed 非零追加红字 `· K failed`），点它弹出统计面板；**Usage** 按钮展开逐轮 token 面板。Tools 泳道上失败调用是红色加高斜纹块。Ledger 区有 **Failed / Tools** 过滤 chip。

| 检查点 | 正常现象 |
| --- | --- |
| 常驻徽章 | 打开会话即见 `M calls`；有失败追加红色 `· K failed`。M = 去重后调用总数 |
| 失败泳道 | Tools 泳道失败调用红块加高带斜纹；无失败的会话全为橙色细条 |
| 面板排序 | 表格按失败数降序 → 调用数降序；红色 Failed 数字自己完成分区，零失败行留白 |
| 使用率 | 有工具目录的会话（Pi/Cue）显示 `挂载 N · 已用 M · 使用率 P%`；无目录的宿主显示 `已用 N · 使用率 n/a`——预期行为不是缺陷 |
| 钻取 | 点击工具行按**时间顺序**展开每次调用：状态点、时间、耗时、入参预览；初始 5 条，show more 追加 |
| 跳转 | 点击钻取条目滚到对应 TOOL 行并打开检查器（有 payload 时直接落 payload 页签）。目标不在已加载页时自动拉取到达 |
| 跳转边界 | 进行中的会话，跳转后行内容以最新投影为准，可能与点击时的统计略有出入——预期行为不是 bug |
| Usage 面板 | 逐轮 input/output 双色条 + 元信息行（agent、轮次、token 合计）；missing turns 非零时显式红字标出而非静默 |
| usage 盲区 | Droid 会话 Usage 面板显示 missing 计数属预期（JSONL 无 token 字段）；cache 列本地中转语料常为空（已知盲区） |
| 过滤 chips | 点 Failed 主表只剩失败行，再点还原；Tools 同理；与搜索叠加不冲突；切换会话后自动复位 |
| 卡片轮次 | 左侧会话卡片显示 turns 数，与会话实际轮次一致 |
| 空会话 | 无工具调用的会话徽章显示 `0 calls`，面板提示 no tool calls |

## 异常速查

| 现象 | 含义 | 处理 |
| --- | --- | --- |
| 工具行一直 pending | 丢了完成态（translate 或账本幂等问题） | 报 bug，附 agent 与会话 |
| 列表看不到新会话 | 服务没起，或会话文件超过 `--tail-max-age-days` 窗口 | 起服务 / 调大窗口 |
| 当前页不动 | 上滚过暂停了跟随 | 点「跟随尾部」 |
| usage 写 0 而不是 Missing | 不正常的退化 | 报 bug |
| 会话标题是 uuid/乱码 | Claude 还没写 `ai-title` / Codex 无 `originator` | 等几秒或刷新 |
| Tool stats 摘要数字与展开对不上 | 账本幂等或去重逻辑回归 | 报 bug，附 agent 与会话 |
| 红方块永远不出现（确定失败过的会话也没有） | 适配器丢 failed 终态 | 报 bug，附 agent 与会话 |

## 已知边界（不是 bug）

- Droid 每轮 usage 恒 `Missing`（契约上限）；Droid 模型名在 `*.settings.json`，不摊到每一轮，Request 的 Model 保持 Not present
- Claude Code 无 SYSTEM 行（transcript 不落盘系统提示）
- 工具行参数区为空对象：Pi 的 `toolSnippets` 只有名字到单行描述的映射，无 JSON schema（契约上限）
- `--tail-max-age-days` 之外的旧会话不显示
- 已入库的助手行不会改写（账本按 id 幂等）。重启服务后，新的 COMPACTED / api_error 行会补上；旧助手行的 Model 要等新会话才有
