// 工具调用统计面板：Badge 常驻 + 弹出明细表（可钻取单工具调用序列），点行跳转。
// DOM 结构与类名对齐旧版 web/js/stats.js（.dtable/.drow/.dname/.dnum + .drill/.crow）。
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ProjectedRow } from '../../api/types'
import { clock, durLabel } from '../../lib/inspectorModel'
import { fmtNum } from '../../lib/format'
import { toolStats } from './stats'

// 钻取每次展开的调用条数（旧版 TDRILL_BATCH）
const TDRILL_BATCH = 8

export function StatsBadges({ rows, onJump }: { rows: ProjectedRow[]; onJump: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [shown, setShown] = useState<Record<string, number>>({})
  const { tools, totalCalls, totalFailed } = useMemo(() => toolStats(rows), [rows])
  const wrapRef = useRef<HTMLSpanElement>(null)

  // 点外面收起（与 TopBar 弹层同策略）
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const jumpTo = (id: string) => {
    onJump(id)
    setOpen(false)
  }

  return (
    <span className="popwrap" ref={wrapRef}>
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
        <div className="pop stats-pop">
          <div className="pop-title">工具调用统计</div>
          <div className="dtable">
            <div className="dhead"><span className="h-tool">Tool</span><span className="h-n">Calls</span><span className="h-n">Failed</span></div>
            {tools.map((t) => {
              const isOpen = expanded === t.name
              const batch = shown[t.name] ?? TDRILL_BATCH
              // 钻取按行序即时间序（rows 本身升序），与旧版 started_at 升序同义
              const calls = rows.filter((r) => (r.kind === 'tool' || r.kind === 'subtool') && r.name === t.name)
              const drillCalls = isOpen ? calls.slice(0, batch) : []
              return (
                <div key={t.name} className="drow-wrap">
                  <button
                    type="button"
                    className="drow"
                    aria-expanded={isOpen}
                    onClick={() => setExpanded(isOpen ? null : t.name)}
                  >
                    <span className="dname" title={t.name}>{t.name}</span>
                    <span className="dnum">{t.calls}</span>
                    <span className={`dnum ${t.failed ? 'bad' : 'mute'}`}>{t.failed || ''}</span>
                  </button>
                  {isOpen && (
                    <div className="drill">
                      {drillCalls.map((c) => (
                        <button key={c.id} type="button" className="crow" onClick={() => jumpTo(c.id)}>
                          <i className={`dot ${c.status === 'failed' ? 'fail' : c.status === 'pending' ? 'wait' : 'ok'}`} />
                          <span className="ct">{clock(c.startedAt)}</span>
                          <span className="cd">{c.durationMs != null ? durLabel(c.durationMs) : '—'}</span>
                          <span className="cx">{(c.text || '').replace(/\s+/g, ' ').trim().slice(0, 120) || <span className="dim">(no input preview)</span>}</span>
                        </button>
                      ))}
                      {calls.length > batch && (
                        <button
                          type="button"
                          className="more"
                          onClick={() => setShown((prev) => ({ ...prev, [t.name]: batch + TDRILL_BATCH }))}
                        >
                          show more ({calls.length - batch} left)
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
            {!tools.length && <div className="hint">窗口内没有工具调用</div>}
          </div>
          <div className="hint">按失败数 → 调用数降序 · 点击工具行展开每次调用 · 点击调用跳转轨迹</div>
        </div>
      )}
    </span>
  )
}
