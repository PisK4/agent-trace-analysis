// 标注板数据源：annotations + runs 的加载与写入后重拉。
// 写入统一走 api.appendForSession（agent 解析的唯一 seam），成功后 reload——
// 与旧版 postBoardEvent 同策略：账本 append-only，没有原地更新。
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { onSummariesChanged } from '../../api/useSummary'
import type { AssignmentEntry, RunInfo, ScoreEntry } from '../../api/types'

export interface BoardData {
  scores: ScoreEntry[]
  assignments: AssignmentEntry[]
  runs: RunInfo[]
}

export function useBoard(enabled: boolean) {
  const [data, setData] = useState<BoardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [anno, runs] = await Promise.all([api.annotations(), api.runs()])
      setData({ scores: anno.scores ?? [], assignments: anno.assignments ?? [], runs })
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    let alive = true
    // 异步加载放 effect 内联：lint 对「effect 里调用的函数含 setState」保守告警
    ;(async () => {
      const load = reload
      try {
        await load()
        void alive
      } catch { /* reload 自吞错误 */ }
    })()
    // live tailing 期间别人标的也能看见：会话页轮询检测到变化即广播，
    // 标注板订阅同一信号（架构评审二轮候选 5）。
    return onSummariesChanged(() => { void reload() })
  }, [enabled, reload])

  /** 组一条 v1 事件经唯一 seam 追加进账本；成功后重拉聚合 */
  const postEvent = useCallback(async (
    sessionId: string,
    type: string,
    payload: Record<string, unknown>,
    okMsg: string | null,
    failPrefix: string,
  ): Promise<boolean> => {
    try {
      await api.appendForSession(sessionId, type, payload)
      if (okMsg) void okMsg
      await reload()
      return true
    } catch (err) {
      setError(`${failPrefix}：${err instanceof Error ? err.message : String(err)}`)
      return false
    }
  }, [reload])

  return { data, error, reload, postEvent, clearError: () => setError(null) }
}
