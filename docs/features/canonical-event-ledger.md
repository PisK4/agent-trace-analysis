# 规范事件账本 / Canonical Event Ledger

账本 = ATA 的唯一事实源。一个 SQLite 文件；写入只经一条追加路径；同一实体的多次快照靠幂等键收敛到最新一行。

| 词 | 定义 |
| --- | --- |
| 规范事件 | Runtime 事件由 `ata/schema.py` `ALLOWED_TYPES` 校验；Evaluation facts 走独立的 subject-aware envelope 与表，不混入 Session 事件 |
| 单 writer | 账本写入只在 `Ledger._append_locked` 一处；`threading.Lock` 串行化；任何适配器、HTTP 端点、代理通道都走这一道门 |
| 幂等键 | 翻译层为不同阶段发的确定性 event id（`:message_start` / `:message_end`、tool start/end）；同键后写覆盖前写 |
| 投影 | 从事件流折叠出的可读视图（会话列表、标注、usage 合计、工具卡片等）；可重建，不是事实源 |
| 折叠 | 把事件流折成「会话级」元事实（标题、turns、最近 ts、血缘）的纯函数；定义在 `ata/fold.py` |

## Runtime 事件

当前 Runtime 事件使用 `run_id`、`turn_number` 与 `observed_turn_ordinal` 表达 identity；旧的全局 `turn` 字段和 assignment 事件不再属于生产 schema。

| 类型 | identity 约束 | 含义 | 自然键 |
| --- | --- | --- | --- |
| `session.opened` | null | 会话起点，附 title / 可选 `parent_session` | `session.opened:` |
| `session.renamed` | null | 用户改名，触发 latest-wins | — |
| `session.closed` | null | 会话终点 | — |
| `system.upserted` | null | System Prompt + tools 目录；只在内容变化时发 | — |
| `turn.started` | 正整数 | 一轮开始 | — |
| `message.upserted` | 正整数 | 用户或助手消息 | `message.upserted:<message_id>` |
| `tool.upserted` | 正整数 | 一次工具调用；start / end 用同一 `tool_call_id` | `tool.upserted:<tool_call_id>` |
| `turn.ended` | 正整数 | 一轮结束，附 `usage` / `status` | — |
| `compaction.boundary` | 正整数 | 上下文压缩点 | — |
| `session.scored` | null | 人工标注（good / bad / partial + note） | — |
| `session.score.cleared` | null | 标注墓碑 | — |
| `run.started` | run only | Runtime Run 起点 | — |
| `run.ended` | run only | Runtime Run 终点 | — |
| `run.lifecycle.conflict` | null | 生命周期冲突事实 | — |

`session.*` 与 conflict 不携带 Runtime identity；Turn 事件必须携带 canonical Run/Turn identity 或显式 observed ordinal。校验见 `ata/schema.py` `parse_event`。

## 单 writer 的强制

| 入口 | 路径 |
| --- | --- |
| 文件 tail 适配器 | `ata/plugins/{pi,droid,claude,codex}.py` → `ata/ingest.py` → `ledger.append` |
| Pi live hook | `POST /api/pi-hooks`（`ata/http.py` `h_pi_hooks`）→ `ledger.append` |
| 代理通道 | `POST /api/captures`（`ata/http.py` `h_capture`）→ `ata/plugins/capture.py` `ingest_capture` → `ledger.append` |
| 通用 `POST /api/events` | 直接走 `parse_event` + `ledger.append` |
| 改名 | `POST /api/sessions/<sid>/title` → `ledger.append`（发 `session.renamed`）；assignment 写路径已移除 |

任何路径都不绕过 `Ledger._append_locked`。`threading.Lock` 串行化确保代理通道与文件 tail 同写一个会话时靠幂等键收敛。

## 幂等键与去重

| 规则 | 实现 |
| --- | --- |
| `message.upserted` 收敛 | `ata/ledger.py` `_dedupe_key`：`f"message.upserted:{payload['message_id']}"` |
| `tool.upserted` 收敛 | 同上：`f"tool.upserted:{payload['tool_call_id']}"` |
| `session.opened` 收敛 | `f"session.opened:"`；同会话只首条生效，后续 opened 不覆盖用户改过的标题 |
| 无自然键的事件 | 追加式（`system.upserted` / `turn.ended` / `compaction.boundary` / `session.scored` 等） |
| 重复写入 | `INSERT OR IGNORE`；同 id 返回原 seq，不改已写行 |

## 折叠：唯一规则归属地

`ata/fold.py` `fold_session_meta(existing, event)` 是「会话级元事实如何从事件流折出来」的唯一纯函数。两侧调用方：

| 调用方 | 用途 |
| --- | --- |
| `ata/ledger.py` `_append_locked` | 维护 `sessions` 表的索引（title / turns / last_ts / first_ts / parent_session_id） |
| `ata/project.py` `project_session` | 投影时独立重推；两侧对同一事件流必须产出同题 |

`fold_session_meta` 三条核心规则：

| 场景 | 规则 |
| --- | --- |
| 用户改名 | `session.renamed` 后 `renamed=True`，后续 `session.opened` 只做兜底，不再覆盖 title |
| 血缘 | `session.opened.payload.parent_session` 非空时写入；空时保留已有值，不抹成 NULL |
| 创建时间 | 取最早的真实事件 ts；`ts < 10**12` 视为脏数据（历史推送端写过 ts=1 的 opened），不参与计算 |

## 数据边界

| 边界 | 行为 |
| --- | --- |
| 旧账本升级 | 走 `ALTER TABLE` 迁移；`parent_session_id` 列首次加入时按此模式无损加 |
| 事件 schema 升级 | `v` 仍为 1；新增事件类型必须先扩 `ALLOWED_TYPES` |
| 同一 writer 不允许出现第二处 | 见 [`codebase-boundaries.md`](codebase-boundaries.md) |
| 同一 schema 不允许出现第二份 | 同上 |

## 引用边界

| 边界 | 不外推成 |
| --- | --- |
| Runtime 事件 | 全部 agent 行为；适配器可以不发，但不许发表外类型 |
| 幂等键收敛 | 「账本能解决一切重复」；轮次口径漂移不在幂等键范围（见 [`proxy-capture-channel.md`](proxy-capture-channel.md)） |
| `fold_session_meta` 纯函数 | 「事件流与投影必然一致」；两侧必须都对同一事件流调用同函数 |

## 代码出处

| 概念 | 文件 · 符号 |
| --- | --- |
| Runtime 事件白名单 | `ata/schema.py` `ALLOWED_TYPES` |
| 事件校验 | `ata/schema.py` `parse_event` |
| 幂等键 | `ata/ledger.py` `_dedupe_key` |
| 单 writer | `ata/ledger.py` `Ledger.append` + `_append_locked` |
| 折叠 | `ata/fold.py` `fold_session_meta` + `REAL_TS_FLOOR` |
| envelope 工厂 | `ata/schema.py` `envelope`（CLI / HTTP / droid 三处组装收口） |
