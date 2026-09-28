import { QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { createAppQueryClient } from '@/app/queryClient'
import { router } from '@/app/router'
import { fetchMe } from '@/features/auth/api/me'
import {
  AUTH_SESSION_EXPIRED_EVENT,
  expireSessionCache,
  expiredSessionLoginPath,
  isSessionChangeEvent,
  refreshSessionCache,
} from '@/features/auth/sessionSync'
import { ApiError } from '@/shared/api/client'

/** GitHub 재연결 안내 화면. 라우터 정의와 같은 경로다. */
const GITHUB_CONNECT_PATH = '/onboarding/github'

/**
 * GitHub 재연결이 필요한 실패를 한곳에서 받아 재연결 화면으로 보낸다 · 티켓 156.
 *
 * 저장된 Access Token이 폐기·만료되면 저장소 조회와 분석 요청이 `AUTH-401-4`로
 * 끊긴다. 권한이 거부·해제된 경우(`AUTH-403-3`·`AUTH-403-4`)도 같다. 세 코드는
 * `errorCodes.ts`가 `RECONNECT_GITHUB`으로 묶어 둔다.
 *
 * 페이지마다 처리하면 새 화면에서 빠뜨리기 쉬워 전역에 둔다. 어느 화면에서 걸리든
 * 사용자는 같은 안내를 본다.
 */
function handleRequestError(error: unknown): void {
  if (!(error instanceof ApiError)) {
    return
  }
  if (error.action === 'REDIRECT_TO_ONBOARDING') {
    window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT))
    return
  }
  if (error.action !== 'RECONNECT_GITHUB') return
  const current = router.state.location.pathname
  if (current === GITHUB_CONNECT_PATH) {
    return
  }
  // 연결이 끝나면 원래 가려던 곳으로 돌아온다.
  const back = encodeURIComponent(current)
  void router.navigate(`${GITHUB_CONNECT_PATH}?redirectTo=${back}`, { replace: true })
}

/**
 * 4xx는 재시도하지 않는다. 401·403·404는 다시 물어도 답이 같고,
 * 429는 서버가 Retry-After로 시점을 지시하므로 훅에서 개별 처리한다.
 *
 * status는 ApiError에만 있다. 다른 예외(훅 내부 버그 등)는 상태를 알 수 없으므로
 * 일반 실패로 보고 재시도한다.
 */
function createQueryClient() {
  return createAppQueryClient(handleRequestError, (failureCount, error) => {
    if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
      return false
    }
    return failureCount < 2
  })
}

/** 로그아웃·재로그인이 다른 탭에서 일어나도 사용자 범위 캐시를 즉시 교체한다. */
function AuthSessionSync() {
  const queryClient = useQueryClient()

  useEffect(() => {
    function onStorage(event: StorageEvent) {
      if (!isSessionChangeEvent(event, window.localStorage)) {
        return
      }
      void refreshSessionCache(queryClient, fetchMe)
    }

    async function onSessionExpired() {
      const applied = await expireSessionCache(queryClient, window.localStorage)
      if (!applied) return

      const destination = expiredSessionLoginPath(
        router.state.location.pathname,
        router.state.location.search,
      )
      if (destination === null) return
      await router.navigate(destination, { replace: true })
    }

    window.addEventListener('storage', onStorage)
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, onSessionExpired)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, onSessionExpired)
    }
  }, [queryClient])

  return null
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient)

  return (
    <QueryClientProvider client={queryClient}>
      <AuthSessionSync />
      {children}
    </QueryClientProvider>
  )
}
