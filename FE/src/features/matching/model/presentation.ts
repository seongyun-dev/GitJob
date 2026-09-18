import type { Basis } from '@/features/matching/api/types'

const KOREAN_NUMBER = new Intl.NumberFormat('ko-KR')
const SEOUL_DEADLINE = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

const UNRESOLVED_REASON_TEXT: Readonly<Record<string, string>> = {
  TECHNOLOGY_MAPPING_UNRESOLVED:
    '일부 기술 표현을 확인하지 못해 자동 판정에서 제외했습니다.',
  EVIDENCE_NOT_LOCATED:
    '요구사항이 나온 원문 위치를 확인하지 못해 자동 판정에서 제외했습니다.',
  NEGATION_UNSUPPORTED:
    '제외·부정 조건이 포함되어 자동 판정을 보류했습니다.',
  CARDINALITY_UNSUPPORTED:
    '기술 개수 조건이 포함되어 자동 판정을 보류했습니다.',
  LOGIC_UNSUPPORTED:
    '복합 조건을 정확하게 해석할 수 없어 자동 판정을 보류했습니다.',
}

export interface UnresolvedRequirementPresentation {
  requirementLabel: string
  reasonText: string
  technologyNames: string[]
}

/**
 * API의 마감 시각을 공고 화면의 날짜·시각 표기로 바꾼다.
 *
 * 계산 API의 값은 timezone을 포함한 ISO instant다. 브라우저·운영체제 timezone에 따라
 * 날짜가 달라지지 않도록 서비스 기준 시간인 Asia/Seoul을 명시한다. 파싱할 수 없는
 * 값은 원문을 노출하지 않는다.
 */
export function formatJobDeadline(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value.trim() === '') {
    return null
  }

  const deadline = new Date(value)
  if (Number.isNaN(deadline.getTime())) {
    return null
  }

  const parts = SEOUL_DEADLINE.formatToParts(deadline)
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((candidate) => candidate.type === type)?.value ?? ''
  const dateText = `${part('year')}.${part('month')}.${part('day')}.`
  const timeText = `${part('hour')}:${part('minute')}`

  // 수집기의 날짜형 마감은 다음 날 00:00 종료 경계로 정규화된다. 현재 API에는
  // 날짜형과 실제 자정 마감을 구분하는 필드가 없으므로 00:00만 날짜로 표시한다.
  return timeText === '00:00' ? dateText : `${dateText} ${timeText}`
}

/** 계산기의 판정 보류 사유를 사용자 문장으로 바꾸고 내부 enum·tech_id를 숨긴다. */
export function presentUnresolvedRequirement(
  item: {
    requirementKind: string
    reason: string
    knownTechIds: readonly string[]
  },
  technologyNameFor: (techId: string) => string,
): UnresolvedRequirementPresentation {
  const requirementLabel =
    item.requirementKind === 'REQUIRED'
      ? '필수'
      : item.requirementKind === 'PREFERRED'
        ? '우대'
        : '요구'

  return {
    requirementLabel,
    reasonText:
      UNRESOLVED_REASON_TEXT[item.reason] ??
      '자동으로 해석하지 못해 판정을 보류한 요구사항입니다.',
    technologyNames: item.knownTechIds.map((techId) => technologyNameFor(techId)),
  }
}

/** API의 ISO 시각을 공고 화면에서 쓰는 고정 KST 표기로 바꾼다. */
export function formatCollectedAt(value: string | null | undefined): string {
  if (value === null || value === undefined) {
    return '수집 기준 미정'
  }

  const at = new Date(value)
  if (Number.isNaN(at.getTime())) {
    return '수집 기준 미정'
  }

  const parts = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(at)
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((candidate) => candidate.type === type)?.value ?? ''

  return `${part('year')}.${part('month')}.${part('day')} ${part('hour')}:${part('minute')}`
}

/** 운영·판정용 data gap 코드를 사용자 안내로 묶는다. */
export function summarizeDataGaps(gaps: readonly string[]): string[] {
  const unique = new Set(gaps)
  const messages: string[] = []

  const reviewCount = [...unique]
    .map((gap) => /^COHORT_RECORDS_REQUIRE_REVIEW:(\d+)$/.exec(gap)?.[1])
    .find((value) => value !== undefined)
  if (reviewCount !== undefined) {
    messages.push(
      `검토가 필요한 공고 ${KOREAN_NUMBER.format(Number(reviewCount))}건이 있어 일부 결과를 미판정으로 표시합니다.`,
    )
  }

  const incompleteRepositoryCount = [...unique].filter((gap) =>
    gap.startsWith('REPOSITORY_COVERAGE_INCOMPLETE:'),
  ).length
  const hasRepositoryGap = [...unique].some(
    (gap) =>
      gap === 'ANALYSIS_PARTIAL' ||
      gap === 'FILES_SKIPPED' ||
      gap === 'REPOSITORY_ANALYSIS_FAILED' ||
      gap.startsWith('REPOSITORY_COVERAGE_INCOMPLETE:'),
  )
  if (hasRepositoryGap) {
    messages.push(
      incompleteRepositoryCount > 0
        ? `저장소 ${KOREAN_NUMBER.format(incompleteRepositoryCount)}개의 분석 범위가 불완전해 일부 기술은 미판정으로 처리했습니다.`
        : '일부 저장소를 완전히 분석하지 못해 일부 기술은 미판정으로 처리했습니다.',
    )
  }

  const hasTechnologyGap = [...unique].some(
    (gap) => gap.startsWith('TECHNOLOGY:') || gap.startsWith('PERSONAL_LEVEL_SCOPE_INCOMPLETE:'),
  )
  if (hasTechnologyGap) {
    messages.push(
      '일부 기술은 사용 근거 또는 개인 기여 범위가 충분하지 않아 보수적으로 판정했습니다.',
    )
  }

  const recognized = (gap: string) =>
    gap === 'ANALYSIS_PARTIAL' ||
    gap === 'FILES_SKIPPED' ||
    gap === 'REPOSITORY_ANALYSIS_FAILED' ||
    gap.startsWith('COHORT_RECORDS_REQUIRE_REVIEW:') ||
    gap.startsWith('REPOSITORY_COVERAGE_INCOMPLETE:') ||
    gap.startsWith('TECHNOLOGY:') ||
    gap.startsWith('PERSONAL_LEVEL_SCOPE_INCOMPLETE:')
  if ([...unique].some((gap) => !recognized(gap))) {
    messages.push('일부 데이터의 판정 근거가 충분하지 않아 결과가 달라질 수 있습니다.')
  }

  return messages
}
/** 사용자가 실제로 비교하는 공고 수. 이전 Snapshot은 matchingJobCount를 우선한다. */
export function activeMatchingJobCount(basis: Basis): number | null {
  return basis.matchingJobCount ?? basis.jobCount
}

/** 내부 strict 집합을 노출하지 않고 실제 비교 모집단을 표시한다. */
export function formatDemandBasis(basis: Basis): string {
  const format = (value: number) => value.toLocaleString('ko-KR')
  const parts: string[] = []
  if (basis.inputJobCount != null) {
    parts.push(`관측 ${format(basis.inputJobCount)}건`)
  }
  const activeCount = activeMatchingJobCount(basis)
  if (activeCount != null) {
    parts.push(`공고 ${format(activeCount)}건`)
  }
  return parts.join(' · ')
}
