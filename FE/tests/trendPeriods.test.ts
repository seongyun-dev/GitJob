import assert from 'node:assert/strict'
import test from 'node:test'

import { pointsForSource, pointsSinceMonth } from '../src/features/trend/model/periods.ts'

/**
 * 월별·공고 원천의 월 범위 하한 · 티켓 S15P21E102-329.
 *
 * 이 함수는 더 이상 주간에 쓰이지 않는다. 주간 head는 누적이고 BE가 기간 selector를
 * 받지 않으므로 월 하한으로 주차를 잘라낼 근거가 없다.
 */
test('월 범위 하한은 그 월부터의 기간만 남기고 상한은 두지 않는다', () => {
  const points = [
    { period: '2026-03-02', value: 10 },
    { period: '2026-06-01', value: 20 },
    { period: '2026-09-07', value: 30 },
  ]

  assert.deepEqual(pointsSinceMonth(points, '2026-06'), [points[1], points[2]])
})

/**
 * 원천별로 월 범위를 적용할지 정한다 · 티켓 S15P21E102-329.
 *
 * 예전에는 주간 point 도 선택한 월 하한으로 잘랐다. 주간 head 는 누적이고 BE 가 주간
 * selector 에 기간을 받지 않으므로(보내면 C 가 422 로 거절한다) 그 절단에는 근거가
 * 없었다 — "최근 3개월" 을 눌렀다고 그보다 앞선 주차의 관측이 사라지는 것은 아니다.
 * 이 구분을 코드 주석이 아니라 테스트로 고정한다.
 */
test('주간 원천은 선택한 월 범위로 잘리지 않는다', () => {
  const points = [
    { period: '2026-03-02', value: 10 },
    { period: '2026-06-01', value: 20 },
    { period: '2026-09-07', value: 30 },
  ]

  assert.deepEqual(pointsForSource('GITHUB_WEEKLY', points, '2026-08'), points)
})

test('월별·공고 원천은 선택한 월 하한을 적용한다', () => {
  const points = [
    { period: '2026-03', value: 10 },
    { period: '2026-06', value: 20 },
    { period: '2026-09', value: 30 },
  ]

  assert.deepEqual(pointsForSource('GITHUB_ARCHIVE', points, '2026-06'), [points[1], points[2]])
  assert.deepEqual(pointsForSource('JOB', points, '2026-06'), [points[1], points[2]])
})

test('월 범위를 고르지 않았으면 어느 원천도 자르지 않는다', () => {
  const points = [{ period: '2026-03', value: 10 }]

  assert.deepEqual(pointsForSource('GITHUB_ARCHIVE', points, undefined), points)
  assert.deepEqual(pointsForSource('GITHUB_WEEKLY', points, undefined), points)
})
