import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nudgeSummaries, useSummary } from './useSummary'

describe('useSummary', () => {
  let fetchCalls: string[]
  beforeEach(() => {
    fetchCalls = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      fetchCalls.push(path)
      return {
        ok: true,
        json: async () => ({ path, n: fetchCalls.length }),
      } as Response
    }))
  })
  // 卸载已挂载的 hook：否则旧消费者的 nudge 监听器残留，会污染后续用例的计数
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('fetches once on mount and exposes data', async () => {
    const { result } = renderHook(() => useSummary<{ n: number }>('/api/sessions/s1/timing'))
    await act(async () => {})
    expect(result.current.data).not.toBeNull()
    expect(fetchCalls).toEqual(['/api/sessions/s1/timing'])
  })

  it('does not fetch when path is null', async () => {
    const { result } = renderHook(() => useSummary<{ n: number }>(null))
    await act(async () => {})
    expect(result.current.data).toBeNull()
    expect(fetchCalls).toEqual([])
  })

  it('path change refetches and stale response is dropped', async () => {
    const { result, rerender } = renderHook(
      ({ sid }: { sid: string }) => useSummary<{ path: string }>(`/api/sessions/${sid}/timing`),
      { initialProps: { sid: 's1' } },
    )
    await act(async () => {})
    rerender({ sid: 's2' })
    await act(async () => {})
    expect(result.current.data?.path).toBe('/api/sessions/s2/timing')
  })

  it('failed fetch sets data null', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 }) as Response))
    const { result } = renderHook(() => useSummary('/x'))
    await act(async () => {})
    expect(result.current.data).toBeNull()
  })

  it('nudge triggers one refetch per consumer', async () => {
    const { result: _result } = renderHook(() => useSummary<{ n: number }>('/t'))
    await act(async () => {})
    const before = fetchCalls.length
    act(() => { nudgeSummaries() })
    await act(async () => {})
    expect(fetchCalls.length).toBe(before + 1)
  })

  it('slow response from previous path is dropped after switch', async () => {
    // 回归：aliveRef 只管挂载生命周期，跨 path 变化仍为 true——旧会话的慢
    // 响应后到会把新会话的数据覆盖掉（旧版 TimeBadge 用 effect 级 alive 防住）。
    let releaseOld!: (v: Response) => void
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path.includes('s1')) {
        return new Promise<Response>((resolve) => { releaseOld = resolve })
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ path }),
      } as Response)
    }))
    const { result, rerender } = renderHook(
      ({ sid }: { sid: string }) => useSummary<{ path: string }>(`/api/sessions/${sid}/usage`),
      { initialProps: { sid: 's1' } },
    )
    rerender({ sid: 's2' })
    await act(async () => {})
    expect(result.current.data?.path).toContain('s2')
    act(() => { releaseOld({ ok: true, json: async () => ({ path: '/old-s1' }) } as Response) })
    await act(async () => {})
    // 慢的旧响应已到，但不得覆盖新会话数据
    expect(result.current.data?.path).toContain('s2')
  })
})
