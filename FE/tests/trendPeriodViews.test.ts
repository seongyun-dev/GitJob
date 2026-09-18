import assert from 'node:assert/strict'
import test from 'node:test'

import { groupTrendRowsByPeriod } from '../src/features/trend/model/periodRows.ts'
import { rankObservableRows } from '../src/features/trend/model/ranking.ts'
import { summarizeTrendLoad } from '../src/features/trend/model/sourceStatus.ts'

/**
 * 기간별 묶음과 기간별 순위 · 티켓 S15P21E102-329.
 *
 * 개요 카드가 기간을 이동하려면 기간별 행이 있어야 한다. 기간 목록은 상답에 실제로 있는
 * point의 합집합이고, 순위 계약(S15P21E102-327)은 기간이 바뀌어도 그대로다.
 *
 * `groupTrendRowsByPeriod`와 `rankObservableRows`를 함께 호출하는 이유는 화면이 정확히
 * 그 순서로 쓰기 때문이다. 둘을 잇는 `toTrendPeriodViews`는 `@/` 런타임 import가 있어
 * `node --test`에서 불러올 수 없고, 그 함수가 하는 일은 이 둘을 잇는 것뿐이다.
 */

function point(period: string, value: number | null) {
  return {
    period,
    status: null,
    value,
    denominator: null,
    ratio: null,
    absoluteChange: null,
    relativeChange: null,
  }
}

function source(
  sourceId: string,
  granularity: string,
  points: ReturnType<typeof point>[],
  dataStatus = 'READY',
) {
  return {
    sourceId,
    cSource: 'WEEKLY_REPO_ACTIVITY',
    dataStatus: dataStatus as never,
    statusReason: 'TREND_SAMPLE_NOTE',
    unit: 'EVENTS',
    metric: 'gh_archive_event_count',
    granularity,
    periods: points.map((item) => item.period),
    points,
    reasons: [],
  }
}

const weeklySource = (points: ReturnType<typeof point>[], dataStatus?: string) =>
  source('GITHUB_WEEKLY', 'WEEK', points, dataStatus)

/** 화면이 하는 것과 같은 순서로 한 기간의 순위를 만든다. */
function rankAt(
  grouped: ReturnType<typeof groupTrendRowsByPeriod>,
  sourceId: 'GITHUB_WEEKLY' | 'GITHUB_ARCHIVE' | 'JOB',
  period: string,
) {
  const rows = grouped.get(sourceId)?.rowsByPeriod.get(period) ?? []
  return rankObservableRows(rows)
}

test('기간 목록은 상답에 있는 point 의 합집합이며 오름순이다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [weeklySource([point('2026-09-07', 10), point('2026-03-02', 4)])] },
    { techId: 'react', sources: [weeklySource([point('2026-09-07', 7)])] },
  ])

  assert.deepEqual(grouped.get('GITHUB_WEEKLY')?.periods, ['2026-03-02', '2026-09-07'])
})

test('기간을 바꾸면 그 기간 기준으로 순위가 다시 매겨진다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [weeklySource([point('2026-03-02', 4), point('2026-09-07', 10)])] },
    { techId: 'react', sources: [weeklySource([point('2026-03-02', 9), point('2026-09-07', 7)])] },
  ])

  // 앞선 주차에서는 React 가 1위다.
  assert.deepEqual(
    rankAt(grouped, 'GITHUB_WEEKLY', '2026-03-02').observed.map((row) => [row.rank, row.techId]),
    [
      [1, 'react'],
      [2, 'java'],
    ],
  )
  // 최신 주차에서는 순위가 뒤집힌다.
  assert.deepEqual(
    rankAt(grouped, 'GITHUB_WEEKLY', '2026-09-07').observed.map((row) => [row.rank, row.techId]),
    [
      [1, 'java'],
      [2, 'react'],
    ],
  )
})

