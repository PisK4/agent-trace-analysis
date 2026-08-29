import { useMemo, useState } from 'react'
import type { EvaluationHistoryEntry, EvaluationMember, SessionMeta } from '../../api/types'
import { AGENT_LABELS } from '../../lib/agents'
import { useToast } from '../toast'
import { EvaluationForm } from './EvaluationForm'
import { EvaluationSessionList } from './EvaluationSessionList'
import { useEvaluations } from '../../api/useEvaluations'

interface Props {
  sessions: SessionMeta[]
  onOpenSession: (sessionId: string) => void
}

type Tab = 'overview' | 'sessions' | 'history'

interface OverviewStats {
  total: number
  good: number
  bad: number
  partial: number
  unrated: number
  failed: number
  tasks: string[]
  agents: string[]
}

const TAB_LABELS: Record<Tab, string> = { overview: 'Overview', sessions: 'Sessions', history: 'History' }

// 不区分大小写比对 + 去前后空白；空字符串归入「未设置」，与 Overview「未标注」统计一致。
function normalize(s: string | null | undefined): string {
  return (s ?? '').trim()
}

function buildOverview(members: EvaluationMember[]): OverviewStats {
  let good = 0, bad = 0, partial = 0, unrated = 0, failed = 0
  const taskSet = new Set<string>()
  const agentSet = new Set<string>()
  for (const m of members) {
    const v = m.score?.value
    if (v === 'good') good += 1
    else if (v === 'bad') bad += 1
    else if (v === 'partial') partial += 1
    else unrated += 1
    if ((m.error_count ?? 0) > 0) failed += 1
    const t = normalize(m.task_label)
    if (t) taskSet.add(t)
    const a = normalize(m.agent)
    if (a) agentSet.add(a)
  }
  return {
    total: members.length,
    good, bad, partial, unrated,
    failed,
    tasks: [...taskSet].sort(),
    agents: [...agentSet].sort(),
  }
}

// History 摘要只允许出现 fact 已知的字段；payload 里的会话正文等其他键一律丢弃。
// 长度硬截断避免 UI 撑开；title 不在截断范围内（它本来就被后端 fact 限制）。
function historySummary(entry: EvaluationHistoryEntry): string {
  const { event, seq } = entry
  const ts = event.ts
  const payload = event.payload || {}
  switch (event.type) {
    case 'evaluation.created':
      return `title=${String(payload.title ?? '')}`
    case 'evaluation.renamed':
      return `title=${String(payload.title ?? '')}`
    case 'evaluation.deleted':
      return '已删除'
    case 'evaluation.session.added':
      return `session_id=${String(payload.session_id ?? '')} task_label=${String(payload.task_label ?? '')}`
    case 'evaluation.session.removed':
      return `session_id=${String(payload.session_id ?? '')}`
    default:
      return `seq=${seq} ts=${ts}`
  }
}

function historyTypeLabel(t: string): string {
  switch (t) {
    case 'evaluation.created': return '创建'
    case 'evaluation.renamed': return '重命名'
    case 'evaluation.deleted': return '删除'
    case 'evaluation.session.added': return '添加会话'
    case 'evaluation.session.removed': return '移除会话'
    default: return t
  }
}

function shortTime(ms: number): string {
  if (!ms) return '—'
  const d = new Date(ms)
  const p2 = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
}

