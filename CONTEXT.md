# Agent Trace Analysis (ATA)

把 Pi、Cue、omp、Claude Code、Codex、Droid 六家 agent 的会话翻译成统一事件账本，在浏览器里按轮次回看，并以「采集 → 观测 → 诊断 → 干预 → 对照复跑」飞轮支撑 agent 调优。产品名是 **Agent Trace Analysis** (ATA)。

## Language

### 账本与事件

**账本（ledger）**：
全部事实的唯一存放处：一个 SQLite 文件（生产为 `~/.ata/ata.sqlite`）。写入只经一条追加路径（事件追加门），单一 writer。
*Avoid*: 数据库、存储、ata.sqlite 指称概念时

**事件（event）**:
发生过的一条事实，带类型词表、轮次号与 payload。账本里只有追加，没有更新；同一实体的多次快照靠幂等键收敛到最新一行。

**适配器（adapter）**：
把某家 agent 的方言翻译成统一事件的组件，位于 `plugins/`。每家一个。
*Avoid*: 插件、翻译器

**extension**:
特指 `extensions/pi-atatrace`——装在 Pi/Cue 运行时里的采集端组件，负责把 hook 推给 ATA。它不是适配器；翻译发生在服务端的适配器里。
*Avoid*: 用 extension 泛指任何适配器

**投影（projection）**：
从事件流折叠出的可读视图（会话行、标注聚合、usage 合计等）。投影可重建，不是事实源。

**权威层 / 便捷层**：
读取接口的两层分工：裸事件流是权威层，能重建任何视图；分析投影端点（usage/tools/compactions 等）是便捷层，省 token。便捷层正文默认尾部 200 字符预览，`full=true` 取全文。

**rev**：
会话的版本号，取自 `sessions.last_seq`。前端用它做零重绘门控。

### 会话结构

**会话（session）**：
一次 agent 对话的完整轨迹trace，是账本的归属单位。
*Avoid*: conversation、对话（指整体轨迹时）

**运行（Run）**：
Session 内一次从 `agent_start` 到 `agent_end` 的 Agent 执行生命周期。一个 Session 可以包含多个 Run；Run 不跨 Session。Run 是 ATA 拥有的 canonical 对象，在可确认的生命周期起点建立自己的 identity，并由显式的 `run.started` / `run.ended` 事实表达边界。Run 的 Session-local ordinal 从 1 开始递增，且只增不复用；`(session_id, run_id)` 是 Run 的 canonical identity，它不是全局唯一标识。每个明确观察到的 `agent_start` 都启动一个新的 Run；若前一 Run 尚未观察到 `agent_end` 又收到新的 `agent_start`，保留前者为 open/incomplete 并分配下一个 ordinal。宿主提供的 `run_id`、`turn_id`、`task_id` 或其他 correlation ID 不等同于 ATA Run identity，只能作为外部关联元数据；缺少生命周期证据的适配器不得猜测并物化 Run。若事件已有可靠的 Session / Turn / ToolCall 事实、但没有可确认的 Run 边界，则事件可以暂时没有 Run 归属；未知不制造特殊 Run，也不因缺少 Run 而丢弃事实，旧事件不因后来获得新证据而被猜测性回填。
*Avoid*: 用旧回归实验语义的 run 指代 Agent 执行生命周期

**Run 生命周期证据**：
只有实际且明确的 `agent_start` / `agent_end` 生命周期 hook 才是 Run 的边界事实。`before_agent_start`、`turn_start` 与 `agent_settled` 不因名称相似而自动等同于 Run 边界；`session.opened` 也不自动表示 Run 开始。

**Run 生命周期 correlation**：
对于能提供稳定生命周期 correlation 的适配器，外部 lifecycle ID 可用于把同一生命周期的 start/end 关联起来；它仍不取代 ATA 的 Session-local Run ordinal 与 `(session_id, run_id)` canonical identity。Pi/Cue Extension 可以为每次实际 Agent 生命周期生成全局唯一的 UUID（或等价的 opaque ID），并在对应的 start/end 中携带；后端以 `(session_id, external_lifecycle_id)` 做严格匹配，同时由 ATA 分配自己的 Run ordinal。外部 ID 的全局唯一性由 Extension 保证，ATA 不依赖其可读语义。

**Run correlation 冲突**：
外部 lifecycle ID 的重复 start 若内容相同则可幂等；内容冲突、缺少 ID、start/end 不匹配或同一 ID 对应多个生命周期时，不覆盖既有事实，也不猜测 Run 归属；相关生命周期事实保持未归属并记录冲突。

