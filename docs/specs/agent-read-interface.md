# ATA 轨迹读取接口 spec（给外部 Agent 用）

状态：已定稿（wayfinder 票「轨迹读取接口 spec 收口」的产出，2026-08-23）。
用途：实现前的唯一依据；也是《ATA 轨迹飞轮机制设计》观测一章的底稿。

## 目标

让任何在本机上运行的 Agent，通过一条 CLI 或几个 HTTP 端点，读到 ATA 账本里的会话与事件细节，用来做失败诊断和干预前后对比。只读，不提供任何写入接口。

## 已定取舍（不再重开）

1. CLI 默认走 HTTP API（地址取环境变量 `ATA_URL`），`--ledger PATH` 直接读 SQLite 作为离线兜底。
2. 接口分两层：裸事件流是权威层，Agent 靠它能重建任何视图；分析投影端点是便捷层，省 token。
3. 会话血缘进首版：`sessions` 表加 `parent_session_id` 列，事件侧从 `session.opened.payload.parent_session`（可选字段）取值。哪个适配器能拿到父会话就写，拿不到就是 NULL，查询如实返回空，不猜。
4. Skill 用宿主无关格式，任何支持 Skill 的 Agent 都能装。

## HTTP 端点

已有的 `GET /api/sessions` 和 `GET /api/sessions/<sid>`（Web UI 投影）保持不动。新增五个：

### GET /api/sessions/{sid}/events?after_seq=&limit=

权威层。返回裸事件流，按 seq 升序。

```json
{"ok": true, "events": [{"seq": 12, "event": {...}}], "next_after_seq": 27}
```

- `after_seq` 游标翻页，默认 0；`limit` 默认 100，上限 500。
- `after_seq` 超过末尾时正常返回 200 加空数组（读到了头不是错误）。

### GET /api/sessions/{sid}/lineage

祖先链 + 子女树，字段同 sessions 列表的行。没有血缘就返回两个空数组——NULL 是事实，不是错误。

```json
{"ok": true, "ancestors": [], "children": []}
```

### GET /api/sessions/{sid}/usage

便捷层。每轮一行，外加会话合计。usage 拿不到的轮保留该行，`status` 标 `"missing"`，绝不删行。

```json
{"ok": true, "turns": [
  {"turn": 2, "model": "...", "effort": null, "status": "reported",
   "input": 1840, "output": 612, "cache_read": 220, "cache_write": 48,
   "total_tokens": 2720, "cost": null}],
 "total": {"input": 3944, "output": 1000, "total_tokens": 7076}}
```

合计只累计 `status=reported` 的轮，并在响应里带 `missing_turns` 数量，避免把缺失当零。

### GET /api/sessions/{sid}/tools?status=&name=&full=

便捷层。工具调用清单：`name`、`turn`、`status`、`duration_ms`、`result`。

- **预览规则**：`result` 默认只给尾部 200 字符，开头补 `…`。工具结果的价值集中在结尾（错误信息、最终输出都在后面）。`full=true` 换完整内容。
- `status` 可选 `failed` / `completed`；`name` 按工具名过滤。过滤后为空是正常答案，返回 200 空数组。

### GET /api/sessions/{sid}/compactions?full=

便捷层。压缩点清单：`trigger`、`pre_tokens`、`post_tokens`、`summary`。`summary` 同样默认尾部 200 字符预览，`full=true` 取全文。

## 错误与空数据约定（全端点统一）

| 情形 | 返回 |
| --- | --- |
| 会话不存在 | HTTP 404，`{"ok": false, "error": "unknown session"}` |
| 参数不合法 | HTTP 400，`{"ok": false, "error": "<原因>"}` |
| 血缘为 NULL | HTTP 200，空数组 |
| 过滤后无匹配 | HTTP 200，空数组 |
| usage 缺失 | 该轮保留，`status: "missing"` |

调用方只需记两条：404 才是「没这个东西」，200 的空数组是「存在但为空」。

## CLI

挂在现有入口上：`python3 -m ata read <子命令>`。

```
read sessions   [--agent AGENT] [--since-days N] [--limit N]
read events     SID [--after-seq N] [--limit M]
read lineage    SID
read usage      SID
read tools      SID [--status failed|completed] [--name NAME] [--full]
read compactions SID [--full]
```

全局参数：

- `--url URL`：默认取 `ATA_URL`。连不上时报错并提示可用 `--ledger` 兜底；
- `--ledger PATH`：绕过 HTTP 直读账本文件（复用同一套投影函数，不走网络）；
- `--text`：人看的紧凑视图；默认输出 JSON，给机器消费。

翻页游标与截断纪律同时写进每条命令的 `--help` 和 Skill。

## Skill 大纲（五节，宿主无关）

1. **探活与兜底**：先打 `/api/health`；不通则改用 `--ledger ~/.ata/ata.sqlite` 直读。
2. **发现**：`read sessions` 按 agent、时间过滤，找到目标会话 id。
3. **下钻**：先 `read usage` 和 `read tools --status failed` 看轮廓，有疑点再用 `read events` 精读原始流。
4. **token 纪律**：默认页大小、预览优先、确认要全文再加 `--full`；不要一次拉整段事件流。
5. **隐私与数据边界**：轨迹含会话正文，分析结论不得发往本机之外。各宿主数据边界照实声明：droid 的 usage 恒为 missing；Claude Code 与 Droid 无 SYSTEM 快照；Pi/Cue 有 SYSTEM 快照且 usage 为 reported。Skill 必须附这张表，防止分析 Agent 把缺失当成异常。

## Schema 变更

`sessions` 表加列 `parent_session_id TEXT NULL` 并建索引，沿用 ledger.py 现有的 `ALTER TABLE` 迁移模式，老账本无损升级。`v` 保持 1，不加新事件类型；`session.opened.payload.parent_session` 为可选字段，校验器放行字符串或缺失。

适配器接线顺序（实施期执行，非本票决策）：Pi/Cue 的 live hook 先通；Claude/Codex/Droid 的文件尾随逐个核对各自方言里有无父会话引用，有证据才写。
