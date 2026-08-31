// useRuns 的契约：换会话/失败/慢响应三组场景，必须不污染 state。
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useRuns } from './useRuns'

const RUN_FIXTURE = (sid: string) => ({
  ok: true,
  runs: [
    {
      run_id: 1,
      external_lifecycle_id: null,
      status: 'ended',
      started_seq: 1,
      ended_seq: 3,
      started_ts: 1,
      ended_ts: 2,
      max_turn_number: 1,
      conflict_count: 0,
    },
    {
      run_id: 2,
      external_lifecycle_id: null,
      status: 'open',
      started_seq: 4,
      ended_seq: null,
      started_ts: 3,
      ended_ts: null,
      max_turn_number: 2,
      conflict_count: 1,
    },
  ],
  _sid: sid,
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('useRuns', () => {
  it('loads runs and resets selection when session changes', async () => {
    let calls: Array<{ path: string; body: unknown }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const body = path.includes('/s1/runs') ? RUN_FIXTURE('s1') : RUN_FIXTURE('s2')
      calls.push({ path, body })
      return {
        ok: true,
        json: async () => body,
      } as Response
    }))
    const { result, rerender } = renderHook(({ sid }) => useRuns(sid), {
      initialProps: { sid: 's1' as string | null },
    })
    await waitFor(() => expect(result.current.runs).toHaveLength(2))
    expect(result.current.runs[0].run_id).toBe(1)
    act(() => result.current.selectRun(1))
    expect(result.current.selectedRunId).toBe(1)
    rerender({ sid: 's2' })
    await waitFor(() => expect(result.current.selectedRunId).toBeNull())
    // s2 的 runs 也已落进 state（s1 的响应必须被 epoch 守卫丢弃）
    await waitFor(() => expect(result.current.runs).toHaveLength(2))
    expect(calls.some((c) => c.path === '/api/sessions/s2/runs')).toBe(true)
  })

  it('writes HTTP errors to error and keeps runs empty', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 500,
      json: async () => ({ error: 'boom' }),
    }) as Response))
    const { result } = renderHook(() => useRuns('s1'))
    await waitFor(() => expect(result.current.error).toBeTruthy())
    expect(result.current.runs).toEqual([])
    expect(result.current.loading).toBe(false)
  })

  it('refresh re-fetches and updates runs', async () => {
    let n = 0
    vi.stubGlobal('fetch', vi.fn(async () => {
      n += 1
      return { ok: true, json: async () => ({ ok: true, runs: [{ run_id: n, external_lifecycle_id: null, status: 'open', started_seq: 1, ended_seq: null, started_ts: 1, ended_ts: null, max_turn_number: 1, conflict_count: 0 }] }) } as Response
    }))
    const { result } = renderHook(() => useRuns('s1'))
    await waitFor(() => expect(result.current.runs).toHaveLength(1))
    expect(result.current.runs[0].run_id).toBe(1)
    await act(async () => { await result.current.refresh() })
    expect(result.current.runs[0].run_id).toBe(2)
  })

  it('stops loading when sessionId is null', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input))
      return { ok: true, json: async () => ({ ok: true, runs: [] }) } as Response
    }))
    const { result } = renderHook(() => useRuns(null))
    await act(async () => {})
    expect(calls).toHaveLength(0)
    expect(result.current.runs).toEqual([])
    expect(result.current.loading).toBe(false)
  })

  it('drops stale response when session changes mid-await (epoch guard)', async () => {
    const resolvers: Array<(r: Response) => void> = []
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => {
      resolvers.push(resolve)
    })))
    const { result, rerender } = renderHook(({ sid }) => useRuns(sid), {
      initialProps: { sid: 's1' as string | null },
    })
    await act(async () => { await Promise.resolve() })
    expect(resolvers).toHaveLength(1)
    rerender({ sid: 's2' })
    await act(async () => { await Promise.resolve() })
    expect(resolvers).toHaveLength(2)
    // 迟到的 s1 响应不得污染 s2 状态
    resolvers[0](new Response(JSON.stringify(RUN_FIXTURE('s1')), { status: 200 }) as Response)
    await act(async () => { await Promise.resolve() })
    expect(result.current.runs).toEqual([])
    // s2 自己的响应正常落进 state
    resolvers[1](new Response(JSON.stringify(RUN_FIXTURE('s2')), { status: 200 }) as Response)
    await waitFor(() => expect(result.current.runs).toHaveLength(2))
  })
})
