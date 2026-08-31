import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { EvaluationView } from './EvaluationView'
import type {
  EvaluationDetail, EvaluationHistoryEntry, EvaluationSummary, SessionMeta,
} from '../../api/types'
import { ToastProvider } from '../ToastProvider'

const sessions: SessionMeta[] = [
  { id: 's-good', agent: 'pi', title: 'good-session', turns: 1, last_seq: 1, last_ts: 1, first_ts: 1, parent_session_id: null, event_count: 1, error_count: 0 },
  { id: 's-bad', agent: 'pi', title: 'bad-session', turns: 1, last_seq: 1, last_ts: 1, first_ts: 1, parent_session_id: null, event_count: 1, error_count: 2 },
  { id: 's-mid', agent: 'claude', title: 'partial-session', turns: 1, last_seq: 1, last_ts: 1, first_ts: 1, parent_session_id: null, event_count: 1, error_count: 0 },
  { id: 's-unrated', agent: 'claude', title: 'unrated-session', turns: 1, last_seq: 1, last_ts: 1, first_ts: 1, parent_session_id: null, event_count: 1, error_count: 0 },
]

function summary(id: string, members: EvaluationSummary['members'] = []): EvaluationSummary {
  return { evaluation_id: id, title: id, deleted: false, member_count: members.length, members }
}

function detail(id: string, members: EvaluationDetail['members']): EvaluationDetail {
  return { evaluation_id: id, title: id, deleted: false, member_count: members.length, members }
}

function hist(events: EvaluationHistoryEntry['event'][]): EvaluationHistoryEntry[] {
  return events.map((event, i) => ({ seq: i + 1, event }))
}

const members: EvaluationDetail['members'] = [
  { session_id: 's-good', task_label: 'task-a', title: 'good-session', agent: 'pi', event_count: 1, error_count: 0, score: { value: 'good', note: null, ts: 1 } },
  { session_id: 's-bad', task_label: 'task-a', title: 'bad-session', agent: 'pi', event_count: 1, error_count: 2, score: { value: 'bad', note: 'failed', ts: 2 } },
  { session_id: 's-mid', task_label: 'task-b', title: 'partial-session', agent: 'claude', event_count: 1, error_count: 0, score: { value: 'partial', note: null, ts: 3 } },
  { session_id: 's-unrated', task_label: 'task-b', title: 'unrated-session', agent: 'claude', event_count: 1, error_count: 0 },
]

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'evaluations').mockResolvedValue({
    evaluations: [summary('e1', members)],
  })
  vi.spyOn(api, 'evaluation').mockImplementation(async (id: string) => detail(id, members))
  vi.spyOn(api, 'evaluationHistory').mockResolvedValue({
    ok: true,
    evaluation_id: 'e1',
    events: hist([
      { type: 'evaluation.created', ts: 1, payload: { title: 'e1' } },
      { type: 'evaluation.session.added', ts: 2, payload: { session_id: 's-good', task_label: 'task-a' } },
      { type: 'evaluation.session.added', ts: 3, payload: { session_id: 's-bad', task_label: 'task-a' } },
      { type: 'evaluation.session.added', ts: 4, payload: { session_id: 's-mid', task_label: 'task-b' } },
      { type: 'evaluation.session.added', ts: 5, payload: { session_id: 's-unrated', task_label: 'task-b' } },
    ]),
  })
})

afterEach(() => {
  cleanup()
})

function renderView() {
  return render(
    <ToastProvider>
      <EvaluationView sessions={sessions} onOpenSession={vi.fn()} />
    </ToastProvider>,
  )
}

describe('EvaluationView', () => {
  it('renders Overview/Sessions/History tabs and shows score distribution', async () => {
    renderView()
    expect(await screen.findByRole('button', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sessions' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'History' })).toBeInTheDocument()
    // good 1 / bad 1 / partial 1 / unrated 1 / failed 1(s-bad)
    expect(screen.getByText('总成员')).toBeInTheDocument()
    const overview = screen.getByLabelText('概览')
    expect(within(overview).getAllByText('1', { selector: 'b' })).toHaveLength(5)
  })

  it('History tab lists fact types and safe summary without real body', async () => {
    renderView()
    fireEvent.click(await screen.findByRole('button', { name: 'History' }))
    // 5 条 history entries
    const history = await screen.findByLabelText('历史')
    const rows = within(history).getAllByRole('listitem')
    expect(rows.length).toBe(5)
    expect(within(history).getAllByText('添加会话')).toHaveLength(4)
    // 安全摘要只渲染已知字段（session_id / task_label / title）
    expect(within(history).getAllByText(/s-good/).length).toBeGreaterThan(0)
    expect(within(history).getAllByText(/task-a/).length).toBeGreaterThan(0)
  })

  it('Sessions tab filters by task label and failed-only', async () => {
    renderView()
    fireEvent.click(await screen.findByRole('button', { name: 'Sessions' }))
    const taskSelect = screen.getAllByRole('combobox')[0]
    fireEvent.change(taskSelect, { target: { value: 'task-a' } })
    // task-a 包含 good-session 与 bad-session
    expect(screen.getByText('good-session')).toBeInTheDocument()
    expect(screen.getByText('bad-session')).toBeInTheDocument()
    expect(screen.queryByText('partial-session')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '仅 failed' }))
    expect(screen.queryByText('good-session')).not.toBeInTheDocument()
    expect(screen.getByText('bad-session')).toBeInTheDocument()
  })

  it('Agent filter narrows members to one agent', async () => {
    renderView()
    fireEvent.click(await screen.findByRole('button', { name: 'Sessions' }))
    // combobox[0]=任务 combobox[1]=Agent
    const agentSelect = screen.getAllByRole('combobox')[1]
    fireEvent.change(agentSelect, { target: { value: 'claude' } })
    expect(screen.queryByText('good-session')).not.toBeInTheDocument()
    expect(screen.getByText('partial-session')).toBeInTheDocument()
  })

  it('addSession error is surfaced inline and form remains open', async () => {
    vi.spyOn(api, 'addEvaluationSession').mockRejectedValue(new Error('session already in another evaluation'))
    vi.spyOn(api, 'evaluation').mockResolvedValue(detail('e1', [members[0]]))
    render(
      <ToastProvider>
        <EvaluationView sessions={[...sessions, { ...sessions[0], id: 's-free', title: 'free-session' }]} onOpenSession={vi.fn()} />
      </ToastProvider>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Sessions' }))
    fireEvent.click(screen.getAllByRole('button', { name: '添加会话' })[0])
    const form = screen.getByRole('form', { name: '添加会话' })
    const submitButton = within(form).getByRole('button', { name: '添加会话' })
    fireEvent.click(submitButton)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('session already in another evaluation')
    // 表单保持打开——用户可立即看到「已填字段」并修正后重试
    expect(screen.getByPlaceholderText('任务标签（可选）')).toBeInTheDocument()
  })
})
