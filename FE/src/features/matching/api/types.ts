import type { DataStatus, EvidenceLevel } from '@/shared/types/domain'

/**
 * 매칭 계열 조회 응답 타입 · 티켓 S15P21E102-281.
 *
 * BE 미구현 상태에서 **먼저** 고정하는 계약이다. 근거는 B조 API 명세서 v0.1이고,
 * 경로·메서드는 그 표에서 그대로 옮겼다.
 *
 *   - B-FN-013 목표 직무 조회·변경   `GET`·`PUT /me/target`
 *   - B-FN-014 직무 마스터 목록 조회 `GET /job-roles`
 *   - B-FN-015 관련 채용공고 목록    `GET /job-postings`
 *   - B-FN-015 기술 수요 집계 조회   `GET /job-demands`
 *   - B-FN-016 Skill Gap 조회        `GET /me/skill-gap`
 *   - B-FN-017 학습 기술 후보·What-if `GET /me/recommendations`
 *   - B-FN-018 학습 기술 선택·변경   `GET`·`PUT /me/learning-target`
 *
 * 티켓 208이 Evidence 계열에 한 것과 같은 방식이다. BE `-279`가 구현 중이므로 필드가
 * 확정되면 이 파일을 고치고, 그때 `api/*Api.ts`·`parseMatching.ts`가 함께 따라온다.
 * **화면 컴포넌트는 이 타입을 직접 보지 않는다** — 페이지가 fixture 자리에 값을
 * 넣어 주므로 컴포넌트 props는 그대로다.
 *
 * ## 무엇을 서버가 주고 무엇을 화면이 만드는가
 *
 * 순위·비중·증감·판정·단계는 **하나도 화면에서 만들지 않는다**(`src/mocks/README.md`).
 * 그래서 아래 타입은 `verdictText`·`levelText`처럼 이미 판정이 끝난 문구를 그대로
 * 받는다. 화면이 Level과 요구 Level을 비교해 "L2 요구"를 조립하면, 그 규칙이 BE와
 * 어긋나는 순간 화면만 다른 말을 한다.
 *
 * 반대로 `ROLE 01`·`#1` 같은 **순번 라벨은 두지 않았다.** 그것은 판정이 아니라 목록에서
 * 몇 번째인가일 뿐이고, 배열 순서에서 나오는 표시 환산이다. 서버가 보내면 배열 순서와
 * 어긋날 수 있는 값이 하나 늘어난다.
 */

/**
 * 공고 기술요건 대조 표시.
 *
 * `WEAK`는 "Evidence는 있는데 요구 Level에 미달"이라 `NONE`과 다른 상태다 — 둘을
 * 합치면 화면이 "없음"과 "부족"을 구분하지 못한다. 표기는 `✓`/`△`/`✕`.
 */
export const REQUIREMENT_MARKS = ['HAVE', 'WEAK', 'NONE'] as const
export type RequirementMark = (typeof REQUIREMENT_MARKS)[number]

/**
 * Skill Gap 판정.
 *
 * `UNDETERMINED`가 `NO_EVIDENCE`와 다른 값인 것이 이 계열의 핵심이다. 선언(L0)만
 * 확인된 기술은 "부족"으로 세지 않는다 — 사용 여부를 판정하지 않았을 뿐이라 Gap
 * 집계에서 빠진다. 둘을 합치면 "없다"고 단정하게 된다.
 */
export const SKILL_GAP_VERDICTS = ['MET', 'LEVEL_SHORT', 'NO_EVIDENCE', 'UNDETERMINED'] as const
export type SkillGapVerdict = (typeof SKILL_GAP_VERDICTS)[number]

/* ------------------------------------------------------------------ *
 * B-FN-013 · B-FN-014  목표 직무
 * ------------------------------------------------------------------ */

/** 직무별로 자주 요구되는 기술 한 줄. 막대 길이의 분자가 `requiredCount`다. */
export interface RoleTopSkill {
  techId: string
  techName: string
  /** 이 직무 공고 중 몇 건이 이 기술을 필수로 요구했는지. */
  requiredCount: number
  mark: RequirementMark
  /** 내 Level 표기. Evidence가 없으면 서버가 "없음"을 보낸다. */
  levelText: string
}

/**
 * 목표 직무 후보 한 건 · `GET /job-roles`.
 *
 * 막대 분모는 **그 직무의 공고 수**(`jobCount`)다. 전체 공고를 분모로 쓰면 직무 간
 * 비교가 되어 버리는데, 이 화면이 답하는 질문은 "어느 직무가 나와 가까운가"이지
 * "어느 직무가 공고가 많은가"가 아니다.
 */
