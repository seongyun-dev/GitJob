import assert from 'node:assert/strict'
import test from 'node:test'

import { rankObservableRows } from '../src/features/trend/model/ranking.ts'

/**
 * 순위는 값의 유무로 갈린다 · 티켓 S15P21E102-327.
 *
 * 이전 계약은 `READY`만 순위에 넣었는데, 운영 TREND 데이터에는 `READY` 포인트가
 * 하나도 없어 화면이 통째로 비었다. 값이 있는 관측은 표본이 얇아도 측정된 사실이므로
 * 순위에 올리고, 얇다는 것은 `dataStatus`로 함께 전달해 카드가 표시한다.
 */

test('값이 있으면 INSUFFICIENT_DATA 여도 순위에 오른다', () => {
  const result = rankObservableRows([
    { techId: 'ready-zero', dataStatus: 'READY' as const, value: 0 },
    { techId: 'thin-largest', dataStatus: 'INSUFFICIENT_DATA' as const, value: 18 },
    { techId: 'ready-middle', dataStatus: 'READY' as const, value: 7 },
  ])

  assert.deepEqual(
    result.observed.map(({ techId, rank, value }) => ({ techId, rank, value })),
    [
      { techId: 'thin-largest', rank: 1, value: 18 },
      { techId: 'ready-middle', rank: 2, value: 7 },
      { techId: 'ready-zero', rank: 3, value: 0 },
    ],
  )
  assert.equal(result.maximumObservedValue, 18)
  assert.deepEqual(result.unobserved, [])
})

test('순위에 오른 행도 원래 dataStatus를 그대로 들고 간다', () => {
  const { observed } = rankObservableRows([
    { techId: 'thin', dataStatus: 'INSUFFICIENT_DATA' as const, value: 5 },
    { techId: 'solid', dataStatus: 'READY' as const, value: 9 },
  ])

  assert.deepEqual(
    observed.map(({ techId, dataStatus }) => ({ techId, dataStatus })),
    [
      { techId: 'solid', dataStatus: 'READY' },
      { techId: 'thin', dataStatus: 'INSUFFICIENT_DATA' },
    ],
  )
})

test('값이 없으면 상태와 무관하게 순위에서 빠진다', () => {
  const result = rankObservableRows([
    { techId: 'observed', dataStatus: 'READY' as const, value: 3 },
    { techId: 'no-data', dataStatus: 'NO_DATA' as const, value: null },
    { techId: 'thin-null', dataStatus: 'INSUFFICIENT_DATA' as const, value: null },
    { techId: 'ready-null', dataStatus: 'READY' as const, value: null },
  ])

  assert.deepEqual(
    result.observed.map(({ techId, rank }) => ({ techId, rank })),
    [{ techId: 'observed', rank: 1 }],
  )
  assert.deepEqual(
    result.unobserved.map(({ techId, dataStatus }) => ({ techId, dataStatus })),
    [
      { techId: 'no-data', dataStatus: 'NO_DATA' },
      { techId: 'thin-null', dataStatus: 'INSUFFICIENT_DATA' },
      { techId: 'ready-null', dataStatus: 'READY' },
    ],
  )
})

test('관측이 하나도 없으면 최대값은 null 이다', () => {
  const result = rankObservableRows([
    { techId: 'a', dataStatus: 'INSUFFICIENT_DATA' as const, value: null },
  ])

  assert.deepEqual(result.observed, [])
  assert.equal(result.maximumObservedValue, null)
})

test('같은 값이면 입력 순서를 유지한다', () => {
  const { observed } = rankObservableRows([
    { techId: 'first', dataStatus: 'INSUFFICIENT_DATA' as const, value: 4 },
    { techId: 'second', dataStatus: 'READY' as const, value: 4 },
  ])

  assert.deepEqual(
    observed.map(({ techId, rank }) => ({ techId, rank })),
    [
      { techId: 'first', rank: 1 },
      { techId: 'second', rank: 2 },
    ],
  )
})

test('신뢰할 수 없는 상태는 값이 남아 있어도 순위에서 빠진다', () => {
  // BE 의 `Source.of()` 는 points 를 가진 채 payload status 를 그대로 옮기므로
  // (`ComputeState.ofTrend`), FAILED · NOT_SUPPORTED · PREPARING · NO_DATA 에도
  // 수치가 남아 있을 수 있다. 그 값은 의지할 수 없다.
  const result = rankObservableRows([
    { techId: 'failed', dataStatus: 'FAILED' as const, value: 999 },
    { techId: 'not-supported', dataStatus: 'NOT_SUPPORTED' as const, value: 888 },
    { techId: 'preparing', dataStatus: 'PREPARING' as const, value: 777 },
    { techId: 'no-data', dataStatus: 'NO_DATA' as const, value: 666 },
    { techId: 'thin', dataStatus: 'INSUFFICIENT_DATA' as const, value: 5 },
  ])

  assert.deepEqual(
    result.observed.map(({ techId, rank }) => ({ techId, rank })),
    [{ techId: 'thin', rank: 1 }],
  )
  assert.equal(result.maximumObservedValue, 5)
  assert.deepEqual(
    result.unobserved.map(({ techId }) => techId),
    ['failed', 'not-supported', 'preparing', 'no-data'],
  )
})

test('PARTIAL 은 READY 와 같은 사용 가능 상태라 순위에 오른다', () => {
  // `ComputeState.isReady()` 가 READY 와 PARTIAL 을 같은 묶음으로 본다.
  const { observed } = rankObservableRows([
    { techId: 'partial', dataStatus: 'PARTIAL' as const, value: 12 },
    { techId: 'ready', dataStatus: 'READY' as const, value: 3 },
  ])

  assert.deepEqual(
    observed.map(({ techId, rank }) => ({ techId, rank })),
    [
      { techId: 'partial', rank: 1 },
      { techId: 'ready', rank: 2 },
    ],
  )
})
