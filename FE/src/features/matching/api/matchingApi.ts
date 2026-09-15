import {
  parseJobDemandList,
  parseJobPostingList,
  parseJobRoleList,
  parseLearningTarget,
  parseRecommendations,
  parseSkillGap,
  parseTargetRole,
} from '@/features/matching/api/parseMatching'
import type {
  JobDemandList,
  JobPostingList,
  JobPostingParams,
  JobRoleList,
  LearningTarget,
  LearningTargetInput,
  Recommendations,
  SkillGap,
  TargetRole,
  TargetRoleInput,
} from '@/features/matching/api/types'
import { get, put } from '@/shared/api/client'
import { toQuery } from '@/shared/api/query'

/**
 * 매칭 계열 HTTP 계층 · 티켓 S15P21E102-281.
 *
 * **이 파일만 경로 문자열을 안다.** 봉투 해제·오류 변환은 `shared/api/client`가 하고,
 * `data` 안쪽 검증은 `parseMatching`이 한다. 버전 접두(`/v1`)는 client가 붙이므로
 * 여기서 쓰지 않는다. `features/evidence/api/evidenceApi.ts`와 같은 구조다.
 *
 * **일곱 엔드포인트 모두 BE에 아직 없다**(명세 상태 `시작 전`, BE `-279`가 구현 중).
 * 지금 호출하면 `HTTP-404`가 온다(계약 1-3의 FE 합성 코드). 화면은 훅이 값을 받지
 * 못하는 동안 기존 `StateCard`나 디자인 fixture를 그대로 그리므로 깨지지 않는다.
 *
 * `get<unknown>`으로 받는 이유는 제네릭으로 타입을 주장하면 검증 없이 그 타입이라고
 * 믿게 되기 때문이다. 실제 타입은 파서를 통과한 뒤에만 생긴다.
 *
 * 경로에 사용자 식별자가 없다 — 세션 쿠키로 who를 정한다(client의 `credentials`).
 */

/** 직무 마스터 목록 · 명세 B-FN-014 (화면 16). */
export async function fetchJobRoles(): Promise<JobRoleList> {
  return parseJobRoleList(await get<unknown>('/job-roles'))
}

/** 현재 목표 직무 · 명세 B-FN-013. */
export async function fetchTargetRole(): Promise<TargetRole> {
  return parseTargetRole(await get<unknown>('/me/target'))
}

/**
 * 목표 직무 변경 · 명세 B-FN-013.
 *
 * 명세가 PUT 전량 교체로 정했다. 바뀌면 Skill Gap·공고·추천이 모두 다른 집합을
 * 근거로 하므로, 호출부는 성공 후 매칭 계열 캐시를 통째로 무효화한다
 * (`hooks/useMatching.ts`의 `useUpdateTargetRole`).
 */
export async function updateTargetRole(body: TargetRoleInput): Promise<TargetRole> {
  return parseTargetRole(await put<unknown>('/me/target', body))
}

/**
 * 관련 채용공고 목록 · 명세 B-FN-015 (화면 02).
 *
 * 필터를 서버에 넘긴다. **화면이 목록을 걸러내지 않는다** — 한 페이지만 받은 상태에서
 * 거르면 "87건 중 12건"의 분모가 그 페이지 안의 수가 되어 사실과 달라진다.
 */
export async function fetchJobPostings(params: JobPostingParams = {}): Promise<JobPostingList> {
  const query = toQuery({
    roleId: params.roleId,
    region: params.region,
    career: params.career,
    page: params.page,
    size: params.size,
  })
  return parseJobPostingList(await get<unknown>(`/job-postings${query}`))
}

/** 기술 수요 집계 · 명세 B-FN-015. */
export async function fetchJobDemands(roleId?: string): Promise<JobDemandList> {
  return parseJobDemandList(await get<unknown>(`/job-demands${toQuery({ roleId })}`))
}

/** Skill Gap · 명세 B-FN-016 (화면 17). */
export async function fetchSkillGap(): Promise<SkillGap> {
  return parseSkillGap(await get<unknown>('/me/skill-gap'))
}

/**
 * 학습 기술 후보·What-if · 명세 B-FN-017 (화면 10·03·17 하단·11 상단).
 *
 * **네 화면이 이 한 응답을 본다.** 화면마다 따로 부르면 같은 기술의 수가 화면마다
 * 어긋날 수 있고, 명세도 후보와 What-if를 한 엔드포인트로 묶었다. 화면은 받은 배열을
 * 각자 다르게 고를 뿐이다 — 10은 `[0]`을 크게, 03은 `?tech=`로 하나를, 17은 상위 3개,
 * 11은 `techId`로 찾는다.
 */
export async function fetchRecommendations(): Promise<Recommendations> {
  return parseRecommendations(await get<unknown>('/me/recommendations'))
}

/** 현재 고른 학습 기술 · 명세 B-FN-018. */
export async function fetchLearningTarget(): Promise<LearningTarget> {
  return parseLearningTarget(await get<unknown>('/me/learning-target'))
}

/** 학습 기술 선택·변경 · 명세 B-FN-018. 확정 범위상 **최대 1개**다. */
export async function updateLearningTarget(body: LearningTargetInput): Promise<LearningTarget> {
  return parseLearningTarget(await put<unknown>('/me/learning-target', body))
}
