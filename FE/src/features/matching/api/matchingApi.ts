import type {
  JobDemandDto,
  JobMatchDetailDto,
  JobMatchListDto,
  RecommendationDto,
  SkillGapDto,
  TargetDto,
  WhatIfDto,
} from '@/features/matching/api/types'
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
 * @param includeConditional 기본은 꺼져 있다. 조건부 공고는 자격 자체가 확정되지 않아
 *                           충족 여부를 말할 수 없고, 섞으면 충족 건수가 커 보인다.
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
 * 추천 기술을 채웠을 때 새로 부합하는 공고.
 *
 * 증가 건수와 목록이 한 응답에서 온다. 숫자를 추천 API에서 목록을 여기서 읽으면 그
 * 사이에 새 계산이 생겼을 때 화면의 "+7건"과 아래 목록이 어긋난다.
 */
export function fetchWhatIf(
  techId: string,
  params: { page: number; perPage: number },
): Promise<WhatIfDto> {
  const query = new URLSearchParams({
    page: String(params.page),
    perPage: String(params.perPage),
  })
  return get<WhatIfDto>(
    `/me/recommendations/${encodeURIComponent(techId)}/what-if?${query.toString()}`,
  )
}

/** 직무별 기술 수요. 개인 결과가 아니라 조건을 직접 넣어 본다. */
export function fetchJobDemands(params: {
  targetRole: string
  regions: readonly string[]
  careerLevels: readonly string[]
}): Promise<JobDemandDto> {
  const query = new URLSearchParams({ targetRole: params.targetRole })
  params.regions.forEach((region) => query.append('regions', region))
  params.careerLevels.forEach((level) => query.append('careerLevels', level))
  return get<JobDemandDto>(`/job-demands?${query.toString()}`)
}
