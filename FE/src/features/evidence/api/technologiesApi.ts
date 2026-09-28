import { get } from '@/shared/api/client'
import type { DataStatus, EvidenceLevel } from '@/shared/types/domain'

/**
 * 내 분석 결과 조회 · BE `TechnologyProfileController`.
 *
 * 이 파일만 경로 문자열을 안다. 봉투 해제와 오류 변환은 `shared/api/client`가 한다.
 */

const BASE = '/me/technologies'

export interface ProfileSummary {
  technologyCount: number
  /** L2 이상. "해 봤다"고 말할 수 있는 기술 수 */
  advancedCount: number
  repositoryCount: number
  /** 분석한 적이 없으면 null */
  analyzedAt: string | null
}

export interface TechnologyVerdict {
  techId: string
  displayName: string
  /**
   * 본인 Commit 이 확인된 범위. **항상 null 이다.**
   *
   * 근거 라인마다 작성자를 봐야 알 수 있는데 워커가 아직 blame 을 하지 않는다.
   * Repository Level 로 대신 채우면 화면이 "본인이 썼다"고 말하게 되므로 BE 가
   * 비워서 보낸다. 값이 생기면 이 필드에 들어온다.
   */
  personalLevel: EvidenceLevel | null
  /** 저장소 전체 기준. 여러 저장소에 걸치면 가장 높은 Level 이다 */
  repositoryLevel: EvidenceLevel
  evidenceCount: number
  repositoryCount: number
  /** 판정에 쓰인 레지스트리 버전. 규칙이 바뀌어도 이 판정은 이 버전의 것이다 */
  registryVersion: string
}

export interface AnalyzedRepository {
  repositoryId: string
  /** V12 이전 분석은 이름을 안 남겼다 */
  fullName: string | null
  commitSha: string
  analyzedAt: string
  evidenceCount: number
}

export interface TechnologyProfile {
  dataStatus: DataStatus
  summary: ProfileSummary
  technologies: TechnologyVerdict[]
  repositories: AnalyzedRepository[]
}

/** 한 파일 안의 근거 한 줄. */
export interface EvidenceLine {
  startLine: number
  endLine: number
  /** DEPENDENCY · IMPORT · API_CALL */
  factType: string
  ruleId: string
  /** 커밋을 고정한 GitHub 링크. 저장소 이름이 없으면 null */
  permalink: string | null
}

/** 한 파일에서 나온 근거. 같은 파일의 연속된 라인이 여기로 접힌다. */
export interface EvidenceFile {
  repository: string | null
  filePath: string
  /** 첫 라인으로 가는 링크 */
  permalink: string | null
  lines: EvidenceLine[]
}

/**
 * 한 Level 의 근거 묶음.
 *
 * `truncated`가 true면 `evidenceCount` 중 `shownCount`만 왔다는 뜻이다. 감추면
 * 화면이 "근거는 이게 전부"라고 말하게 된다.
 */
export interface EvidenceLevelGroup {
  level: EvidenceLevel
  evidenceCount: number
  shownCount: number
  truncated: boolean
  /** 이 Level 을 낸 규칙 이름. "왜 이 Level 인가"의 답이다 */
  rules: string[]
  files: EvidenceFile[]
}

export interface TechnologyEvidence {
  techId: string
  dataStatus: DataStatus
  /** 근거가 있는 Level 중 가장 높은 것. 근거가 없으면 null */
  level: EvidenceLevel | null
  levels: EvidenceLevelGroup[]
}

/**
 * 요약이 없는 이유. 화면이 다시 물을지 말지를 이 값이 정한다.
 *
 * `PENDING` 과 `NONE` 을 가르는 것이 이 타입의 목적이다. 생성은 노트북 GPU 한 대
 * 위에서 돌고 BE 가 동시 2건까지만 보내므로, 자리를 못 받은 요청이 `PENDING` 으로
 * 돌아온다. 그것을 `NONE` 과 같이 다루면 화면은 빈 자리가 영구적인지 알 수 없다.
 */
export type SummaryStatus = 'READY' | 'PENDING' | 'NONE'

/**
 * 판정 위에 얹는 한 문단. BE `TechnologySummaryView`.
 *
 * **언제나 200 이다.** 모델이 꺼져 있어도 문장 검증에 떨어져도 `status` 로 사유가
 * 오고 본문만 비어 온다. 이 호출이 실패해도 카드는 이미 완성돼 있다 -- 수준·근거·
 * permalink 는 이 문장과 무관하다.
 */
export interface TechnologySummary {
  techId: string
  status: SummaryStatus
  /** `PENDING` 일 때만 0 보다 크다. 서버가 자리가 날 즈음을 지시한다 */
  retryAfterSeconds: number
  /** 40자 이내. 카드 제목. Level 문자열은 담지 않는다 -- Level 은 옆에 따로 그려진다 */
  headline: string | null
  /** 2~3문장, 200자 이내 */
  summary: string | null
  /**
   * 다음 수준까지 무엇이 비었는지 한 문장.
   *
   * 도달 가능한 최고 수준이면 `null` 이다. 현재 레지스트리에 L3 규칙을 가진 기술이
   * 둘뿐이라 대부분의 기술이 여기 해당한다.
   */
  gap: string | null
  /**
   * 자신감이 아니라 **입력이 얼마나 구체적인가**다. 의존성 선언만 확인된 기술은
   * 문장이 맞아도 `LOW` 다. AI 서비스가 Fact Pack 에서 규칙으로 계산한다.
   */
  confidence: 'HIGH' | 'MEDIUM' | 'LOW' | null
  /**
   * `OK` 모델이 쓴 문장 · `FALLBACK` 데이터에서 기계적으로 만든 문장.
   * **둘 다 정상이라 화면은 구분하지 않는다.** 되짚을 때만 쓴다.
   */
  llmStatus: 'OK' | 'FALLBACK' | null
}

export function fetchTechnologyProfile(): Promise<TechnologyProfile> {
  return get<TechnologyProfile>(BASE)
}

export function fetchTechnologyEvidence(techId: string): Promise<TechnologyEvidence> {
  return get<TechnologyEvidence>(`${BASE}/${encodeURIComponent(techId)}/evidence`)
}

/**
 * 기술 하나의 요약. 캐시에 있으면 즉시, 없으면 BE 가 만들어서 준다(약 4초).
 *
 * 목록(`/me/technologies`)에 실리지 않는 이유는 기술 열두 개면 목록이 48초를
 * 기다리게 되기 때문이다. 카드마다 따로 부르면 목록은 즉시 뜨고 문단은 도착하는
 * 대로 채워진다.
 */
export function fetchTechnologySummary(techId: string): Promise<TechnologySummary> {
  return get<TechnologySummary>(`${BASE}/${encodeURIComponent(techId)}/summary`)
}
