// 归组表单：会话 × run × 任务 id；支持就地新建组（组名 = runs.description）。
import { useState } from 'react'
import type { RunInfo } from '../../api/types'
import type { SessionOption } from './AnnoForm'

interface Props {
  sessions: SessionOption[]
  runs: RunInfo[]
  onSave: (sessionId: string, runId: string, taskId: string) => Promise<void>
  onCreateRun: (name: string) => Promise<string | null>
  onCancel: () => void
}

export function AssignForm({ sessions, runs, onSave, onCreateRun, onCancel }: Props) {
  const [sessionId, setSessionId] = useState(sessions[0]?.id ?? '')
  const [runId, setRunId] = useState(runs[0]?.run_id ?? '')
  const [taskId, setTaskId] = useState('')
  const [newRunName, setNewRunName] = useState('')
  const [busy, setBusy] = useState(false)

  const createRun = async () => {
    const name = newRunName.trim()
    if (!name || busy) return
    setBusy(true)
    const created = await onCreateRun(name)
    setBusy(false)
    if (created) {
      setRunId(created)
      setNewRunName('')
    }
  }

  const submit = async () => {
    if (!sessionId || !runId || !taskId.trim() || busy) return
    setBusy(true)
    try {
      await onSave(sessionId, runId, taskId.trim())
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="pop" role="form" aria-label="新建归组" onClick={(e) => e.stopPropagation()}>
      <div className="pop-title">新建归组</div>
      <select className="board-input" aria-label="选择会话" value={sessionId} onChange={(e) => setSessionId(e.target.value)}>
        {sessions.map((s) => (
          <option key={s.id} value={s.id}>{(s.title || s.id).slice(0, 40)}（{s.agent} · {s.eventCount} evts）</option>
        ))}
      </select>
      <select className="board-input" aria-label="选择组" value={runId} onChange={(e) => setRunId(e.target.value)}>
        {runs.length
          ? runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.description || r.run_id}</option>)
          : <option value="">（无组，先在下方新建）</option>}
      </select>
      <div className="pop-row">
        <input
          className="board-input"
          type="text"
          placeholder="新组名（中英文皆可）"
          maxLength={60}
          style={{ flex: 1 }}
          value={newRunName}
          onChange={(e) => setNewRunName(e.target.value)}
        />
        <button type="button" className="ghost" disabled={!newRunName.trim() || busy} onClick={createRun}>新建</button>
      </div>
      <input
        className="board-input"
        type="text"
        placeholder="任务 id（t-xxxx）"
        maxLength={40}
        value={taskId}
        onChange={(e) => setTaskId(e.target.value)}
      />
      <div className="pop-row">
        <button type="button" className="ghost primary-btn save-btn" disabled={busy} onClick={submit}>归入</button>
        <button type="button" className="ghost" onClick={onCancel}>取消</button>
      </div>
    </div>
  )
}
