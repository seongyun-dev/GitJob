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

export function fetchTechnologyProfile(): Promise<TechnologyProfile> {
  return get<TechnologyProfile>(BASE)
}

export function fetchTechnologyEvidence(techId: string): Promise<TechnologyEvidence> {
  return get<TechnologyEvidence>(`${BASE}/${encodeURIComponent(techId)}/evidence`)
}
