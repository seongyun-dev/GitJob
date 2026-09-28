import type { EvidenceLevel } from '@/shared/types/domain'

/**
 * fixture 전용 화면 타입.
 *
 * **`shared/types/`에 두지 않는 이유가 이 파일의 요점이다.** 아래 타입은 조회 API가
 * 없어 계약이 정해지지 않았다. 공용 폴더에 두면 다음 사람이 확정된 계약으로 읽고
 * 화면을 붙인다. BE 응답이 오면 그때 각 feature의 `api/types.ts`에 명세를 근거로 다시
 * 정의하고 여기서는 지운다.
 *
 * <h2>연결이 끝난 화면의 타입은 여기 없다 (S15P21E102-279)</h2>
 *
 * 공고 매칭 · Skill Gap · 추천 · What-if · Trend · 목표 직무는 실제 API에 연결됐고,
 * 그 화면 타입은 `features/matching/model/view.ts`와 `features/trend/model/view.ts`로
 * 옮겼다. 같은 개념의 타입이 두 곳에 있으면 한쪽만 고쳐지고, 그 차이가 곧 화면의
 * 판정 차이가 된다 — 실제로 `RequirementMark`는 연결하면서 `UNKNOWN`이 늘었다.
 *
 * Evidence 계열(S6·S7)은 여기에 없다. 그쪽은 티켓 208이 명세를 근거로 계약을 고정해
 * 두어 `features/evidence/api/types.ts`를 그대로 쓴다.
 *
 * 출처는 확정 디자인 `GitJob_FE_Final_v2_17screens.html`의 데모 스크립트다. 화면
 * 번호는 그 파일의 아트보드 번호(01~17)를 따른다.
 */

/**
 * 공고 기술요건 대조 표시.
 *
 * 연결된 화면은 `features/matching/model/view.ts`의 네 값짜리 타입을 쓴다. 여기 것은
 * `11 Technology Detail`의 fixture가 쓰는 세 값짜리이며, 그 화면은 아직 조회 API가
 * 없다.
 */
export type RequirementMark = 'HAVE' | 'WEAK' | 'NONE'

/** 공고 한 건이 요구하는 기술 하나. */
export interface JobRequirementFixture {
  techName: string
  mark: RequirementMark
}

/** What-if로 새로 충족되는 공고 한 건 · 화면 11에서 후보 설명에 함께 쓴다. */
export interface WhatIfJobFixture {
  title: string
  /** `서울 · 신입~3년` 형태. */
  meta: string
  chips: JobRequirementFixture[]
  /** 왜 새로 충족되는지 한 줄. */
  why: string
}

/** 다음 학습 기술 후보 · 화면 11 Technology Detail. */
export interface NextSkillFixture {
  techId: string
  /** `#1` 같은 순위 라벨. */
  rank: string
  techName: string
  /** 탭에 들어가는 짧은 이름. */
  shortName: string
  fromLevel: EvidenceLevel
  targetLevel: EvidenceLevel
  /** 현재 필수 전체 충족 공고 수. */
  currentFullMatch: number
  /** 목표 Level 확보를 가정했을 때의 수. */
  projectedFullMatch: number
  headline: string
  ctaLabel: string
  /** 추천 근거. 점수가 아니라 문장으로만 제시한다. */
  reasons: string[]
  newlyMatched: WhatIfJobFixture[]
}

/** 분석 대상 저장소 · 화면 06. */
export interface RepositoryFixture {
  id: string
  name: string
  /** `Java · Spring Boot · main`. */
  meta: string
  /** `최근 push 3일 전`. */
  lastPushText: string
  /** `Fork`, `Archived` 같은 표시. */
  flags: string[]
  /** 기본 선택 여부. */
  selected: boolean
}

/** 분석 단계 한 줄 · 화면 07. */
export interface AnalysisStepFixture {
  /** `STEP 01`. */
  no: string
  title: string
  description: string
  /** 단계별 진행 표기. `3개 확인`, `대기`. */
  progressText: string
  state: 'DONE' | 'RUNNING' | 'WAITING'
}

/** 저장소별 분석 진행 · 화면 07. */
export interface AnalysisRepoProgressFixture {
  name: string
  meta: string
  /** `완료 · 기술 11 확인`. */
  statusText: string
  state: 'DONE' | 'RUNNING' | 'WAITING'
}

/** 분석 이력 한 줄 · 화면 14. */
export interface AnalysisHistoryFixture {
  /** `오늘 10:42`. 상대 표기는 화면이 정하므로 문자열로 둔다. */
  at: string
  /** 대상 저장소 나열. */
  repositories: string
  /** 결과 요약. */
  resultText: string
  /** `JobStatus`가 아니라 `PARTIAL`도 쓰는 화면 표기다. */
  status: 'SUCCEEDED' | 'PARTIAL' | 'FAILED'
}
