---
title: 干预-轨迹关联的最小机制
labels: [wayfinder:grilling]
status: open
assignee: none
blocked_by: [T2-cue-failure-modes]
---

## Question

要不要在轨迹或项目侧记录"这次干预针对哪个失败模式、改了什么"？最小做法是什么？

Langfuse 的做法给了一个方向：它让每条轨迹都记着"当时用的是哪版 prompt"，干预物（prompt 版本）和轨迹天然对得上。我们不需要建它的 prompt 管理系统——git commit 本身就是现成的版本对象。

目前的倾向：不改 ata 的 schema，干预记录留在 Cue 仓库的 commit message 或 changelog 里；诊断产出的失败模式标注（见 T4 的 D 方案）引用对应的 commit，这样"哪个问题、哪次修改、哪次复跑验证"三点能连起来。

裁决标准：对照复跑要能说清"这次对比是哪次干预的结果"，满足这一点即可，不预先建管理系统。如果你觉得 git 方案不够，再考虑在 ata 加轻量标注事件。
