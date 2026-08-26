import { describe, expect, it } from 'vitest'
import { conversationBlocks } from './conversationModel'
import type { ProjectedRow } from '../api/types'

const row = (over: Partial<ProjectedRow>): ProjectedRow => ({
  id: 'x', _seq: 0, index: 0, turn: 1, kind: 'user', tag: 'USER', text: '',
  startedAt: 0, durationMs: 0, status: 'completed',
  usage: { status: 'n/a', input: null, output: null, cacheRead: null, cacheWrite: null, totalTokens: null, cost: null },
  ...over,
})

describe('conversationBlocks', () => {
  it('工具行按父消息聚成一组', () => {
    const blocks = conversationBlocks([
      row({ id: 'u1', kind: 'user' }),
      row({ id: 'a1', kind: 'assistant' }),
      row({ id: 't1', kind: 'tool', parentId: 'a1', name: 'Read' }),
      row({ id: 't2', kind: 'tool', parentId: 'a1', name: 'Bash' }),
      row({ id: 'a2', kind: 'assistant' }),
    ])
    expect(blocks.map((b) => b.type)).toEqual(['message', 'message', 'tools', 'message'])
    expect((blocks[2] as { rows: ProjectedRow[] }).rows).toHaveLength(2)
  })

  it('context/system 行不进对话视图', () => {
    const blocks = conversationBlocks([
      row({ id: 'c1', kind: 'context' }),
      row({ id: 's1', kind: 'system', turn: null }),
    ])
    expect(blocks).toHaveLength(0)
  })

  it('compaction 边界保留为独立块', () => {
    const blocks = conversationBlocks([row({ id: 'k1', kind: 'compacted' })])
    expect(blocks.map((b) => b.type)).toEqual(['compacted'])
  })

  it('无父消息的孤儿工具行丢弃', () => {
    const blocks = conversationBlocks([row({ id: 't9', kind: 'tool', parentId: null })])
    expect(blocks).toHaveLength(0)
  })
})
