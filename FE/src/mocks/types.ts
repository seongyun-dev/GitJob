import type { DataStatus, EvidenceLevel } from '@/shared/types/domain'

/**
 * fixture 전용 화면 타입.
 *
 * **`shared/types/`에 두지 않는 이유가 이 파일의 요점이다.** 아래 타입 대부분은
 * 조회 API가 없어 계약이 정해지지 않았다. 공용 폴더에 두면 다음 사람이 확정된
 * 계약으로 읽고 화면을 붙인다. BE 응답이 오면 그때 각 feature의 `api/types.ts`에
 * 명세를 근거로 다시 정의하고, 이 파일은 지운다.
 *
 * Evidence 계열(S6·S7)만 예외다. 그쪽은 티켓 208이 명세를 근거로 이미 계약을
 * 고정해 두어 `features/evidence/api/types.ts`를 그대로 쓴다 — fixture도 그 타입을
 * 만족해야 하며, 만족하지 못하면 fixture가 아니라 계약 이해가 틀린 것이다.
 *
 * 출처는 확정 디자인 `GitJob_FE_Final_v2_17screens.html`의 데모 스크립트다.
 * 화면 번호는 그 파일의 아트보드 번호(01~17)를 따른다.
 */

/**
 * 공고 기술요건 대조 표시 · 화면 02·16.
 *
 * 와이어프레임의 `have` / `weak` / `none`이고 표기는 각각 `✓` / `△` / `✕`다.
 * `WEAK`는 "Evidence는 있는데 요구 Level에 미달"이라 `NONE`과 다른 상태다 —
 * 둘을 합치면 화면이 "없음"과 "부족"을 구분하지 못한다.
 */
export type RequirementMark = 'HAVE' | 'WEAK' | 'NONE'

/** 공고 한 건이 요구하는 기술 하나. */
export interface JobRequirementFixture {
  techName: string
  mark: RequirementMark
}

/** 공고 한 건 · 화면 02. */
export interface JobPostingFixture {
  id: string
  title: string
  /** 근무지. 필터 값과 같은 어휘를 쓴다. */
  region: string
  /** 경력 조건. 필터 값과 같은 어휘를 쓴다. */
  career: string
  /** 마감 표기. `D-11` 형태 그대로 둔다 — 날짜 계산은 공고 Snapshot이 정한다. */
  deadline: string
  required: JobRequirementFixture[]
  preferred: JobRequirementFixture[]
}

