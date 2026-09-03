// sess-tabs 滚轮→横向滚动决策：返回新的 scrollLeft；返回 null 表示放行（不可溢出 / 已在边界 / 无 deltaY）。
// 独立成纯函数便于单元测试，不直接耦合 DOM 几何读取。
export function nextTabsScrollLeft(
  current: number,
  scrollWidth: number,
  clientWidth: number,
  deltaY: number,
): number | null {
  if (deltaY === 0) return null
  if (scrollWidth <= clientWidth) return null
  const max = scrollWidth - clientWidth
  const next = Math.max(0, Math.min(max, current + deltaY))
  return next === current ? null : next
}
