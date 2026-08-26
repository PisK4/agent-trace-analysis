# ADR-0001: 引入代理采集通道（重开 v1 非目标裁决）

日期: 2026-08-26
状态: 已接受

## 背景

v1 kernel design（docs/superpowers/specs/2026-08-15-ata-v1-canonical-event-kernel-design.md
L240-247）把「实现反向代理」「把旧 AVA 的 Python 代理搬进本仓库」列为非目标，
L19 同时裁决「权威平面=规范事件，来源可以是 live 流或第一方账本适配器；
HTTP 抓包可选」。同一份 spec L214 承认：「要求每次 HTTP 都有 usage 会逼出代理」。

## 裁决

重开非目标中的「反向代理」一条，但收窄范围：

1. 代理是**补充通道**，不是权威平面。它只发账本里别处拿不到的事件
   （system.upserted、turn.ended），从不替代第一方 transcript 适配器。
2. 只搬 ava 的**解析内核**（ata/wire/，纯函数）；转发壳在 ata 重写
   （ata/capture_proxy.py），不搬 ava 的上帝模块与存储层。
3. 身份规则：能恢复宿主 sessionId 就并入同一 session；不能就丢弃，
   绝不新建孤儿会话（与「血缘 NULL 即事实」同一哲学）。

## 为什么现在重开

claude transcript 侧永久缺失 SYSTEM 快照、tools 目录、每轮 usage
（官方 transcript 不落盘这些事实，features/2026-08-17 文档确认旁路目录
也没有）。hook 路线已被 spec 否决（27 个 hook 无每轮 token）。代理是
这些事实的唯一可得来源——这正是 spec L214 自己预言的「逼出代理」。

## 后果

- 数据边界速记表中 claude 的 SYSTEM 快照从「无」变为「代理通道开启时有」。
- 两条采集通道写同一 session，靠幂等键收敛；代理刻意不发 message/tool
  行以避免 natural-key 写序竞态。
- OpenAI 族解析（codex 可用）暂缓，ata/wire 的注册表 seam 已预留。
