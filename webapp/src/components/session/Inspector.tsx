// 详情面板：会话上下文抽屉（System Prompt / Tools / Skills）+ 事件 tab 详情。
// 语义平移自旧版 web/js/inspector.js paintContext + paintInspector；
// 渲染从 innerHTML 字符串拼接改为 React 节点，交互态全部组件 state。
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { ProjectedRow } from '../../api/types'
import {
  clock,
  dayClock,
  durLabel,
  lineDiff,
  modelLabel,
  parseMaybe,
  statusLabel,
  tabsOf,
  type DiffLine,
  type InspectorTab,
} from '../../lib/inspectorModel'
import { fmtCost, fmtNum } from '../../lib/format'
import { highlightIn, markdownHtml } from '../../lib/markdown'
import type { SessionData } from '../../api/merge'
import { Copyable } from './Copyable'
import { JsonView } from './JsonView'

const TAB_LABEL: Record<InspectorTab, string> = {
  summary: 'Summary', usage: 'Usage', timing: 'Timing', diff: 'Diff',
  prompt: 'System Prompt', tools: 'Tools', skills: 'Skills',
  payload: 'Payload', result: 'Result', schema: 'Schema',
  preview: 'Preview', raw: 'Raw', source: 'Source',
}

/** markdown 正文块：渲染后对容器内代码做一次 hljs 高亮 */
function Md({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    highlightIn(ref.current)
  }, [text])
  return <div className="md" ref={ref} dangerouslySetInnerHTML={{ __html: markdownHtml(text) }} />
}

function DiffBlob({ lines }: { lines: DiffLine[] }) {
  return (
    <pre className="blob diff">
      {lines.length === 0
        ? 'Identical arguments'
        : lines.map((p, i) =>
            p.t === 'fold' ? (
              <span key={i} className="miss">… {p.n} unchanged lines</span>
            ) : (
              <span key={i} className={p.t}>{p.text}</span>
            ),
          )}
    </pre>
  )
}

function StartedValue({ ms }: { ms: number }) {
  const [unix, setUnix] = useState(false)
  if (!Number.isFinite(ms)) return <dd>Not available</dd>
  return (
    <dd>
      <button
        type="button"
        className="stamp"
        title={unix ? 'Show local time' : 'Show Unix timestamp'}
        onClick={() => setUnix(!unix)}
      >
        {unix ? (ms / 1000).toFixed(3) : dayClock(ms)}
      </button>
    </dd>
  )
}

interface UsageLike {
  status: string
  input?: number | null
  output?: number | null
  cacheRead?: number | null
  cacheWrite?: number | null
  totalTokens?: number | null
  cost?: number | null
}

function UsageCells({ usage }: { usage: UsageLike }) {
  const cell = (label: string, value: string | null, missing: boolean) => (
    <div className="u-cell">
      <span>{label}</span>
      {missing ? <b className="miss">{usage.status === 'n/a' ? '—' : 'Missing'}</b> : <b>{value}</b>}
    </div>
  )
  const st = (v: number | null | undefined) => (usage.status === 'n/a' ? true : v == null)
  return (
    <div className="usage-grid">
      {cell('Input', fmtNum(usage.input ?? null), st(usage.input))}
      {cell('Output', fmtNum(usage.output ?? null), st(usage.output))}
      {cell('Cache read', fmtNum(usage.cacheRead ?? null), st(usage.cacheRead))}
      {cell('Cache write', fmtNum(usage.cacheWrite ?? null), st(usage.cacheWrite))}
      {cell('Total tokens', fmtNum(usage.totalTokens ?? null), st(usage.totalTokens))}
      {cell('Cost', fmtCost(usage.cost ?? null) ?? null, st(usage.cost))}
    </div>
  )
}

