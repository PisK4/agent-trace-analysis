import { describe, expect, it } from 'vitest'
import { fmtDur } from './timing'

describe('fmtDur', () => {
  it('毫秒档', () => expect(fmtDur(33)).toBe('33 ms'))
  it('秒档', () => expect(fmtDur(13600)).toBe('13.6 s'))
  it('分档不显示成 802s', () => expect(fmtDur(802_000)).toBe('13m22s'))
})
