// Ledger 表格的数据模型：过滤 → 折叠投影 → 虚拟窗口，全部纯函数。
// 语义平移自旧版 web/js/model.js displayRecords / table.js virtualRows。
import type { ProjectedRow } from '../api/types'
import { rowTurnKey, rowTurnLabel } from './turnIdentity'

export type TableFilter = '' | 'failed' | 'tools'

// 折叠后的显示行：content 是真实投影行，summary 是折叠占位行
export interface ContentRow extends ProjectedRow {
  virtual: 'content'
}

export interface SummaryRow {
  virtual: 'summary'
  id: string
  index: number
  turn: number | null
  kind: 'summary'
  tag: 'SUMMARY'
  text: string
  expandTurn?: string | number
  turnLabel?: string | null
  expandAssistant?: string
}

export type DisplayRow = ContentRow | SummaryRow

export function rowContent(row: ProjectedRow, rows: ProjectedRow[]): string {
  if (row.kind === 'tool' || row.kind === 'subtool') {
    return compactPreview(row.text || row.name || row.tag)
  }
  if (row.text) return compactPreview(row.text)
  if (row.kind !== 'assistant') return compactPreview(row.text)
  const names: string[] = []
  for (const item of rows) {
    if (item.parentId !== row.id || (item.kind !== 'tool' && item.kind !== 'subtool')) continue
    if (item.name && !names.includes(item.name)) names.push(item.name)
  }
  return names.join(' · ')
}

const compactPreview = (text: string) => String(text || '').replace(/\s+/g, ' ').trim()

function matchesSearch(row: ProjectedRow, terms: string[]): boolean {
  if (!terms.length) return true
  const blob = [
    row.tag, row.kind, row.text, row.name, row.result, row.outputText,
    row.payloadText, row.promptText, row.note, row.thinking, row.model, row.effort,
    JSON.stringify(row.payload ?? ''),
  ].join(' ').toLowerCase()
  return terms.every((t) => blob.includes(t))
}

/**
 * 折叠投影：turn 折叠成 SUMMARY 行、assistant 后随工具链折叠成 SUMMARY 行。
 * collapsedTurns/collapsedAssistants 是客户端折叠态；search 非空时直接平铺匹配行。
 */
export function displayRecords(
  rows: ProjectedRow[],
  opts: {
    filter: TableFilter
    search: string
    collapsedTurns: Set<string | number>
    collapsedAssistants: Set<string>
  },
): DisplayRow[] {
  let base = rows
  if (opts.filter === 'failed') base = rows.filter((r) => r.status === 'failed')
  else if (opts.filter === 'tools') base = rows.filter((r) => r.kind === 'tool' || r.kind === 'subtool')

  const terms = opts.search.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length) {
    return base.filter((r) => matchesSearch(r, terms)).map((r) => ({ ...r, virtual: 'content' }))
  }

  const byTurn = new Map<string | number, ProjectedRow[]>()
  for (const row of base) {
    const key = rowTurnKey(row)
    if (key == null) continue
    const list = byTurn.get(key) ?? []
    list.push(row)
    byTurn.set(key, list)
  }

  const out: DisplayRow[] = []
  for (const row of base) {
    const turnKey = rowTurnKey(row)
    if (turnKey == null || !opts.collapsedTurns.has(turnKey) || row.kind === 'system') {
      out.push({ ...row, virtual: 'content' })
      continue
    }
    const content = (byTurn.get(turnKey) ?? []).filter((item) => item.kind !== 'system')
    if (content.length <= 1 || row.id !== content[0].id) continue
    out.push({ ...row, virtual: 'content' })
    const rest = content.slice(1)
    const steps = new Set(rest.map((i) => i.group).filter((g) => g && g.startsWith('Step '))).size
    const tools = rest.filter((i) => i.kind === 'tool' || i.kind === 'subtool').length
    out.push({
      virtual: 'summary',
      id: `${row.id}__turn`,
      index: row.index,
      turn: row.turn,
      kind: 'summary',
      tag: 'SUMMARY',
      text: `${steps} ${steps === 1 ? 'step' : 'steps'} · ${tools} tool ${tools === 1 ? 'call' : 'calls'}`,
      expandTurn: turnKey,
      turnLabel: rowTurnLabel(row),
    })
  }

  // assistant 折叠：吃掉其后连续的 tool/subtool 行，换成一条 SUMMARY
  const folded: DisplayRow[] = []
  for (let i = 0; i < out.length; i++) {
    const row = out[i]
    folded.push(row)
    if (row.kind !== 'assistant' || !opts.collapsedAssistants.has(row.id)) continue
    const calls: DisplayRow[] = []
    for (let j = i + 1; j < out.length; j++) {
      if (out[j].kind !== 'tool' && out[j].kind !== 'subtool') break
      calls.push(out[j])
    }
    if (!calls.length) continue
    const names = [...new Set(calls.map((c) => (c as ContentRow).name).filter(Boolean))] as string[]
    folded.push({
      virtual: 'summary',
      id: `${row.id}__calls`,
      index: row.index,
      turn: row.turn ?? null,
      kind: 'summary',
      tag: 'SUMMARY',
      text: `${calls.length} tool ${calls.length === 1 ? 'call' : 'calls'}${names.length ? ` · ${names.join(', ')}` : ''}`,
      expandAssistant: row.id,
    })
    i += calls.length
  }
  return folded
}

