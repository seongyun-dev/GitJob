import type { EvidenceLevel } from '@/shared/types/domain'

/**
 * Evidence 조회 응답 타입 · 티켓 S15P21E102-208.
 *
 * BE 미구현 상태에서 **먼저** 고정하는 계약이다. 137·138이 화면을 붙일 때 계약을
 * 다시 정하지 않도록 한다.
 *
 * 근거는 [B조 API 명세서](https://app.notion.com/p/3d7a6b738a2880c69427df7300fa6c18)
 * v0.1의 두 항목이고, 필드명·타입·optional 여부를 그 예시 응답에서 그대로 옮겼다.
 *   - B-FN-010 기술 프로필 조회 (`GET /me/profile`, 화면 S6)
 *   - B-FN-011 기술 Evidence 근거 조회 (`GET /me/technologies/{techId}/evidence`, S7)
 *
 * `docs/fe/shared-api-contract.md`가 정한 우선순위는 "BE에 구현된 것은 BE 코드를
 * 따르고, **아직 없는 것만 Notion 명세를 유지한다**"다. 이 둘은 BE에 없으므로 명세가
 * 기준이다. 저장소 문서(`docs/be/README.md` §8)와 어긋나는 곳은 명세를 택하고 아래에
 * 근거를 남겼다.
 *
 * 명세와 기존 FE 확정 규칙이 충돌하는 항목은 이 파일에서 조용히 정하지 않았다.
 * `contributionScore`가 그것이며 계약 문서 미결에 올렸다.
 */

/**
 * Fact 종류. 명세 B-FN-011의 `factType` 예시는 `API_CALL`이고, 값 집합은 Registry
 * 스키마 `vocabularies.fact_type`의 5종이다.
 *
 * 이 중 **추출기가 있는 것은 `IMPORT`·`DEPENDENCY` 둘뿐**이다(같은 스키마의 `구현됨`).
 * 명세 예시가 쓰는 `API_CALL`은 아직 나올 수 없다. 다섯을 모두 두는 이유는 추출기가
 * 늘 때 이 배열만 고치면 되게 하려는 것이고, 화면이 "아직 안 오는 값"을 구분해야 하면
 * `IMPLEMENTED_FACT_TYPES`를 쓴다.
 */
export const EVIDENCE_FACT_TYPES = [
  'IMPORT',
  'DEPENDENCY',
  'ANNOTATION',
  'CONFIG_KEY',
  'API_CALL',
] as const
export type EvidenceFactType = (typeof EVIDENCE_FACT_TYPES)[number]

/** 현재 추출기가 있어 실제로 응답에 나올 수 있는 fact 종류. */
export const IMPLEMENTED_FACT_TYPES: ReadonlySet<EvidenceFactType> = new Set([
  'IMPORT',
  'DEPENDENCY',
])

/**
 * 근거의 판정 범위. 명세 B-FN-011이 `scopeType` 쿼리 파라미터를
 * `"REPOSITORY" | "PERSONAL" | "ALL"`로 정의한다.
 *
 * Registry 스키마의 `evaluation_scope`는 `REPOSITORY`·`PERSONAL` 둘만 허용하는데,
 * 그건 **규칙**이 어느 범위를 평가하는지를 제약하는 값이고 여기 `scopeType`은
 * **조회 필터와 근거 한 줄의 소속**이다. `ALL`은 필터에서 "둘 다"를 뜻하므로 층이
 * 다르다. 응답 항목의 `scopeType`에는 `ALL`이 오지 않는다고 보아
 * `EVIDENCE_ITEM_SCOPES`를 따로 둔다.
 */
export const EVIDENCE_SCOPE_FILTERS = ['REPOSITORY', 'PERSONAL', 'ALL'] as const
export type EvidenceScopeFilter = (typeof EVIDENCE_SCOPE_FILTERS)[number]

/** 근거 한 줄이 실제로 가질 수 있는 범위. 명세 예시의 항목은 `REPOSITORY`다. */
export const EVIDENCE_ITEM_SCOPES = ['REPOSITORY', 'PERSONAL'] as const
export type EvidenceItemScope = (typeof EVIDENCE_ITEM_SCOPES)[number]

/**
 * 기술 카테고리. 명세 B-FN-010의 `categoryCode 값 정의` 표 6종이다.
 * `OTHER`는 "Registry category가 5개 영역에 매핑되지 않는 경우"라 항상 올 수 있다.
 */
