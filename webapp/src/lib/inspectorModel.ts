// Inspector 的数据层：tab 集合、状态/模型文案、行内 diff、JSON 探测与累计 usage。
// 语义平移自旧版 web/js/util.js tabsOf/statusLabel/modelLabel/lineDiff/parseMaybe/sessionUsage。
import type { ProjectedRow, RowUsage } from '../api/types'

export type InspectorTab =
  | 'summary' | 'usage' | 'timing'
  | 'diff' | 'prompt' | 'tools' | 'skills'
  | 'payload' | 'result' | 'schema'
  | 'preview' | 'raw' | 'source'

/** request 目标是 assistant 行的请求聚合视图（旧版 selectRequest 形态） */
export interface InspectTarget {
  type: 'record' | 'request'
  id: string
}

/**
 * 选中目标的 tab 集：按 kind 与数据有无动态增删。
 * system 行有前版 prompt 时多一个 Diff tab。
 */
export function tabsOf(target: InspectTarget, byId: (id: string) => ProjectedRow | undefined): InspectorTab[] {
  if (target.type === 'request') return ['summary', 'usage', 'timing']
  const row = byId(target.id)
  if (!row) return ['summary']
  if (row.kind === 'system') return row.previousPrompt ? ['diff', 'prompt', 'tools', 'skills'] : ['prompt', 'tools', 'skills']
  if (row.kind === 'compacted') return ['summary', 'raw']
  if (row.kind === 'tool' || row.kind === 'subtool') {
    const tabs: InspectorTab[] = ['summary']
    if (row.payload || row.payloadText) tabs.push('payload')
    if (row.result) tabs.push('result')
    tabs.push('schema', 'timing')
    return tabs
  }
  const tabs: InspectorTab[] = ['summary', 'preview', 'raw']
  // source tab：后端投影目前不下发 messageSource（旧版同款死分支），保留 tab id 以防将来恢复
  if ((row as { messageSource?: string }).messageSource) tabs.push('source')
  return tabs
}

// 跨目标记住用户去过的 tab：换选中时优先恢复历史 tab（旧版 rememberTab/restoreTab）
export function createTabHistory() {
  let history: InspectorTab[] = ['summary']
  return {
    get(): InspectorTab[] { return history },
    remember(id: InspectorTab) {
      history = history.filter((t) => t !== id).concat(id)
    },
    restore(tabs: InspectorTab[]): InspectorTab {
      const found = [...history].reverse().find((id) => tabs.includes(id))
      return found ?? tabs[0]
    },
  }
}

export const statusLabel = (status: string) =>
  status === 'failed' ? 'Failed' : status === 'cancelled' ? 'Cancelled' : status === 'pending' ? 'Pending' : 'Completed'

export function modelLabel(row: Pick<ProjectedRow, 'model' | 'effort'>): string {
  if (!row.model) return 'Not present'
  return row.effort ? `${row.model} · ${row.effort}` : row.model
}

/** 毫秒时长：<1s 给整数 ms，其余给 s 并按量级取舍入位 */
export const durLabel = (ms: number) =>
  ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`

export const commaMs = (ms: number) => `${Math.round(ms).toLocaleString('en-US')} ms`

export const clock = (ms: number) => {
  const d = new Date(ms)
  const p = (n: number, w = 2) => String(n).padStart(w, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`
}

const p2 = (n: number) => String(n).padStart(2, '0')

export const dayClock = (ms: number) => {
  const d = new Date(ms)
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${clock(ms)}`
}

/**
 * 行级 diff：只裁公共前后缀、不做 LCS，对「模型改了几个字段」这类局部编辑够用；
 * 大范围改写会显示成大段 +/-，届时再上真正的 diff 算法。ctx=2 行上下文。
 * 返回 React 可直接渲染的结构化行，不再拼 HTML 字符串。
 */
export type DiffLine =
  | { t: 'del'; text: string }
  | { t: 'add'; text: string }
  | { t: 'ctx'; text: string }
  | { t: 'fold'; n: number }

export function lineDiff(before: string, after: string): DiffLine[] {
  const A = before.split('\n')
  const B = after.split('\n')
  let s = 0
  while (s < A.length && s < B.length && A[s] === B[s]) s++
  let e = 0
  while (e < A.length - s && e < B.length - s && A[A.length - 1 - e] === B[B.length - 1 - e]) e++
  const ctx = 2
  const parts: DiffLine[] = []
  if (s > ctx) parts.push({ t: 'fold', n: s - ctx })
  for (let i = Math.max(0, s - ctx); i < s; i++) parts.push({ t: 'ctx', text: `  ${A[i]}` })
  for (let i = s; i < A.length - e; i++) parts.push({ t: 'del', text: `- ${A[i]}` })
  for (let i = s; i < B.length - e; i++) parts.push({ t: 'add', text: `+ ${B[i]}` })
  const tailStart = Math.max(A.length - e, s)
  // 尾部未展示的公共行数：tailStart..A.length-e 之间被裁掉的部分（旧版公式
  // A.length-e-tailStart-ctx 把后缀重复扣了一次，改动居中时会算出负数，此处修正）
  const tailHidden = A.length - e - tailStart
  if (tailHidden > ctx) parts.push({ t: 'fold', n: tailHidden - ctx })
  for (let i = tailStart; i < Math.min(tailStart + ctx, A.length); i++) parts.push({ t: 'ctx', text: `  ${A[i]}` })
  return parts
}

/** 整段字符串是否是一份 JSON 对象/数组（Cue 意图 context 等整条 JSON 正文） */
export function parseMaybe(text: unknown): object | null {
  if (typeof text !== 'string' || text.length < 2) return null
  const c = text[0]
  if (c !== '{' && c !== '[') return null
  try {
    const v = JSON.parse(text)
    return v && typeof v === 'object' ? (v as object) : null
  } catch {
    return null
  }
}

/** Session 累计 usage：只统计已加载窗口内 reported 的 assistant 行 */
export function sessionUsage(rows: ProjectedRow[]): { usage: RowUsage; count: number } | null {
  const total = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: 0 }
  let count = 0
  for (const row of rows) {
    const u = row.usage
    if (row.kind !== 'assistant' || !u || u.status !== 'reported') continue
    count += 1
    for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens', 'cost'] as const) {
      if (typeof u[key] === 'number') total[key] += u[key] as number
    }
  }
  if (!count) return null
  return { usage: { ...total, status: 'reported' }, count }
}

/** 同名工具的上一次调用入参 diff；没有前例或两侧 payload 都缺时返回 null */
export function prevCallDiff(row: ProjectedRow, rows: ProjectedRow[]): DiffLine[] | null {
  const same = rows.filter((r) => r.kind === 'tool' && r.name === row.name && r._seq < row._seq)
  const prev = same[same.length - 1]
  if (!prev || !row.payload || !prev.payload) return null
  return lineDiff(JSON.stringify(prev.payload, null, 2), JSON.stringify(row.payload, null, 2))
}

/** 复制用原文：从 row 字段取，不从 DOM 抄（markdown 保住源码、payload 抄不出干净 JSON） */
export function copyTextFor(kind: string, row: ProjectedRow): string {
  if (kind === 'payload') return JSON.stringify(row.payload ?? null, null, 2)
  if (kind === 'raw') return [row.thinking, row.outputText || row.payloadText || row.text].filter(Boolean).join('\n\n')
  if (kind === 'prompt') return row.promptText || ''
  return row.result || row.outputText || row.payloadText || row.text || ''
}
