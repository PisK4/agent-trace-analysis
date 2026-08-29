// Session 级 Run navigator：列出当前 Session 真实存在的 Run，让用户切换
// canonical identity 视角。Run 来源唯一是后端 `/api/sessions/{sid}/runs`，
// 前端不根据 rows 推 Run；observed（run_id=null）行不当作 Run，单独计数说明。
import type { RunInfo } from '../../api/types'

interface Props {
  runs: RunInfo[]
  selectedRunId: number | null
  onSelect: (id: number | null) => void
  runlessTurnCount: number
  loading: boolean
  error: string | null
}

const STATUS_LABEL: Record<RunInfo['status'], string> = {
  open: 'open',
  ended: 'ended',
  incomplete: 'incomplete',
}

export function RunPanel({ runs, selectedRunId, onSelect, runlessTurnCount, loading, error }: Props) {
  return (
    <div className="run-panel" role="group" aria-label="Run navigator">
      {error ? (
        <div className="run-panel-error" role="alert">Run 加载失败：{error}</div>
      ) : null}
      {loading && !error && runs.length === 0 ? (
        <div className="run-panel-hint">正在加载 Run…</div>
      ) : null}
      <div className="run-panel-list" role="list">
        <button
          type="button"
          role="listitem"
          className="run-chip"
          aria-pressed={selectedRunId == null}
          onClick={() => onSelect(null)}
          title="显示全部 Runs 与 runless observed 行"
        >
          <span className="run-id">全部 Runs</span>
          <span className="run-meta">{runs.length} 个 Run</span>
        </button>
        {runs.map((run) => {
          const selected = run.run_id === selectedRunId
          const conflictText = run.conflict_count > 0
            ? `${run.conflict_count} conflict${run.conflict_count === 1 ? '' : 's'}`
            : 'no conflict'
          return (
            <button
              key={run.run_id}
              type="button"
              role="listitem"
              className="run-chip"
              data-status={run.status}
              aria-pressed={selected}
              onClick={() => onSelect(run.run_id)}
              title={`R${run.run_id} · ${STATUS_LABEL[run.status]} · ${conflictText}`}
            >
              <span className="run-id">R{run.run_id}</span>
              <span className={`run-status run-status-${run.status}`}>{STATUS_LABEL[run.status]}</span>
              <span className="run-conflicts">{conflictText}</span>
            </button>
          )
        })}
      </div>
      {runs.length === 0 && !loading && !error ? (
        <div className="run-panel-hint">暂无明确 lifecycle Run；只有 Observed 行可显示</div>
      ) : null}
      {runlessTurnCount > 0 ? (
        <div className="run-panel-hint" data-testid="runless-hint">
          {runlessTurnCount} 行无 Run（显示为 Observed {runlessTurnCount > 1 ? '序列' : '序列'}）
        </div>
      ) : null}
    </div>
  )
}
