// Evaluation 数据层：列表与当前详情分开请求，写入后只刷新当前资源。
import { useCallback, useEffect, useState } from 'react'
import { api } from './client'
import type { EvaluationDetail, EvaluationSummary } from './types'

export function useEvaluations() {
  const [evaluations, setEvaluations] = useState<EvaluationSummary[]>([])
  const [current, setCurrent] = useState<EvaluationDetail | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const loadList = useCallback(async () => {
    const page = await api.evaluations()
    const list = (page.evaluations ?? []).map((item) => ({
      ...item,
      member_count: item.member_count ?? item.members?.length ?? 0,
    }))
    setEvaluations(list)
    return list
  }, [])

  const loadDetail = useCallback(async (id: string) => {
    const detail = await api.evaluation(id)
    setCurrent(detail)
    return detail
  }, [])

  const reload = useCallback(async () => {
    try {
      const list = await loadList()
      const id = selectedId && list.some((item) => item.evaluation_id === selectedId)
        ? selectedId
        : list.find((item) => !item.deleted)?.evaluation_id ?? null
      setSelectedId(id)
      if (id) await loadDetail(id)
      else setCurrent(null)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [loadDetail, loadList, selectedId])

  useEffect(() => { void reload() }, [reload])

  const select = useCallback(async (id: string) => {
    setSelectedId(id)
    try {
      await loadDetail(id)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [loadDetail])

  const create = useCallback(async (title: string) => {
    const result = await api.createEvaluation(title)
    await reload()
    await select(result.evaluation_id)
  }, [reload, select])

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
    await loadDetail(id)
    await loadList()
  }, [loadDetail, loadList])

  const removeSession = useCallback(async (id: string, sessionId: string) => {
    await api.removeEvaluationSession(id, sessionId)
    await loadDetail(id)
    await loadList()
  }, [loadDetail, loadList])

  return {
    evaluations, current, selectedId, error, loading,
    select, create, rename, remove, addSession, removeSession, reload,
  }
}
