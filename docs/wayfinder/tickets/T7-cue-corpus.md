---
title: 攒够 Cue 语料
labels: [wayfinder:task]
status: open
assignee: none
blocked_by: []
---

## Question

用 Cue 跑一批覆盖典型工作流的真实任务（代码调研、多轮工具使用、长会话触发压缩各来几条），让 extension 正常推送入账。攒到 10 个以上真实任务会话、覆盖至少三类工作流后关票。

做法（人工，HITL）：正常使用 Cue 即可，无需专门造数据；跑完在票里报一声量级。计数只算真实任务会话，内部会话（标题生成、subagent-delegate 开头的）不算——过滤信号见 T3 决议。

这是 T2 失败模式盘点的前置，不涉及任何决策。

## Progress notes

- 2026-08-23 更正：入账链路正常（用户实测新消息即时捕获，账本已见 4 会话）。此前"GUI 读不到 ATA_URL"的猜测不成立，撤回。
- 语料质量发现：现有会话里只有 1 条是真实任务会话，其余是内部会话（标题生成、subagent-delegate）。攒语料时按标题模式过滤内部会话，只数真实任务会话。
- 待跟进：用户提到 Cue 实现了 subagent package，捕获其父子逻辑前需读源码（源码位置待定位，本机暂未找到检出）。
