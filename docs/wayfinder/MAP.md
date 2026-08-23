---
title: ATA 轨迹飞轮机制设计
labels: [wayfinder:map]
status: open
---

## Destination

一份《ATA 轨迹飞轮机制设计》文档：以 Cue 为首个服务对象、面向所有 agent 通用，把「采集 → 观测 → 诊断 → 干预 → 对照复跑」五拍各自的缺口与补法定清楚，齐备到可以分头动工。当前环断在③诊断、④干预后的验证、⑤对照复跑。

## Notes

- **领域**：`repos/ata`（独立 Git 仓库）。轨迹设计参考 `Agent研究/deepseek-harness/`（锚 `47f943859b`，全部为静态读码结论）；引用其结论前先读该目录 `AGENTS.md` 护栏。
- **已定取舍**（2026-08 会话确认，写入 spec 时不得推翻除非用户明说）：
  - CLI 默认走 HTTP API（`ATA_URL`），`--ledger PATH` 离线兜底；
  - 接口分两层：裸事件流为权威层 + 2-3 个分析投影便捷端点；
  - 会话血缘进首版：`sessions.parent_session_id` 加列，`session.opened.payload.parent_session` 采集，适配器渐进补齐；
  - Skill 用宿主无关的通用格式。
- **写作纪律**：动笔写任何文档前调 `de-AI-writing`；改生产代码前走 `/ponytail full`。
- **隐私红线**：会话正文、密钥不进代码、fixture、日志、文档；研究结论只写抽象模式，示例一律合成。轨迹数据不出本机。
- **仓库边界**：设计与本文档提交进 `repos/ata`；Cue 侧改动先读 `repos/cue/AGENTS.md`。
- **设计原则：坏案例要回流**。在轨迹里发现一个失败案例，就把它存进回归任务集；之后每次改完 agent，都拿这批任务重跑一遍，看老毛病有没有复发。飞轮能转起来靠的就是这一步——诊断的产出变成复跑的输入。（参考：Langfuse 文档管这个叫 Evaluation Loop）
- **定位声明**：飞轮以轨迹为证据、以失败案例为驱动，评估只是它的度量环节，不要把这套东西漂移成纯评估平台。产出的好坏最终由用户标注给出主观真值（见「人工标注机制」票），机器检测的失败信号只是线索；两者分开存、分开统计。
- **外部参照：Langfuse**（https://langfuse.com/docs ，Evaluation 部分）。2026-08 评估过它的全部功能，结论：
  - 它的观测能力我们已经有了，不用搬；
  - 值得借的是四个概念：①从真实坏轨迹里提取测试项（它叫 dataset item）；②对比要以「一次实验运行」为单位（它叫 experiment run）；③评分结果要结构化：名字 + 数值 + 类型（数字/布尔/分类），挂在会话上，方便以后统计（它叫 score）；④上面那条回流循环。
  - 不引入 Langfuse 本身：它是服务端 + Postgres 的多租户平台，和我们"全部数据留本机、一本 SQLite"冲突；而且它靠应用内埋点接入，我们的对象是不改代码的第三方 agent。上面的概念用普通文件就能实现（比如 JSONL 任务集 + git 管版本）。

## Decisions so far

<!-- 一张关闭的票一行：[票名](链接) — 一句话答案 -->

- [轨迹读取接口 spec 收口](tickets/T1-read-interface-spec.md)：spec 定稿在 `docs/specs/agent-read-interface.md`。五个只读端点加 CLI `read` 子命令；便捷层正文默认尾部 200 字符预览、`full=true` 取全文；404 表不存在、空数组表「存在但为空」；usage 缺失保留该轮标 missing；Skill 五节全写。
- [对照复跑的可行性](tickets/T3-replay-feasibility.md)：Cue 会话能重放但做不到逐字复现，对比靠固定可控项 + 挑低耦合任务 + 多次 run 看统计。测试项字段定为 input（首条用户消息全文）+ channel + model/thinkingLevel，可选 cwd、注入快照、回链 id；提取首版手动复制粘贴，不预做导出命令。噪声源主要是记忆库、采集数据、屏幕注入、web_search 和模型随机性；失败类指标对噪声最鲁棒，优先建。
- [人工标注机制](tickets/T9-human-annotation.md)：产出质量的主观真值由用户标注给出。新事件类型 `session.scored` 走同一条追加门，值为 good/bad/partial 加自由备注；Web UI 与 CLI 第一期一起做。主观标注是锚、机器信号是线索，分开存分开统计，run 对比时标注优先级最高。
- [外部评估体系经验盘点](tickets/T10-external-eval-survey.md)：可吸取清单定稿。T2 编码本用 AgentErrorTaxonomy 五类失败模式（arXiv:2509.25370）加六簇综合；T5 候选指标加 pass^k 与"子任务/端到端分歧"告警；T4 采纳"评过程不只评结果"但 LLM 判官不进首版；工程形态确认任务集文件化 + git 版本 + 无服务端。

## Not yet specified

- 指标体系的具体定义收口在 T5（现只剩 T2 一个前置）：编码本与候选指标已由 T10 备齐。
- 泛化路径：Cue 之后第二个宿主对象怎么挑，等飞轮在 Cue 上先转起来再说。

## Out of scope

- Web UI 的只读展示类增强不做；标注入口控件属本 effort（T9 决议收窄了原范围）。
- 训练/微调数据管线：远期，另立 effort。
- 新宿主的采集适配器开发：现有五宿主够用。
