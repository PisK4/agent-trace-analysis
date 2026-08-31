// Timeline 总览：sequence 轴上的 span 泳道 + turn 分隔线 + 选区/悬停/平移/缩放。
// 语义平移自旧版 web/js/timeline.js paintOverview + interactions.js 指针交互；
// 状态（range/draft/viewport）提升到 SessionView，range 驱动表格 focus 变暗。
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ProjectedRow } from '../../api/types'
import {
  buildTimeline,
  centeredRange,
  clamp,
  domainState,
  EDGE_PAN_STEP_FRACTION,
  EDGE_PAN_ZONE_FRACTION,
  MAXIMUM_EDGE_PAN_PX,
  MINIMUM_DRAG_PX,
  MINIMUM_ZOOM_OPERATIONS,
  orderedRange,
  TIMELINE_TOOLTIP_DELAY_MS,
  type Viewport,
} from '../../lib/timelineModel'
import { clock, commaMs } from '../../lib/inspectorModel'

const kindLabel = (kind: string) =>
  ({ system: 'SYSTEM', user: 'USER', context: 'CONTEXT', compacted: 'COMPACTED', assistant: 'ASSISTANT', tool: 'TOOL', subtool: 'SUBTOOL' })[kind] ??
  String(kind).toUpperCase()

interface Props {
  rows: ProjectedRow[]
  hasOlder: boolean
  loadingOlder: boolean
  selectedId: string | null
  /** 已落地的选区；null 即无聚焦 */
  range: Viewport | null
  onRangeChange: (r: Viewport | null) => void
  onSelect: (id: string) => void
  onLoadOlder: () => void
}

interface DragState {
  pointerId: number
  x: number
  t: number
  id: string | null
}

interface PanState {
  pointerId: number
  anchorClientX: number
  anchorStart: number
  moved: boolean
  pannable: boolean
}

interface TipState {
  text: string
  left: number
  top: number
}

