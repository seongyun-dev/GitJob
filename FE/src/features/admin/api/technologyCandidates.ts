import { get, post } from '@/shared/api/client'

/**
 * 기술 후보 검토 API (티켓 14 · 관리자 화면).
 *
 * BE `analysis/controller/AdminTechnologyCandidateController`가 원본이고
 * 경로는 `/api/v1/admin/technology-candidates`다. 이 경로는 SecurityConfig에서
 * ADMIN 역할로 제한되므로 일반 사용자는 401·403을 받는다.
 */

const BASE = '/admin/technology-candidates'

/** BE `TechnologyCandidateResponse`. 시각은 ISO-8601 문자열로 온다. */
export interface TechnologyCandidate {
  candidateId: number
  /** MAVEN · NPM · PYPI · NUGET 등. 좌표를 읽는 방식이 생태계마다 다르다. */
  ecosystem: string
  coordinate: string
  /** MAIN · TEST · DEV. 관찰이 엇갈리면 BE가 null로 둔다. */
  scope: string | null
  /** NEW · REVIEWING · PROMOTED · REJECTED */
  status: string
  /**
   * 판단의 근거가 되는 수치. 정렬은 이 값으로만 한다 —
   * 발생 횟수로 줄을 세우면 모노레포 하나가 순서를 정한다.
   */
  distinctUserCount: number
  distinctRepositoryCount: number
  occurrenceCount: number
  firstSeenAt: string
  lastSeenAt: string
}

/** 지금 판정에 쓰이는 버전과, 승격이 쌓이고 있는 초안 버전. */
export interface RegistryStatus {
  current: string | null
  draft: string | null
}

export interface PromotionResult {
  /** 실제로 등록된 식별자. 안 넘기면 BE가 좌표에서 만든다. */
  techId: string
  registry: RegistryStatus
}

export interface PromoteInput {
  candidateId: number
  techId?: string
  displayName?: string
  jobDomains?: string[]
  note?: string
}

export function fetchTechnologyCandidates(limit: number): Promise<TechnologyCandidate[]> {
  return get<TechnologyCandidate[]>(`${BASE}?limit=${limit}`)
}

export function fetchRegistryStatus(): Promise<RegistryStatus> {
  return get<RegistryStatus>(`${BASE}/registry`)
}

/**
 * 승격은 CURRENT가 아니라 초안에 들어간다.
 *
 * 이미 판정이 끝난 분석은 자기가 쓴 버전을 그대로 가리키므로, 발행 전까지
 * 사용자에게 보이는 결과는 바뀌지 않는다.
 */
export function promoteCandidate({
  candidateId,
  ...body
}: PromoteInput): Promise<PromotionResult> {
  return post<PromotionResult>(`${BASE}/${candidateId}/promote`, body)
}

export function rejectCandidate(candidateId: number, note?: string): Promise<RegistryStatus> {
  return post<RegistryStatus>(`${BASE}/${candidateId}/reject`, { note: note ?? null })
}

/** 초안을 CURRENT로 올린다. 이후 요청되는 분석부터 새 버전으로 판정된다. */
export function publishRegistryDraft(): Promise<RegistryStatus> {
  return post<RegistryStatus>(`${BASE}/registry/publish`)
}
