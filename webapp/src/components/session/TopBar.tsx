// 会话页顶栏：crumb / 重命名 / 刷新 / 跟随尾部 / 标注徽章+弹层 / 归组徽章+弹层 /
// 全局搜索 / 主题切换。功能与摆放对齐旧版 web/index.html header.top。
import { useEffect, useRef, useState } from 'react'
import { api, eventEnvelope } from '../../api/client'
import type { SessionData } from '../../api/merge'
import { useToast } from '../toast'

const SCORES = ['good', 'bad', 'partial'] as const

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
  const [runId, setRunId] = useState('')
  const [taskId, setTaskId] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)

  const latestScore = data.scores[data.scores.length - 1]

  // 归组 run 列表：打开弹层时懒加载一次（旧版 ensureRunsLoaded 同策略）
  useEffect(() => {
    if (!assignOpen || runs.length) return
    let alive = true
    api.runs().then((rs) => { if (alive) setRuns(rs) }).catch(() => { /* 服务不可达时保持空下拉 */ })
    return () => { alive = false }
  }, [assignOpen, runs.length])

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
      await api.appendEvent(eventEnvelope(null, sessionId, 'session.scored',
        note ? { value, note } : { value }))
      setNote('')
      setScoreOpen(false)
      toast(`已标注：${value}`)
      onRefresh()
    } catch (err) {
      toast(`标注写入失败：${String(err)}`, 'err')
    }
  }

  const submitAssign = async () => {
    if (!runId || !taskId) {
      toast('先选 run 并填任务 id（ata tasks list 可查）', 'err')
      return
    }
    try {
      await api.appendEvent(eventEnvelope(null, sessionId, 'session.assigned', { run_id: runId, task_id: taskId }))
      setTaskId('')
      setAssignOpen(false)
      toast('已归入')
      onRefresh()
    } catch (err) {
      toast(`归组失败：${String(err)}`, 'err')
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
            <div className="pop-title">归组到回归轮次</div>
            <select value={runId} onChange={(e) => setRunId(e.target.value)}>
              <option value="">选 run…</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>{r.run_id} · {r.description}</option>
              ))}
            </select>
            <input
              className="score-note"
              type="text"
              placeholder="任务 id（t-xxxx）"
              maxLength={40}
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
            />
            <button type="button" className="ghost" onClick={() => void submitAssign()}>归入</button>
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
