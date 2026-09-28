import assert from 'node:assert/strict'
import test from 'node:test'

import { groupTrendRowsByPeriod } from '../src/features/trend/model/periodRows.ts'
import {
  resolveEmptySourceStatus,
  summarizeTrendLoad,
} from '../src/features/trend/model/sourceStatus.ts'

/**
 * 서버 판정 보존과 부분 실패 노출 · 티켓 S15P21E102-329.
 *
 * 개요 화면은 기술별 detail 상답을 최대 10개 모아 카드를 만든다. 그 과정에서 두 가지를
 * 잃을 수 있고, 이 파일이 둘을 고정한다.
 *
 * 1. point가 없는 원천의 `dataStatus`. HTTP 200 안의 `FAILED`·`PREPARING`을 화면이
 *    `NO_DATA`("아직 집계된 기간이 없습니다")로 바꿔 말하면 안 된다. 서버 판정은
 *    point 유무와 무관하게 따로 온다.
 * 2. 10개 중 일부 요청이 실패한 사실. 남은 9개로 만든 순위가 10개 완전 성공처럼
 *    보이면 사용자는 빠진 기술을 알 수 없다.
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
  points: ReturnType<typeof point>[],
  dataStatus: string,
  statusReason = 'TREND_SAMPLE_NOTE',
) {
  return {
    sourceId,
    cSource: 'WEEKLY_REPO_ACTIVITY',
    dataStatus: dataStatus as never,
    statusReason,
    unit: 'EVENTS',
    metric: 'gh_archive_event_count',
    granularity: 'WEEK',
    periods: points.map((item) => item.period),
    points,
    reasons: [],
  }
}

// ---------------------------------------------------------------------------
// D1. point가 없어도 서버 판정은 남는다
// ---------------------------------------------------------------------------

/** 화면이 하는 것과 같은 순서로 빈 원천의 상태를 정한다. */
function judge(grouped: ReturnType<typeof groupTrendRowsByPeriod>, requestFailed = false) {
  const entry = grouped.get('GITHUB_WEEKLY')
  return {
    periods: entry?.periods ?? [],
    ...resolveEmptySourceStatus(
      (entry?.judgements ?? []).map((item) => item.status),
      requestFailed,
    ),
  }
}

test('point 가 없는 원천도 서버가 내린 dataStatus 와 statusReason 을 들고 있다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [source('GITHUB_WEEKLY', [], 'PREPARING', 'TREND_INPUT_PENDING')] },
  ])

  const entry = grouped.get('GITHUB_WEEKLY')
  assert.deepEqual(entry?.periods, [])
  assert.deepEqual(entry?.judgements, [
    { techId: 'java', status: 'PREPARING', statusReason: 'TREND_INPUT_PENDING' },
  ])
  // 화면이 그 판정을 그대로 쓴다 — NO_DATA 로 바뀌지 않는다.
  assert.equal(judge(grouped).status, 'PREPARING')
})

test('200 응답 안의 FAILED 는 조회가 성공했어도 빈 카드에서 FAILED 로 남는다', () => {
  const grouped = groupTrendRowsByPeriod([
    { techId: 'java', sources: [source('GITHUB_WEEKLY', [], 'FAILED', 'TREND_COMPUTE_FAILED')] },
  ])

  assert.equal(judge(grouped, false).status, 'FAILED')
})

test('PREPARING + 빈 points 는 NO_DATA 로 바뀌지 않는다', () => {
  assert.equal(resolveEmptySourceStatus(['PREPARING'], false).status, 'PREPARING')
})

test('200 응답 안의 FAILED + 빈 points 는 FAILED 로 남는다', () => {
  // 요청 자체는 성공했으므로 requestFailed 는 false 다. 그래도 FAILED 여야 한다 —
  // 이것이 "아직 집계된 기간이 없습니다"로 보이면 장애가 정상 상태로 읽힌다.
  assert.equal(resolveEmptySourceStatus(['FAILED'], false).status, 'FAILED')
})

test('NO_DATA + 빈 points 는 NO_DATA 다', () => {
  assert.equal(resolveEmptySourceStatus(['NO_DATA'], false).status, 'NO_DATA')
})

test('여러 기술의 판정이 섞이면 가장 심각한 것을 택한다', () => {
  // 카드는 원천당 상태 하나만 보여준다. 축소해서 말하면 실제 문제가 가려진다.
  assert.equal(resolveEmptySourceStatus(['NO_DATA', 'FAILED'], false).status, 'FAILED')
  assert.equal(resolveEmptySourceStatus(['NO_DATA', 'PREPARING'], false).status, 'PREPARING')
  assert.equal(
    resolveEmptySourceStatus(['NOT_SUPPORTED', 'NO_DATA'], false).status,
    'NO_DATA',
  )
})

