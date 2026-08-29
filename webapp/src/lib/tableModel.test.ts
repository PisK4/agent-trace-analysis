import { assert, describe, expect, it } from 'vitest'
import {
  collapsibleAssistants,
  collapsibleTurns,
  displayRecords,
  filterRowsByRun,
  virtualWindow,
  type DisplayRow,
} from './tableModel'
import type { ProjectedRow } from '../api/types'

function row(overrides: Partial<ProjectedRow>): ProjectedRow {
  return {
    id: 'r', _seq: 1, index: 0, turn: 1, kind: 'user', tag: 'USER',
    text: 'hi', startedAt: 1000, durationMs: 0, status: 'completed',
    usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
    ...overrides,
  }
}

const NO_FOLD = { filter: '' as const, search: '', collapsedTurns: new Set<number>(), collapsedAssistants: new Set<string>() }

describe('displayRecords', () => {
  it('passes rows through unfolded', () => {
    const rows = [row({ id: 'a', turn: 1 }), row({ id: 'b', turn: 1, kind: 'assistant', tag: 'ASSISTANT' })]
    const out = displayRecords(rows, NO_FOLD)
    expect(out).toHaveLength(2)
    expect(out.every((r) => r.virtual === 'content')).toBe(true)
  })

  it('collapses a turn into first row + SUMMARY', () => {
    const rows = [
      row({ id: 'a', turn: 1 }),
      row({ id: 'b', turn: 1, kind: 'assistant', tag: 'ASSISTANT', group: 'Step 1' }),
      row({ id: 'c', turn: 1, kind: 'tool', tag: 'TOOL', group: 'Step 1', name: 'read' }),
    ]
    const out = displayRecords(rows, { ...NO_FOLD, collapsedTurns: new Set([1]) })
    expect(out.map((r) => r.id)).toEqual(['a', 'a__turn'])
    const sum = out[1]
    expect(sum.virtual).toBe('summary')
    assert('expandTurn' in sum && sum.expandTurn === 1)
    expect(sum.text).toContain('1 step')
    expect(sum.text).toContain('1 tool call')
  })

  it('collapses assistant tool-chain with tool names', () => {
    const rows = [
      row({ id: 'a', turn: 1, kind: 'assistant', tag: 'ASSISTANT', group: 'Step 1' }),
      row({ id: 't1', turn: 1, kind: 'tool', tag: 'TOOL', name: 'read' }),
      row({ id: 't2', turn: 1, kind: 'tool', tag: 'TOOL', name: 'grep' }),
    ]
    const out = displayRecords(rows, { ...NO_FOLD, collapsedAssistants: new Set(['a']) })
    expect(out.map((r) => r.id)).toEqual(['a', 'a__calls'])
    expect(out[1].text).toBe('2 tool calls · read, grep')
  })

  it('search flattens to matching content rows only', () => {
    const rows = [row({ id: 'a', text: 'hello world' }), row({ id: 'b', text: 'other' })]
    const out = displayRecords(rows, { ...NO_FOLD, search: 'hello' })
    expect(out.map((r) => r.id)).toEqual(['a'])
  })

  it('filter=tools keeps only tool rows', () => {
    const rows = [row({ id: 'a' }), row({ id: 't', kind: 'tool', tag: 'TOOL' })]
    const out = displayRecords(rows, { ...NO_FOLD, filter: 'tools' })
    expect(out.map((r) => r.id)).toEqual(['t'])
  })
})

describe('virtualWindow', () => {
  const many: DisplayRow[] = Array.from({ length: 300 }, (_, i) =>
    ({ ...row({ id: `r${i}`, _seq: i, index: i }), virtual: 'content' }))

  it('renders all rows below threshold', () => {
    const few = many.slice(0, 50)
    const w = virtualWindow(few, { hasOlder: false, scrollTop: 0, viewportHeight: 600 })
    expect(w.rows).toHaveLength(50)
    expect(w.topSpacer).toBe(0)
    expect(w.bottomSpacer).toBe(0)
  })

  it('slices window around scrollTop with overscan and spacers', () => {
    const w = virtualWindow(many, { hasOlder: false, scrollTop: 3000, viewportHeight: 600 })
    // 3000/30 = 行 100 起可见；±12 overscan（first 端再让一位给 end>=top 的边界行）
    expect(w.rows[0].index).toBeGreaterThanOrEqual(87)
    expect(w.rows[w.rows.length - 1].index).toBeLessThanOrEqual(132)
    expect(w.topSpacer).toBeGreaterThan(0)
    expect(w.bottomSpacer).toBeGreaterThan(0)
    const total = w.topSpacer + w.rows.length * 30 + w.bottomSpacer
    expect(total).toBe(300 * 30)
  })

  it('reserves a leading row for the older-history button', () => {
    const w = virtualWindow(many.slice(0, 200), { hasOlder: true, scrollTop: 0, viewportHeight: 600 })
    expect(w.hasOlderButton).toBe(true)
    // 全量渲染时首行前有 30px 按钮位（hasOlder 强制虚拟路径）
    expect(w.topSpacer).toBe(0)
  })
})

describe('collapsibles', () => {
  it('collapsibleTurns only returns turns with >1 row', () => {
    const rows = [
      row({ id: 'a', turn: 1 }), row({ id: 'b', turn: 1 }),
      row({ id: 'c', turn: 2 }), row({ id: 'sys', turn: null, kind: 'system' }),
    ]
    expect(collapsibleTurns(rows)).toEqual([1])
  })

  it('collapsibleAssistants returns assistants followed by tools', () => {
    const rows = [
      row({ id: 'a1', kind: 'assistant', tag: 'ASSISTANT' }),
      row({ id: 't1', kind: 'tool', tag: 'TOOL' }),
      row({ id: 'a2', kind: 'assistant', tag: 'ASSISTANT' }),
    ]
    expect(collapsibleAssistants(rows)).toEqual(['a1'])
  })
})

describe('filterRowsByRun', () => {
  it('filters canonical rows by run without colliding on turn number', () => {
    const rows = [
      row({ id: 'r1t1', run_id: 1, turn_number: 1, observed_turn_ordinal: null, turn: 1 }),
      row({ id: 'r2t1', run_id: 2, turn_number: 1, observed_turn_ordinal: null, turn: 2 }),
      row({ id: 'obs1', run_id: null, turn_number: null, observed_turn_ordinal: 1, turn: 3 }),
    ]
    expect(filterRowsByRun(rows, 1).map((r) => r.id)).toEqual(['r1t1'])
    expect(filterRowsByRun(rows, 2).map((r) => r.id)).toEqual(['r2t1'])
  })

  it('keeps observed rows only in the all-runs view', () => {
    const rows = [
      row({ id: 'r1t1', run_id: 1, turn_number: 1 }),
      row({ id: 'obs1', run_id: null, turn_number: null, observed_turn_ordinal: 1 }),
    ]
    expect(filterRowsByRun(rows, null).map((r) => r.id)).toEqual(['r1t1', 'obs1'])
    expect(filterRowsByRun(rows, 1).map((r) => r.id)).toEqual(['r1t1'])
    // 选了具体 Run 后 observed 行不出现，避免「Observed 1」与 R1 · T1 误撞
    expect(filterRowsByRun(rows, 1).some((r) => r.id === 'obs1')).toBe(false)
  })

  it('returns all rows unchanged when runId is null', () => {
    const rows = [row({ id: 'a' }), row({ id: 'b' })]
    expect(filterRowsByRun(rows, null)).toBe(rows)
  })
})
