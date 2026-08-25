// Usage 全周期面板：占用/缓存命中率双层曲线 + 体检发现 + 轮级跳转。
// 数据来自 GET /api/sessions/{id}/usage（后端纯派生视图）。
// SVG 绘制语义平移自旧版 web/js/usage.js renderUsagePanel。
import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { UsageSummary, UsageTurn } from '../../api/types'
import { fmtNum } from '../../lib/format'

// 大数缩写（曲线轴帽）：12.3K / 123K，旧版 fmtK
const fmtK = (v: number) => (v >= 10000 ? (v / 1000).toFixed(v >= 100000 ? 0 : 1) + 'K' : String(Math.round(v)))

const RULE_LABEL: Record<string, string> = {
  missing: '缺 usage', placeholder: '占位值', duplicate: '重复嫌疑', cliff: '断崖嫌疑',
}

const W = 840, L = 52, R = 14
const OCC_TOP = 26, OCC_BOT = 150, HIT_TOP = 186, HIT_BOT = 246, H = 262

interface UsageBadgesProps {
  sessionId: string
  /** 面板开态由外层 overview 控制：面板要铺满 overview 宽度，不能嵌在 zone-bar 里 */
  open: boolean
  onToggle: () => void
}

export function UsageBadges({ sessionId, open, onToggle }: UsageBadgesProps) {
  const [data, setData] = useState<UsageSummary | null>(null)

  // epoch 守卫：await 期间换会话即丢弃（与旧版 refreshUsage 同策略）
  useEffect(() => {
    if (!sessionId) return
    let alive = true
    api.usage(sessionId)
      .then((d) => { if (alive) setData(d) })
      .catch(() => { if (alive) setData(null) })
    return () => { alive = false }
  }, [sessionId])

  const total = data?.total
  return (
    <button
      type="button"
      className="stat-badge"
      aria-expanded={open}
      title="Usage 全周期与可信度"
      hidden={!sessionId || !data}
      onClick={onToggle}
    >
      <b>Usage · {data?.audit.reported_turns ?? 0} turns</b>
      {total ? (
        <span>
          {' '}· ↓ {fmtK(total.input)} ↑ {fmtK(total.output)} ↓c {fmtK(total.cache_read)}
        </span>
      ) : null}
    </button>
  )
}

/** 面板本体：挂在 overview 直下的 .panel-wrap 里，绝对定位铺满宽度（旧版同构） */
export function UsagePanel({ sessionId, onJump, open, onClose }: {
  sessionId: string
  onJump: (seq: number) => void
  open: boolean
  onClose: () => void
}) {
  const [data, setData] = useState<UsageSummary | null>(null)
  useEffect(() => {
    if (!sessionId) return
    let alive = true
    api.usage(sessionId)
      .then((d) => { if (alive) setData(d) })
      .catch(() => { if (alive) setData(null) })
    return () => { alive = false }
  }, [sessionId])

  if (!open || !data) return null
  return (
    <div className="panel-wrap">
      <div className="stats-panel">
        <UsagePanelBody
          data={data}
          onJump={(seq) => { onJump(seq); onClose() }}
          onClose={onClose}
        />
      </div>
    </div>
  )
}

