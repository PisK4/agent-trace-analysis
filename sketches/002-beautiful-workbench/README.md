## Variant: Beautiful UI 工作台

### Design stance
Beautiful UI 的表面 Token，交互按 dsh `ui-trajectory` 源码对齐。这份稿是上线账本的像素合同：泳道、拖选、四投影、折叠、虚拟行和多分栏检查器都按源码手势复刻，不再做简化条。

### Key choices
- Toolbar: Duration / Actual time / Turns / Calls / Search；右上角只多 Light/Dark
- Timeline: Input / Model / Tools；`sequence` / `duration` / `time` / `actual` 四投影；滚轮缩放、放大后右键平移、拖选边缘平移
- Focus: 闭区间；窗外色块 20%、账本行 24%；搜索不匹配色块 14%；右键单击、双击、Escape 清区间
- Tooltip: 悬停 500ms，kind + 起止钟面 + Total / TTFT
- Ledger: 主表三列；Turn 双击折叠；Assistant 双击折叠其后工具；左侧 `…` 与表头 `Load earlier history` 真加载更早页
- Request: 事件列小圆点打开 Request 检查器；SYSTEM 有 Prompt / Tools / Diff
- Inspector: 工具行 Summary / Payload / Result / Schema / Timing；拖宽 320–720；页签按最近使用记忆；Started 可切 Unix
- Virtual rows: 超过 100 行或仍有更早页时只挂可见窗口，overscan 12
- Theme: 成对 Light/Dark；浅色对照 dsh 截图

### Not copied
dsh 产品名、composer 浮层、`'conversation.view'` slot、Session 快照、隐藏的 Actual time 开关（本稿显式放出，才能点到四种投影）。

### Best for
要把上线交互钉成「dsh 账本手势 + Beautiful UI 表面」的人