export const TECHNOLOGY_CATEGORY_CODES = [
  'BACKEND',
  'DATABASE',
  'INFRASTRUCTURE',
  'TESTING',
  'OBSERVABILITY',
  'OTHER',
] as const
export type TechnologyCategoryCode = (typeof TECHNOLOGY_CATEGORY_CODES)[number]

/**
 * 판정에 쓰인 기준. 명세는 "숫자를 반환하므로 criteria 객체를 반드시 함께 반환한다"고
 * 못 박는다. 즉 이 객체는 장식이 아니라 수치의 출처다 — 값과 함께 화면에 남아야 한다.
 */
export interface ProfileCriteria {
  registryVersion: string
  registryChecksum: string
  /** 사용자가 고른 저장소 수. */
  repositoryCount: number
  /** 그중 실제로 분석이 끝난 수. `repositoryCount`와 다르면 부분 결과다. */
  analyzedRepositoryCount: number
  commitShas: { repoFullName: string; commitSha: string }[]
  limits: { maxRepositories: number; maxFilesPerRepository: number }
}

/**
 * 기술 하나의 판정. 명세 B-FN-010 `categories[].technologies[]`.
 *
 * **레벨은 항상 두 개가 함께 온다.** 명세 설명이 "하나만 내려보내면 화면에서 축이
 * 혼동된다"고 적었다. `repoLevel`은 저장소가 그 기술을 어떻게 쓰는가,
 * `personalLevel`은 본인이 어떻게 썼는가다. 둘을 합쳐 단일 숙련도 숫자로 만들지
 * 않는다(`docs/be/README.md` §8).
 *
 * 필드명은 명세 그대로다. `techName`(≠ `displayName`), `repoLevel`(≠ `repositoryLevel`).
 */
export interface TechnologyProfileEntry {
  /** Registry `technology.tech_id`. 명세 예시는 `kafka`. */
  techId: string
  /** 화면에 보이는 이름. 명세 예시는 `Apache Kafka`. */
  techName: string
  repoLevel: EvidenceLevel
  personalLevel: EvidenceLevel
  /** 이 기술을 뒷받침하는 근거 건수. */
  evidenceCount: number
  representativeRepo: string
  /** UTC ISO-8601. */
  lastUsedAt: string
}

export interface TechnologyCategory {
  categoryCode: TechnologyCategoryCode
  categoryName: string
  /** 명세 예시의 `OTHER`처럼 빈 배열이 올 수 있다. */
  technologies: TechnologyProfileEntry[]
}

/**
 * `GET /me/profile` 응답 · 명세 B-FN-010.
 *
 * 배열이 아니라 객체다. 카테고리별로 묶여 오고, 분석 범위(`partial`·`missingScope`)와
 * 판정 한계(`judgementLimits`)가 같은 응답에 실린다.
 *
 * `partial`이 true면 일부 저장소 분석이 실패한 결과다. 그 사실을 감추고 목록만
 * 보여주면 사용자는 전체를 본 것으로 오해한다 — `missingScope`가 그 사유 문장이다.
 */
export interface TechnologyProfile {
  analysisId: string
  /** UTC ISO-8601. */
  analyzedAt: string
  partial: boolean
  /** 분석되지 않은 범위의 사유 문장. 완전한 결과면 빈 배열. */
  missingScope: string[]
  criteria: ProfileCriteria
  categories: TechnologyCategory[]
  /** 판정 방식의 한계. 수치를 그대로 믿지 않게 하는 문장들이다. */
  judgementLimits: string[]
}

/** `GET /me/profile` 쿼리 파라미터. 둘 다 optional이라 생략하면 최근 종료 분석이다. */
export interface TechnologyProfileParams {
  analysisId?: string
}

