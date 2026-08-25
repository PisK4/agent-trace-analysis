// JSON 树 / raw 双视图：tree 用嵌套 <details>，超长字符串折叠、数组切片、
// double-encoded JSON 展开成子树。语义平移自旧版 util.js jsonTree/jsonView，
// 但不再拼 HTML 字符串，直接产出 React 节点。
import { useState } from 'react'
import { esc } from '../../lib/markdown'

const STR_FOLD = 400
const ARR_SLICE = 20

function parseMaybe(text: unknown): object | null {
  if (typeof text !== 'string' || text.length < 2) return null
  const c = text[0]
  if (c !== '{' && c !== '[') return null
  try {
    const v: unknown = JSON.parse(text)
    return v && typeof v === 'object' ? (v as object) : null
  } catch {
    return null
  }
}

function fmtNum(v: number) {
  return v.toLocaleString('en-US')
}

export function JsonNode({ value, k }: { value: unknown; k?: string }) {
  if (value !== null && typeof value === 'object') {
    const entries: Array<[string, unknown]> = Array.isArray(value)
      ? (value as unknown[]).slice(0, ARR_SLICE).map((item, i) => [String(i), item])
      : Object.entries(value as Record<string, unknown>)
    const rest = Array.isArray(value) ? (value as unknown[]).slice(ARR_SLICE) : []
    const name = k == null ? (Array.isArray(value) ? `array[${(value as unknown[]).length}]` : 'object') : esc(k)
    return (
      <details open>
        <summary>
          <span className="k">{name}</span>
        </summary>
        {entries.map(([key, v]) => (
          <JsonNode key={key} value={v} k={key} />
        ))}
        {rest.length > 0 && (
          <details>
            <summary>
              <span className="miss">… {rest.length} more items</span>
            </summary>
            {rest.map((item, i) => (
              <JsonNode key={i} value={item} k={String(i + ARR_SLICE)} />
            ))}
          </details>
        )}
      </details>
    )
  }
  const label = k != null ? <span className="k">{esc(k)}</span>: null
  if (typeof value === 'string') {
    // 字符串里又嵌了一层 JSON（double-encoded）：展开成子树
    const nested = value.length > STR_FOLD ? parseMaybe(value) : null
    if (nested) {
      return (
        <div>
          {label}
          <details open>
            <summary>
              <span className="s">&quot;(embedded JSON · {fmtNum(value.length)} chars)&quot;</span>
            </summary>
            <div className="tree">
              <JsonNode value={nested} />
            </div>
          </details>
        </div>
      )
    }
    if (value.length > STR_FOLD) {
      return (
        <div>
          {label}
          <details>
            <summary>
              <span className="s">&quot;{esc(value.slice(0, STR_FOLD))}…&quot;</span>{' '}
              <span className="miss">({fmtNum(value.length)} chars)</span>
            </summary>
            <span className="s">{esc(value)}</span>
          </details>
        </div>
      )
    }
    return (
      <div>
        {label}
        <span className="s">&quot;{esc(value)}&quot;</span>
      </div>
    )
  }
  return (
    <div>
      {label}
      <span className="n">{esc(value)}</span>
    </div>
  )
}

/**
 * tree/raw 双视图容器：stateKey 隔离不同位置的视图态（同一 row 的 payload/result 各自记忆）。
 * parsed 为可解析 JSON 时给切换按钮；否则只渲染 children（调用方给的原文块）。
 */
export function JsonView({ stateKey, parsed, children }: {
  stateKey: string
  parsed: object | null
  children?: React.ReactNode
}) {
  const [mode, setMode] = useState<'tree' | 'raw'>('tree')
  if (!parsed) return <>{children}</>
  return (
    <>
      <span className="view-toggle">
        <button type="button" data-vset={stateKey} aria-selected={mode === 'tree'} onClick={() => setMode('tree')}>
          Tree
        </button>
        <button type="button" data-vset={stateKey} aria-selected={mode === 'raw'} onClick={() => setMode('raw')}>
          Raw
        </button>
      </span>
      {mode === 'raw' ? (
        <pre className="blob lang-json">{JSON.stringify(parsed, null, 2)}</pre>
      ) : (
        <div className="tree">
          <JsonNode value={parsed} />
        </div>
      )}
    </>
  )
}
