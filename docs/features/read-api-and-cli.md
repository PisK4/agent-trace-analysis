# 读取接口与 CLI / Read API and CLI

只读接口让任何在本机运行的 Agent 通过 HTTP 或 CLI 读账本。CLI 默认走 HTTP（`ATA_URL`），`--ledger PATH` 离线兜底直读 SQLite。

| 词 | 定义 |
| --- | --- |
| 权威层 | 裸事件流；Agent 拿它能重建任何视图 |
| 便捷层 | 投影端点（usage / tools / compactions / tool-stats / timing）；省 token |
| 预览 | 便捷层正文默认尾部 200 字符（开头补 `…`）；`full=true` 取全文 |
| missing | 数据缺失；该字段记 `null` / 该轮保留并标 `status: "missing"`，不删行 |

## HTTP 端点（详情见 [`../../specs/agent-read-interface.md`](../../specs/agent-read-interface.md)）

| 端点 | 层 | 用途 |
| --- | --- | --- |
| `GET /api/sessions` | 便捷层 | 会话列表（`h_sessions`） |
| `GET /api/sessions/{sid}` | 便捷层 | 单会话投影（标题 / turns / rows / tools_index） |
| `GET /api/sessions/{sid}/events?after_seq=&limit=` | 权威层 | 裸事件流，按 seq 升序 |
| `GET /api/sessions/{sid}/lineage` | 便捷层 | 祖先链 + 子女树 |
| `GET /api/sessions/{sid}/usage` | 便捷层 | 每轮 usage + 会话合计 + `missing_turns` |
| `GET /api/sessions/{sid}/tools?status=&name=&full=` | 便捷层 | 工具调用清单 |
| `GET /api/sessions/{sid}/tool-stats` | 便捷层 | 工具计数 + 调用时间序列（供 UI 钻取） |
| `GET /api/sessions/{sid}/timing` | 便捷层 | 时间拆解（LLM vs 工具逐轮） |
| `GET /api/sessions/{sid}/compactions?full=` | 便捷层 | 压缩点清单 |

`/api/sessions/{sid}` 是统一入口；按 URL 子路径分发到上述便捷层。`h_session` 在 `ata/http.py`。

## CLI

挂在 `python3 -m ata read` 与 `python3 -m ata rate` 两个子命令上。

| 子命令 | 对应端点 | 关键参数 |
| --- | --- | --- |
| `read sessions` | `GET /api/sessions` | `--agent`、`--since-days`、`--limit` |
| `read events SID` | `GET /api/sessions/{sid}/events` | `--after-seq`、`--limit` |
| `read lineage SID` | `GET /api/sessions/{sid}/lineage` | — |
| `read usage SID` | `GET /api/sessions/{sid}/usage` | — |
| `read tools SID` | `GET /api/sessions/{sid}/tools` | `--status failed\|completed`、`--name`、`--full` |
| `read compactions SID` | `GET /api/sessions/{sid}/compactions` | `--full` |
| `rate` | 直接读账本 + 五个便捷端点 | `--ledger`、`--url` |

`read` 默认输出 JSON（机器消费）；`--text` 切人看的紧凑视图。

`read` 与 `rate` 都接受 `--url`（默认取 `ATA_URL`）与 `--ledger`（绕过 HTTP 直读账本）。两路共享同一套投影函数，输出形状一致。

## 错误与空数据约定

| 情形 | 返回 |
| --- | --- |
| 会话不存在 | HTTP 404，`{"ok": false, "error": "unknown session"}` |
| 参数不合法 | HTTP 400，`{"ok": false, "error": "<原因>"}` |
| 血缘为 NULL | HTTP 200，空数组 |
| 过滤后无匹配 | HTTP 200，空数组 |
| usage 缺失 | 该轮保留，`status: "missing"` |
| `/api/sessions` 远端 | 返回裸数组（不带 `ok` 包装），CLI 内部归一化 |

## 端点细节（与代码对齐）

| 端点 | 关键实现 |
| --- | --- |
| `/api/sessions/{sid}/usage` | `summarize_usage(recs)`；合计只累计 `status="reported"` 的轮，响应带 `missing_turns` |
| `/api/sessions/{sid}/tools` | `list_tools(recs, status, name)`；`result` 默认尾部 200 字符预览 |
| `/api/sessions/{sid}/tool-stats` | `summarize_tools(recs)`；含每工具调用时间序列，UI 钻取用 |
| `/api/sessions/{sid}/timing` | `summarize_timing(recs)`；LLM vs 工具逐轮分解；`PLACEHOLDER_MS` 过滤 |
| `/api/sessions/{sid}/compactions` | `list_compactions(recs)`；`summary` 同预览规则 |
| `/api/sessions/{sid}/events` | `ledger.read(sid, after_seq, limit)`；按 seq 升序，`next_after_seq` 翻页游标 |
| `/api/sessions/{sid}/lineage` | 查 `sessions.parent_session_id`；NULL 走事实，不猜 |

## Skill 大纲（宿主无关）

1. 探活与兜底：先打 `/api/health`；不通则改用 `--ledger ~/.ata/ata.sqlite` 直读。
2. 发现：`read sessions` 按 agent、时间过滤，找到目标会话 id。
3. 下钻：先 `read usage` 和 `read tools --status failed` 看轮廓，有疑点再用 `read events` 精读原始流。
4. token 纪律：默认页大小、预览优先、确认要全文再加 `--full`；不要一次拉整段事件流。
5. 隐私与数据边界：轨迹含会话正文，分析结论不得发往本机之外；各宿主数据边界照实声明（见 [`session-data-sources.md`](session-data-sources.md)）。

## 数据边界

| 边界 | 行为 |
| --- | --- |
| `tools_index` 缺失 | 没有 `system.upserted` 的会话该字段为空对象，UI 不画 Schema 页签 |
| usage 缺失 | 该轮保留行，`status: "missing"`，计入 `missing_turns` |
| Droid usage | 恒 missing（契约上限，不是 bug） |
| Claude / Droid SYSTEM | 无快照；代理通道开启时才有（见 [`proxy-capture-channel.md`](proxy-capture-channel.md)） |

## 引用边界

| 边界 | 不外推成 |
| --- | --- |
| 五个便捷端点 | 全部能力；tool-stats / timing 是 UI 钻取用的便捷层，不是事实源 |
| CLI 默认 HTTP | 「`--ledger` 是离线选项」；它不是另一套语义，只是绕过网络 |
| `read` JSON 默认 | 「只有 JSON」；`--text` 是人看的紧凑视图，与 JSON 同源 |

## 代码出处

| 概念 | 文件 · 符号 |
| --- | --- |
| 端点分发 | `ata/http.py` `h_sessions` / `h_session` |
| 投影函数 | `ata/project.py` `list_tools` / `summarize_usage` / `summarize_tools` / `summarize_timing` / `list_compactions` / `project_session` |
| 缓存（便捷层 rev 门控） | `ata/projection_cache.py` |
| CLI `read` / `rate` | `ata/cli.py` `read` 子命令 + `_remote` + `_local` |
| 离线兜底 | `--ledger` 路径；`cli.py` `_local` |
| 接口定稿 | [`../../specs/agent-read-interface.md`](../../specs/agent-read-interface.md) |
