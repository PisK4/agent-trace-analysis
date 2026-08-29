// 会话页顶栏：crumb / 重命名 / 刷新 / 跟随尾部 / 标注徽章+弹层 /
// 全局搜索 / 主题切换。功能与摆放对齐旧版 web/index.html header.top。
import { useState } from 'react'
import { api } from '../../api/client'
import type { SessionData } from '../../api/merge'
import type { RunInfo } from '../../api/types'
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
  /** 当前 Session 的 Run 列表（来自 useRuns） */
  runs: RunInfo[]
  /** 当前选中的 Run id：null = 全部 Runs（含 observed） */
  selectedRunId: number | null
}

export function TopBar({ sessionId, data, follow, onFollowChange, search, onSearchChange, onRenamed, onRefresh, runs, selectedRunId }: Props) {
  const toast = useToast()
  const [scoreOpen, setScoreOpen] = useState(false)
  const [note, setNote] = useState('')
  const latestScore = data.scores[data.scores.length - 1]


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
      <span className="popwrap">
        <button
          type="button"
          className="stat-badge anno-badge"
          aria-expanded={scoreOpen}
          aria-controls="scoreBox"
          title={latestScore ? `${data.scores.length} 条标注${latestScore.note ? ` · 最近：${latestScore.note}` : ''}` : '尚未标注'}
          onClick={() => setScoreOpen(!scoreOpen)}
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
        <span className="stat-badge" title="Run 由真实 agent_start 生命周期产生；Turns 是后端权威计数；冲突由 Run 派生">
          <span>Runs</span><b>{runs.length}</b>
          <span className="meta-sep">·</span>
          <span>Turns</span><b>{data.turns || '暂无'}</b>
          {runs.some((r) => r.conflict_count > 0) ? (
            <span className="meta-sep meta-warn" data-testid="conflict-count">
              · <span className="meta-warn-label">冲突</span>
              <b>{runs.reduce((sum, r) => sum + r.conflict_count, 0)}</b>
            </span>
          ) : null}
          {selectedRunId != null ? (
            <span className="meta-sep">· R{selectedRunId}</span>
          ) : null}
        </span>
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
