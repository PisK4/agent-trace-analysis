// 时间拆解的展示格式化：徽章与弹层共用。数据来自 /api/sessions/{id}/timing。
import type { TimingSummary } from '../api/types'

/** 三档时长：33 ms / 13.6 s / 13m22s。inspectorModel 的 durLabel 没有分档，
 * 长会话会显示成 802.0 s，这里单独给一分钟进位。 */
export function fmtDur(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m${String(s).padStart(2, '0')}s`
}

export const QUALITY_LABEL: Record<TimingSummary['llm_quality'], string> = {
  measured: '实测',
  placeholder: '占位值（来源不带耗时）',
  'n/a': '无数据',
}
