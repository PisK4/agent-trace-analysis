# ATA（Agent Trace Analysis）

把 Pi、Cue、Claude Code、Codex、Droid 五家 agent 的会话翻译成统一事件账本，在浏览器里按轮次回看，并以「采集 → 观测 → 诊断 → 干预 → 对照复跑」飞轮支撑 agent 调优。产品 UI 名是 **Atatrace**；ATA 是项目与服务名。

## Language

### 账本与事件

**账本（ledger）**：
全部事实的唯一存放处：一个 SQLite 文件（生产为 `~/.ata/ata.sqlite`）。写入只经一条追加路径（事件追加门），单一 writer。
_Avoid_: 数据库、存储、ata.sqlite 指称概念时

**事件（event）**:
发生过的一条事实，带类型词表、轮次号与 payload。账本里只有追加，没有更新；同一实体的多次快照靠幂等键收敛到最新一行。

**适配器（adapter）**：
把某家 agent 的方言翻译成统一事件的组件，位于 `plugins/`。每家一个。
_Avoid_: 插件、翻译器

**extension**:
特指 `extensions/pi-atatrace`——装在 Pi/Cue 运行时里的采集端组件，负责把 hook 推给 ATA。它不是适配器；翻译发生在服务端的适配器里。
_Avoid_: 用 extension 泛指任何适配器

**投影（projection）**：
从事件流折叠出的可读视图（会话行、标注聚合、usage 合计等）。投影可重建，不是事实源。

**权威层 / 便捷层**：
读取接口的两层分工：裸事件流是权威层，能重建任何视图；分析投影端点（usage/tools/compactions 等）是便捷层，省 token。便捷层正文默认尾部 200 字符预览，`full=true` 取全文。

**rev**：
会话的版本号，取自 `sessions.last_seq`。前端用它做零重绘门控。

### 会话结构

**会话（session）**：
一次 agent 对话的完整轨迹，是账本的归属单位。
_Avoid_: conversation、对话（指整体轨迹时）

**对话视图**：
webapp 里只看「人说的话 + 模型答的话」的阅读模式，工具收成单行链；与完整轨迹视图相对。

**轮次（turn）**：
一轮对话，从一条真实用户消息到模型收尾。「轮次」这个词专属于 turn。
_Avoid_: 用「轮次」指 experiment run

**Step**：
一轮内的第几次模型请求。一轮 ≠ 一次请求，故有 Step。

**SYSTEM 行 / System Prompt / Tools 目录**：
三个不同的东西：SYSTEM 行是 system.upserted 的投影；System Prompt 是当时真正发给模型的系统提示全文（prompt_text）；Tools 目录是当时挂载的工具清单含参数 schema。工具调用行是已发生的事实，不是 Tools 目录。没有快照的宿主（Claude Code、Droid）不画 SYSTEM 行——没记录不等于没有。

**CONTEXT 行**：
会话中途以 `<system-reminder>` 等前缀注入的用户侧内容。它不是 SYSTEM。CONTEXT 注入不算新轮次。

**压缩点（compaction）**：
上下文被压缩的事件边界（compaction.boundary）。

**血缘（lineage）**：
会话的父子派生关系（parent_session_id / session.opened.payload.parent_session）。拿不到就是 NULL，NULL 是事实不是错误。

### Agent 身份

**agent**：
五个白名单值之一：pi / cue / droid / claude / codex。Cue 是 Screenpipe 品牌升级后的名称，运行时是 Pi，以自己的产品身份写入。

**channel**：
两处不同语义，说的时候要带上文：① session.opened 里该会话走的采集通道（如 Cue 的应答/主动通道）；② 回归任务项里「重跑时用哪个宿主」，取值就是 agent 名。

**usage 状态**：
每轮 token 记录的三态：reported（宿主上报）/ estimated / missing（宿主不给，如 Droid 恒 missing）。缺失保留该行标 missing，绝不当作 0 参与合计。

### 标注与归组

**标注**：
人类在会话上打的主观真值：good / bad / partial 加可选备注。真值锚。入口是 Web UI 标注控件与 CLI `ata rate`。
_Avoid_: score（指人工那一路时）、评分

**score**：
挂在会话上的评分事实的数据形状：名字 + 数值 + 类型（number/boolean/categorical）+ 来源（human/machine）。标注是 source=human 的 score。

**信号**：
机器从轨迹里检测出的失败线索。线索，不是真值。与标注分开存、分开统计。
_Avoid_: 机器标注

**墓碑（tombstone）**：
以追加事件撤销先前事实的写法（如 session.score.cleared、session.unassigned），读取端 latest-wins 折叠后即消失。

### 飞轮：回归与实验

**任务集（taskset）**：
回归题目的集合，存 `~/.ata/regression/tasks.jsonl`，本地 git 管版本，整册有一个指纹。不入 repos/ata 仓库——题目是真实会话正文。

**任务项（task item）**：
任务集里的一道题：冻结的首条用户消息原文（input）、channel/model 固定项、可选 k。提取即冻结，改题面等于出新版任务集。
_Avoid_: 把 task_id 单独叫「任务」

**run**：
一次实验运行：干预后对同一版任务集重跑一遍。对比发生在 run 与 run 之间。run 不译。
_Avoid_: 实验轮次、「创建一轮实验」的说法（应说「创建一个 run」）

**归组（assignment)**:
把一个会话挂到某个 run 下的格子上（session.assigned：run_id + task_id）。格子标签允许先于任务项自由创建，不必指向 tasks.jsonl 里的题；此时它只是归属记账，不是一道题。

**对照对比（compare）**:
两个 run 各自的分数快照摆出一张差异表。任一侧数据缺失则 Δ 为 n/a，不参与汇总；跨版本任务集不做逐格差值。

## 数据边界速记

| agent | SYSTEM 快照 | usage |
| --- | --- | --- |
| pi / cue | 有 | reported |
| claude | 无 | reported（缺失或全 0 → missing） |
| codex | 有 | reported |
| droid | 无 | 恒 missing |
