import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'

type RetryPolicy = (failureCount: number, error: unknown) => boolean

/** Query와 Mutation이 같은 인증·GitHub 오류 경계를 사용하게 한다. */
export function createAppQueryClient(
  onError: (error: unknown) => void,
  retry: RetryPolicy = (failureCount) => failureCount < 2,
): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        retry,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  })
}
