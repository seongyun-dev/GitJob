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

/** 후보 하나의 관찰 기록. 합계가 어느 저장소에서 나왔는지 되짚는 근거다. */
export interface CandidateObservation {
  /** GitHub 저장소 식별자. 저장소 이름은 이 응답에 없다(표시는 화면이 판단한다). */
  repositoryId: string
  scope: string | null
  occurrenceCount: number
  observedAt: string
}

/** 목록 항목에 결정 이력과 관찰을 더한 것. */
export interface TechnologyCandidateDetail extends TechnologyCandidate {
  /** 승격된 경우에만 값이 있다. */
  promotedTechId: string | null
  decidedAt: string | null
  decisionNote: string | null
  observations: CandidateObservation[]
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

/** 레지스트리에 이미 있는 기술 하나. 승격 화면의 선택지다. */
export interface TechnologyOption {
  techId: string
  displayName: string
}

export interface PromoteInput {
  candidateId: number
  techId?: string
  displayName?: string
  jobDomains?: string[]
  note?: string
}

/**
 * 목록이 보여 줄 묶음. BE `CandidateFilter` 와 같은 이름이다.
 *
 * 기본이 `UNDECIDED` 인 이유는 이 화면이 처리할 일이 쌓이는 큐이기 때문이다.
 * 결정이 끝난 것도 사용자 수로 정렬되므로, 섞어 두면 가장 많이 쓰이는 기술이
 * 맨 위에 영구히 박혀 정작 볼 일이 아래로 밀린다.
 */
export type CandidateFilter = 'UNDECIDED' | 'PROMOTED' | 'REJECTED' | 'ALL'

export function fetchTechnologyCandidates(
  limit: number,
  status: CandidateFilter,
): Promise<TechnologyCandidate[]> {
  return get<TechnologyCandidate[]>(`${BASE}?limit=${limit}&status=${status}`)
}

/**
 * 한 후보의 결정 이력과 근거 관찰 (티켓 141).
 *
 * 목록이 주는 합계(사용자·저장소·선언)가 어디서 나온 값인지 되짚는 자리다.
 * 관찰은 최근 것부터 오며 서버가 개수를 제한한다.
 */
export function fetchCandidateDetail(candidateId: number): Promise<TechnologyCandidateDetail> {
  return get<TechnologyCandidateDetail>(`${BASE}/${candidateId}`)
}

/**
 * 승격할 때 붙일 수 있는 기술 목록.
 *
 * 초안이 열려 있으면 초안을, 없으면 CURRENT를 읽는다. 한 검토 세션에서 방금 새로
 * 등록한 기술에도 바로 좌표를 더 붙일 수 있어야 하기 때문이다.
 */
export function fetchTechnologyOptions(): Promise<TechnologyOption[]> {
  return get<TechnologyOption[]>(`${BASE}/registry/technologies`)
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
