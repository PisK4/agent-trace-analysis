// 应用壳：侧栏（agent 页签 + 会话列表）+ 视图切换（会话流 | 标注板）。
// 会话流主体在后续阶段逐块迁入；本壳先承载标注板并管理会话选中态。
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { SessionMeta } from '../api/types'
import { shortTime } from '../lib/format'
import { BoardView } from './board/BoardView'
import { ToastProvider } from './ToastProvider'

const AGENT_LABELS: Record<string, string> = {
  pi: 'Pi', cue: 'Cue', droid: 'Droid', claude: 'Claude Code', codex: 'Codex',
}
const AGENT_CLASS: Record<string, string> = {
  pi: 'agent-pi', cue: 'agent-cue', droid: 'agent-droid', claude: 'agent-claude', codex: 'agent-codex',
}

type View = 'sessions' | 'board'

export function App() {
  const [sessions, setSessions] = useState<SessionMeta[]>([])
  const [agentFilter, setAgentFilter] = useState<string | null>(null)
  const [view, setView] = useState<View>('board')
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api.listSessions()
      .then((list) => { if (alive) setSessions(list) })
      .catch((err) => { if (alive) setLoadError(String(err)) })
    return () => { alive = false }
  }, [])

  const agents = useMemo(
    () => [...new Set(sessions.map((s) => s.agent))],
    [sessions],
  )
  const visible = useMemo(
    () => (agentFilter ? sessions.filter((s) => s.agent === agentFilter) : sessions),
    [sessions, agentFilter],
  )

  const sessionOptions = useMemo(() => sessions.map((s) => ({
    id: s.id,
    title: s.title,
    agent: AGENT_LABELS[s.agent] ?? s.agent,
    eventCount: s.event_count,
  })), [sessions])

  return (
    <ToastProvider>
      <div className="shell" data-view={view}>
        <aside className="nav">
          <button type="button" className="brand" onClick={() => setView('sessions')}>
            <i className="mark" /><b>Atatrace</b><em>ledger</em>
          </button>
          <div className="view-switch" role="group" aria-label="切换视图">
            <button type="button" aria-pressed={view === 'sessions'} onClick={() => setView('sessions')}>会话</button>
            <button type="button" aria-pressed={view === 'board'} onClick={() => setView('board')}>标注板</button>
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
                onClick={() => setCurrentId(s.id)}
              >
                <span className="t">{s.title}</span>
                <span className="meta">
                  <span className="ag">{AGENT_LABELS[s.agent] ?? s.agent}</span>
                  <span>{s.event_count} evts</span>
                  {s.error_count > 0 && (
                    <span className="errs" title={`${s.error_count} failed tool calls`}>⚠ {s.error_count}</span>
                  )}
                  {(s as SessionMeta & { scores?: unknown[] }).scores?.length ? <span className="adot" /> : null}
                  <span className="ts">{shortTime(s.first_ts)}</span>
                </span>
              </button>
            ))}
          </div>
        </aside>
        <main className="stage">
          <BoardView sessions={sessionOptions} onOpenSession={(sid) => setCurrentId(sid)} />
        </main>
      </div>
    </ToastProvider>
  )
}
