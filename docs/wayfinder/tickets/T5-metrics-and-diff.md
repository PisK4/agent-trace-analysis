---
title: 指标体系与对比输出
labels: [wayfinder:grilling]
status: closed
superseded_by: Evaluation membership in runtime-runs-and-evaluations.md
assignee: pis
claimed_at: 2026-08-23
closed_at: 2026-08-23
blocked_by: []
---

## Question

"变好了"用什么数字表达，新旧两次运行怎么摆在一起看？

1. ~~指标选哪几个~~：2026-08-23 用户裁决解耦推进，此问剥离至「指标清单定稿」票（blocked by 「Cue 真实轨迹的失败模式盘点」）。
2. 对比以「一次实验运行」为单位（参考 Langfuse 的 experiment run）：一次干预后，对同一份任务集重跑一遍，就是一个 run；对比发生在 run 和 run 之间，产出一张差异表。
3. 指标的存储格式借用 Langfuse score 的类型学：名字 + 数值 + 类型（数字/布尔/分类），挂到会话或 run 上。
4. droid usage 恒 missing、claude 无 SYSTEM 快照这类数据边界，指标定义里怎么如实降级而不是假装可比。
5. 指标分两类来源、分开统计：客观过程信号和用户主观标注。参考 tau-bench 的 pass^k。

## Resolution

2026-08-23 与用户对齐收口。七项决议：

1. **存放位置**：任务集与实验产物放 `~/.ata/regression/`（`tasks/` 任务集 JSONL、`runs/` 分数快照），目录内单独建纯本地 git（无远端）管版本。不进 repos/ata 仓库——任务项 input 是真实会话正文，红线禁止入库。
2. **run 归属进账本**：新增两个事件类型走既有追加门——`run.opened`（干预描述 + 任务集指纹）、`session.assigned`（run_id + task_id）。单一 writer 规矩不破，manifest 文件取消。创建轮次是低频动作，CLI 一条命令即可，不做前端控件。
3. **分数快照**：每轮存 `runs/<run_id>/scores.jsonl`，一行一条 `{task_id, session_id, name, value, type(number|boolean|categorical), source(machine|human)}`。定性为**可重建的快照**而非第二事实源：human 权威在账本 `session.scored`，machine 权威在账本原始事件；落盘只为指标定义演进后老 run 数字不失真。
4. **pass^k 定义锁死、缓实现**：任务项可选字段 `k`（默认 1）；k>1 时同一 run 内独立重跑 k 次、取全部通过概率。首版实现只要求支持 k=1。
5. **降级三值语义**：数据缺失记 missing，永不当作 0 参与求和平均；差异表任一侧 missing 则 Δ 显示 n/a 不参与汇总；整列数据条件不满足时标注适用宿主范围（如 droid 的 token 列）；每个指标定义强制带「数据条件」子句，条件不满足输出 missing 而非报错或跳过。
6. **题面冻结**：提取即复制首条用户消息原文入任务集，之后冻结；改题面 = 出新版任务集由 git 记录；新旧对比只在同一版任务集的 run 之间做，跨版本不比逐格差值。环境漂移（记忆库、屏幕状态、模型随机性）靠低耦合选题加多次 run 统计兜底（衔接 T3 决议）。
7. **命令面与前端边界**：薄 CLI 三条——`ata tasks add`（贴题面、生成 id、校验必填字段）、`ata tasks list`、`ata run new --desc`（自动记任务集指纹）。任务集管理不做前端（低频贴文本 + 避免 UI 直写 regression 目录破坏单一 writer）；归组/打分控件搭「人工标注机制」票的车（Web UI 会话页选 run 和任务，走追加门）。对比输出为 CLI 表格。

打分与被比较的主观真值仍以用户标注为锚（T9 决议不变）；机器不打分只统计。
