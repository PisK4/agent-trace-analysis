# Runtime Runs 与 Evaluations 前端工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 React 前端真实消费后端的 Session/Run/Turn/Evaluation 分层契约，提供可筛选的 Run/Turn 阅读体验、可审计的 Evaluation 工作台，并清理迁移遗留逻辑。

**Architecture:** 保持后端作为唯一事实与派生规则来源。Session 页面通过新增的 `useRuns` 数据层读取当前 Session 作用域内的 Run，使用共享的 `RunPanel` 选择 Run，再由 `SessionView` 将选中的 canonical Run identity 传给表格和 Turn 查询；runless 事件继续以 `Observed N` 显示，绝不推断 Run。Evaluation 页面在现有 CRUD 上增加 history、Overview 统计、task label/agent/failed 过滤与明确的 API 错误反馈；评分仍复用成员 Session 的最新 score，不复制 Evaluation score。所有状态更新沿用现有 React hooks、`api` client 和 CSS 单一事实源。

**Tech Stack:** React 19、TypeScript 6、Vite、Vitest、@testing-library/react、现有 `webapp/src/api` hooks、`webapp/src/lib/turnIdentity.ts`、`webapp/src/styles/`。

**Spec:** `docs/features/runtime-runs-and-evaluations.md`

## Global Constraints

- `Turn identity` 必须使用 `(run_id, turn_number)`；同一 Session 中不同 Run 的 `T1` 不能碰撞。
- 没有 lifecycle 证据的事件保留 `run_id=null`、`turn_number=null`，按 `observed_turn_ordinal` 展示为 `Observed N`，不能猜测 Run。
- Run 读取始终限定在 Session scope；React 只消费 HTTP/query facade 返回的 status、conflict 与 identity，不自行重建后端规则。
- Evaluation 只引用已有 Session，不拥有或修改 Run，不复制 Session score；history 保留 Evaluation facts 的审计顺序。
- 同一 Session 最多属于一个 active Evaluation；添加冲突必须把后端错误明确显示给用户，不能静默失败。
- 生产代码修改前遵守 `repos/ata/AGENTS.md` 的 `/ponytail full` 工作流；样式只修改 `webapp/src/styles/`，不创建第二份 CSS 事实源。
- 不引入运行期下载、演示模式、第二 writer 或第二事实源；fixture 不包含真实会话正文、密钥或真实 Base URL。
- 完成生产代码后必须运行 `make test`、`./scripts/install-service.sh restart` 和 `curl -s http://127.0.0.1:17877/api/health`。

---

## 文件结构与职责

- **Modify:** `webapp/src/api/types.ts` — 增加 Run/Turn/Evaluation history 的精确响应类型，避免组件使用 `unknown` 或重新解释后端 payload。
- **Modify:** `webapp/src/api/client.ts` — 增加 `evaluationHistory` 与带 `run_id` 的 Turn 读取入口，集中处理 HTTP 错误。
- **Create:** `webapp/src/api/useRuns.ts` — 当前 Session 的 Run 列表、选中 Run、加载错误与刷新状态。
- **Create:** `webapp/src/api/useRuns.test.tsx` — hook 的初始加载、Session 切换、刷新和失败测试。
- **Create:** `webapp/src/components/session/RunPanel.tsx` — Session 级 Run navigator 与 runless 状态说明。
- **Create:** `webapp/src/components/session/RunPanel.test.tsx` — status/conflict/selection/accessibility 渲染测试。
- **Modify:** `webapp/src/components/session/SessionView.tsx` — 接入 Run hook，维护 selected Run，向表格、TopBar、Turn 跳转传递过滤条件。
- **Modify:** `webapp/src/components/session/SessionTable.tsx` — 增加 Run 过滤控制并使用完整 identity 过滤 canonical rows；保留 observed rows 在“全部”视图中。
- **Modify:** `webapp/src/components/session/TopBar.tsx` — 将 Turns 徽章升级为 Runs/Turns/冲突摘要，不把 runless observed turn 误标为 Run。
- **Modify:** `webapp/src/components/evaluation/EvaluationView.tsx` — 增加 Overview/Sessions/History 面板、过滤器、统计和错误提示。
- **Modify:** `webapp/src/components/evaluation/EvaluationForm.tsx` — 过滤不可添加的成员，并在 API 失败后保持输入和可重试状态。
- **Modify:** `webapp/src/components/evaluation/EvaluationSessionList.tsx` — 接收已过滤成员并保持 score、task label、failed metadata 的语义展示。
- **Modify:** `webapp/src/api/useEvaluations.ts` — 加载当前 Evaluation history，写操作后刷新 detail/history/list，并保留可展示错误。
- **Create:** `webapp/src/api/useEvaluations.test.tsx` — history 加载、写后刷新、失败错误测试。
- **Modify:** `webapp/src/components/App.tsx` — 删除无效的 `scores` cast/圆点逻辑，避免暗示 Session 列表有未提供的 score 数据。
- **Modify:** `webapp/src/styles/style.css` — 仅添加 Run navigator、Evaluation tabs/summary/history/filter 的样式，复用现有 token 和控件档位。
- **Modify:** `webapp/src/lib/tableModel.ts` — 如需过滤，新增纯函数 `filterRowsByRun`；保持 `rowTurnKey`/`turnIdentityKey` 作为唯一 identity 入口。
- **Modify:** `webapp/src/lib/tableModel.test.ts` — canonical Run 过滤、跨 Run 同一 turn_number 不碰撞、observed rows 行为测试。
- **Create:** `webapp/src/components/session/SessionView.test.tsx` — Run selection 与 Run-scoped table/jump 集成测试。
- **Modify:** `webapp/src/api/types.test.ts` 或新增 `webapp/src/api/client.test.ts` — API path、history 与 response shape 测试。

