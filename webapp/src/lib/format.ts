// 展示格式化：与旧版 web/js/util.js 同口径
const p2 = (n: number) => String(n).padStart(2, '0')

export function shortTime(ms: number): string {
  if (!ms) return '—'
  const d = new Date(ms)
  return `${p2(d.getHours())}:${p2(d.getMinutes())}`
}

export function fullTime(ms: number): string {
  if (!ms) return '—'
  const d = new Date(ms)
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
}
