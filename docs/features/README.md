# features/

一篇讲一个项目概念。一份文档回答"这是什么 / 为什么这样 / 在代码哪里"，不是"哪天我做了什么"。

## 适用规则

| 来源 | 管什么 |
| --- | --- |
| 本目录 `README.md` | 选题与结构 |
| 根 [`../../docs/文档结构纪律.md`](../../docs/文档结构纪律.md) | 章节顺序、表 / 图 / 散文选择、定义与红线 |
| `de-AI-writing` Skill | 中文句式、消除 AI 痕迹 |
| 根 [`../../CONTEXT.md`](../../CONTEXT.md) | 词汇裁决（avoid 词、prefer 词） |

动笔前先加载 `de-AI-writing` Skill。

## 一篇 features 文档必须有的

| 段落 | 内容 |
| --- | --- |
| 一句话定义 | ≤ 30 字，能复述 |
| 设计立场 | 为什么这样；不那样做的路为什么排除 |
| 数据边界 | 什么时候这条不成立、返回 missing / 空态、不是 bug |
| 代码出处 | 文件 + 关键符号（`ata/foo.py` `fold_session_meta`） |
| 引用边界 | 不能外推到哪类对象 / 版本 |

## 禁止出现

- 日期前缀或日期字段
- 提交哈希列表
- "本轮落地"型修复记录
- 临时端口 / 临时账本之类一次性口径
- 把 `2026-08-26-strangler-parity-checklist` 这种"一次性合规表"塞进来

## 文件清单

| 文件 | 一句话定义 |
| --- | --- |
| `session-data-sources.md` | 五家宿主能拿什么 SYSTEM / tools / usage / model / title |
| `canonical-event-ledger.md` | 账本 = 唯一事实源：schema / envelope / 幂等键 / 单 writer / fold_session_meta |
| `runtime-runs-and-evaluations.md` | Runtime Run/Turn identity、lifecycle correlation 与 Evaluation facts / membership |
| `adapters-and-shared-kernel.md` | 五家适配器 + capture + common.py 共享翻译内核 |
| `proxy-capture-channel.md` | `--proxy-port` 怎么转、wire 解析、轮次漂移缓解边界 |
| `read-api-and-cli.md` | 权威层 + 便捷层五个端点 + read / rate CLI + Skill |
| `regression-and-rating.md` | 历史 regression 文档；当前产品以 `runtime-runs-and-evaluations.md` 为 Runtime / Evaluation 契约 |
| `webapp-strangler-restyle.md` | 为什么 React + 保留 ata.css：组件切分、视觉单一事实源 |
| `tool-stats-debug-view.md` | 工具统计 + 钻取 + 跳转的设计意图与契约 |
| `viewer-presentation.md` | 当前 Atatrace 展示层能力：GFM / 高亮 / thinking / schema / usage |
| `session-services.md` | 本地常驻：launchd plist / 端口 / 账本 / extension / 代理 |
| `codebase-boundaries.md` | 单一 writer / 单一 CSS / 复用阶梯 / 隐私红线 / 证据强度不动 |

## 与其它目录的分工

| 类型 | 去哪 |
| --- | --- |
| 决策记录（"为什么这样裁决"） | `docs/adr/` |
| 接口定稿（"实现的唯一依据"） | `docs/specs/` |
| 操作指南（"手测 / 部署 / 排错"） | `docs/guides/` |
| 一次性交付总结、过期核验记录 | `docs/archive/` |
| 待办飞轮 / 实验票 | `docs/wayfinder/` |
| 项目级硬约束（工作流） | 根 `AGENTS.md` |
| 词汇裁决 | 根 `CONTEXT.md` |
