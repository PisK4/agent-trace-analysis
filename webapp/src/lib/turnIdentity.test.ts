import { describe, expect, it } from 'vitest'
import { sameTurnIdentity, turnIdentityKey, turnIdentityLabel, turnIdentityOf } from './turnIdentity'

describe('turn identity', () => {
  it('keeps T1 from different runs distinct', () => {
    expect(turnIdentityKey({ run_id: 1, turn_number: 1 })).toBe('run:1:turn:1')
    expect(turnIdentityKey({ run_id: 2, turn_number: 1 })).toBe('run:2:turn:1')
    expect(sameTurnIdentity({ run_id: 1, turn_number: 1 }, { run_id: 2, turn_number: 1 })).toBe(false)
  })

  it('uses canonical and observed labels without guessing a run', () => {
    expect(turnIdentityLabel({ run_id: 1, turn_number: 1 })).toBe('R1 · T1')
    expect(turnIdentityLabel({ observed_turn_ordinal: 1 })).toBe('Observed 1')
    expect(turnIdentityOf({ turn: 1 })).toEqual({ kind: 'observed', ordinal: 1 })
    expect(turnIdentityLabel({ turn_number: 1 })).toBeNull()
  })
})