export interface JobRole {
  id: string
  name: string
  /** 직무 한 줄 설명. */
  summary: string
  /** 비교 대상 공고 수. */
  jobCount: number
  /** 그중 현재 필수 전체 충족 건수. */
  fullMatchCount: number
  /** 이 직무를 고르는 판단에 붙는 서버 문구. */
  note: string
  topSkills: RoleTopSkill[]
}

export interface JobRoleList {
  dataStatus: DataStatus
  roles: JobRole[]
}

/**
 * 현재 목표 직무 · `GET /me/target`.
 *
 * 아직 고르지 않았으면 `roleId`가 null이다. 첫 직무를 기본값으로 채워 보내지 않는다 —
 * 고르지 않은 것과 첫 번째를 고른 것은 다른 상태다.
 */
export interface TargetRole {
  roleId: string | null
  roleName: string | null
  updatedAt: string | null
}

/** `PUT /me/target` 요청 본문. */
export interface TargetRoleInput {
  roleId: string
}

/* ------------------------------------------------------------------ *
 * B-FN-015  채용공고 · 기술 수요
 * ------------------------------------------------------------------ */

export interface JobRequirement {
  techId: string
  techName: string
  mark: RequirementMark
}

/** 공고 한 건 · `GET /job-postings`의 항목. */
export interface JobPosting {
  id: string
  title: string
  /** 근무지. 필터 값과 같은 어휘를 쓴다. */
  region: string
  /** 경력 조건. 필터 값과 같은 어휘를 쓴다. */
  career: string
  /**
   * 마감 표기. `D-11` 형태 그대로 온다.
   *
   * 날짜를 받아 화면이 D-day를 계산하지 않는 이유는 기준 시각이 공고 Snapshot의
   * 것이기 때문이다. 브라우저 시계로 다시 세면 Snapshot과 하루씩 어긋난다.
   */
  deadline: string
  required: JobRequirement[]
  preferred: JobRequirement[]
}

/**
 * 충족 분포 · `GET /job-postings`가 목록과 함께 주는 요약.
 *
 * 화면이 `items`를 세어 만들지 않는다. 한 페이지만 받은 상태에서 세면 전체가 아니라
 * 그 페이지의 분포가 된다.
 */
export interface JobMatchKpi {
  /** 대조한 공고 수. */
  total: number
  /** 필수 100% 충족. */
  fullMatch: number
  /** 75~99% 충족. */
  nearMatch: number
  /** 75% 미만. */
  lowMatch: number
  /** 어떤 필터가 걸렸는지 한 줄 설명. 필터가 없으면 그 사실을 적는다. */
  scopeText: string
}

/** 공고 화면 우측 Gap 요약의 한 줄. 막대 분모는 1위의 `requiredCount`다. */
export interface GapHighlight {
  techId: string
  techName: string
  /** 이 기술을 필수로 요구한 공고 수. */
  requiredCount: number
  /** 내 Evidence 상태 문구. `현재 L1` 또는 `Evidence 없음`. */
  levelText: string
}

/**
 * 공고 목록 응답 · `GET /job-postings`.
 *
 * 목록·요약·Gap을 한 응답에 두는 이유는 셋이 **같은 필터 집합을 근거로 해야** 하기
 * 때문이다. 따로 부르면 필터가 바뀌는 순간 KPI와 목록이 서로 다른 집합을 말한다.
 */
export interface JobPostingList {
  dataStatus: DataStatus
  headline: string
  kpi: JobMatchKpi
  gapTitle: string
  gaps: GapHighlight[]
  items: JobPosting[]
  /** 0-base. 명세 v0.1 */
  page: number
  size: number
  totalCount: number
}

/** `GET /job-postings` 질의 인자. 빈 값은 보내지 않는다(전체를 뜻한다). */
export interface JobPostingParams {
  roleId?: string
  region?: string
  career?: string
  page?: number
  size?: number
}

/** 기술 수요 집계 한 줄 · `GET /job-demands`. */
export interface JobDemand {
  techId: string
  techName: string
  /** 필수로 요구한 공고 수. */
  requiredCount: number
  /** 우대로 요구한 공고 수. */
  preferredCount: number
}

export interface JobDemandList {
  dataStatus: DataStatus
  /** 집계 근거 설명. `백엔드 · 전체 공고 87건`. */
  basisText: string
  items: JobDemand[]
}

/* ------------------------------------------------------------------ *
 * B-FN-016  Skill Gap
 * ------------------------------------------------------------------ */

