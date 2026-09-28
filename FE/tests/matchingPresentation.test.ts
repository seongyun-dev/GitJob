import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatDemandBasis,
  formatCollectedAt,
  formatJobDeadline,
  presentUnresolvedRequirement,
  summarizeDataGaps,
} from '../src/features/matching/model/presentation.ts'

const technologyNameFor = (techId: string) =>
  ({ csharp: 'C#', dotnet: '.NET', sql: 'SQL' })[techId as 'csharp' | 'dotnet' | 'sql'] ??
  '알 수 없는 기술'

test('demand basis presents the active matching population without a strict subset', () => {
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
    '관측 1,744건 · 공고 253건',
  )
})

test('collection timestamp is rendered in fixed Korean time', () => {
  assert.equal(formatCollectedAt('2026-09-15T22:30:04.308945Z'), '2026.09.16 07:30')
  assert.equal(formatCollectedAt(null), '수집 기준 미정')
  assert.equal(formatCollectedAt('not-a-date'), '수집 기준 미정')
})

test('job deadline preserves a specified time without leaking ISO timestamps', () => {
  assert.equal(formatJobDeadline('2026-10-14T00:00:00+09:00'), '2026.10.14.')
  assert.equal(formatJobDeadline('2026-10-13T15:00:00Z'), '2026.10.14.')
  assert.equal(formatJobDeadline('2026-10-14T18:30:00+09:00'), '2026.10.14. 18:30')
  assert.equal(formatJobDeadline('2026-10-14T09:30:00Z'), '2026.10.14. 18:30')
  assert.equal(formatJobDeadline(null), null)
  assert.equal(formatJobDeadline('not-a-date'), null)
})

test('unresolved requirement codes and registry ids become user-facing labels', () => {
  assert.deepEqual(
    presentUnresolvedRequirement(
      {
        requirementKind: 'REQUIRED',
        reason: 'TECHNOLOGY_MAPPING_UNRESOLVED',
        knownTechIds: ['csharp', 'dotnet'],
      },
      technologyNameFor,
    ),
    {
      requirementLabel: '필수',
      reasonText: '일부 기술 표현을 확인하지 못해 자동 판정에서 제외했습니다.',
      technologyNames: ['C#', '.NET'],
    },
  )

  assert.deepEqual(
    presentUnresolvedRequirement(
      {
        requirementKind: 'PREFERRED',
        reason: 'LOGIC_UNSUPPORTED',
        knownTechIds: ['sql'],
      },
      technologyNameFor,
    ),
    {
      requirementLabel: '우대',
      reasonText: '복합 조건을 정확하게 해석할 수 없어 자동 판정을 보류했습니다.',
      technologyNames: ['SQL'],
    },
  )
})

test('unresolved requirement passes only the technology id to a multi-argument name resolver', () => {
  const technologyNameWithSuppliedFallback = (
    techId: string,
    suppliedName?: string | null,
  ) => suppliedName?.trim() || technologyNameFor(techId)

  assert.deepEqual(
    presentUnresolvedRequirement(
      {
        requirementKind: 'REQUIRED',
        reason: 'TECHNOLOGY_MAPPING_UNRESOLVED',
        knownTechIds: ['csharp', 'dotnet'],
      },
      technologyNameWithSuppliedFallback,
    ).technologyNames,
    ['C#', '.NET'],
  )
})

test('unknown unresolved requirement values never leak raw internal codes', () => {
  const presented = presentUnresolvedRequirement(
    {
      requirementKind: 'NEW_KIND',
      reason: 'NEW_INTERNAL_REASON:secret',
      knownTechIds: ['unknown-internal-id'],
    },
    technologyNameFor,
  )

  assert.deepEqual(presented, {
    requirementLabel: '요구',
    reasonText: '자동으로 해석하지 못해 판정을 보류한 요구사항입니다.',
    technologyNames: ['알 수 없는 기술'],
  })
  assert.equal(JSON.stringify(presented).includes('NEW_INTERNAL_REASON'), false)
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
    '검토가 필요한 공고 278건이 있어 일부 결과를 미판정으로 표시합니다.',
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
