import { useQuery } from '@tanstack/react-query'
import {
  fetchTechnologyEvidence,
  fetchTechnologyProfile,
  fetchTechnologySummary,
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
 * `PENDING` 재시도 상한. 서버가 5초를 지시하므로 6회면 약 30초다.
 *
 * 상한을 두는 이유는 생성이 노트북 GPU 한 대에서 돌기 때문이다. 탭을 열어 둔
 * 사람이 무한히 5초마다 물으면 그 자리를 다른 요청이 못 쓴다. 상한에 닿으면
 * 폴링을 멈추고 화면이 다시 부를 길을 준다.
 */
const MAX_PENDING_POLLS = 6

/**
 * 기술 하나의 요약.
 *
 * `enabled`는 목록 화면을 위해 열어 둔다. 카드 열두 장이 마운트되자마자 각자
 * 부르면 BE 의 GPU 자리가 둘뿐이라 대부분이 `PENDING` 으로 떨어지고 첫 화면이
 * 재시도로 출렁인다. 부르는 쪽이 "지금 이 기술을 보고 있다"고 말할 때만 켠다.
 *
 * `staleTime`을 길게 두는 것은 같은 Fact Pack 이면 BE 캐시에서 그대로 나오기
 * 때문이다. 화면을 오갈 때마다 다시 묻는 것은 의미가 없고, 분석이 새로 끝나면
 * `['me','technologies']` 무효화가 이 키까지 함께 밀어낸다.
 */
export function useTechnologySummary(techId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.myTechnologySummary(techId ?? ''),
    queryFn: () => fetchTechnologySummary(techId as string),
    enabled: enabled && techId !== undefined && techId !== '',
    /*
     * `PENDING`은 GPU 자리가 없었다는 뜻이라 기다리면 채워진다. `READY`와 `NONE`은
     * 다시 물어도 같으므로 멈춘다.
     */
    refetchInterval: (query) => {
      const data = query.state.data
      if (data === undefined || data.status !== 'PENDING') {
        return false
      }
      if (query.state.dataUpdateCount >= MAX_PENDING_POLLS) {
        return false
      }
      return Math.max(data.retryAfterSeconds, 1) * 1000
    },
    staleTime: 10 * 60 * 1000,
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
