# 数据来源速记 / Data Source Cheatsheet

Atatrace 看到的每条事实，都得由某家宿主的某条记录或某次 hook 提供。下面是五家宿主的可观测面——能拿什么、不能拿什么、契约上限在哪。

| 词 | 定义 |
| --- | --- |
| 宿主 | Pi / Cue / Droid / Claude Code / Codex 之一，ATATRACE 适配的 agent 实现 |
| 适配器 | `ata/plugins/<agent>.py`；把宿主方言翻成规范事件 |
| 通道 | 适配器拿到宿主事实的路径：第一方文件 tail / live hook / 转发代理 |
| 数据可得性 | 该宿主在「现有落盘 + 现有 hook + 现有代理」三条通道下能给到的事实 |

## 五宿主可观测面

| 宿主 | 通道 | 标题 | System Prompt | Tools 目录 | 每轮 usage | Model |
| --- | --- | --- | --- | --- | --- | --- |
| Pi | 官方 extension / live hook | 首条用户消息 | 有（`before_agent_start`） | 有（名字 + 单行描述） | reported | Not present（按需可补） |
| Cue | Pi 官方 extension / live hook | 首条用户消息 | 有（`before_agent_start`） | 有（名字 + 单行描述） | reported | Not present（按需可补） |
| Claude Code | 第一方 transcript / 文件 tail | `ai-title` 行 | 无 | 无 | reported（缺失或全 0 → Missing） | `message.model` |
| Codex | 第一方 rollout / 文件 tail | `originator`（首条 prompt） | 有（`base_instructions`） | 无（`tools_catalog` 留空数组） | reported（`token_count.last_token_usage`） | `turn_context.model` + `effort` |
| Droid | 第一方 sessions / 文件 tail | `session_start.title` | 无 | 无 | 恒 Missing | Not present（在 `*.settings.json`） |
| 任意 | `--proxy-port` 代理通道 | 同通道 | 补 SYSTEM（prompt_text + tools_catalog） | 补 tools_catalog | 补 turn.ended.usage | Not present |

## 关键不变量

| 不变量 | 含义 |
| --- | --- |
| 数据缺失一律记 missing / 空态 | 适配器拿不到就写 `Missing`、空数组、空对象；不造假行 |
| SYSTEM 无自然键 | `system.upserted` 不带幂等键，只在内容变化时发射（详见 [`proxy-capture-channel.md`](proxy-capture-channel.md)） |
| `tools_catalog` 取自 system.upserted | Droid / Claude 的会话没有 `system.upserted`，所以 `tools_index` 永远为空 |
| Droid usage 契约上限 | 第一方 JSONL 不落盘每轮 token；`*.settings.json` 的合计与 `compaction_state.summaryTokens` 都不是每轮 |
| Claude SYSTEM 永远拿不到 | transcript 不落盘系统提示；旁挂目录里也没有；只有代理通道开启时才能补 |

## 不在表里的事实为什么不在

| 候选 | 为什么不画 |
| --- | --- |
| Droid `enabledToolIds` | 启停清单，无描述、无 schema、不表示实际调用过哪些工具 |
| Droid `settings.json.tokenUsage` | 会话合计，不是每轮 |
| Claude `type=system` 块 | 抽样内容是压缩边界与本地命令，不是发给模型的系统提示 |
| Codex `dynamic_tools` | CLI 会话里没有；只在 vscode / Desktop 部分会话出现，覆盖面不全 |
| 任何宿主的 TTFT / decoding | 计时类细节在宿主的事件模型里没有；本机四家语料拿不到首 token 与生成分段计时 |

## 何时从「拿不到」变「拿得到」

| 触发 | 才有 |
| --- | --- |
| Droid 把 system prompt 或带 schema 的工具目录写进 jsonl / 旁路文件 / 官方 hook | 才有 Droid 的 SYSTEM 行 |
| Claude Code transcript 或旁路文件出现可核验的系统提示 / 工具目录 | 才有 Claude 的 SYSTEM 行 |
| Codex 在 CLI 会话也落一份完整工具目录 | 才能填 `tools_catalog` |
| 启用代理通道（`--proxy-port`） | Claude / Codex / 任意未鉴权宿主都能补 SYSTEM + 每轮 usage |

## 引用边界

| 边界 | 不外推成 |
| --- | --- |
| 本表事实 | 任意未来版本的宿主行为 |
| 代理通道的 SYSTEM 补全 | 任意宿主都覆盖；当下只对能解析的协议族（anthropic）有效 |
| Codex `base_instructions` | 「Codex 一定会发 system prompt」；CLI 偶发缺字段时同样按 missing 处理 |
| Droid 恒 Missing | 「所有 Factory 版本都不会落盘 token」 |

## 代码出处

| 词 | 落点 |
| --- | --- |
| `system.upserted` 发射 | `ata/plugins/{pi,codex,capture}.py` |
| `tools_index` 合并 | `ata/project.py` `project_session`（按名字合并 `tools_catalog`） |
| usage 投影三态 | `ata/project.py` `_usage` + `MISS` 常量 |
| Droid / Claude 不发射 SYSTEM 的设计裁决 | `ata/plugins/droid.py` / `ata/plugins/claude.py`（无 system.upserted 处理） |
