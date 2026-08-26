import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSession } from './useSession'
import type { SessionPage } from './types'

function page(rev: number, text: string): SessionPage {
  return {
    id: 's1', agent: 'pi', title: 't', crumb: 'c', has_older: false,
    cursor: 3, turns: 1, scores: [], tools_index: {},
    rows: [{
      id: 'r1', _seq: rev, index: 0, turn: 1, kind: 'user', tag: 'USER',
      text, startedAt: 1000, durationMs: 0, status: 'completed',
      usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
    }],
    rev,
  }
}

const sessionFetch = (bodies: unknown[]) => {
  const calls: string[] = []
  const queue = [...bodies]
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input))
    return new Response(JSON.stringify(queue.shift() ?? { ok: true, unchanged: true, rev: 99 }), {
      status: 200, headers: { 'content-type': 'application/json' },
    })
  }))
  return calls
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useSession', () => {
  it('loads full page then polls with rev and skips unchanged ticks', async () => {
    const full = page(5, 'v1')
    const calls = sessionFetch([full])
    const { unmount } = renderHook(() => useSession('s1'))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(calls[0]).toBe('/api/sessions/s1')
    const afterBaseline = calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(calls.length).toBeGreaterThan(afterBaseline)
    expect(calls[calls.length - 1]).toBe('/api/sessions/s1?rev=5')
    // 之后持续按节拍轮询且全部带 rev；stub 恒回 unchanged，不再出现整页
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(calls.every((c, i) => i === 0 || c.includes('rev='))).toBe(true)
    unmount()
  })

  it('applies changed page and updates rev baseline', async () => {
    const calls = sessionFetch([page(5, 'v1'), page(6, 'v2')])
    const { result } = renderHook(() => useSession('s1'))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(result.current.data?.rows[0].text).toBe('v2')
    expect(result.current.data?.rev).toBe(6)
    // 第二拍用的还是旧基线 rev=5
    expect(calls.some((c) => c.includes('rev=5'))).toBe(true)
  })

  it('backs off after a failed poll and recovers afterwards', async () => {
    let fail = true
    vi.stubGlobal('fetch', vi.fn(async () => {
      if (fail) throw new TypeError('network down')
      return new Response(JSON.stringify(page(7, 'ok')), { status: 200 })
    }))
    const { result } = renderHook(() => useSession('s1'))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.error).toBeTruthy()
    const fetchMock = vi.mocked(globalThis.fetch)
    const nFailed = fetchMock.mock.calls.length
    // 退避窗口中段：不重试
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(fetchMock.mock.calls.length).toBe(nFailed)
    // 退避到点后重试成功
    fail = false
    await act(async () => { await vi.advanceTimersByTimeAsync(2500) })
    expect(fetchMock.mock.calls.length).toBe(nFailed + 1)
    expect(result.current.error).toBeNull()
    expect(result.current.data?.rows[0].text).toBe('ok')
  })

  it('drops in-flight response when session changes mid-await (epoch guard)', async () => {
    // 每个请求一个独立 deferred，避免单槽位被后续请求覆盖
    const resolvers: Array<(r: Response) => void> = []
    vi.stubGlobal('fetch', vi.fn(() =>
      new Promise<Response>((resolve) => { resolvers.push(resolve) })))
    const { result, rerender } = renderHook(({ sid }) => useSession(sid), {
      initialProps: { sid: 's1' as string | null },
    })
    await act(async () => { await Promise.resolve() })
    expect(resolvers.length).toBe(1)
    // 换会话：旧请求还在路上
    rerender({ sid: 's2' })
    await act(async () => { await Promise.resolve() })
    expect(resolvers.length).toBe(2)
    // 迟到的 s1 响应必须被丢弃，不能落进 s2 的数据
    resolvers[0](new Response(JSON.stringify(page(9, 'stale')), { status: 200 }))
    await act(async () => { await Promise.resolve() })
    expect(result.current.data?.rows[0]?.text).not.toBe('stale')
    // s2 自己的响应正常落地
    resolvers[1](new Response(JSON.stringify({ ...page(3, 'fresh'), id: 's2' }), { status: 200 }))
    await act(async () => { await Promise.resolve() })
    expect(result.current.data?.rows[0]?.text).toBe('fresh')
  })

  it('stops polling for null id', async () => {
    const calls = sessionFetch([])
    renderHook(() => useSession(null))
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(calls).toHaveLength(0)
  })
})
