import { describe, expect, it } from 'vitest'
import type { ProjectedRow } from '../api/types'
import {
  copyTextFor,
  createTabHistory,
  durLabel,
  lineDiff,
  modelLabel,
  parseMaybe,
  prevCallDiff,
  sessionUsage,
  statusLabel,
  tabsOf,
} from './inspectorModel'

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

describe('tabsOf', () => {
  const byId = (id: string) => ROWS.find((r) => r.id === id)
  const ROWS = [
    row({ id: 'sys', kind: 'system' }),
    row({ id: 'sys2', kind: 'system', previousPrompt: 'old' }),
    row({ id: 'cmp', kind: 'compacted' }),
    row({ id: 'tool', kind: 'tool', payload: { a: 1 }, result: 'ok' }),
    row({ id: 'toolbare', kind: 'tool' }),
    row({ id: 'asst', kind: 'assistant' }),
    row({ id: 'user', kind: 'user' }),
  ]

  it('request 目标固定三 tab', () => {
    expect(tabsOf({ type: 'request', id: 'x' }, byId)).toEqual(['summary', 'usage', 'timing'])
  })
  it('system：无前版无 Diff，有前版多 Diff', () => {
    expect(tabsOf({ type: 'record', id: 'sys' }, byId)).toEqual(['prompt', 'tools', 'skills'])
    expect(tabsOf({ type: 'record', id: 'sys2' }, byId)).toEqual(['diff', 'prompt', 'tools', 'skills'])
  })
  it('compacted 两 tab；tool 按 payload/result 有无增删', () => {
    expect(tabsOf({ type: 'record', id: 'cmp' }, byId)).toEqual(['summary', 'raw'])
    expect(tabsOf({ type: 'record', id: 'tool' }, byId)).toEqual(['summary', 'payload', 'result', 'schema', 'timing'])
    expect(tabsOf({ type: 'record', id: 'toolbare' }, byId)).toEqual(['summary', 'schema', 'timing'])
  })
  it('消息类三 tab；未知行兜底 summary', () => {
    expect(tabsOf({ type: 'record', id: 'asst' }, byId)).toEqual(['summary', 'preview', 'raw'])
    expect(tabsOf({ type: 'record', id: 'nope' }, byId)).toEqual(['summary'])
  })
})

describe('createTabHistory', () => {
  it('remember 置顶、restore 按最近优先回退到合法 tab', () => {
    const h = createTabHistory()
    h.remember('timing')
    h.remember('raw')
    expect(h.restore(['summary', 'timing'])).toBe('timing')
    expect(h.restore(['summary'])).toBe('summary')
  })
})

describe('lineDiff', () => {
  it('局部编辑只显示改动区 + ctx=2 上下文与折叠计数', () => {
    const before = Array.from({ length: 10 }, (_, i) => `line${i}`).join('\n')
    const after = before.replace('line5', 'CHANGED')
    const parts = lineDiff(before, after)
    expect(parts.some((p) => p.t === 'del' && p.text.includes('line5'))).toBe(true)
    expect(parts.some((p) => p.t === 'add' && p.text.includes('CHANGED'))).toBe(true)
    expect(parts.filter((p) => p.t === 'fold').map((p) => (p.t === 'fold' ? p.n : 0))).toEqual([3])
    expect(parts.filter((p) => p.t === 'ctx')).toHaveLength(4)
  })
  it('完全相同 → 只有上下文行，无 +/-', () => {
    const parts = lineDiff('a\nb', 'a\nb')
    expect(parts.every((p) => p.t === 'ctx')).toBe(true)
  })
})

describe('parseMaybe / 文案', () => {
  it('JSON 探测：对象数组通过，标量/残破串拒绝', () => {
    expect(parseMaybe('{"a":1}')).toEqual({ a: 1 })
    expect(parseMaybe('[1,2]')).toEqual([1, 2])
    expect(parseMaybe('hello')).toBeNull()
    expect(parseMaybe('{"a":')).toBeNull()
    expect(parseMaybe('"str"')).toBeNull()
  })
  it('status/model/dur 标签', () => {
    expect(statusLabel('failed')).toBe('Failed')
    expect(statusLabel('completed')).toBe('Completed')
    expect(modelLabel({ model: 'gpt', effort: 'high' })).toBe('gpt · high')
    expect(modelLabel({ model: null, effort: null })).toBe('Not present')
    expect(durLabel(500)).toBe('500 ms')
    expect(durLabel(1500)).toBe('1.50 s')
    expect(durLabel(15000)).toBe('15.0 s')
  })
})

describe('sessionUsage', () => {
  it('累计 reported assistant 行，忽略其余', () => {
    const rows = [
      row({ id: '1', kind: 'assistant', usage: { status: 'reported', input: 100, output: 10, cacheRead: 5, cacheWrite: 0, totalTokens: 110, cost: 0.01 } }),
      row({ id: '2', kind: 'tool' }),
      row({ id: '3', kind: 'assistant', usage: { status: 'reported', input: 50, output: 5, cacheRead: 0, cacheWrite: 0, totalTokens: 55, cost: 0.02 } }),
      row({ id: '4', kind: 'assistant', usage: { status: 'n/a', input: 999, output: 999, cacheRead: 0, cacheWrite: 0, totalTokens: 999, cost: 9 } }),
    ]
    const cum = sessionUsage(rows)
    expect(cum?.count).toBe(2)
    expect(cum?.usage.input).toBe(150)
    expect(cum?.usage.cost).toBeCloseTo(0.03)
    expect(sessionUsage([])).toBeNull()
  })
})

describe('prevCallDiff / copyTextFor', () => {
  it('同名工具取 _seq 更小的前例做 payload diff', () => {
    const rows = [
      row({ id: 't1', kind: 'tool', name: 'read', _seq: 1, payload: { path: 'a' } }),
      row({ id: 't2', kind: 'tool', name: 'read', _seq: 2, payload: { path: 'b' } }),
    ]
    const diff = prevCallDiff(rows[1], rows)
    expect(diff?.some((p) => p.t === 'del' && p.text.includes('"a"'))).toBe(true)
    expect(diff?.some((p) => p.t === 'add' && p.text.includes('"b"'))).toBe(true)
    expect(prevCallDiff(rows[0], rows)).toBeNull() // 无前例
  })
  it('copy 各类原文都从字段取', () => {
    const r = row({ id: 'x', text: 'body', payload: { k: 1 }, promptText: 'sys prompt', thinking: 'hmm', outputText: 'out' })
    expect(copyTextFor('payload', r)).toBe('{\n  "k": 1\n}')
    expect(copyTextFor('prompt', r)).toBe('sys prompt')
    expect(copyTextFor('raw', r)).toBe('hmm\n\nout')
    expect(copyTextFor('result', r)).toBe('out')
  })
})
