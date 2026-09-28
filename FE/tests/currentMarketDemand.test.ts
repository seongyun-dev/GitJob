import assert from 'node:assert/strict'
import test from 'node:test'

import { jobDemandsPath } from '../src/features/matching/model/jobDemandsQuery.ts'
import { marketDemandView, marketRankRows } from '../src/features/trend/model/marketDemand.ts'
import { hasComputedValue } from '../src/shared/api/computeState.ts'
import { queryKeys } from '../src/shared/api/queryKeys.ts'
import type { JobDemandDto } from '../src/features/matching/api/types.ts'

/** 화면이 하는 것과 똑같이 공용 판정을 거쳐 본다. 규칙을 테스트가 다시 쓰지 않는다. */
function viewOf(demand: JobDemandDto | undefined) {
  return marketDemandView(demand, hasComputedValue(demand))
}

/*
 * 목표 직무가 없는 요청은 시장 전체를 묻는 것이다 · 티켓 S15P21E102-339.
 *
 * BE는 `targetRole`의 **유무**로 모집단을 고른다. 빈 문자열이나 "undefined"를 실어
 * 보내면 그것은 "직무를 고르지 않았다"가 아니라 그런 이름의 직무를 달라는 요청이 되고,
 * C는 422를 준다. 그래서 파라미터 자체가 없어야 한다.
 */

test('current market request carries no targetRole parameter at all', () => {
  const path = jobDemandsPath({ regions: [], careerLevels: [] })

  assert.equal(path, '/job-demands')
  assert.ok(!path.includes('targetRole'))
  assert.ok(!path.includes('undefined'))
  assert.ok(!path.includes('null'))
})

test('an explicitly empty role is still a market request, not a role named ""', () => {
  assert.equal(jobDemandsPath({ targetRole: '', regions: [], careerLevels: [] }), '/job-demands')
})

test('role-specific request keeps sending targetRole and the existing filters', () => {
  const path = jobDemandsPath({
    targetRole: 'BACKEND',
    regions: ['서울'],
    careerLevels: ['신입'],
  })

  assert.equal(path, '/job-demands?targetRole=BACKEND&regions=%EC%84%9C%EC%9A%B8&careerLevels=%EC%8B%A0%EC%9E%85')
})

test('market request still forwards the shared filters', () => {
  assert.equal(
    jobDemandsPath({ regions: ['서울'], careerLevels: [] }),
    '/job-demands?regions=%EC%84%9C%EC%9A%B8',
  )
})

test('market and role query keys never collide', () => {
  const market = JSON.stringify(queryKeys.currentMarketDemands([], []))
  const role = JSON.stringify(queryKeys.jobDemands('BACKEND', [], []))
  // 예전 훅은 직무가 없으면 '' 를 키에 넣었다. 그 키와도 겹치면 안 된다.
  const blankRole = JSON.stringify(queryKeys.jobDemands('', [], []))

  assert.notEqual(market, role)
  assert.notEqual(market, blankRole)
  // 필터가 다르면 시장 키도 갈라져야 한다. 아니면 조건을 바꿔도 옛 숫자가 남는다.
  assert.notEqual(market, JSON.stringify(queryKeys.currentMarketDemands(['서울'], [])))
})

function dto(overrides: Partial<JobDemandDto> = {}): JobDemandDto {
  return {
    dataStatus: 'READY',
    statusReason: 'NONE',
    retryAfterSec: null,
    basis: {
      targetRole: null,
      regions: [],
      careerLevels: [],
      asOf: '2026-09-18T03:00:00Z',
      jobCount: 1621,
      inputJobCount: 1700,
      duplicateJobCount: 12,
      excludedJobCount: 67,
      reviewJobCount: 0,
      matchingJobCount: 747,
    },
    technologies: [
      {
        techId: 'java',
        rank: 1,
        requiredCount: 240,
        preferredCount: 44,
        generalCount: 0,
        totalCount: 284,
        requiredRatio: 0.148,
        preferredRatio: 0.027,
        generalRatio: 0,
        totalRatio: 0.175,
      },
      {
        techId: 'python',
        rank: 2,
        requiredCount: 200,
        preferredCount: 53,
        generalCount: 0,
        totalCount: 253,
        requiredRatio: 0.123,
        preferredRatio: 0.032,
        generalRatio: 0,
        totalRatio: 0.156,
      },
    ],
    ...overrides,
  }
}