/** Skill Gap 표의 한 행. */
export interface SkillGapRow {
  techId: string
  techName: string
  /** 필수로 요구한 공고 수. */
  requiredCount: number
  /** 우대로 요구한 공고 수. 요구가 없으면 null(0건과 구분한다). */
  preferredCount: number | null
  /** 내 Personal Level. Evidence가 없으면 null. */
  personalLevel: EvidenceLevel | null
  verdict: SkillGapVerdict
  /** 판정 문구. `L2 요구`, `미보유`, `충족`, `미판정`. */
  verdictText: string
  /**
   * 이 기술 하나만 요구 Level로 채웠다고 가정할 때 늘어나는 필수 전체 충족 공고 수.
   * 계산하지 않는 행(충족·미판정)은 null이다.
   *
   * **행끼리 더하지 않는다.** 같은 공고가 여러 행에 걸쳐 있어 합계는 의미를 갖지
   * 않는다. 화면이 합을 만들면 "3개만 배우면 12건이 늘어난다"는 없는 사실이 생긴다.
   */
  fillDelta: number | null
}

/** 판정별 묶음. 서버가 묶어서 보낸다 — 화면이 `verdict`로 다시 묶지 않는다. */
export interface SkillGapGroup {
  verdict: SkillGapVerdict
  title: string
  description: string
  rows: SkillGapRow[]
}

/**
 * Skill Gap 상단 요약.
 *
 * `요구 기술 = 충족 + 부족 + 판단 근거 부족`이 성립해야 한다. 화면이 합을 만들지 않는
 * 이유는 서버 값과 어긋났을 때 그 사실이 감춰지기 때문이다.
 */
export interface SkillGapSummary {
  /** 비교 집합 설명. `백엔드 · 전체 공고 87건`. */
  basisText: string
  requiredTechCount: number
  metCount: number
  gapCount: number
  /** 부족 내역 문구. `Evidence 없음 6 · Level 부족 3`. */
  gapBreakdown: string
  undeterminedCount: number
}

export interface SkillGap {
  dataStatus: DataStatus
  summary: SkillGapSummary
  groups: SkillGapGroup[]
}

/* ------------------------------------------------------------------ *
 * B-FN-017 · B-FN-018  추천 · What-if · 학습 기술
 * ------------------------------------------------------------------ */

/** What-if로 새로 충족되는 공고 한 건. */
export interface WhatIfJob {
  id: string
  title: string
  /** `서울 · 신입~3년` 형태. */
  meta: string
  chips: JobRequirement[]
  /** 왜 새로 충족되는지 한 줄. */
  why: string
}

/**
 * 학습 기술 후보 한 건 · `GET /me/recommendations`.
 *
 * 명세 확정 범위: **후보는 최대 3개**이고 사용자는 1개를 고른다.
 *
 * `currentFullMatch`·`projectedFullMatch`를 **둘 다** 받는다. 증가분 하나만 받으면
 * 화면이 "무엇에서 무엇으로"를 말할 수 없고, 반대로 증가분을 화면이 빼서 만들면
 * 서버의 What-if 공식과 어긋난 수가 표시될 수 있다. 명세가 두 수를 모두 주는 이유다.
 */
export interface NextSkill {
  techId: string
  techName: string
  /** 탭·칩에 들어가는 짧은 이름. */
  shortName: string
  fromLevel: EvidenceLevel
  targetLevel: EvidenceLevel
  /** 현재 필수 전체 충족 공고 수. */
  currentFullMatch: number
  /** 목표 Level 확보를 가정했을 때의 수. */
  projectedFullMatch: number
  headline: string
  ctaLabel: string
  /** 추천 근거. **점수가 아니라 문장으로만** 제시한다. */
  reasons: string[]
  /** 반대 신호. 명세 확정 범위가 근거와 함께 요구한다. 없으면 빈 배열. */
  counterSignals: string[]
  newlyMatched: WhatIfJob[]
}

/**
 * 추천 응답.
 *
 * 공식 버전을 함께 받는다. 명세 확정 범위가 `recommendationFormulaVersion`과
 * `whatIfFormulaVersion`을 남기라고 정했고, 같은 화면이 다른 버전으로 계산된 수를
 * 섞어 보이지 않게 하는 장치다.
 */
export interface Recommendations {
  dataStatus: DataStatus
  recommendationFormulaVersion: string
  whatIfFormulaVersion: string
  skills: NextSkill[]
}

/** 현재 고른 학습 기술 · `GET /me/learning-target`. 고르지 않았으면 null이다. */
export interface LearningTarget {
  techId: string | null
  techName: string | null
  updatedAt: string | null
}

/** `PUT /me/learning-target` 요청 본문. */
export interface LearningTargetInput {
  techId: string
}
