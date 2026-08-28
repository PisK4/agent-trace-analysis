import { useState } from 'react'
import type { SessionMeta } from '../../api/types'

interface Props {
  sessions: SessionMeta[]
  onCreate: (title: string) => Promise<void>
  onAdd: (sessionId: string, taskLabel: string) => Promise<void>
  evaluationId: string | null
  onCancel?: () => void
}

export function EvaluationForm({ sessions, onCreate, onAdd, evaluationId, onCancel }: Props) {
  const [title, setTitle] = useState('')
  const [sessionId, setSessionId] = useState(sessions[0]?.id ?? '')
  const [taskLabel, setTaskLabel] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    if (saving) return
    const value = evaluationId ? sessionId : title.trim()
    if (!value) return
    setSaving(true)
    try {
      if (evaluationId) {
        await onAdd(sessionId, taskLabel.trim())
        setTaskLabel('')
      } else {
        await onCreate(title.trim())
        setTitle('')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="evaluation-form" role="form" aria-label={evaluationId ? '添加会话' : '新建 Evaluation'}>
      {evaluationId ? (
        <>
          <select className="board-input" aria-label="选择会话" value={sessionId} onChange={(e) => setSessionId(e.target.value)}>
            {sessions.map((session) => <option key={session.id} value={session.id}>{session.title || session.id}</option>)}
          </select>
          <input className="board-input" value={taskLabel} maxLength={120} placeholder="任务标签（可选）" onChange={(e) => setTaskLabel(e.target.value)} />
        </>
      ) : (
        <input className="board-input" value={title} maxLength={120} autoFocus placeholder="Evaluation 名称" onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void submit() }} />
      )}
      <div className="pop-row">
        <button type="button" className="ghost primary-btn" disabled={saving || (evaluationId ? !sessionId : !title.trim())} onClick={() => void submit()}>{saving ? '保存中…' : evaluationId ? '添加会话' : '创建'}</button>
        {onCancel && <button type="button" className="ghost" onClick={onCancel}>取消</button>}
      </div>
    </div>
  )
}
