import type {
  JobDemandDto,
  JobMatchDetailDto,
  JobMatchListDto,
  RecommendationDto,
  SkillGapDto,
  TargetDto,
  WhatIfDto,
} from '@/features/matching/api/types'
import { jobDemandsPath } from '@/features/matching/model/jobDemandsQuery'
import { get, put } from '@/shared/api/client'

/**
 * 매칭 계열 조회 (S15P21E102-279).
 *
 * **요청에 사용자 ID도 Snapshot ID도 넣지 않는다.** 어느 계산 결과를 읽을지는 BE가
 * 로그인 사용자와 저장된 목표 직무로 정한다. 화면이 식별자를 들고 다니면 그것을 바꿔
 * 보내는 경로가 생기고, 그 경로는 곧 남의 결과를 요구하는 시도가 된다.
 *
 * 인증은 HttpOnly 세션 쿠키로 하며 `client`가 모든 요청에 실어 보낸다.
 */

/** 고른 적이 없으면 `null`이다. 오류가 아니라 다음 할 일이 정해진 상태다. */
export function fetchTarget(): Promise<TargetDto | null> {
  return get<TargetDto | null>('/me/target')
}

export function saveTarget(body: {
  targetRole: string
  regions: string[]
  careerLevels: string[]
}): Promise<TargetDto> {
  return put<TargetDto>('/me/target', body)
}

/**
 * 공고 매칭 목록.
 *
 * @param includeConditional 조건부 공고도 목록에 포함할지 결정한다. 포함해도 C가 판정을
 *                           UNKNOWN으로 유지하므로 충족 공고로 승격되지 않는다.
 */
export function fetchJobMatches(params: {
  page: number
  perPage: number
  includeConditional: boolean
}): Promise<JobMatchListDto> {
  const query = new URLSearchParams({
    page: String(params.page),
    perPage: String(params.perPage),
    includeConditional: String(params.includeConditional),
  })
  return get<JobMatchListDto>(`/me/job-matches?${query.toString()}`)
}

export function fetchJobMatch(jobId: string): Promise<JobMatchDetailDto> {
  return get<JobMatchDetailDto>(`/me/job-matches/${encodeURIComponent(jobId)}`)
}

export function fetchSkillGap(): Promise<SkillGapDto> {
  return get<SkillGapDto>('/me/skill-gap')
}

export function fetchRecommendations(): Promise<RecommendationDto> {
  return get<RecommendationDto>('/me/recommendations')
}

/**
 * 추천 기술이 필수 또는 우대로 언급된 공고.
 *
 * 활성 공고의 필수·우대·중복 제외 건수와 목록이 한 응답에서 온다.
 */
export function fetchWhatIf(
  techId: string,
  params: { page: number; perPage: number; kind: 'ALL' | 'REQUIRED' | 'PREFERRED' },
): Promise<WhatIfDto> {
  const query = new URLSearchParams({
    page: String(params.page),
    perPage: String(params.perPage),
    kind: params.kind,
  })
  return get<WhatIfDto>(
    `/me/recommendations/${encodeURIComponent(techId)}/what-if?${query.toString()}`,
  )
}

/**
 * 기술 수요. 개인 결과가 아니라 조건을 직접 넣어 본다.
 *
 * `targetRole`이 없으면 현재 채용시장 전체다 — 경로 규칙은 {@link jobDemandsPath}.
 */
export function fetchJobDemands(params: {
  targetRole?: string
  regions: readonly string[]
  careerLevels: readonly string[]
}): Promise<JobDemandDto> {
  return get<JobDemandDto>(jobDemandsPath(params))
}
