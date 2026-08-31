# ATA Ledger seam grilling（归档）

> **状态：暂停，未实现。** 本文记录 2026-08-29 的 Ledger seam 设计讨论。它是设计过程快照，不是当前实现合同。恢复任务时，先核对 `CONTEXT.md`、现行 features 文档和代码，再继续未决问题。
>
> 本次讨论确认：旧账本数据可以删除。实现阶段可以直接建立符合当前领域模型的新 schema，不需要旧 schema migration 或旧数据兼容。

## 目标

收窄 Ledger 的 writer seam，避免 Runtime、Evaluation、HTTP handler 和 adapter 直接操作 SQLite connection 或 lock。

目标边界：

- Ledger 是全部事实的唯一存放处。
- `LedgerWriter` 是唯一写入 port。
- `LedgerReader` 是读取 port。
- SQLite 是唯一 production adapter。
- Runtime 负责 Run identity 和 Run lifecycle。
- Evaluation 负责 Evaluation、membership 和 Evaluation transition。
- projection 不是事实源，可以从事实流重建。
- 测试 fake 只放在 `tests/`，不提供 production in-memory adapter。

## 已确认的设计决策

### Ledger seam

1. 拆成 `LedgerWriter` 和 `LedgerReader` 两个 interface。一个 SQLite adapter 可以同时实现两者。
2. `LedgerWriter` 采用窄 seam，至少提供 `append(event)` 和 `append_many(events)`。不把 `start_run`、`create_evaluation` 等领域动作放进 adapter。
3. SQLite adapter 负责 schema、锁、transaction、commit、幂等记录和 projection persistence mechanics。
4. Domain code 不访问 `_conn`、`_lock`，也不自行 commit。
5. transaction discipline 由 adapter 管理。简单 append 自动成 transaction；需要多步原子的领域操作使用受控的显式 transaction。
6. SQLite 是唯一 production adapter。完整的 `LedgerWriter` / `LedgerReader` fake 只用于 tests。

### Schema 和旧数据

7. 允许破坏式重构。当前 public Ledger method、HTTP shape 和 CLI shape 不需要自动保持兼容。
8. 旧数据可以删除。旧 schema 不需要 migration、兼容读取或延迟迁移。
9. 可以直接按当前架构建立新的 schema。若启动时发现不是当前 schema，处理方式应是明确失败或由用户显式 reset；不得猜测旧 schema 的含义。
10. `sessions` 和 `run_index` 如果保留，只能是可重建 projection/index，不是第二事实源。

### Event 语义

11. Event 是 immutable fact。已经写入的 event 不修改。
12. 同一逻辑对象的真实状态变化追加新的 fact。例如 tool 可以依次产生 `tool.started` 和 `tool.completed`；Reader 再折叠成当前 tool view。
13. 幂等和事实保存分开处理：重复投递不应覆盖旧 fact。
14. 使用 `idempotency_key + payload_hash` 判断重试。相同 key 且 payload 相同，视为同一事实的重试并跳过；相同 key 但 payload 不同，追加新的 immutable fact。
15. Runtime Trace event 与 Evaluation event 使用两个事实流、两张事实表，但仍属于同一个 Ledger，并由同一个 `LedgerWriter` 管理。两者共享 immutable event 和 writer discipline，各自拥有 subject、sequence 和 projection 边界。这不构成两个 Ledger 或两个 writer。
16. 独立 event 使用 per-event best-effort 语义：一个 event 无效，不阻止其他独立 event。基础设施错误、transaction 错误和不可隔离的领域不变量错误不能静默吞掉。

## 代码事实

当前 `repos/ata/ata` 仍是旧的合并 Ledger 实现，尚未形成上述 seam：

