// 会话页数据源：rev 门控轮询 + 按行合并的 React 化。
//
// 轮询形态沿用旧版已验证的设计（web/js/app.js 自调度链）：setTimeout 链
// 天然防重叠；unchanged 响应零 setState；失败退避；后台标签暂停；epoch
// 守卫消灭「await 期间换会话」脏写。
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './client'
import { applySessionPage, emptySessionData, prependOlderPage, type SessionData } from './merge'
import { nudgeSummaries } from './useSummary'
import { isUnchanged } from './types'

const POLL_INTERVAL_MS = 1000
const POLL_BACKOFF_MS = 5000

export interface UseSessionResult {
  data: SessionData | null
  error: string | null
  /** 手动全量刷新：绕过 rev 门控重置基线 */
  refresh: () => void
  /**
   * 拉取更早历史并前插。返回是否真的拉了（锚点缺失/已在加载时为 false）。
   * rev 基线随 older 页的 rev 推进，后续轮询照常命中门控。
   */
  loadOlder: () => Promise<boolean>
}

export function useSession(id: string | null): UseSessionResult {
  const [sessionData, setSessionData] = useState<SessionData | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 无 id（首页态）时直接派生空数据，不进轮询
  const data = id ? sessionData : null
  // force 拍标记：置位后下一拍不带 rev 拉整页（rev 基线作废）
  const forceRef = useRef(false)

  const refresh = useCallback(() => {
    forceRef.current = true
  }, [])

  // loadOlder 需要读改 dataRef（轮询 effect 的私有状态），经 ref 转发出来。
  // dataRef 在 effect 内创建，这里存它的最新实例。
  const dataRefOuter = useRef<{ current: SessionData } | null>(null)
  const loadingOlderRef = useRef(false)

  const loadOlder = useCallback(async (): Promise<boolean> => {
    const ref = dataRefOuter.current
    if (!ref || loadingOlderRef.current || !ref.current.hasOlder) return false
    const sid = id
    if (!sid) return false
    loadingOlderRef.current = true
    try {
      const page = await api.session(sid, { before: ref.current.cursor, limit: 36 })
      if (!isUnchanged(page) && sid === id) {
        ref.current = prependOlderPage(ref.current, page)
        setSessionData({ ...ref.current })
      }
      return true
    } finally {
      loadingOlderRef.current = false
    }
  }, [id])

  useEffect(() => {
    if (!id) return
    // epoch 守卫：await 回来后 effect 已因换会话重建（epoch 不符）即丢弃结果
    const sid = id
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    let inFlight = false
    let errorStreak = 0

    function schedule(ms: number) {
      timer = setTimeout(run, ms)
    }

    async function run() {
      if (!alive || inFlight) return schedule(POLL_INTERVAL_MS)
      if (document.hidden) return schedule(POLL_INTERVAL_MS)
      inFlight = true
      try {
        // force 拍不带 rev；正常拍带当前基线 rev（0 = 基线未建立），命中 unchanged 返回短响应
        const force = forceRef.current
        forceRef.current = false
        const baseline = dataRef.current.rev
        const res = await api.session(sid, { rev: !force && baseline > 0 ? baseline : undefined })
        if (!alive) return
        if (!isUnchanged(res)) {
          const page = res
          const { next, report } = applySessionPage(dataRef.current ?? emptySessionData(page.id), page)
          dataRef.current = next
          setSessionData(next)
          // live tailing 检测到变化即广播：所有 useSummary 消费者统一重拉，
          // 修复派生面板（usage/timing）在轮询期间静默过期。
          if (report.rowsChanged || report.metaChanged) nudgeSummaries()
        }
        errorStreak = 0
        setError(null)
      } catch (err) {
        errorStreak += 1
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        inFlight = false
      }
      schedule(errorStreak ? POLL_BACKOFF_MS : POLL_INTERVAL_MS)
    }
    // dataRef 与 effect 同生命周期：换会话即重置，不跨会话复用
    const dataRef = { current: emptySessionData(sid) }
    dataRefOuter.current = dataRef
    run()
    return () => {
      alive = false
      clearTimeout(timer)
      if (dataRefOuter.current === dataRef) dataRefOuter.current = null
    }
  }, [id])

  // 页面回前台立刻补一拍，不等退避计时器走完
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') refresh()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh])

  return { data, error, refresh, loadOlder }
}
