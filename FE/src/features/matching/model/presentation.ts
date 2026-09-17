import type { Basis } from '@/features/matching/api/types'

const KOREAN_NUMBER = new Intl.NumberFormat('ko-KR')

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
      `검토가 필요한 공고 ${KOREAN_NUMBER.format(Number(reviewCount))}건은 계산에서 제외했습니다.`,
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
/** 서로 다른 공고 모집단을 한 숫자인 것처럼 보이지 않게 단계별로 표시한다. */
export function formatDemandBasis(basis: Basis): string {
  const format = (value: number) => value.toLocaleString('ko-KR')
  const parts: string[] = []
  if (basis.inputJobCount != null) {
    parts.push(`관측 ${format(basis.inputJobCount)}건`)
  }
  if (basis.matchingJobCount != null) {
    parts.push(`상세 비교 후보 ${format(basis.matchingJobCount)}건`)
  }
  if (basis.jobCount != null) {
    parts.push(`수요 산정 ${format(basis.jobCount)}건`)
  }
  return parts.join(' · ')
}
