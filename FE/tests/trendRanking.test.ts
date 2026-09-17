import assert from 'node:assert/strict'
import test from 'node:test'

import { rankObservableRows } from '../src/features/trend/model/ranking.ts'

test('ranks only READY observations by their numeric value and retains unobserved rows separately', () => {
  const result = rankObservableRows([
    { techId: 'zero', dataStatus: 'READY' as const, value: 0 },
    { techId: 'largest', dataStatus: 'READY' as const, value: 18 },
    { techId: 'missing', dataStatus: 'NO_DATA' as const, value: null },
    { techId: 'insufficient', dataStatus: 'INSUFFICIENT_DATA' as const, value: null },
    { techId: 'middle', dataStatus: 'READY' as const, value: 7 },
  ])

  assert.deepEqual(
    result.observed.map(({ techId, rank, value }) => ({ techId, rank, value })),
    [
      { techId: 'largest', rank: 1, value: 18 },
      { techId: 'middle', rank: 2, value: 7 },
      { techId: 'zero', rank: 3, value: 0 },
    ],
  )
  assert.equal(result.maximumObservedValue, 18)
  assert.deepEqual(
    result.unobserved.map(({ techId, dataStatus }) => ({ techId, dataStatus })),
    [
      { techId: 'missing', dataStatus: 'NO_DATA' },
      { techId: 'insufficient', dataStatus: 'INSUFFICIENT_DATA' },
    ],
  )
})