/**
 * 근거 한 줄 · 명세 B-FN-011 `evidences[]`.
 *
 * **원본 코드 본문을 담는 필드는 두지 않는다.** 명세가 "원본 코드는 응답에 포함하지
 * 않는다. 경로·라인번호·commitSha와 GitHub permalink만 반환한다"고 못 박고, 화면도
 * Raw Code Viewer를 제공하지 않는다(`EvidenceDetailPage`). `parseEvidence.ts`가 알려진
 * 필드만 옮겨 담으므로 BE가 나중에 본문 필드를 실어 보내도 FE 상태로 들어오지 않는다.
 *
 * `contributionScore`는 **의도적으로 넣지 않았다.** 명세 예시는 `0.4`라는 비율 숫자를
 * 내려보내지만, `shared/types/domain.ts`의 `ContributionLabel`이 "비율 값을 노출하지
 * 않는다(와이어프레임 1-1 금지 규칙). 숫자를 받는 자리를 만들지 않는 것이 이 타입의
 * 목적이다"라고 적혀 있다. 확정 규칙 둘이 충돌하므로 FE가 혼자 정하지 않는다 —
 * 계약 문서 미결에 올렸다. 필드를 받아 두면 화면이 그 숫자를 쓰기 시작한다.
 */
export interface EvidenceItem {
  /** 명세 예시는 정수(`90211`)다. 표 행의 key로 쓸 수 있다. */
  evidenceId: number
  scopeType: EvidenceItemScope
  /** 이 근거가 기여하는 Level. */
  level: EvidenceLevel
  /**
   * 맞춘 규칙 ID. 명세 `matchedRule 값 정의` 표가 `L0-a`~`L3-e`를 열거하지만
   * 문자열로 받는다. 규칙이 늘면 값이 늘고, 화면은 이 값을 파싱하지 않는다.
   */
  matchedRule: string
  factType: EvidenceFactType
  repoFullName: string
  filePath: string
  /**
   * 파일 안의 위치. `DEPENDENCY`는 매니페스트 스캔에서 나와 줄 번호가 없을 수 있어
   * nullable로 둔다. 0을 "줄 정보 없음"으로 쓰지 않는다.
   */
  lineNo: number | null
  commitSha: string
  /** GitHub permalink. 원문 확인의 유일한 경로다. */
  permalink: string
  inherited: boolean
  /** UTC ISO-8601. */
  detectedAt: string
  /**
   * 제외 사유. 봇·merge·fork base·generated·format-only는 버리지 않고 사유를 남긴다.
   * `includeExcluded=true`로 조회할 때만 값이 있는 항목이 섞여 온다.
   */
  excludedReason: string | null
}

/** 미충족 규칙 · 명세 B-FN-011 `unmetRules[]`. 문자열이 아니라 객체다. */
export interface UnmetRule {
  /** 규칙 ID. 예: `L2-b`. */
  rule: string
  description: string
}

/**
 * 다음 Level로 가는 최소 행동 · 명세 B-FN-011 `nextActions[]`.
 * 명세 설명이 "화면이 진단으로만 끝나지 않게 한다"고 적은 자리다.
 */
export interface NextAction {
  fromLevel: EvidenceLevel
  targetLevel: EvidenceLevel
  ruleId: string
  message: string
}

/**
 * 노이즈로 제외된 근거의 종류별 건수 · 명세 B-FN-011 `excludedCounts`.
 * 무엇을 왜 뺐는지 세어 보여주는 값이라 0도 의미가 있다.
 */
export interface ExcludedCounts {
  bot: number
  merge: number
  forkBase: number
  formatOnly: number
  generated: number
}

/** `GET /me/technologies/{techId}/evidence` 응답 · 명세 B-FN-011. */
export interface TechnologyEvidence {
  techId: string
  techName: string
  repoLevel: EvidenceLevel
  personalLevel: EvidenceLevel
  /** 프로필의 `criteria`보다 좁다. 명세 예시는 이 둘만 담는다. */
  criteria: { analysisId: string; registryVersion: string }
  evidences: EvidenceItem[]
  unmetRules: UnmetRule[]
  nextActions: NextAction[]
  excludedCounts: ExcludedCounts
}

/**
 * `GET /me/technologies/{techId}/evidence` 쿼리 파라미터 · 명세 B-FN-011.
 * 전부 optional이며 기본값은 명세가 정한다(`scopeType` 기본 `ALL`,
 * `includeExcluded` 기본 false).
 */
export interface TechnologyEvidenceParams {
  analysisId?: string
  scopeType?: EvidenceScopeFilter
  /** 특정 저장소로 필터. `owner/repo`. */
  repoFullName?: string
  /** true면 노이즈로 제외된 근거도 함께 온다. */
  includeExcluded?: boolean
}
