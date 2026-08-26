# Atatrace 阅读器展示层 / Atatrace Presentation Layer

把账本事件流折成可读视图的能力清单。所有视觉规则收在 `webapp/src/styles/`，第二份 CSS 不复存在。

| 词 | 定义 |
| --- | --- |
| 视觉体系 | 颜色 / 间距 / 字号等 token；收在 `webapp/src/styles/style.css` |
| 主表 | 虚拟滚动的轨迹表；`SessionTable.tsx` |
| 详情栏 | 右侧多 tab 检查器；`Inspector.tsx` |
| 对话视图 | 只看「人说 + 模型答」的工具收单行链模式；`ConversationView.tsx` |

## 展示能力

| 能力 | 形态 | 落点 |
| --- | --- | --- |
| 完整 GFM Markdown | 表格、任务列表、删除线、自动链接 | `webapp/src/lib/markdown.ts` `Marked({ gfm: true, breaks: true })` |
| 代码块高亮 | `highlight.js` common 语言集；token 配色走 CSS 变量（明暗双主题） | `webapp/src/lib/markdown.ts` `highlightIn` |
| HTML 转义 | 原始 HTML 一律转义；不做高信任 | `webapp/src/lib/markdown.ts` `esc` |
| 链接白名单 | 只放行 `http(s)` / `mailto` | `webapp/src/lib/markdown.ts` `renderer.link` |
| Thinking 折叠 | 适配器把 content 拆成「正文 + thinking」两个字段；前端折叠 | `webapp/src/components/session/ConversationView.tsx` |
| 工具 Schema 页签 | 从 `tools_index` 取 `name` / `description` / `parameters` | `webapp/src/components/session/Inspector.tsx` Schema tab |
| Usage 六格 | input / output / cacheRead / cacheWrite / totalTokens / cost | `webapp/src/components/session/UsagePanel.tsx` + `inspectorModel.ts` |
| Session cumulative | 已加载窗口累计全部 reported 的 assistant 行 | `webapp/src/components/session/UsagePanel.tsx` |
| 工具统计 + 钻取 | 徽章 + 弹层 + 钻取 + 跳转 | 详见 [`tool-stats-debug-view.md`](tool-stats-debug-view.md) |
| 时间拆解 | LLM 生成 vs 工具执行逐轮分解；`PLACEHOLDER_MS` 过滤 | `webapp/src/components/session/TimeBadge.tsx` + `lib/timing.ts` |
| 对话视图 | 工具收成单行链；`conversationModel` 纯函数 | `webapp/src/components/session/ConversationView.tsx` + `lib/conversationModel.ts` |
| 标注板视图 | 标注 + 归组 + 树状组织 | `webapp/src/components/board/BoardView.tsx` + `AnnoForm` + `AssignForm` |
| 主题切换 | 明 / 暗双主题同一份 token | `webapp/src/styles/style.css` |
| 详情栏拖宽 / 折叠 / 持久化 | pointer 拖拽 + 边界钳制 + localStorage | `webapp/src/components/session/Inspector.tsx` + `SessionView.tsx` |
| 侧栏 agent 筛选 | 按 agent 类型 tab 过滤 | `webapp/src/components/App.tsx` `sess-tabs` |
| 侧栏轮询刷新 | 5s `setInterval` 拉 `listSessions` | `webapp/src/components/App.tsx` |
| live tailing 派生刷新 | `useSummary` 统一刷新派生面板 | `webapp/src/api/useSummary.ts` |

## 视觉体系单一事实源

| 文件 | 角色 |
| --- | --- |
| `webapp/src/styles/ata.css` | 入口；`@import "./style.css"` |
| `webapp/src/styles/style.css` | 实际规则；明暗双主题同一份变量 |
| `web/style.css` | 已删（绞杀者收尾 `chore(web) 076b3f5`） |
| 任何第三方 UI 库 | 只做局部增强（按钮 / 弹层 / 表单 / 下拉） |

样式改动只落 `webapp/src/styles/`；不为同一视觉规则建立第二份 CSS。

## 数据边界

| 边界 | 行为 |
| --- | --- |
| Droid 工具参数区 | 显示空对象（`toolSnippets` 合同上限，无 JSON schema） |
| Claude Code / Droid 无 SYSTEM 行 | 无 System Prompt / Tools / Diff 页签，不是 bug |
| Droid / Claude 无 tools_index | Inspector 不画 Schema 页签 |
| Droid usage 恒 Missing | Usage 六格全 `—`；契约上限 |
| 本地中转语料 cache_read / cache_write | 系统性为 `null`；不单独成图 |
| 解析失败 | `markdownHtml` 退化为换行保留的纯文本 |
| 高亮失败 | 保留纯文本；不抛错 |
| TTFT / decoding | 不存在；语料里没有（见 [`session-data-sources.md`](session-data-sources.md)） |

## 引用边界

| 边界 | 不外推成 |
| --- | --- |
| 视觉规则全在 React 端 | legacy `web/style.css` 仍可访问；它已 `rm` |
| 明暗双主题同一份规则 | 任意未来主题；现状锁在 `style.css` 变量 |
| 第三方 UI 库只做局部增强 | 设计系统底座；引入前走 ADR |

## 代码出处

| 概念 | 文件 |
| --- | --- |
| Markdown 渲染 | `webapp/src/lib/markdown.ts` |
| 高亮 | `webapp/src/lib/markdown.ts` `highlightIn` |
| Usage 六格 | `webapp/src/lib/inspectorModel.ts` + `webapp/src/components/session/UsagePanel.tsx` |
| 工具 Schema | `webapp/src/components/session/Inspector.tsx` Schema tab |
| Thinking 折叠 | `webapp/src/components/session/ConversationView.tsx` |
| 时间拆解 | `webapp/src/lib/timing.ts` + `webapp/src/components/session/TimeBadge.tsx` |
| 对话视图 | `webapp/src/components/session/ConversationView.tsx` + `webapp/src/lib/conversationModel.ts` |
| 标注板视图 | `webapp/src/components/board/BoardView.tsx` + `AnnoForm` + `AssignForm` |
| 视觉体系 | `webapp/src/styles/ata.css` + `style.css` |
| 决策 | [`../adr/0000-dsh-ui-reuse.md`](../adr/0000-dsh-ui-reuse.md) |
| 能力对齐历史 | [`../archive/2026-08-16-ata-v2-dsh-trajectory-alignment.md`](../archive/2026-08-16-ata-v2-dsh-trajectory-alignment.md) |