**Run 边界事件**：
`run.started` / `run.ended` 保存 ATA Run identity、外部 lifecycle ID（若有）及边界来源；`run.ended` 表示实际观察到的 `agent_end`。异常恢复使用独立的恢复事实或状态（如 `run.recovered`），不得伪装成 `run.ended`。

**Run 事件归属**：
Run-scoped canonical event 的统一 envelope 携带 Session-local `run_id`；`run.started` / `run.ended` 自身也携带该 ID。尚无可确认 Run 归属的事件，其 `run_id` 保持缺失或 NULL，不使用 `0`、`unknown` 或虚构 Run。

**Run 结束状态**：
观察到 `agent_end` 时，Run 正常结束；若生命周期在未观察到 `agent_end` 时中断，Run 保留未完成事实，并可另有明确的恢复/推断状态，但推断结束不等同于宿主真实发出的 `agent_end`。

**普通用户消息与 Run**：
上一 Run 结束后的普通用户消息在语义上触发新的 Agent 执行，但只有随后观察到明确的 `agent_start` 才物化新的 canonical Run。未观察到 start 时，消息仍保留为 Session 事实，不因内容相似度、task_label 或最近 Run 猜测归属。

**对话视图**：
webapp 里只看「人说的话 + 模型答的话」的阅读模式，工具收成单行链；与完整轨迹视图相对。

**轮次（turn）**：
一次模型调用，以及该调用触发的全部工具执行；工具结果回填后再次调用模型，进入下一个 Turn。「轮次」这个词专属于 turn。Turn number 在每个 Run 内从 1 开始；Turn 的 canonical identity 是 `(run_id, turn_number)`，不跨 Run 延续编号。若事件尚无可确认的 Run 归属，仍可保留 Session-local 的 `observed_turn_ordinal` 作为观测排序号，但它不是 canonical `turn_number`，也不能暗示 Run 边界。
*Avoid*: 用「轮次」指完整 Run 或 Evaluation

**Step**：
一轮内的第几次模型请求。一轮 ≠ 一次请求，故有 Step。

**SYSTEM 行 / System Prompt / Tools 目录**：
三个不同的东西：SYSTEM 行是 system.upserted 的投影；System Prompt 是当时真正发给模型的系统提示全文（prompt_text）；Tools 目录是当时挂载的工具清单含参数 schema。工具调用行是已发生的事实，不是 Tools 目录。没有快照的宿主（Claude Code、Droid）不画 SYSTEM 行——没记录不等于没有。

**CONTEXT 行**：
会话中途以 `<system-reminder>` 等前缀注入的用户侧内容。它不是 SYSTEM。CONTEXT 注入不算新轮次。

**压缩点（compaction）**：
上下文被压缩的事件边界（compaction.boundary）。Compaction 本身不是 `agent_start` / `agent_end`，不创建 Run；只有宿主提供可验证的等价生命周期事实时，才可按该适配器的明确语义建立 Run。若无法证明 compaction 前后属于同一 Agent 生命周期，后续事件可以继续无 Run 归属，不因未知而创建 inferred Run。

**血缘（lineage）**：
会话的父子派生关系（parent_session_id / session.opened.payload.parent_session）。拿不到就是 NULL，NULL 是事实不是错误。Subagent 使用自己的 child Session，并在该 Session 内拥有自己的 Run；父子关系不通过把子 Run 挂到父 Session 表达。

**agent**：
六个白名单值之一：pi / cue / omp / droid / claude / codex。Cue 是 Screenpipe 品牌升级后的名称，运行时是 Pi，以自己的产品身份写入；omp（Oh My Pi）是 Pi 之上的桌面端产品身份，运行时仍是 Pi，但 `host` 与 `agent` 都写成 `omp`，`runtime` 保留 `pi`，由 `attach-omp-pi.sh` 安装的同名扩展把 hook 推给 ATA。

**channel**：
两处不同语义，说的时候要带上文：① session.opened 里该会话走的采集通道（如 Cue 的应答/主动通道）；② 回归任务项里「重跑时用哪个宿主」，取值就是 agent 名。

**usage 状态**：
每轮 token 记录的三态：reported（宿主上报）/ estimated / missing（宿主不给，如 Droid 恒 missing）。缺失保留该行标 missing，绝不当作 0 参与合计。

### 标注与归组

