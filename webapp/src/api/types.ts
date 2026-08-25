// /api/sessions 响应的会话行（ata/http.py _list_sessions → ledger._session_row）
export interface SessionMeta {
  id: string
  agent: string
  title: string
  turns: number
  last_seq: number
  last_ts: number
  first_ts: number
  parent_session_id: string | null
  event_count: number
  error_count: number
}

// 投影行的 usage 归一化形态（ata/project.py NA/MISS/_usage）
export interface RowUsage {
  status: 'reported' | 'missing' | 'n/a' | 'estimated'
  input: number | null
  output: number | null
  cacheRead: number | null
  cacheWrite: number | null
  totalTokens: number | null
  cost: number | null
}

// project_session 输出的统一行：message/tool/system/compacted 共用，
// 各 kind 只填自己用到的字段，其余为 undefined。
export interface ProjectedRow {
  id: string
  _seq: number
  _first?: number
  index: number
  turn: number | null
  kind: 'user' | 'assistant' | 'context' | 'system' | 'tool' | 'compacted'
  tag: string
  text: string
  startedAt: number
  durationMs: number
  status: string
  start?: boolean
  step?: number
  group?: string
  requestNo?: number
  outputText?: string | null
  payloadText?: string | null
  thinking?: string | null
  model?: string | null
  effort?: string | null
  usage: RowUsage
  name?: string
  parentId?: string | null
  payload?: unknown
  result?: string | null
  promptText?: string | null
  previousPrompt?: string | null
  toolsCatalog?: Array<{ name: string; description?: string; parameters?: object }>
  skillsCatalog?: Array<Record<string, unknown>>
  note?: string | null
}

export interface ToolSchema {
  name: string
  description?: string
  parameters?: object
}

// GET /api/sessions/{id} 整页（project.py project_session）
export interface SessionPage {
  id: string
  agent: string
  title: string
  crumb: string
  has_older: boolean
  cursor: number
  turns: number
  scores: Array<{ value: string; note: string | null; ts: number }>
  tools_index: Record<string, ToolSchema>
  rows: ProjectedRow[]
  rev: number
}

// rev 门控命中时的短响应（ata/http.py sub == "" 分支）
export interface Unchanged {
  ok: true
  unchanged: true
  rev: number
}

export type SessionResponse = SessionPage | Unchanged

export function isUnchanged(res: SessionResponse): res is Unchanged {
  return 'unchanged' in res && res.unchanged === true
}
