// Session-scoped Run 数据层。
//
// 仅读取 `/api/sessions/{sid}/runs`，绝不据 rows 推导 Run；canonical identity
// 完全由后端（status、conflict、started/ended seq）给定。换 Session 时旧会话
// 的运行结果必须丢弃——选中的 Run 也复位，避免旧 Run id 落到新会话上。
// 慢响应后到用 epoch 守卫吞掉（与 useSession/useSummary 的同套防护一致）。
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './client'
import type { RunInfo } from './types'

export interface UseRunsResult {
  runs: RunInfo[]
  selectedRunId: number | null
  /** `null` 表示「全部 Runs + runless」，与 navigator 的「全部」入口对齐。 */
  selectRun: (id: number | null) => void
  loading: boolean
  error: string | null
  /** 主动重拉当前 Session 的 Run 列表，HTTP 失败写入 error。 */
  refresh: () => Promise<void>
}

export function useRuns(sessionId: string | null): UseRunsResult {
  const [runs, setRuns] = useState<RunInfo[]>([])
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const [loading, setLoading] = useState<boolean>(sessionId != null)
  const [error, setError] = useState<string | null>(null)
  // epoch 守卫：换会话 / 卸载后旧请求的响应必须丢弃
  const epochRef = useRef(0)
  // 锁定当前选中的 Run id：refresh 时如果用户已选某个 Run 且它仍存在，
  // 服务端翻序也不让选中项跳走（保持消费侧选择稳定）
  const selectedRef = useRef<number | null>(null)
  useEffect(() => { selectedRef.current = selectedRunId }, [selectedRunId])

  const load = useCallback(async (sid: string) => {
    const epoch = ++epochRef.current
    setLoading(true)
    try {
      const res = await api.runs(sid)
      // 旧请求/卸载后的响应必须丢弃，不能覆盖当前 session 的数据
      if (epochRef.current !== epoch) return
      const list = res.runs ?? []
      setRuns(list)
      // 选中的 Run 若已不存在（run 关闭/折叠），回退到「全部」以免 UI 指向幽灵 id
      const still = selectedRef.current
      setSelectedRunId(still != null && list.some((r) => r.run_id === still) ? still : null)
      setError(null)
    } catch (err) {
      if (epochRef.current !== epoch) return
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (epochRef.current === epoch) setLoading(false)
    }
  }, [])

  // 切会话即重置：旧 runs/选中的 Run/error 全部丢弃，再发新请求
  useEffect(() => {
    if (sessionId == null) {
      ++epochRef.current
      setRuns([])
      setSelectedRunId(null)
      setError(null)
      setLoading(false)
      return
    }
    setRuns([])
    setSelectedRunId(null)
    setError(null)
    void load(sessionId)
  }, [sessionId, load])

  const selectRun = useCallback((id: number | null) => {
    setSelectedRunId(id)
  }, [])

  const refresh = useCallback(async () => {
    if (sessionId == null) return
    await load(sessionId)
  }, [sessionId, load])

  return { runs, selectedRunId, selectRun, loading, error, refresh }
}