/** 충족 분포 KPI · 화면 02 상단. */
export interface JobMatchKpiFixture {
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

/** 화면 02 우측 Skill Gap 요약 카드의 한 줄. */
export interface GapHighlightFixture {
  techName: string
  /** 이 기술을 필수로 요구한 공고 수. */
  requiredCount: number
  /** 내 Evidence 상태 문구. `현재 L1` 또는 `Evidence 없음`. */
  levelText: string
}

/**
 * 화면 02의 필터 시나리오.
 *
 * 셋을 모두 두는 이유는 이 화면의 레이아웃 위험이 값이 있을 때가 아니라 **없을 때**
 * 나오기 때문이다. `EMPTY`가 없으면 빈 상태에서 우측 카드가 무너지는 것을 디자인
 * 단계에서 발견하지 못한다.
 */
export interface JobMatchScenarioFixture {
  id: 'ALL' | 'FILTERED' | 'EMPTY'
  headline: string
  kpi: JobMatchKpiFixture
  gapTitle: string
  gaps: GapHighlightFixture[]
  /** 목록 하단 "N개 중 M개 표시" 문구. 빈 시나리오에서는 빈 문자열. */
  moreText: string
  postings: JobPostingFixture[]
}

/** 직무별 자주 요구되는 기술 한 줄 · 화면 16. */
export interface RoleTopSkillFixture {
  techName: string
  /** 이 직무 공고 중 몇 건이 요구했는지. 막대 길이의 분자다. */
  requiredCount: number
  mark: RequirementMark
  /** 내 Level 표기. Evidence가 없으면 `없음`. */
  levelText: string
}

/** 목표 직무 후보 · 화면 16. */
export interface TargetRoleFixture {
  id: string
  /** `ROLE 01` 같은 순번 라벨. */
  kicker: string
  name: string
  /** 직무 한 줄 설명. */
  summary: string
  /** 비교 대상 공고 수. */
  jobCount: number
  /** 그중 현재 필수 전체 충족 건수. */
  fullMatchCount: number
  note: string
  topSkills: RoleTopSkillFixture[]
}

/**
 * Skill Gap 상세의 판정 · 화면 17.
 *
 * `UNDETERMINED`가 `NO_EVIDENCE`와 다른 값인 것이 이 화면의 핵심이다. 선언(L0)만
 * 확인된 기술은 "부족"으로 세지 않는다 — 사용 여부를 판정하지 않았을 뿐이라
 * Gap 집계에서 빠진다.
 */
export type SkillGapVerdict = 'MET' | 'LEVEL_SHORT' | 'NO_EVIDENCE' | 'UNDETERMINED'

/** Skill Gap 표의 한 행 · 화면 17. */
export interface SkillGapRowFixture {
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
   * 계산하지 않는 행(충족·미판정)은 null이다. **행끼리 더하지 않는다** — 같은 공고가
   * 여러 행에 걸쳐 있어 합계는 의미를 갖지 않는다.
   */
  fillDelta: number | null
}

/** Skill Gap 표의 묶음 · 화면 17. */
export interface SkillGapGroupFixture {
  verdict: SkillGapVerdict
  title: string
  description: string
  rows: SkillGapRowFixture[]
}

/** 화면 17 상단 요약. */
export interface SkillGapSummaryFixture {
  /** 비교 집합 설명. `백엔드 · 전체 공고 87건`. */
  basisText: string
  requiredTechCount: number
  metCount: number
  gapCount: number
  /** 부족 내역 문구. `Evidence 없음 6 · Level 부족 3`. */
  gapBreakdown: string
  undeterminedCount: number
}

/** What-if로 새로 충족되는 공고 한 건 · 화면 03. */
export interface WhatIfJobFixture {
  title: string
  /** `서울 · 신입~3년` 형태. */
  meta: string
  chips: JobRequirementFixture[]
  /** 왜 새로 충족되는지 한 줄. */
  why: string
}

/** 다음 학습 기술 후보 · 화면 10·03 공용. */
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

/** 트렌드 출처 · 화면 12·13. */
export type TrendSourceId = 'JOB' | 'GITHUB' | 'STACK_OVERFLOW'

/** 출처별 순위 한 줄 · 화면 12. */
export interface TrendRankRowFixture {
  rank: number
  /**
   * Registry `tech_id`. 상세 화면으로 가는 링크가 이 값을 쓴다.
   *
   * 표시 이름에서 만들어내지 않는다. `Apache Kafka` → `apache-kafka`가 되는데
   * 실제 id는 `kafka`라 상세 화면이 기술을 못 찾는다. 표시 이름과 식별자는 다른 값이다.
   */
  techId: string
  techName: string
  /** 비중 표기. 출처마다 분모가 달라 문자열로 둔다. */
  share: string
  /** 변화 표기. `↑ 7.1%`. */
  delta: string
  direction: 'UP' | 'DOWN'
}

/** 출처 하나 · 화면 12. */
export interface TrendSourceFixture {
  id: TrendSourceId
  label: string
  /** 무엇을 세는지. 출처 간 비교를 막는 이름이라 반드시 표시한다. */
  unit: string
  status: DataStatus
  /** 측정 범위와 기간. */
  basis: string
  /** 이 출처의 지원 범위 한계. 없으면 null. */
  scopeNote: string | null
  rows: TrendRankRowFixture[]
  footnote: string
}

/** 기간별 값 한 점 · 화면 13. */
export interface TrendPointFixture {
  /** 표시용 기간 라벨. `9월`. */
  period: string
  value: number
}

/** 출처별 시계열 · 화면 13. */
export interface TrendSeriesFixture {
  sourceId: TrendSourceId
  label: string
  status: DataStatus
  /** Y축이 무엇인지. 출처마다 독립이라 한 축에 겹쳐 그리지 않는다. */
  axisLabel: string
  /** 최근 값 표기. 상태가 READY가 아니면 null. */
  latestText: string | null
  /** 전기 대비 변화 표기. 상태가 READY가 아니면 null. */
  deltaText: string | null
  /** 상태가 READY가 아니면 빈 배열. 값을 지어내지 않는다. */
  points: TrendPointFixture[]
  note: string
}

/**
 * 기술 성장 단계 · S6 초안(트렌드 · 성장 단계).
 *
 * 아직 확정 디자인에 없는 화면이라 fixture도 초안 캡처를 근거로 만들었다.
 * `stage` 하나를 만드는 계산은 아직 어디에도 없다 — 세 축을 묶어 단계를 정하는
 * 규칙은 제품 결정이고, 그 결정 전까지 이 값은 화면 배치를 보기 위한 자리다.
 *
 * **초안의 `쇠퇴기`를 값 목록에 두지 않았다.** 특정 기술이 쇠퇴한다고 단정하는 것은
 * 이 제품이 할 판단이 아니다. 근거로 쓸 수 있는 것은 "국내 백엔드 공고 표본에서
 * 언급이 줄었다"까지인데 그 라벨은 훨씬 센 주장을 한다. 하락 자체는 숨기지 않고
 * 축의 `↓` 표기로 남긴다.
 *
 * 값을 여기서 닫아 두는 이유는 화면이 만들 수 없는 단계를 stepper에 그리지 않게
 * 하려는 것이다. 활성될 수 없는 칸은 자리만 차지한다.
 */
export type GrowthStageId = 'EARLY' | 'GROWING' | 'MATURE'

/** 성장 단계 판정에 쓰이는 축 하나. */
export interface GrowthStageAxisFixture {
  label: string
  /** 어느 출처에서 오는 값인지. 축마다 출처가 달라 반드시 밝힌다. */
  sourceLabel: string
  status: DataStatus
  /** 상태가 READY가 아니면 null. 빈 값을 0으로 채우지 않는다. */
  valueText: string | null
  deltaText: string | null
  direction: 'UP' | 'DOWN' | null
  note: string
}

/** 성장 단계 카드 하나. */
export interface GrowthStageFixture {
  techId: string
  techName: string
  stage: GrowthStageId
  /** `Kafka는 성장기입니다`. */
  verdict: string
  /** `진입 적기 — 지금 배우면 선점`. */
  advice: string
  axes: GrowthStageAxisFixture[]
  footnote: string
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
