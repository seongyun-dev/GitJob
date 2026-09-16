import { useQuery } from '@tanstack/react-query'
import { fetchTechnologyTrends, fetchTrendCompare } from '@/features/trend/api/trendApi'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * Trend 조회 훅 (S15P21E102-279).
 *
 * 폴링하지 않는다. 공용 집계는 사용자의 분석과 무관하게 주기적으로 갱신되고, 화면을
 * 열어 둔 몇 분 사이에 바뀌지 않는다. 계산 대기를 기다리는 매칭 계열과 다르다.
 *
 * 출처별 요청을 하나로 묶지 않는 이유는 비교 화면이 출처 카드마다 독립이기 때문이다.
 * 한 출처가 실패해도 나머지 카드는 그려져야 한다.
 */

/** 공용 집계는 자주 바뀌지 않는다. 화면 전환마다 다시 부르지 않는다. */
const TREND_STALE_TIME = 5 * 60 * 1000

export function useTechnologyTrends(techId: string | undefined, periods: readonly string[]) {
  return useQuery({
    queryKey: queryKeys.technologyTrends(techId ?? '', periods),
    queryFn: () => fetchTechnologyTrends(techId as string, periods),
    enabled: techId !== undefined && techId !== '',
    staleTime: TREND_STALE_TIME,
  })
}

/**
 * 한 출처 안에서 기술 여러 개를 비교한다.
 *
 * `techIds`가 비면 부르지 않는다. 비교할 기술을 화면이 임의로 고르면 그 목록 자체가
 * 근거 없는 순위가 된다 — 목록은 사용자의 목표 직무 수요에서 온다.
 */
export function useTrendCompare(params: {
  source: string
  techIds: readonly string[]
  periods: readonly string[]
  enabled?: boolean
}) {
  return useQuery({
    queryKey: queryKeys.trendCompare(params.source, params.techIds, params.periods),
    queryFn: () =>
      fetchTrendCompare({
        source: params.source,
        techIds: params.techIds,
        periods: params.periods,
      }),
    enabled: (params.enabled ?? true) && params.techIds.length > 0,
    staleTime: TREND_STALE_TIME,
    // 한 출처의 실패가 다른 카드를 막지 않는다. 재시도로 화면 전체를 붙잡지 않는다.
    retry: false,
  })
}
