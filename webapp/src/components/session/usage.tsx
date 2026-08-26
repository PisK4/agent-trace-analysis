// 行内 usage 迷你条：↓输入 ↑输出 · 缓存读写徽标 · 成本，悬停展开六字段明细。
// 语义平移自旧版 web/js/util.js usageStrip/usageCells；明细弹层用 CSS hover
// 替代旧版的全局 #tip 跟随。
import type { RowUsage } from '../../api/types'
import { fmtCost, fmtNum } from '../../lib/format'

function cells(usage: RowUsage) {
  const cell = (label: string, value: string | null, missing: boolean) => (
    <div className="u-cell" key={label}>
      <span>{label}</span>
      {missing ? <b className="miss">Missing</b> : <b>{value}</b>}
    </div>
  )
  const na = usage.status === 'n/a'
  const st = (v: number | null) => na || v == null
  return (
    <div className="usage-grid">
      {cell('Input', fmtNum(usage.input), st(usage.input))}
      {cell('Output', fmtNum(usage.output), st(usage.output))}
      {cell('Cache read', fmtNum(usage.cacheRead), st(usage.cacheRead))}
      {cell('Cache write', fmtNum(usage.cacheWrite), st(usage.cacheWrite))}
      {cell('Total tokens', fmtNum(usage.totalTokens), st(usage.totalTokens))}
      {cell('Cost', fmtCost(usage.cost), st(usage.cost as number | null))}
    </div>
  )
}

/** Ledger 行内的紧凑条。缓存/cost 为 0 或缺失不上条；cost 只在真实上报时显示，
 *  不查价目表补算（Droid 等方言恒缺，如实标 Missing）。 */
export function usageStripInline(usage: RowUsage) {
  if (!usage || usage.status === 'n/a') return null
  const est = usage.status === 'estimated' ? <span className="us-est" title="estimated，非实测">est</span> : null
  const strip = (
    <div className={`ustrip ${usage.status === 'reported' ? '' : 'us-dim'}`}>
      <span className="us-seg us-in" title="Input tokens">↓ <b>{fmtNum(usage.input)}</b></span>
      <span className="us-seg us-out" title="Output tokens">↑ <b>{fmtNum(usage.output)}</b></span>
      {usage.cacheRead ? <span className="us-seg us-cache" title="Cache read tokens">⛁ <b>{fmtNum(usage.cacheRead)}</b></span> : null}
      {usage.cacheWrite ? <span className="us-seg us-cache" title="Cache write tokens">⛁+ <b>{fmtNum(usage.cacheWrite)}</b></span> : null}
      {usage.cost ? <span className="us-seg us-cost" title="Cost">${fmtCost(usage.cost)}</span> : null}
      <span className="us-info" title="悬停看明细">ⓘ</span>
      <div className="ustrip-pop">{cells(usage)}</div>
    </div>
  )
  return <span className="row-usage">{strip}{est}</span>
}
