---
title: 人工标注机制
labels: [wayfinder:grilling]
status: closed
assignee: pis
claimed_at: 2026-08-23
closed_at: 2026-08-23
blocked_by: []
---

## Question

用户观点（2026-08-23）：Cue 产出好不好，最终只有用户说了算（例：意图卡片的质量）。调优时需要在 ata 上给会话打标注，作为主观真值。这张票定标注机制的四个问题：

1. **标注以什么形态入账本**：新增一种事件类型，还是开独立的标注表？
2. **从哪里打**：Web UI、CLI，还是两者？
3. **值的形状**：分类、数值，还是都要？
4. **与机器信号的关系**：怎么分工？

## Resolution

2026-08-23 与用户当面拍板：

1. **形态**：新增事件类型 `session.scored`，走同一条事件追加门。标注也是发生过的事实，进同一本账；读取端复用事件流，不另开表。schema 词表加一种类型，v 保持 1；payload 校验要求 `value` 必须是 `good / bad / partial` 三选一，`note` 可选字符串。
2. **入口**：Web UI 与 CLI 第一期一起做。Web UI 在会话回看视图加标注控件（好/不好/部分 + 备注框）；CLI 提供 `ata rate <sid>` 子命令作批量与脚本化兜底。
3. **值形状**：分类三档 good/bad/partial 加一句自由备注。数值型以后有需要再加。
4. **与机器信号分工**：主观标注是真值锚，机器检测的失败信号是线索；两类分开存（来源字段区分）、分开统计；T5 做 run 对比时主观标注优先级最高。

连带修订：地图 Out of scope 原写"Web UI 的对应改造不做"，现收窄为"只读展示类增强仍不做，标注入口控件属本 effort"。

背景参考：Langfuse 的 Scores via UI 与 Annotation Queues。

## Progress notes

- 2026-08-23 CLI 入口落地（计划 Task 2/10/11）：`session.scored` 事件类型入 schema（value 三选一 + 可选 note，turn 强制 null）；`ata rate <sid> --value good|bad|partial [--note ...]` 经服务事件追加门写入，拒绝 `--ledger` 直写。真机冒烟通过：对 cue 会话 `01a029d0` 打 `good` 标注，seq 141 落账，payload 形状与 Resolution 一致。Web UI 标注控件留待第二份计划（需先摸前端现状），本票 Resolution 第 2 点的 Web UI 部分未完成。
