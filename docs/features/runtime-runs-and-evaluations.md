# Runtime Run 与 Evaluation

Runtime Run 记录 Agent 的真实执行生命周期；Evaluation 记录人工观察的 Session 集合。

## 设计立场

ATA 把 Session、Run、Turn 和 Evaluation 分成不同事实边界。Run 只能由明确的 `agent_start` / `agent_end` 生命周期证据建立，`run_id` 是 Session-local、从 1 开始且不复用的正整数；Turn identity 是 `(run_id, turn_number)`。宿主提供的 `run_id`、`turn_id`、`task_id` 或 request ID 只保留为外部 metadata，不替代 ATA identity。

没有 Run 证据的事件仍然入账。它们的 canonical `run_id` 与 `turn_number` 保持 `null`，需要排序时使用正整数 `observed_turn_ordinal`；这个字段不表示 Run 边界，也不允许读取端回填旧事件。

Evaluation 是人创建的持久观察集合。它可以为空，成员是已有 Session，关系上可带任意字符串 `task_label`。Evaluation 不启动、不拥有也不修改 Run；评分仍是 Session-level 事实，Evaluation 页面复用同一份评分记录。

## Runtime event contract

Runtime event 使用唯一的 Session 事件 envelope：

```python
envelope(
    agent_id: str,
    session_id: str,
    type_: str,
    payload: dict,
    *,
    run_id: int | None = None,
    turn_number: int | None = None,
    observed_turn_ordinal: int | None = None,
    ts: int | None = None,
    eid: str | None = None,
) -> dict
```

`parse_event` 保留所有 canonical 字段，不把 `run_id`、`turn_number` 或 `observed_turn_ordinal` 归一化为旧的 Session-global `turn`。`v` 固定为 `1`；`id`、`agent_id`、`session_id`、`ts`、`type` 和 `payload` 必须存在。`run_id`、`turn_number` 与 `observed_turn_ordinal` 要么为正整数，要么为 `null`。

当前 Runtime 事件白名单与字段组合如下：

| type | `run_id` | `turn_number` | `observed_turn_ordinal` | 事实含义 |
| --- | --- | --- | --- | --- |
| `session.opened` | null | null | null | Session 起点 |
| `session.renamed` | null | null | null | Session 标题变更 |
| `session.closed` | null | null | null | Session 关闭 |
| `session.scored` | null | null | null | Session 人工评分 |
| `session.score.cleared` | null | null | null | 撤销 Session 评分 |
| `system.upserted` | null 或已确认 Run | null | null | SYSTEM / tools 快照；不创建 Run 或 Turn |
| `run.started` | 必须为正整数 | null | null | 明确 `agent_start` 物化的 Run 起点 |
| `run.ended` | 必须为正整数 | null | null | 明确 `agent_end` 观察到的 Run 终点 |
| `run.lifecycle.conflict` | null | null | null | 生命周期 correlation 失败或冲突 |
| `turn.started` | 必须为正整数 | 必须为正整数 | null | 已确认 Run 内的 Turn 起点 |
| `message.upserted` | 必须为正整数 | 必须为正整数 | null | 已确认 Run 内的用户或助手消息 |
| `tool.upserted` | 必须为正整数 | 必须为正整数 | null | 已确认 Run 内的工具调用快照 |
| `turn.ended` | 必须为正整数 | 必须为正整数 | null | 已确认 Run 内的 Turn 终点与可选 usage |
| `compaction.boundary` | null 或已确认 Run | null | null | 上下文压缩边界；不创建 Run 或 Turn |

`turn.started`、`message.upserted`、`tool.upserted` 与 `turn.ended` 在没有可确认 Run 时可以使用另一种合法组合：`run_id=null`、`turn_number=null`、`observed_turn_ordinal` 为正整数。该组合表示可靠的观测顺序，不是 canonical Turn。它们不得同时携带 canonical identity 与 observed ordinal。

`run.started` 和 `run.ended` 的 payload 至少包含：

```json
{"external_lifecycle_id": "opaque-id-or-null", "boundary_source": "agent_start-or-agent_end-source"}
```

`external_lifecycle_id` 可为 `null`，但存在时按 `(session_id, external_lifecycle_id)` 严格 correlation；它不替代 `(session_id, run_id)`。`boundary_source` 是非空来源标识。`run.ended` 只由实际观察到的 `agent_end` 表达；未观察到 end 的生命周期保持 `open` 或在后续 Run 建立后显示为 `incomplete`，不能补写假的 `run.ended`。

`run.lifecycle.conflict` 是 Session event，三个 identity 字段都必须为 `null`。payload 固定保留以下字段：

```json
{
  "external_lifecycle_id": "opaque-id-or-null",
  "hook_name": "agent_start-or-agent_end-hook",
  "reason": "missing-id-or-correlation-reason",
  "semantic_fingerprint": "delivery-independent-fingerprint",
  "boundary_source": "observed-source"
}
```

缺少 lifecycle ID、end 没有对应 start、ID 不匹配、重复内容冲突或同一 ID 指向多个生命周期时，追加 conflict fact；不覆盖既有 Run fact，也不按最近 Run 猜测归属。相同语义的重试可以幂等；`semantic_fingerprint` 排除 delivery timestamp 与 event ID，因此真实重试不会因传输差异变成新语义。

`system.upserted` 与 `compaction.boundary` 只有在事件确实能证明属于某个 Run 时才携带 `run_id`，仍不得携带 `turn_number`，也不因此创建 Run。`session.*`、评分和 conflict 永远不携带 Run 或 Turn identity。

