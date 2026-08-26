# 适配器与共享翻译内核 / Adapters and Shared Kernel

五家宿主（Pi / Cue / Droid / Claude Code / Codex） + 代理通道（capture） 共六个适配器，共用同一份翻译词汇表。

| 词 | 定义 |
| --- | --- |
| 适配器 | `ata/plugins/<name>.py`；把某家宿主方言翻成规范事件 |
| 共享内核 | `ata/plugins/common.py`；同构部分（信封、工具双行、轮次递增、usage 三态、CONTEXT 判定）只写一次 |
| 方言差异 | 字段名映射、事件路由、各家 tool start / end 配对规则；留在各自适配器 |
| 工具双行协议 | 一次工具调用拆成 start / end 两条 `tool.upserted`，自然键 `tool_call_id` 收敛；详情见 [`canonical-event-ledger.md`](canonical-event-ledger.md) |

## 六个适配器与通道

| 适配器 | 宿主 | 通道 | 文件 |
| --- | --- | --- | --- |
| `pi` | Pi | 官方 extension / live hook | `ata/plugins/pi.py` |
| `pi` | Cue | Pi 官方 extension / live hook（与 Pi 共享适配器，agent_id 用 `cue`） | `ata/plugins/pi.py` |
| `droid` | Droid | 第一方 sessions / JSONL tail | `ata/plugins/droid.py` |
| `claude` | Claude Code | 第一方 transcript / JSONL tail | `ata/plugins/claude.py` |
| `codex` | Codex | 第一方 rollout / JSONL tail | `ata/plugins/codex.py` |
| `capture` | 任意走代理的宿主 | `--proxy-port` 转发通道 | `ata/plugins/capture.py` |
| `jsonl` | （公共） | 增量 JSONL 读取；非适配器，只被 droid / claude / codex 复用 | `ata/plugins/jsonl.py` |

Cue 与 Pi 共用同一个适配器，区别只在 `agent_id`。两类 SYSTEM 行为相同：拿得到 prompt 全文 + 工具目录（名字 + 单行描述）；usage reported。

## 共享内核的同构部分

`ata/plugins/common.py` 只收「同构」——方言差异留给各适配器。

| 同构点 | 符号 | 适用范围 |
| --- | --- | --- |
| 信封构造 | `make_ev(eid, agent_id, session_id, ts, typ, turn, payload)` | 所有适配器 |
| CONTEXT 注入判定 | `is_context_text(text)` | droid / claude / codex 三个 JSONL 适配器（CONTEXT 不开新轮） |
| usage 三态（reported / missing） | `usage_from_counts(...)` | droid / claude / codex；Pi 走 hook 自带 `usage`，不进内核 |
| usage missing 常量 | `usage_missing()` | 同上 |
| 工具 start payload | `tool_start_payload(cid, parent_mid, name, args, text, started_at)` | claude / codex / droid |
| 工具 end payload | `tool_end_payload(prev, cid, parent_fallback, result, completed_at)` | 同上 |
| 真实用户轮次递增 | `bump_turn_if_real_user(state, texts, agent_id, session_id, ts, emit)` | 同上（CONTEXT 不递增） |
| 「耗时未知」占位 | `PLACEHOLDER_MS = 1` | droid / claude / codex（这些宿主落盘不带耗时） |

JSONL 读取器（`ata/plugins/jsonl.py`）无状态机，只做「字节偏移 + 半行留待下次 + 坏行跳过 + 1s tail」，不属于翻译内核。

## CONTEXT 注入规则

| 项 | 规则 |
| --- | --- |
| 触发前缀 | `<system-reminder>`、`<system-notification>`、`Skill "`、`Skill '` |
| 翻译裁决 | 仍走 `user` 角色；不开新轮；不计入 turns |
| 投影层 | `is_context_text` 同吃，标 `CONTEXT` 与 dsh 对齐 |
| 出处 | 唯一归属地在 `ata/plugins/common.py`；投影层 `ata/project.py` 复用同函数 |

## usage 三态判定

| 输入 | 输出 |
| --- | --- |
| `inp` / `outp` / `cache_read` / `cache_write` 至少一项非零 | `status: "reported"`，附各字段 |
| 全部为 0 / 缺 | `status: "missing"`，各字段 `null` |
| 拿不到（host 落盘就不带） | 直接 `usage_missing()`，不进 `usage_from_counts` |

Pi 不参与——hook 自带 `usage` 对象，落到 `turn.ended.payload.usage`；代理通道的 `capture` 适配器走 `usage_from_counts`，与 JSONL 三家同源。

## 方言差异在哪

| 差异 | 在哪 |
| --- | --- |
| 字段名映射（如 claude 的 `tool_use_id` ↔ `tool_call_id`、codex 的 `function_call` ↔ `tool.upserted`） | 各适配器 `translate_line` |
| 事件路由（如 claude 不发射 `system.upserted`、codex 取 `base_instructions.text`） | 各适配器 `open_session` / `handle_*` |
| tool start / end 配对规则（droid 的 `tool_use` + `tool_result` 配对、codex 的 `function_call` + `_output` 配对） | 各适配器 |
| 标题来源（`ai-title` / `originator` / `session_start.title` / 首条用户消息） | 各适配器 `open_session` |
| 失败状态捕获（claude 的 `api_error`、droid 的 `agent_turn_outcome.reason`、codex 的 `turn_aborted`） | 各适配器 |

## 数据边界

| 边界 | 行为 |
| --- | --- |
| `tools_index` 为空 | 没有 `system.upserted` 的宿主（Droid / Claude）该索引永远空，UI 不画 Schema 页签 |
| Droid 工具参数区 | 显示空对象（`toolSnippets` 合同上限，无 JSON schema） |
| 占位耗时 | droid / claude / codex 的 TOOL 行 `duration_ms=1`（`PLACEHOLDER_MS`），投影层 `summarize_timing` 按 `>PLACEHOLDER_MS` 过滤 |
| 工具卡 result 截断 | 适配器自生成的入参单行描述（`_tool_text(args)`）长度受限，详见各适配器 |

## 引用边界

| 边界 | 不外推成 |
| --- | --- |
| 共享内核的同构点 | 「所有适配器必须用」；不参与的部分（Pi hook / capture 代理）允许不调用 |
| `usage_from_counts` 全 0 计 missing | 任何全 0 都不是「真实 0 token」；是「宿主给了 0，等同于没给」 |
| `is_context_text` 前缀列表 | 全部 dsh 注入；本项目目前观察到这四种前缀 |

## 代码出处

| 概念 | 文件 · 符号 |
| --- | --- |
| 信封 | `ata/plugins/common.py` `make_ev` |
| CONTEXT 判定 | `ata/plugins/common.py` `is_context_text` |
| usage 三态 | `ata/plugins/common.py` `usage_from_counts` / `usage_missing` |
| 工具双行 | `ata/plugins/common.py` `tool_start_payload` / `tool_end_payload` |
| 真实用户轮次 | `ata/plugins/common.py` `bump_turn_if_real_user` |
| 占位耗时 | `ata/plugins/common.py` `PLACEHOLDER_MS` |
| envelope 工厂（CLI / HTTP / droid 共用） | `ata/schema.py` `envelope` |
| 投影侧 usage 三态 | `ata/project.py` `_usage` + `MISS` 常量 |
