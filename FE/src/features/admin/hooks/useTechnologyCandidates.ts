import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult } from '@tanstack/react-query'
import {
  fetchRegistryStatus,
  fetchTechnologyCandidates,
  promoteCandidate,
  publishRegistryDraft,
  rejectCandidate,
} from '@/features/admin/api/technologyCandidates'
import type {
  PromoteInput,
  PromotionResult,
  RegistryStatus,
  TechnologyCandidate,
} from '@/features/admin/api/technologyCandidates'
import { ApiError } from '@/shared/api/client'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 후보 목록은 분석이 끝날 때마다 늘어나므로 캐시를 오래 잡지 않는다.
 * 증거 계열의 무한 staleTime과 다른 이유가 여기에 있다.
 */
export function useTechnologyCandidates(limit: number) {
  return useQuery({
    queryKey: queryKeys.technologyCandidates(limit),
    queryFn: () => fetchTechnologyCandidates(limit),
  })
}

export function useRegistryStatus() {
  return useQuery({
    queryKey: queryKeys.registryStatus(),
    queryFn: fetchRegistryStatus,
  })
}

/**
 * 결정 하나가 목록과 레지스트리 상태를 모두 바꾼다.
 *
 * 낙관적 업데이트는 하지 않는다. 관리자 둘이 같은 행을 누르면 뒤에 누른
 * 쪽은 409를 받는데, 미리 지워 둔 행을 되살리는 것보다 서버가 실제로 무엇을
 * 받아들였는지 다시 읽는 편이 정확하다.
 */
function useDecision<TInput, TResult>(
  mutationFn: (input: TInput) => Promise<TResult>,
): UseMutationResult<TResult, Error, TInput> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn,
    onSettled: () => {
      // 실패했을 때도 다시 읽는다. 409는 "다른 사람이 이미 처리했다"는
      // 뜻이므로, 그 결과를 보여주는 것이 화면이 해야 할 일이다.
      void queryClient.invalidateQueries({ queryKey: ['admin'] })
    },
  })
}

export function usePromoteCandidate() {
  return useDecision<PromoteInput, PromotionResult>(promoteCandidate)
}

export function useRejectCandidate() {
  return useDecision<{ candidateId: number; note?: string }, RegistryStatus>(
    ({ candidateId, note }) => rejectCandidate(candidateId, note),
  )
}

export function usePublishRegistry() {
  return useDecision<void, RegistryStatus>(publishRegistryDraft)
}

/**
 * 서버가 준 메시지를 그대로 쓴다.
 *
 * 화면에서 코드별 문장을 다시 짜면 BE가 사유를 바꿔도 여기가 옛말을 하게 된다.
 * 봉투가 아닌 실패(네트워크 단절 등)만 일반 문구로 덮는다.
 */
export function decisionMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  return '처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'
}

export type { PromotionResult, RegistryStatus, TechnologyCandidate }