---

### Task 1: 固化前端 Run/Turn 与 Evaluation History 类型及 API seam

**Files:**
- Modify: `webapp/src/api/types.ts:147-228`
- Modify: `webapp/src/api/client.ts:49-63`
- Create: `webapp/src/api/client.test.ts`

**Interfaces:**
- Produces `EvaluationHistoryEntry`，包含后端 history fact record 的 `seq: number` 与 `event: { type: string; ts: number; payload: Record<string, unknown> }`；client 不折叠或重排 facts。
- Produces `api.evaluationHistory(id: string): Promise<{ ok: true; evaluation_id: string; events: EvaluationHistoryEntry[] }>`；hook 再把 `events` 命名为页面状态里的 `history`。
- Produces `api.turns(sessionId: string, runId?: number): Promise<{ ok: true; turns: TurnInfo[] }>`，将现有 `unknown[]` 换成明确的 `TurnInfo[]`，其中 `run_id`, `turn_number`, `observed_turn_ordinal`, `status`, `first_seq`, `last_seq` 与后端字段一致。

- [ ] **Step 1: 写 API 失败测试**

```ts
it('requests evaluation history with an encoded id', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(
    JSON.stringify({ ok: true, evaluation_id: 'e/a', events: [{ seq: 1, event: { type: 'evaluation.created', ts: 10, payload: { title: 'smoke' } } }] }),
    { status: 200, headers: { 'content-type': 'application/json' } },
  )))
  await expect(api.evaluationHistory('e/a')).resolves.toEqual(expect.objectContaining({ ok: true, events: expect.any(Array) }))
  expect(fetch).toHaveBeenCalledWith('/api/evaluations/e%2Fa/history')
})
```

- [ ] **Step 2: 运行测试确认失败**

运行：`cd webapp && npx vitest run src/api/client.test.ts`
预期：FAIL，提示 `api.evaluationHistory is not a function`，或类型/断言未满足。

- [ ] **Step 3: 实现最小 API 和类型**

在 `types.ts` 定义 `TurnInfo` 和 `EvaluationHistoryEntry`，在 `client.ts` 添加：

```ts
evaluationHistory: (id: string) =>
  getJSON<{ ok: true; evaluation_id: string; events: EvaluationHistoryEntry[] }>(
    `/api/evaluations/${encodeURIComponent(id)}/history`,
  ),
```

并把 `turns` 返回类型替换为 `TurnInfo[]`，保留 `run_id` query 编码。

- [ ] **Step 4: 运行测试确认通过**

运行：`cd webapp && npx vitest run src/api/client.test.ts src/api/types.test.ts`
预期：PASS。

- [ ] **Step 5: 提交**

```bash
git add webapp/src/api/types.ts webapp/src/api/client.ts webapp/src/api/client.test.ts
git commit -m "feat(web): add runtime and evaluation history API types"
```

---

### Task 2: 添加可测试的 Run 数据 hook 与 navigator

