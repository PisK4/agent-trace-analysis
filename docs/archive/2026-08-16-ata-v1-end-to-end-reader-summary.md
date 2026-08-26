# ATA v1 首段 · 交付总结（归档）

> **状态：归档**。本文是 2026-08-16 的 v1 交付快照；代码已经过 envelope 工厂化、`fold_session_meta` 提取、common.py 共享翻译内核、`bbfb06b` 加深候选二轮八候选重构等多轮修改。当前架构说明以 [`../features/canonical-event-ledger.md`](../features/canonical-event-ledger.md) 与 [`../features/adapters-and-shared-kernel.md`](../features/adapters-and-shared-kernel.md) 为准。
>
> 文中描述的代码路径（独立 `ata/plugins/pi.py` 形态、单 writer 路径、文末指向不存在的 `feat/v1-end-to-end-reader` 分支）只对归档当时成立。
>
> 原文以下为历史内容，未做修改。

---

- **日期**：2026-08-16
- **性质**：`repos/ata` v1 首段（Atatrace 阅读器 + Pi 参考插件 + Droid 适配器）落地结果的归档。本文只总结已交付并验证过的事实，不改写 spec / plan 的合同。配套修订（字段名冻结回填、SYSTEM 快照发射正式化）已写进这两份文档的未提交改动
- **配套文档**：spec《2026-08-15-ata-v1-canonical-event-kernel-design》、plan《2026-08-15-ata-v1-end-to-end-reader》
- **分支**：`feat/v1-end-to-end-reader`

## 一句话

v1 首段打通了「插件翻译 → 内核账本 → Atatrace 投影」三段链路：Pi 与 Droid 各有一条入账通道，内核单 writer 落盘，阅读器只拉投影、不回源厂商文件。链路经过自动测试、真机 Pi 会话与浏览器逐项验证。

## 已交付能力

| 层 | 组件 | 交付内容 | 验证 |
| --- | --- | --- | --- |
| 内核 | `ata/schema.py` | 校验规范事件：7 种 `type`、`agent_id` 白名单、payload 规则（用户行禁 usage、`system.upserted` 要求 `prompt_text` 等）；缺身份字段拒收 | unittest |
| 内核 | `ata/ledger.py` | SQLite 单 writer 追加：`(session_id, event_id)` 主键幂等、`(session_id, seq)` 分页、会话标题索引；重复 id 返回原 seq 不改已写行 | unittest |
| HTTP | `ata/http.py` | `/api/health`、`/api/sessions`、`/api/sessions/{id}?limit&before`、`/api/events`、`/api/pi-hooks` | unittest + 浏览器 |
| 入口 | `ata/__main__.py` | `serve` 默认不打开任何厂商路径；`--droid-path` / `--claude-path` / `--codex-path` 显式传入才灌入（单文件 tail、目录一次性灌入）；`seed` 生成合成演示账本 | 手工 |
| Pi 插件 | `ata/plugins/pi.py` + `extensions/pi-atatrace/index.ts` | 锚定 `845d6ff1` 的 hook 翻译成规范事件；TS extension 经 HTTP 推送到账本 | unittest + 真机两轮会话 |
| Droid 适配器 | `ata/plugins/droid.py` | JSONL 按偏移增量 tail：`session_start` / `message` / `tool_use`+`tool_result` / `agent_turn_outcome` 转规范事件；`todo_state` / `compaction_state` 跳过；每轮 usage 恒 `Missing` | unittest + API + 浏览器 |
| Claude Code 适配器 | `ata/plugins/claude.py` | 读 `~/.claude/projects/**/*.jsonl` 第一方 transcript：`user`/`assistant` 消息（官方 API 消息形态）+ `ai-title` 标题；无 system 行与 turn 事件 → 不发射 `system.upserted` / `turn.ended`；usage 驼峰转蛇形，缺失或全 0 标 Missing | unittest + API + 浏览器 |
| Codex 适配器 | `ata/plugins/codex.py` | 读 `~/.codex/sessions/**/rollout-*.jsonl`：`session_meta` 的 `base_instructions` 发 SYSTEM、`originator` 作标题；`task_started`/`task_complete` 定轮次；`response_item` 消息/工具为单一来源；`token_count.last_token_usage` 对齐每轮 usage；compaction 行跳过 | unittest + API + 浏览器 |
| 公共读取 | `ata/plugins/jsonl.py` | 增量 JSONL 读取（字节偏移、半行留待下次、坏行跳过）+ 1s tail | unittest + 真实数据 |
| 阅读器 | `web/index.html` | 复制 02 视觉合同、只换数据入口；`sketches/002-beautiful-workbench/` 冻结只读 | 浏览器 B1–B9 |

## 修复记录

