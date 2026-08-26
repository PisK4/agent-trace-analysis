# ATA v2 · 展示层对标 dsh Trajectory 的差距清单与落地记录（归档）

> **状态：归档**。本文是 2026-08-16 当天的一次性差距清单与合入动作；所有「本轮落地」项早已合入主干，文末描述的"临时端口 8788 + 临时账本"等口径已无效。
>
> 当前展示层能力以 [`../features/viewer-presentation.md`](../features/viewer-presentation.md) 为准。复用决策见 [`../adr/0000-dsh-ui-reuse.md`](../adr/0000-dsh-ui-reuse.md)。
>
> 原文以下为历史内容，未做修改。

---

- **日期**：2026-08-16
- **性质**：以 dsh（DeepSeek Harness，检出 @ `47f943859b`）Trajectory 为规格，逐项核对 ATA 阅读器展示层的差距、本轮落地与保留的语料边界。复用决策见 [`../adr/0000-dsh-ui-reuse.md`](../adr/0000-dsh-ui-reuse.md)。
- **改动范围**：`web/index.html`、`web/vendor/`、`ata/project.py`、`ata/plugins/droid.py`、`ata/plugins/claude.py`、`tests/`、`README.md`

## 一句话

ATA 的账本手势本就来自 dsh（sketch 的设计立场），缺的是深度：Markdown 从简化渲染升级为完整 GFM + 代码高亮，usage 明细补全，工具 Schema 接通目录索引，thinking 从正文拆出可折叠——语料里没有的计时类细节（TTFT/decoding）如实保留空态。

## 差距清单与落地情况

| # | dsh 细节（锚 `47f943859b`） | ATA 改动前 | 本轮落地 | 验证 |
| --- | --- | --- | --- | --- |
| 1 | 完整 GFM Markdown（micromark/mdast 管线 + 表格） | `markdown()` 只渲染行内代码/粗体/段落 | vendored `marked` 18.0.9，`gfm/breaks` 开启；原始 HTML 一律转义、链接限 http(s)/mailto 后才放行 | 浏览器：H1、GFM 表格、链接 |
| 2 | 代码块高亮（shiki） | 无 | vendored `highlight.js` 11.12.0（common 语言集），token 配色走主题变量（明暗双主题同一份规则） | 浏览器：python 代码块带 `.hljs` 类 |
| 3 | Usage 明细（input/output/cache/total/cost） | 六字段中 `total_tokens`/`cost` 在投影层丢失（bug），前端四格 | `project.py` 透传 `totalTokens`/`cost`；前端六格（新增 Total tokens、Cost，Cost < 0.01 保留三位有效数字） | unittest + 浏览器：`Total tokens 175`、`Cost 0.00123` |
| 4 | Request 面板 Usage | 「Session cumulative」占位文案 | 前端按已加载窗口累计全部 reported 的 assistant 行，标注请求数 | 浏览器：`Session cumulative · 1 request` 六格有值 |
| 5 | 工具 Schema 页签（按工具名查定义） | `row.schema` 恒空 → 「Schema unavailable」 | `project.py` 把全部 `system.upserted` 的 `tools_catalog` 按名字合并为 `tools_index` 随页面下发；前端 Schema 页签从索引取 name/description/parameters | unittest（后写覆盖）+ 浏览器：Read → 参数树 `object → properties → path → required` |
| 6 | Thinking 折叠 | droid/claude 把 thinking 块并进正文本，无独立字段 | 两个适配器把 content 拆成「正文 + thinking」两个字段，text 只含 text 块；前端既有 `.think` 折叠直接生效 | unittest（契约改为拆分）+ 浏览器：展开显示 `planning the plan...` |
| 7 | 搜索 | 只搜已加载窗口 | 顺带把 `thinking` 纳入搜索 blob | — |

## 保留了 dsh 有、ATA 语料无源的细节（空态是数据边界，不是实现缺位）

| dsh 细节 | 为什么 ATA 保持空态 |
| --- | --- |
| TTFT / decoding / 吞吐 | dsh 的计时来自自身 `turn/step` 事件；Pi/Claude/Codex/Droid 语料没有首 token 与生成分段计时 |
| subtool 树 | dsh 的 `SUBTOOL` 事件类型与子代理派生结构；四种语料的工具事件没有子代理层级 |
| master 请求模型 | dsh 有独立的 `request/header` 请求级事件；ATA 用 `request_no` 投影近似，无模型字段可填 |
| katex 数学渲染 | dsh 的 `ui-primitives` 带 katex；agent 会话正文里数学公式是零需求，需要时再 vendor |
| Pi 通道的 thinking 拆分 | Pi hook 的 message 是流式 start/end 两次写入，拆分 thinking 会让中间态不一致；droid/claude 的 content 块结构天然可分，已拆 |
| 虚拟滚动/时间轴手势 | ATA 已有（阈值 100、overscan 12、拖选、缩放、500ms tooltip），无差距 |

## 后端契约变化

`GET /api/sessions/{id}` 响应新增 `tools_index`（对象，按工具名索引的目录条目；无目录时为空对象）。`rows[]` 的 message 行新增 `thinking` 字段（无 thinking 时为 `null`）、usage 对象新增 `totalTokens`/`cost`。三个新增都是加字段，不改变既有字段语义，旧前端可忽略。

## 验证记录

- `make test`：29 个用例全过（新增 `test_tools_index_merges_catalog`、`test_thinking_split_from_text` 契约更新、`test_usage_and_order` 补透传断言）
- 常驻服务：`install-service.sh restart` 后 `/api/health` 正常
- 浏览器（临时端口 8788 + 临时账本，未碰生产数据）：GFM、高亮、thinking、六格 usage、Session cumulative、Schema 参数树逐项 DOM 验证通过
