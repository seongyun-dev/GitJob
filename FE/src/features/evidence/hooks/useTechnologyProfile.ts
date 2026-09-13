import { useQuery } from '@tanstack/react-query'
import {
  fetchTechnologyEvidence,
  fetchTechnologyProfile,
} from '@/features/evidence/api/technologiesApi'
import { ApiError } from '@/shared/api/client'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 기술별 판정 한 장.
 *
 * 증거 계열이지만 `staleTime: Infinity`를 쓰지 않는다. 설계 4-1의 무한 캐시는
 * `analysisId`에 묶인 조회를 위한 것이고, 이 화면은 "내 저장소들의 최신 상태"라
 * 분석이 하나 더 끝나면 답이 달라진다.
 */
export function useTechnologyProfile() {
  return useQuery({
    queryKey: queryKeys.myTechnologies(),
    queryFn: fetchTechnologyProfile,
  })
}

export function useTechnologyEvidence(techId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.myTechnologyEvidence(techId ?? ''),
    queryFn: () => fetchTechnologyEvidence(techId as string),
    enabled: techId !== undefined && techId !== '',
  })
}

/**
 * 서버가 준 메시지를 그대로 쓴다. 화면에서 코드별 문장을 다시 짜면 BE가 사유를
 * 바꿨을 때 여기가 옛말을 한다. 봉투가 아닌 실패만 일반 문구로 덮는다.
 */
export function profileErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  return '결과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
}
