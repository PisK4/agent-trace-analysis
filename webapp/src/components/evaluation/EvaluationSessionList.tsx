import type { EvaluationMember } from '../../api/types'

interface Props {
  members: EvaluationMember[]
  onRemove: (sessionId: string) => Promise<void>
  onOpenSession: (sessionId: string) => void
}

export function EvaluationSessionList({ members, onRemove, onOpenSession }: Props) {
  if (!members.length) return <div className="evaluation-empty">还没有会话。添加一条轨迹开始观察。</div>
  return (
    <div className="evaluation-sessions">
      {members.map((member) => {
        const score = member.score
        return (
          <div className="evaluation-session" key={member.session_id}>
            <div className="evaluation-session-copy">
              <button type="button" className="evaluation-session-title" onClick={() => onOpenSession(member.session_id)}>{member.title || member.session_id}</button>
              <span className="evaluation-session-meta">{member.agent || '未知 agent'} · {member.event_count ?? 0} evts{member.error_count ? ` · ${member.error_count} failed` : ''}</span>
              {member.task_label && <span className="evaluation-task">{member.task_label}</span>}
            </div>
            {score && <span className="vchip" data-v={score.value}>{score.value}</span>}
            <button type="button" className="icon-btn danger" aria-label={`移除 ${member.title || member.session_id}`} onClick={() => void onRemove(member.session_id)}>×</button>
          </div>
        )
      })}
    </div>
  )
}
