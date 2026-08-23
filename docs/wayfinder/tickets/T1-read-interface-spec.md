---
title: 轨迹读取接口 spec 收口
labels: [wayfinder:grilling]
status: closed
assignee: pis
claimed_at: 2026-08-23
closed_at: 2026-08-23
blocked_by: []
---

## Question

四项取舍已经定了（HTTP 默认加 `--ledger` 兜底、权威层加速捷层、血缘进首版、Skill 通用格式），这张票把它们收口成一份完整接口 spec，补齐还没定的部分：

1. 端点与 CLI 命令面的最终清单，含参数、翻页游标、截断纪律；
2. 便捷层（usage / tools / compactions）的字段裁剪：哪些字段进默认返回，哪些要显式 `full=true`；
3. 错误与空数据的返回约定：会话不存在、血缘为 NULL、usage missing 时各返回什么，让调用方不必猜；
4. Skill 大纲定稿：使用路径、token 纪律、隐私边界条款、各宿主数据边界声明（droid usage 恒 missing 等）。

spec 成文后作为《飞轮机制设计》文档的观测一章底稿。

## Resolution

2026-08-23 与用户当面过完三个开放问题，spec 定稿于
[`docs/specs/agent-read-interface.md`](../../specs/agent-read-interface.md)。要点：

1. 便捷层正文默认尾部 200 字符预览（用户指出：工具结果的价值集中在结尾，从尾部截断），`full=true` 取全文；usage 端点小字段默认全给。
2. 错误约定统一：404 才是「不存在」，200 的空数组是「存在但为空」；usage 缺失的轮保留并标 `missing`，绝不删行。
3. Skill 按五节全写：探活兜底 / 发现 / 下钻 / token 纪律 / 隐私与数据边界。
4. 血缘 schema 只加列不加事件类型；适配器接线顺序降为实施期事项，不另立决策票。
