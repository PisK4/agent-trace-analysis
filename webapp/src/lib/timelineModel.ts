// Timeline 总览的数据模型：sequence 模式的 span 几何、视口数学、选区焦点集，全部纯函数。
// 语义平移自旧版 web/js/model.js model()/domainState()/focusSet()。
// 旧版时间轴已固定 Sequence 视图（Actual time / Duration / Usage 模式已移除，
// 见 web/index.html zone-bar 注释），故这里只保留 sequence 分支——index 即时间轴坐标。
import type { ProjectedRow } from '../api/types'
import { rowTurnKey, rowTurnLabel } from './turnIdentity'

/** 泳道分配：tool/subtool=2 · assistant/compacted=1 · 其余(user/context/system)=0 */
export function laneOf(kind: ProjectedRow['kind']): number {
  return kind === 'tool' || kind === 'subtool' ? 2 : kind === 'assistant' || kind === 'compacted' ? 1 : 0
}

export interface TSpan {
  id: string
  kind: ProjectedRow['kind']
  lane: number
  /** sequence 坐标：start=行序号，end=序号+1 */
  start: number
  end: number
  error: boolean
}

export interface TurnBound {
  turn: number
  key: string | number
  label: string
  /** 该轮起始行在 sequence 轴上的位置 */
  time: number
}

export interface TimelineModel {
  start: number
  end: number
  spans: TSpan[]
  bounds: TurnBound[]
}

/**
 * sequence 时间轴几何：每行占一格 [i, i+1]，turn 起始行记一条分隔线。
 * durationMs/startedAt 不参与布局（等宽视图），error 只影响着色。
 */
export function buildTimeline(rows: ProjectedRow[]): TimelineModel {
  // 防御：summary 行是表格折叠产物，ProjectedRow 类型里没有该 kind，
  // 正常数据不会命中此过滤（旧版同款防御）
  const base = rows.filter((row) => !((row as { kind?: string }).kind === 'summary'))
  const spans: TSpan[] = base.map((row, i) => ({
    id: row.id,
    kind: row.kind,
    lane: laneOf(row.kind),
    start: i,
    end: i + 1,
    error: row.status === 'failed',
  }))
  const bounds: TurnBound[] = []
  base.forEach((row, i) => {
    // turn 0 是 falsy：与旧版同口径，turn==null 或 0 都不画分隔线
    const key = rowTurnKey(row)
    const label = rowTurnLabel(row)
    const turn = row.turn_number ?? row.turn
    if (row.start && turn && key != null && label) bounds.push({ turn, key, label, time: i })
  })
  return { start: 0, end: Math.max(1, spans.length), spans, bounds }
}

export interface Viewport {
  start: number
  end: number
}

export interface DomainState {
  domainStart: number
  domainDuration: number
  fullDuration: number
}

/** 视口裁剪：无 viewport 即全景；有则把起点夹进 [m.start, m.end - 视口宽] */
export function domainState(m: TimelineModel, viewport: Viewport | null): DomainState {
  const fullDuration = Math.max(1, m.end - m.start)
  if (!viewport) return { domainStart: m.start, domainDuration: fullDuration, fullDuration }
  const viewportDuration = Math.min(fullDuration, Math.max(1, viewport.end - viewport.start))
  const domainStart = clamp(viewport.start, m.start, m.end - viewportDuration)
  return { domainStart, domainDuration: viewportDuration, fullDuration }
}

/** 选区（draft 优先于已落地的 range）覆盖到的 span id 集 */
export function focusSet(m: TimelineModel | null, sel: Viewport | null): Set<string> | null {
  if (!m || !sel) return null
  return new Set(m.spans.filter((s) => s.start <= sel.end && s.end >= sel.start).map((s) => s.id))
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export const orderedRange = (a: number, b: number): Viewport =>
  a <= b ? { start: a, end: b } : { start: b, end: a }

/** 以 center 为中心取宽 width 的区间，夹在 [minimum, maximum] 内 */
export function centeredRange(center: number, width: number, minimum: number, maximum: number): Viewport {
  const clampedWidth = Math.min(maximum - minimum, Math.max(0, width))
  const start = Math.min(Math.max(center - clampedWidth / 2, minimum), maximum - clampedWidth)
  return { start, end: start + clampedWidth }
}

// ── 交互常量（旧版 util.js 同值）──
export const MINIMUM_DRAG_PX = 3
export const MINIMUM_ZOOM_OPERATIONS = 4
export const EDGE_PAN_ZONE_FRACTION = 0.08
export const EDGE_PAN_STEP_FRACTION = 0.025
export const MAXIMUM_EDGE_PAN_PX = 32
export const TIMELINE_TOOLTIP_DELAY_MS = 500
