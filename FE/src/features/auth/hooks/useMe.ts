import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchMe } from '@/features/auth/api/me'
import {
  ME_QUERY_KEY,
  synchronizeSessionCache,
} from '@/features/auth/sessionSync'

export { ME_QUERY_KEY } from '@/features/auth/sessionSync'

/**
 * 로그인 사용자 조회 · 티켓 S15P21E102-246.
 *
 * `data`가 `undefined`면 아직 확인 중, `null`이면 로그아웃, 값이 있으면 로그인이다.
 * 헤더는 확인 중일 때 로그인 버튼을 그리지 않는다 — 새로고침 순간 로그인 버튼이
 * 잘못 번쩍이는 것을 막기 위해서다.
 *
 * `retry: false`: 401은 정상적인 로그아웃 신호라 재시도할 이유가 없다(그리고 `fetchMe`가
 * 401을 `null`로 접으므로 여기 도달하지도 않는다).
 *
 * `staleTime: 0` + `refetchOnMount: 'always'` + `refetchOnWindowFocus: true`: 로그인 상태는
 * 이 탭 밖에서 바뀔 수 있다(다른 곳에서 로그인/로그아웃, OAuth 왕복 후 탭 복귀). 그때
 * 로그아웃 상태로 캐시된 값이 남아 로그인 버튼이 그대로 보이면 안 된다. 헤더가 뜨거나
 * 탭이 다시 포커스될 때마다 `/me`를 다시 확인해 헤더를 실제 상태로 맞춘다. 호출은
 * 가볍고(로그인 여부의 단일 출처), 앱 헤더는 내부 화면 이동에서는 remount되지 않아
 * 매 이동마다 부르지도 않는다. 전역 기본값(`refetchOnWindowFocus: false`)을 이 쿼리에서만
 * 뒤집는다 — 인증 표시는 신선함이 캐시 절약보다 중요하다.
 */
export function useMe() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: fetchMe,
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  })

  useEffect(() => {
    if (query.data === undefined) {
      return
    }
    void synchronizeSessionCache(queryClient, window.localStorage, query.data)
  }, [query.data, queryClient])

  return query
}
