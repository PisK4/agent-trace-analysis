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
  kind: 'user' | 'assistant' | 'context' | 'system' | 'tool' | 'subtool' | 'compacted'
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
  // 客户端标记（服务端不下发）：loadOlder 攒下的 tail 窗口外历史行
  keptOlder?: boolean
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

// ── 标注板（board）──

export interface ScoreEntry {
  session_id: string
  value: string
  note: string | null
  ts: number
  seq: number
  agent: string | null
  title: string | null
  event_count: number
  error_count: number
}

export interface AssignmentEntry {
  session_id: string
  run_id: string | null
  task_id: string | null
  ts: number
  seq: number
  agent: string | null
  title: string | null
  event_count: number
  error_count: number
}

// GET /api/annotations（ledger.annotations：latest-wins 折叠墓碑后）
export interface AnnotationsPage {
  ok: true
  scores: ScoreEntry[]
  assignments: AssignmentEntry[]
}

export interface RunInfo {
  run_id: string
  description: string
  taskset_fingerprint: string | null
  created_ts: number
  assignment_count?: number
}

// ── Usage 全周期（GET /api/sessions/{id}/usage，project.py summarize_usage/audit_usage）──

// 逐轮 usage：context 是方言感知的上下文占用（后端算好）
export interface UsageTurn {
  turn: number
  seq: number
  agent: string
  model: string | null
  effort: string | null
  status: 'reported' | 'missing' | 'estimated'
  input: number | null
  output: number | null
  cache_read: number | null
  cache_write: number | null
  total_tokens: number | null
  cost: number | null
  context: number | null
}

export interface UsageAuditFinding {
  rule: 'missing' | 'placeholder' | 'duplicate' | 'cliff'
  turn: number
  detail: string
}

export interface UsageSummary {
  ok: true
  turns: UsageTurn[]
  total: { input: number; output: number; cache_read: number; cache_write: number; total_tokens: number }
  missing_turns: number
  audit: { findings: UsageAuditFinding[]; reported_turns: number; expected_turns: number }
  compactions: Array<{ turn: number | null; seq: number }>
}

// ── 会话时间拆解（GET /api/sessions/{id}/timing，project.py summarize_timing）──

export interface TimingTurn {
  turn: number
  llm_ms: number
  tool_ms: number
  steps: number
  calls: number
}

export interface TimingSummary {
  ok: true
  span_ms: number
  first_ts: number | null
  last_ts: number | null
  turns: number
  steps: number
  calls: number
  llm_ms: number
  tool_ms: number
  other_ms: number
  llm_quality: 'measured' | 'placeholder' | 'n/a'
  tool_quality: 'measured' | 'placeholder' | 'n/a'
  per_turn: TimingTurn[]
}
