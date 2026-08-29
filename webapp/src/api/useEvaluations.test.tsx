import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'
import { useEvaluations } from './useEvaluations'
import type {
  EvaluationDetail, EvaluationHistoryEntry, EvaluationSummary, SessionMeta,
} from './types'

const sessions: SessionMeta[] = [
  { id: 's1', agent: 'pi', title: 's1t', turns: 1, last_seq: 1, last_ts: 1, first_ts: 1, parent_session_id: null, event_count: 1, error_count: 0 },
  { id: 's2', agent: 'pi', title: 's2t', turns: 1, last_seq: 1, last_ts: 1, first_ts: 1, parent_session_id: null, event_count: 1, error_count: 0 },
  { id: 's3', agent: 'claude', title: 's3t', turns: 1, last_seq: 1, last_ts: 1, first_ts: 1, parent_session_id: null, event_count: 1, error_count: 0 },
]

function summary(id: string, memberCount = 0, members: EvaluationSummary['members'] = []): EvaluationSummary {
  return { evaluation_id: id, title: id, deleted: false, member_count: memberCount, members }
}

function detail(id: string, members: EvaluationDetail['members'] = []): EvaluationDetail {
  return { evaluation_id: id, title: id, deleted: false, member_count: members.length, members }
}

function history(events: EvaluationHistoryEntry['event'][]): EvaluationHistoryEntry[] {
  return events.map((event, i) => ({ seq: i + 1, event }))
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  cleanup()
})

describe('useEvaluations', () => {
  it('loads history alongside the selected detail and preserves API errors', async () => {
    vi.spyOn(api, 'evaluations').mockResolvedValue({
      evaluations: [
        summary('e1', 1, [{ session_id: 's1', task_label: 't1' }]),
        summary('e2', 0),
      ],
    })
    vi.spyOn(api, 'evaluation').mockImplementation(async (id: string) => detail(id))
    vi.spyOn(api, 'evaluationHistory').mockResolvedValue({
      ok: true,
      evaluation_id: 'e1',
      events: history([
        { type: 'evaluation.created', ts: 1, payload: { title: 'e1' } },
        { type: 'evaluation.session.added', ts: 2, payload: { session_id: 's1', task_label: 't1' } },
      ]),
    })

    const { result } = renderHook(() => useEvaluations(sessions))

    await waitFor(() => expect(result.current.current?.evaluation_id).toBe('e1'))
    expect(result.current.history.map((e) => e.seq)).toEqual([1, 2])
    expect(result.current.error).toBeNull()

    // 写失败必须 reject 并把后端原始 message 透出，不在 hook 内吞掉。
    vi.spyOn(api, 'addEvaluationSession').mockRejectedValue(new Error('session already in another evaluation'))
    await expect(
      result.current.addSession('e1', 's2', 't'),
    ).rejects.toThrow('session already in another evaluation')
  })

  it('drops in-flight detail when select races ahead of a slower response (epoch guard)', async () => {
    const resolvers: Array<() => void> = []
    vi.spyOn(api, 'evaluations').mockResolvedValue({
      evaluations: [summary('e1', 0), summary('e2', 0)],
    })
    // 把 evaluation 与 evaluationHistory 都卡住，避免任一先 resolve 污染 state。
    let pendingDetail = 0
    let pendingHistory = 0
    vi.spyOn(api, 'evaluation').mockImplementation(async (id: string) => {
      pendingDetail += 1
      await new Promise<void>((resolve) => { resolvers.push(resolve); pendingDetail = id === 'e1' ? 1 : 2 })
      return detail(id)
    })
    vi.spyOn(api, 'evaluationHistory').mockImplementation(async (id: string) => {
      pendingHistory += 1
      await new Promise<void>((resolve) => { resolvers.push(resolve); pendingHistory = id === 'e1' ? 1 : 2 })
      return { ok: true, evaluation_id: id, events: history([{ type: 'evaluation.created', ts: 1, payload: { title: id } }]) }
    })

    const { result } = renderHook(() => useEvaluations(sessions))
    // 初次 reload 一定会拉一次 e1；这里只关心「select e2 后 e1 后到会不会污染」。
    await waitFor(() => expect(resolvers.length).toBeGreaterThanOrEqual(2))
    const initialCalls = resolvers.length
    // select 会等待 e2 的 detail/history；先启动而不 await，避免测试自身把它卡住。
    let selectPromise!: Promise<void>
    act(() => { selectPromise = result.current.select('e2') })
    await waitFor(() => expect(resolvers.length).toBeGreaterThanOrEqual(initialCalls + 2))
    // 先让初次 reload 的 e1 过期，再放行 e2。
    for (let i = 0; i < initialCalls; i += 1) resolvers[i]?.()
    for (let i = initialCalls; i < resolvers.length; i += 1) resolvers[i]?.()
    await act(async () => { await selectPromise })
    await waitFor(() => expect(result.current.current?.evaluation_id).toBe('e2'))
    expect(result.current.history.find((e) => e.event.payload.title === 'e2')).toBeTruthy()
  })

  it('exposes availableSessions excluding current members and other active members', async () => {
    vi.spyOn(api, 'evaluations').mockResolvedValue({
      evaluations: [
        // e1 当前选中：成员 s1
        summary('e1', 1, [{ session_id: 's1', task_label: '' }]),
        // e2 active：成员 s2（应被 availableSessions 排除）
        summary('e2', 1, [{ session_id: 's2', task_label: '' }]),
      ],
    })
    vi.spyOn(api, 'evaluation').mockImplementation(async (id: string) =>
      id === 'e1' ? detail('e1', [{ session_id: 's1', task_label: '' }]) : detail('e2', [{ session_id: 's2', task_label: '' }]),
    )
    vi.spyOn(api, 'evaluationHistory').mockResolvedValue({ ok: true, evaluation_id: 'e1', events: [] })

    const { result } = renderHook(() => useEvaluations(sessions))
    await waitFor(() => expect(result.current.current?.evaluation_id).toBe('e1'))
    // s1 在当前成员、s2 在其他 active 成员——都应被剔除，只剩 s3
    expect(result.current.availableSessions.map((s) => s.id)).toEqual(['s3'])
  })

  it('create selects the new evaluation via pendingSelect, not a flicker through null', async () => {
    vi.spyOn(api, 'evaluations').mockResolvedValue({ evaluations: [] })
    vi.spyOn(api, 'evaluation').mockResolvedValue(detail('e-new'))
    vi.spyOn(api, 'evaluationHistory').mockResolvedValue({ ok: true, evaluation_id: 'e-new', events: [] })
    vi.spyOn(api, 'createEvaluation').mockResolvedValue({ ok: true, evaluation_id: 'e-new' })

    const { result } = renderHook(() => useEvaluations(sessions))
    await waitFor(() => expect(result.current.loading).toBe(false))
    await act(async () => { await result.current.create('new') })
    await waitFor(() => expect(result.current.selectedId).toBe('e-new'))
  })

  it('surfaces error from loadList when backend is unreachable', async () => {
    vi.spyOn(api, 'evaluations').mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useEvaluations(sessions))
    await waitFor(() => expect(result.current.error).toBe('boom'))
    expect(result.current.current).toBeNull()
  })
})