| 提交 | 问题 | 根因 | 修法 |
| --- | --- | --- | --- |
| `f46f172` | Pi 官方 hook 事件没有持久化路径 | extension 只做了内存翻译，账本不增 | `http.py` 加 `/api/pi-hooks` 流式入账，`index.ts` 改为 HTTP 推送 |
| `bb4d500` | 系统提示与工具目录在 Atatrace 不可见；标题停留 session id；第二轮用户消息与轮次被静默丢弃；出现幽灵 pending 行 | hook 无 SYSTEM 通道；`turnIndex` 每 run 从 0 起算，run 2 与 run 1 的轮次号、message id 撞车后被幂等账本吞掉；`agent_end` 在下一个 agent run 前提前关会话；`message_start` 与 `message_end` 各自生成 id | `before_agent_start` 转 `system.upserted`（`prompt_text` / `previous_prompt` / `tools_catalog`）；标题取首条用户消息；轮次号改为用户消息到达时递增的会话级计数；`message_end` / `turn_end` 复用 `message_start` 定下的 id；tool start/end 拆成两个 id；`agent_end` 不再发 `session.closed`；thinking 并入消息文本；crumb 转义防 XSS；`step` 随轮次重置；turns 只数真实轮 |
| `e025e05` | Droid 工具行永远 pending、结果不可见 | `tool_use` 与 `tool_result` 共用 event id `{session_id}:tool:{cid}`，幂等账本只认第一条，完成态被吞 | 拆成 `:start` / `:end` 两个 id（与 `bb4d500` 的 Pi 修法同款），投影按 `tool_call_id` 合并、后写覆盖；顺带把空助手文本从 `(empty)` 占位改为真实空串，并简化 `request_no` 的绕路表达式 |
| `3b38b1f` | — | — | 新增 Claude Code 适配器：消息、工具配对、ai-title 标题、usage 驼峰转蛇形；共享 jsonl 读取器与 `--claude-path` |
| `ca84f9a` | — | — | 新增 Codex 适配器：`session_meta` SYSTEM/标题、task 事件定轮次、token_count 对齐 usage、工具 start/end 配对 |
| `cd29cf9` | 真实会话有截断行时整个文件 ingest/tail 崩溃 | 厂商文件写入中/损坏行 `json.loads` 抛错 | jsonl 读取器跳过坏行继续 |

## 验收证据

| 项 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 23 个全过 |
| 真机 Pi 两轮会话（`sensenova-6.7-flash-lite`，session `ata-verify`） | SYSTEM 行、7 个工具目录、标题「你好」、turns=2、工具 completed、无 pending 幽灵行 |
| 浏览器（Pi 修复后） | System Prompt / Tools / Diff 页签正常 |
| API（droid 修复后） | `droid-missing` 工具行 `status=completed`、`result=type=message`、`parentId=m2` |
| 浏览器（droid 修复后） | TOOL 行渲染为「Read session.jsonl → type=message」 |
| API（claude/codex 适配器，真实本机数据） | 324 个真实会话灌入（claude 55 / codex 269）；Claude 会话 user/assistant 行正确、usage 缺失标 Missing；Codex 会话含 system 行、2 个工具全 completed、usage 全 reported、无 pending |
| 浏览器（真实本机数据） | 会话列表显示 Claude ai-title 中文标题与 Codex originator 标题；打开会话账本正常渲染 |

## 已知边界

| 类别 | 内容 |
| --- | --- |
| spec 非目标 | 反向代理、Docker、Tauri 桌面壳、其余 13 个 agent 名字、旧 AVA 的 Evidence / 全量详情卡嵌进主时间线 |
| plan 明确不做 | 改 `sketches/002-beautiful-workbench/`、Node 工作区、内核读取 `~/.factory` / `~/.pi` / AVA `records.jsonl`、真实会话正文进 testdata、Compare / SSE / 会话合计摊销 / sub2api 计费 |
| plan「做完再考虑」 | 真机装 `extensions/pi-atatrace` 到 `~/.pi/agent/extensions/`；`--droid-path` 对真实第一方 JSONL 做授权审计——**未做**：读 `~/.factory/sessions` 正文前需要用户授权 |
| Droid 能力上限 | 每轮 usage 恒 `Missing`（JSONL 样本无 token 字段；`compaction_state.summaryTokens` 与 `*.settings.json` 的合计都不是每轮 usage）；工具卡片参数区显示空对象是契约上限（Pi 合同：`toolSnippets` 只是名字到单行描述的映射，无 JSON schema） |
| 实时通道 | Pi 走 HTTP hook（`/api/pi-hooks`），Droid 走文件 tail，两套并存是现状，未合并 |

## 锚点与引用边界

| 对象 | 锚点 | 不得外推成 |
| --- | --- | --- |
| Pi | `repos-external/pi-agent` @ `845d6ff1` / `v0.83.0` | 后续 `main`、Harness V2、planned 能力 |
| Droid | 本机 `~/.factory` 抽样 + marketplace README | 未核实的 live hook 词表；所有 Droid 版本 |
| Claude Code | `2.1.88` / `a8a678c` 纯净树 | 当前安装的 Claude Code |
| Codex | `2b5bdcf675` | 发布版默认开启 |

## 提交状态

droid 修复 `e025e05` 已提交到分支 `feat/v1-end-to-end-reader`。spec / plan 修订与本文档未提交（延续既有约定：spec/plan 与 `sketches/` 默认排除在提交外），`sketches/` 整个目录未跟踪。
