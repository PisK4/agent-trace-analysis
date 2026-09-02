// sess-tabs 滚轮→横向滚动决策：可溢出才拦截；clamp 到 [0, scrollWidth-clientWidth]；到底/顶放行。
import { describe, expect, it } from 'vitest'
import { nextTabsScrollLeft } from './tabsScroll'

describe('nextTabsScrollLeft', () => {
  it('returns null when deltaY is zero (无滚轮信号)', () => {
    expect(nextTabsScrollLeft(0, 500, 200, 0)).toBeNull()
  })

  it('returns null when content does not overflow (放行页面滚动)', () => {
    expect(nextTabsScrollLeft(0, 200, 200, 100)).toBeNull()
    expect(nextTabsScrollLeft(0, 180, 200, 100)).toBeNull()
  })

  it('scrolls right by deltaY when within range', () => {
    expect(nextTabsScrollLeft(0, 500, 200, 80)).toBe(80)
  })

  it('clamps to max when scrolling past the end', () => {
    // max = 500 - 200 = 300, current=250, deltaY=200 → clamp 300
    expect(nextTabsScrollLeft(250, 500, 200, 200)).toBe(300)
  })

  it('returns null when already at the rightmost edge', () => {
    expect(nextTabsScrollLeft(300, 500, 200, 50)).toBeNull()
  })

  it('clamps to zero when scrolling left past the start', () => {
    expect(nextTabsScrollLeft(20, 500, 200, -100)).toBe(0)
  })

  it('returns null when already at the leftmost edge', () => {
    expect(nextTabsScrollLeft(0, 500, 200, -50)).toBeNull()
  })
})
