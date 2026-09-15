import {
  parseTechnologyTrend,
  parseTrendComparison,
  parseTrendOverview,
} from '@/features/trend/api/parseTrend'
import type {
  TechnologyTrend,
  TrendComparison,
  TrendOverview,
} from '@/features/trend/api/types'
import { get } from '@/shared/api/client'
import { toQuery } from '@/shared/api/query'

/**
 * 트렌드 HTTP 계층 · 티켓 S15P21E102-281.
 *
 * 이 파일만 경로 문자열을 안다. 세 엔드포인트 모두 BE에 아직 없다(명세 상태 `시작 전`).
 *
 * 인증이 필요한 조회로 표에 적혀 있지만 사용자별 값은 아니다 — 같은 기술의 추세는
 * 누가 보든 같다. 그래서 캐시 키에 `me` 접두를 쓰지 않는다(`queryKeys.trends`).
 */

/** 기술 트렌드 개요 · 명세 B-FN-020 (화면 12). */
export async function fetchTrendOverview(): Promise<TrendOverview> {
  return parseTrendOverview(await get<unknown>('/trends'))
}

/**
 * 출처별 기술 추세 · 명세 B-FN-020 (화면 13).
 *
 * `techId`를 인코딩하는 이유는 이 값이 라우트 파라미터에서 오기 때문이다. 주소창에서
 * 고칠 수 있고, `../`나 `?`가 섞이면 다른 엔드포인트를 부르게 된다.
 */
export async function fetchTechnologyTrend(techId: string): Promise<TechnologyTrend> {
  return parseTechnologyTrend(await get<unknown>(`/technologies/${encodeURIComponent(techId)}/trends`))
}

/**
 * 후보 기술 교차 비교 · 명세 B-FN-021.
 *
 * `sourceId`를 받는 이유는 **같은 출처끼리만** 비교할 수 있기 때문이다. 출처를 섞으면
 * 단위가 다른 수를 한 축에 놓게 되는데, 명세 확정 범위가 금지한 종합 점수와 같은 일이다.
 */
export async function fetchTrendComparison(
  techIds: readonly string[],
  sourceId: string,
): Promise<TrendComparison> {
  const query = toQuery({ techIds: techIds.join(','), sourceId })
  return parseTrendComparison(await get<unknown>(`/trends/compare${query}`))
}
