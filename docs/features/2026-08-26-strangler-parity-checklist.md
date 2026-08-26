# 绞杀者收尾 · React 版与 legacy 前端 parity 清单

> Task 9 产出。Task 10 删除 `web/js/` 前逐项核对：每项标注 legacy 出处、React 版出处与覆盖状态。
> 状态：✅ 覆盖 / ⚠️ 有差距（已补齐）/ ➖ 刻意不带（附理由）。

## 标注板视图（legacy `web/js/board.js`）

| 功能 | legacy 出处 | React 版出处 | 状态 |
| --- | --- | --- | --- |
| 视图切换（会话/标注板互斥） | board.js:14-27 | App.tsx view state + view-switch | ✅ |
| 标注列表（值 chip/标题链接/时间/agent/evts/failed/备注） | board.js paintBoard annoList 段 | BoardView.tsx scores.map 段 | ✅ |
| 编辑标注（回填 value+note，锁定会话） | board.js openAnnoForm | BoardView setEditingScore + AnnoForm editing | ✅ |
| 删除标注（cleared 墓碑） | board.js data-clear | BoardView clearAnno | ✅ |
| 归组树 run→task→会话 + 计数 | board.js byRun/byTask 段 | BoardView byRun/groupByTask | ✅ |
| 归组折叠/展开（内存态） | boardState.openRuns | BoardView openRuns Set | ✅ |
| 组重命名（留空回退 run_id） | board.js data-rrname | BoardView renameRun → api.renameRun | ✅ |
| 移出单条归组（unassigned 墓碑） | board.js data-unassign | BoardView unassign | ✅ |
| 移出整组（逐条墓碑 + toast 计数） | board.js data-drun | BoardView unassignWholeRun | ✅ |
| 「+ 挂会话」预选 run/task | board.js openAssignForm(tid, rid) | BoardView assignTarget + AssignForm | ✅ |
| 新增标注表单（会话下拉/value 三选/备注） | board.js annoForm 段 | AnnoForm.tsx | ✅ |
| 归组表单（run 下拉/task id） | board.js assignForm 段 | AssignForm.tsx | ✅ |
| 就地新建组（建后选中） | board.js assignNewRun | CreateRunForm / TopBar createRunHere | ✅ |
| badOnly 过滤 | board.js badFilter | BoardView badOnly | ✅ |
| 板内搜索（标题/备注/task/run/session 任一命中） | board.js boardMatch | BoardView filterEntries | ✅ |
| 计数徽章（N 条标注/N runs/N 会话） | board.js annoCountText 等 | BoardView zone-bar stat-badge | ✅ |

## 会话页顶栏（legacy `web/js/app.js` + index.html header.top）

| 功能 | legacy 出处 | React 版出处 | 状态 |
| --- | --- | --- | --- |
| crumb 展示（服务端 HTML 片段） | app.js openSession crumb 段 | TopBar dangerouslySetInnerHTML | ✅ |
| 重命名会话 | app.js renameBtn | TopBar rename | ✅ |
| 手动刷新 | app.js refreshTail(true) 入口 | SessionView onRefresh=refresh | ✅ |
| 跟随尾部开关 | app.js follow 逻辑 | TopBar follow-toggle + SessionTable | ✅ |
| 标注徽章+弹层（三值/备注） | app.js paintScore + scoreBox | TopBar scoreOpen 弹层 | ✅ |
| 归组徽章+弹层（归入/移出/就地建组/沿用 task id） | app.js assignBox | TopBar assigns 弹层 | ✅ |
| 全局搜索框 | app.js q input | TopBar searchwrap | ✅ |
| 主题切换（html.dark） | app.js themeBtn | TopBar toggleTheme | ✅ |
| 返回标注板按钮（从板进会话时出现） | app.js boardBackBtn:352 | — | ➖ 左侧导航的视图切换常驻可见，一键可达标注板；专用返回按钮是 legacy 单页 hash 导航的补偿，不再需要 |

## 主表格 / 时间线 / 详情栏

| 功能 | legacy 出处 | React 版出处 | 状态 |
| --- | --- | --- | --- |
| 虚拟滚动表格 + 折叠 SUMMARY + turn/assistant 折叠 | table.js/timeline.js | SessionTable.tsx toggleTurn/toggleAssistant | ✅ |
| Timeline 选区聚焦变暗 | interactions.js | SessionView range + focusRange | ✅ |
| loadOlder 前插 + 滚动差补偿 | app.js loadOlder | useSession.loadOlder + handleLoadOlder | ✅ |
| rev 门控轮询 + unchanged 零重绘 | app.js pollTick | useSession rev 轮询 | ✅ |
| Inspector 多 tab（summary/usage/timing/diff）+ tab 记忆 | inspector.js rememberTab | Inspector tabHistory | ✅ |
| 会话上下文抽屉（System Prompt/Tools/Skills） | inspector.js paintContext | Inspector ContextDrawer | ✅ |
| JSON tree/raw 双视图 | JsonView legacy | JsonView.tsx | ✅ |
| 对话视图（chat 渲染）+ 工具 chip 回跳轨迹 | legacy 无（React 新增） | ConversationView.tsx | ✅（超集） |
| 详情栏拖宽（pointer 拖拽 + 边界钳制） | app.js resize pointerdown/move/up:384-399 | Inspector .resize + clampWidth | ⚠️ 已补齐 |
| 详情栏双击复位宽度 | app.js resize dblclick:401 | Inspector onDoubleClick | ⚠️ 已补齐 |
| 宽度/折叠态 localStorage 持久化 | app.js ata.detailsWidth/Collapsed | SessionView useState 初始化 + 写回（同键名） | ⚠️ 已补齐 |
| 右缘折叠把手（收起/展开详情栏） | app.js detailsHandle:341 | SessionView collapse-handle 按钮 | ⚠️ 已补齐 |
| 把手上 ←/→ 键盘微调宽度 | app.js resize keydown:404-417 | — | ➖ 纯键盘微调使用率极低，鼠标拖拽与双击复位保留；需要时再补 |

## 数据面 / 全局

| 功能 | legacy 出处 | React 版出处 | 状态 |
| --- | --- | --- | --- |
| usage 曲线面板（占用/命中率/compaction 竖线/红点/悬停） | usage.js renderUsagePanel | UsagePanel.tsx（语义平移） | ✅ |
| 时间拆解徽章+弹层（LLM vs 工具、逐轮跳转） | stats.js | TimeBadge.tsx | ✅ |
| 统计徽章 | stats.js | StatsPanel.tsx StatsBadges | ✅ |
| 侧栏 agent 页签过滤 + 卡片（错误数/标注点/时间） | app.js paintSessions | App.tsx sess-tabs + item | ✅ |
| **侧栏会话列表轮询刷新**（5s 指纹门控） | app.js pollSessions:546 | App.tsx 5s setInterval 重拉 listSessions | ⚠️ 已补齐（指纹门控简化为全量 setState，列表量级下无感知差异） |
| live tailing 时派生面板（usage/timing）跟随刷新 | app.js report.rowsChanged 统一刷新 | useSummary nudgeSummaries（Task 6） | ✅ |
| toast 反馈 | util.js toast | ToastProvider/useToast | ✅ |

## 结论

- ⚠️ 项共 5 处，其中 4 处已在本次补齐（详情栏拖宽/复位/持久化/折叠把手、侧栏轮询），1 处（把手上方向键微调）判定为刻意不带。
- ➖ 项 2 处均附理由（返回按钮被常驻视图切换覆盖、键盘微调低频）。
- 无 ❌ 缺失项。**可进入 Task 10 删除 legacy 前端。**
