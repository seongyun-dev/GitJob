import { useMutation, useQuery } from '@tanstack/react-query'
import {
  fetchBranches,
  fetchRepositories,
  fetchAnalysisStatus,
  requestAnalysis,
} from '@/features/analysis/api/repositoriesApi'
import type { AnalysisRequestOutcome, AnalysisTarget } from '@/features/analysis/api/types'
import { queryKeys } from '@/shared/api/queryKeys'
import type { PageParams } from '@/shared/types/api'

/**
 * 저장소 선택 화면의 서버 상태 · 티켓 S15P21E102-117.
 *
 * 캐시 키는 `shared/api/queryKeys`의 확정 규약을 그대로 쓴다. 저장소 계열은
 * 사용자의 GitHub 상태에 따라 변하므로 `staleTime`을 늘리지 않는다(설계 4-1).
 * 4xx 재시도 차단·429 처리는 `app/providers`가 담당하므로 여기서 다시 정하지 않는다.
 */

/** BE 기본값과 같은 값을 명시해 화면과 서버의 페이지 크기 인식을 일치시킨다. */
const REPOSITORY_PER_PAGE = 30

/** 브랜치는 한 화면에서 고르므로 BE 상한(100)까지 한 번에 받는다. */
const BRANCH_PER_PAGE = 100

export function useRepositoryList(page: number) {
  const params: PageParams = { page, perPage: REPOSITORY_PER_PAGE }
  return useQuery({
    queryKey: queryKeys.repositories(params),
    queryFn: () => fetchRepositories(params),
  })
}

/**
 * 고른 저장소의 브랜치. 선택된 저장소마다 이 훅이 하나씩 붙으므로
 * 목록에 있는 저장소 전체의 브랜치를 미리 받지 않는다. BE가 요청마다 GitHub을
 * 호출하는 구조라 미리 받으면 rate limit을 목록 크기만큼 쓴다.
 *
 * `hasNext`가 true여도 추가 페이지를 따라가지 않는다. 브랜치 100개를 넘는
 * 저장소에서 필요한 것은 무한 스크롤이 아니라 BE의 브랜치 검색 파라미터다.
 */
export function useBranchList(fullName: string | null) {
  const params: PageParams = { page: 1, perPage: BRANCH_PER_PAGE }
  return useQuery({
    queryKey: queryKeys.repositoryBranches(fullName ?? '', params),
    queryFn: () => {
      if (fullName === null) {
        // enabled가 false면 호출되지 않는다. 타입을 좁히려고 두는 불변식이다.
        throw new Error('브랜치 조회는 저장소를 고른 뒤에만 실행된다.')
      }
      return fetchBranches(fullName, params)
    },
    enabled: fullName !== null,
  })
}

/**
 * 선택한 저장소들의 분석 등록.
 *
 * 저장소마다 독립 분석이고 `analysisId`도 저장소마다 따로 생긴다(2026-09-09 팀 확정).
 * 그래서 요청을 한 번에 묶지 않고 대상 수만큼 `POST /analyses`를 병렬로 보낸다.
 *
 * `Promise.all`을 쓰지 않는 이유: 하나가 reject되면 이미 접수된 나머지 저장소의
 * `analysisId`까지 잃는다. 서버에서는 분석이 시작됐는데 화면은 결과를 모르는
 * 상태가 되므로, `allSettled`로 저장소별 결과를 전부 보존한다.
 *
 * 이 mutationFn은 reject하지 않는다. 전부 실패해도 실패 목록을 담아 resolve하며,
 * 성공·실패 판정은 호출부가 `outcome.ok`로 한다.
 *
 * 동시 요청 수는 제한하지 않는다. 최대 선택 개수 정책이 아직 없어서
 * 임의의 상한을 두면 근거 없는 magic number가 된다. rate limit 노출은 알려진 gap이다.
 */
export function useAnalysisRequests() {
  return useMutation({
    mutationFn: async (targets: AnalysisTarget[]): Promise<AnalysisRequestOutcome[]> => {
      const settled = await Promise.allSettled(
        targets.map((target) => requestAnalysis(target)),
      )

      return settled.map((result, index) => {
        // targets와 settled는 같은 순서·같은 길이다. 인덱스로 대상을 되찾는다.
        const target = targets[index]
        if (target === undefined) {
          throw new Error('요청 대상과 결과 수가 어긋났습니다.')
        }
        return result.status === 'fulfilled'
          ? { target, ok: true, accepted: result.value }
          : { target, ok: false, error: result.reason }
      })
    },
  })
}

/**
 * 진행 상황 폴링.
 *
 * 다음 호출 간격을 서버가 정한다 -- 응답의 `pollAfterSeconds`다. 화면이 상수를
 * 들고 있으면 워커가 느려졌을 때 같이 조정할 방법이 없다. 종료 상태에서는 BE가
 * `null`을 주고, 그때 폴링을 멈춘다.
 *
 * `isTerminalJobStatus`를 쓰지 않는 이유는 이 응답의 상태 집합이 다섯 값으로
 * 접혀 오기 때문이다(`PARTIAL_SUCCEEDED` 포함). 종료 판정을 두 곳에서 하면
 * 어긋난다 -- 서버가 준 `pollAfterSeconds`가 유일한 기준이다.
 */
export function useAnalysisStatus(analysisId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.analysis(analysisId ?? ''),
    queryFn: () => fetchAnalysisStatus(analysisId as string),
    enabled: analysisId !== undefined && analysisId !== '',
    refetchInterval: (query) => {
      const seconds = query.state.data?.pollAfterSeconds
      return seconds === null || seconds === undefined ? false : seconds * 1000
    },
  })
}
