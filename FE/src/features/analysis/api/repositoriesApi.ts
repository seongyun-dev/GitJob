import type {
  AnalysisBatchAccepted,
  AnalysisRequestBody,
  AnalysisStatus,
  LatestBatchView,
  BranchSummary,
  RepositorySelection,
  RepositorySelectionInput,
  RepositorySummary,
} from '@/features/analysis/api/types'
import { get, post, put } from '@/shared/api/client'
import type { PageParams, PageResponse } from '@/shared/types/api'

/**
 * 저장소 선택 화면의 HTTP 계층 · 티켓 S15P21E102-117.
 *
 * 이 파일만 경로 문자열을 안다. 봉투 해제·오류 변환은 `shared/api/client`가 하고
 * 여기서는 경로와 타입만 고정한다. 버전 접두(`/v1`)는 client가 붙이므로 쓰지 않는다.
 */

/** BE는 page 1-base, perPage 최대 100이다. 빈 값은 BE 기본값에 맡긴다. */
function pageQuery(params: PageParams): string {
  const query = new URLSearchParams()
  if (params.page !== undefined) {
    query.set('page', String(params.page))
  }
  if (params.perPage !== undefined) {
    query.set('perPage', String(params.perPage))
  }
  const serialized = query.toString()
  return serialized === '' ? '' : `?${serialized}`
}

export function fetchRepositories(params: PageParams): Promise<PageResponse<RepositorySummary>> {
  return get<PageResponse<RepositorySummary>>(`/me/repositories${pageQuery(params)}`)
}

/**
 * `fullName`은 `owner/repo`이며 BE는 두 개의 경로 변수로 받는다.
 * 저장소 이름에 `.`이나 유니코드가 들어갈 수 있어 세그먼트마다 인코딩한다.
 */
export function fetchBranches(
  fullName: string,
  params: PageParams,
): Promise<PageResponse<BranchSummary>> {
  const [owner, repository] = fullName.split('/')
  if (owner === undefined || repository === undefined || owner === '' || repository === '') {
    return Promise.reject(new Error(`저장소 이름 형식이 올바르지 않습니다: ${fullName}`))
  }
  const path = `/me/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(repository)}/branches`
  return get<PageResponse<BranchSummary>>(`${path}${pageQuery(params)}`)
}

/**
 * 고른 저장소 전부를 한 묶음으로 등록한다. 결과를 기다리지 않는다.
 *
 * 하나라도 새로 만들면 202, 아니면 200이고 본문 형태는 같다. 저장소별 결말은
 * `items`에 담겨 오므로 실패도 예외가 아니라 값으로 돌아온다 -- 진행 중인 분석이
 * 있어 요청 자체가 거절된 경우(409)만 예외가 된다.
 */
export function requestAnalyses(body: AnalysisRequestBody): Promise<AnalysisBatchAccepted> {
  return post<AnalysisBatchAccepted>('/analyses', body)
}

/**
 * 지금 무엇이 돌고 있나. 저장소 선택 화면이 폴링하는 단 하나의 조회다.
 *
 * 분석 하나마다 따로 묻지 않는다. 저장소 넷을 고르면 폴링도 넷이 되고, 그 넷이
 * 저마다 다른 순간의 상태를 들고 있어 화면이 몇 개가 끝났는지 말할 수 없다.
 */
export function fetchLatestAnalysisBatch(): Promise<LatestBatchView> {
  return get<LatestBatchView>('/me/analyses/latest-batch')
}

/** 진행 상황. 종료 상태가 될 때까지 화면이 되풀이해 부른다. */
export function fetchAnalysisStatus(analysisId: string): Promise<AnalysisStatus> {
  return get<AnalysisStatus>(`/analyses/${encodeURIComponent(analysisId)}`)
}

/**
 * 분석 대상 저장소 선택 조회·저장 · 명세 B-FN-003 (티켓 S15P21E102-281).
 *
 * **BE에 아직 없다**(명세 상태 `시작 전`). 지금 부르면 `HTTP-404`가 온다.
 *
 * 위의 `fetchRepositories`와 다른 것이다. 저쪽은 GitHub이 주는 저장소 **목록**이고
 * 이쪽은 그중 무엇을 분석할지에 대한 **사용자의 선택**이다. 목록은 매번 GitHub에서
 * 새로 오지만 선택은 서버가 들고 있어야 새로고침을 견딘다.
 *
 * 파서를 쓰지 않고 `get<T>`로 받는 이유는 `features/analysis/api`가 처음부터 그
 * 방식이기 때문이다(티켓 117). 이 파일 안에서 두 방식을 섞으면 다음 사람이 어느
 * 쪽이 규칙인지 알 수 없다. 이 계열 전체를 파서로 옮기는 것은 별도 정리다.
 */
export function fetchRepositorySelection(): Promise<RepositorySelection> {
  return get<RepositorySelection>('/me/repositories/selection')
}

/** 명세가 PUT 전량 교체로 정했다. 부분 갱신이 아니므로 화면은 전체 목록을 보낸다. */
export function updateRepositorySelection(
  body: RepositorySelectionInput,
): Promise<RepositorySelection> {
  return put<RepositorySelection>('/me/repositories/selection', body)
}
