# Webapp 绞杀者重写 / Webapp Strangler Restyle

把旧的零构建 vanilla JS 前端（`web/js/`）替换成 React + Vite。收尾后 `web/dist` 是唯一前端，legacy 已删。

| 词 | 定义 |
| --- | --- |
| webroot | `web/dist`（Vite 构建产物）；`ata serve` 默认参数 `--web web/dist` |
| legacy 前端 | `web/index.html` + `web/js/*.js` + `web/style.css` + `web/vendor/`；`chore(web) 076b3f5` 已删 |
| 视觉体系单一事实源 | React 版样式只在 `webapp/src/styles/`；旧 `web/style.css` 不复存在，CSS 改动不落第二处 |

## 决策回顾

| 选项 | 结论 |
| --- | --- |
| dsh Trajectory React 组件直接搬 | 不可行（dsh 强绑 boot manifest + RPC，不存在可独立消费资产） |
| 零构建 vanilla JS 续命 | 已到复杂度上限；状态层、过滤 chips、usage 趋势、对话视图都堆到一定体量 |
| 绞杀者收尾 | 采纳。React + Vite 栈，但视觉体系延续旧 CSS（详见下） |

裁决过程见 [`../adr/0000-dsh-ui-reuse.md`](../adr/0000-dsh-ui-reuse.md)。

## 视觉体系单一事实源

| 文件 | 角色 |
| --- | --- |
| `webapp/src/styles/ata.css` | 入口；`@import "./style.css"`；约定所有样式改动只落本目录 |
| `webapp/src/styles/style.css` | 实际 token + 组件规则；旧 `web/style.css` 的语义继承 |
| `web/style.css` | 已删；不再有第二份 CSS |
| 任何第三方 UI 库 | 只用于标准控件（按钮 / 弹层 / 表单 / 下拉）的局部增强；引入前走 ADR |

构建链只信 `webapp/`（Vite 根）；构建不能跨目录依赖。Vite 配置 `webapp/` 为工作根，产物 `dist/` 由 `ata serve` 当 webroot 静态托管。

## 组件切分

```
webapp/src/
  api/                       # 数据获取：client / useSession / useSummary / types / merge
  components/
    App.tsx                  # 顶层 view state
    board/                   # 标注板视图
      BoardView.tsx + AnnoForm + AssignForm + useBoard
    session/                 # 会话视图
      SessionView.tsx        # 容器
      TopBar.tsx             # 头部
      Timeline.tsx           # 时间轴与泳道
      SessionTable.tsx       # 主表 + 虚拟滚动
      ConversationView.tsx   # 对话视图（仅显示人说 + 模型答）
      Inspector.tsx          # 详情栏多 tab
      JsonView.tsx           # JSON tree/raw 双视图
      UsagePanel.tsx         # usage 曲线 + 累计
      StatsPanel.tsx + stats.ts  # 工具统计徽章与弹层
      TimeBadge.tsx          # 时间拆解徽章
      usage.tsx              # usage 趋势接线
    ToastProvider.tsx + toast.ts
  lib/                       # 纯函数模型：conversationModel / tableModel / timelineModel
                             #            inspectorModel / timing / markdown / format
  styles/                    # ata.css + style.css
  test/                      # 单元测试
```

| 分层 | 职责 |
| --- | --- |
| `api/` | 服务端契约封装；React hook；与组件解耦 |
| `components/` | 视图；状态在 hook 与本地 state，不直接调 fetch |
| `lib/` | 纯函数（无 React 依赖），便于单测；模型与视图分离 |
| `styles/` | 视觉体系 |
| `test/` | 单测；与代码同目录或 `src/test/` |

## parity 收尾（与 2026-08-26 表对齐）

| legacy 能力 | 落点 | 状态 |
| --- | --- | --- |
| 标注板视图 + 归组 | `BoardView.tsx` + `AnnoForm` + `AssignForm` | 覆盖 |
| 会话页顶栏（crumb / 改名 / 刷新 / 跟随） | `TopBar.tsx` | 覆盖 |
| 主表 / 时间线 / 详情栏 | `SessionTable` / `Timeline` / `Inspector` | 覆盖 |
| 详情栏拖宽 / 折叠 / 持久化 | `Inspector.tsx` + `SessionView.tsx` localStorage | 覆盖（2026-08-26 补齐） |
| 侧栏会话列表轮询 | `App.tsx` 5s `setInterval` | 覆盖（指纹门控简化为全量 setState） |
| usage 曲线 / 时间拆解 / 统计徽章 | `UsagePanel.tsx` / `TimeBadge.tsx` / `StatsPanel.tsx` | 覆盖 |
| 对话视图（仅人说 + 模型答） | `ConversationView.tsx` + `lib/conversationModel.ts` | React 新增（legacy 无） |
| 工具统计 + 钻取 + 跳转 | `StatsPanel.tsx` + `stats.ts` | 覆盖（详见 [`tool-stats-debug-view.md`](tool-stats-debug-view.md)） |
| 返回标注板按钮 | — | 刻意不带（常驻视图切换覆盖） |
| 详情栏把手上方向键微调 | — | 刻意不带（鼠标拖拽 + 双击复位保留） |

详情与历史补丁见 [`../archive/2026-08-26-strangler-parity-checklist.md`](../archive/2026-08-26-strangler-parity-checklist.md)。

## 关键不变量

| 不变量 | 含义 |
| --- | --- |
| 样式改动只落 `webapp/src/styles/` | 不为同一视觉规则建立第二份 CSS |
| 第三方 UI 库只做局部增强 | 不做设计系统底座；引入前走 ADR（见 [`codebase-boundaries.md`](codebase-boundaries.md)） |
| 注释只写「读代码得不到的信息」 | 不写脚手架占位、Phase X、临时 TODO（这些放任务系统或 plans） |
| `lib/` 保持纯函数 | 便于单测；视图逻辑不渗入 |
| 视觉 token 走 CSS 变量 | 明暗双主题同一份规则（详见 `style.css`） |

## 引用边界

| 边界 | 不外推成 |
| --- | --- |
| 绞杀者收尾完成 | 「legacy `web/js/` 仍可访问」；它已 `rm` |
| 视觉体系单一事实源 | 「所有样式都进 React」；CSS Modules / Tailwind 之类未引入 |
| React 19 / Vite 6 | 任意未来前端栈；现状锁在 `webapp/package.json` |

## 代码出处

| 概念 | 文件 |
| --- | --- |
| 入口样式 | `webapp/src/styles/ata.css` |
| 实际样式 | `webapp/src/styles/style.css` |
| 数据 hook | `webapp/src/api/useSession.ts` / `useSummary.ts` |
| 会话视图 | `webapp/src/components/session/SessionView.tsx` |
| 标注板视图 | `webapp/src/components/board/BoardView.tsx` |
| 纯函数模型 | `webapp/src/lib/*` |
| webroot 默认 | `ata/__main__.py` `--web` 默认 `web/dist` |
| 静态托管 | `ata/http.py` `make_server(ledger, webroot, ...)` |
| 决策 | [`../adr/0000-dsh-ui-reuse.md`](../adr/0000-dsh-ui-reuse.md) |
