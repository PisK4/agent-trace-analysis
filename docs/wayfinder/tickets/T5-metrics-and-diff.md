---
title: 指标体系与对比输出
labels: [wayfinder:grilling]
status: open
assignee: none
blocked_by: [T2-cue-failure-modes, T3-replay-feasibility]
---

## Question

"变好了"用什么数字表达，新旧两次运行怎么摆在一起看？

1. 指标选哪几个：每轮 token（区分 reported/missing）、工具失败率、每任务步数、turn 完成率、耗时、压缩次数？以 T2 盘点的失败模式为准挑可归因的指标。
2. 对比以「一次实验运行」为单位（参考 Langfuse 的 experiment run）：一次干预后，对同一份任务集重跑一遍，就是一个 run；对比发生在 run 和 run 之间，产出一张差异表。票里要给出这张表的最小样子（用合成数据演示列名和一两行示例）。
3. 指标的存储格式借用 Langfuse score 的类型学：名字 + 数值 + 类型（数字/布尔/分类），挂到会话或 run 上。这样指标本身也是数据，以后能统计趋势。
4. droid usage 恒 missing、claude 无 SYSTEM 快照这类数据边界，指标定义里怎么如实降级而不是假装可比。
5. 指标分两类来源、分开统计：客观过程信号（工具失败率、步数、耗时）和用户主观标注（「人工标注机制」票，真值锚）。参考 tau-bench 的 pass^k：同一任务跑 k 次取全部通过概率，专治"时好时坏"的 agent——与 T3 决议"多次 run 看统计"直接衔接。
