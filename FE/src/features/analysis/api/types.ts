/**
 * 저장소 선택 화면의 DTO · 티켓 S15P21E102-117.
 *
 * BE `analysis/controller/dto/`가 원본이다(계약 우선순위: develop 실코드 > 명세).
 * 명세에 있으나 BE가 내려주지 않는 필드(`repositoryId` `primaryLanguage` `sizeKb`
 * `pushedAt` `permissions` `notAnalyzableReason` `fork`)는 두지 않는다.
 * 없는 필드를 optional로 미리 만들어 두면 화면이 그 값을 참조하는 코드를 갖게 되고,
 * BE가 끝내 안 주면 죽은 분기만 남는다. 계약은 docs/fe/shared-api-contract.md 2장.
 */

/**
 * `GET /me/repositories` 항목. BE `RepositorySummaryResponse`와 1:1이다.
 *
 * `description`·`language`는 GitHub이 null을 주므로 null을 받는다.
 * `analyzable`은 BE `GithubRepositoryResponse.analyzable()`의 결과이며
 * `archived || disabled`이면 false다. fork 여부는 이 값에 들어 있지 않다.
 */
export interface RepositorySummary {
  githubRepositoryId: number
  fullName: string
  name: string
  owner: string
  isPrivate: boolean
  defaultBranch: string
  description: string | null
  language: string | null
  updatedAt: string
  analyzable: boolean
}

/**
 * `GET /me/repositories/{owner}/{repo}/branches` 항목.
 *
 * `commitSha`는 조회 시점의 tip이고 분석 요청 시 서버가 다시 확정한다.
 * 화면은 표시용으로만 쓰고 요청 본문에 싣지 않는다(BE DTO 주석).
 */
export interface BranchSummary {
  name: string
  commitSha: string
  isProtected: boolean
}

/**
 * `POST /analyses` 요청 본문. BE `AnalysisCreateRequest`와 1:1이다.
 *
 * 저장소 하나 + 브랜치 하나만 받는다. analysisId·commitSha·Registry 버전은
 * 클라이언트가 보내면 권한 밖 저장소를 분석시킬 수 있어 서버가 채운다.
 */
export interface AnalysisRequestBody {
  repositoryFullName: string
  branchName: string
}

/**
 * `POST /analyses` 응답. BE `AnalysisAcceptedResponse`와 1:1이다.
 *
 * `status`를 `JobStatus`로 좁히지 않고 string으로 둔다. BE는 활성 상태로
 * `QUEUED COLLECTING RUNNING ANALYZING RATE_LIMITED CANCEL_REQUESTED`를 쓰는데
 * 와이어프레임 확정 6종과 집합이 다르다(계약 3장, 미결 2). 신규 등록은 항상
 * `QUEUED`지만 진행 중 Job을 재안내하면 나머지 값도 올 수 있다.
 *
 * `statusUrl`은 `/api/v1/analyses/{analysisId}`를 가리키나 그 GET endpoint는
 * 아직 BE에 없다(S15P21E102-133 미구현). 화면은 이 값을 링크로 쓰지 않는다.
 */
export interface AnalysisAccepted {
  analysisId: string
  status: string
  repositoryFullName: string
  branchName: string
  commitSha: string
  pollAfterSec: number
  statusUrl: string
}

/**
 * 분석 요청 1건의 대상. 저장소마다 `POST /analyses`를 1회 호출하므로
 * 이 값이 요청 본문 하나에 대응한다(2026-09-09 팀 확정: 저장소별 독립 분석).
 */
export interface AnalysisTarget {
  repositoryFullName: string
  branchName: string
}

/**
 * 저장소 1건의 요청 결과.
 *
 * 성공·실패를 union으로 나눠 두면 성공 분기에서 `analysisId`가 항상 존재한다.
 * nullable 필드로 두면 화면이 매번 null 검사를 하게 되고, 실패한 저장소를
 * 성공처럼 렌더하는 실수가 타입으로 막히지 않는다.
 *
 * 여러 요청 중 하나가 실패해도 나머지 결과를 잃지 않아야 하므로
 * 호출부는 `Promise.allSettled`로 모으고 이 형태로 정규화한다.
 */
export type AnalysisRequestOutcome =
  | { target: AnalysisTarget; ok: true; accepted: AnalysisAccepted }
  | { target: AnalysisTarget; ok: false; error: unknown }
