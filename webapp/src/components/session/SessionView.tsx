// 会话页：顶栏（crumb / 刷新）+ overview 区（统计 / Usage 徽章 + Timeline 占位）
// + Ledger 表格。数据走 useSession（rev 门控轮询 + loadOlder 前插）。
// Timeline 拖拽聚焦与右侧 inspector 属后续阶段迁移，本版先留占位。
import { useCallback, useRef, useState } from 'react'
import { CONTENT_ROW_HEIGHT } from '../../lib/tableModel'
import { useSession } from '../../api/useSession'
import { SessionTable } from './SessionTable'
import { StatsBadges } from './StatsPanel'
import { UsageBadges, UsagePanel } from './UsagePanel'

interface Props {
  sessionId: string
}

export function SessionView({ sessionId }: Props) {
  const { data, error, refresh, loadOlder } = useSession(sessionId)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [usageOpen, setUsageOpen] = useState(false)
  const scrollerRef = useRef<HTMLDivElement | null>(null)
  // loadOlder 前插后补偿滚动差，视觉位置不跳
  const scrollBeforeLoad = useRef<{ height: number; top: number } | null>(null)

  const handleLoadOlder = useCallback(async () => {
    const el = scrollerRef.current
    if (el) scrollBeforeLoad.current = { height: el.scrollHeight, top: el.scrollTop }
    if (await loadOlder()) {
      requestAnimationFrame(() => {
        const after = scrollerRef.current
        const before = scrollBeforeLoad.current
        if (after && before) after.scrollTop = before.top + (after.scrollHeight - before.height)
      })
    }
  }, [loadOlder])

  // usage 曲线红点 / 统计面板入口跳转轨迹现场：定位到行，滚到可见并选中。
  // 行高定值（30/20）+ hasOlder 头部预留一格，index 可直接换算偏移；
  // 折叠态下有偏差，可接受——目标是行进入视窗。
  const jumpToRow = useCallback((match: (r: { id: string; _seq: number }) => boolean) => {
    const rows = data?.rows
    if (!rows || !scrollerRef.current) return
    const row = rows.find(match)
    if (!row) return
    setSelectedId(row.id)
    const el = scrollerRef.current
    const olderH = data.hasOlder ? CONTENT_ROW_HEIGHT : 0
    el.scrollTop = Math.max(0, olderH + CONTENT_ROW_HEIGHT * row.index - el.clientHeight / 2)
  }, [data])

  const jumpToSeq = useCallback((seq: number) => jumpToRow((r) => r._seq === seq), [jumpToRow])
  const jumpToId = useCallback((id: string) => jumpToRow((r) => r.id === id), [jumpToRow])

  if (error) return <div className="board-empty">加载失败：{error}</div>
  if (!data) return <div className="home-empty">加载中…</div>

  return (
    <>
      <header className="top">
        {/* crumb 是服务端拼好的 HTML 片段（标题已转义），与旧版 innerHTML 同语义 */}
        <div className="crumb" dangerouslySetInnerHTML={{ __html: data.crumb || data.title }} />
        <button type="button" className="ghost" title="重新拉取当前会话的最新数据" onClick={refresh}>
          刷新
        </button>
      </header>
      <section className="overview">
        <div className="zone-bar">
          <span className="zone-name">Timeline</span>
          <div className="grow" />
          <StatsBadges rows={data.rows} onJump={jumpToId} />
          <UsageBadges
            sessionId={sessionId}
            open={usageOpen}
            onToggle={() => setUsageOpen(!usageOpen)}
          />
        </div>
        <UsagePanel
          sessionId={sessionId}
          onJump={jumpToSeq}
          open={usageOpen}
          onClose={() => setUsageOpen(false)}
        />
        <div className="plot">
          {/* Timeline 拖拽/缩放视图属下一阶段迁移；占位保持布局高度 */}
          <div className="track" aria-label="Timeline overview" style={{ minHeight: 56 }} />
        </div>
      </section>
      <section className="ledger">
        <div className="ledger-main">
          <div className="zone-bar">
            <span className="zone-name">Ledger</span>
            <code className="sid">{sessionId}</code>
            <button
              type="button"
              className="ghost"
              title="复制 session id"
              onClick={() => { void navigator.clipboard.writeText(sessionId) }}
            >
              复制 id
            </button>
            <div className="grow" />
            <span className="hint">{data.rows.length} 行 · T{Math.max(data.turns, 0)} 轮</span>
          </div>
          <SessionTable
            data={data}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onLoadOlder={handleLoadOlder}
            loadingOlder={false}
            scrollerRef={scrollerRef}
          />
        </div>
      </section>
    </>
  )
}

