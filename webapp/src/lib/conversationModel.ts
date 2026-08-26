// 对话视图的数据模型：把投影行重组为「消息块 + 工具链块」。纯函数，
// 语义对齐 DSH 对话 tab：只看人说的话和模型答的话，工具收成单行链。
import type { ProjectedRow } from '../api/types'

export type ConvBlock =
  | { type: 'message'; row: ProjectedRow }
  | { type: 'tools'; parentId: string; rows: ProjectedRow[] }
  | { type: 'compacted'; row: ProjectedRow }

export function conversationBlocks(rows: ProjectedRow[]): ConvBlock[] {
  const blocks: ConvBlock[] = []
  for (const row of rows) {
    if (row.kind === 'user' || row.kind === 'assistant') {
      blocks.push({ type: 'message', row })
    } else if (row.kind === 'compacted') {
      blocks.push({ type: 'compacted', row })
    } else if ((row.kind === 'tool' || row.kind === 'subtool') && row.parentId) {
      const last = blocks[blocks.length - 1]
      if (last && last.type === 'tools' && last.parentId === row.parentId) {
        last.rows.push(row)
      } else {
        blocks.push({ type: 'tools', parentId: row.parentId, rows: [row] })
      }
    }
    // context/system 行不进对话：它们属于轨迹视图与 Inspector 的 ctx 抽屉
  }
  return blocks
}
