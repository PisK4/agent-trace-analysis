import { describe, expect, it } from 'vitest'
import { isUnchanged, type SessionResponse } from './types'

describe('isUnchanged', () => {
  it('detects rev-gated short response', () => {
    const res: SessionResponse = { ok: true, unchanged: true, rev: 7 }
    expect(isUnchanged(res)).toBe(true)
  })

  it('treats full page as changed', () => {
    const res: SessionResponse = {
      id: 's1', agent: 'pi', title: 't', crumb: 'c', has_older: false,
      cursor: 3, turns: 1, scores: [], tools_index: {}, rows: [], rev: 8,
    }
    expect(isUnchanged(res)).toBe(false)
  })
})
