// 标注板视图：标注列表 + 归组树（run → task → 会话）的浏览与增删改查。
// 数据经 useBoard；写入（标注/归组/墓碑/建组/改名）成功后统一重拉。
import { useCallback, useMemo, useState } from 'react'
import type { AssignmentEntry, RunInfo, ScoreEntry } from '../../api/types'
import { fullTime, shortTime } from '../../lib/format'
import { useToast } from '../toast'
import { AnnoForm, type AnnoValue, type SessionOption } from './AnnoForm'
import { AssignForm } from './AssignForm'
import { useBoard } from './useBoard'

import { api } from '../../api/client'

const AGENT_LABELS: Record<string, string> = {
  pi: 'Pi', cue: 'Cue', droid: 'Droid', claude: 'Claude Code', codex: 'Codex',
}

// 标注/归组共用的列表过滤：badOnly + 搜索（标题/备注/任务/run 任一命中）
function filterEntries<T extends { title: string | null; value?: string }>(
  entries: T[],
  badOnly: boolean,
  search: string,
  scoreOf: (entry: T) => string | undefined,
): T[] {
  const q = search.trim().toLowerCase()
  return entries.filter((e) => {
    if (badOnly && (e.value ?? scoreOf(e)) !== 'bad') return false
    if (!q) return true
    return [e.title, 'value' in e ? e.value : null].filter(Boolean).join(' ').toLowerCase().includes(q)
      || ('task_id' in e && String(e.task_id ?? '').toLowerCase().includes(q))
      || ('run_id' in e && String(e.run_id ?? '').toLowerCase().includes(q))
      || ('session_id' in e && String(e.session_id ?? '').toLowerCase().includes(q))
  })
}

interface Props {
  sessions: SessionOption[]
  onOpenSession: (sessionId: string) => void
}