export function Timeline({ rows, hasOlder, loadingOlder, selectedId, range, onRangeChange, onSelect, onLoadOlder }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState | null>(null)
  const panRef = useRef<PanState | null>(null)
  const tipTimerRef = useRef(0)

  const [draft, setDraft] = useState<Viewport | null>(null)
  const [panning, setPanning] = useState(false)
  const [hoverFrac, setHoverFrac] = useState<number | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [tip, setTip] = useState<TipState | null>(null)
  const [viewport, setViewport] = useState<Viewport | null>(null)

  const m = useMemo(() => buildTimeline(rows), [rows])
  // viewport 放 ref 供事件回调读最新值，state 只驱动渲染。
  // 写 ref.current 属「渲染期镜像」惯用法（React Compiler 警告可忽略）：
  // 事件回调需要读到与本次渲染一致的值，走 state 会拿到过期闭包。
  const viewportRef = useRef(viewport)
  if (viewportRef.current !== viewport) viewportRef.current = viewport

  // 卸载时清 tooltip 定时器
  useEffect(() => () => window.clearTimeout(tipTimerRef.current), [])

  const sel = draft || range

  // 空数据早退放在全部 hooks 之后，保证 hooks 顺序稳定
  if (!m.spans.length) return <div className="track" style={{ minHeight: 50 }} aria-label="Timeline overview" />

  const ds = domainState(m, viewport)
  const fullDuration = ds.fullDuration
  const domainLeft = `${-((ds.domainStart - m.start) / ds.domainDuration) * 100}%`
  const domainWidth = `${(fullDuration / ds.domainDuration) * 100}%`

  const fractionAt = (event: React.PointerEvent | React.WheelEvent) => {
    const rect = trackRef.current!.getBoundingClientRect()
    return clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1)
  }

  const spanIdAt = (target: EventTarget | null): string | null => {
    const node = (target as Element | null)?.closest?.('[data-id]')
    return node ? (node as HTMLElement).dataset.id ?? null : null
  }

  const hideTip = () => {
    window.clearTimeout(tipTimerRef.current)
    setTip(null)
  }

  const scheduleTip = (id: string, event: React.PointerEvent) => {
    window.clearTimeout(tipTimerRef.current)
    tipTimerRef.current = window.setTimeout(() => {
      const row = rows.find((r) => r.id === id)
      if (!row) return
      const lines = [kindLabel(row.kind)]
      if (Number.isFinite(row.startedAt) && row.durationMs) {
        lines.push(`${clock(row.startedAt)} → ${clock(row.startedAt + row.durationMs)}`)
      } else if (Number.isFinite(row.startedAt)) {
        lines.push(`Started ${clock(row.startedAt)}`)
      }
      const bits: string[] = []
      if (row.durationMs) bits.push(`Total ${commaMs(row.durationMs)}`)
      if (bits.length) lines.push(bits.join(' · '))
      const box = trackRef.current?.getBoundingClientRect()
      setTip({
        text: lines.join('\n'),
        left: Math.min(window.innerWidth - 220, Math.max(12, (box?.left ?? 0) + (box?.width ?? 0) / 2 - 80)),
        top: (box?.bottom ?? 0) + 8,
      })
      void event
    }, TIMELINE_TOOLTIP_DELAY_MS)
  }

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    const mNow = m
    if (!mNow.spans.length) return
    const { domainStart, domainDuration } = domainState(mNow, viewportRef.current)
    event.currentTarget.setPointerCapture(event.pointerId)
    if (event.button === 2) {
      panRef.current = {
        pointerId: event.pointerId,
        anchorClientX: event.clientX,
        anchorStart: domainStart,
        moved: false,
        pannable: viewportRef.current != null,
      }
      setPanning(true)
      return
    }
    if (event.button !== 0) return
    const t = domainStart + fractionAt(event) * domainDuration
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, t, id: spanIdAt(event.target) }
    setDraft({ start: t, end: t })
  }

  const applyViewport = (nextStart: number, duration: number, mNow: typeof m) => {
    const v = { start: nextStart, end: nextStart + duration }
    setViewport(duration >= mNow.end - mNow.start ? null : v)
  }

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!m.spans.length) return
    const frac = fractionAt(event)
    const id = spanIdAt(event.target)

    const pan = panRef.current
    if (pan && pan.pointerId === event.pointerId) {
      if (Math.abs(event.clientX - pan.anchorClientX) >= MINIMUM_DRAG_PX) pan.moved = true
      if (!pan.pannable) return
      const { domainDuration } = domainState(m, viewportRef.current)
      const delta = (event.clientX - pan.anchorClientX) / Math.max(1, trackRef.current!.getBoundingClientRect().width)
      const nextStart = clamp(pan.anchorStart - delta * domainDuration, m.start, m.end - domainDuration)
      applyViewport(nextStart, domainDuration, m)
      return
    }

    const drag = dragRef.current
    if (!drag) {
      setHoverFrac(frac)
      setHoveredId(id)
      hideTip()
      if (id == null) return
      scheduleTip(id, event)
      return
    }
    hideTip()
    let { domainStart, domainDuration } = domainState(m, viewportRef.current)
    if (viewportRef.current) {
      const rect = trackRef.current!.getBoundingClientRect()
      const localX = event.clientX - rect.left
      const edgeWidth = Math.min(MAXIMUM_EDGE_PAN_PX, Math.max(1, rect.width * EDGE_PAN_ZONE_FRACTION))
      const direction = localX < edgeWidth ? -1 : localX > rect.width - edgeWidth ? 1 : 0
      if (direction !== 0) {
        const edgeDistance = direction < 0 ? edgeWidth - localX : localX - (rect.width - edgeWidth)
        const strength = clamp(edgeDistance / edgeWidth, 0, 1)
        const nextStart = clamp(
          domainStart + direction * domainDuration * EDGE_PAN_STEP_FRACTION * Math.max(0.2, strength),
          m.start,
          m.end - domainDuration,
        )
        applyViewport(nextStart, domainDuration, m)
        domainStart = nextStart
      }
    }
    const next = domainStart + frac * domainDuration
    setDraft(orderedRange(drag.t, next))
  }

  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    const pan = panRef.current
    if (pan && pan.pointerId === event.pointerId) {
      const moved = pan.moved || Math.abs(event.clientX - pan.anchorClientX) >= MINIMUM_DRAG_PX
      panRef.current = null
      setPanning(false)
      if (!moved) onRangeChange(null)
      return
    }
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    dragRef.current = null
    hideTip()
    const moved = Math.abs(event.clientX - drag.x) >= MINIMUM_DRAG_PX
    const clickId = spanIdAt(event.target) || drag.id
    const { domainStart, domainDuration } = domainState(m, viewportRef.current)
    if (!moved && clickId) {
      setDraft(null)
      onRangeChange(null)
      onSelect(clickId)
      return
    }
    const picked = draft || orderedRange(drag.t, domainStart + fractionAt(event) * domainDuration)
    const minW = Math.min(domainDuration, (m.end - m.start) / Math.max(m.spans.length, 1))
    const final = picked.end - picked.start < minW
      ? centeredRange(moved ? (picked.start + picked.end) / 2 : picked.start, minW, m.start, m.end)
      : picked
    setDraft(null)
    onRangeChange(final)
    if (!moved) {
      // 单击空白处：吸附最近 span 并选中
      const t = picked.start
      const nearest = m.spans.reduce((best, span) => {
        const dist = t < span.start ? span.start - t : t > span.end ? t - span.end : 0
        const bestDist = t < best.start ? best.start - t : t > best.end ? t - best.end : 0
        return dist < bestDist ? span : best
      })
      onSelect(nearest.id)
    }
  }

  // wheel 缩放以指针为锚：anchorTime 在缩放前后保持在同一屏幕位置
  const onWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!m.spans.length) return
    event.preventDefault()
    const { domainStart, domainDuration } = domainState(m, viewportRef.current)
    const anchorFraction = fractionAt(event)
    const minZoom = Math.min(MINIMUM_ZOOM_OPERATIONS, m.end - m.start)
    const nextDuration = Math.min(m.end - m.start, Math.max(minZoom, domainDuration * Math.exp(event.deltaY * 0.0015)))
    if (nextDuration >= (m.end - m.start) * 0.999) {
      setViewport(null)
      return
    }
    const anchorTime = domainStart + anchorFraction * domainDuration
    const nextStart = clamp(anchorTime - anchorFraction * nextDuration, m.start, m.end - nextDuration)
    applyViewport(nextStart, nextDuration, m)
  }

  const selLeft = sel
    ? ((clamp(Math.min(sel.start, sel.end), m.start, m.end) - ds.domainStart) / ds.domainDuration) * 100
    : 0
  const selWidth = sel
    ? ((clamp(Math.max(sel.start, sel.end), m.start, m.end) - clamp(Math.min(sel.start, sel.end), m.start, m.end)) /
        ds.domainDuration) *
      100
    : 0
  const atStart = !viewport || ds.domainStart === m.start

  return (
    <>
      <div
        className="track"
        data-panning={panning}
        tabIndex={0}
        aria-label="Timeline overview; drag horizontally to focus events"
        onKeyDown={(e) => {
          if (e.key === 'Escape' && range) onRangeChange(null)
        }}
        ref={trackRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => {
          if (!dragRef.current && !panRef.current) {
            setHoverFrac(null)
            hideTip()
          }
        }}
        onDoubleClick={(e) => {
          e.preventDefault()
          onRangeChange(null)
        }}
        onContextMenu={(e) => e.preventDefault()}
        onWheel={onWheel}
      >
        {hasOlder && atStart && (
          <button type="button" className="ellipsis" disabled={loadingOlder} title="Load earlier history" onClick={onLoadOlder}>
            …
          </button>
        )}
        {sel && (
          <>
            <div className="selection" data-draft={draft ? 'true' : 'false'} style={{ '--sel-left': `${selLeft}%`, '--sel-width': `${Math.max(selWidth, 0.15)}%` } as React.CSSProperties} />
            <div className="selection-edges" data-draft={draft ? 'true' : 'false'} style={{ '--sel-left': `${selLeft}%`, '--sel-width': `${Math.max(selWidth, 0.15)}%` } as React.CSSProperties} />
          </>
        )}
        {hoverFrac != null && !hoveredId && (
          <div className="hover-line" style={{ '--hover-left': `${hoverFrac * 100}%` } as React.CSSProperties} />
        )}
        <div className="turn-lines" style={{ '--domain-left': domainLeft, '--domain-width': domainWidth } as React.CSSProperties}>
          {m.bounds.map((b, i) => (
            // key 用位置不用 turn 号：loadOlder 前插后同 turn 理论上可能出现多条 start
            <span key={`${b.key}-${b.time}-${i}`} className="turn-line" data-turn-label={b.label} title={b.label} style={{ '--left': `${((b.time - m.start) / fullDuration) * 100}%` } as React.CSSProperties} />
          ))}
        </div>
        <div className="lanes" style={{ '--domain-left': domainLeft, '--domain-width': domainWidth } as React.CSSProperties}>
          {m.spans.map((span) => {
            const spanLeft = ((span.start - m.start) / fullDuration) * 100
            const spanWidth = ((span.end - span.start) / fullDuration) * 100
            const inRange = !sel || (span.start <= sel.end && span.end >= sel.start)
            return (
              <span
                key={span.id}
                className={`span ${span.kind}`}
                data-id={span.id}
                data-current={selectedId === span.id}
                data-in-range={inRange}
                data-error={span.error === true}
                style={{
                  '--lane': span.lane,
                  '--left': `${spanLeft}%`,
                  '--width': `${spanWidth}%`,
                  '--gap': `min(${Math.max(spanWidth, 0.01) * 0.08}%,1px)`,
                } as React.CSSProperties}
              />
            )
          })}
        </div>
      </div>
      {tip && (
        <div className="tip" data-on="true" style={{ left: tip.left, top: tip.top }}>
          {tip.text}
        </div>
      )}
    </>
  )
}

export type { Viewport as TimelineRange }