test('서버 판정이 하나도 없고 요청이 실패했으면 FAILED 다', () => {
  // 원천이 어느 상답에도 없었던 경우. 그때만 요청 수준 실패로 판정한다.
  assert.equal(resolveEmptySourceStatus([], true).status, 'FAILED')
})

test('서버 판정이 없고 요청도 실패하지 않았으면 NO_DATA 다', () => {
  assert.equal(resolveEmptySourceStatus([], false).status, 'NO_DATA')
})

test('판정마다 사용자에게 보일 이유 문구가 서로 다르다', () => {
  const failed = resolveEmptySourceStatus(['FAILED'], false).scopeNote
  const preparing = resolveEmptySourceStatus(['PREPARING'], false).scopeNote
  const empty = resolveEmptySourceStatus(['NO_DATA'], false).scopeNote

  assert.notEqual(failed, empty)
  assert.notEqual(preparing, empty)
  // 실패를 "집계된 기간이 없다"로 설명하지 않는다.
  assert.ok(!failed.includes('집계된 기간이 없'))
  assert.ok(!preparing.includes('집계된 기간이 없'))
})

// ---------------------------------------------------------------------------
// D2. 부분 실패는 화면에 드러난다
// ---------------------------------------------------------------------------

/**
 * 순위에 실제로 들어간 기술 수를 화면과 같은 방법으로 센다.
 *
 * 화면은 `query.data`가 있는 상답만 모아 순위를 만든다(`loadedDtos`). 그래서 "빠진
 * 기술"은 오류 플래그가 켜진 요청이 아니라 **값을 내놓지 못한 요청**이다. 둘은 같지
 * 않다 — `retry: false`에 `staleTime`이 5분이라, 캐시를 들고 있던 기술이 재조회에서
 * 실패하면 `isError`가 켜진 채로도 값은 그대로 순위에 남는다.
 */
function loadedCount(queries: readonly { data?: unknown; isError: boolean }[]): number {
  return queries.filter((query) => query.data !== undefined).length
}

test('10 개 기술이 모두 순위에 들어가면 알릴 것이 없다', () => {
  assert.equal(summarizeTrendLoad(10, 10), null)
})

test('10 개 중 9 개만 들어가면 부분 성공을 알리고 성공 수를 밝힌다', () => {
  const summary = summarizeTrendLoad(10, 9)

  assert.equal(summary?.kind, 'PARTIAL')
  assert.equal(summary?.loaded, 9)
  assert.equal(summary?.total, 10)
  // 9/10 이 10/10 처럼 보이지 않도록 숫자가 문구에 들어간다.
  assert.ok(summary?.description.includes('9'))
  assert.ok(summary?.description.includes('10'))
})

test('하나도 들어가지 못하면 부분 성공이 아니라 실패다', () => {
  const summary = summarizeTrendLoad(10, 0)

  assert.equal(summary?.kind, 'FAILED')
  assert.equal(summary?.loaded, 0)
})

test('조회 대상이 없으면 알릴 것이 없다', () => {
  assert.equal(summarizeTrendLoad(0, 0), null)
})

test('재조회에 실패해도 값을 들고 있는 기술은 빠진 기술이 아니다', () => {
  /*
   * `isError` 를 그대로 세면 이 경우가 "10 개 중 9 개만 성공" 으로 보고된다. 그런데
   * 순위에는 열 개가 모두 있으므로 "빠져 있습니다" 는 사실이 아니다. 없는 실패를
   * 지어내는 것도 실패를 숨기는 것과 같은 종류의 거짓이다.
   */
  const queries = [
    ...Array.from({ length: 9 }, () => ({ data: { techId: 'ok' }, isError: false })),
    { data: { techId: 'stale' }, isError: true },
  ]

  assert.equal(loadedCount(queries), 10)
  assert.equal(summarizeTrendLoad(queries.length, loadedCount(queries)), null)
})

test('값을 내놓지 못한 요청만 빠진 기술로 센다', () => {
  const queries = [
    ...Array.from({ length: 9 }, () => ({ data: { techId: 'ok' }, isError: false })),
    { data: undefined, isError: true },
  ]

  assert.equal(loadedCount(queries), 9)
  assert.equal(summarizeTrendLoad(queries.length, loadedCount(queries))?.loaded, 9)
})
