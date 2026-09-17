import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatDemandBasis,
  formatCollectedAt,
  summarizeDataGaps,
} from '../src/features/matching/model/presentation.ts'

test('demand basis distinguishes observed, comparable, and strict denominator counts', () => {
  assert.equal(
    formatDemandBasis({
      targetRole: 'BACKEND',
      regions: [],
      careerLevels: [],
      asOf: '2026-09-15T22:30:04Z',
      jobCount: 13,
      inputJobCount: 1_744,
      duplicateJobCount: 0,
      excludedJobCount: 1_452,
      reviewJobCount: 279,
      matchingJobCount: 253,
    }),
    '관측 1,744건 · 상세 비교 후보 253건 · 수요 산정 13건',
  )
})

test('collection timestamp is rendered in fixed Korean time', () => {
  assert.equal(formatCollectedAt('2026-09-15T22:30:04.308945Z'), '2026.09.16 07:30')
  assert.equal(formatCollectedAt(null), '수집 기준 미정')
  assert.equal(formatCollectedAt('not-a-date'), '수집 기준 미정')
})

test('internal data gap codes are grouped into user-facing messages', () => {
  const messages = summarizeDataGaps([
    'ANALYSIS_PARTIAL',
    'COHORT_RECORDS_REQUIRE_REVIEW:278',
    'FILES_SKIPPED',
    'PERSONAL_LEVEL_SCOPE_INCOMPLETE:java',
    'REPOSITORY_ANALYSIS_FAILED',
    'REPOSITORY_COVERAGE_INCOMPLETE:1132888449',
    'REPOSITORY_COVERAGE_INCOMPLETE:1346733327',
    'TECHNOLOGY:java:INCONSISTENT_LEVEL_FACTS',
    'TECHNOLOGY:java:DIRECT_DEPENDENCY_UNCONFIRMED',
  ])

  assert.deepEqual(messages, [
    '검토가 필요한 공고 278건은 계산에서 제외했습니다.',
    '저장소 2개의 분석 범위가 불완전해 일부 기술은 미판정으로 처리했습니다.',
    '일부 기술은 사용 근거 또는 개인 기여 범위가 충분하지 않아 보수적으로 판정했습니다.',
  ])
  assert.equal(messages.some((message) => /ANALYSIS_|TECHNOLOGY:|\d{10}/.test(message)), false)
})

test('unknown data gap code never leaks its raw value', () => {
  assert.deepEqual(summarizeDataGaps(['NEW_INTERNAL_REASON:secret']), [
    '일부 데이터의 판정 근거가 충분하지 않아 결과가 달라질 수 있습니다.',
  ])
})
