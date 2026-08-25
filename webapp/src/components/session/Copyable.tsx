// 复制 chip：原文从 row 字段取（不从 DOM 抄——markdown 保住源码、payload 抄不出
// 干净 JSON）。旧版 attachCopyButtons 的 React 化；样式复用 .copyable/.copy-chip。
import type { ReactNode } from 'react'
import { useToast } from '../toast'

export interface CopySource {
  payload?: unknown
  thinking?: string | null
  outputText?: string | null
  payloadText?: string | null
  text: string
  result?: string | null
  promptText?: string | null
}

function copyTextFor(kind: string, row: CopySource): string {
  if (kind === 'payload') return JSON.stringify(row.payload ?? null, null, 2)
  if (kind === 'raw') return [row.thinking, row.outputText || row.payloadText || row.text].filter(Boolean).join('\n\n')
  if (kind === 'prompt') return row.promptText || ''
  return row.result || row.outputText || row.payloadText || row.text || ''
}

export function Copyable({ kind, row, children }: { kind: string; row: CopySource; children: ReactNode }) {
  const toast = useToast()
  return (
    <div className="copyable">
      {children}
      <button
        type="button"
        className="copy-chip"
        title="复制内容"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(copyTextFor(kind, row))
            toast('已复制')
          } catch {
            toast('复制失败', 'err')
          }
        }}
      >
        ⧉
      </button>
    </div>
  )
}