export interface VirtualWindow {
  rows: DisplayRow[]
  topSpacer: number
  bottomSpacer: number
  hasOlderButton: boolean
}

export const VIRTUAL_THRESHOLD = 100
export const OVERSCAN = 12
export const CONTENT_ROW_HEIGHT = 30
export const COLLAPSED_SUMMARY_HEIGHT = 20

/**
 * 虚拟滚动窗口：行数少或有更早历史锚点时全量渲染；否则按 scrollTop 切窗，
 * 上下用定高 spacer 撑起总高（行高固定 30/20，无需测量）。
 */
export function virtualWindow(
  records: DisplayRow[],
  opts: { hasOlder: boolean; scrollTop: number; viewportHeight: number },
): VirtualWindow {
  const force = opts.hasOlder
  if (records.length <= VIRTUAL_THRESHOLD && !force) {
    return { rows: records, topSpacer: 0, bottomSpacer: 0, hasOlderButton: opts.hasOlder }
  }
  const olderH = opts.hasOlder ? CONTENT_ROW_HEIGHT : 0
  const offsets: Array<{ row: DisplayRow; start: number; end: number }> = []
  let offset = olderH
  for (const row of records) {
    const h = row.virtual === 'summary' ? COLLAPSED_SUMMARY_HEIGHT : CONTENT_ROW_HEIGHT
    offsets.push({ row, start: offset, end: offset + h })
    offset += h
  }
  const viewH = opts.viewportHeight || 600
  const top = opts.scrollTop
  let first = offsets.findIndex((o) => o.end >= top)
  if (first < 0) first = 0
  let last = offsets.findIndex((o) => o.start > top + viewH)
  if (last < 0) last = offsets.length
  first = Math.max(0, first - OVERSCAN)
  last = Math.min(offsets.length, last + OVERSCAN)
  const shown = offsets.slice(first, last)
  return {
    rows: shown.map((o) => o.row),
    topSpacer: Math.max(0, (shown[0]?.start ?? olderH) - olderH),
    bottomSpacer: Math.max(0, offset - (shown.length ? shown[shown.length - 1].end : olderH)),
    hasOlderButton: opts.hasOlder,
  }
}

/** 可折叠的 turn 集合：行数 >1 的 turn 才有折叠意义 */
export function collapsibleTurns(rows: ProjectedRow[]): Array<string | number> {
  const counts = new Map<string | number, number>()
  for (const row of rows) {
    const key = rowTurnKey(row)
    if (key == null || row.kind === 'system') continue
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return [...counts.entries()].filter(([, n]) => n > 1).map(([turn]) => turn)
}

/** 可折叠的 assistant 行：其后紧跟 tool/subtool 的 */
export function collapsibleAssistants(rows: ProjectedRow[]): string[] {
  const ids: string[] = []
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    const next = rows[i + 1]
    if (row.kind === 'assistant' && next && (next.kind === 'tool' || next.kind === 'subtool')) ids.push(row.id)
  }
  return ids
}