**Files:**
- Create: `webapp/src/api/useRuns.ts`
- Create: `webapp/src/api/useRuns.test.tsx`
- Create: `webapp/src/components/session/RunPanel.tsx`
- Create: `webapp/src/components/session/RunPanel.test.tsx`
- Modify: `webapp/src/styles/style.css`

**Interfaces:**
- `useRuns(sessionId: string | null)` 返回 `{ runs: RunInfo[]; selectedRunId: number | null; selectRun: (id: number | null) => void; loading: boolean; error: string | null; refresh: () => Promise<void> }`。Hook 只读取 `/api/sessions/{sid}/runs`，不根据 rows 推导 Run。
- `RunPanel` props 为 `{ runs, selectedRunId, onSelect, runlessTurnCount, loading, error }`，必须提供“全部 Runs”入口和 runless 说明；Run item 显示 `R{id}`、`open|ended|incomplete` 与 `conflict_count`。

- [ ] **Step 1: 写 hook 的失败测试**

```tsx
it('loads runs and resets selection when session changes', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input) => new Response(JSON.stringify(
    String(input).includes('/s1/runs')
      ? { ok: true, runs: [{ run_id: 1, external_lifecycle_id: null, status: 'ended', started_seq: 1, ended_seq: 3, started_ts: 1, ended_ts: 2, max_turn_number: 1, conflict_count: 0 }] }
      : { ok: true, runs: [] },
  ), { status: 200 })))
  const { result, rerender } = renderHook(({ sid }) => useRuns(sid), { initialProps: { sid: 's1' } })
  await waitFor(() => expect(result.current.runs).toHaveLength(1))
  act(() => result.current.selectRun(1))
  rerender({ sid: 's2' })
  await waitFor(() => expect(result.current.selectedRunId).toBeNull())
})
```

- [ ] **Step 2: 运行 hook 测试确认失败**

运行：`cd webapp && npx vitest run src/api/useRuns.test.tsx`
预期：FAIL，提示模块不存在。

- [ ] **Step 3: 实现 hook**

使用 `useEffect` 的 `alive`/epoch guard，Session 改变时清空旧 `runs`、`error` 和 `selectedRunId`，加载成功后仅保留服务端返回的 Run。`refresh` 必须重复调用 `api.runs`，HTTP 失败写入 `error`。

- [ ] **Step 4: 写 navigator 渲染测试**

```tsx
it('shows lifecycle state, conflicts, and runless notice', () => {
  render(<RunPanel runs={[{ run_id: 2, external_lifecycle_id: null, status: 'incomplete', started_seq: 1, ended_seq: null, started_ts: 1, ended_ts: null, max_turn_number: 3, conflict_count: 2 }]} selectedRunId={2} onSelect={vi.fn()} runlessTurnCount={1} loading={false} error={null} />)
  expect(screen.getByText('R2')).toBeInTheDocument()
  expect(screen.getByText('incomplete')).toBeInTheDocument()
  expect(screen.getByText(/2 conflicts/)).toBeInTheDocument()
  expect(screen.getByText(/Observed/)).toBeInTheDocument()
})
```

- [ ] **Step 5: 实现 navigator 与样式**

用按钮而非裸 div 表示选择，`aria-pressed` 或 `aria-current` 反映 selected Run；Run 为零时显示“暂无明确 lifecycle Run”，而不是创建虚拟 Run。冲突显示为 warning 文案；runless count 只说明 observed order，不显示为 canonical Run。

- [ ] **Step 6: 运行测试确认通过**

运行：`cd webapp && npx vitest run src/api/useRuns.test.tsx src/components/session/RunPanel.test.tsx`
预期：PASS。

- [ ] **Step 7: 提交**

```bash
git add webapp/src/api/useRuns.ts webapp/src/api/useRuns.test.tsx webapp/src/components/session/RunPanel.tsx webapp/src/components/session/RunPanel.test.tsx webapp/src/styles/style.css
git commit -m "feat(web): add session run navigator"
```

---

### Task 3: 接入 Session Run-scoped 阅读与统计

**Files:**
- Modify: `webapp/src/components/session/SessionView.tsx:22-220`
- Modify: `webapp/src/components/session/SessionTable.tsx:17-220`
- Modify: `webapp/src/components/session/TopBar.tsx:8-106`
- Modify: `webapp/src/lib/tableModel.ts`
- Modify: `webapp/src/lib/tableModel.test.ts`
- Create: `webapp/src/components/session/SessionView.test.tsx`
- Modify: `webapp/src/styles/style.css`

