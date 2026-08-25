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

/** 千分位：12345 → "12,345"；null → "—"（旧版 fmtNum） */
export function fmtNum(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toLocaleString('en-US')
}

/** 成本：小于一分钱用三位有效数字，避免 $0.00（旧版 fmtCost） */
export function fmtCost(v: number | null | undefined): string | null {
  if (v == null) return null
  return Math.abs(v) < 0.01 ? Number(v).toPrecision(3) : v.toLocaleString('en-US', { maximumFractionDigits: 4 })
}
