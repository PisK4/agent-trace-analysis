// Ledger 表格：虚拟滚动 + 折叠 SUMMARY + 选中/悬停 + Timeline 选区聚焦变暗。
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ProjectedRow } from '../../api/types'
import type { SessionData } from '../../api/merge'
import type { Viewport } from '../../lib/timelineModel'
import {
  collapsibleAssistants,
  collapsibleTurns,
  displayRecords,
  rowContent,
  virtualWindow,
  type TableFilter,
} from '../../lib/tableModel'
import { usageStripInline } from './usage'

interface Props {
  data: SessionData
  selectedId: string | null
  onSelect: (id: string) => void
  onLoadOlder: () => void
  loadingOlder: boolean
  /** Timeline 选区：非 null 时不在区间内的行变暗（旧版 focusSet 同义） */
  focusRange?: Viewport | null
  /** 外层要读滚动位置（loadOlder 补偿 / 跳转定位），共享同一个滚动容器 */
  scrollerRef?: React.RefObject<HTMLDivElement | null>
}

export function SessionTable({ data, selectedId, onSelect, onLoadOlder, loadingOlder, focusRange, scrollerRef: outerRef }: Props) {
  const [filter, setFilter] = useState<TableFilter>('')
  const [search, setSearch] = useState('')
  const [collapsedTurns, setCollapsedTurns] = useState<Set<number>>(new Set())
  const [collapsedAssistants, setCollapsedAssistants] = useState<Set<string>>(new Set())
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(600)
  const innerRef = useRef<HTMLDivElement>(null)
  const scrollerRef = outerRef ?? innerRef
  // 数据落地后是否自动跳尾（跟随模式）
  const [follow, setFollow] = useState(true)
  const lastRowsRef = useRef(data.rows)

  const display = useMemo(
    () => displayRecords(data.rows, { filter, search, collapsedTurns, collapsedAssistants }),
    [data.rows, filter, search, collapsedTurns, collapsedAssistants],
  )
  const win = useMemo(
    () => virtualWindow(display, { hasOlder: data.hasOlder, scrollTop, viewportHeight }),
    [display, data.hasOlder, scrollTop, viewportHeight],
  )

  const turns = useMemo(() => collapsibleTurns(data.rows), [data.rows])
  const assistants = useMemo(() => collapsibleAssistants(data.rows), [data.rows])

  // 焦点集：Timeline 选区覆盖的行（按行序几何：行 i 占 [i, i+1]）。
  // range 为空或无命中时全部正常显示；命中时窗口外行 data-focus="out" 变暗。
  const focusIds = useMemo(() => {
    if (!focusRange) return null
    const ids = new Set<string>()
    for (const r of data.rows) {
      const i = r.index
      if (i <= focusRange.end && i + 1 >= focusRange.start) ids.add(r.id)
    }
    return ids.size ? ids : null
  }, [focusRange, data.rows])

  // 跟随尾部：行数据变化且 follow 开着时贴底。用行数组引用变化判断，
  // unchanged 拍不产生新数组，不会无谓跳滚动。
  useEffect(() => {
    if (lastRowsRef.current === data.rows) return
    lastRowsRef.current = data.rows
    const el = scrollerRef.current
    if (follow && el) el.scrollTop = el.scrollHeight
  }, [data.rows, follow, scrollerRef])

  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setViewportHeight(el.clientHeight))
    ro.observe(el)
    setViewportHeight(el.clientHeight)
    return () => ro.disconnect()
  }, [scrollerRef])

  // 滚动处理不用 useCallback 包：React Compiler 对 ref.current 的推断与
  // 手写 deps 冲突；内联箭头随组件重建，成本可忽略。
  const onScroll = () => {
    const el = scrollerRef.current
    if (!el) return
    setScrollTop(el.scrollTop)
    // 用户上滚离开底部 → 关跟随；贴底 → 开
    const atBottom = el.scrollTop >= el.scrollHeight - el.clientHeight - 24
    setFollow(atBottom)
  }

  const toggleTurn = (turn: number) =>
    setCollapsedTurns((prev) => {
      const next = new Set(prev)
      if (next.has(turn)) next.delete(turn)
      else next.add(turn)
      return next
    })
  const toggleAssistant = (id: string) =>
    setCollapsedAssistants((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const allTurnsFolded = turns.length > 0 && turns.every((t) => collapsedTurns.has(t))
  const allCallsFolded = assistants.length > 0 && assistants.every((id) => collapsedAssistants.has(id))

  const toggleAllTurns = () =>
    setCollapsedTurns(allTurnsFolded ? new Set() : new Set(turns))
  const toggleAllCalls = () =>
    setCollapsedAssistants(allCallsFolded ? new Set() : new Set(assistants))

  return (
    <>
      <div className="zone-bar">
        <button
          type="button"
          className="ghost"
          aria-pressed={allTurnsFolded}
          title={allTurnsFolded ? 'Expand turns' : 'Collapse turns'}
          onClick={toggleAllTurns}
        >
          {allTurnsFolded ? '⤵' : '⤴'} turns
        </button>
        <button
          type="button"
          className="ghost"
          aria-pressed={allCallsFolded}
          title={allCallsFolded ? 'Expand calls' : 'Collapse calls'}
          onClick={toggleAllCalls}
        >
          {allCallsFolded ? '⤵' : '⤴'} calls
        </button>
        <button
          type="button"
          className="ghost chip"
          aria-pressed={filter === 'failed'}
          onClick={() => setFilter(filter === 'failed' ? '' : 'failed')}
        >
          failed
        </button>
        <button
          type="button"
          className="ghost chip"
          aria-pressed={filter === 'tools'}
          onClick={() => setFilter(filter === 'tools' ? '' : 'tools')}
        >
          tools
        </button>
        <input
          className="board-input"
          type="text"
          placeholder="搜索正文 / 工具名"
          style={{ width: 160 }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="table-wrap" ref={scrollerRef} onScroll={onScroll}>
        <table>
          <tbody>
            {win.hasOlderButton && (
              <tr className="older" data-kind="older">
                <td className="idx" />
                <td colSpan={2}>
                  <button type="button" className="ghost" disabled={loadingOlder} onClick={onLoadOlder}>
                    {loadingOlder ? 'Loading…' : 'Load earlier history'}
                  </button>
                </td>
              </tr>
            )}
            {win.topSpacer > 0 && <tr className="spacer"><td colSpan={3} style={{ height: win.topSpacer }} /></tr>}
            {win.rows.map((r) =>
              r.virtual === 'summary' ? (
                <tr
                  key={r.id}
                  className="summary"
                  onClick={() => {
                    if (r.expandTurn != null) toggleTurn(r.expandTurn)
                    if (r.expandAssistant) toggleAssistant(r.expandAssistant)
                  }}
                >
                  <td className="idx" />
                  <td className="evt" />
                  <td>{r.text}</td>
                </tr>
              ) : (
                <TableRow
                  key={r.id}
                  row={r}
                  rows={data.rows}
                  selected={selectedId === r.id}
                  dimmed={focusIds != null && !focusIds.has(r.id)}
                  onSelect={onSelect}
                  onDblClick={() => {
                    if (r.kind === 'assistant' && assistants.includes(r.id)) toggleAssistant(r.id)
                    else if (r.start && turns.includes(r.turn ?? NaN)) toggleTurn(r.turn!)
                  }}
                />
              ),
            )}
            {win.bottomSpacer > 0 && <tr className="spacer"><td colSpan={3} style={{ height: win.bottomSpacer }} /></tr>}
          </tbody>
        </table>
      </div>
    </>
  )
}

function TableRow({ row, rows, selected, dimmed, onSelect, onDblClick }: {
  row: ProjectedRow
  rows: ProjectedRow[]
  selected: boolean
  dimmed: boolean
  onSelect: (id: string) => void
  onDblClick: () => void
}) {
  const hasUsage = row.usage && (row.usage.status === 'reported' || row.usage.status === 'estimated')
  return (
    <tr
      data-id={row.id}
      data-selected={selected}
      data-focus={dimmed ? 'out' : undefined}
      data-error={row.status === 'failed' || row.status === 'cancelled'}
      data-pending={row.status === 'pending'}
      data-turn-start={row.start ? 'true' : undefined}
      className={`${row.kind === 'subtool' ? 'subtool' : ''}${row.start ? ` turnc-${row.kind}` : ''}`}
      onClick={() => onSelect(row.id)}
      onDoubleClick={onDblClick}
    >
      <td className="idx">
        {String(row.index + 1).padStart(2, '0')}
        {row.start && row.turn && row.kind !== 'context' ? (
          <span className="turn-chip">{row.turn < 0 ? 'T…' : `T${row.turn}`}</span>
        ) : null}
      </td>
      <td className="evt">
        <span className={`kind ${row.kind}`}>{row.tag}</span>
      </td>
      <td className={`content ${row.kind === 'tool' || row.kind === 'subtool' ? 'mono' : ''}`}>
        {rowContent(row, rows)}
        {row.kind === 'assistant' && hasUsage ? usageStripInline(row.usage) : null}
      </td>
    </tr>
  )
}
