// 标注表单：新增/编辑共用。编辑态预填既有值并锁会话选择。
import { useState } from 'react'
import type { ScoreEntry } from '../../api/types'

export interface SessionOption {
  id: string
  title: string
  agent: string
  eventCount: number
}

const VALUES = ['good', 'bad', 'partial'] as const
export type AnnoValue = (typeof VALUES)[number]

interface Props {
  sessions: SessionOption[]
  editing: ScoreEntry | null
  onSave: (sessionId: string, value: AnnoValue, note: string) => Promise<void>
  onCancel: () => void
}

export function AnnoForm({ sessions, editing, onSave, onCancel }: Props) {
  const [sessionId, setSessionId] = useState(editing?.session_id ?? sessions[0]?.id ?? '')
  const [value, setValue] = useState<AnnoValue>((editing?.value as AnnoValue) ?? 'good')
  const [note, setNote] = useState(editing?.note ?? '')
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    if (!sessionId || saving) return
    setSaving(true)
    try {
      await onSave(sessionId, value, note.trim())
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="pop" role="form" aria-label={editing ? '编辑标注' : '新增标注'} onClick={(e) => e.stopPropagation()}>
      <div className="pop-title">{editing ? '编辑标注' : '新增标注'}</div>
      <select
        className="board-input"
        aria-label="选择会话"
        value={sessionId}
        disabled={!!editing}
        onChange={(e) => setSessionId(e.target.value)}
      >
        {sessions.map((s) => (
          <option key={s.id} value={s.id}>
            {(s.title || s.id).slice(0, 40)}（{s.agent} · {s.eventCount} evts）
          </option>
        ))}
      </select>
      <div className="pop-row">
        {VALUES.map((v) => (
          <button key={v} type="button" className="ghost" aria-pressed={value === v} onClick={() => setValue(v)}>
            {v[0].toUpperCase() + v.slice(1)}
          </button>
        ))}
      </div>
      <input
        className="board-input"
        type="text"
        placeholder="备注（可选）"
        maxLength={200}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="pop-row">
        <button type="button" className="ghost primary-btn save-btn" disabled={saving} onClick={submit}>
          {saving ? '保存中…' : '保存'}
        </button>
        <button type="button" className="ghost" onClick={onCancel}>取消</button>
      </div>
    </div>
  )
}
