import { useState } from 'react'
import type { SessionMeta } from '../../api/types'

interface Props {
  // 添加会话时传入的 sessions 已被 useEvaluations.availableSessions 过滤：
  // 排除当前 Evaluation 成员 + 其他 active Evaluation 成员。客户端只做
  // 早期 UI 过滤，最终约束以 API 为准——后端 400 时表单不回填、不清空。
  sessions: SessionMeta[]
  onCreate: (title: string) => Promise<unknown>
  onAdd: (sessionId: string, taskLabel: string) => Promise<unknown>
  evaluationId: string | null
  onCancel?: () => void
}

export function EvaluationForm({ sessions, onCreate, onAdd, evaluationId, onCancel }: Props) {
  const [title, setTitle] = useState('')
  const [sessionId, setSessionId] = useState(sessions[0]?.id ?? '')
  const [taskLabel, setTaskLabel] = useState('')
  const [saving, setSaving] = useState(false)
  // 写失败时由调用方 toast/inline alert 展示；表单只在自己 submit 期间置 saving，
  // 不主动吞错误，也不清空字段——用户可立刻看到「哪些已填好」并修正后重试。
  const submit = async () => {
    if (saving) return
    const value = evaluationId ? sessionId : title.trim()
    if (!value) return
    setSaving(true)
    try {
      if (evaluationId) {
        await onAdd(sessionId, taskLabel.trim())
        // 成功才清 task label；sessionId 保留以便用户继续添加多条。
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
            {sessions.length === 0 && <option value="">没有可添加的会话</option>}
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