**Interfaces:**
- `SessionView` 使用 Task 2 的 `useRuns` 与 `RunPanel`，将 `selectedRunId: number | null` 传给表格；Session 切换时清空选中 Run。
- `SessionTable` 增加 `runId?: number | null`；过滤规则为：`null` 显示所有 canonical 与 observed rows，正整数只显示 `row.run_id === runId` 的 rows，同时保留 summary 的 identity key 与 `rowTurnLabel`。
- `TopBar` 增加 `runs: RunInfo[]` 与 `selectedRunId` props，显示 `Runs N · Turns M`，当 `conflict_count > 0` 显示冲突数；`Turns` 仍为服务端 `data.turns`，不要将 Run count 与 Turn count 混加。

- [ ] **Step 1: 写跨 Run identity 的纯函数测试**

```ts
it('filters canonical rows by run without colliding on turn number', () => {
  const rows = [
    row({ id: 'r1t1', run_id: 1, turn_number: 1, observed_turn_ordinal: null }),
    row({ id: 'r2t1', run_id: 2, turn_number: 1, observed_turn_ordinal: null }),
    row({ id: 'obs1', run_id: null, turn_number: null, observed_turn_ordinal: 1 }),
  ]
  expect(filterRowsByRun(rows, 1).map((item) => item.id)).toEqual(['r1t1'])
  expect(filterRowsByRun(rows, null).map((item) => item.id)).toEqual(['r1t1', 'r2t1', 'obs1'])
})
```

- [ ] **Step 2: 运行测试确认失败**

运行：`cd webapp && npx vitest run src/lib/tableModel.test.ts`
预期：FAIL，提示 `filterRowsByRun` 未定义。

- [ ] **Step 3: 实现纯过滤函数**

```ts
export function filterRowsByRun(rows: ProjectedRow[], runId: number | null): ProjectedRow[] {
  if (runId == null) return rows
  return rows.filter((row) => row.run_id === runId)
}
```

在 `SessionTable` 的 `displayRecords` 之前应用该过滤，并将过滤状态变化时的 collapsed sets 清理为当前 identity 仍存在的集合，避免旧 Run 的折叠状态泄露。

- [ ] **Step 4: 写 Session 集成失败测试**

mock `/api/sessions/s1`、`/api/sessions/s1/runs` 返回无真实正文的 canonical rows 与两个 Run；渲染 `<SessionView sessionId="s1" />`，点击 `R2` 后断言 `R2 · T1` 出现、`R1 · T1` 不出现，TopBar 显示 `Runs 2`，并断言 Runless rows 在“全部 Runs”下显示 `Observed 1`。

- [ ] **Step 5: 接入 `RunPanel`、Run filter 与 jump**

`SessionView` 将 `selectedRunId` 传到 `SessionTable`；`jumpToTurn` 在传入 canonical identity 时使用 `sameTurnIdentity`，不以裸 `turn` fallback 匹配 canonical rows。Run navigator 的选择只影响当前 Session，不影响 App 侧栏或 Evaluation membership。

- [ ] **Step 6: 更新 TopBar 和运行测试**

运行：`cd webapp && npx vitest run src/lib/tableModel.test.ts src/components/session/SessionView.test.tsx src/components/session/RunPanel.test.tsx`
预期：PASS；随后运行 `cd webapp && npm run build`，预期 TypeScript 与 Vite build 成功。

- [ ] **Step 7: 提交**

```bash
git add webapp/src/components/session/SessionView.tsx webapp/src/components/session/SessionTable.tsx webapp/src/components/session/TopBar.tsx webapp/src/lib/tableModel.ts webapp/src/lib/tableModel.test.ts webapp/src/components/session/SessionView.test.tsx webapp/src/styles/style.css
git commit -m "feat(web): add run-scoped session reading"
```

---

### Task 4: 增强 Evaluation 数据层与错误/成员选择语义

**Files:**
- Modify: `webapp/src/api/useEvaluations.ts:1-90`
- Create: `webapp/src/api/useEvaluations.test.tsx`
- Modify: `webapp/src/components/evaluation/EvaluationForm.tsx:1-53`
- Modify: `webapp/src/components/evaluation/EvaluationSessionList.tsx:1-29`
- Modify: `webapp/src/components/evaluation/EvaluationView.tsx:13-63`

