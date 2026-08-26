// 派生数据（usage/timing/tool-stats）的统一获取 hook（架构评审候选 2）。
//
// 旧问题：各组件各自裸拉一次且只在换会话时刷新，live tailing 期间静默过期
// （旧版 web/js/app.js 的 report.rowsChanged 统一刷新在 React 迁移中丢失）。
// dataFor 守卫、失败置 null、nudge 触发刷新从此只有这一份实现。
import { useCallback, useEffect, useRef, useState } from 'react'

type Listener = () => void
const listeners = new Set<Listener>()

/** live tailing 检测到数据变化时通知全部 useSummary 消费者重新拉取。 */
export function nudgeSummaries(): void {
  for (const l of listeners) l()
}

export function useSummary<T>(
  path: string | null,
): { data: T | null; reload: () => void } {
  // dataFor 记录 data 归属的路径：换目标过渡期渲染 null，不在 effect 里同步置空
  const [state, setState] = useState<{ dataFor: string | null; data: T | null }>({ dataFor: null, data: null })
  const aliveRef = useRef(true)
  // 最新请求的 path：aliveRef 只管挂载生命周期，跨 path 变化仍为 true——
  // 换会话时旧会话的慢响应后到必须丢弃，否则会把新会话的面板刷成旧数据。
  const requestedRef = useRef<string | null>(null)
  useEffect(() => {
    aliveRef.current = true
    return () => { aliveRef.current = false }
  }, [])

  const load = useCallback((p: string) => {
    requestedRef.current = p
    fetch(p)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((d: T) => { if (aliveRef.current && requestedRef.current === p) setState({ dataFor: p, data: d }) })
      .catch(() => { if (aliveRef.current && requestedRef.current === p) setState({ dataFor: p, data: null }) })
  }, [])

  useEffect(() => {
    if (!path) { setState({ dataFor: null, data: null }); return }
    load(path)
  }, [path, load])

  useEffect(() => {
    const listener = () => { if (path) load(path) }
    listeners.add(listener)
    return () => { listeners.delete(listener) }
  }, [path, load])

  const reload = useCallback(() => { if (path) load(path) }, [path, load])
  const data = state.dataFor === path ? state.data : null
  return { data, reload }
}
