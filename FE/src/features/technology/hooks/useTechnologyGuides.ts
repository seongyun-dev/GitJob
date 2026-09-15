import { useQuery } from '@tanstack/react-query'
import {
  fetchPainTopics,
  fetchProjectTemplates,
  fetchTechnologyFaqs,
} from '@/features/technology/api/technologyApi'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 학습 지원 조회 훅 · 티켓 S15P21E102-281.
 *
 * 엔드포인트가 아직 없어 지금은 `HTTP-404`로 끝난다. 화면은 값이 없으면 기존
 * 상태 카드를 그린다.
 *
 * 셋 다 `techId`가 라우트 파라미터라 없을 수 있다. 없으면 조회하지 않는다 — 빈
 * 문자열로 부르면 `/technologies//faqs`가 되어 의미 없는 404를 만든다.
 *
 * 검수된 정적 자료라 자주 바뀌지 않지만 `staleTime`을 늘리지 않았다. 기본값으로 두면
 * 검수 결과가 바뀌었을 때 다음 방문에 반영된다. 무한 캐시는 증거 계열처럼 "값이
 * 불변임을 계약이 보장할 때"만 쓴다.
 */

function useTechnologyResource<T>(
  techId: string | undefined,
  queryKey: readonly unknown[],
  fetcher: (techId: string) => Promise<T>,
) {
  return useQuery({
    queryKey,
    queryFn: () => fetcher(techId as string),
    enabled: techId !== undefined && techId !== '',
  })
}

export function useProjectTemplates(techId: string | undefined) {
  return useTechnologyResource(techId, queryKeys.projectTemplates(techId ?? ''), fetchProjectTemplates)
}

export function useTechnologyFaqs(techId: string | undefined) {
  return useTechnologyResource(techId, queryKeys.technologyFaqs(techId ?? ''), fetchTechnologyFaqs)
}

export function usePainTopics(techId: string | undefined) {
  return useTechnologyResource(techId, queryKeys.technologyPainTopics(techId ?? ''), fetchPainTopics)
}
