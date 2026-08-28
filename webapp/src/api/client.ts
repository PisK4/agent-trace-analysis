import type { AnnotationsPage, EvaluationDetail, EvaluationsPage, RunInfo, SessionMeta, SessionResponse, TimingSummary, UsageSummary } from './types'

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path} ${res.status}`)
  return res.json() as Promise<T>
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  return requestJSON<T>(path, 'POST', body)
}

async function requestJSON<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ error: res.status }))
    throw new Error(String((detail as { error?: unknown }).error ?? res.status))
  }
  return res.json() as Promise<T>
}

export const api = {
  listSessions: () => getJSON<SessionMeta[]>('/api/sessions'),

  // rev 门控轮询的唯一入口：命中 unchanged 返回 Unchanged，零投影成本；
  // 未命中返回整页 + 新 rev。before+limit 走同一端点拉更早历史（loadOlder）。
  session: (id: string, opts: { rev?: number; before?: number; limit?: number } = {}) => {
    const qs = new URLSearchParams()
    if (opts.rev != null) qs.set('rev', String(opts.rev))
    if (opts.before != null) qs.set('before', String(opts.before))
    if (opts.limit != null) qs.set('limit', String(opts.limit))
    const q = qs.size ? `?${qs}` : ''
    return getJSON<SessionResponse>(`/api/sessions/${encodeURIComponent(id)}${q}`)
  },

  usage: (id: string) =>
    getJSON<UsageSummary>(`/api/sessions/${encodeURIComponent(id)}/usage`),

  timing: (id: string) =>
    getJSON<TimingSummary>(`/api/sessions/${encodeURIComponent(id)}/timing`),

  renameSession: (id: string, title: string) =>
    postJSON<{ ok: true; title: string }>(`/api/sessions/${encodeURIComponent(id)}/title`, { title }),

  annotations: () => getJSON<AnnotationsPage>('/api/annotations'),
  // Evaluation 路由由后端事实服务提供；客户端不重算 latest-wins 折叠。
  evaluations: () => getJSON<EvaluationsPage>('/api/evaluations'),
  evaluation: (id: string) => getJSON<EvaluationDetail>(`/api/evaluations/${encodeURIComponent(id)}`),
  createEvaluation: (title: string) => postJSON<{ ok: true; evaluation_id: string }>('/api/evaluations', { title }),
  renameEvaluation: (id: string, title: string) => postJSON<{ ok: true; title: string }>(`/api/evaluations/${encodeURIComponent(id)}/title`, { title }),
  deleteEvaluation: (id: string) => requestJSON<{ ok: true }>(`/api/evaluations/${encodeURIComponent(id)}`, 'DELETE'),
  addEvaluationSession: (id: string, sessionId: string, taskLabel: string) =>
    postJSON<{ ok: true }>(`/api/evaluations/${encodeURIComponent(id)}/sessions`, { session_id: sessionId, task_label: taskLabel }),
  removeEvaluationSession: (id: string, sessionId: string) =>
    requestJSON<{ ok: true }>(`/api/evaluations/${encodeURIComponent(id)}/sessions/${encodeURIComponent(sessionId)}`, 'DELETE'),
  runs: () => getJSON<RunInfo[]>('/api/runs'),
  appendEvent: (event: Record<string, unknown>) =>
    postJSON<{ ok: true; seq: number }>('/api/events', event),

  // 标注/归组写入口（TopBar 与标注板共用）：agent 解析在 seam 内
  appendForSession,
  createRun: (description: string) =>
    postJSON<{ ok: true; run_id: string }>('/api/runs', { description }),
  renameRun: (runId: string, name: string) =>
    postJSON<{ ok: true; name: string }>(`/api/runs/${encodeURIComponent(runId)}/name`, { name }),
}

// v1 事件信封：前端写入的统一组装（与 schema.parse_event 对齐）。
// agentId 必传——曾允许 null 落成 'unknown'，被 schema 白名单 400 拒收，
// 会话页三条写路径因此全坏；接口不再接受调用方撒谎。
export function eventEnvelope(agentId: string, sessionId: string, type: string, payload: Record<string, unknown>) {
  return {
    v: 1 as const,
    id: crypto.randomUUID().replace(/-/g, ''),
    agent_id: agentId,
    session_id: sessionId,
    ts: Date.now(),
    type,
    turn: null,
    payload,
  }
}

// 标注/归组写路径的唯一 seam（架构评审二轮候选 1）：agent_id 解析收在此处，
// 调用方只说「给会话 s 打 good」，不需要知道 agent。会话详情投影页带 agent
// 字段；写操作是用户点击级低频，多一次 GET 换掉两套各写各的反查逻辑。
async function appendForSession(sessionId: string, type: string, payload: Record<string, unknown>) {
  const page = await getJSON<{ agent: string }>(`/api/sessions/${encodeURIComponent(sessionId)}`)
  return postJSON<{ ok: true; seq: number }>('/api/events',
    eventEnvelope(page.agent, sessionId, type, payload))
}
