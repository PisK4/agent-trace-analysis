import { describe, expect, it } from 'vitest'
import { applySessionPage, emptySessionData, type SessionData } from './merge'
import type { ProjectedRow, SessionPage } from './types'

function row(overrides: Partial<ProjectedRow>): ProjectedRow {
  return {
    id: 'r1', _seq: 1, index: 0, turn: 1, kind: 'user', tag: 'USER',
    text: 'hi', startedAt: 1000, durationMs: 0, status: 'completed',
    usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
    ...overrides,
  }
}

function page(rows: ProjectedRow[], overrides: Partial<SessionPage> = {}): SessionPage {
  return {
    id: 's1', agent: 'pi', title: 't', crumb: 'pi · <b>t</b>', has_older: false,
    cursor: rows[0]?._seq ?? 0, turns: 1, scores: [], tools_index: {}, rev: 1,
    rows,
    ...overrides,
  }
}

describe('applySessionPage', () => {
  it('keeps object identity for unchanged rows', () => {
    const r = row({})
    const current: SessionData = applySessionPage(emptySessionData('s1'), page([r])).next
    const { next, report } = applySessionPage(current, page([r], { rev: 2 }))
    expect(report.rowsChanged).toBe(false)
    expect(next.rows[0]).toBe(r)
  })

  it('replaces same-id row when content changes (streaming append)', () => {
    const before = row({ text: 'partial' })
    const after = row({ text: 'partial + more', _seq: 5 })
    const current: SessionData = applySessionPage(emptySessionData('s1'), page([before])).next
    const { next, report } = applySessionPage(current, page([after]))
    expect(report.rowsChanged).toBe(true)
    expect(next.rows[0].text).toBe('partial + more')
    expect(next.rows[0]).not.toBe(before)
  })

  it('appends new rows and reindexes by _seq', () => {
    const a = row({ id: 'a', _seq: 1 })
    const b = row({ id: 'b', _seq: 2 })
    const current: SessionData = applySessionPage(emptySessionData('s1'), page([b])).next
    const { next } = applySessionPage(current, page([a, b]))
    expect(next.rows.map((r) => r.id)).toEqual(['a', 'b'])
    expect(next.rows.map((r) => r.index)).toEqual([0, 1])
  })

  it('handles dedupe-collapse replay: old id returns with newer seq', () => {
    // 折叠替换：旧行以新 seq 整行重现，不能无脑 append，也不能错位排序
    const v1 = row({ id: 'm1', _seq: 3, text: 'v1' })
    const v2 = row({ id: 'm1', _seq: 7, text: 'v2' })
    const other = row({ id: 'm2', _seq: 5 })
    const current: SessionData = applySessionPage(emptySessionData('s1'), page([v1, other])).next
    const { next } = applySessionPage(current, page([other, v2]))
    expect(next.rows.map((r) => r.id)).toEqual(['m2', 'm1'])
    expect(next.rows[1].text).toBe('v2')
  })

  it('preserves keptOlder rows outside the tail window', () => {
    const kept = row({ id: 'old', _seq: 1, keptOlder: true })
    const tail = row({ id: 'new', _seq: 9 })
    const base = applySessionPage(emptySessionData('s1'), page([kept, tail])).next
    // 新 tail 页只含 new；old 是 keptOlder 应保留且排最前
    const { next } = applySessionPage(base, page([tail]))
    expect(next.rows.map((r) => r.id)).toEqual(['old', 'new'])
  })

  it('drops keptOlder row once it re-enters the tail window', () => {
    const kept = row({ id: 'x', _seq: 1, keptOlder: true })
    const fresh = row({ id: 'x', _seq: 1 }) // 服务端重新下发同一行（无客户端标记）
    const base = applySessionPage(emptySessionData('s1'), page([kept])).next
    const { next } = applySessionPage(base, page([fresh]))
    expect(next.rows.filter((r) => r.id === 'x')).toHaveLength(1)
    expect(next.rows[0].keptOlder).toBeUndefined()
  })

  it('reports metaChanged only when meta actually differs', () => {
    const r = row({})
    const first = applySessionPage(emptySessionData('s1'), page([r]))
    expect(first.report.metaChanged).toBe(true)
    const second = applySessionPage(first.next, page([r], { rev: 9 }))
    expect(second.report.metaChanged).toBe(false)
    const renamed = applySessionPage(second.next, page([r], { rev: 10, title: 'renamed' }))
    expect(renamed.report.metaChanged).toBe(true)
    expect(renamed.next.title).toBe('renamed')
  })

  it('carries rev forward for the next gated poll', () => {
    const { next } = applySessionPage(emptySessionData('s1'), page([row({})], { rev: 42 }))
    expect(next.rev).toBe(42)
  })
})
