// 对话视图（DSH 对话 tab 同思路）：只渲染 user/assistant 消息，工具调用收成
// 单行 chip，点击跳回轨迹现场。markdown 渲染与高亮复用 lib/markdown。
import { useEffect, useRef } from 'react'
import type { SessionData } from '../../api/merge'
import { conversationBlocks } from '../../lib/conversationModel'
import { markdownHtml, highlightIn } from '../../lib/markdown'
import { durLabel } from '../../lib/inspectorModel'
import { usageStripInline } from './usage'

interface Props {
  data: SessionData
  onInspect: (id: string) => void
  onLoadOlder: () => void
  loadingOlder: boolean
}

export function ConversationView({ data, onInspect, onLoadOlder, loadingOlder }: Props) {
  const blocks = conversationBlocks(data.rows)
  const ref = useRef<HTMLDivElement>(null)
  // markdown 代码块高亮：rows 变化后对新 DOM 补一轮
  useEffect(() => { highlightIn(ref.current) }, [data.rows])

  return (
    <div className="conv-wrap" ref={ref}>
      {data.hasOlder && (
        <button type="button" className="ghost conv-older" disabled={loadingOlder} onClick={onLoadOlder}>
          {loadingOlder ? 'Loading…' : 'Load earlier history'}
        </button>
      )}
      {blocks.map((b) => {
        if (b.type === 'compacted') {
          return <div key={b.row.id} className="conv-compact">已压缩上下文：{b.row.text}</div>
        }
        if (b.type === 'tools') {
          return (
            <div key={`tools-${b.parentId}-${b.rows[0].id}`} className="conv-tools">
              {b.rows.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className="conv-tool-chip"
                  data-error={t.status === 'failed' || undefined}
                  title="在轨迹中查看这次调用"
                  onClick={() => onInspect(t.id)}
                >
                  {t.name}
                  {t.durationMs > 1 ? ` · ${durLabel(t.durationMs)}` : ''}
                  {t.status === 'failed' ? ' · failed' : ''}
                </button>
              ))}
            </div>
          )
        }
        const r = b.row
        const isUser = r.kind === 'user'
        const body = isUser ? r.text : (r.outputText || r.text || '')
        return (
          <div key={r.id} className={`conv-msg ${isUser ? 'user' : 'assistant'}`}>
            <span className="conv-who">{isUser ? 'USER' : 'ASSISTANT'}</span>
            {!isUser && r.thinking ? (
              <details className="think">
                <summary>Thinking</summary>
                <div className="think-body" dangerouslySetInnerHTML={{ __html: markdownHtml(r.thinking) }} />
              </details>
            ) : null}
            <div className="conv-body" dangerouslySetInnerHTML={{ __html: markdownHtml(body) }} />
            {!isUser && r.usage && (r.usage.status === 'reported' || r.usage.status === 'estimated')
              ? usageStripInline(r.usage)
              : null}
          </div>
        )
      })}
      {!blocks.length && <div className="board-empty">本窗口没有对话内容</div>}
    </div>
  )
}
