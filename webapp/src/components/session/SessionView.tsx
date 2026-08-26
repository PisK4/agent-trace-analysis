// 会话页：顶栏（crumb / 刷新）+ overview 区（统计 / Usage 徽章 / Timeline）
// + Ledger 表格 + 右侧 Inspector。数据走 useSession（rev 门控轮询 + loadOlder 前插）。
import { useCallback, useRef, useState } from 'react'
import type { ProjectedRow } from '../../api/types'
import { CONTENT_ROW_HEIGHT } from '../../lib/tableModel'
import type { Viewport } from '../../lib/timelineModel'
import { useSession } from '../../api/useSession'
import { SessionTable } from './SessionTable'
import { StatsBadges } from './StatsPanel'
import { UsageBadges, UsagePanel } from './UsagePanel'
import { Timeline } from './Timeline'
import { TopBar } from './TopBar'
import { Inspector } from './Inspector'
import { TimeBadge } from './TimeBadge'
import { ConversationView } from './ConversationView'

interface Props {
  sessionId: string
}

export function SessionView({ sessionId }: Props) {
  const { data, error, refresh, loadOlder } = useSession(sessionId)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [usageOpen, setUsageOpen] = useState(false)
  // Ledger 双视图：trace 是既有账本表格，chat 是只看对话的渲染视图
  const [ledgerView, setLedgerView] = useState<'trace' | 'chat'>('trace')
  // Timeline 选区：null 无聚焦；聚焦时表格里不在焦点集的行变暗
  const [range, setRange] = useState<Viewport | null>(null)
  // 跟随尾部与全局搜索提升到本层：TopBar 是开关，SessionTable 是消费方
  const [follow, setFollow] = useState(true)
  const [search, setSearch] = useState('')
  const [titleOverride, setTitleOverride] = useState<{ title: string; crumb: string } | null>(null)
  // 详情栏宽度/折叠态跨会话记忆（旧版 ata.detailsWidth / ata.detailsCollapsed 同键）
  const [detailsWidth, setDetailsWidth] = useState<number | null>(() => {
    try { return Number(localStorage.getItem('ata.detailsWidth')) || null } catch { return null }
  })
  const [detailsCollapsed, setDetailsCollapsed] = useState(() => {
    try { return localStorage.getItem('ata.detailsCollapsed') === 'true' } catch { return false }
  })
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
  const jumpToRow = useCallback((match: (r: ProjectedRow) => boolean) => {
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

  // 时间拆解弹层点某轮 → 跳到该轮起始行（user 行 start=true）
  const jumpToTurn = useCallback(
    (turn: number) => jumpToRow((r) => r.start === true && r.turn === turn),
    [jumpToRow],
  )

  // 对话视图点工具 chip → 切回轨迹视图并选中该行；rAF 等 SessionTable
  // 重新挂载拿到 scroller 再滚动定位
  const inspectFromChat = useCallback(
    (id: string) => {
      setLedgerView('trace')
      setSelectedId(id)
      requestAnimationFrame(() => {
        const el = scrollerRef.current
        const rows = data?.rows
        if (!el || !rows) return
        const row = rows.find((r) => r.id === id)
        if (!row) return
        const olderH = data.hasOlder ? CONTENT_ROW_HEIGHT : 0
        el.scrollTop = Math.max(0, olderH + CONTENT_ROW_HEIGHT * row.index - el.clientHeight / 2)
      })
    },
    [data],
  )

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
    setLedgerView('trace')
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
          <TimeBadge sessionId={sessionId} onJumpTurn={jumpToTurn} />
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
            <div className="seg-toggle" role="group" aria-label="Ledger 视图">
              <button type="button" aria-pressed={ledgerView === 'trace'} onClick={() => setLedgerView('trace')}>轨迹</button>
              <button type="button" aria-pressed={ledgerView === 'chat'} onClick={() => setLedgerView('chat')}>对话</button>
            </div>
            <span className="hint">{data.rows.length} 行 · T{Math.max(data.turns, 0)} 轮</span>
          </div>
          {ledgerView === 'trace' ? (
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
          ) : (
            <ConversationView
              data={viewData}
              onInspect={inspectFromChat}
              onLoadOlder={handleLoadOlder}
              loadingOlder={false}
            />
          )}
        </div>
        {!detailsCollapsed && (
          <Inspector
            rows={data.rows}
            toolsIndex={data.toolsIndex}
            sessionId={sessionId}
            selectedId={selectedId}
            onJump={jumpToId}
            width={detailsWidth}
            onWidthChange={(w) => {
              setDetailsWidth(w)
              try { if (w == null) localStorage.removeItem('ata.detailsWidth'); else localStorage.setItem('ata.detailsWidth', String(w)) } catch { /* 隐私模式等存储不可用 */ }
            }}
          />
        )}
        {/* 右缘细把手：折叠/展开详情栏，折叠后把手留在屏幕右缘（旧版同款） */}
        <button
          type="button"
          className="collapse-handle"
          title={detailsCollapsed ? '展开详情栏' : '收起详情栏'}
          aria-label={detailsCollapsed ? '展开详情栏' : '收起详情栏'}
          onClick={() => {
            setDetailsCollapsed(!detailsCollapsed)
            try { localStorage.setItem('ata.detailsCollapsed', String(!detailsCollapsed)) } catch { /* 同上 */ }
          }}
        />
      </section>
    </>
  )
}
