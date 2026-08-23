---
name: ata
description: 操作本机 ATA（Agent Trace Analysis）轨迹服务：查会话与事件、看工具成败与 usage、标注会话好坏、管理回归任务集并对比实验轮次。当任务涉及"查某条 agent 轨迹 / 诊断一次会话为什么失败 / 给会话打 good-bad 标注 / 建回归任务或跑 run 对比"，或用户提到 ata、atatrace、轨迹账本时使用。
---

# ATA 轨迹服务操作

ATA 是本机的 agent 轨迹账本：各宿主（cue/pi/droid/claude/codex）的会话事件追加进同一本 SQLite，提供只读查询端点、打标注入口和回归实验闭环。

**部署事实**：常驻服务 launchd 管理，生产端口 **17877**（`ATA_URL` 环境变量已指向它），账本 `~/.ata/ata.sqlite`，Web UI http://127.0.0.1:17877 。CLI 入口：`python3 -m ata <子命令>`（需在 repos/ata 目录或已安装的包内）。

## 1. 探活与兜底

先打健康检查；不通改用 `--ledger` 直读 SQLite：

```
curl -s $ATA_URL/api/health          # {"ok": true} 即可用
python3 -m ata read sessions --ledger ~/.ata/ata.sqlite   # 离线兜底
```

写操作（rate/归组/run 创建）**只能走 HTTP**，`--ledger` 模式会拒绝——单一 writer 纪律。

## 2. 发现会话

```
python3 -m ata read sessions [--agent cue] [--limit N]
```

输出 JSON 数组：`id`、`agent`、`title`、`turns`、`last_ts`、`parent_session_id`。服务端不做过滤：`--agent` 是客户端裁剪，title 关键词要自己对输出 grep。

## 3. 下钻诊断

先看轮廓再精读，顺序固定：

1. `read usage SID` —— 每轮 token 与模型；usage 缺失的轮保留且 `status:"missing"`，另有 `missing_turns` 计数
2. `read tools SID --status failed` —— 工具清单（result 默认只给尾部 200 字符预览；`--full` 取全文，对 compactions 的 summary 同样生效）
3. `read events SID --after-seq N --limit M` —— 权威层裸事件流，前两步解释不了时才用
4. `read compactions SID` / `read lineage SID` —— 压缩点与父子血缘按需查

**events 是全量权威数据，翻到头才算拿完。** 每条是 `{seq, event}` 结构，正文和工具记录都在 `event.payload` 里。HTTP 路径 limit 服务端封顶 500；循环取数直到本页为空或 `next_after_seq` 不再前进，提前停就是漏数据。探活失败时改用 `--ledger` 直读：离线模式不限条数，反而是最省事的全量通道。

**别把 `/api/sessions/{SID}` 投影端点当全量来源。** 它默认只回尾部 80 行（`before` 游标向前翻），是给人看的预览；要完整正文走 events。

### 取「谁说了什么」

- **User 发言**：`message.upserted` 且 `payload.role=="user"` → `payload.text`。首条 user 往往是 `<system-reminder>` 等注入上下文，按前缀区分，别当真人发言。
- **Tool 行为**：`tool.upserted` → `payload.name`（工具名）、`payload.payload`（入参）、`payload.text`（适配器摘要）、`payload.result`（返回）、`payload.status`。droid 会话字段不齐：有的记录 name 是泛化的 `"tool"`、入参为空、真实内容在 `text` 里，解析时按 `text`/`payload`/`result` 兜着取。

## 4. 空数据约定

只有两条要记：**HTTP 404 = 不存在**；**200 加空数组 = 存在但为空**（如无失败工具、无血缘）。usage 缺失是数据边界不是异常，别当成故障报。

两个已知陷阱：

- **没有跨会话内容检索端点。** 找「哪条会话提到 X」只能先 `read sessions` 拿 sid 清单，再逐个拉 events 本地 grep；会话多时先用 agent/title 缩小范围。
- **`--since-days` 是死参数**：CLI 声明了但没有任何执行路径消费它，用了等于没过滤，按时间筛选只能拿到数据后自己裁。

## 5. 隐私与数据边界（硬约束）

- 轨迹含会话正文与密钥痕迹：**分析结论、示例原文一律不得发往本机之外**
- 各宿主可观测面不同，引用时照实声明：

| 宿主 | usage | SYSTEM 快照 |
| --- | --- | --- |
| pi / cue | reported | 有 |
| droid | 恒 missing | 无 |
| claude | reported | 无 |

## 6. 写入：标注与归组

- 打分：`python3 -m ata rate SID --value good|bad|partial [--note "..."]`
- 归组（把会话挂到某个实验轮次的某个任务）：Web UI 会话页「归组」控件选 run 填任务 id；脚本化则 POST `/api/events` 一条 `session.assigned` 事件（payload 必填 `run_id` + `task_id`）
- 两类信号分开存：human 标注是主观真值锚，machine 过程信号只是线索，统计时不混算

## 7. 回归飞轮

任务集与实验产物在 `~/.ata/regression/`（本地 git 管版本，**不入任何远端仓库**）：

```
echo "<首条用户消息原文>" | python3 -m ata tasks add --channel cue   # 出题，题面从此冻结
python3 -m ata tasks list                                            # 查任务 id
python3 -m ata run new --desc "这轮改了什么"                          # 干预后建轮次，自动记任务集指纹
python3 -m ata run list                                              # 列出现有轮次（含归组计数）
python3 -m ata compare RUN_A RUN_B                                   # 新旧差异表 + 双侧分数快照落盘
```

纪律：改题面 = 新版任务集（git 记录）；对比只在同版任务集的 run 之间成立；缺失值显示 miss、差值 n/a，永不当作 0。