test('행은 기술·원천 단위 dataStatus 와 statusReason 을 그대로 들고 간다', () => {
  // 이 묶음 단계는 상태를 해석하지 않는다. 순위에 넣을지 말지는 `rankObservableRows`
  // 가 정하고, 그 정책이 바뀌어도 여기서 옮기는 값은 같아야 한다.
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [weeklySource([point('2026-09-07', 10)], 'INSUFFICIENT_DATA')] },
  ])
  const row = grouped.get('GITHUB_WEEKLY')?.rowsByPeriod.get('2026-09-07')?.[0]

  assert.equal(row?.techId, 'java')
  assert.equal(row?.dataStatus, 'INSUFFICIENT_DATA')
  assert.equal(row?.statusReason, 'TREND_SAMPLE_NOTE')
  assert.equal(row?.period, '2026-09-07')
  assert.equal(row?.value, 10)
})

test('PARTIAL 도 기간별 순위에 오른다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [weeklySource([point('2026-09-07', 10)], 'PARTIAL')] },
  ])
  const ranked = rankAt(grouped, 'GITHUB_WEEKLY', '2026-09-07')

  assert.deepEqual(
    ranked.observed.map((row) => [row.rank, row.techId, row.dataStatus]),
    [[1, 'java', 'PARTIAL']],
  )
})

test('믿을 수 없는 상태는 기간별 순위에서도 빠진다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [weeklySource([point('2026-09-07', 999)], 'FAILED')] },
    { techId: 'react', sources: [weeklySource([point('2026-09-07', 7)])] },
  ])
  const ranked = rankAt(grouped, 'GITHUB_WEEKLY', '2026-09-07')

  assert.deepEqual(
    ranked.observed.map((row) => row.techId),
    ['react'],
  )
  assert.deepEqual(
    ranked.unobserved.map((row) => row.techId),
    ['java'],
  )
})

test('값이 null 인 기간은 목록에 남고 순위에서만 빠진다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [weeklySource([point('2026-03-02', null), point('2026-09-07', 5)])] },
  ])

  assert.deepEqual(grouped.get('GITHUB_WEEKLY')?.periods, ['2026-03-02', '2026-09-07'])
  assert.deepEqual(rankAt(grouped, 'GITHUB_WEEKLY', '2026-03-02').observed, [])
  assert.deepEqual(
    rankAt(grouped, 'GITHUB_WEEKLY', '2026-03-02').unobserved.map((row) => row.techId),
    ['java'],
  )
  assert.equal(rankAt(grouped, 'GITHUB_WEEKLY', '2026-09-07').observed.length, 1)
})

test('주간과 월별의 기간 목록은 서로 독립이다', () => {
  const grouped = groupTrendRowsByPeriod([
    {
      techId: 'java',
      sources: [
        weeklySource([point('2026-09-07', 10)]),
        source('GITHUB_ARCHIVE', 'MONTH', [point('2026-07', 100), point('2026-08', 120)]),
      ],
    },
  ])

  assert.deepEqual(grouped.get('GITHUB_WEEKLY')?.periods, ['2026-09-07'])
  assert.deepEqual(grouped.get('GITHUB_ARCHIVE')?.periods, ['2026-07', '2026-08'])
})

test('모르는 원천은 통째로 버린다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [source('SOMETHING_ELSE', 'MONTH', [point('2026-08', 3)], 'READY')] },
  ])

  assert.equal(grouped.size, 0)
})

test('point 가 없는 원천은 기간 목록이 비어 있다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [weeklySource([], 'NO_DATA')] },
  ])

  assert.deepEqual(grouped.get('GITHUB_WEEKLY')?.periods, [])
})

// ---------------------------------------------------------------------------
// READY 기준선과 기간 이동 시 함께 바뀌는 값
// ---------------------------------------------------------------------------

test('READY 와 값이 있는 기간은 그대로 순위에 오른다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [weeklySource([point('2026-09-07', 10)])] },
  ])
  const ranked = rankAt(grouped, 'GITHUB_WEEKLY', '2026-09-07')

  assert.deepEqual(
    ranked.observed.map((row) => [row.rank, row.techId, row.dataStatus, row.value]),
    [[1, 'java', 'READY', 10]],
  )
  assert.deepEqual(ranked.unobserved, [])
})

