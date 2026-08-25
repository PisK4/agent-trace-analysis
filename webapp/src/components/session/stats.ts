// 工具调用统计：从已加载窗口的行派生 calls/failed 分布。
// 语义平移自旧版 web/js/stats.js refreshToolStats；面板渲染在 StatsPanel。
import type { ProjectedRow } from '../../api/types'

export interface ToolStat {
  name: string
  calls: number
  failed: number
  /** 失败行的 id 列表（按时间序），点击跳转用 */
  failedIds: string[]
}

export function toolStats(rows: ProjectedRow[]): { tools: ToolStat[]; totalCalls: number; totalFailed: number } {
  const byName = new Map<string, ToolStat>()
  let totalCalls = 0
  for (const row of rows) {
    if (row.kind !== 'tool' && row.kind !== 'subtool') continue
    if (!row.name) continue
    totalCalls += 1
    const stat = byName.get(row.name) ?? { name: row.name, calls: 0, failed: 0, failedIds: [] }
    stat.calls += 1
    if (row.status === 'failed') {
      stat.failed += 1
      stat.failedIds.push(row.id)
    }
    byName.set(row.name, stat)
  }
  // 按失败数 → 调用数降序（与旧版同口径）
  const tools = [...byName.values()].sort((a, b) => b.failed - a.failed || b.calls - a.calls)
  return { tools, totalCalls, totalFailed: tools.reduce((n, t) => n + t.failed, 0) }
}