export function EvaluationView({ sessions, onOpenSession }: Props) {
  const toast = useToast()
  const {
    evaluations, current, history, selectedId, error, loading,
    availableSessions,
    select, create, rename, remove, addSession, removeSession,
  } = useEvaluations(sessions)
  const [createOpen, setCreateOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [tab, setTab] = useState<Tab>('overview')
  const [taskFilter, setTaskFilter] = useState<string>('all')
  const [agentFilter, setAgentFilter] = useState<string>('all')
  const [failedOnly, setFailedOnly] = useState(false)
  // 添加会话失败的内联展示：toast 2.4s 就消失，表单打开期间需要一直可见。
  const [addError, setAddError] = useState<string | null>(null)

  const overview = useMemo(() => buildOverview(current?.members ?? []), [current])
  const sortedHistory = useMemo(
    () => [...history].sort((a, b) => a.seq - b.seq),
    [history],
  )
  const filteredMembers = useMemo(() => {
    const list = current?.members ?? []
    return list.filter((m) => {
      if (taskFilter !== 'all' && normalize(m.task_label) !== taskFilter) return false
      if (agentFilter !== 'all' && normalize(m.agent) !== agentFilter) return false
      if (failedOnly && (m.error_count ?? 0) <= 0) return false
      return true
    })
  }, [current, taskFilter, agentFilter, failedOnly])

  // 写操作错误统一通道：toast 弹一下 + 表单内联一次；toast 消失后内联仍可读。
  // EvaluationView 不吞错误，由 hook 抛上来；只有「用户没点提交」这种 UI 触发
  // 的会话才走 toast，避免每次 reload 都吵用户。
  const action = async (
    fn: () => Promise<unknown>,
    success: string,
    opts: { onError?: (msg: string) => void } = {},
  ) => {
    try {
      await fn()
      toast(success)
      opts.onError?.('') // 成功后清掉内联错误
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      toast(`操作失败：${msg}`, 'err')
      opts.onError?.(msg)
    }
  }

  if (loading && !evaluations.length) return <section className="evaluation-view"><div className="board-empty">加载中…</div></section>
  if (error && !current) return <section className="evaluation-view"><div className="board-empty">Evaluation 加载失败：{error}</div></section>

  const activeEvaluations = evaluations.filter((item) => !item.deleted)
  const noEvaluations = activeEvaluations.length === 0

  return (
    <section className="evaluation-view">
      <div className="zone-bar evaluation-toolbar">
        <span className="zone-name">Evaluation</span>
        <span className="stat-badge"><b>{activeEvaluations.length}</b> 个集合</span>
        <div className="grow" />
        <button type="button" className="ghost primary-btn" onClick={() => setCreateOpen(!createOpen)}>新建 Evaluation</button>
      </div>
      {createOpen && (
        <div className="evaluation-create">
          <EvaluationForm
            sessions={sessions}
            evaluationId={null}
            onCreate={(title) => action(() => create(title), '已创建 Evaluation', { onError: () => {} })}
            onAdd={async () => {}}
            onCancel={() => setCreateOpen(false)}
          />
        </div>
      )}
      <div className="evaluation-layout">
        <aside className="evaluation-list" aria-label="Evaluation 列表">
          {activeEvaluations.map((item) => (
            <button
              type="button"
              key={item.evaluation_id}
              className="evaluation-list-item"
              aria-current={selectedId === item.evaluation_id}
              onClick={() => { setTab('overview'); void select(item.evaluation_id) }}
            >
              <span>{item.title}</span>
              <small>{item.member_count ?? 0} sessions</small>
            </button>
          ))}
          {noEvaluations && <div className="evaluation-empty">还没有 Evaluation。</div>}
        </aside>
        <div className="evaluation-detail">
          {current ? (
            <>
              <header className="evaluation-heading">
                <div>
                  <span className="zone-name">集合详情</span>
                  <h1>{current.title}</h1>
                  <span className="evaluation-id">{current.evaluation_id}</span>
                </div>
                <div className="acts">
                  <button type="button" className="ghost" onClick={() => { const title = window.prompt('重命名 Evaluation', current.title)?.trim(); if (title && title !== current.title) void action(() => rename(current.evaluation_id, title), '已重命名') }}>重命名</button>
                  <button type="button" className="ghost danger" onClick={() => { if (window.confirm(`删除「${current.title}」？`)) void action(() => remove(current.evaluation_id), '已删除') }}>删除</button>
                </div>
              </header>
              <div className="seg-toggle evaluation-tabs" role="group" aria-label="Evaluation 视图">
                {(Object.keys(TAB_LABELS) as Tab[]).map((key) => (
                  <button
                    type="button"
                    key={key}
                    aria-pressed={tab === key}
                    onClick={() => setTab(key)}
                  >{TAB_LABELS[key]}</button>
                ))}
              </div>
              {tab === 'overview' && (
                <div className="evaluation-overview" aria-label="概览">
                  <div className="evaluation-overview-grid">
                    <div className="evaluation-overview-cell"><span>总成员</span><b>{overview.total}</b></div>
                    <div className="evaluation-overview-cell"><span>good</span><b>{overview.good}</b></div>
                    <div className="evaluation-overview-cell"><span>bad</span><b>{overview.bad}</b></div>
                    <div className="evaluation-overview-cell"><span>partial</span><b>{overview.partial}</b></div>
                    <div className="evaluation-overview-cell"><span>未标注</span><b>{overview.unrated}</b></div>
                    <div className="evaluation-overview-cell"><span>failed</span><b>{overview.failed}</b></div>
                  </div>
                  <div className="evaluation-overview-list">
                    <div>
                      <span className="zone-name">任务标签</span>
                      {overview.tasks.length === 0
                        ? <div className="evaluation-empty">还没有任务标签。</div>
                        : <div className="evaluation-chips">{overview.tasks.map((t) => <span key={t} className="vchip evaluation-chip">{t}</span>)}</div>}
                    </div>
                    <div>
                      <span className="zone-name">Agent</span>
                      {overview.agents.length === 0
                        ? <div className="evaluation-empty">还没有 agent。</div>
                        : <div className="evaluation-chips">{overview.agents.map((a) => <span key={a} className="vchip evaluation-chip">{AGENT_LABELS[a] ?? a}</span>)}</div>}
                    </div>
                  </div>
                </div>
              )}
              {tab === 'sessions' && (
                <>
                  <div className="evaluation-members-head">
                    <span>会话</span>
                    <span>{current.members.length} 条成员 / 筛选后 {filteredMembers.length}</span>
                    <button type="button" className="ghost" onClick={() => { setAddOpen(!addOpen); setAddError(null) }}>添加会话</button>
                  </div>
                  <div className="evaluation-filters" role="group" aria-label="筛选">
                    <label className="evaluation-filter">
                      <span>任务</span>
                      <select className="board-input" value={taskFilter} onChange={(e) => setTaskFilter(e.target.value)}>
                        <option value="all">全部</option>
                        {overview.tasks.map((t) => <option key={t} value={t}>{t}</option>)}
                        <option value="">（未设置）</option>
                      </select>
                    </label>
                    <label className="evaluation-filter">
                      <span>Agent</span>
                      <select className="board-input" value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)}>
                        <option value="all">全部</option>
                        {overview.agents.map((a) => <option key={a} value={a}>{AGENT_LABELS[a] ?? a}</option>)}
                        <option value="">（未知）</option>
                      </select>
                    </label>
                    <button
                      type="button"
                      className="ghost"
                      aria-pressed={failedOnly}
                      onClick={() => setFailedOnly(!failedOnly)}
                    >仅 failed</button>
                  </div>
                  {addOpen && (
                    <>
                      <EvaluationForm
                        sessions={availableSessions}
                        evaluationId={current.evaluation_id}
                        onCreate={async () => {}}
                        onAdd={(sid, label) => action(
                          () => addSession(current.evaluation_id, sid, label),
                          '已添加会话',
                          { onError: (msg) => setAddError(msg || null) },
                        )}
                        onCancel={() => { setAddOpen(false); setAddError(null) }}
                      />
                      {addError && <div className="evaluation-inline-error" role="alert">添加失败：{addError}</div>}
                    </>
                  )}
                  <EvaluationSessionList members={filteredMembers} onRemove={(sid) => action(() => removeSession(current.evaluation_id, sid), '已移除会话')} onOpenSession={onOpenSession} />
                </>
              )}
              {tab === 'history' && (
                <div className="evaluation-history" aria-label="历史">
                  {sortedHistory.length === 0
                    ? <div className="evaluation-empty">还没有 history。</div>
                    : (
                      <ol className="evaluation-history-list">
                        {sortedHistory.map((entry) => (
                          <li key={entry.seq} className="evaluation-history-row">
                            <span className="evaluation-history-seq">#{entry.seq}</span>
                            <span className="evaluation-history-type">{historyTypeLabel(entry.event.type)}</span>
                            <span className="evaluation-history-ts">{shortTime(entry.event.ts)}</span>
                            <span className="evaluation-history-summary">{historySummary(entry)}</span>
                          </li>
                        ))}
                      </ol>
                    )}
                </div>
              )}
            </>
          ) : <div className="evaluation-empty">选择一个 Evaluation。</div>}
        </div>
      </div>
    </section>
  )
}
