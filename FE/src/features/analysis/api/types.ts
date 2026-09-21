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
 * `POST /analyses` 요청 본문. BE `AnalysisBatchCreateRequest`와 1:1이다.
 *
 * 고른 저장소 전부를 한 번에 보낸다. 항목 하나의 모양은 예전 단건 본문과 같아서,
 * 바뀐 것은 감싸는 배열뿐이다. analysisId·commitSha·Registry 버전은 클라이언트가
 * 보내면 권한 밖 저장소를 분석시킬 수 있어 서버가 채운다.
 */
export interface AnalysisRequestBody {
  repositories: AnalysisTarget[]
}

/**
 * `POST /analyses` 응답. BE `AnalysisAcceptedResponse`와 1:1이다.
 *
 * `status`를 `JobStatus`로 좁히지 않고 string으로 둔다. BE는 활성 상태로
 * `QUEUED COLLECTING RUNNING ANALYZING RATE_LIMITED CANCEL_REQUESTED`를 쓰는데
 * 와이어프레임 확정 6종과 집합이 다르다(계약 3장, 미결 2). 신규 등록은 항상
 * `QUEUED`지만 진행 중 Job을 재안내하면 나머지 값도 올 수 있다.
 *
 * `statusUrl`은 `/api/v1/analyses/{analysisId}`를 가리킨다. 이 endpoint는 BE에
 * 구현됐다 — 응답 모양은 `AnalysisStatus`다.
 */
export interface AnalysisAccepted {
  analysisId: string
  status: string
  repositoryFullName: string
  branchName: string
  commitSha: string
  statusUrl: string
}

/** 저장소 하나의 결말. 재사용은 실패가 아니라 세 번째 값이다. */
export type AnalysisBatchOutcome = 'ACCEPTED' | 'REUSED' | 'FAILED'

/**
 * `POST /analyses` 응답 항목. BE `AnalysisBatchAcceptedResponse.ItemResponse`와 1:1이다.
 *
 * `requestedRepositoryFullName`이 따로 있는 이유는, 서버가 저장소 이름을 GitHub의
 * 정규 표기로 바꾸기 때문이다. 화면은 목록에서 받은 이름으로 선택을 키잉하므로
 * 보낸 이름이 함께 돌아와야 결과를 어느 카드에 붙일지 알 수 있다.
 */
export interface AnalysisBatchItem {
  requestedRepositoryFullName: string
  outcome: AnalysisBatchOutcome
  analysisId: string | null
  status: string | null
  repositoryFullName: string | null
  branchName: string | null
  commitSha: string | null
  statusUrl: string | null
  errorCode: string | null
  message: string | null
}

/**
 * `POST /analyses` 응답. 하나라도 새로 만들었으면 202, 아니면 200이다.
 *
 * 전부 실패해도 오류가 아니라 이 본문이 온다. 사유가 저장소마다 다를 수 있는데
 * 오류 봉투는 코드와 메시지를 한 쌍만 실을 수 있어, 가장 필요한 순간에 나머지를 잃는다.
 */
export interface AnalysisBatchAccepted {
  batchId: string | null
  totalCount: number
  acceptedCount: number
  reusedCount: number
  failedCount: number
  pollAfterSeconds: number | null
  statusUrl: string
  items: AnalysisBatchItem[]
}

/** `GET /me/analyses/latest-batch`의 구성원 하나. */
export interface LatestBatchItem {
  analysisId: string
  repositoryId: string
  repositoryFullName: string | null
  branchName: string
  commitSha: string
  /** QUEUED · RUNNING · SUCCEEDED · PARTIAL_SUCCEEDED · FAILED */
  analysisStatus: string
  currentStage: string
  requestedAt: string
  errorCode: string | null
}

export interface LatestBatch {
  batchId: string
  requestedAt: string
  totalCount: number
  completedCount: number
  failedCount: number
  /** 진행 중인 구성원이 없으면 null. 폴링을 멈추는 유일한 신호다 */
  pollAfterSeconds: number | null
  items: LatestBatchItem[]
}

