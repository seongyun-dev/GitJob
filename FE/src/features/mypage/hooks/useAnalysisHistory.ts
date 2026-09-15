import { useQuery } from '@tanstack/react-query'
import { fetchAnalysisHistory } from '@/features/mypage/api/mypageApi'
import type { AnalysisHistoryParams } from '@/features/mypage/api/types'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 분석 이력 조회 훅 · 티켓 S15P21E102-281.
 *
 * 엔드포인트가 아직 없어 지금은 `HTTP-404`로 끝난다. 화면은 값이 없으면 기존
 * `StateCard`를 그린다.
 *
 * 증거 계열이 아니므로 `staleTime: Infinity`를 쓰지 않는다 — 분석이 하나 더 끝나면
 * 이력이 한 줄 늘어난다.
 *
 * 화면 14의 `계정 · 연결` 영역에는 훅을 만들지 않았다. `features/auth/hooks/useMe.ts`의
 * `useMe()`가 이미 그 값을 주고 BE에도 구현돼 있다 — 같은 것을 두 번 부르지 않는다.
 */
export function useAnalysisHistory(params: AnalysisHistoryParams = {}) {
  return useQuery({
    queryKey: queryKeys.myAnalyses(params),
    queryFn: () => fetchAnalysisHistory(params),
  })
}
