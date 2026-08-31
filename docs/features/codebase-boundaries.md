# 代码库硬约束 / Codebase Boundaries

ATA 的几条不可越线。任何改动若触线，先回这里；测试与 lint 不会自动拦下。

| 词 | 定义 |
| --- | --- |
| 单一事实源 | 一个 schema / port / 事实源 / 写者同时只能有一处；不许建第二份 |
| 零构建 | 旧约束；现已放宽为「React 栈锁在 `webapp/`，不引入第二份 CSS / 第二个 Node 工作区」 |
| 测试替身 | mock / fixture / synthetic 数据；只在测试或 fixture 目录；不进生产入口 |
| 隐私红线 | 密钥、真实 Base URL、会话正文、用户采集内容不进代码、fixture、日志、文档 |

## 复用阶梯

实现一个组件前，按以下顺序核验。跳到后一档时，必须在 ADR 留下前一档不可行的源码或运行证据。

| 档 | 形态 | 选择条件 |
| --- | --- | --- |
| 一档 | 原包直接依赖 | 满足零引入额外运行时的依赖 |
| 二档 | 宿主 adapter | 依赖能装但与本地优先冲突，写薄壳适配 |
| 三档 | 固定上游版本的最小兼容 fork | 上游可拆但当前版本与合同冲突 |
| 四档 | 自研 | 三档都不可行的实证已落在 ADR |

兼容性 fork 保留上游目录、测试、许可证、提交血缘；每个 patch 都要有合同来源、测试、失效条件、可重放的上游同步记录。禁止复制上游源码后改名成为无血缘的本地实现。

## 单一事实源红线

| 对象 | 红线 |
| --- | --- |
| 账本 | Session 与 Evaluation facts 都在同一 `Ledger` writer / transaction discipline 下写入；适配器 / HTTP 端点 / 代理通道都过这一道门 |
| 事件 schema | Runtime event type 收在 `ata/schema.py` `ALLOWED_TYPES`；新事件必须先扩白名单；Evaluation fact type 单独校验并存于 `evaluation_events` |
| 端口 | launchd 服务一个；dev 临时端口一个；不并发跑 |
| 视觉体系 | React 版样式只在 `webapp/src/styles/`；不为同一规则建立第二份 CSS |
| 折叠 | Session 标题 / 最近 ts / 血缘的 latest-wins 规则归属 `ata/fold.py` `fold_session_meta`；Runtime Run/Turn 与 Evaluation membership 分别由各自 domain fold 负责 |
| 翻译词汇 | envelope / 工具双行 / observed 轮次 / usage 三态收在 `ata/plugins/common.py`；canonical Run/Turn identity 由 `ata/runtime.py` 统一分配 |
| 投影 | Session / Run / Turn / Evaluation 读取先经过 `ata/queries.py`；usage / tools / tool-stats / timing / compactions 的投影实现仍集中在 `ata/project.py` |
| 便捷层缓存 | `ata/projection_cache.py` 单一归属地；rev 门控短路 |

## 测试替身与数据

| 项 | 位置 |
| --- | --- |
| Mock / stub / synthetic fixture | `tests/` 或 `testdata/` |
| 演示账本 | `make seed` 灌入；不进生产入口 |
| 真实会话正文 | 不进 `testdata/`；不进 fixture；不进日志 |
| 真实密钥 | 不进代码、fixture、文档、日志 |
| 真实 Base URL | 不进代码、fixture、文档（用占位 / 显式提示） |
| 第二套 runtime | 不进生产入口；演示模式只走种子账本 |

## 依赖与运行时

| 项 | 规则 |
| --- | --- |
| 仓库嵌套 | `repos/ata` 本身是独立 Git 仓库；不得在其内嵌套 Git 仓库 |
| 外层 Node 工作区 | 不得在外层知识库根目录新增 Node 工作区 |
| 第三方 UI 库 | 引入新 UI 依赖前按复用阶梯走 ADR；只用于标准控件的局部增强 |
| 远端行为 | 不得引入运行期下载安装；vendored 库以文件形式随仓库分发 |
| 浮动依赖 | 不得引入；版本必须固定在 `requirements` / `package.json` |
| 服务端数据库 | 账本用 SQLite；不引入第二数据库（Postgres / DuckDB 等） |

## 注释与代码风格

| 项 | 规则 |
| --- | --- |
| 注释内容 | 只写「读代码得不到的信息」：为什么这样做、踩过什么坑、外部约束来源 |
| 阶段性注释 | 不写「脚手架占位 / Phase X 起填充 / TODO 重构」之类——计划与进度放任务系统或 `docs/plans`，不进代码 |
| 标识 | 字段名 / 函数名 / 路径 / 命令 / `snake_case` / 错误字符串保留原文；润色不改标识 |
| 证据强度 | 「未找到调用方 / 当前样本未观察到」不得改成「不存在 / 永远不」；证据强度与原文一致 |

## 隐私与外部发送

| 项 | 规则 |
| --- | --- |
| 数据流向 | 全部数据留本机；不设服务端 |
| 采集内容 | 密钥、真实 Base URL、会话正文、用户采集内容不进代码、fixture、日志、文档 |
| 代理通道的认证头 | 转发头黑名单不含 `authorization` / `x-api-key`（上游网关需要）；落档侧白名单只收 `x-claude-*` |
| 文档示例 | 一律合成；研究结论只写抽象模式 |
| Skill 携带的内容 | 不得把会话正文发往本机之外 |

## 数据边界速记（与 [`session-data-sources.md`](session-data-sources.md) 同步）

| 宿主 | SYSTEM | tools_catalog | usage | model |
| --- | --- | --- | --- | --- |
| Pi / Cue | 有 | 有（名字 + 单行描述） | reported | Not present（按需可补） |
| Claude Code | 无 | 无 | reported | `message.model` |
| Codex | 有 | 无 | reported | `turn_context.model` + `effort` |
| Droid | 无 | 无 | 恒 Missing | Not present（在 `*.settings.json`） |
| 任意 + 代理 | 补 | 补 | 补 | Not present |

## 引用边界

| 边界 | 不外推成 |
| --- | --- |
| 13 种事件 | 任意未来 agent 行为；适配器可以不发，但不许发表外类型 |
| 单一事实源 | 「所有端点都该共享状态」；事实源唯一是设计立场，不是性能优化 |
| 复用阶梯 | 任何项目都该这样；这是本仓库的工作流，不是普适工程观 |
| 隐私红线 | 任何 SaaS / 团队化方案；本项目是单机本机优先 |

## 代码出处

| 概念 | 文件 |
| --- | --- |
| 复用阶梯 | 根 `AGENTS.md` 第 2 节 |
| 工作流 | 根 `AGENTS.md` 第 1 节 |
| 隐私红线 | 根 `AGENTS.md` 第 3 节 |
| 词汇裁决 | 根 [`../../CONTEXT.md`](../../CONTEXT.md) |
| 账本 | [`canonical-event-ledger.md`](canonical-event-ledger.md) |
| 翻译 | [`adapters-and-shared-kernel.md`](adapters-and-shared-kernel.md) |
| 视觉 | [`webapp-strangler-restyle.md`](webapp-strangler-restyle.md) |