**Interfaces:**
- `useEvaluations` 返回 `history: EvaluationHistoryEntry[]` 与 `availableSessions: SessionMeta[]`；`availableSessions` 过滤当前 Evaluation 成员及所有 active Evaluation 成员，但最终约束仍以 API 为准。
- 写操作失败必须 reject 给 `EvaluationView.action`，由 toast/inline alert 显示后端原始错误（例如 `session already in another evaluation`），不能在 hook 内吞掉。
- 每次 `select`/`reload` 只允许当前请求写入 state；Evaluation 切换时旧 detail/history 响应必须丢弃。

- [ ] **Step 1: 写 history 与失败传播测试**

```tsx
it('loads history with the selected detail and preserves API errors', async () => {
  vi.spyOn(api, 'evaluations').mockResolvedValue({ evaluations: [{ evaluation_id: 'e1', title: 'smoke', deleted: false, member_count: 0 }] })
  vi.spyOn(api, 'evaluation').mockResolvedValue({ evaluation_id: 'e1', title: 'smoke', deleted: false, members: [] })
  vi.spyOn(api, 'evaluationHistory').mockResolvedValue({ ok: true, evaluation_id: 'e1', events: [] })
  const { result } = renderHook(() => useEvaluations())
  await waitFor(() => expect(result.current.history).toEqual([]))
  vi.spyOn(api, 'addEvaluationSession').mockRejectedValue(new Error('session already in another evaluation'))
  await expect(result.current.addSession('e1', 's2', 'task')).rejects.toThrow('session already in another evaluation')
})
```

- [ ] **Step 2: 运行测试确认失败**

运行：`cd webapp && npx vitest run src/api/useEvaluations.test.tsx`
预期：FAIL，提示缺少 `history` 或 `evaluationHistory` 调用。

- [ ] **Step 3: 实现带竞态保护的加载**

增加 `history` state；`loadDetail(id)` 用递增 request epoch，同时请求 `api.evaluation(id)` 与 `api.evaluationHistory(id)`，只有 epoch 仍匹配才写入 `current`/`history`。`reload`、`select`、create/rename/remove/add/remove 后按现有语义刷新相关资源；写操作不要 catch，交给页面 action。

- [ ] **Step 4: 实现成员可选列表和错误保留**

`EvaluationView` 计算当前 active members 与所有其他 active members 的 `session_id` 集合，将可添加 sessions 传入 `EvaluationForm`；如果用户在竞态下仍选到冲突 Session，显示 `session already in another evaluation`。添加失败时表单保持打开，不清空 label，便于用户修正后重试。

- [ ] **Step 5: 运行测试确认通过**

运行：`cd webapp && npx vitest run src/api/useEvaluations.test.tsx src/components/evaluation`
预期：PASS。

- [ ] **Step 6: 提交**

```bash
git add webapp/src/api/useEvaluations.ts webapp/src/api/useEvaluations.test.tsx webapp/src/components/evaluation/EvaluationForm.tsx webapp/src/components/evaluation/EvaluationSessionList.tsx webapp/src/components/evaluation/EvaluationView.tsx
git commit -m "feat(web): improve evaluation membership workflow"
```

---

### Task 5: 增加 Evaluation Overview、History、筛选与评分聚合

**Files:**
- Modify: `webapp/src/components/evaluation/EvaluationView.tsx`
- Modify: `webapp/src/components/evaluation/EvaluationSessionList.tsx`
- Modify: `webapp/src/styles/style.css`
- Create: `webapp/src/components/evaluation/EvaluationView.test.tsx`

**Interfaces:**
- 纯前端聚合只作用于已由后端 detail enrich 的 member metadata：`member_count`、`error_count`、`score.value`、`task_label`、`agent`；不得把缺失值当作 0 或复制 score 事实。
- 页面状态 `evaluationTab: 'overview' | 'sessions' | 'history'`、`taskFilter: string`、`agentFilter: string`、`failedOnly: boolean`；过滤只影响 Sessions tab，不改变后端 membership。
- History tab 按 `seq` 升序显示时间、fact type、Session/title payload 的安全摘要；不能展示真实会话正文或在 UI 中重新折叠 facts。

- [ ] **Step 1: 写 overview/history/filter 渲染测试**

