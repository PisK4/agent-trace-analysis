import { describe, expect, it } from 'vitest'
import { fmtDur, fmtDurQ } from './timing'

describe('fmtDur', () => {
  it('毫秒档', () => expect(fmtDur(33)).toBe('33 ms'))
  it('秒档', () => expect(fmtDur(13600)).toBe('13.6 s'))
  it('分档不显示成 802s', () => expect(fmtDur(802_000)).toBe('13m22s'))
})

describe('fmtDurQ', () => {
  it('未测量显示 — 而非 0 ms', () => expect(fmtDurQ(0, 'placeholder')).toBe('—'))
  it('实测走正常格式化', () => expect(fmtDurQ(250, 'measured')).toBe('250 ms'))
})
