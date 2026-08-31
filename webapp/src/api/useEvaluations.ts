// Evaluation 数据层：列表与当前详情分开请求，写入后只刷新当前资源。
//
// 竞态保护：useEffect 与每次 select 都用一个递增的请求 epoch，await 回来
// 后与当前 epoch 比对，不一致即丢弃——避免切换 Evaluation 时旧请求把新
// Evaluation 的 detail/history 写进 state。写操作不 catch 错误，交给页面
// 的 action 通道做 toast/inline alert；hook 只负责把后端原始消息往上抛。
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './client'
import type {
  EvaluationDetail, EvaluationHistoryEntry, EvaluationSummary, SessionMeta,
} from './types'

export interface UseEvaluationsResult {
  evaluations: EvaluationSummary[]
  current: EvaluationDetail | null
  history: EvaluationHistoryEntry[]
  selectedId: string | null
  error: string | null
  loading: boolean
  /** 当前 Evaluation 之外仍可加入的 Session（不与其他 active Evaluation 冲突） */
  availableSessions: SessionMeta[]
  select: (id: string) => Promise<void>
  create: (title: string) => Promise<string>
  rename: (id: string, title: string) => Promise<void>
  remove: (id: string) => Promise<void>
  addSession: (id: string, sessionId: string, taskLabel: string) => Promise<void>
  removeSession: (id: string, sessionId: string) => Promise<void>
  reload: () => Promise<void>
}

export function useEvaluations(allSessions: SessionMeta[] = []): UseEvaluationsResult {
  const [evaluations, setEvaluations] = useState<EvaluationSummary[]>([])
  const [current, setCurrent] = useState<EvaluationDetail | null>(null)
  const [history, setHistory] = useState<EvaluationHistoryEntry[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const requestRef = useRef(0)
  const selectedIdRef = useRef<string | null>(null)
  // 跨 select/create 透传：选完一个新 Evaluation 后，它的 id 直接进入列表高亮，
  // 不用等待 reload 回来再 setSelectedId（reload 是异步的，中间会有「未选中」闪动）。
  const pendingSelectRef = useRef<string | null>(null)

  const loadList = useCallback(async () => {
    const page = await api.evaluations()
    const list = (page.evaluations ?? []).map((item) => ({
      ...item,
      member_count: item.member_count ?? item.members?.length ?? 0,
    }))
    return list
  }, [])

  // 把 detail 与 history 绑成一对并发请求；任一失败都视作整体失败，由调用方决定
  // 是否重试（reload 用，select 不重试——避免来回切时旧请求劫持 UI）。
  const loadDetailAndHistory = useCallback(async (id: string) => {
    const [detail, hist] = await Promise.all([
      api.evaluation(id),
      api.evaluationHistory(id),
    ])
    return { detail, history: hist.events }
  }, [])

  const reload = useCallback(async () => {
    const epoch = ++requestRef.current
    try {
      const list = await loadList()
      if (epoch !== requestRef.current) return
      setEvaluations(list)
      const target = pendingSelectRef.current
        ?? (selectedIdRef.current && list.some((item) => item.evaluation_id === selectedIdRef.current)
          ? selectedIdRef.current
          : list.find((item) => !item.deleted)?.evaluation_id ?? null)
      pendingSelectRef.current = null
      selectedIdRef.current = target
      setSelectedId(target)
      if (target) {
        const { detail, history: hist } = await loadDetailAndHistory(target)
        if (epoch !== requestRef.current) return
        setCurrent(detail)
        setHistory(hist)
      } else {
        setCurrent(null)
        setHistory([])
      }
      setError(null)
    } catch (err) {
      if (epoch !== requestRef.current) return
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (epoch === requestRef.current) setLoading(false)
    }
  }, [loadDetailAndHistory, loadList])

  useEffect(() => { void reload() }, [reload])

  const select = useCallback(async (id: string) => {
    selectedIdRef.current = id
    setSelectedId(id)
    const epoch = ++requestRef.current
    try {
      const { detail, history: hist } = await loadDetailAndHistory(id)
      if (epoch !== requestRef.current) return
      setCurrent(detail)
      setHistory(hist)
      setError(null)
    } catch (err) {
      if (epoch !== requestRef.current) return
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [loadDetailAndHistory])

  const create = useCallback(async (title: string) => {
    // 写操作不 catch：失败交给 EvaluationView.action 转 toast/inline alert，
    // 让用户看到后端原始消息（如「evaluation already exists」）。
    const result = await api.createEvaluation(title)
    pendingSelectRef.current = result.evaluation_id
    await reload()
    return result.evaluation_id
  }, [reload])

  const rename = useCallback(async (id: string, title: string) => {
    await api.renameEvaluation(id, title)
    await reload()
  }, [reload])

  const remove = useCallback(async (id: string) => {
    await api.deleteEvaluation(id)
    await reload()
  }, [reload])

  const addSession = useCallback(async (id: string, sessionId: string, taskLabel: string) => {
    await api.addEvaluationSession(id, sessionId, taskLabel)
    // 仅刷新当前 Evaluation 视图；列表也要更新（member_count / title 投影）。
    const epoch = ++requestRef.current
    const [detail, list] = await Promise.all([
      api.evaluation(id),
      loadList(),
    ])
    if (epoch !== requestRef.current) return
    setCurrent(detail)
    setEvaluations(list)
  }, [loadList])

  const removeSession = useCallback(async (id: string, sessionId: string) => {
    await api.removeEvaluationSession(id, sessionId)
    const epoch = ++requestRef.current
    const [detail, list] = await Promise.all([
      api.evaluation(id),
      loadList(),
    ])
    if (epoch !== requestRef.current) return
    setCurrent(detail)
    setEvaluations(list)
  }, [loadList])

  // 可选 Session = 去除「当前 Evaluation 成员」与「其他 active Evaluation 成员」。
  // 客户端只是早期 UI 过滤（不让用户选到已知冲突项），最终约束以 API 为准；
  // 竞态下后端 400 仍把原始 error 抛给页面展示。
  const availableSessions = (() => {
    const currentIds = new Set(current?.members.map((m) => m.session_id) ?? [])
    const otherActiveIds = new Set<string>()
    for (const ev of evaluations) {
      if (ev.deleted || ev.evaluation_id === current?.evaluation_id) continue
      for (const m of ev.members ?? []) otherActiveIds.add(m.session_id)
    }
    const blocked = new Set<string>([...currentIds, ...otherActiveIds])
    return allSessions.filter((s) => !blocked.has(s.id))
  })()

  return {
    evaluations, current, history, selectedId, error, loading,
    availableSessions,
    select, create, rename, remove, addSession, removeSession, reload,
  }
}
