import { useMutation, useQuery } from '@tanstack/react-query'
import {
  fetchBranches,
  fetchLatestAnalysisBatch,
  fetchRepositories,
  fetchAnalysisStatus,
  requestAnalyses,
} from '@/features/analysis/api/repositoriesApi'
import type { AnalysisBatchAccepted, AnalysisTarget } from '@/features/analysis/api/types'
import { batchPollInterval } from '@/features/analysis/model/analysisBatch'
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
 * 그 사실은 그대로다 -- 묶이는 것은 요청뿐이고, 서버는 여전히 저장소마다 Job을 만든다.
 *
 * 예전에는 저장소 수만큼 `POST /analyses`를 병렬로 보내고 `Promise.allSettled`로
 * 결과를 모았다. 그렇게는 "한 사용자에 한 묶음"을 서버가 판정할 수 없다 -- 같은 묶음의
 * 두 번째 호출이 첫 번째 호출에 막히기 때문이다. 호출을 하나로 합치면 그 판정이
 * 가능해지고, 덤으로 저장소 넷을 고른 요청이 왕복 하나가 된다.
 *
 * 저장소별 실패는 여전히 잃지 않는다. 실패가 예외가 아니라 응답 안의 항목으로 오므로
 * `allSettled`가 하던 일을 서버가 대신한다. 던지는 경우는 요청 전체가 거절됐을 때뿐이다
 * (진행 중 분석 409, GitHub 연결 끊김).
 */
export function useAnalysisRequests() {
  return useMutation({
    mutationFn: (targets: AnalysisTarget[]): Promise<AnalysisBatchAccepted> =>
      requestAnalyses({ repositories: targets }),
  })
}

/**
 * 지금 돌고 있는 묶음 하나.
 *
 * 저장소마다 폴링하지 않는 이유가 둘이다. 넷을 고르면 폴링도 넷이 되어 서버를 그만큼
 * 두드리고, 그 넷이 저마다 다른 순간의 상태를 들고 있어 화면이 "몇 개가 끝났는지"를
 * 말할 수 없다. 묶음을 한 번에 읽으면 그 수가 서버가 센 값 그대로다.
 *
 * `enabled`를 걸지 않는다. 분석을 한 번도 하지 않은 사용자에게도 `batch: null`이 200으로
 * 오고, 그 값이 곧 "제출해도 된다"는 답이다.
 */
export function useLatestAnalysisBatch() {
  return useQuery({
    queryKey: queryKeys.latestAnalysisBatch(),
    queryFn: fetchLatestAnalysisBatch,
    refetchInterval: (query) => batchPollInterval(query.state.data),
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
