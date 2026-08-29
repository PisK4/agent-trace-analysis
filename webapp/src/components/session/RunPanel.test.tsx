// RunPanel：选 Run / 取消选 / 展示 status · conflict · runless 提示。
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunPanel } from './RunPanel'
import type { RunInfo } from '../../api/types'

const BASE_RUNS: RunInfo[] = [
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
]

afterEach(cleanup)

describe('RunPanel', () => {
  it('lists every run with status, conflict and 全部入口', () => {
    const onSelect = vi.fn()
    render(
      <RunPanel
        runs={BASE_RUNS}
        selectedRunId={null}
        onSelect={onSelect}
        runlessTurnCount={0}
        loading={false}
        error={null}
      />,
    )
    expect(screen.getByText('全部 Runs')).toBeInTheDocument()
    expect(screen.getByText('R1')).toBeInTheDocument()
    expect(screen.getByText('ended')).toBeInTheDocument()
    expect(screen.getByText('no conflict')).toBeInTheDocument()
  })

  it('shows lifecycle state, conflicts, and runless notice', () => {
    const runs: RunInfo[] = [{
      run_id: 2,
      external_lifecycle_id: null,
      status: 'incomplete',
      started_seq: 1,
      ended_seq: null,
      started_ts: 1,
      ended_ts: null,
      max_turn_number: 3,
      conflict_count: 2,
    }]
    render(
      <RunPanel
        runs={runs}
        selectedRunId={2}
        onSelect={vi.fn()}
        runlessTurnCount={1}
        loading={false}
        error={null}
      />,
    )
    expect(screen.getByText('R2')).toBeInTheDocument()
    expect(screen.getByText('incomplete')).toBeInTheDocument()
    expect(screen.getByText('2 conflicts')).toBeInTheDocument()
    expect(screen.getByTestId('runless-hint').textContent).toMatch(/Observed|无 Run/)
  })

  it('emits onSelect with run id and 全部 entries', () => {
    const onSelect = vi.fn()
    render(
      <RunPanel
        runs={BASE_RUNS}
        selectedRunId={null}
        onSelect={onSelect}
        runlessTurnCount={0}
        loading={false}
        error={null}
      />,
    )
    fireEvent.click(screen.getByText('R1'))
    expect(onSelect).toHaveBeenCalledWith(1)
    fireEvent.click(screen.getByText('全部 Runs'))
    expect(onSelect).toHaveBeenCalledWith(null)
  })

  it('reflects selection via aria-pressed', () => {
    render(
      <RunPanel
        runs={BASE_RUNS}
        selectedRunId={1}
        onSelect={vi.fn()}
        runlessTurnCount={0}
        loading={false}
        error={null}
      />,
    )
    expect(screen.getByText('R1').closest('button')!.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText('全部 Runs').closest('button')!.getAttribute('aria-pressed')).toBe('false')
  })

  it('renders error banner when api fails', () => {
    render(
      <RunPanel
        runs={[]}
        selectedRunId={null}
        onSelect={vi.fn()}
        runlessTurnCount={0}
        loading={false}
        error={'500 boom'}
      />,
    )
    expect(screen.getByRole('alert').textContent).toMatch(/Run 加载失败.*500 boom/)
  })

  it('shows empty hint when no runs are returned', () => {
    render(
      <RunPanel
        runs={[]}
        selectedRunId={null}
        onSelect={vi.fn()}
        runlessTurnCount={0}
        loading={false}
        error={null}
      />,
    )
    expect(screen.getByText(/暂无明确 lifecycle Run/)).toBeInTheDocument()
  })
})
