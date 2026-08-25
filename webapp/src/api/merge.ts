// rev 门控 + 按行 upsert 合并：会话页数据的唯一落地路径。
//
// 投影层的行是「同 id 新版本」语义（流式增长的 assistant 文本、
// pending→completed 的工具行都以新 _seq 整行重现），所以合并不做字段级
// diff，只按 id 整行替换；未变行保留原对象身份，对象引用相等即未变，
// 供 React memo / 分区重绘判断用。
import type { ProjectedRow, SessionPage } from './types'

export interface SessionData {
  rows: ProjectedRow[]
  title: string
  crumb: string
  hasOlder: boolean
  cursor: number
  turns: number
  scores: SessionPage['scores']
  toolsIndex: SessionPage['tools_index']
  rev: number
}

export interface MergeReport {
  rowsChanged: boolean
  metaChanged: boolean
}

export function emptySessionData(id: string): SessionData {
  return {
    rows: [],
    title: id,
    crumb: '',
    hasOlder: false,
    cursor: 0,
    turns: 0,
    scores: [],
    toolsIndex: {},
    rev: 0,
  }
}

// 行级相等：剔除随页窗口变的 index 后整行比对。两侧都出自服务端同一
// 序列化器，键序一致，JSON 字符串比较即结构比较。
function sameRow(a: ProjectedRow, b: ProjectedRow): boolean {
  const { index: _ai, ...ra } = a
  const { index: _bi, ...rb } = b
  return JSON.stringify(ra) === JSON.stringify(rb)
}

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

/**
 * 把一页投影结果 upsert 进当前状态，返回变化报告。
 *
 * - id 相同且内容全等 → 保留旧对象（身份即变更标记）
 * - 同 id 内容变或新 id → 用新对象替换/追加
 * - keptOlder 行（loadOlder 攒下的 tail 窗口外历史）继续保留并排最前
 * - 最终按 _seq 排序并重编 index（折叠替换会让旧行以新 seq 重现）
 */
export function applySessionPage(current: SessionData, page: SessionPage): {
  next: SessionData
  report: MergeReport
} {
  const report: MergeReport = { rowsChanged: false, metaChanged: false }

  const oldById = new Map(current.rows.map((r) => [r.id, r]))
  const merged: ProjectedRow[] = []
  for (const row of page.rows) {
    const prev = oldById.get(row.id)
    if (prev && sameRow(prev, row)) {
      merged.push(prev)
      continue
    }
    merged.push(row)
    report.rowsChanged = true
  }
  const tailIds = new Set(page.rows.map((r) => r.id))
  for (const row of current.rows) {
    if (row.keptOlder && !tailIds.has(row.id)) merged.unshift(row)
  }
  merged.sort((a, b) => a._seq - b._seq)
  // 只在 index 真变了才造新对象，否则未变行的对象身份会在这里丢掉
  const rows = merged.map((row, i) => (row.index === i ? row : { ...row, index: i }))
  if (rows.length !== current.rows.length) report.rowsChanged = true

  // 服务端 snake_case → SessionData camelCase，一一对应
  const meta: Pick<SessionData, 'title' | 'crumb' | 'hasOlder' | 'cursor' | 'turns' | 'scores' | 'toolsIndex'> = {
    title: page.title,
    crumb: page.crumb,
    hasOlder: page.has_older,
    cursor: page.cursor,
    turns: page.turns,
    scores: page.scores,
    toolsIndex: page.tools_index,
  }
  for (const [key, incoming] of Object.entries(meta)) {
    if (!sameValue(current[key as keyof typeof meta], incoming)) report.metaChanged = true
  }

  return {
    next: { ...current, ...meta, rows, rev: page.rev },
    report,
  }
}
