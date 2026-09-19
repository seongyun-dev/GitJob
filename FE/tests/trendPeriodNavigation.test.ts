import assert from 'node:assert/strict'
import { test } from 'node:test'
import { periodNavigation } from '../src/features/trend/model/periodNavigation.ts'

/*
 * 기간 이동 회귀 · 티켓 S15P21E102-329.
 *
 * 이 기능은 한 번 사라졌다 — S15P21E102-345 가 순위 API 로 옮기면서 같이 들어냈고,
 * 그때 근거는 "순위 API 가 어떤 기간이 게시됐는지 모른다"였다. 이제 API 가 그것을
 * 답하므로 기능이 성립하고, 다시 잃지 않도록 값으로 고정한다.
 */

const WEEKS = ['2026-03-02', '2026-08-31', '2026-09-07']

test('기간이 셋이면 이동할 수 있다', () => {
  const state = periodNavigation(WEEKS, '2026-09-07')

  assert.notEqual(state, null)
  assert.deepEqual(state?.periods, WEEKS)
})

test('기본 선택은 최신 기간이다', () => {
  // 서버가 기간을 생략한 요청에 최신으로 답한다. 화면은 그 답을 그대로 읽는다.
  const state = periodNavigation(WEEKS, '2026-09-07')

  assert.equal(state?.selected, WEEKS[WEEKS.length - 1])
})

test('고른 기간을 그대로 읽는다', () => {
  const state = periodNavigation(WEEKS, '2026-08-31')

  assert.equal(state?.selected, '2026-08-31')
  // 카드는 이 위치에서 양쪽으로 움직인다.
  const index = state?.periods.indexOf('2026-08-31')
  assert.equal(index, 1)
  assert.equal(state?.periods[(index ?? 0) - 1], '2026-03-02')
  assert.equal(state?.periods[(index ?? 0) + 1], '2026-09-07')
})

test('기간이 하나뿐이면 버튼을 만들지 않는다', () => {
  // 누를 수는 있는데 아무 일도 안 나는 버튼을 두지 않는다.
  assert.equal(periodNavigation(['2026-08'], '2026-08'), null)
})

test('게시된 기간이 없으면 이동도 없다', () => {
  assert.equal(periodNavigation([], null), null)
  assert.equal(periodNavigation(undefined, undefined), null)
})

test('목록 밖 기간이 선택돼 있으면 최신으로 되돌린다', () => {
  // 그대로 두면 이전·다음이 모두 disabled 가 되어 되돌아올 수 없는 곳에 갇힌다.
  const state = periodNavigation(WEEKS, '2020-01-01')

  assert.equal(state?.selected, '2026-09-07')
})

test('주간과 월별의 선택은 서로 섞이지 않는다', () => {
  /*
   * 두 카드는 각자 자기 응답으로 상태를 만든다. 한쪽을 옮겼다고 다른 쪽이 따라
   * 움직이면 나란히 놓은 이유가 없어진다. 모집단도 기간도 달라(주간 4,045 ·
   * 월별 695) 같은 축에 놓을 수 없다.
   */
  const weekly = periodNavigation(WEEKS, '2026-08-31')
  const monthly = periodNavigation(['2026-05', '2026-06', '2026-07', '2026-08'], '2026-08')

  assert.equal(weekly?.selected, '2026-08-31')
  assert.equal(monthly?.selected, '2026-08')
  assert.equal(weekly?.periods.length, 3)
  assert.equal(monthly?.periods.length, 4)
})

test('순위가 비어 있어도 게시 목록만 있으면 이동은 살아 있다', () => {
  /*
   * 아직 집계되지 않은 기간으로 옮겨 간 카드에서 화살표를 없애면 되돌아올 수 없다.
   * 그래서 이동은 순위 행이 아니라 서버가 준 기간 목록으로 만든다.
   */
  const state = periodNavigation(WEEKS, '2026-03-02')

  assert.notEqual(state, null)
  assert.equal(state?.selected, '2026-03-02')
  // 첫 기간이라 이전은 없고 다음은 있다.
  assert.equal(state?.periods.indexOf('2026-03-02'), 0)
  assert.equal(state?.periods[1], '2026-08-31')
})
