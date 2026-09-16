import type { EvidenceLevel } from '@/shared/types/domain'

/**
 * 매칭 계열 화면이 그리는 값의 타입 (S15P21E102-279).
 *
 * `src/mocks/types.ts`에 있던 것을 여기로 옮겼다. 그쪽은 조회 API가 없던 동안 디자인
 * fixture가 쓰던 자리이고, 이제 실제 계약이 생겼으므로 화면 타입이 `features/` 안에
 * 있어야 한다. **`features/`가 `@/mocks`를 import하지 않는 것이 규칙이다** — 그래야
 * 운영 빌드에 fixture가 섞이지 않는다.
 *
 * 서버 DTO(`../api/types.ts`)와 나눈 이유는 둘의 관심이 다르기 때문이다. 서버 DTO는
 * 계약이라 마음대로 바꿀 수 없고, 이쪽은 화면이 그리기 좋은 모양이다. 변환은
 * `../api/adapter.ts` 한 곳에서만 한다.
 */

/**
 * 공고 기술요건 대조 표시 · 화면 02·16.
 *
 * `UNKNOWN`이 네 번째 값인 것이 핵심이다. C는 "요구를 해석하지 못했다"와 "충족하지
 * 못했다"를 구분해서 주는데, 둘을 `NONE`으로 합치면 화면이 판정하지 않은 기술을
 * 미보유로 표시한다. `WEAK`는 Evidence는 있는데 요구 Level에 미달인 경우다.
 */
export type RequirementMark = 'HAVE' | 'WEAK' | 'NONE' | 'UNKNOWN'

/** 공고 한 건이 요구하는 절 하나. 절은 기술 여러 개의 OR일 수 있다. */
export interface JobRequirement {
  /** 화면 표시용 이름. 지금은 Registry `tech_id`를 그대로 쓴다. */
  techName: string
  mark: RequirementMark
  /** 공고가 수준을 말하지 않았으면 `null`. 기본값으로 채우지 않는다. */
  requiredLevel: EvidenceLevel | null
}

/** 공고 한 건 · 화면 02. */
export interface JobPostingView {
  id: string
  title: string
  companyName: string
  /** 근무지. 공고가 밝히지 않았으면 `null`. */
  region: string | null
  /** 경력 조건. 공고가 밝히지 않았으면 `null`. */
  career: string | null
  /** 마감 표기. 원본이 없으면 `null`이고 화면은 그 칸을 비운다. */
  deadline: string | null
  sourceSite: string | null
  sourceUrl: string | null
  /** `FULL`만 "필수 전체 충족"이다. 나머지는 배지를 붙이지 않는다. */
  requiredStatus: string
  required: JobRequirement[]
  preferred: JobRequirement[]
  /** 해석하지 못한 요구. 부족으로 세지 않고 따로 보여 준다. */
  unresolved: { requirementKind: string; reason: string; knownTechIds: string[] }[]
}

/**
 * Skill Gap 판정 · 화면 17.
 *
 * `UNDETERMINED`가 `NO_EVIDENCE`와 다른 값인 것이 이 화면의 핵심이다. 평가하지 않은
 * 기술은 부족으로 세지 않는다.
 */
export type SkillGapVerdict = 'MET' | 'LEVEL_SHORT' | 'NO_EVIDENCE' | 'UNDETERMINED'

/** Skill Gap 표의 한 행 · 화면 17. */
export interface SkillGapRowView {
  techName: string
  /** 필수로 요구한 공고 수. 수요 집계에 없으면 `null`. */
  requiredCount: number | null
  /** 우대로 요구한 공고 수. 요구가 없으면 `null`(0건과 구분한다). */
  preferredCount: number | null
  /** 내 Personal Level. 판정되지 않았으면 `null`이며 "미보유"가 아니다. */
  personalLevel: EvidenceLevel | null
  verdict: SkillGapVerdict
  verdictText: string
  /**
   * 이 기술 하나만 채웠을 때 늘어나는 공고 수. C가 상위 후보에만 계산하므로 대부분
   * `null`이다. **행끼리 더하지 않는다** — 같은 공고가 여러 행에 걸쳐 있다.
   */
  fillDelta: number | null
}

export interface SkillGapGroupView {
  verdict: SkillGapVerdict
  title: string
  description: string
  rows: SkillGapRowView[]
}

export interface SkillGapSummaryView {
  basisText: string
  requiredTechCount: number
  metCount: number
  gapCount: number
  gapBreakdown: string
  undeterminedCount: number
}

/** What-if로 새로 충족되는 공고 한 건 · 화면 03. */
export interface WhatIfJobView {
  id: string
  title: string
  /** `서울 · 신입` 형태. 값이 없는 축은 빠진다. */
  meta: string
  sourceUrl: string | null
}

/** 다음 학습 기술 후보 · 화면 10·03 공용. */
export interface NextSkillView {
  techId: string
  rank: number
  techName: string
  /** 현재 Personal Level. 판정되지 않았으면 `null`. */
  fromLevel: EvidenceLevel | null
  /** 현재 필수 전체 충족 공고 수. 계산되지 않았으면 `null`. */
  currentFullMatch: number | null
  projectedFullMatch: number | null
  increasedCount: number | null
  /** 이 기술을 필수로 요구한 공고 수. */
  requiredCount: number | null
  /** 추천 근거. 점수가 아니라 C가 만든 문장이다. */
  reasons: string[]
  /** 선행 기술 중 판정하지 못한 것. 누락된 선행과 섞지 않는다. */
  unknownPrerequisiteTechIds: string[]
  missingPrerequisiteTechIds: string[]
}