function UsagePanelBody({ data, onJump, onClose }: { data: UsageSummary; onJump: (seq: number) => void; onClose: () => void }) {
  const a = data.audit
  const turns = data.turns ?? []
  const maxTurn = Math.max(a.expected_turns, 1)
  const rep = turns.filter((t) => t.status === 'reported')
  const plotW = W - L - R
  const x = (turn: number) => (maxTurn > 1 ? L + plotW * (turn - 1) / (maxTurn - 1) : L + plotW / 2)
  const maxIn = Math.max(1, ...rep.map((t) => t.context || t.input || 0))
  const yIn = (v: number) => OCC_BOT - (OCC_BOT - OCC_TOP) * Math.min(v, maxIn) / maxIn
  const yHit = (r: number) => HIT_BOT - (HIT_BOT - HIT_TOP) * Math.min(r, 100) / 100

  // data 整体 memo：usage 拉一次后引用稳定，按字段拆 memo 反而依赖抖动
  const { byTurn, susp } = useMemo(() => {
    const byT = new Map<number, UsageTurn>()
    for (const t of turns) byT.set(t.turn, t)
    const sp = new Map<number, string>()
    for (const f of a.findings) if (f.rule !== 'missing') sp.set(f.turn, f.rule)
    return { byTurn: byT, susp: sp }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 见上：data 引用即缓存键
  }, [data])

  // 占用曲线在 missing 轮断开，不补线——缺口本身就是信息。
  const segs: string[] = []
  let cur: string[] = []
  for (const t of turns) {
    if (t.status !== 'reported') {
      if (cur.length > 1) segs.push(cur.join(' '))
      cur = []
      continue
    }
    cur.push(`${x(t.turn).toFixed(1)},${yIn(t.context || t.input || 0).toFixed(1)}`)
  }
  if (cur.length > 1) segs.push(cur.join(' '))
  const occArea = rep.length > 1
    ? <polygon points={`${L},${OCC_BOT} ${rep.map((t) => `${x(t.turn).toFixed(1)},${yIn(t.context || t.input || 0).toFixed(1)}`).join(' ')} ${L + plotW},${OCC_BOT}`} className="uc-area" />
    : null
  const occLine = segs.map((s, i) => <polyline key={i} points={s} className="uc-line" />)

  const hitPts = rep.filter((t) => (t.context || 0) > 0 && t.cache_read != null)
  const hitLine = hitPts.length > 1
    ? <polyline points={hitPts.map((t) => `${x(t.turn).toFixed(1)},${yHit((t.cache_read || 0) / (t.context || 1) * 100).toFixed(1)}`).join(' ')} className="uc-hit" />
    : null

  // 命中率最低的一轮，点名让人看见。
  let minHitAnno: React.ReactNode = null
  if (hitPts.length > 2) {
    const minT = hitPts.reduce((p, c) =>
      ((p.cache_read || 0) / (p.context || 1)) <= ((c.cache_read || 0) / (c.context || 1)) ? p : c)
    const rate = (((minT.cache_read || 0) / (minT.context || 1)) * 100).toFixed(1)
    const ax = x(minT.turn), ay = yHit(((minT.cache_read || 0) / (minT.context || 1)) * 100)
    const anchor = ax > W - 180 ? 'end' : ax < L + 120 ? 'start' : 'middle'
    const dx = anchor === 'end' ? -6 : anchor === 'start' ? 6 : 0
    minHitAnno = (
      <g>
        <circle cx={ax} cy={ay} r={3} className="uc-hitmin" />
        <text x={ax + dx} y={ay - 7} textAnchor={anchor} className="uc-anno">命中率最低 T{minT.turn} · {rate}%</text>
      </g>
    )
  }

  const grid = [0, 0.5, 1].map((f) => {
    const v = maxIn * f, y = yIn(v)
    return (
      <g key={f}>
        <line x1={L} y1={y} x2={W - R} y2={y} className="uc-grid" />
        <text x={L - 6} y={y + 3} textAnchor="end" className="uc-cap">{fmtK(v)}</text>
      </g>
    )
  })

  // compaction：竖线贯穿两层 + 落差标注（−N）。
  const compAnno = (data.compactions || []).flatMap((c, i) => {
    if (c.turn == null) return []
    const turnNo: number = c.turn
    const cx = x(turnNo)
    const curT = byTurn.get(turnNo)
    const prev = [...rep].reverse().find((r) => r.turn < turnNo)
    if (!prev || !curT) return <line key={i} x1={cx} y1={OCC_TOP} x2={cx} y2={HIT_BOT} className="uc-comp" />
    const drop = (prev.context || 0) > (curT.context || 0)
      ? (prev.context || 0) - (curT.context || 0) : null
    return (
      <g key={i}>
        <line x1={cx} y1={OCC_TOP} x2={cx} y2={HIT_BOT} className="uc-comp" />
        {drop != null && (
          <text x={cx + 6} y={(yIn(prev.context || 0) + yIn(curT.context || 0)) / 2 + 3} className="uc-drop">−{fmtK(drop)}</text>
        )}
      </g>
    )
  })

  const dots = rep.filter((t) => susp.has(t.turn)).map((t) => (
    <circle
      key={t.turn}
      cx={x(t.turn)} cy={yIn(t.context || t.input || 0)} r={4}
      className="uc-dot bad" data-u={t.turn}
    />
  ))

  // 悬停明细：mousemove 按横轴就近取轮（旧版同款几何）
  const [tip, setTip] = useState<{ turn: number; px: number } | null>(null)
  const tipTurn = tip ? byTurn.get(tip.turn) : undefined

  return (
    <>
      <div className="sp-head">
        <b>Usage 全周期</b>
        <span className="sum">
          Σ {fmtNum(data.total?.total_tokens ?? 0)} tok · in {fmtNum(data.total?.input ?? 0)} · out {fmtNum(data.total?.output ?? 0)}
          {' '}· cache R {fmtNum(data.total?.cache_read ?? 0)} · W {fmtNum(data.total?.cache_write ?? 0)}
          {data.missing_turns ? ` · ${data.missing_turns} 轮缺` : ''}
        </span>
        <button type="button" className="ghost" onClick={onClose} aria-label="关闭 Usage 面板">×</button>
      </div>
      <div className="ucurve-wrap">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="uc-svg"
          onMouseMove={(ev) => {
            const rect = ev.currentTarget.getBoundingClientRect()
            const mx = (ev.clientX - rect.left) / rect.width * W
            const turn = Math.max(1, Math.min(maxTurn, Math.round(1 + (mx - L) / plotW * (maxTurn - 1))))
            setTip(byTurn.has(turn)
              ? { turn, px: Math.min(Math.max(x(turn) / W * rect.width, 70), rect.width - 70) }
              : null)
          }}
          onMouseLeave={() => setTip(null)}
          onClick={(ev) => {
            const dot = (ev.target as Element).closest('[data-u]')
            if (!dot) return
            const row = byTurn.get(Number(dot.getAttribute('data-u')))
            if (row?.seq) onJump(row.seq)
          }}
        >
          {grid}
          {occArea}
          {occLine}
          {hitLine}
          {compAnno}
          {dots}
          {minHitAnno}
          <text x={L} y={OCC_TOP - 8} className="uc-lab">context / 轮（max {fmtK(maxIn)}）· 断口 = missing</text>
          <text x={L} y={HIT_TOP - 8} className="uc-lab">缓存命中率</text>
          <line x1={L} y1={HIT_BOT} x2={W - R} y2={HIT_BOT} className="uc-grid" />
          <text x={L - 6} y={HIT_BOT + 3} textAnchor="end" className="uc-cap">0%</text>
          <text x={L - 6} y={HIT_TOP + 3} textAnchor="end" className="uc-cap">100%</text>
          {maxTurn > 1 && (
            <>
              <text x={L} y={H - 4} className="uc-cap">T1</text>
              <text x={W - R} y={H - 4} textAnchor="end" className="uc-cap">T{maxTurn}</text>
            </>
          )}
        </svg>
        {tip && tipTurn && (
          <div className="uc-tip" style={{ left: tip.px }}>
            <b>第 {tipTurn.turn} 轮 · {tipTurn.status}</b>
            <div>context {fmtNum(tipTurn.context)} · 输入 {fmtNum(tipTurn.input)} · 输出 {fmtNum(tipTurn.output)}</div>
            <div>缓存读取 {fmtNum(tipTurn.cache_read)} · 命中 {
              (tipTurn.context || 0) > 0 && tipTurn.cache_read != null
                ? (((tipTurn.cache_read || 0) / (tipTurn.context || 1)) * 100).toFixed(1) + '%' : '—'}
            </div>
            {tipTurn.cache_write != null && <div>缓存写入 {fmtNum(tipTurn.cache_write)}</div>}
            <div>总 {fmtNum(tipTurn.total_tokens)} tok{tipTurn.cost != null ? ` · $${tipTurn.cost}` : ''}</div>
            {susp.get(tipTurn.turn) && (
              <div className="uc-tip-bad">{RULE_LABEL[susp.get(tipTurn.turn)!] ?? susp.get(tipTurn.turn)}</div>
            )}
          </div>
        )}
      </div>
      {a.findings.length > 0 && (
        <details className="ufindings">
          <summary>{a.findings.length} 处发现</summary>
          {a.findings.map((f, i) => {
            const row = byTurn.get(f.turn)
            return (
              <button
                key={i}
                type="button"
                className="uf-row"
                onClick={() => { if (row?.seq) onJump(row.seq) }}
              >
                <span className={`uf-rule ${f.rule}`}>{RULE_LABEL[f.rule] ?? f.rule}</span>
                <span className="uf-turn">T{f.turn}</span>
                <span className="uf-detail">{f.detail}</span>
              </button>
            )
          })}
        </details>
      )}
      <div className="hint">上层 context 占用 · 下层缓存命中率 · 竖线=compaction（含落差标注）· 红点=体检发现 · 断口=missing · 悬停看明细，点击跳转轨迹</div>
    </>
  )
}
