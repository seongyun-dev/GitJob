import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchRepositorySelection,
  updateRepositorySelection,
} from '@/features/analysis/api/repositoriesApi'
import type { RepositorySelectionInput } from '@/features/analysis/api/types'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 분석 대상 저장소 선택 훅 · 티켓 S15P21E102-281.
 *
 * 엔드포인트가 아직 없어(명세 B-FN-003 `시작 전`) 지금은 `HTTP-404`로 끝난다.
 * `RepositorySelectionPage`는 선택을 `useState`로 들고 있으므로 화면 동작은 그대로다.
 *
 * 키는 `queryKeys.repositorySelection()`이다 — 계약 문서 1-4가 `['repositories',
 * 'selection']`으로 이미 자리를 잡아 두었고, 281이 새로 만들지 않았다.
 */
export function useRepositorySelection() {
  return useQuery({
    queryKey: queryKeys.repositorySelection(),
    queryFn: fetchRepositorySelection,
  })
}

/**
 * 선택 저장.
 *
 * 성공하면 선택 키만 무효화한다. 저장소 **목록**(`['repositories','list']`)은 GitHub이
 * 주는 값이라 내 선택으로 달라지지 않는다 — 함께 무효화하면 GitHub API를 쓸데없이
 * 다시 부르고, 그쪽은 한도가 있는 호출이다(`REPO-429-1`).
 */
export function useUpdateRepositorySelection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: RepositorySelectionInput) => updateRepositorySelection(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.repositorySelection() })
    },
  })
}