## Run correlation 与 Turn allocation

适配器不分配 `run_id`，也不自行判断重复、冲突和 end 匹配。它向 `RuntimeCoordinator` 提供 lifecycle evidence：phase（start/end）、Session、外部 lifecycle ID、boundary source、timestamp 与语义 payload。Coordinator 在 Ledger 的单 writer 事务内返回 `created`、`matched`、`duplicate`、`conflict` 或 `unscoped`，以及可选的 `RuntimeScope`。

每个 Session 的明确 start 按 Ledger 持久化的最大 ordinal 分配下一个 `run_id`；关闭并重启进程后仍从账本继续，两个并发 start 也不能得到相同 ordinal。每个 Run 的 `turn_number` 从 1 开始，Run 之间允许重复 T1；自然键去重必须区分 canonical `run_id`，无 Run 事件使用显式 runless namespace。

没有 lifecycle ID 的普通事件只能在 Session 恰好有一个 open Run 且没有冲突时继承该 Run；零个或多个 open Run 时保持 unscoped。之前未归属的事件不会因为后来出现 start 而被猜测性回填。

## Evaluation facts

Evaluation 使用独立的 subject-aware fact envelope，不伪造 Session ID：

```python
EvaluationFact = {
    "v": 1,
    "id": str,
    "evaluation_id": str,
    "ts": int,
    "type": "evaluation.created" | "evaluation.renamed" | "evaluation.deleted"
          | "evaluation.session.added" | "evaluation.session.removed",
    "payload": dict,
}
```

Evaluation fact 存在 `evaluation_events` 表中。`evaluation_id` 是不透明的 `e-<uuid>` identity，title 不是 identity；`seq` 是 Evaluation-local revision，由 Ledger writer 分配，不推进 `sessions.last_seq`。Evaluation facts 与 Session events 共用同一把 Ledger lock、同一事务纪律和同一事实存储边界，但不是第二个 Ledger 或第二个 writer。

| type | payload | 规则 |
| --- | --- | --- |
| `evaluation.created` | `{"title": string}` | 创建空 Evaluation 也合法 |
| `evaluation.renamed` | `{"title": string}` | 更新现有 title |
| `evaluation.deleted` | `{}` | 删除是 identity 终态，只解除当前 membership |
| `evaluation.session.added` | `{"session_id": string, "task_label": string}` | 添加或更新 label；Session 必须已存在 |
| `evaluation.session.removed` | `{"session_id": string}` | 解除当前关系，历史事实保留 |

同一 Session 最多有一个 active Evaluation membership。加入、移除、重新加入和 label 修改都追加 fact；读取时按 Evaluation-local `seq` latest-wins 折叠。Session 已在另一 Evaluation active 时，add 在同一 Ledger 事务中失败且不留下部分 fact。删除 Evaluation 后，历史 membership 仍可审计但不再 active；Session 的 events、score、Run、Turn 和 lineage 全部保留。同名重建得到新的 `evaluation_id`。

Evaluation 不保存 score 副本。Session score / annotation 查询仍从 Session facts 折叠，Evaluation detail 只 enrich 当前 member 的 Session metadata 与最新 Session score。

## 读取边界

Session、Run、Turn 和 Evaluation 的读取接口必须返回完整 identity：

```json
{
  "run_id": 1,
  "turn_number": 2,
  "observed_turn_ordinal": null
}
```

Run 列表和详情始终在 Session 作用域内；Run status 由 facts 推导为 `ended`、`open` 或在后续 Run 已建立且自身未结束时的 `incomplete`。observed turn 不出现在 canonical Run 的 Turn 列表中，也不制造 `run_id=0`、`unknown` 或 inferred Run。HTTP、CLI 与 React 只能消费共享 query facade，不能各自重新推导这些规则。

## 开发账本重建边界

当前契约不迁移旧 regression schema。发现旧的全局 experiment `runs`、assignment 表或旧 `events.turn` 形状时，启动应明确报告需要 reset，而不是静默重解释。完成所有代码 gate、测试和服务验收后，且用户在执行时明确确认，才可重建开发账本。

建议先保留可回退备份，再清空两份开发账本：

```sh
stamp=$(date +%Y%m%d-%H%M%S)
for db in "$HOME/.ata/ata.sqlite" "$HOME/.ata/dev.sqlite"; do
  if [ -e "$db" ]; then
    mv "$db" "$db.before-runtime-reset.$stamp"
  fi
done
```

这段命令只定义 reset procedure，本 gate 不执行。备份确认可读且用户明确选择放弃后，才删除对应 `.before-runtime-reset.*` 文件；服务必须停止或按部署脚本重启，不能在运行中的 SQLite 上直接删除当前文件。

## 代码出处与边界

| 概念 | 文件 · 符号 |
| --- | --- |
| Runtime envelope / event validation | `ata/schema.py` `envelope`、`parse_event` |
| Runtime coordination | `ata/runtime.py` `RuntimeCoordinator` |
| Single writer and persistence | `ata/ledger.py` `Ledger._append_locked` |
| Session fold | `ata/fold.py` `fold_session_meta` |
| Runtime read projections | `ata/project.py`、`ata/queries.py` |
| Evaluation facts and fold | `ata/evaluation.py` `EvaluationStore` |

这些定义只约束当前 Runtime Trace 与 Evaluation 产品。未来 regression 实验、预定义 `EvaluationCase` 或跨 Session 的实验比较需要另行设计，不得把本契约外推为现有对象。