- `ata/ledger.py` 同时维护 event、`sessions`、`run_index` 和 Evaluation persistence，并暴露 SQLite connection 与 lock 的使用方式。
- `_append_locked` 会维护 projection，并可能按旧的 `dedupe_key` 修改已有行；这不符合本次确认的 immutable fact 语义。
- `ata/runtime.py` 直接持有 `ledger._lock` / `ledger._conn`，并自行 commit。
- `ata/evaluation.py` 直接读取 connection、执行 lock，并调用 Ledger 私有写入方法。
- `ata/queries.py` 是读取 facade，但 HTTP 和 CLI 仍有多处直接依赖旧 Ledger API。
- `ata/project.py` 负责 Session、Run、Turn、Tool、usage 和 timing 的 projection 逻辑。
- `plugins/jsonl.py` 和 `plugins/capture.py` 已使用 `append_many`，但当前失败处理和事务边界不统一。

因此，已确认的决策不能直接视为现有代码已经满足的 contract；实现时需要重写对应测试和调用关系。

## 暂停位置：下一轮 frontier

以下问题尚未回答。恢复时按依赖顺序继续 grilling，不要直接实现。

### Q15：Sequence scope

需要决定 Trace event 和 Evaluation event 的 `seq` 范围：

- 每个 Session / Evaluation 各自递增的 local sequence；
- 一个 Ledger-wide global sequence；
- 或不再使用 sequence，只使用 timestamp 和 event identity。

同时要明确 `seq`、`event_id`、Session `rev` 和 Run 内 `turn_number` 的区别，以及 HTTP cursor 使用哪一个值。

### Q16：批量 append 的调用 contract

需要把 Q14 的 per-event best-effort 具体化：

- `append_many` 是否逐 event 隔离，并返回每个 event 的 accepted/skipped/rejected 结果；
- 显式 transaction 是否只由 Runtime / Evaluation 等 domain service 请求；
- 哪些错误可以隔离，哪些错误必须 rollback 或直接失败；
- 是否需要独立的 best-effort API，避免调用方误解 `append_many` 的语义。

### Q17：Projection rebuild lifecycle

需要决定 projection 的维护方式：

- 写入成功时 eager update，启动时校验并可重建；
- 读取时 lazy rebuild；
- 只提供显式 rebuild；
- 或删除 projection，完全从 event stream 计算。

还要明确 rebuild lock、projection version、缺失或过期 projection 的行为，以及 Session `rev` 是否继续使用 `sessions.last_seq` 的语义。

### Q18：Runtime identity allocation

需要决定 Runtime 如何安全分配 Session-local Run ordinal：

- adapter transaction 内分配并和 `run.started` 一起提交；
- Runtime 扫描事实流中的最大 ordinal 后加一；
- 或改用全局 UUID。

必须继续满足 `CONTEXT.md`：Run identity 是 `(session_id, run_id)`，ordinal 从 1 开始，只增不复用；明确观察到的每次 `agent_start` 都建立新的 Run。

### Q19：Evaluation membership constraint

需要决定“一个 Session 只能属于一个 Evaluation”如何保证：

- Evaluation service 在显式 transaction 中检查当前 membership，再追加 membership fact；
- 只在 Reader 中发现冲突；
- 或由 SQLite current-membership projection 的 unique constraint 保证。

无论选择哪种方式，都必须保留加入、移除、重新加入和 Evaluation 删除的历史事实；删除 Evaluation 不删除 Session、Run、Turn 或 Trace。

## 恢复协议

1. 先重新读取 `CONTEXT.md` 和本文件。
2. 继续以 grilling round 询问 Q15–Q19，不把已确认决策重新提问。
3. 依据回答展开新的依赖问题，直到 design tree frontier 为空。
4. 让用户确认 shared understanding。
5. 若出现新的领域概念，再调用 `domain-modeling` 更新 `CONTEXT.md`。
6. 之后才按 ATA 的 `/ponytail full` 工作流实现。
7. 实现必须保持单一 writer、测试 fake 仅在 tests、不得把真实会话正文或密钥放入 fixture。

## 相关文档

- [`../../CONTEXT.md`](../../CONTEXT.md)
- [`../features/canonical-event-ledger.md`](../features/canonical-event-ledger.md)
- [`../features/runtime-runs-and-evaluations.md`](../features/runtime-runs-and-evaluations.md)
- [`../adr/0001-proxy-capture-channel.md`](../adr/0001-proxy-capture-channel.md)
