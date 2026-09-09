import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError } from '@/shared/api/client'

/**
 * 4xx는 재시도하지 않는다. 401·403·404는 다시 물어도 답이 같고,
 * 429는 서버가 Retry-After로 시점을 지시하므로 훅에서 개별 처리한다.
 *
 * status는 ApiError에만 있다. 다른 예외(훅 내부 버그 등)는 상태를 알 수 없으므로
 * 일반 실패로 보고 재시도한다.
 */
function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            return false
          }
          return failureCount < 2
        },
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  })
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient)

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