test('ready market view keeps the ranks and counts the server sent', () => {
  const view = viewOf(dto())

  assert.equal(view.kind, 'ROWS')
  assert.deepEqual(
    view.rows.map((row) => [row.techId, row.rank, row.totalCount, row.totalRatio]),
    [
      ['java', 1, 284, 0.175],
      ['python', 2, 253, 0.156],
    ],
  )
  // 비율을 건수/분모로 다시 만들지 않는다. 284/1621 은 0.1752... 라 값이 달라진다.
  assert.equal(view.rows[0]?.totalRatio, 0.175)
})

test('market view reports the population it was measured against', () => {
  const view = viewOf(dto())

  assert.equal(view.jobCount, 1621)
  assert.equal(view.matchingJobCount, 747)
  assert.equal(view.asOf, '2026-09-18T03:00:00Z')
})

test('the bar scale comes from the top row, never from a fixed number', () => {
  const view = viewOf(dto())

  assert.equal(view.topCount, 284)
})

test('preparing market has no rows to draw and says so instead of showing zero', () => {
  const view = viewOf(
    dto({ dataStatus: 'PREPARING', statusReason: 'COHORT_NOT_PREPARED', technologies: [] }),
  )

  assert.equal(view.kind, 'PENDING')
  assert.deepEqual(view.rows, [])
})

test('a ready market with nothing collected yet is empty, not preparing', () => {
  const view = viewOf(dto({ technologies: [] }))

  assert.equal(view.kind, 'EMPTY')
})

test('states with no value are left to the shared status panel', () => {
  for (const dataStatus of ['NO_DATA', 'FAILED', 'INSUFFICIENT_DATA', 'NOT_SUPPORTED'] as const) {
    assert.equal(viewOf(dto({ dataStatus })).kind, 'PENDING')
  }
})

test('partial still has a value, so its rows are drawn', () => {
  /*
   * `hasComputedValue` 가 PARTIAL 을 값 있는 상태로 보는 이유가 여기 그대로 적용된다.
   * 일부를 못 읽었다고 나머지로 나온 순위를 감추면, 사용자는 있는 근거조차 못 본다.
   */
  const view = viewOf(dto({ dataStatus: 'PARTIAL', statusReason: 'PARTIAL_MARKET' }))

  assert.equal(view.kind, 'ROWS')
  assert.equal(view.rows.length, 2)
})

test('a view without data is pending rather than empty', () => {
  const view = viewOf(undefined)

  assert.equal(view.kind, 'PENDING')
  assert.deepEqual(view.rows, [])
  assert.equal(view.jobCount, null)
})

/*
 * 카드 한 장으로 옮긴 뒤 · 티켓 S15P21E102-342.
 *
 * 분포는 상단 대형 섹션이 아니라 `채용공고 수요` 카드 안에 들어간다. 카드는 세 출처가
 * 공유하므로, 여기서 만드는 줄의 모양이 옆 카드와 같아야 열 너비와 높이가 갈라지지 않는다.
 */

test('card rows keep the server rank and cap at the card limit', () => {
  const rows = marketRankRows(viewOf(dto()), 1)

  assert.equal(rows.length, 1)
  assert.equal(rows[0]?.rank, 1)
  assert.equal(rows[0]?.techId, 'java')
})

test('card row shows the posting count, and the bar reads the raw value', () => {
  const rows = marketRankRows(viewOf(dto()), 10)

  assert.equal(rows[0]?.share, '284건')
  assert.equal(rows[0]?.observedValue, 284)
})

test('a snapshot has no previous period, so the change column stays empty', () => {
  const rows = marketRankRows(viewOf(dto()), 10)

  assert.ok(rows.every((row) => row.delta === '—'))
  assert.ok(rows.every((row) => row.direction === null))
})

test('nothing to draw yields no card rows at all', () => {
  assert.deepEqual(marketRankRows(viewOf(undefined), 10), [])
  assert.deepEqual(marketRankRows(viewOf(dto({ technologies: [] })), 10), [])
})

test('a failed market keeps the server verdict instead of looking like waiting', () => {
  const view = viewOf(dto({ dataStatus: 'FAILED', statusReason: 'COMPUTE_FAILED' }))

  assert.equal(view.kind, 'PENDING')
  // FAILED 를 PREPARING 으로 그리면 기다리면 낫는 상태로 읽힌다.
  assert.equal(view.status, 'FAILED')
})

test('the server verdict rides along on every kind', () => {
  assert.equal(viewOf(dto()).status, 'READY')
  assert.equal(viewOf(dto({ technologies: [] })).status, 'READY')
  assert.equal(viewOf(dto({ dataStatus: 'PARTIAL' })).status, 'PARTIAL')
  assert.equal(viewOf(dto({ dataStatus: 'NO_DATA' })).status, 'NO_DATA')
  // 아직 조회 전이라 판정 자체가 없을 때만 준비 중이다.
  assert.equal(viewOf(undefined).status, 'PREPARING')
})
