import type { AnnotationsPage, RunInfo, SessionMeta, SessionResponse, TimingSummary, UsageSummary } from './types'

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path} ${res.status}`)
  return res.json() as Promise<T>
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
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
  runs: () => getJSON<RunInfo[]>('/api/runs'),
  appendEvent: (event: Record<string, unknown>) =>
    postJSON<{ ok: true; seq: number }>('/api/events', event),
  createRun: (description: string) =>
    postJSON<{ ok: true; run_id: string }>('/api/runs', { description }),
  renameRun: (runId: string, name: string) =>
    postJSON<{ ok: true; name: string }>(`/api/runs/${encodeURIComponent(runId)}/name`, { name }),
}

// v1 事件信封：标注/归组等前端写入的统一组装（与 schema.parse_event 对齐）
export function eventEnvelope(agentId: string | null, sessionId: string, type: string, payload: Record<string, unknown>) {
  return {
    v: 1 as const,
    id: crypto.randomUUID().replace(/-/g, ''),
    agent_id: agentId ?? 'unknown',
    session_id: sessionId,
    ts: Date.now(),
    type,
    turn: null,
    payload,
  }
}
