import { describe, expect, it } from 'vitest'
import type { ProjectedRow } from '../api/types'
import {
  buildTimeline,
  centeredRange,
  clamp,
  domainState,
  focusSet,
  laneOf,
  orderedRange,
} from './timelineModel'

const row = (over: Partial<ProjectedRow>): ProjectedRow => ({
  id: 'r',
  _seq: 0,
  index: 0,
  turn: null,
  kind: 'user',
  tag: 'USER',
  text: '',
  startedAt: 0,
  durationMs: 0,
  status: 'completed',
  usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
  ...over,
})

describe('laneOf', () => {
  it('tool/subtool 在第 3 泳道，assistant/compacted 第 2，其余第 1', () => {
    expect(laneOf('tool')).toBe(2)
    expect(laneOf('subtool')).toBe(2)
    expect(laneOf('assistant')).toBe(1)
    expect(laneOf('compacted')).toBe(1)
    expect(laneOf('user')).toBe(0)
    expect(laneOf('context')).toBe(0)
    expect(laneOf('system')).toBe(0)
  })
})

describe('buildTimeline', () => {
  it('每行占一格，turn 起始行产出分隔线', () => {
    const rows = [
      row({ id: 'a', turn: 1, start: true, kind: 'user' }),
      row({ id: 'b', kind: 'assistant' }),
      row({ id: 'c', kind: 'tool' }),
      row({ id: 'd', turn: 2, start: true, kind: 'user' }),
    ]
    const m = buildTimeline(rows)
    expect(m.spans.map((s) => s.id)).toEqual(['a', 'b', 'c', 'd'])
    expect(m.spans[0]).toMatchObject({ start: 0, end: 1, lane: 0 })
    expect(m.spans[2]).toMatchObject({ start: 2, end: 3, lane: 2 })
    expect(m.bounds).toEqual([
      { turn: 1, key: 1, label: 'Observed 1', time: 0 },
      { turn: 2, key: 2, label: 'Observed 2', time: 3 },
    ])
    expect(m.start).toBe(0)
    expect(m.end).toBe(4)
  })

  it('summary 行不进时间轴；空会话给至少一格宽的轴', () => {
    const m = buildTimeline([])
    expect(m.spans).toEqual([])
    expect(m.end).toBe(1)
  })
})

describe('domainState', () => {
  const m = buildTimeline([row({}), row({}), row({}), row({})])

  it('无 viewport 即全景', () => {
    expect(domainState(m, null)).toEqual({ domainStart: 0, domainDuration: 4, fullDuration: 4 })
  })
  it('viewport 起点被夹进合法区间', () => {
    const d = domainState(m, { start: -5, end: -1 })
    expect(d.domainStart).toBe(0)
    expect(d.domainDuration).toBe(4) // 视口比全景还宽 → 收敛为全景
  })
})

describe('focusSet', () => {
  it('覆盖 [sel.start, sel.end] 的 span 进焦点集', () => {
    const m = buildTimeline([row({ id: 'a' }), row({ id: 'b' }), row({ id: 'c' })])
    expect(focusSet(m, { start: 0.5, end: 1.5 })).toEqual(new Set(['a', 'b']))
    expect(focusSet(null, { start: 0, end: 1 })).toBeNull()
  })
})

describe('几何工具', () => {
  it('orderedRange 归一化方向', () => {
    expect(orderedRange(3, 1)).toEqual({ start: 1, end: 3 })
  })
  it('centeredRange 夹住边界且不越上界', () => {
    expect(centeredRange(5, 4, 0, 10)).toEqual({ start: 3, end: 7 })
    expect(centeredRange(1, 6, 0, 10)).toEqual({ start: 0, end: 6 })
    expect(centeredRange(9, 6, 0, 10)).toEqual({ start: 4, end: 10 })
  })
  it('clamp', () => {
    expect(clamp(5, 0, 3)).toBe(3)
    expect(clamp(-1, 0, 3)).toBe(0)
  })
})
