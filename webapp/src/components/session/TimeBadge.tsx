// 会话时间拆解徽章（DSH 统计栏同思路）：墙钟里 LLM 生成 vs 工具执行各占多少。
// 全量数据来自 /timing 端点（不受前端尾窗分页限制），与 Usage 徽章同款懒加载。
import { useEffect, useRef, useState } from 'react'
import type { TimingSummary } from '../../api/types'
import { api } from '../../api/client'
import { fmtDur, QUALITY_LABEL } from '../../lib/timing'

interface Props {
  sessionId: string
  onJumpTurn: (turn: number) => void
}

export function TimeBadge({ sessionId, onJumpTurn }: Props) {
  // dataFor 记录 data 归属的会话：换会话的过渡期渲染期直接判 null，
  // 不在 effect 里同步置空（避免级联 render，lint 同款告警在 UsagePanel 已有先例）
  const [state, setState] = useState<{ dataFor: string; data: TimingSummary | null }>({ dataFor: '', data: null })
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    let alive = true
    api.timing(sessionId)
      .then((d) => { if (alive) setState({ dataFor: sessionId, data: d }) })
      .catch(() => { if (alive) setState({ dataFor: sessionId, data: null }) })
    return () => { alive = false }
  }, [sessionId])

  const data = state.dataFor === sessionId ? state.data : null

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
  return (
    <span className="popwrap" ref={wrapRef}>
      <button
        type="button"
        className="stat-badge"
        aria-expanded={open}
        title="时间拆解：LLM 生成 vs 工具执行"
        onClick={() => setOpen(!open)}
      >
        <b>⏱ {fmtDur(data.llm_ms)} · {fmtDur(data.tool_ms)}</b>
      </button>
      {open && (
        <div className="pop timing-pop">
          <div className="pop-title">时间拆解</div>
          <dl className="timing-kv">
            <div><dt>墙钟</dt><dd>{fmtDur(data.span_ms)} · {data.steps} 步 · {data.turns} 轮</dd></div>
            <div><dt>LLM</dt><dd>{fmtDur(data.llm_ms)} <span className="q">{QUALITY_LABEL[data.llm_quality]}</span></dd></div>
            <div><dt>工具</dt><dd>{fmtDur(data.tool_ms)} <span className="q">{QUALITY_LABEL[data.tool_quality]}</span></dd></div>
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
                  <span className="cd">{fmtDur(t.llm_ms)}</span>
                  <span className="cd">{fmtDur(t.tool_ms)}</span>
                  <span className="cx">{t.steps} 步 · {t.calls} 次调用</span>
                </button>
              ))}
            </div>
          )}
          <div className="hint">Claude/Codex/Droid 的转录不带耗时，对应项标为占位值，只看相对量纲</div>
        </div>
      )}
    </span>
  )
}