**标注**：
人类在会话上打的主观真值：good / bad / partial 加可选备注。真值锚。入口是 Web UI 标注控件与 CLI `ata rate`。
*Avoid*: score（指人工那一路时）、评分

**Evaluation**：
由人创建的持久观察集合，包含一个标题和若干已存在的 Session。一个 Session 只能属于一个 Evaluation。Evaluation 用于把一组 Session 放在一起观察、标注或比较；它不触发 Run，不拥有 Run 的生命周期，也不改变 Session、Run、Turn 或 Trace。创建、加入、移除和删除 Evaluation 都是人工归组操作；membership 可以携带属于该集合关系的 `task_label: string`；删除 Evaluation 不删除 Session 或事件账本，只解除集合关系。被移除的 Session 可以重新加入同一个 Evaluation；Evaluation 删除后，Session 可以加入新的 Evaluation；历史加入、移除和重新加入事实保留，当前 membership 由最新有效状态决定。

**观察标注**：
Evaluation 复用 Session 上已有的标注与 score 记录保存人工结论；Evaluation 只是观察与操作标注的上下文，不复制一套 Evaluation-level 评分事实。Session 视图与 Evaluation 视图看到的是同一份标注；删除 Evaluation 不删除标注。

**Evaluation 产品表面**：
前端、公开 HTTP API 和 `ata` skill 以 Evaluation 作为人工观察与归组入口，以 Session / Run / Turn 作为轨迹查询入口；标注仍是 Session 事实，`task_label` 属于 Evaluation–Session membership。当前直接切换新领域契约，不保留旧回归 taskset、实验批次 run、assignment 或 compare 的兼容表面；具体命令、路由和组件属于接口设计，不改变这些领域边界。

**Evaluation 删除**：
删除是 Evaluation identity 的终态；历史 membership 仍可审计，但不再是 active 集合。再次创建同名 Evaluation 得到新的 identity；Session 可加入新的 Evaluation。

**EvaluationCase**：
暂不属于当前模型。它未来可以表示预先定义的固定评估问题或规则，但当前 Evaluation 不通过 EvaluationCase 触发 Run，也不要求 EvaluationCase 存在。

**task_label**：
人工在 Evaluation 中为 Session 指定的任意字符串，用来记录被观察 Agent 的外部业务 Task 标签，例如“日报”。ATA 不知道该 Task 的业务生命周期、成功条件或执行规则；`task_label` 不是 ATA 的权威 Task 对象，也不等于 Evaluation。

**score**：
挂在会话上的评分事实的数据形状：名字 + 数值 + 类型（number/boolean/categorical）+ 来源（human/machine）。标注是 source=human 的 score。

**信号**：
机器从轨迹里检测出的失败线索。线索，不是真值。与标注分开存、分开统计。
*Avoid*: 机器标注

**墓碑（tombstone）**：
以追加事件撤销先前事实的写法（如 session.score.cleared、session.unassigned），读取端 latest-wins 折叠后即消失。

### 回归与实验（已移出当前产品）

回归实验的 `taskset`、task item、实验批次 run、assignment 与 compare 概念不属于当前 ATA 领域模型。当前产品只保留 Agent Runtime Trace 与 Evaluation；对应的代码、API、UI、schema、SQLite 表和开发数据均可破坏式移除或重建，不保留兼容层。未来若重新需要，作为独立 bounded context 重新设计。

### 代理采集

**代理通道（capture）**：
转发式采集代理：截获 agent↔LLM 的 HTTP 流量，解析出账本别处拿不到的事实（SYSTEM 快照、tools 目录、每轮 usage）作为规范事件并入账本。补充通道，不是权威平面；只发增量事实，从不替代第一方 transcript 适配器。
*Avoid*: 万能代理、以代理流量当账本、把代理叫「反向代理组件」

**并入（merge-on-write）**：
代理截获的流量恢复出宿主 sessionId 后往同一 session 追加，靠幂等键收敛；恢复不了就丢弃并放弃该次采集，绝不新建孤儿会话。
*Avoid*: 平行会话、读取侧归并

## 数据边界速记

| agent        | SYSTEM 快照   | usage                                       |
| ------------ | ----------- | ------------------------------------------- |
| pi / cue / omp | 有         | reported                                    |
| claude       | 无（代理通道开启时有） | reported（缺失或全 0 → missing）；每轮 usage 经代理通道补全 |
| codex        | 有           | reported                                    |
| droid        | 无           | 恒 missing                                   |