/** usage 紧凑条：↓输入 ↑输出 · 缓存徽标 · 成本，悬停弹六字段明细 */
export function UsageStrip({ usage }: { usage: ProjectedRow['usage'] }) {
  if (!usage || usage.status === 'n/a') return <p className="miss">No usage reported</p>
  const est = usage.status === 'estimated' ? <span className="us-est" title="estimated，非实测">est</span> : null
  return (
    <div className={`ustrip-wrap${usage.status === 'reported' ? '' : ''}`}>
      <div className={`ustrip ${usage.status === 'reported' ? '' : 'us-dim'}`}>
        <span className="us-seg us-in" title="Input tokens">↓ <b>{fmtNum(usage.input)}</b></span>
        <span className="us-seg us-out" title="Output tokens">↑ <b>{fmtNum(usage.output)}</b></span>
        {usage.cacheRead ? <span className="us-seg us-cache" title="Cache read tokens">⛁ <b>{fmtNum(usage.cacheRead)}</b></span> : null}
        {usage.cacheWrite ? <span className="us-seg us-cache" title="Cache write tokens">⛁+ <b>{fmtNum(usage.cacheWrite)}</b></span> : null}
        {usage.cost ? <span className="us-seg us-cost" title="Cost">${fmtCost(usage.cost)}</span> : null}
      </div>
      {est}
      <div className="ustrip-pop">
        <UsageCells usage={usage} />
      </div>
    </div>
  )
}

function ThinkingBlock({ text }: { text?: string | null }) {
  if (!text) return null
  return (
    <details className="think">
      <summary>Thinking</summary>
      <div className="think-body">
        <Md text={text} />
      </div>
    </details>
  )
}

/** 预览正文：assistant 用 outputText；整条 JSON 给结构化视图；残破 JSON 保等宽 */
function PreviewBody({ row }: { row: ProjectedRow }) {
  const shown = row.kind === 'assistant' ? row.outputText || '' : row.payloadText || row.outputText || row.text || ''
  const parsed = row.kind === 'assistant' ? null : parseMaybe(shown)
  const brokenJson = !parsed && !row.thinking && /^\s*[{[]/.test(shown) && shown.length > 200
  const body: ReactNode = shown
    ? parsed
      ? <JsonView stateKey={`${row.id}:body`} parsed={parsed} />
      : brokenJson
        ? <pre className="blob">{shown}</pre>
        : <Md text={shown} />
    : null
  if (!body && !row.thinking) return <p className="miss">No content</p>
  return (
    <>
      <ThinkingBlock text={row.thinking} />
      {body}
    </>
  )
}

function ToolCards({ tools }: { tools: NonNullable<ProjectedRow['toolsCatalog']> }) {
  return (
    <>
      {tools.map((tool) => (
        <details key={tool.name} className="tool-card">
          <summary>{tool.name}</summary>
          <div className="inner">
            <p className="miss">{tool.description}</p>
            {tool.parameters && Object.keys(tool.parameters).length ? (
              <div className="tree">
                <JsonNodeStandalone value={tool.parameters} />
              </div>
            ) : null}
          </div>
        </details>
      ))}
    </>
  )
}

// JsonNode 独立导出：schema 参数树等只需 tree 不需要切换按钮的场景复用
import { JsonNode as JsonNodeStandalone } from './JsonView'

function SkillCards({ skills }: { skills: Array<Record<string, unknown>> }) {
  if (!skills.length) return <div className="sec"><p className="miss">No skills injected in this round.</p></div>
  // skill 元素按 Pi Skill 接口防御式渲染：name 做标题，其余字段全部展示。
  return (
    <>
      {skills.map((skill, i) => (
        <details key={i} className="tool-card">
          <summary>{typeof skill.name === 'string' ? skill.name : 'skill'}</summary>
          <div className="inner">
            <dl className="kv">
              {Object.entries(skill)
                .filter(([k, v]) => k !== 'name' && v != null)
                .map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
                  </div>
                ))}
            </dl>
          </div>
        </details>
      ))}
    </>
  )
}

// ── 会话上下文抽屉 ──

interface CtxProps {
  rows: ProjectedRow[]
  sessionId: string
}