```tsx
it('shows score distribution, task filters, and audit history', async () => {
  // fixture 仅使用 synthetic ids/titles/labels，不放真实正文
  render(<EvaluationView sessions={sessions} onOpenSession={vi.fn()} />)
  expect(await screen.findByText('Overview')).toBeInTheDocument()
  expect(screen.getByText(/good 1/)).toBeInTheDocument()
  // 使用 @testing-library/react 内置的 fireEvent，避免引入 package.json 未声明的 user-event 依赖。
  fireEvent.click(screen.getByRole('button', { name: 'History' }))
  expect(screen.getByText('evaluation.session.added')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Sessions' }))
  fireEvent.click(screen.getByRole('button', { name: /task-a/ }))
  expect(screen.getByText('task-a')).toBeInTheDocument()
})
```

- [ ] **Step 2: 运行测试确认失败**

运行：`cd webapp && npx vitest run src/components/evaluation/EvaluationView.test.tsx`
预期：FAIL，提示缺少 Overview/History tab 或 score summary。

- [ ] **Step 3: 实现 Overview 聚合和 tabs**

在组件内以 `useMemo` 计算：总成员数、good/bad/partial/未标注数量、failed members、task label 集合、agent 集合。显示 `—` 或“未标注”区分缺失 score，不能把 null 计为 good/bad。Tabs 使用按钮和 `aria-pressed`，默认 Overview；空 Evaluation 显示明确 empty state。

- [ ] **Step 4: 实现 Sessions 筛选**

task label 和 agent 使用 select/button filter，failedOnly 依据 `error_count > 0`。筛选后传给 `EvaluationSessionList`；空结果显示“没有符合筛选条件的会话”，而不是误报 Evaluation 为空。

- [ ] **Step 5: 实现 History tab**

按 `seq` 展示每条 history entry 的 `evaluation.created/renamed/deleted/session.added/session.removed` 与安全字段（title/task_label/session_id），使用 `String` 和长度限制，不渲染 payload 中可能出现的会话正文。删除 Evaluation 后仍可在已加载的 history 中审计，不允许因 `deleted` 把 history 清空。

- [ ] **Step 6: 运行测试与构建**

运行：`cd webapp && npx vitest run src/components/evaluation/EvaluationView.test.tsx src/api/useEvaluations.test.tsx && npm run build`
预期：测试全部 PASS，build 成功；大 chunk warning 若仍存在记录为非阻断 warning，不为本任务扩大范围。

- [ ] **Step 7: 提交**

```bash
git add webapp/src/components/evaluation/EvaluationView.tsx webapp/src/components/evaluation/EvaluationSessionList.tsx webapp/src/styles/style.css webapp/src/components/evaluation/EvaluationView.test.tsx
git commit -m "feat(web): add evaluation overview and history workspace"
```

---

### Task 6: 清理迁移遗留并补齐全链路验收

**Files:**
- Modify: `webapp/src/components/App.tsx:14-105`
- Modify: `webapp/src/api/client.ts:46-63`
- Modify: `webapp/src/lib/turnIdentity.ts`（仅在测试发现裸 key/label 缺口时）
- Modify: `webapp/src/lib/turnIdentity.test.ts`
- Modify: `webapp/src/api/types.test.ts`
- Create: `webapp/src/components/evaluation/EvaluationForm.test.tsx`（如 Task 4 未覆盖）
- Create: `webapp/src/components/session/runtime-fixtures.ts`
- Create: `webapp/src/components/session/runtime-fixtures.test.ts`

**Interfaces:**
- `App` 侧栏只展示 API 实际提供的 SessionMeta 字段；不再读取 `(s as SessionMeta & { scores?: unknown[] }).scores`。
- rename 保持现有 POST `/title` client seam；如果统一到 PATCH，必须先在后端确认兼容性并同步测试，默认不扩大后端变更范围。
- fixture 输出 canonical `R1 · T1`、canonical `R2 · T1`、observed `Observed 1` 三种 identity，供组件和纯函数测试复用。

- [ ] **Step 1: 写迁移清理回归测试**

```tsx
it('does not render a score marker from an absent SessionMeta field', () => {
  render(<App />)
  expect(document.querySelector('#sessList .adot')).toBeNull()
})
```

- [ ] **Step 2: 运行测试确认失败**

