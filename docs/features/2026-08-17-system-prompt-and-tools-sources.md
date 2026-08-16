# ATA · System Prompt 与 Tools 目录的来源边界与落地计划

- **日期**：2026-08-17
- **性质**：对照 dsh Trajectory 的 SYSTEM 行（System Prompt / Tools 页签），核四家语料能不能拿出真实数据；能修的写进本轮计划，拿不到的保持空态，不造假行。
- **触发**：Droid 会话「Explorer: 定位 pane title 渲染」轨迹表没有 SYSTEM 行，用户要求对齐 dsh。
- **改动范围（本轮只改这些）**：`ata/plugins/codex.py`、`tests/test_codex.py`、`testdata/vendor/codex-sample.jsonl`、`docs/features/manual-test-guide.md`、`README.md`
- **本轮不改**：`ata/plugins/droid.py`、`ata/plugins/claude.py`、前端页签结构、seed 合成会话补 SYSTEM

## 一句话

dsh 的 SYSTEM 行挂的是「发给模型的那份 prompt + 当时可用的工具目录」。ATA 前端已经会画这两个页签，缺的是账本里的 `system.upserted`。本机抽样后：Droid / Claude Code 现有落盘拿不到这两样；Codex 能拿到 prompt，但适配器会把对象壳画出来；Pi 只能靠 live hook，线上账本目前是 seed，没有 SYSTEM。

## SYSTEM 在 ATA 里指什么

| 词 | 定义 |
| --- | --- |
| SYSTEM 行 | 投影层把 `system.upserted` 画成轨迹表第一类行；点开后检查器出 `System Prompt` / `Tools`（有上一份 prompt 时再加 `Diff`） |
| System Prompt | `system.upserted.payload.prompt_text`：这次请求真正发给模型的系统提示全文 |
| Tools 目录 | `system.upserted.payload.tools_catalog`：当时挂给模型的工具清单（名字、描述、参数 schema） |
| 工具调用行 | 会话里已经发生的 `tool.upserted`，轨迹表里的 TOOL 行。它不是 Tools 目录 |

CONTEXT 行（正文以 `<system-reminder>` 开头）不是 SYSTEM。那是中途注入的提醒，dsh 也标成 CONTEXT。

## 四家核验结果

抽样时间 2026-08-16。结论只对这次读过的本机文件成立，不外推成「该厂商永远没有」。

| Agent | System Prompt | Tools 目录 | 证据 | 本轮动作 |
| --- | --- | --- | --- | --- |
| Droid | 当前样本拿不到 | 当前样本拿不到 | 会话目录只有 `<uuid>.jsonl` + `<uuid>.settings.json`（+ bak）。jsonl 类型只有 `session_start` / `message` / `agent_turn_outcome` / `todo_state` / `compaction_state`。`session_start` 无 prompt/tools。`~/.factory` 关键词检索未找到会话级 `systemPrompt` / `tools_catalog` / `inputSchema`。settings 的 `enabledToolIds` / `disabledToolIds` 只有名字 | 不改适配器，不造 SYSTEM 行 |
| Claude Code | 当前样本拿不到 | 当前样本拿不到 | 适配器只处理 `user` / `assistant` / `ai-title`。本机 transcript `type=system` 是 `local_command` / `compact_boundary` / `turn_duration`，不是 prompt。旁挂 `subagents/`、`tool-results/` 也没有系统提示或工具目录 | 不改适配器，不把 `type=system` 当成 SYSTEM |
| Codex | 能拿到 | 完整目录当前样本拿不到 | 近 40 条 `session_meta` 都有 `base_instructions`。本机抽样的真实 rollout 里该字段是 `{"text": "..."}`，适配器 `str(dict)` 会画出 Python 字典壳。`dynamic_tools` 只出现在部分 vscode/Desktop 会话，内容是 `codex_app` 附加工具，不是 CLI 全量目录 | 修 `base_instructions` 取文本；`tools_catalog` 继续空数组 |
| Pi | 能拿到，但只能实时 hook | 能拿到名字 + 一行描述 | `before_agent_start.systemPrompt` + `systemPromptOptions.toolSnippets` 已转 `system.upserted`。Pi 自己的会话 jsonl 不落盘 prompt，事后回读补不出 SYSTEM。线上 `pi-compact` / `pi-long` 是 `make seed` 写入的，seed 没有 `system.upserted`。extension 已装，服务日志未见 `POST /api/pi-hooks` | 不改代码；重启 Pi 后再跑一轮真实会话 |

## 明确不做的路