function ContextDrawer({ rows, sessionId }: CtxProps) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'system' | 'tools' | 'skills'>('system')
  // 换会话重置抽屉：以 sessionId 派生 state（React 官方推荐模式），避免 effect 级联渲染
  const [prevSid, setPrevSid] = useState(sessionId)
  if (prevSid !== sessionId) {
    setPrevSid(sessionId)
    setOpen(false)
    setTab('system')
  }
  const systemRows = useMemo(() => rows.filter((r) => r.kind === 'system'), [rows])
  const latest = systemRows[systemRows.length - 1]
  if (!latest) return null

  return (
    <div className="ctx">
      <button type="button" className="ctx-bar" aria-expanded={open} aria-controls="ctxPanel" onClick={() => setOpen(!open)}>
        <span className="caret">{open ? '▾' : '▸'}</span>
        <span>
          {systemRows.length} System Prompt{systemRows.length > 1 ? 's' : ''} · {(latest.toolsCatalog || []).length} Tools ·{' '}
          {(latest.skillsCatalog || []).length} Skills
        </span>
      </button>
      {open && (
        <div className="ctx-panel" id="ctxPanel">
          <div className="tabs ctx-tabs" role="tablist">
            {(['system', 'tools', 'skills'] as const).map((id) => (
              <button key={id} type="button" className="tab" aria-selected={id === tab} onClick={() => setTab(id)}>
                {{ system: 'System', tools: 'Tools', skills: 'Skills' }[id]}
              </button>
            ))}
          </div>
          <div className="ctx-body">
            {tab === 'tools' && <ToolCards tools={latest.toolsCatalog || []} />}
            {tab === 'skills' && <SkillCards skills={latest.skillsCatalog || []} />}
            {tab === 'system' && (
              <>
                {/* 版本栈：倒序排列，最新版默认展开；Diff 独立折叠块插在两版之间 */}
                {[...systemRows].reverse().map((row, i) => {
                  const name = i === 0 ? 'System Prompt (latest)' : `System Prompt v${systemRows.length - i}`
                  const loc = row.turn != null ? `Turn ${row.turn}` : Number.isFinite(row.startedAt) ? clock(row.startedAt) : 'Session start'
                  const size = `${(row.promptText || '').length.toLocaleString('en-US')} chars`
                  return (
                    <div key={row.id}>
                      <details className={`ver${i === 0 ? ' latest' : ''}`} open={i === 0}>
                        <summary>
                          {name}
                          <small>{loc} · {size}</small>
                        </summary>
                        <div className="inner">
                          <div className="sec">
                            <Copyable kind="prompt" row={row}>
                              <Md text={row.promptText || ''} />
                            </Copyable>
                          </div>
                        </div>
                      </details>
                      {row.previousPrompt && (
                        <details className="ver-diff">
                          <summary>Diff · {name} vs previous</summary>
                          <DiffBlob lines={lineDiff(row.previousPrompt, row.promptText || '')} />
                        </details>
                      )}
                    </div>
                  )
                })}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── 事件详情主面板 ──

interface Props {
  rows: ProjectedRow[]
  toolsIndex: SessionData['toolsIndex']
  sessionId: string
  selectedId: string | null
  onJump: (id: string) => void
  /** 详情栏宽度（px）；null = 用 CSS 默认 clamp(320px,38%,440px) */
  width: number | null
  /** 拖拽中回传新宽度（父层只更新 state，不落存储） */
  onWidthChange: (w: number | null) => void
  /** 拖拽/双击复位结束时回调一次；localStorage 持久化由父层在此做，
   * 不随 pointermove 每帧写存储 */
  onWidthCommit?: () => void
}

// 与旧版 web/js/util.js 同参：拖宽边界与表格最小宽度，防止把轨迹列挤没。
const DETAILS_MIN = 320
const DETAILS_MAX = 720
const TABLE_MIN = 280

export function Inspector({ rows, toolsIndex, sessionId, selectedId, onJump, width, onWidthChange, onWidthCommit }: Props) {
  // tab 记忆：换选中优先恢复用户去过的 tab（旧版 rememberTab/restoreTab）
  // tab 历史：换选中优先恢复用户去过的 tab（旧版 rememberTab/restoreTab）
  const [tabHistory, setTabHistory] = useState<string[]>(['summary'])
  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows])
  const row = selectedId ? byId.get(selectedId) : undefined

  const target = useMemo(
    () => (selectedId && byId.has(selectedId) ? { type: 'record' as const, id: selectedId } : null),
    [selectedId, byId],
  )
  const tabs = target ? tabsOf(target, (id) => byId.get(id)) : []
  // tab 记忆在渲染期读取 ref：与旧版 restoreTab 同语义——换选中时优先恢复用户
  // 去过的 tab。历史只在事件回调里写入，渲染期只读，无并发问题。
  const tab: InspectorTab | null = tabs.length
    ? ([...tabHistory].reverse().find((t) => tabs.includes(t as InspectorTab)) as InspectorTab) ?? tabs[0]
    : null

  const selectTab = (t: InspectorTab) => {
    setTabHistory((prev) => prev.filter((x) => x !== t).concat(t))
  }

  // 左缘拖宽（旧版 resize pointer 三件套同语义）：pointer capture 保证移出
  // 把手仍持续收到 move；双击复位交还 CSS 默认宽度。
  const dragRef = useRef<{ pointerId: number; startX: number; startWidth: number; splitWidth: number } | null>(null)
  const clampWidth = (w: number, splitW: number) =>
    Math.min(Math.max(w, DETAILS_MIN), Math.min(DETAILS_MAX, splitW - TABLE_MIN))

  return (
    <aside className="details" style={width != null ? { width } : undefined}>
      <div
        className="resize"
        role="separator"
        aria-orientation="vertical"
        onPointerDown={(e) => {
          if (e.button !== 0) return
          e.currentTarget.setPointerCapture(e.pointerId)
          const aside = e.currentTarget.parentElement as HTMLElement
          dragRef.current = {
            pointerId: e.pointerId,
            startX: e.clientX,
            startWidth: aside.getBoundingClientRect().width,
            splitWidth: (aside.parentElement as HTMLElement).getBoundingClientRect().width,
          }
          e.preventDefault()
        }}
        onPointerMove={(e) => {
          const d = dragRef.current
          if (!d || d.pointerId !== e.pointerId) return
          onWidthChange(clampWidth(d.startWidth + d.startX - e.clientX, d.splitWidth))
        }}
        onPointerUp={(e) => {
          if (dragRef.current?.pointerId === e.pointerId) {
            // capture 可能已被浏览器提前释放（pointercancel 等），强判再放
            if (e.currentTarget.hasPointerCapture(e.pointerId)) {
              e.currentTarget.releasePointerCapture(e.pointerId)
            }
            dragRef.current = null
            onWidthCommit?.()
          }
        }}
        onPointerCancel={() => {
          // 浏览器中途取消（滚动手势打断等）：capture 自动释放，只清拖拽态，
          // 否则 dragRef 残留会让后续 mousemove 无按键持续触发 resize
          dragRef.current = null
          onWidthCommit?.()
        }}
        onDoubleClick={() => { onWidthChange(null); onWidthCommit?.() }}
      />
      <ContextDrawer rows={rows} sessionId={sessionId} />
      {row && target && tab ? (
        <>
          <div className="d-h">
            <div className="d-title">
              <span className={`kind ${row.kind}`}>{row.tag}</span>
              <span className="d-loc">{row.turn == null ? 'SYSTEM' : `Turn ${row.turn}${row.step != null ? ` · Step ${row.step}` : row.group ? ` · ${row.group}` : ''}`}</span>
            </div>
          </div>
          <div className="tabs" role="tablist">
            {tabs.map((id) => (
              <button key={id} type="button" className="tab" role="tab" aria-selected={id === tab} onClick={() => selectTab(id)}>
                {TAB_LABEL[id]}
              </button>
            ))}
          </div>
          <div className="d-body">
            <DetailBody row={row} byId={byId} tab={tab} onJump={onJump} toolsIndex={toolsIndex} />
          </div>
        </>
      ) : (
        <div className="d-empty">点击事件查看详情</div>
      )}
    </aside>
  )
}

function DetailBody({ row, byId, tab, onJump, toolsIndex }: {
  row: ProjectedRow
  byId: Map<string, ProjectedRow>
  tab: InspectorTab
  onJump: (id: string) => void
  toolsIndex: SessionData['toolsIndex']
}) {
  const parent = row.parentId ? byId.get(row.parentId) : undefined
  const grand = parent?.parentId ? byId.get(parent.parentId) : undefined

  if (row.kind === 'system') {
    if (tab === 'prompt')
      return <div className="sec"><Copyable kind="prompt" row={row}><Md text={row.promptText || ''} /></Copyable></div>
    if (tab === 'tools') return <div className="sec"><ToolCards tools={row.toolsCatalog || []} /></div>
    if (tab === 'skills') return <div className="sec"><SkillCards skills={(row.skillsCatalog || []) as Array<Record<string, unknown>>} /></div>
    return <div className="sec"><DiffBlob lines={lineDiff(row.previousPrompt || '', row.promptText || '')} /></div>
  }

  if (row.kind === 'compacted') {
    if (tab === 'raw')
      return <div className="sec"><Copyable kind="raw" row={row}><pre className="blob">{row.outputText || row.text || 'No output'}</pre></Copyable></div>
    return (
      <dl className="kv">
        <div><dt>Status</dt><dd>{statusLabel(row.status)}</dd></div>
        {row.note ? <div><dt>Note</dt><dd>{row.note}</dd></div> : null}
        <div><dt>Summary</dt><dd>{row.text || 'Context compacted'}</dd></div>
      </dl>
    )
  }

  switch (tab) {
    case 'payload':
      return (
        <div className="sec">
          {row.payload ? (
            <Copyable kind="payload" row={row}>
              <JsonView stateKey={`${row.id}:payload`} parsed={(row.payload as object) ?? null} />
            </Copyable>
          ) : row.payloadText ? (
            <Copyable kind="preview" row={row}>
              <Md text={row.payloadText} />
            </Copyable>
          ) : (
            <div className="sec miss">No payload captured</div>
          )}
        </div>
      )
    case 'result':
      return (
        <div className="sec">
          {row.result ? (
            <Copyable kind="result" row={row}>
              <JsonView stateKey={`${row.id}:result`} parsed={parseMaybe(row.result)}>
                <pre className="blob">{row.result}</pre>
              </JsonView>
            </Copyable>
          ) : (
            <div className="sec miss">No result captured</div>
          )}
        </div>
      )
    case 'schema': {
      // 行级 schema 字段后端不下发，统一走 tools_index（按工具名查，dsh 同款取数）
      const schema = row.name ? toolsIndex[row.name] : undefined
      const params = schema?.parameters && Object.keys(schema.parameters).length ? schema.parameters : null
      return (
        <div className="sec">
          {schema ? (
            <>
              <div className="schema-box">
                <h3>{schema.name}</h3>
                {schema.description ? <p>{schema.description}</p> : null}
              </div>
              {params ? (
                <div className="tree">
                  <JsonNodeStandalone value={params} />
                </div>
              ) : (
                <p className="miss" style={{ marginTop: 6 }}>Parameters not recorded in source log</p>
              )}
            </>
          ) : (
            <div className="sec miss">Schema unavailable</div>
          )}
        </div>
      )
    }
    case 'timing': {
      const throughput = row.usage?.output != null && row.durationMs ? null : null // 占位：旧版用 outputTokens 字段，投影未下发
      void throughput
      return (
        <dl className="kv">
          <div><dt>Started</dt><StartedValue ms={row.startedAt} /></div>
          <div><dt>Duration</dt><dd>{row.durationMs ? durLabel(row.durationMs) : 'Pending'}</dd></div>
          <div><dt>TTFT</dt><dd className="miss">First token unavailable</dd></div>
          <div><dt>Generation</dt><dd className="miss">Not recorded</dd></div>
          <div><dt>Throughput</dt><dd className="miss">Usage unavailable</dd></div>
          <div><dt>Timing source</dt><dd>Session timestamps</dd></div>
        </dl>
      )
    }
    case 'preview':
      return <div className="sec"><Copyable kind="preview" row={row}><PreviewBody row={row} /></Copyable></div>
    case 'raw': {
      const raw = [row.thinking, row.outputText || row.payloadText || row.text].filter(Boolean).join('\n\n')
      return <div className="sec"><Copyable kind="raw" row={row}><pre className="blob">{raw || 'No content'}</pre></Copyable></div>
    }
    default:
      return <SummaryBody row={row} parent={parent} grand={grand} onJump={onJump} toolsIndex={toolsIndex} />
  }
}

function SummaryBody({ row, parent, grand, onJump, toolsIndex }: {
  row: ProjectedRow
  parent?: ProjectedRow
  grand?: ProjectedRow
  onJump: (id: string) => void
  toolsIndex: SessionData['toolsIndex']
}) {
  const isMarkdown = row.kind === 'assistant' || row.kind === 'user' || row.kind === 'context'
  const jumpBtn = (target: ProjectedRow, label: string) => (
    <button type="button" className="jump" onClick={() => onJump(target.id)}>
      {label} <i>›</i>
    </button>
  )
  return (
    <>
      <dl className="kv">
        {parent ? (
          <div>
            <dt>Hierarchy</dt>
            <dd>
              {jumpBtn(parent, parent.kind === 'assistant' ? 'Assistant Message' : parent.tag)}
              {grand ? <> · {jumpBtn(grand, grand.tag)}</> : null}
            </dd>
          </div>
        ) : null}
        <div><dt>Status</dt><dd>{statusLabel(row.status)}</dd></div>
        {row.kind === 'assistant' && row.model ? <div><dt>Model</dt><dd>{modelLabel(row)}</dd></div> : null}
        {row.kind === 'assistant' && row.usage.status !== 'n/a' ? (
          <div><dt>Tokens</dt><dd>{row.usage.output != null ? `${fmtNum(row.usage.output)} tok` : '—'}</dd></div>
        ) : null}
        {row.kind === 'user' || row.kind === 'context' ? <div><dt>Duration</dt><dd>{durLabel(row.durationMs || 0)}</dd></div> : null}
        {row.note ? <div><dt>Note</dt><dd>{row.note}</dd></div> : null}
      </dl>
      {isMarkdown ? (
        <div className="sec">
          <div className="sec-h">Preview</div>
          <Copyable kind="preview" row={row}>
            <PreviewBody row={row} />
          </Copyable>
        </div>
      ) : null}
      {!isMarkdown && row.payload ? (
        <div className="sec">
          <div className="sec-h">Payload</div>
          <Copyable kind="payload" row={row}>
            <JsonView stateKey={`${row.id}:payload`} parsed={(row.payload as object) ?? null} />
          </Copyable>
        </div>
      ) : null}
      {!isMarkdown && row.result ? (
        <div className="sec">
          <div className="sec-h">Result</div>
          <Copyable kind="result" row={row}>
            <JsonView stateKey={`${row.id}:result`} parsed={parseMaybe(row.result)}>
              <pre className="blob">{row.result}</pre>
            </JsonView>
          </Copyable>
        </div>
      ) : null}
      {!isMarkdown && row.name && toolsIndex[row.name] ? (
        <div className="sec">
          <div className="sec-h">Schema</div>
          <div className="schema-box">
            <h3>{toolsIndex[row.name].name}</h3>
            {toolsIndex[row.name].description ? <p>{toolsIndex[row.name].description}</p> : null}
          </div>
        </div>
      ) : null}
      {/* 「Diff vs previous call」功能已按需求移除（同名工具入参对比） */}
      <div className="sec">
        <div className="sec-h">{row.kind === 'assistant' ? 'Request Timing' : 'Timing'}</div>
        <dl className="kv">
          <div><dt>Started</dt><StartedValue ms={row.startedAt} /></div>
          <div><dt>Duration</dt><dd>{durLabel(row.durationMs || 0)}</dd></div>
          <div><dt>Timing source</dt><dd>Session timestamps</dd></div>
        </dl>
      </div>
    </>
  )
}
