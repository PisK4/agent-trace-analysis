import { useState } from 'react'
import type { SessionMeta } from '../../api/types'
import { useToast } from '../toast'
import { EvaluationForm } from './EvaluationForm'
import { EvaluationSessionList } from './EvaluationSessionList'
import { useEvaluations } from '../../api/useEvaluations'

interface Props {
  sessions: SessionMeta[]
  onOpenSession: (sessionId: string) => void
}

export function EvaluationView({ sessions, onOpenSession }: Props) {
  const toast = useToast()
  const {
    evaluations, current, selectedId, error, loading, select, create, rename, remove, addSession, removeSession,
  } = useEvaluations()
  const [createOpen, setCreateOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)

  const action = async (fn: () => Promise<void>, success: string) => {
    try { await fn(); toast(success) } catch (err) { toast(`操作失败：${err instanceof Error ? err.message : String(err)}`, 'err') }
  }

  if (loading && !evaluations.length) return <section className="evaluation-view"><div className="board-empty">加载中…</div></section>
  if (error && !current) return <section className="evaluation-view"><div className="board-empty">Evaluation 加载失败：{error}</div></section>

  return (
    <section className="evaluation-view">
      <div className="zone-bar evaluation-toolbar">
        <span className="zone-name">Evaluation</span>
        <span className="stat-badge"><b>{evaluations.filter((item) => !item.deleted).length}</b> 个集合</span>
        <div className="grow" />
        <button type="button" className="ghost primary-btn" onClick={() => setCreateOpen(!createOpen)}>新建 Evaluation</button>
      </div>
      {createOpen && <div className="evaluation-create"><EvaluationForm sessions={sessions} evaluationId={null} onCreate={(title) => action(async () => { await create(title); setCreateOpen(false) }, '已创建 Evaluation')} onAdd={async () => {}} onCancel={() => setCreateOpen(false)} /></div>}
      <div className="evaluation-layout">
        <aside className="evaluation-list" aria-label="Evaluation 列表">
          {evaluations.filter((item) => !item.deleted).map((item) => (
            <button type="button" key={item.evaluation_id} className="evaluation-list-item" aria-current={selectedId === item.evaluation_id} onClick={() => void select(item.evaluation_id)}>
              <span>{item.title}</span><small>{item.member_count ?? 0} sessions</small>
            </button>
          ))}
          {!evaluations.filter((item) => !item.deleted).length && <div className="evaluation-empty">还没有 Evaluation。</div>}
        </aside>
        <div className="evaluation-detail">
          {current ? (
            <>
              <header className="evaluation-heading">
                <div><span className="zone-name">集合详情</span><h1>{current.title}</h1><span className="evaluation-id">{current.evaluation_id}</span></div>
                <div className="acts">
                  <button type="button" className="ghost" onClick={() => { const title = window.prompt('重命名 Evaluation', current.title)?.trim(); if (title && title !== current.title) void action(() => rename(current.evaluation_id, title), '已重命名') }}>重命名</button>
                  <button type="button" className="ghost danger" onClick={() => { if (window.confirm(`删除「${current.title}」？`)) void action(() => remove(current.evaluation_id), '已删除') }}>删除</button>
                </div>
              </header>
              <div className="evaluation-members-head"><span>会话</span><span>{current.members.length} 条成员</span><button type="button" className="ghost" onClick={() => setAddOpen(!addOpen)}>添加会话</button></div>
              {addOpen && <EvaluationForm sessions={sessions} evaluationId={current.evaluation_id} onCreate={async () => {}} onAdd={(sid, label) => action(async () => { await addSession(current.evaluation_id, sid, label); setAddOpen(false) }, '已添加会话')} onCancel={() => setAddOpen(false)} />}
              <EvaluationSessionList members={current.members} onRemove={(sid) => action(() => removeSession(current.evaluation_id, sid), '已移除会话')} onOpenSession={onOpenSession} />
            </>
          ) : <div className="evaluation-empty">选择一个 Evaluation。</div>}
        </div>
      </div>
    </section>
  )
}