运行：`cd webapp && npx vitest run src/components/App.test.tsx`
预期：若当前无 App 测试则先看到测试文件不存在；新增测试应在清理前以旧 cast 路径为基线并明确覆盖不存在字段。

- [ ] **Step 3: 清理无效 cast 并审计裸 turn 用法**

删除 `App.tsx` 的 `scores` cast 和 dot 分支。执行 `grep -R "key=.*turn\|turn ===\|turn:` webapp/src --include='*.ts' --include='*.tsx'`，逐处确认 React key、比较和 jump 逻辑使用 `turnIdentityKey`/`sameTurnIdentity`；保留后端兼容字段 `turn` 仅作为 observed fallback 的展示输入。

- [ ] **Step 4: 增加 synthetic runtime fixture 与 identity 测试**

fixture 必须只含 `s1`、`agent-test`、`task-a` 等合成值；断言跨 Run 的同号 Turn key 不同、runless 不生成 `run_id=0` 或 inferred Run，并覆盖 Usage/Timing 组件使用 identity key 的行为。

- [ ] **Step 5: 运行前端门禁**

运行：`cd webapp && npx vitest run && npm run build && npm run lint`
预期：全部测试 PASS、build 成功；若 lint 暴露本任务新增的 unused import，修复后重跑，不通过则不能提交。

- [ ] **Step 6: 运行仓库门禁与服务验收**

运行：`make test`
预期：ATA Python 与前端相关测试全部 PASS。

运行：`./scripts/install-service.sh restart`
预期：服务重启成功；不要执行开发账本 reset。

运行：`curl -s http://127.0.0.1:17877/api/health`
预期：输出 `{"ok": true}`。

启动前端验证：`cd webapp && npm run dev -- --host 127.0.0.1`，用浏览器打开 `http://127.0.0.1:5173/`，选择一个 Session，点击 Run navigator 的不同 Run，确认 `R1 · T1`/`R2 · T1` 不碰撞；切换 Evaluation 的 Overview/Sessions/History，确认 API 错误可见且无 console error。

- [ ] **Step 7: 提交**

```bash
git add webapp/src/components/App.tsx webapp/src/lib/turnIdentity.ts webapp/src/lib/turnIdentity.test.ts webapp/src/api/types.test.ts webapp/src/components/evaluation/EvaluationForm.test.tsx webapp/src/components/session/runtime-fixtures.ts webapp/src/components/session/runtime-fixtures.test.ts
git commit -m "chore(web): finish runtime evaluation migration cleanup"
```

---

## Spec 覆盖与自检

- [ ] **Run 生命周期**：Task 1 固化 status/conflict 类型；Task 2 展示 `open|ended|incomplete` 与 conflict；Task 3 不推断 Run，支持 Session-scoped filter。
- [ ] **Turn identity**：Task 1 固化 identity 类型；Task 3 以 `run_id` 过滤；Task 6 覆盖跨 Run 同号 Turn 与 observed fallback。
- [ ] **Evaluation membership**：Task 4 过滤可选 Session、保留后端冲突错误并刷新；Task 5 仅展示/筛选，不修改事实。
- [ ] **Evaluation score**：Task 5 从 member Session 最新 score 聚合，不写 Evaluation score 副本。
- [ ] **Evaluation history**：Task 1 增加 API；Task 4 加载；Task 5 展示 seq/type/history，删除后仍可审计。
- [ ] **读取边界**：所有 Run/Turn 请求通过 `/api/sessions/{sid}/...`，没有全局 Run 视图；React 不重算 lifecycle。
- [ ] **视觉与可用性**：Task 2/3/5 仅修改 `webapp/src/styles/`，复用现有 tokens、按钮和 responsive overflow 规则。
- [ ] **测试覆盖**：hook 竞态、API errors、Run status/conflict、cross-Run identity、Evaluation filters/history、build/lint/service health 均有明确验证命令。
- [ ] **类型一致性**：Task 1 的 `TurnInfo` 与 `EvaluationHistoryEntry` 是后续组件唯一输入；Task 2 的 `useRuns`/`RunPanel` props 在 Task 3 按同名接口消费；Task 4 的 `history` 在 Task 5 仅按 `seq/event` 读取。
- [ ] **占位符扫描**：计划中不使用 TBD/TODO/“实现适当错误处理”等未定义步骤；每个任务都提供文件、接口、失败测试、实现方式、验证命令和提交命令。
