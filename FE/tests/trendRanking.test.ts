import assert from 'node:assert/strict'
import test from 'node:test'

import { rankObservableRows } from '../src/features/trend/model/ranking.ts'

test('ranks READY and PARTIAL observations by numeric value and retains missing rows separately', () => {
  const result = rankObservableRows([
    { techId: 'zero', dataStatus: 'READY' as const, value: 0 },
    { techId: 'largest', dataStatus: 'READY' as const, value: 18 },
    { techId: 'missing', dataStatus: 'NO_DATA' as const, value: null },
    { techId: 'insufficient', dataStatus: 'INSUFFICIENT_DATA' as const, value: null },
    { techId: 'middle', dataStatus: 'READY' as const, value: 7 },
    { techId: 'quality-limited', dataStatus: 'PARTIAL' as const, value: 11 },
  ])

  assert.deepEqual(
    result.observed.map(({ techId, rank, value }) => ({ techId, rank, value })),
    [
      { techId: 'largest', rank: 1, value: 18 },
      { techId: 'quality-limited', rank: 2, value: 11 },
      { techId: 'middle', rank: 3, value: 7 },
      { techId: 'zero', rank: 4, value: 0 },
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

/*
 * 얇은 표본이라고 실측값을 숨기지 않는다 · 티켓 S15P21E102-327.
 *
 * Production TREND point 는 전부 `INSUFFICIENT_DATA` 인데 그 아래 수치는 실재한다
 * (2026-08 html 1,204,607 · javascript 878,599). 순위에서 빼면 화면은 "아무것도
 * 측정하지 못했다"고 말하게 되는데, 그것은 "표본이 얇다"와 다르고 더 틀린 말이다.
 *
 * 순위는 값이 있느냐로 가른다. 값이 없는 행만 순위를 받지 못한다.
 */

test('a thin sample with a real number still gets ranked', () => {
  const result = rankObservableRows([
    { techId: 'html', dataStatus: 'INSUFFICIENT_DATA' as const, value: 1_204_607 },
    { techId: 'javascript', dataStatus: 'INSUFFICIENT_DATA' as const, value: 878_599 },
    { techId: 'ready-but-smaller', dataStatus: 'READY' as const, value: 10 },
  ])

  assert.deepEqual(
    result.observed.map(({ techId, rank }) => ({ techId, rank })),
    [
      { techId: 'html', rank: 1 },
      { techId: 'javascript', rank: 2 },
      { techId: 'ready-but-smaller', rank: 3 },
    ],
  )
  assert.equal(result.maximumObservedValue, 1_204_607)
  assert.deepEqual(result.unobserved, [])
})

test('the status rides along with the ranked row and is not rewritten to READY', () => {
  const result = rankObservableRows([
    { techId: 'html', dataStatus: 'INSUFFICIENT_DATA' as const, value: 5 },
  ])

  assert.equal(result.observed[0]?.dataStatus, 'INSUFFICIENT_DATA')
})

test('only a missing value stays out of the ranking', () => {
  const result = rankObservableRows([
    { techId: 'counted', dataStatus: 'INSUFFICIENT_DATA' as const, value: 3 },
    { techId: 'not-measured', dataStatus: 'INSUFFICIENT_DATA' as const, value: null },
  ])

  assert.deepEqual(
    result.observed.map((row) => row.techId),
    ['counted'],
  )
  assert.deepEqual(
    result.unobserved.map((row) => row.techId),
    ['not-measured'],
  )
})

test('states whose numbers cannot be trusted are still kept out', () => {
  // 실패·미준비 응답도 잔여 수치를 달고 올 수 있다. 그것을 순위에 올리면
  // 실패를 측정처럼 보이게 한다.
  for (const dataStatus of ['FAILED', 'PREPARING', 'NOT_SUPPORTED', 'NO_DATA'] as const) {
    const result = rankObservableRows([{ techId: 'x', dataStatus, value: 99 }])
    assert.deepEqual(result.observed, [], `${dataStatus} must not be ranked`)
  }
})
