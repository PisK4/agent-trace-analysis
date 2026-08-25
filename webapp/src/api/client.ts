import type { SessionMeta, SessionResponse } from './types'

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
  // 未命中返回整页 + 新 rev。
  session: (id: string, rev?: number) =>
    getJSON<SessionResponse>(`/api/sessions/${encodeURIComponent(id)}${rev != null ? `?rev=${rev}` : ''}`),

  renameSession: (id: string, title: string) =>
    postJSON<{ ok: true; title: string }>(`/api/sessions/${encodeURIComponent(id)}/title`, { title }),
}
