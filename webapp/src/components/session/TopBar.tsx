// 会话页顶栏：crumb / 重命名 / 刷新 / 跟随尾部 / 标注徽章+弹层 / 归组徽章+弹层 /
// 全局搜索 / 主题切换。功能与摆放对齐旧版 web/index.html header.top。
import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import type { SessionData } from '../../api/merge'
import type { AnnotationsPage } from '../../api/types'
import { useToast } from '../toast'

const SCORES = ['good', 'bad', 'partial'] as const
// 「＋ 新建组…」在下拉里的哨兵值
const NEW_RUN = '__new__'

interface Props {
  sessionId: string
  data: SessionData
  follow: boolean
  onFollowChange: (v: boolean) => void
  search: string
  onSearchChange: (v: string) => void
  onRenamed: (title: string, crumb: string) => void
  onRefresh: () => void
}

export function TopBar({ sessionId, data, follow, onFollowChange, search, onSearchChange, onRenamed, onRefresh }: Props) {
  const toast = useToast()
  const [scoreOpen, setScoreOpen] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)
  const [note, setNote] = useState('')
  const [runs, setRuns] = useState<Array<{ run_id: string; description: string }>>([])
  // 下拉选中的组（NEW_RUN 哨兵 = 就地建组）
  const [runId, setRunId] = useState('')
  // 全量归组（latest-wins 后）：派生本会话已有归组
  const [allAssigns, setAllAssigns] = useState<Array<{ session_id: string; run_id: string | null; task_id: string | null; seq: number }>>([])
  // 选「新建组」时的就地建组输入；正在归入中的 run_id（按钮 busy 态）
  const [newRunName, setNewRunName] = useState('')
  const [busyRun, setBusyRun] = useState<string | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  const latestScore = data.scores[data.scores.length - 1]

  const assigns = allAssigns
    .filter((a) => a.session_id === sessionId && a.run_id)
    .map((a) => ({ run_id: a.run_id as string, task_id: a.task_id }))

  // 归组数据：打开弹层时懒加载 runs + 归组列表
  useEffect(() => {
    if (!assignOpen) return
    let alive = true
    api.runs().then((rs) => { if (alive) setRuns(rs) }).catch(() => { /* 服务不可达时保持空下拉 */ })
    api.annotations().then((page: AnnotationsPage) => {
      if (alive) setAllAssigns(page.assignments)
    }).catch(() => { /* 同上，空列表即可 */ })
    return () => { alive = false }
  }, [assignOpen])

  // 点外面收起两个弹层
  useEffect(() => {
    if (!scoreOpen && !assignOpen) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setScoreOpen(false)
        setAssignOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [scoreOpen, assignOpen])

  // 主题切换走 html.dark 类，CSS 变量整套联动（旧版同机制）
  const toggleTheme = () => {
    document.documentElement.classList.toggle('dark')
  }

  const rename = async () => {
    const next = window.prompt('重命名会话', data.title || '')
    if (next == null) return
    const title = next.trim()
    if (!title || title === data.title) return
    try {
      await api.renameSession(sessionId, title)
      toast('已重命名')
      onRenamed(title, `${data.crumb.split(' · ')[0]} · <b>${title}</b>`)
    } catch (err) {
      toast(`重命名失败：${String(err)}`, 'err')
    }
  }

  const submitScore = async (value: string) => {
    try {
      await api.appendForSession(sessionId, 'session.scored',
        note ? { value, note } : { value })
      setNote('')
      setScoreOpen(false)
      toast(`已标注：${value}`)
      onRefresh()
    } catch (err) {
      toast(`标注写入失败：${String(err)}`, 'err')
    }
  }

  // 该组最近一次使用的任务 id（归入时自动沿用，保持任务维度聚合）
  const lastTaskOf = (rid: string) =>
    allAssigns.filter((a) => a.run_id === rid && a.task_id).sort((a, b) => b.seq - a.seq)[0]?.task_id ?? ''

  // 点「归入」才提交；任务 id 沿用该组最近一次用的，没有则留空
  const assignToRun = async (rid: string) => {
    if (busyRun) return
    const lastTask = lastTaskOf(rid)
    setBusyRun(rid)
    try {
      await api.appendForSession(sessionId, 'session.assigned',
        lastTask ? { run_id: rid, task_id: lastTask } : { run_id: rid, task_id: '' })
      setAllAssigns((prev) => [...prev, { session_id: sessionId, run_id: rid, task_id: lastTask || null, seq: Number.MAX_SAFE_INTEGER }])
      setRunId('')
      setAssignOpen(false)
      toast(`已归入：${runs.find((r) => r.run_id === rid)?.description || rid}${lastTask ? ` · ${lastTask}` : ''}`)
      onRefresh()
    } catch (err) {
      toast(`归组失败：${String(err)}`, 'err')
    } finally {
      setBusyRun(null)
    }
  }

  const createRunHere = async () => {
    const name = newRunName.trim()
    if (!name) return
    try {
      const { run_id: rid } = await api.createRun(name)
      setRuns((prev) => [...prev, { run_id: rid, description: name }])
      setNewRunName('')
      toast(`已建组：${name}`)
    } catch (err) {
      toast(`建组失败：${String(err)}`, 'err')
    }
  }

  const unassign = async (rid: string) => {
    try {
      await api.appendForSession(sessionId, 'session.unassigned', { run_id: rid })
      setAllAssigns((prev) => prev.filter((a) => !(a.session_id === sessionId && a.run_id === rid)))
      toast('已移出归组')
      onRefresh()
    } catch (err) {
      toast(`移出失败：${String(err)}`, 'err')
    }
  }

  return (
    <header className="top">
      {/* crumb 是服务端拼好的 HTML 片段（标题已转义） */}
      <div className="crumb" dangerouslySetInnerHTML={{ __html: data.crumb || data.title }} />
      <button type="button" className="ghost" title="重命名会话" onClick={() => void rename()}>✎</button>
      <button type="button" className="ghost" title="重新拉取当前会话的最新数据" onClick={onRefresh}>
        刷新
      </button>
      <button type="button" className="follow-toggle" aria-pressed={follow} onClick={() => onFollowChange(!follow)}>
        <span className="dot" /><span className="txt">{follow ? '跟随尾部' : '已暂停跟随'}</span>
      </button>
      <div className="grow" />
      <span className="popwrap" ref={wrapRef}>
        <button
          type="button"
          className="stat-badge anno-badge"
          aria-expanded={scoreOpen}
          aria-controls="scoreBox"
          title={latestScore ? `${data.scores.length} 条标注${latestScore.note ? ` · 最近：${latestScore.note}` : ''}` : '尚未标注'}
          onClick={() => { setScoreOpen(!scoreOpen); setAssignOpen(false) }}
        >
          <span className="adot" {...(latestScore ? { 'data-v': latestScore.value } : {})} />
          <span>标注</span>
          <b>{latestScore ? latestScore.value + (latestScore.note ? ` · ${latestScore.note}` : '') : '未标注'}</b>
        </button>
        {scoreOpen && (
          <div className="pop" id="scoreBox">
            <div className="pop-title">标注本条会话</div>
            <div className="pop-row">
              {SCORES.map((s) => (
                <button key={s} type="button" className="ghost" onClick={() => void submitScore(s)}>{s}</button>
              ))}
            </div>
            <input
              className="score-note"
              type="text"
              placeholder="备注（可选）"
              maxLength={200}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
        )}
        <button
          type="button"
          className="stat-badge"
          aria-expanded={assignOpen}
          aria-controls="assignBox"
          onClick={() => { setAssignOpen(!assignOpen); setScoreOpen(false) }}
        >
          <span>归组</span><span className="caret">▾</span>
        </button>
        {assignOpen && (
          <div className="pop" id="assignBox">
            <div className="pop-title">归组：点组名即把本会话挂进去</div>

            {/* 已有归组：可见、可移出 */}
            {assigns.length > 0 && (
              <div className="assign-current">
                {assigns.map((a) => {
                  const run = runs.find((r) => r.run_id === a.run_id)
                  return (
                    <span key={a.run_id} className="assign-chip">
                      {run?.description || a.run_id}
                      {a.task_id ? <span className="assign-task"> · {a.task_id}</span> : null}
                      <button type="button" className="assign-x" title="移出该组"
                        onClick={() => void unassign(a.run_id)}>✕</button>
                    </span>
                  )
                })}
              </div>
            )}

            {/* 下拉选组：组名单行显示；任务 id 自动沿用该组最近一次用的，不用填 */}
            <select
              className="board-input"
              aria-label="选择组"
              value={runId}
              onChange={(e) => {
                const v = e.target.value
                setRunId(v)
                if (v === NEW_RUN) setNewRunName('')
              }}
            >
              <option value="">{runs.length ? '选择组…' : '还没有组，选「＋ 新建组…」'}</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.description || r.run_id}{assigns.some((a) => a.run_id === r.run_id) ? '（已归入）' : ''}
                </option>
              ))}
              <option value={NEW_RUN}>＋ 新建组…</option>
            </select>

            {/* 选了「＋ 新建组…」→ 就地建组；选了普通组 → 归入按钮 */}
            {runId === NEW_RUN ? (
              <div className="pop-row">
                <input
                  className="board-input"
                  type="text"
                  placeholder="新组名（中英文皆可）"
                  maxLength={60}
                  autoFocus
                  style={{ flex: 1 }}
                  value={newRunName}
                  onChange={(e) => setNewRunName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') void createRunHere() }}
                />
                <button type="button" className="ghost" disabled={!newRunName.trim()} onClick={() => void createRunHere()}>创建</button>
              </div>
            ) : (
              runId && (
                <div className="pop-row">
                  <button type="button" className="ghost primary-btn" disabled={busyRun === runId}
                    onClick={() => void assignToRun(runId)}>
                    {busyRun === runId ? '归入中…' : '归入'}
                  </button>
                  {lastTaskOf(runId) && (
                    <span className="assign-hint" style={{ alignSelf: 'center' }}>任务 id 自动沿用：{lastTaskOf(runId)}</span>
                  )}
                </div>
              )
            )}
          </div>
        )}
      </span>
      <div className="divider" />
      <span className="searchwrap">
        <input
          className="search"
          type="search"
          placeholder="Search"
          aria-label="Search trajectory"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </span>
      <button type="button" className="theme-btn" title="切换主题" aria-label="切换主题" onClick={toggleTheme}>
        ◐
      </button>
    </header>
  )
}
