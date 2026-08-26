// 会话时间拆解徽章（DSH 统计栏同思路）：墙钟里 LLM 生成 vs 工具执行各占多少。
// 全量数据来自 /timing 端点（不受前端尾窗分页限制），与 Usage 徽章同款懒加载。
import { useEffect, useRef, useState } from 'react'
import type { TimingSummary } from '../../api/types'
import { useSummary } from '../../api/useSummary'
import { fmtDur, fmtDurQ, QUALITY_LABEL } from '../../lib/timing'

interface Props {
  sessionId: string
  onJumpTurn: (turn: number) => void
}

export function TimeBadge({ sessionId, onJumpTurn }: Props) {
  const { data } = useSummary<TimingSummary>(
    sessionId ? `/api/sessions/${encodeURIComponent(sessionId)}/timing` : null,
  )
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLSpanElement>(null)

  // 点外面收起（与 StatsBadges 弹层同策略）
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  if (!data) return null
  // LLM/工具全未测量时徽章只显墙钟——「0 ms · 0 ms」会被读成实测零毫秒
  const anyMeasured = data.llm_quality === 'measured' || data.tool_quality === 'measured'
  return (
    <span className="popwrap" ref={wrapRef}>
      <button
        type="button"
        className="stat-badge"
        aria-expanded={open}
        title="时间拆解：LLM 生成 vs 工具执行"
        onClick={() => setOpen(!open)}
      >
        <b>⏱ {anyMeasured ? `${fmtDurQ(data.llm_ms, data.llm_quality)} · ${fmtDurQ(data.tool_ms, data.tool_quality)}` : fmtDur(data.span_ms)}</b>
      </button>
      {open && (
        <div className="pop timing-pop">
          <div className="pop-title">时间拆解</div>
          <dl className="timing-kv">
            <div><dt>墙钟</dt><dd>{fmtDur(data.span_ms)} · {data.steps} 步 · {data.turns} 轮</dd></div>
            <div><dt>LLM</dt><dd>{fmtDurQ(data.llm_ms, data.llm_quality)} <span className="q">{QUALITY_LABEL[data.llm_quality]}</span></dd></div>
            <div><dt>工具</dt><dd>{fmtDurQ(data.tool_ms, data.tool_quality)} <span className="q">{QUALITY_LABEL[data.tool_quality]}</span></dd></div>
            <div><dt>等待/其他</dt><dd>{fmtDur(data.other_ms)}</dd></div>
          </dl>
          {data.per_turn.length > 0 && (
            <div className="dtable">
              <div className="dhead"><span className="h-tool">Turn</span><span className="h-n">LLM</span><span className="h-n">Tools</span></div>
              {data.per_turn.map((t) => (
                <button
                  key={t.turn}
                  type="button"
                  className="crow"
                  onClick={() => { onJumpTurn(t.turn); setOpen(false) }}
                >
                  <span className="ct">T{t.turn}</span>
                  <span className="cd">{fmtDurQ(t.llm_ms, data.llm_quality)}</span>
                  <span className="cd">{fmtDurQ(t.tool_ms, data.tool_quality)}</span>
                  <span className="cx">{t.steps} 步 · {t.calls} 次调用</span>
                </button>
              ))}
            </div>
          )}
          <div className="hint">— 表示来源不带耗时（未测量）；实测项按真实毫秒显示</div>
        </div>
      )}
    </span>
  )
}
