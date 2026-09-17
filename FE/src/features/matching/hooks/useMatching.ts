import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchJobDemands,
  fetchJobMatch,
  fetchJobMatches,
  fetchRecommendations,
  fetchSkillGap,
  fetchTarget,
  fetchWhatIf,
  saveTarget,
} from '@/features/matching/api/matchingApi'
import type { ComputeStateFields } from '@/features/matching/api/types'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 매칭 계열 조회 훅 (S15P21E102-279).
 *
 * <h2>왜 목표 직무를 먼저 읽는가</h2>
 *
 * 나머지 조회의 캐시 키가 서버가 만든 `targetKey`이기 때문이다. 직무를 바꾸면 키가
 * 달라져 자동으로 무효화되고, 이전 직무의 결과가 새 직무 화면에 남지 않는다. FE가
 * 직무·필터에서 키를 직접 조합하면 공백이나 순서 차이로 같은 조건에 캐시가 두 벌
 * 생긴다.
 *
 * <h2>왜 계산 중일 때 다시 묻는가</h2>
 *
 * 계산 대기는 오류가 아니라 곧 값이 생기는 상태다. 사용자가 새로고침해야만 결과가
 * 보이면 그건 화면이 상태를 표시만 하고 다루지는 않은 것이다.
 */

/** 계산 중일 때의 기본 폴링 간격. 서버가 `retryAfterSec`을 주면 그쪽을 따른다. */
const DEFAULT_POLL_MS = 5_000

/** 준비되지 않은 입력을 기다릴 때. 짧게 물으면 의미 없이 서버만 때린다. */
const SLOW_POLL_MS = 30_000

/**
 * 다음 조회까지의 간격.
 *
 * `PREPARING`이 아니면 폴링하지 않는다. 표본 부족이나 미보유는 기다린다고 달라지지
 * 않으므로, 계속 물으면 서버만 때리고 화면은 그대로다.
 */
function pollInterval(state: ComputeStateFields | undefined): number | false {
  if (state === undefined || state.dataStatus !== 'PREPARING') {
    return false
  }
  if (state.retryAfterSec !== null) {
    return Math.max(state.retryAfterSec, 1) * 1000
  }
  // 공고 모집단 자체가 아직 없는 경우는 우리 쪽 계산이 아니라 수집을 기다리는 것이다.
  return state.statusReason === 'COHORT_NOT_PREPARED' ? SLOW_POLL_MS : DEFAULT_POLL_MS
}

export function useTarget() {
  return useQuery({
    queryKey: queryKeys.target(),
    queryFn: fetchTarget,
  })
}

/**
 * 목표 직무 저장.
 *
 * 성공하면 매칭 계열 전체를 무효화한다. 직무가 바뀌면 비교 집합이 통째로 달라져
 * 이전 결과가 하나도 유효하지 않기 때문이다.
 */
export function useSaveTarget() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: saveTarget,
    onSuccess: (target) => {
      client.setQueryData(queryKeys.target(), target)
      void client.invalidateQueries({ queryKey: ['matching'] })
    },
  })
}

export function useJobMatches(
  targetKey: string | undefined,
  params: { page: number; perPage: number; includeConditional: boolean },
) {
  return useQuery({
    queryKey: queryKeys.matchingPostings(targetKey ?? '', params),
    queryFn: () => fetchJobMatches(params),
    enabled: targetKey !== undefined,
    refetchInterval: (query) => pollInterval(query.state.data),
  })
}

/**
 * 공고 한 건의 상세 · 티켓 S15P21E102-291.
 *
 * 목록(`useJobMatches`)과 같은 `JobMatchItemDto` 를 한 건만 받는다. 목록에서 들고
 * 넘어가지 않고 다시 부르는 이유는 주소로 바로 들어올 수 있어야 하기 때문이다 —
 * 공고 링크를 공유하거나 새로고침해도 같은 화면이 떠야 한다.
 *
 * `jobId` 가 라우트 파라미터라 없을 수 있다. 없으면 부르지 않는다. 캐시 키에
 * `targetKey` 가 함께 들어가는 것은 목록과 같은 이유다 — 목표 직무가 바뀌면 같은
 * 공고라도 대조 결과가 달라진다.
 */
export function useJobMatch(targetKey: string | undefined, jobId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.matchingPosting(targetKey ?? '', jobId ?? ''),
    queryFn: () => fetchJobMatch(jobId as string),
    enabled: targetKey !== undefined && jobId !== undefined && jobId !== '',
    refetchInterval: (query) => pollInterval(query.state.data),
  })
}

export function useSkillGap(targetKey: string | undefined) {
  return useQuery({
    queryKey: queryKeys.matchingSkillGap(targetKey ?? ''),
    queryFn: fetchSkillGap,
    enabled: targetKey !== undefined,
    refetchInterval: (query) => pollInterval(query.state.data),
  })
}

export function useRecommendations(targetKey: string | undefined) {
  return useQuery({
    queryKey: queryKeys.matchingRecommendations(targetKey ?? ''),
    queryFn: fetchRecommendations,
    enabled: targetKey !== undefined,
    refetchInterval: (query) => pollInterval(query.state.data),
  })
}

/**
 * What-if. 기술을 고르기 전에는 부르지 않는다.
 *
 * 증가 건수와 목록이 이 한 응답에서 온다. 추천 화면의 숫자를 여기에 끌어다 쓰면 두
 * 값이 서로 다른 계산에서 나올 수 있다.
 */
export function useWhatIf(
  targetKey: string | undefined,
  techId: string | undefined,
  params: { page: number; perPage: number },
) {
  return useQuery({
    queryKey: queryKeys.matchingWhatIf(targetKey ?? '', techId ?? '', params),
    queryFn: () => fetchWhatIf(techId as string, params),
    enabled: targetKey !== undefined && techId !== undefined && techId !== '',
    refetchInterval: (query) => pollInterval(query.state.data),
  })
}

/** 직무별 수요. 개인 결과가 아니라 목표 직무를 고르지 않아도 볼 수 있다. */
export function useJobDemands(params: {
  targetRole: string | undefined
  regions: readonly string[]
  careerLevels: readonly string[]
}) {
  return useQuery({
    queryKey: queryKeys.jobDemands(
      params.targetRole ?? '',
      params.regions,
      params.careerLevels,
    ),
    queryFn: () =>
      fetchJobDemands({
        targetRole: params.targetRole as string,
        regions: params.regions,
        careerLevels: params.careerLevels,
      }),
    enabled: params.targetRole !== undefined && params.targetRole !== '',
    refetchInterval: (query) => pollInterval(query.state.data),
  })
}
