import assert from 'node:assert/strict'
import test from 'node:test'

import { pollInterval } from '../src/features/matching/model/polling.ts'

const preparing = {
  dataStatus: 'PREPARING' as const,
  statusReason: 'COMPUTE_PENDING',
  retryAfterSec: 5,
}

test('matching polling stops when the latest request failed despite cached preparing data', () => {
  assert.equal(pollInterval(preparing, true), false)
})

test('matching polling follows the server delay only while preparing without an error', () => {
  assert.equal(pollInterval(preparing, false), 5_000)
  assert.equal(
    pollInterval({ ...preparing, retryAfterSec: null, statusReason: 'COHORT_NOT_PREPARED' }, false),
    30_000,
  )
  assert.equal(pollInterval({ ...preparing, dataStatus: 'READY' }, false), false)
})
