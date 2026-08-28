# 飞轮与回归 / Regression and Rating

> 历史文档：旧 regression CLI、全局 `/api/runs` handlers 与 assignment 写路径已移除。当前产品契约见 [`runtime-runs-and-evaluations.md`](runtime-runs-and-evaluations.md)，本页仅保留历史决策上下文，不描述可用入口。

把「轨迹里发现一个失败 → 存进任务集 → 改完 agent 之后重跑同任务集 → 对比指标」做成四件套。

| 词 | 定义 |
| --- | --- |
| 任务集 | `~/.ata/regression/tasks.jsonl`；每行一条任务，字段含 `input`（首条用户消息全文）+ `channel` + `model` / `thinkingLevel`，可选 `cwd` / `cwd` 注入 / 回链 id |
| 任务项 fingerprint | 任务集整体 `sha256` 截 16 位；run 引用它来锁版本 |
| run | 一轮实验；含 `run_id` / `description` / `taskset_fingerprint` / `created_ts` |
| 标注 | `session.scored` 事件；值 good / bad / partial + note；主观真值 |
| 指标 | 便捷层采集 + 端点合成（`fail_rate` 出 `/tools`、`usage_missing_turns` 出 `/usage`、`duration` 出 `/timing`） |
| 快照 | 一次 run 跑完后把每任务分数落盘到 `~/.ata/regression/runs/<run_id>/`；定性为可重建 |

## 四件套

| 组件 | CLI 子命令 | 落点 |
| --- | --- | --- |
| 任务集 | `tasks add` / `tasks list` | `~/.ata/regression/tasks.jsonl` |
| 实验 run | `run new` / `run list` | 账本 `runs` 表 + `run.opened` 事件（HTTP 端点创建） |
| 标注 | `rate` | 账本 `session.scored` 事件 |
| 对比 | `compare <run_a> <run_b>` | 终端 markdown 表 + 双方快照到 `~/.ata/regression/runs/` |

## 五个相关事件类型

| 事件 | 触发 | 用途 |
| --- | --- | --- |
| `session.scored` | `rate` 子命令 | 主观真值（good / bad / partial + note） |
| `session.score.cleared` | UI / CLI | 标注墓碑 |
| `session.assigned` | UI / CLI | 把会话归入 run / task（manifest 文件取消） |
| `session.unassigned` | UI / CLI | 归组墓碑 |
| `run.opened` | `POST /api/runs` | 一次实验开始；携带 `taskset_fingerprint` |

> 词汇：CLI 用「rate」动词；账本事件类型用 `session.scored`；UI 与文档用「标注」。三者指同一件事。

## 任务项字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `task_id` | 自动生成 | `t-<uuid8>` |
| `input` | 必填 | 首条用户消息全文（手动复制粘贴起步，未做导出命令） |
| `channel` | 必填 | agent / 模型通道标识 |
| `model` / `thinkingLevel` | 视通道 | 与 channel 配套 |
| `cwd` / `cwd` 注入 / 回链 id | 可选 | 固定可控项，便于对照 |
| `session_id` | 创建 run 时回填 | 跑完后写回，统计时按 session 走便捷层 |

`tasks.jsonl` 与 `~/.ata/regression/` 在本地 git 管版本（设计原则见 [`../../wayfinder/MAP.md`](../../wayfinder/MAP.md)）；任务集管理不做前端。

## run 流程

1. `run new --desc "改完 X" --taskset tasks.jsonl`：HTTP 端点创建 `runs` 行 + 发 `run.opened` 事件；记录 `taskset_fingerprint`
2. 在每个 agent 里跑完任务集：会话进账本；通过 `session.assigned` 把每条 session 挂到对应 task
3. `rate <sid> --value good|bad|partial --note ...`：发 `session.scored`
4. `compare <run_a> <run_b>`：走便捷层 + 写双方快照，输出 markdown 对比表

`run list` 拉 `runs` 表；`compare` 内部不再重推平行口径（架构评审候选 6 收口）。

## 对比表字段

| 字段 | 来源 |
| --- | --- |
| `fail_rate` | `/tools` 端点 `failed` / 总数 |
| `tokens_reported` | `/usage` 端点逐轮 `reported` 合计 |
| `usage_missing_turns` | `/usage` 端点 `missing_turns` |
| `duration_s` | `/timing` 端点 `span_ms`（`PLACEHOLDER_MS` 过滤） |
| 主观分数 | `session.scored` 最新一条 `value` |

任一侧缺数据则 Δ 标 `n/a`，不把缺失当 0。题面冻结、对比只在同版任务集间做（`taskset_fingerprint` 不一致拒绝对比）。

## 失败类指标优先

> 设计原则（[wayfinder/MAP.md](../../wayfinder/MAP.md)）：失败类指标对噪声最鲁棒，优先建。

| 噪声源 | 影响 | 处理 |
| --- | --- | --- |
| 记忆库 | 同题面不同上下文 | `cwd` / 注入固定；固定可控项 |
| 采集数据 | 与 host 落盘稳定性相关 | 走便捷层；缺失标 missing，不当 0 |
| 屏幕注入 | 偶发 | 任务集里避开相关钩子 |
| `web_search` | 实时结果不同 | 任务里如非必要不依赖 |
| 模型随机性 | 同 prompt 不同输出 | pass^k（同一任务跑 k 次取全过率） |

## 数据边界

| 边界 | 行为 |
| --- | --- |
| 任务集管理 | 不做前端；纯 `tasks.jsonl` + git |
| 标注归组 | UI 与 CLI 同源；归组与打分同入口 |
| Web UI 实验只读 tab | 不在首版；等真实跑过几轮实验再立票 |
| pass^k | 定义锁死缓实现；命令面只暴露 `--k` |
| 实验对比 | 只在同 `taskset_fingerprint` 之间做 |

## 引用边界

| 边界 | 不外推成 |
| --- | --- |
| 任务集文件化 + git | 任何团队/服务端化方案；不引入 Langfuse / 多租户平台 |
| pass^k | 评估单一指标的「全过」；失败类指标对噪声更鲁棒，优先用 |
| 主观标注 | 任何机器评估的真值；主观是锚，机器是线索，分开存分开统计 |

## 代码出处

| 概念 | 文件 · 符号 |
| --- | --- |
| 任务集默认路径 | `ata/cli.py` `TASKS_FILE` |
| `tasks` / `run` / `compare` CLI | `ata/cli.py` 子命令 |
| `rate` CLI 与 `session.scored` 发射 | `ata/cli.py` `_rate_main` + `envelope` |
| `runs` 表 + `create_run` / `rename_run` / `run` | `ata/ledger.py` |
| 指标收集 | `ata/cli.py` `collect_task_score` |
| 快照写盘 | `ata/cli.py` `_write_snapshot` + `RUNS_DIR` |
| HTTP 端点 | `ata/http.py` `h_rename_run` / `h_append_events` |
| 设计决议 | [`../../wayfinder/MAP.md`](../../wayfinder/MAP.md) + `wayfinder/tickets/T1 / T3 / T5 / T9 / T10` |
