import type { EvaluationMember } from '../../api/types'

interface Props {
  // 接收已过滤的成员；空数组=「符合筛选条件的会话为空」,不是 Evaluation 本身为空。
  // 父组件必须自己区分这两种空态。
  members: EvaluationMember[]
  onRemove: (sessionId: string) => Promise<unknown>
  onOpenSession: (sessionId: string) => void
}

export function EvaluationSessionList({ members, onRemove, onOpenSession }: Props) {
  if (!members.length) return <div className="evaluation-empty">没有符合筛选条件的会话。</div>
  return (
    <div className="evaluation-sessions">
      {members.map((member) => {
        const score = member.score
        const failed = (member.error_count ?? 0) > 0
        return (
          <div className="evaluation-session" key={member.session_id}>
            <div className="evaluation-session-copy">
              <button type="button" className="evaluation-session-title" onClick={() => onOpenSession(member.session_id)}>{member.title || member.session_id}</button>
              <span className="evaluation-session-meta">{member.agent || '未知 agent'} · {member.event_count ?? 0} evts{failed ? ` · ${member.error_count} failed` : ''}</span>
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
