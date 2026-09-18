import assert from 'node:assert/strict'
import test from 'node:test'

import { pointsSinceMonth } from '../src/features/trend/model/periods.ts'

test('weekly detail points honor the selected month range without dropping the current week', () => {
  const points = [
    { period: '2026-03-02', value: 10 },
    { period: '2026-06-01', value: 20 },
    { period: '2026-09-07', value: 30 },
  ]

  assert.deepEqual(pointsSinceMonth(points, '2026-06'), [points[1], points[2]])
})
