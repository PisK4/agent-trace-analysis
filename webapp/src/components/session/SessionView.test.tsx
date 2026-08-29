// SessionView 集成：选 Run 后表格只显示该 Run 行；换「全部」恢复 observed 行；
// 跳到 R2·T1 不命中 R1·T1；TopBar 显示 Runs 计数 + 冲突摘要。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionView } from './SessionView'
import type { ProjectedRow, SessionPage } from '../../api/types'

const SESSION_ROWS: ProjectedRow[] = [
  // R1 · T1
  {
    id: 'r1t1u', _seq: 1, index: 0, turn: 1, run_id: 1, turn_number: 1, observed_turn_ordinal: null,
    kind: 'user', tag: 'USER', text: 'r1u', startedAt: 1000, durationMs: 0, status: 'completed', start: true,
    usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
  },
  {
    id: 'r1t1a', _seq: 2, index: 1, turn: 1, run_id: 1, turn_number: 1, observed_turn_ordinal: null,
    kind: 'assistant', tag: 'ASSISTANT', text: 'r1a', startedAt: 1100, durationMs: 0, status: 'completed',
    usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
  },
  // R2 · T1
  {
    id: 'r2t1u', _seq: 10, index: 2, turn: 2, run_id: 2, turn_number: 1, observed_turn_ordinal: null,
    kind: 'user', tag: 'USER', text: 'r2u', startedAt: 2000, durationMs: 0, status: 'completed', start: true,
    usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
  },
  {
    id: 'r2t1a', _seq: 11, index: 3, turn: 2, run_id: 2, turn_number: 1, observed_turn_ordinal: null,
    kind: 'assistant', tag: 'ASSISTANT', text: 'r2a', startedAt: 2100, durationMs: 0, status: 'completed',
    usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
  },
  // observed 行
  {
    id: 'obs1', _seq: 20, index: 4, turn: 3, run_id: null, turn_number: null, observed_turn_ordinal: 1,
    kind: 'system', tag: 'SYSTEM', text: 'orphan', startedAt: 3000, durationMs: 0, status: 'completed',
    usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
  },
]

const SESSION_PAGE: SessionPage = {
  id: 's1', agent: 'pi', title: 'sess', crumb: 'pi · sess', has_older: false,
  cursor: 0, turns: 2, scores: [], tools_index: {},
  rows: SESSION_ROWS, rev: 1,
}

const RUNS_PAGE = {
  ok: true,
  runs: [
    { run_id: 1, external_lifecycle_id: null, status: 'ended', started_seq: 1, ended_seq: 5, started_ts: 1, ended_ts: 2, max_turn_number: 1, conflict_count: 0 },
    { run_id: 2, external_lifecycle_id: null, status: 'open', started_seq: 10, ended_seq: null, started_ts: 3, ended_ts: null, max_turn_number: 1, conflict_count: 2 },
  ],
}

function mockFetchSuccess() {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    let body: unknown
    if (path.includes('/runs')) body = RUNS_PAGE
    else if (path.includes('/usage')) body = {
      ok: true,
      turns: [],
      total: { input: 0, output: 0, cache_read: 0, cache_write: 0, total_tokens: 0 },
      missing_turns: 0,
      audit: { findings: [], reported_turns: 0, expected_turns: 0 },
      compactions: [],
    }
    else if (path.includes('/timing')) body = {
      ok: true,
      span_ms: 0, first_ts: null, last_ts: null,
      turns: 0, steps: 0, calls: 0,
      llm_ms: 0, tool_ms: 0, other_ms: 0,
      llm_quality: 'n/a', tool_quality: 'n/a',
      per_turn: [],
    }
    else body = SESSION_PAGE
    return { ok: true, status: 200, json: async () => body } as Response
  }))
}

beforeEach(() => {
  // SessionTable 用 ResizeObserver 监听滚动容器
  ;(globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  // useSession 默认 1s 轮询，测试不挂 fake timer，让它跑真实 setTimeout；
  // afterEach 全部 unmount 后不会留 in-flight 链。
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('SessionView', () => {
  it('loads session + runs, lets user switch runs without identity collision', async () => {
    mockFetchSuccess()
    render(<SessionView sessionId="s1" />)
    // 第一次跑：fetch 异步落地
    await waitFor(() => expect(screen.getByText('R1')).toBeInTheDocument(), { timeout: 3000 })
    // TopBar Runs 徽章：精确锁定到 .stat-badge 区域
    const runBadges = document.querySelectorAll('.stat-badge')
    const runsBadge = Array.from(runBadges).find((el) => el.textContent?.includes('Runs') && el.textContent?.includes('Turns'))
    expect(runsBadge).toBeTruthy()
    expect(runsBadge!.textContent).toMatch(/2/)
    // 冲突摘要（2 个冲突）
    expect(screen.getByTestId('conflict-count').textContent).toMatch(/2/)
    // 全部视图下所有行都能搜到（包括 Observed）
    expect(screen.getByText('r1u')).toBeInTheDocument()
    expect(screen.getByText('r2u')).toBeInTheDocument()
    expect(screen.getByText('orphan')).toBeInTheDocument()

    // 切到 R2：r1u 消失，r2u 仍可见，observed 不再出现
    fireEvent.click(screen.getByText('R2'))
    await waitFor(() => expect(screen.queryByText('r1u')).toBeNull(), { timeout: 3000 })
    expect(screen.getByText('r2u')).toBeInTheDocument()
    expect(screen.getByText('r2a')).toBeInTheDocument()
    expect(screen.queryByText('orphan')).toBeNull()
    // TopBar 显示 R2 选中态
    expect(screen.getByText('R2').closest('button')!.getAttribute('aria-pressed')).toBe('true')
    // 切回「全部 Runs」恢复 observed
    fireEvent.click(screen.getByText('全部 Runs'))
    await waitFor(() => expect(screen.getByText('orphan')).toBeInTheDocument(), { timeout: 3000 })
    expect(screen.getByText('r1u')).toBeInTheDocument()
  })

  it('reflects selected run id in TopBar badge', async () => {
    mockFetchSuccess()
    render(<SessionView sessionId="s1" />)
    await waitFor(() => expect(screen.getByText('R1')).toBeInTheDocument(), { timeout: 3000 })
    fireEvent.click(screen.getByText('R1'))
    // TopBar 的 Runs 徽章出现 `· R1` 标记
    await waitFor(() => {
      const runBadges = document.querySelectorAll('.stat-badge')
      const runsBadge = Array.from(runBadges).find((el) => el.textContent?.includes('Runs') && el.textContent?.includes('Turns'))
      expect(runsBadge?.textContent).toMatch(/·\s*R1/)
    }, { timeout: 3000 })
  })
})
