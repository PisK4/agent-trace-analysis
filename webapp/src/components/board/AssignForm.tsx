// 归组弹层的两个表单：CreateRunForm 只填组名建组；AssignForm 在指定 run/task 下挂会话。
import { useState } from 'react'
import type { SessionOption } from './AnnoForm'

interface CreateRunProps {
  onCreateRun: (name: string) => Promise<string | null>
  onCancel: () => void
}

export function CreateRunForm({ onCreateRun, onCancel }: CreateRunProps) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  const create = async () => {
    const trimmed = name.trim()
    if (!trimmed || busy) return
    setBusy(true)
    const created = await onCreateRun(trimmed)
    setBusy(false)
    if (created) onCancel()
  }

  return (
    <div className="pop" role="form" aria-label="新建组" onClick={(e) => e.stopPropagation()}>
      <div className="pop-title">新建组</div>
      <input
        className="board-input"
        type="text"
        placeholder="组名（中英文皆可）"
        maxLength={60}
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') void create() }}
      />
      <div className="pop-row">
        <button type="button" className="ghost primary-btn" disabled={!name.trim() || busy} onClick={() => void create()}>创建</button>
        <button type="button" className="ghost" onClick={onCancel}>取消</button>
      </div>
    </div>
  )
}

interface AssignProps {
  sessions: SessionOption[]
  runId: string
  taskId: string
  onSave: (sessionId: string, runId: string, taskId: string) => Promise<void>
  onCancel: () => void
}

// 挂会话：run/task 由入口（任务行的「+ 挂会话」）锁定，这里只选会话。
export function AssignForm({ sessions, runId, taskId, onSave, onCancel }: AssignProps) {
  const [sessionId, setSessionId] = useState(sessions[0]?.id ?? '')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!sessionId || busy) return
    setBusy(true)
    try {
      await onSave(sessionId, runId, taskId)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="pop" role="form" aria-label={`挂会话到 ${taskId}`} onClick={(e) => e.stopPropagation()}>
      <div className="pop-title">挂会话 · {taskId}</div>
      <select className="board-input" aria-label="选择会话" value={sessionId} onChange={(e) => setSessionId(e.target.value)}>
        {sessions.map((s) => (
          <option key={s.id} value={s.id}>{(s.title || s.id).slice(0, 40)}（{s.agent} · {s.eventCount} evts）</option>
        ))}
      </select>
      <div className="pop-row">
        <button type="button" className="ghost primary-btn" disabled={!sessionId || busy} onClick={() => void submit()}>归入</button>
        <button type="button" className="ghost" onClick={onCancel}>取消</button>
      </div>
    </div>
  )
}