export function BoardView({ sessions, onOpenSession }: Props) {
  const toast = useToast()
  const { data, error, reload, postEvent } = useBoard(true)
  const [badOnly, setBadOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [annoFormOpen, setAnnoFormOpen] = useState(false)
  const [editingScore, setEditingScore] = useState<ScoreEntry | null>(null)
  const [assignFormOpen, setAssignFormOpen] = useState(false)
  const [openRuns, setOpenRuns] = useState<Set<string>>(new Set())

  const scoresBySid = useMemo(() => new Map((data?.scores ?? []).map((s) => [s.session_id, s.value])), [data])
  const scoreOf = useCallback((sid: string): string | undefined => scoresBySid.get(sid), [scoresBySid])

  const scores = useMemo(
    () => filterEntries(data?.scores ?? [], badOnly, search, () => undefined),
    [data, badOnly, search],
  )
  const assignments = useMemo(
    () => filterEntries(data?.assignments ?? [], badOnly, search, (a) => scoresBySid.get(a.session_id)),
    [data, badOnly, search, scoresBySid],
  )

  if (error) {
    return (
      <div className="board-view">
        <div className="board-empty">标注板加载失败：{error}</div>
      </div>
    )
  }
  if (!data) {
    return <div className="board-view"><div className="board-empty">加载中…</div></div>
  }

  const saveAnno = async (sessionId: string, value: AnnoValue, note: string) => {
    const ok = await postEvent(sessionId, 'session.scored',
      note ? { value, note } : { value },
      `已标注：${value}`, '标注写入失败')
    if (ok) {
      toast(`已标注：${value}`)
      setAnnoFormOpen(false)
      setEditingScore(null)
    } else {
      toast('标注写入失败', 'err')
    }
  }

  const clearAnno = async (sid: string) => {
    const ok = await postEvent(sid, 'session.score.cleared', {}, '已删除标注', '删除失败')
    if (ok) toast('已删除标注')
  }

  const saveAssign = async (sessionId: string, runId: string, taskId: string) => {
    const ok = await postEvent(sessionId, 'session.assigned', { run_id: runId, task_id: taskId },
      `已归组：${taskId} → ${runId}`, '归组写入失败')
    if (ok) {
      toast(`已归组：${taskId} → ${runId}`)
      setAssignFormOpen(false)
    } else {
      toast('归组写入失败', 'err')
    }
  }

  const unassign = async (sid: string, rid: string) => {
    const ok = await postEvent(sid, 'session.unassigned', { run_id: rid }, '已移出归组', '移出失败')
    if (ok) toast('已移出归组')
  }

  const unassignWholeRun = async (rid: string) => {
    const list = (data?.assignments ?? []).filter((a) => a.run_id === rid)
    for (const a of list) {
      await postEvent(a.session_id, 'session.unassigned', { run_id: rid }, null, '移出失败')
    }
    if (list.length) {
      toast(`已移出 ${list.length} 条归组`)
      await reload()
    }
  }

  const createRun = async (name: string): Promise<string | null> => {
    try {
      const { run_id: res } = await api.createRun(name)
      toast(`已建组：${name}`)
      await reload()
      return res
    } catch (err) {
      toast(`建组失败：${err instanceof Error ? err.message : String(err)}`, 'err')
      return null
    }
  }

  const renameRun = async (run: RunInfo) => {
    const next = window.prompt('重命名组（留空则回退显示 run_id）', run.description || '')
    if (next == null) return
    const name = next.trim()
    if (name === (run.description || '')) return
    try {
      await api.renameRun(run.run_id, name)
      toast(name ? '已重命名' : '已清空组名')
      await reload()
    } catch (err) {
      toast(`重命名失败：${err instanceof Error ? err.message : String(err)}`, 'err')
    }
  }

  // 归组树按 run 聚合，run 内再按 task 聚合
  const byRun = new Map<string, AssignmentEntry[]>()
  for (const a of assignments) {
    if (!a.run_id) continue
    if (!byRun.has(a.run_id)) byRun.set(a.run_id, [])
    byRun.get(a.run_id)!.push(a)
  }
  const runMeta = new Map((data?.runs ?? []).map((r) => [r.run_id, r]))

  return (
    <section className="board-view">
      <div className="zone-bar">
        <span className="zone-name">Overview</span>
        <span className="stat-badge">
          <b>{data.scores.length} 条标注</b>
        </span>
        {!!data.assignments.length && (
          <span className="stat-badge">
            <span><b>{new Set(data.assignments.map((a) => a.run_id)).size}</b> runs · <b>{new Set(data.assignments.map((a) => a.session_id)).size}</b> 会话已归组</span>
          </span>
        )}
        <div className="grow" />
        <input
          className="board-input"
          type="text"
          placeholder="搜索标题 / 备注 / 任务"
          style={{ width: 180 }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button type="button" className="ghost chip" aria-pressed={badOnly} onClick={() => setBadOnly(!badOnly)}>
          只看 bad
        </button>
        <span className="popwrap">
          <button type="button" className="ghost primary-btn" disabled={!sessions.length} onClick={() => { setEditingScore(null); setAnnoFormOpen(true) }}>
            新增标注
          </button>
          {annoFormOpen && (
            <AnnoForm
              sessions={sessions}
              editing={editingScore}
              onSave={saveAnno}
              onCancel={() => { setAnnoFormOpen(false); setEditingScore(null) }}
            />
          )}
        </span>
      </div>

      <div className="board-scroll">
        <div className="board-section">
          <div className="board-sec-head"><b>标注</b><span className="cnt">{scores.length} 条 · 按时间倒序</span></div>
          <div id="annoList">
            {scores.length ? scores.map((s) => (
              <div key={s.seq} className="arow" data-sid={s.session_id}>
                <span className="adot" data-v={s.value} />
                <span className="vchip" data-v={s.value}>{s.value}</span>
                <span className="who">
                  <span className="trow">
                    <button type="button" className="t" onClick={() => onOpenSession(s.session_id)}>
                      {s.title || s.session_id}
                    </button>
                    <span className="ts">{fullTime(s.ts)}</span>
                  </span>
                  <span className="sub">
                    {AGENT_LABELS[s.agent ?? ''] ?? s.agent ?? '?'} · {s.event_count} evts{s.error_count ? ` · ${s.error_count} failed` : ''} · {shortTime(s.ts)}
                  </span>
                  <span className="note">{s.note || <i>（无备注）</i>}</span>
                </span>
                <span className="acts">
                  <button type="button" className="icon-btn" title="编辑标注"
                    onClick={(e) => { e.stopPropagation(); setEditingScore(s); setAnnoFormOpen(true) }}>
                    ✎
                  </button>
                  <button type="button" className="icon-btn danger" title="删除标注（追加 cleared 墓碑，历史可追溯）"
                    onClick={(e) => { e.stopPropagation(); void clearAnno(s.session_id) }}>
                    🗑
                  </button>
                </span>
              </div>
            )) : (
              <div className="board-empty">暂无标注{badOnly ? '（bad 过滤中）' : ''} —— 打开一条会话，在顶栏「标注」里打分</div>
            )}
          </div>
        </div>

        <div className="board-section">
          <div className="board-sec-head">
            <b>归组</b>
            <span className="cnt">{new Set(assignments.map((a) => a.run_id)).size} runs · 按任务聚合</span>
            <span className="grow" />
            <span className="popwrap">
              <button type="button" className="ghost" disabled={!sessions.length} onClick={() => setAssignFormOpen(true)}>新建归组</button>
              {assignFormOpen && (
                <AssignForm
                  sessions={sessions}
                  runs={data.runs}
                  onSave={saveAssign}
                  onCreateRun={createRun}
                  onCancel={() => setAssignFormOpen(false)}
                />
              )}
            </span>
          </div>
          <div id="runList">
            {byRun.size ? [...byRun.entries()].map(([rid, list]) => {
              const meta = runMeta.get(rid)
              const folded = !openRuns.has(rid)
              const tasks = groupByTask(list)
              return (
                <div key={rid} className="run">
                  <div className="run-head">
                    <button type="button" className="icon-btn fold" title="展开/折叠归组"
                      onClick={(e) => {
                        e.stopPropagation()
                        setOpenRuns((prev) => {
                          const nextSet = new Set(prev)
                          if (nextSet.has(rid)) nextSet.delete(rid)
                          else nextSet.add(rid)
                          return nextSet
                        })
                      }}>
                      {folded ? '▸' : '▾'}
                    </button>
                    <b>{meta?.description || rid}</b>
                    {meta?.description ? <span className="fp">id: {rid}</span> : null}
                    {meta?.created_ts ? <span className="fp">{fullTime(meta.created_ts)} 建</span> : null}
                    <span className="grow" />
                    <span className="cnt">{tasks.size} 任务 · {list.length} 会话</span>
                    <span className="acts">
                      <button type="button" className="icon-btn" title="重命名组（中英文皆可；run_id 不变）"
                        onClick={(e) => { e.stopPropagation(); void renameRun(meta ?? { run_id: rid, description: '', taskset_fingerprint: null, created_ts: 0 }) }}>
                        ✎
                      </button>
                      <button type="button" className="icon-btn danger" title="移出该 run 全部归组（逐条墓碑）"
                        onClick={(e) => { e.stopPropagation(); void unassignWholeRun(rid) }}>
                        🗑
                      </button>
                    </span>
                  </div>
                  {!folded && (
                    <div className="run-body">
                      {[...tasks.entries()].map(([tid, sess]) => (
                        <div key={tid} className="task">
                          <span className="task-id">{tid}</span>
                          <div className="task-sessions">
                            {sess.map((a) => {
                              const sv = scoreOf(a.session_id)
                              return (
                                <div key={a.session_id} className="tsess">
                                  <span className="arow-l">
                                    <span className="arow-l1">
                                      <button type="button" className="t" onClick={() => onOpenSession(a.session_id)}>
                                        {a.title || a.session_id}
                                      </button>
                                      <span className="adot" {...(sv ? { 'data-v': sv } : {})} />
                                      <span className="meta">{AGENT_LABELS[a.agent ?? ''] ?? a.agent ?? '?'} · {a.event_count} evts · {shortTime(a.ts)}</span>
                                    </span>
                                    {sv ? <span className="arow-l2"><span className="vchip" data-v={sv}>{sv}</span></span> : null}
                                  </span>
                                  <button type="button" className="icon-btn danger" title="移出归组（追加 unassigned 墓碑）"
                                    onClick={() => void unassign(a.session_id, rid)}>
                                    ✕
                                  </button>
                                </div>
                              )
                            })}
                            <button
                              type="button"
                              className="add-sess"
                              onClick={(e) => { e.stopPropagation(); setAssignFormOpen(true) }}
                            >
                              + 挂会话
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            }) : <div className="board-empty">暂无归组 —— 在会话页「归组」或点右上「新建归组」</div>}
          </div>
        </div>
      </div>
    </section>
  )
}

function groupByTask(list: AssignmentEntry[]): Map<string, AssignmentEntry[]> {
  const m = new Map<string, AssignmentEntry[]>()
  for (const a of list) {
    const tid = a.task_id ?? '(未填任务)'
    if (!m.has(tid)) m.set(tid, [])
    m.get(tid)!.push(a)
  }
  return m
}