test('기간을 옮기면 순위·값·진행도 기준·상태·상태 사유가 함께 바뀐다', () => {
  /*
   * 카드 안의 막대 길이는 `maximumObservedValue` 를 분모로 쓴다. 기간을 옮겼는데 그
   * 분모가 이전 기간 값으로 남아 있으면, 순위만 바뀌고 막대는 엉뚱한 비율로 남는다.
   */
  const grouped = groupTrendRowsByPeriod([
    {
      techId: 'java',
      sources: [source('GITHUB_WEEKLY', 'WEEK', [point('2026-03-02', 4), point('2026-09-07', 10)])],
    },
    {
      techId: 'react',
      sources: [
        source(
          'GITHUB_WEEKLY',
          'WEEK',
          [point('2026-03-02', 9), point('2026-09-07', 7)],
          'PARTIAL',
        ),
      ],
    },
  ])

  const earlier = rankAt(grouped, 'GITHUB_WEEKLY', '2026-03-02')
  const latest = rankAt(grouped, 'GITHUB_WEEKLY', '2026-09-07')

  // 순위와 값
  assert.deepEqual(
    earlier.observed.map((row) => [row.rank, row.techId, row.value]),
    [
      [1, 'react', 9],
      [2, 'java', 4],
    ],
  )
  assert.deepEqual(
    latest.observed.map((row) => [row.rank, row.techId, row.value]),
    [
      [1, 'java', 10],
      [2, 'react', 7],
    ],
  )
  // 진행도의 분모도 그 기간 것이다.
  assert.equal(earlier.maximumObservedValue, 9)
  assert.equal(latest.maximumObservedValue, 10)
  // 상태와 상태 사유는 그 기간 행의 것을 그대로 들고 간다.
  assert.deepEqual(
    latest.observed.map((row) => [row.techId, row.dataStatus, row.statusReason]),
    [
      ['java', 'READY', 'TREND_SAMPLE_NOTE'],
      ['react', 'PARTIAL', 'TREND_SAMPLE_NOTE'],
    ],
  )
})

// ---------------------------------------------------------------------------
// 기술별 병렬 조회의 부분 실패 · 티켓 S15P21E102-329 D2
// ---------------------------------------------------------------------------

/** 기술 `count` 개의 상세 상답. 한 기간에 기술마다 값이 하나씩 있다. */
function dtosFor(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    techId: `tech-${index}`,
    sources: [weeklySource([point('2026-09-07', count - index)])],
  }))
}

test('기술 10 개가 모두 오면 10 개가 순위에 오르고 알릴 것이 없다', () => {
  const grouped = groupTrendRowsByPeriod(dtosFor(10))

  assert.equal(rankAt(grouped, 'GITHUB_WEEKLY', '2026-09-07').observed.length, 10)
  assert.equal(summarizeTrendLoad(10, 10), null)
})

test('10 개 중 1 개가 실패해도 나머지 9 개는 순위에 남고 부분 실패가 드러난다', () => {
  // 실패한 기술의 상답은 화면에 도달하지 않는다. 남은 9 개로 순위를 만드는 것 자체는
  // 허용한다 — 하나 때문에 볼 수 있었던 아홉을 감추지 않는다.
  const grouped = groupTrendRowsByPeriod(dtosFor(9))
  const ranked = rankAt(grouped, 'GITHUB_WEEKLY', '2026-09-07')

  assert.equal(ranked.observed.length, 9)
  assert.deepEqual(
    ranked.observed.map((row) => row.rank),
    [1, 2, 3, 4, 5, 6, 7, 8, 9],
  )
  // 다만 9 개가 10 개 완전 성공처럼 보이면 안 된다.
  const summary = summarizeTrendLoad(10, 9)
  assert.equal(summary?.kind, 'PARTIAL')
  assert.equal(summary?.loaded, 9)
})

test('기술 조회가 전부 실패하면 순위가 비고 실패로 알린다', () => {
  const grouped = groupTrendRowsByPeriod([])

  assert.equal(grouped.get('GITHUB_WEEKLY'), undefined)
  assert.equal(summarizeTrendLoad(10, 0)?.kind, 'FAILED')
})
