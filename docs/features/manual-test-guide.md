# Atatrace 手动测试指南

在 Pi / Droid / Claude Code / Codex 里发起真实会话，然后在 Atatrace 里核对投影是否正确。检查点统一是：**标题、轮次、工具完成态、usage 状态、无 pending 幽灵**。

## 前置

```bash
cd repos/ata
make serve                      # 端口 8787，账本 ~/.ata/dev.sqlite，近 7 天会话
# 浏览器打开 http://127.0.0.1:8787
```

页面启动后保持打开：新会话 5 秒内出现在左侧列表（无需刷新）；已打开的会话尾部 1 秒内跟随（上滚后自动暂停跟随，点「跟随尾部」恢复）。

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

### Claude Code

1. 在 Claude Code 里发起一轮对话（可让工具跑一次）
2. 回 Atatrace：新会话出现在列表，标题 = `ai-title`（AI 生成的标题）

| 检查点 | 正常现象 |
| --- | --- |
| SYSTEM 行 | **没有**——预期（transcript 不落盘系统提示），检查器无 System 页签不为异常 |
| 工具 | completed（`tool_use_id` 与 `tool_use` 配对） |
| usage | Usage 格子有数字（官方 API usage 驼峰键已映射）；个别旧会话无 usage 显示 `Missing` |
| 轮次 | 与用户消息数一致 |

### Codex

1. 在 Codex（TUI / VS Code / Desktop 任一）发起一轮对话
2. 回 Atatrace：新会话出现在列表，标题 = `originator`（首条 prompt）

| 检查点 | 正常现象 |
| --- | --- |
| SYSTEM 行 | 有（来自 `base_instructions`） |
| 工具 | completed（`function_call` / `custom_tool_call` 与 `_output` 配对） |
| usage | Usage 格子有数字（`token_count.last_token_usage` 对齐最近一轮） |
| 轮次 | 与 `task_started` / `task_complete` 对齐 |

## 异常速查

| 现象 | 含义 | 处理 |
| --- | --- | --- |
| 工具行一直 pending | 丢了完成态（translate 或账本幂等问题） | 报 bug，附 agent 与会话 |
| 列表看不到新会话 | 服务没起，或会话文件超过 `--tail-max-age-days` 窗口 | 起服务 / 调大窗口 |
| 当前页不动 | 上滚过暂停了跟随 | 点「跟随尾部」 |
| usage 写 0 而不是 Missing | 不正常的退化 | 报 bug |
| 会话标题是 uuid/乱码 | Claude 还没写 `ai-title` / Codex 无 `originator` | 等几秒或刷新 |

## 已知边界（不是 bug）

- Droid 每轮 usage 恒 `Missing`（契约上限）
- Claude Code 无 SYSTEM 行（transcript 不落盘系统提示）
- 工具行参数区为空对象：Pi 的 `toolSnippets` 只有名字到单行描述的映射，无 JSON schema（契约上限）
- `--tail-max-age-days` 之外的旧会话不显示