| 候选 | 为什么不做 |
| --- | --- |
| 用 Droid `enabledToolIds` 填 Tools 页 | 那是启停清单：无描述、无 schema、不表示实际调用过哪些工具 |
| 用 Droid `settings.json` 的 `tokenUsage` 当每轮 usage | 那是会话合计，不是每轮 |
| 把 Claude `type=system` 画成 SYSTEM 行 | 抽样内容是压缩边界和本地命令，不是发给模型的系统提示 |
| 把 Codex `dynamic_tools` 标成完整 Tools | 覆盖面不全（CLI 会话没有），内容只是 app 附加工具 |
| 给 Droid / Claude 造一行空 SYSTEM，Prompt 写「没有」 | 空行本身就是假数据；没有源就不画这一行 |
| 改 seed 给 `pi-compact` 补 SYSTEM | seed 是演示账本，补上会让人误以为线上 Pi 已经在推 hook |

## 本轮落地

只修已经证实写错的那一处，并同步文档里已经过时的检查口径。

### 1. Codex：取出 `base_instructions` 的正文

本机抽样里，`session_meta.payload.base_instructions` 是对象 `{"text": "..."}`。适配器现在对整个对象做 `str(...)`，检查器里会看到 `{'text': 'You are Codex...'}`。取文本时同时兼容字符串，避免另一种形态被丢掉。

| 项 | 做法 |
| --- | --- |
| 代码 | `ata/plugins/codex.py` 取文本：字符串沿用；对象取 `text`；取不到就不发 `system.upserted` |
| fixture | `testdata/vendor/codex-sample.jsonl` 改成对象形态，与本机 rollout 一致 |
| 测试 | `tests/test_codex.py` 继续断言 `prompt_text` 是干净字符串；补一条「对象形态取出 text」 |
| 不改 | `tools_catalog` 仍为 `[]`。有 `dynamic_tools` 也不写入目录 |

### 2. 文档：写清「没有 SYSTEM」是数据边界

| 文件 | 改什么 |
| --- | --- |
| `README.md` 支持的 agent 表 | Droid / Claude 的 SYSTEM 列保持「无」，补一句「现有落盘没有 prompt/目录，不是前端藏了」 |
| `docs/features/manual-test-guide.md` | Droid 检查点显式写「没有 SYSTEM 行」；Claude 维持现有「没有 SYSTEM」；Codex 加一条：System Prompt 正文不得带 `{'text':` 壳；Pi 加一条：seed 会话没有 SYSTEM，要看页签须重启 Pi 后跑真实会话 |
| 本文 | 作为本轮核验记录与不做清单的入口 |

### 3. Pi：环境动作，不进代码

extension 软链已在 `~/.pi/agent/extensions/pi-atatrace`。要让线上账本出现 SYSTEM：先确认 ATA 服务在 8787，再**新开**一个 Pi 进程跑一轮对话。旧进程不会加载后装的 extension。不改 seed。

## 验收

| 项 | 通过标准 |
| --- | --- |
| `make test` | 全量通过；Codex 用例断言 `prompt_text` 不含字典壳 |
| Codex 真机会话 | 打开任意一条有 `base_instructions` 的会话，SYSTEM 行存在，System Prompt 页签是连续英文/中文正文，不以 `{'text':` 开头 |
| Droid / Claude 真机会话 | 轨迹表仍然没有 SYSTEM 行；TOOL 行继续画已经发生的调用 |
| Pi seed 会话 | 仍然没有 SYSTEM 行（预期） |
| 不做回归 | 不为 Droid/Claude 新增 `system.upserted`；不把 `enabledToolIds` 或 `dynamic_tools` 写入 `tools_catalog` |

## 以后才做

| 条件 | 才考虑 |
| --- | --- |
| Factory 把 system prompt 或带 schema 的工具目录写进 jsonl / 旁路文件 / 官方 hook | 再开 Droid SYSTEM 通道 |
| Claude Code transcript 或旁路文件出现可核验的系统提示 / 工具目录 | 再开 Claude SYSTEM 通道 |
| Codex 在全部会话（含 CLI）落一份完整工具目录 | 再填 `tools_catalog` |
| 用户接受「只展示 Codex app 附加工具，并在页签上写明局部」 | 才把 `dynamic_tools` 单独标出来，不得叫完整 Tools |

## 引用边界

| 对象 | 这次实际读过的材料 | 不得写成 |
| --- | --- | --- |
| Droid | 本机 `~/.factory/sessions` 抽样 + `11d1c749-3775-4825-afb5-65e36962890b` 的 jsonl/settings + `~/.factory` 关键词检索 | 所有 Factory 版本都不会落盘 prompt |
| Claude Code | 本机 `~/.claude/projects/.../952477d9-6418-408a-8998-72960cfbf578.jsonl` 与旁挂目录；ATA 适配器与手册 | 官方源码里不存在系统提示 |
| Codex | 近 40 条本机 `session_meta`；`dynamic_tools` 抽样 3 个 vscode/Desktop 会话 | `dynamic_tools` 就是完整工具目录 |
| Pi | `ata/plugins/pi.py`、`extensions/pi-atatrace`、`~/.ata/atatrace.log` 未见 `POST /api/pi-hooks`、seed 源码 | 机制不可用；真实 Pi 会话文件里能回读 prompt |