/**
 * `GET /me/analyses/latest-batch` 응답.
 *
 * `canSubmit`이 `batch` 안이 아니라 밖에 있는 것은 판정 단위가 다르기 때문이다.
 * 제출 차단은 **사용자 단위**이고, 배치가 생기기 전에 만들어진 분석도 진행 중이면
 * 막는다. 배치 안에 두면 그런 사용자가 "제출 가능"을 보고 눌렀다가 409를 맞는다.
 *
 * 한 번도 분석한 적이 없으면 `batch`가 null이다. 404가 아니라 200이다.
 */
export interface LatestBatchView {
  canSubmit: boolean
  /**
   * 한 번에 고를 수 있는 저장소 수. 서버가 정한다.
   *
   * 화면이 상수를 들고 있으면 서버가 상한을 바꾼 날 조용히 어긋나고, 사용자는 버튼을
   * 눌러야만 거절을 알게 된다. 이 값이 있으면 고르는 동안 막을 수 있다.
   */
  maxBatchSize: number
  batch: LatestBatch | null
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
  | { target: AnalysisTarget; ok: true; accepted: AnalysisAccepted; reused: boolean }
  | { target: AnalysisTarget; ok: false; error: AnalysisRequestError }

/**
 * 저장소 하나가 왜 실패했는지.
 *
 * `unknown`이던 자리를 좁혔다. 배치 응답은 항목마다 코드와 문장을 함께 주므로
 * 호출부가 `instanceof`로 되짚을 필요가 없고, 되짚을 수도 없다 — 이제 실패는
 * 예외가 아니라 성공 응답 안의 값이다.
 */
export interface AnalysisRequestError {
  code: string | null
  message: string
}

/**
 * 분석 진행 상황 · `GET /analyses/{analysisId}` 응답.
 *
 * BE `AnalysisStatusResponse`가 원본이다. `analysisStatus`는 다섯 값으로 접혀서
 * 온다 — 저장은 열려 있고 응답 경계에서만 닫으므로, 화면이 모르는 값을 받는 일은
 * 없다.
 *
 * `completedCount`/`totalCount`는 **저장소 수**이지 파일 수가 아니다. 지금은 분석
 * 한 건이 저장소 하나라 `totalCount`가 1이고 `progressPercent`는 0 또는 100만
 * 나온다. 워커가 중간 진행을 발행하지 않아 그 사이 값을 만들 근거가 없다.
 */
export interface AnalysisStatus {
  analysisId: string
  /** QUEUED · RUNNING · SUCCEEDED · PARTIAL_SUCCEEDED · FAILED */
  analysisStatus: string
  currentStage: string
  completedCount: number
  totalCount: number
  progressPercent: number
  requestedAt: string
  startedAt: string | null
  finishedAt: string | null
  /** 종료 상태면 null. 아니면 이 초만큼 뒤에 다시 물으라는 뜻이다 */
  pollAfterSeconds: number | null
  errorCode: string | null
  stages: { stage: string; status: string; processed: number; total: number }[]
  repositories: {
    repositoryId: string
    branchName: string
    commitSha: string
    status: string
    errorCode: string | null
  }[]
}

/**
 * 분석 대상 저장소 선택 · 명세 B-FN-003 (티켓 S15P21E102-281).
 *
 * BE 미구현이라 명세가 기준이다. 선택은 **서버에 저장되는 값**이다 — 화면이
 * `useState`로만 들고 있으면 새로고침이나 다른 기기에서 다시 고르게 된다.
 *
 * 저장소마다 브랜치를 함께 고른다. 같은 저장소라도 브랜치가 다르면 다른 코드라
 * 분석 결과가 달라지므로, 저장소 이름만 저장하면 무엇을 분석했는지 특정할 수 없다.
 */
export interface RepositorySelectionEntry {
  /** `owner/repo`. 조회 응답의 `fullName`과 같은 값이다. */
  fullName: string
  branchName: string
}

export interface RepositorySelection {
  items: RepositorySelectionEntry[]
  /** 한 번도 저장한 적이 없으면 null. 빈 선택을 저장한 것과 구분된다. */
  updatedAt: string | null
}

/** `PUT /me/repositories/selection` 요청 본문. 명세가 PUT 전량 교체로 정했다. */
export interface RepositorySelectionInput {
  items: RepositorySelectionEntry[]
}
