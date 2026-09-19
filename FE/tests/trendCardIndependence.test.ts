import assert from 'node:assert/strict'
import test from 'node:test'

import * as githubTrend from '../src/features/trend/model/githubTrendTechnologies.ts'
import { pendingSourceStatus } from '../src/features/trend/model/githubTrendTechnologies.ts'
import { resolveEmptySourceStatus } from '../src/features/trend/model/sourceStatus.ts'

/*
 * GitHub 트렌드는 목표 직무와 무관하다 · 티켓 S15P21E102-345.
 *
 * 계약이 그렇게 말한다 — `docs/be/c-compute-public-api.md` §4.8 은 `targetRole` 을
 * **JOB 출처에만** 요구한다. 그런데 화면이 조회할 기술 목록을 직무별 수요 응답에서
 * 뽑아 쓰는 바람에, 직무를 고르지 않으면 GitHub 카드가 통째로 사라졌다.
 *
 * 그래서 조회 대상 기술은 어느 응답에도 기대지 않는 고정 목록이다. 이것은 "무엇을
 * 물어볼지"이지 "무엇이 상위인지"가 아니다 — 카드 안의 순위는 여전히 서버가 준
 * 관측값으로만 만든다.
 */

test('a source still loading is preparing, not empty', () => {
  // 조회가 끝나기 전에 "데이터 없음"을 적으면 아직 모르는 것을 없다고 말하는 것이 된다.
  const judged = pendingSourceStatus()

  assert.equal(judged.status, 'PREPARING')
  assert.ok(judged.scopeNote.length > 0)
})

test('a settled source keeps the server verdict it already had', () => {
  // 조회가 끝난 뒤의 판정은 기존 규칙 그대로다. 이 티켓이 바꾸는 것은 "끝나기 전"뿐이다.
  assert.equal(resolveEmptySourceStatus(['FAILED'], false).status, 'FAILED')
  assert.equal(resolveEmptySourceStatus([], true).status, 'FAILED')
  assert.equal(resolveEmptySourceStatus([], false).status, 'NO_DATA')
})

test('a source still loading does not claim it could not be queried', () => {
  const judged = pendingSourceStatus()

  // "조회 불가"는 못 물었다는 말이다. 묻고 있는 중에 그렇게 적으면 안 된다.
  assert.notEqual(judged.basis, '조회 불가')
  assert.equal(judged.basis, '불러오는 중')
})


test('the screen no longer carries a technology list of its own', () => {
  /*
   * -345 에서는 이 모듈이 기술 열 개를 들고 있었다. 그러면 카드가 보여 주는 것이
   * "이 기간에 많이 관측된 기술"이 아니라 "우리가 고른 열 개 중의 순위"가 된다.
   * -346 이 순위 API 를 열면서 그 목록은 사라졌다.
   */
  const exported = Object.keys(githubTrend)

  assert.deepEqual(exported, ['pendingSourceStatus'])
  assert.ok(!exported.some((name) => name.includes('TECH')))
})
