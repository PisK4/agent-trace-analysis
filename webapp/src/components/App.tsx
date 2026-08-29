// 应用壳：侧栏（agent 页签 + 会话列表）+ 视图切换（会话流 | 标注板）。
// 会话流主体在后续阶段逐块迁入；本壳先承载标注板并管理会话选中态。
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { SessionMeta } from '../api/types'
import { shortTime } from '../lib/format'
import { AGENT_CLASS, AGENT_LABELS } from '../lib/agents'
import { EvaluationView } from './evaluation/EvaluationView'
import { SessionView } from './session/SessionView'
import { ToastProvider } from './ToastProvider'

type View = 'sessions' | 'evaluations'

// 侧栏轮询的变更门控：last_seq 随每次 append 单调递增，覆盖新事件/改名/标注
function sameList(a: SessionMeta[], b: SessionMeta[]): boolean {
  return a.length === b.length && a.every((s, i) =>
    s.id === b[i].id && s.last_seq === b[i].last_seq && s.title === b[i].title
    && s.event_count === b[i].event_count && s.error_count === b[i].error_count)
}

export function App() {
  const [sessions, setSessions] = useState<SessionMeta[]>([])
  const [agentFilter, setAgentFilter] = useState<string | null>(null)
  const [view, setView] = useState<View>('sessions')
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api.listSessions()
      .then((list) => { if (alive) setSessions(list) })
      .catch((err) => { if (alive) setLoadError(String(err)) })
    return () => { alive = false }
  }, [])

  // 侧栏轮询：新 agent 会话出现时无需刷新页面（旧版 pollSessions 5s 同频；
  // 失败静默——首轮失败已由 loadError 提示，后续恢复即自动补上）。
  // 门控：last_seq/title/计数全等才保留旧数组身份，账本没变不触发整树重渲染
  // （架构评审二轮候选 5：盲轮询是三套刷新纪律里唯一没门控的）。
  useEffect(() => {
    const t = setInterval(() => {
      api.listSessions().then((list) => {
        setSessions((prev) => (sameList(prev, list) ? prev : list))
      }).catch(() => {})
    }, 5000)
    return () => clearInterval(t)
  }, [])

  const agents = useMemo(
    () => [...new Set(sessions.map((s) => s.agent))],
    [sessions],
  )
  const visible = useMemo(
    () => (agentFilter ? sessions.filter((s) => s.agent === agentFilter) : sessions),
    [sessions, agentFilter],
  )

  return (
    <ToastProvider>
      <div className="shell" data-view={view} data-inspect="open">
        <aside className="nav">
          <button type="button" className="brand" onClick={() => setView('sessions')}>
            <i className="mark" /><b>Atatrace</b><em>ledger</em>
          </button>
          <div className="view-switch" role="group" aria-label="切换视图">
            <button type="button" aria-pressed={view === 'sessions'} onClick={() => setView('sessions')}>会话</button>
            <button type="button" aria-pressed={view === 'evaluations'} onClick={() => setView('evaluations')}>Evaluations</button>
          </div>
          <div className="nav-label">Sessions</div>
          <div className="sess-tabs" role="group" aria-label="Filter by agent">
            <button type="button" className="tab" aria-pressed={agentFilter == null} onClick={() => setAgentFilter(null)}>全部</button>
            {agents.map((a) => (
              <button
                key={a}
                type="button"
                className={`tab ${AGENT_CLASS[a] ?? ''}`}
                aria-pressed={agentFilter === a}
                onClick={() => setAgentFilter(a)}
              >
                <i className="dot" />{AGENT_LABELS[a] ?? a}
              </button>
            ))}
          </div>
          <div id="sessList">
            {loadError && <div className="board-empty">加载失败：{loadError}</div>}
            {!loadError && visible.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`item ${AGENT_CLASS[s.agent] ?? ''}`}
                aria-current={s.id === currentId}
                onClick={() => { setCurrentId(s.id); setView('sessions') }}
              >
                <span className="t">{s.title}</span>
                <span className="meta">
                  <span className="ag">{AGENT_LABELS[s.agent] ?? s.agent}</span>
                  <span>{s.event_count} evts</span>
                  {s.error_count > 0 && (
                    <span className="errs" title={`${s.error_count} failed tool calls`}>⚠ {s.error_count}</span>
                  )}
                  <span className="ts">{shortTime(s.first_ts)}</span>
                </span>
              </button>
            ))}
          </div>
        </aside>
        <main className="stage">
          {view === 'evaluations' ? (
            <EvaluationView sessions={sessions} onOpenSession={(sid) => { setCurrentId(sid); setView('sessions') }} />
          ) : currentId ? (
            <SessionView sessionId={currentId} />
          ) : (
            <div className="home-empty">选择一条会话</div>
          )}
        </main>
      </div>
    </ToastProvider>
  )
}
