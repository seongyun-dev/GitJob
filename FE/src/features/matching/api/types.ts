import type { DataStatus } from '@/shared/types/domain'

/**
 * 매칭 계열 공개 API의 응답 계약 (S15P21E102-279).
 *
 * 원본은 `docs/be/c-compute-public-api.md` §4이고, 그 값들은 BE가 계산한 것이 아니라
 * C 계산 결과를 옮긴 것이다. **FE는 이 숫자들을 다시 만들지 않는다** — 충족 건수를
 * 목록에서 세거나, 비율을 분자·분모로 나누거나, 증가 건수를 더하지 않는다.
 *
 * `null`은 "없음"이 아니라 대개 "C가 주지 않았다"이다. 0으로 바꿔 그리면 화면이
 * "측정했더니 0이었다"고 말하게 된다.
 */

/** 계산 계열 응답이 공통으로 갖는 상태. */
export interface ComputeStateFields {
  dataStatus: DataStatus
  /** `COMPUTING`·`COHORT_NOT_PREPARED`·`INSUFFICIENT_EVIDENCE` 등. 폴링 간격과 문구를 정한다. */
  statusReason: string
  /** 있으면 이 간격으로 다시 묻는다. 없으면 화면이 기본 간격을 쓴다. */
  retryAfterSec: number | null
}

/** 이 수치가 무엇을 기준으로 나왔는지. 화면이 반드시 함께 표시한다. */
export interface Basis {
  targetRole: string | null
  regions: string[]
  careerLevels: string[]
  /** 공고 수집 기준 시각. C가 정한 값이다. */
  asOf: string | null
  /** 비교 대상 공고 수. 모든 비율의 분모다. */
  jobCount: number | null
}

export interface TargetDto {
  targetRole: string
  regions: string[]
  careerLevels: string[]
  /** 캐시 키. 서버가 만든다 — FE가 조합하면 같은 조건에 캐시가 두 벌 생긴다. */
  targetKey: string
  updatedAt: string
}

export interface JobMatchSummaryDto {
  totalCount: number
  /** 필수 전체 충족. C의 `current_count`다. */
  fullMatchCount: number | null
  /** C가 분포를 주지 않아 항상 `null`이다. 화면은 이 칸을 그리지 않는다. */
  nearMatchCount: number | null
  lowMatchCount: number | null
  conditionalCount: number
  /** 조건부라 목록에서 빠진 건수. 사라진 공고가 몇 건인지 말할 수 있어야 한다. */
  excludedConditionalCount: number
}

export interface ClauseDto {
  /** `HAVE`·`WEAK`·`NONE`·`UNKNOWN`. */
  mark: string
  techIds: string[]
  requiredLevel: string | null
  heldTechIds: string[]
  missingTechIds: string[]
  unknownTechIds: string[]
}

export interface ConditionDto {
  satisfiedCount: number
  unsatisfiedCount: number
  /** 충족 실패와 합치지 않는다. 요구를 해석하지 못한 절의 수다. */
  unknownCount: number
  fulfillmentRatio: number | null
  clauses: ClauseDto[]
  unresolved: { requirementKind: string; reason: string; knownTechIds: string[] }[]
}

export interface JobMatchItemDto {
  jobId: string
  title: string | null
  companyName: string | null
  sourceSite: string | null
  sourceUrl: string | null
  region: string | null
  careerLevel: string | null
  deadline: string | null
  eligibility: string | null
  /** `FULL`·`PARTIAL`·`NONE`·`UNKNOWN`·`NOT_APPLICABLE`. */
  requiredStatus: string | null
  fulfillmentRatio: number | null
  required: ConditionDto | null
  preferred: ConditionDto | null
}

export interface JobMatchListDto extends ComputeStateFields {
  basis: Basis
  summary: JobMatchSummaryDto | null
  dataGaps: string[]
  page: number
  perPage: number
  hasNext: boolean
  items: JobMatchItemDto[]
}

export interface JobMatchDetailDto extends ComputeStateFields {
  basis: Basis
  item: JobMatchItemDto | null
}

export interface SkillGapRowDto {
  techId: string
  /** `MET`·`LEVEL_SHORT`·`NO_EVIDENCE`·`UNDETERMINED`. */
  verdict: string
  requiredCount: number | null
  preferredCount: number | null
  personalLevel: string | null
  /** BE의 규칙이 배제할 수 있었던 최고 Level. 이 위는 "확인되지 않음"이다. */
  assessmentCeiling: string | null
  reasonCodes: string[]
  /** C가 상위 후보에만 계산한다. 대부분 `null`이며 0이 아니다. */
  fillDelta: number | null
}

export interface SkillGapDto extends ComputeStateFields {
  basis: Basis
  summary: {
    requiredTechCount: number
    metCount: number
    noEvidenceCount: number
    levelShortCount: number
    /** 미판정을 포함하지 않는다. */
    gapCount: number
    undeterminedCount: number
  } | null
  rows: SkillGapRowDto[]
  dataGaps: string[]
}

/** 분모는 같은 비교 집합의 공고 수다. 세 값이 서로 다른 계산에서 오면 안 된다. */
export interface WhatIfCountsDto {
  currentCount: number
  projectedCount: number
  increasedCount: number
}

export interface RecommendationDto extends ComputeStateFields {
  basis: Basis
  candidates: {
    techId: string
    rank: number
    personalLevel: string | null
    evidenceStatus: string | null
    demand: { requiredCount: number; requiredRatio: number; rank: number } | null
    whatIf: WhatIfCountsDto | null
    prerequisiteTechIds: string[]
    missingPrerequisiteTechIds: string[]
    unknownPrerequisiteTechIds: string[]
    reasonCodes: string[]
    /** C가 만든 설명 문장. 화면은 점수를 만들지 않고 이것을 그대로 쓴다. */
    reasons: string[]
    dataGaps: string[]
  }[]
  dataGaps: string[]
}

export interface WhatIfDto extends ComputeStateFields {
  basis: Basis
  techId: string | null
  /** 증가 건수와 아래 목록이 같은 응답에서 온다. 어긋날 수 없다. */
  counts: WhatIfCountsDto | null
  page: number
  perPage: number
  hasNext: boolean
  totalCount: number
  items: {
    jobId: string
    title: string | null
    companyName: string | null
    sourceSite: string | null
    sourceUrl: string | null
    region: string | null
    careerLevel: string | null
    deadline: string | null
  }[]
  dataGaps: string[]
}

export interface JobDemandDto extends ComputeStateFields {
  basis: Basis
  technologies: {
    techId: string
    rank: number
    requiredCount: number
    preferredCount: number
    generalCount: number
    totalCount: number
    requiredRatio: number
    preferredRatio: number
    generalRatio: number
    totalRatio: number
  }[]
}
