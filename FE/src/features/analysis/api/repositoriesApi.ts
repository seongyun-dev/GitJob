import type {
  AnalysisAccepted,
  AnalysisRequestBody,
  AnalysisStatus,
  BranchSummary,
  RepositorySummary,
} from '@/features/analysis/api/types'
import { get, post } from '@/shared/api/client'
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

/** 등록만 하고 결과를 기다리지 않는다. 신규는 202, 진행 중 Job 재안내는 200이며 본문 형태는 같다. */
export function requestAnalysis(body: AnalysisRequestBody): Promise<AnalysisAccepted> {
  return post<AnalysisAccepted>('/analyses', body)
}

/** 진행 상황. 종료 상태가 될 때까지 화면이 되풀이해 부른다. */
export function fetchAnalysisStatus(analysisId: string): Promise<AnalysisStatus> {
  return get<AnalysisStatus>(`/analyses/${encodeURIComponent(analysisId)}`)
}
