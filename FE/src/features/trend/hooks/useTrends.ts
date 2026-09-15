import { useQuery } from '@tanstack/react-query'
import { fetchTechnologyTrend, fetchTrendOverview } from '@/features/trend/api/trendApi'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 트렌드 조회 훅 · 티켓 S15P21E102-281.
 *
 * 엔드포인트가 아직 없어(-279·데이터 팀 작업 중) 지금은 `HTTP-404`로 끝난다. 화면은
 * 값이 없으면 기존 `StateCard`를 그리므로 표시는 지금과 같다.
 *
 * `trends/compare`(B-FN-021) 훅은 두지 않았다. 후보 비교를 쓰는 화면이 아직 없고,
 * 쓰이지 않는 훅은 다음 사람이 화면 요구와 맞는지 확인할 방법이 없다. `trendApi`에
 * 호출 함수는 있으므로 화면이 생기면 훅만 여기 추가한다.
 */

/** 기술 트렌드 개요 · 화면 12. 사용자와 무관한 집계다. */
export function useTrendOverview() {
  return useQuery({
    queryKey: queryKeys.trends(),
    queryFn: fetchTrendOverview,
  })
}

/**
 * 출처별 기술 추세 · 화면 13.
 *
 * `techId`가 라우트 파라미터라 없을 수 있다. 없으면 조회하지 않는다 — 빈 문자열로
 * 부르면 `/technologies//trends`가 되어 의미 없는 404를 만든다.
 */
export function useTechnologyTrend(techId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.technologyTrends(techId ?? ''),
    queryFn: () => fetchTechnologyTrend(techId as string),
    enabled: techId !== undefined && techId !== '',
  })
}
