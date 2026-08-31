// Runtime Turn 的展示与分组唯一入口：canonical identity 不能只用 turn number。

export interface TurnIdentityFields {
  run_id?: number | null
  turn_number?: number | null
  observed_turn_ordinal?: number | null
  runId?: number | null
  turnNumber?: number | null
  observedOrdinal?: number | null
  /** 旧服务端字段：没有 Runtime identity 时只作为 observed 兼容值。 */
  turn?: number | null
}

export type TurnIdentity =
  | { kind: 'canonical'; runId: number; turnNumber: number }
  | { kind: 'observed'; ordinal: number }

const positive = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value) && value > 0

/** 先读 Runtime canonical identity，再读 runless observed ordinal；不猜测缺失的 Run。 */
export function turnIdentityOf(value: TurnIdentityFields | null | undefined): TurnIdentity | null {
  if (!value) return null
  const runId = value.run_id ?? value.runId
  const turnNumber = value.turn_number ?? value.turnNumber
  if (positive(runId) && positive(turnNumber)) return { kind: 'canonical', runId, turnNumber }
  const observed = value.observed_turn_ordinal ?? value.observedOrdinal
  if (positive(observed)) return { kind: 'observed', ordinal: observed }
  // 旧投影只有 session-global turn；标成 observed，避免伪造 Rn · Tn。
  if (positive(value.turn)) return { kind: 'observed', ordinal: value.turn }
  return null
}

export function turnIdentityKey(value: TurnIdentityFields | TurnIdentity | null | undefined): string | null {
  const identity = value && 'kind' in value && (value.kind === 'canonical' || value.kind === 'observed') ? value : turnIdentityOf(value)
  if (!identity) return null
  return identity.kind === 'canonical'
    ? `run:${identity.runId}:turn:${identity.turnNumber}`
    : `observed:${identity.ordinal}`
}

export function turnIdentityLabel(value: TurnIdentityFields | TurnIdentity | null | undefined): string | null {
  const identity = value && 'kind' in value && (value.kind === 'canonical' || value.kind === 'observed') ? value : turnIdentityOf(value)
  if (!identity) return null
  return identity.kind === 'canonical'
    ? `R${identity.runId} · T${identity.turnNumber}`
    : `Observed ${identity.ordinal}`
}

export function sameTurnIdentity(a: TurnIdentityFields | null | undefined, b: TurnIdentityFields | null | undefined): boolean {
  return turnIdentityKey(a) === turnIdentityKey(b)
}

/** 表格折叠态兼容旧投影数字 key，同时让 Runtime key 保持跨 Run 唯一。 */
export function rowTurnKey(value: TurnIdentityFields | null | undefined): string | number | null {
  if (!value) return null
  if (positive(value.run_id ?? value.runId) && positive(value.turn_number ?? value.turnNumber)) return turnIdentityKey(value)
  if (positive(value.observed_turn_ordinal ?? value.observedOrdinal)) return turnIdentityKey(value)
  return positive(value.turn) ? value.turn : null
}

export function rowTurnLabel(value: TurnIdentityFields | null | undefined): string | null {
  return turnIdentityLabel(value)
}
