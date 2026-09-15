import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchJobDemands,
  fetchJobPostings,
  fetchJobRoles,
  fetchLearningTarget,
  fetchRecommendations,
  fetchSkillGap,
  updateLearningTarget,
  updateTargetRole,
  fetchTargetRole,
} from '@/features/matching/api/matchingApi'
import type { JobPostingParams } from '@/features/matching/api/types'
import { ApiError } from '@/shared/api/client'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 매칭 계열 조회 훅 · 티켓 S15P21E102-281.
 *
 * 화면은 이 훅만 부르고 경로·파서를 모른다. 엔드포인트가 아직 없으므로(-279 구현 중)
 * 지금은 전부 `HTTP-404`로 끝나고 `data`가 `undefined`로 남는다. 화면이 그 상태에서
 * 기존 `StateCard`를 그리도록 되어 있어 표시는 지금과 같다.
 *
 * ## 목표 직무가 키에 들어가는 방식
 *
 * 실제 엔드포인트는 경로에 직무를 받지 않는다 — 서버가 `/me/target`으로 들고 있다.
 * 그런데 설계 4-1은 "직무가 바뀌면 키가 달라져 자동 무효화"를 요구한다. 그래서
 * 아래 훅들은 `useTargetRole()`을 먼저 읽어 그 `roleId`를 **키에만** 넣는다. 요청에는
 * 넣지 않는다 — 서버가 이미 아는 값을 FE가 다시 주장하면 둘이 어긋날 때 화면이
 * 어느 쪽 기준인지 알 수 없게 된다.
 *
 * 목표 직무를 아직 고르지 않았으면 `roleId`가 `null`이고, 그 상태로도 조회한다.
 * 서버가 기본 집합으로 답할지 `NO_DATA`로 답할지는 서버가 정한다.
 *
 * ## 목표 직무 조회를 기다리지 않는다
 *
 * 처음에는 `enabled`로 `/me/target`이 끝날 때까지 막았다. 직무를 모르는 채 받은 응답이
 * `roleId: null` 키에 담기고, 직무가 도착하면 키가 달라져 같은 것을 또 받기 때문이다.
 *
 * **그 게이트를 뺐다.** 브라우저에서 확인해 보니 `/me/target`이 실패할 때 react-query가
 * `fetchStatus: 'paused'`로 멈추고 `status`는 `'pending'`에 머문다(온라인 판정이
 * 흔들리면 재시도를 일시정지한다). 그동안 `isPending`이 계속 `true`라 게이트가 열리지
 * 않고, **Skill Gap·추천 화면이 요청조차 보내지 못한 채 빈 화면으로 남았다.** 목표 직무
 * 조회 하나가 두 화면을 통째로 잠그는 셈이다.
 *
 * 그래서 기다리지 않고 바로 조회한다. 치르는 값은 목표 직무가 나중에 도착할 때 조회가
 * 한 번 더 나가는 것뿐이고, 그것도 **틀린 값을 보여주지 않는다** — 목표 직무는 서버가
 * 들고 있으므로 응답 자체는 처음부터 올바른 직무 기준이다. 키만 나중에 정확해진다.
 */

/** 직무 마스터 목록 · 화면 16. 사용자와 무관하므로 로그인 전에도 값이 있다. */
export function useJobRoles() {
  return useQuery({
    queryKey: queryKeys.jobRoles(),
    queryFn: fetchJobRoles,
  })
}

export function useTargetRole() {
  return useQuery({
    queryKey: queryKeys.myTarget(),
    queryFn: fetchTargetRole,
  })
}

/**
 * 목표 직무 변경.
 *
 * 성공하면 `/me/target`만 무효화한다. 매칭 계열의 나머지 키에는 `roleId`가 들어 있어
 * 새 직무가 들어오는 순간 **키 자체가 달라져** 자동으로 다시 조회된다. 여기서
 * `['me']`를 통째로 무효화하면 증거 계열까지 날아가는데, 설계 4-1은 증거가 목표 직무
 * 변경에도 살아 있어야 한다고 정했다.
 */
export function useUpdateTargetRole() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (roleId: string) => updateTargetRole({ roleId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.myTarget() })
    },
  })
}

/**
 * 관련 채용공고 · 화면 02.
 *
 * 필터를 인자로 받아 **서버에** 넘긴다. 화면이 받은 배열을 거르지 않는 이유는
 * `matchingApi.fetchJobPostings`에 적었다.
 */
export function useJobPostings(params: JobPostingParams = {}) {
  return useQuery({
    queryKey: queryKeys.jobPostings(params),
    queryFn: () => fetchJobPostings(params),
  })
}

export function useJobDemands(roleId: string | null = null) {
  return useQuery({
    queryKey: queryKeys.jobDemands(roleId),
    queryFn: () => fetchJobDemands(roleId ?? undefined),
  })
}

/** Skill Gap · 화면 17. */
export function useSkillGap() {
  const target = useTargetRole()
  return useQuery({
    queryKey: queryKeys.mySkillGap(target.data?.roleId ?? null),
    queryFn: fetchSkillGap,
  })
}

/**
 * 학습 기술 후보·What-if · 화면 10·03·17 하단·11 상단.
 *
 * 네 화면이 같은 키를 쓰므로 react-query가 요청을 한 번만 보낸다. 화면마다 다른
 * 훅을 만들면 같은 데이터를 네 번 받고, 그 사이 서버 값이 바뀌면 화면마다 다른 수를
 * 보이게 된다.
 */
export function useRecommendations() {
  const target = useTargetRole()
  return useQuery({
    queryKey: queryKeys.myRecommendations(target.data?.roleId ?? null),
    queryFn: fetchRecommendations,
  })
}

export function useLearningTarget() {
  return useQuery({
    queryKey: queryKeys.myLearningTarget(),
    queryFn: fetchLearningTarget,
  })
}

/** 학습 기술 선택. 확정 범위상 최대 1개라 교체(PUT)다. */
export function useUpdateLearningTarget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (techId: string) => updateLearningTarget({ techId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.myLearningTarget() })
    },
  })
}

/**
 * 서버가 준 메시지를 그대로 쓴다. 화면에서 코드별 문장을 다시 짜면 BE가 사유를
 * 바꿨을 때 여기가 옛말을 한다. 봉투가 아닌 실패만 일반 문구로 덮는다.
 *
 * `features/evidence/hooks/useTechnologyProfile.ts`의 `profileErrorMessage`와 같은
 * 규칙이다.
 */
export function matchingErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  return '결과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
}
