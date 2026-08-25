// 工具调用统计面板：Badge 常驻 + 弹出明细表，点行跳转轨迹。
import { useMemo, useState } from 'react'
import type { ProjectedRow } from '../../api/types'
import { fmtNum } from '../../lib/format'
import { toolStats } from './stats'

export function StatsBadges({ rows, onJump }: { rows: ProjectedRow[]; onJump: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const { tools, totalCalls, totalFailed } = useMemo(() => toolStats(rows), [rows])

  return (
    <span className="popwrap">
      <button
        type="button"
        className="stat-badge"
        aria-expanded={open}
        title="工具调用统计"
        onClick={() => setOpen(!open)}
      >
        <b>Σ {fmtNum(totalCalls)} calls</b>
        {totalFailed > 0 ? <b className="bad">⚠ {totalFailed}</b> : null}
      </button>
      {open && (
        <div className="pop">
          <div className="pop-title">工具调用统计</div>
          <div className="dtable">
            <div className="dhead"><span className="h-tool">Tool</span><span className="h-n">Calls</span><span className="h-n">Failed</span></div>
            {tools.map((t) => (
              <button
                key={t.name}
                type="button"
                className="dist-row"
                disabled={!t.failedIds.length}
                title={t.failedIds.length ? '点击按时间顺序展开每次调用' : undefined}
                onClick={() => {
                  if (t.failedIds.length) onJump(t.failedIds[0])
                  setOpen(false)
                }}
              >
                <span className="h-tool">{t.name}</span>
                <span className="h-n">{t.calls}</span>
                <span className={`h-n ${t.failed ? 'bad' : ''}`}>{t.failed || ''}</span>
              </button>
            ))}
            {!tools.length && <div className="hint">窗口内没有工具调用</div>}
          </div>
          <div className="hint">按失败数 → 调用数降序 · 点击行跳到首个失败调用</div>
        </div>
      )}
    </span>
  )
}
