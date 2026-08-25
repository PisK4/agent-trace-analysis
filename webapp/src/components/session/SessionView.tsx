// 会话页：顶栏（crumb / 刷新）+ overview 区（统计 / Usage 徽章 / Timeline）
// + Ledger 表格 + 右侧 Inspector。数据走 useSession（rev 门控轮询 + loadOlder 前插）。
import { useCallback, useRef, useState } from 'react'
import { CONTENT_ROW_HEIGHT } from '../../lib/tableModel'
import type { Viewport } from '../../lib/timelineModel'
import { useSession } from '../../api/useSession'
import { SessionTable } from './SessionTable'
import { StatsBadges } from './StatsPanel'
import { UsageBadges, UsagePanel } from './UsagePanel'
import { Timeline } from './Timeline'
import { TopBar } from './TopBar'
import { Inspector } from './Inspector'

interface Props {
  sessionId: string
}

export function SessionView({ sessionId }: Props) {
  const { data, error, refresh, loadOlder } = useSession(sessionId)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [usageOpen, setUsageOpen] = useState(false)
  // Timeline 选区：null 无聚焦；聚焦时表格里不在焦点集的行变暗
  const [range, setRange] = useState<Viewport | null>(null)
  // 跟随尾部与全局搜索提升到本层：TopBar 是开关，SessionTable 是消费方
  const [follow, setFollow] = useState(true)
  const [search, setSearch] = useState('')
  const [titleOverride, setTitleOverride] = useState<{ title: string; crumb: string } | null>(null)
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

  // Timeline 点击 span → 表格滚到该行（旧版 selectRecord 的 scrollIntoView 同义）
  const selectFromTimeline = useCallback(
    (id: string) => {
      setSelectedId(id)
      const rows = data?.rows
      const el = scrollerRef.current
      if (!rows || !el) return
      const row = rows.find((r) => r.id === id)
      if (!row) return
      const olderH = data.hasOlder ? CONTENT_ROW_HEIGHT : 0
      el.scrollTop = Math.max(0, olderH + CONTENT_ROW_HEIGHT * row.index - el.clientHeight / 2)
    },
    [data],
  )

  // 焦点集在 SessionTable 内部由 focusRange 计算（需要行序号几何）

  // 换会话清掉标题覆盖与搜索（旧版 openSession 的状态重置同义）
  const [prevSid, setPrevSid] = useState(sessionId)
  if (prevSid !== sessionId) {
    setPrevSid(sessionId)
    setTitleOverride(null)
    setSearch('')
    setRange(null)
  }

  if (error) return <div className="board-empty">加载失败：{error}</div>
  if (!data) return <div className="home-empty">加载中…</div>

  const viewData = titleOverride ? { ...data, title: titleOverride.title, crumb: titleOverride.crumb } : data

  return (
    <>
      <TopBar
        sessionId={sessionId}
        data={viewData}
        follow={follow}
        onFollowChange={setFollow}
        search={search}
        onSearchChange={setSearch}
        onRenamed={(title, crumb) => setTitleOverride({ title, crumb })}
        onRefresh={refresh}
      />
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
          <div className="labels" aria-hidden="true"><span>Input</span><span>Model</span><span>Tools</span></div>
          <Timeline
            rows={data.rows}
            hasOlder={data.hasOlder}
            loadingOlder={false}
            selectedId={selectedId}
            range={range}
            onRangeChange={setRange}
            onSelect={selectFromTimeline}
            onLoadOlder={handleLoadOlder}
          />
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
            data={viewData}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onLoadOlder={handleLoadOlder}
            loadingOlder={false}
            focusRange={range}
            follow={follow}
            onFollowChange={setFollow}
            search={search}
            scrollerRef={scrollerRef}
          />
        </div>
        <Inspector
          rows={data.rows}
          toolsIndex={data.toolsIndex}
          sessionId={sessionId}
          selectedId={selectedId}
          onJump={jumpToId}
        />
      </section>
    </>
  )
}
