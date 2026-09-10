# FE shared API 계약 — BE 실구현 기준

> 상태: 결정 확정 (2026-09-09, FE 담당) · 코드 반영은 `S15P21E102-170` 브랜치에서 진행
>
> 기준일: 2026-09-09
>
> 기준 코드: BE `origin/develop` `13b2a92` —
> `global/response/ApiResponse.java` · `global/response/ErrorResponse.java` ·
> `global/exceptions/ErrorCode.java` · `analysis/controller/dto/PageResponse.java` ·
> `analysis/controller/RepositoryController.java` · `analysis/domain/AnalysisJob.java`
>
> 이 문서는 `FE/src/shared/api/`와 `FE/src/shared/types/`가 따르는 계약이다.
> **BE에 구현된 것은 BE 코드를 따르고, 아직 없는 것만 Notion 명세를 유지한다**(2026-09-09 결정).
> [B조 API 명세서](https://app.notion.com/p/3cdae4cfead28108a0a5cf55da67a004)·
> [프론트엔드 설계](https://app.notion.com/p/3ceae4cfead281c5bf9bf1863c5ce610) 6-3장과
> 다른 부분은 2장에 표로 남기고, 어느 쪽을 고칠지는 팀 결정으로 넘긴다.

## 1. 계약

### 1-1. 응답 봉투 (구현됨)

```json
// 성공 — data는 null 허용
{ "message": "요청이 성공적으로 처리되었습니다.", "data": { } }

// 실패
{ "code": "REPO-429-1", "message": "GitHub API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요." }
```

- `meta`는 없다. 명세의 `meta.generatedAt / fetchedAt / cached / registryVersion`은 BE `ApiResponse`에 없으므로 FE 타입에서 제외한다. BE가 추가하면 optional로 복원한다.
- 본문이 없거나 JSON이 아니면 FE는 봉투 오류로 처리한다. 204를 성공으로 취급하지 않는다 (미결 4-3).

### 1-2. 페이징 (구현됨 — `GET /me/repositories`, `GET /me/repositories/{owner}/{repo}/branches`)

```ts
interface PageResponse<T> {
  items: T[]
  page: number      // 1-base. BE 기본값 1
  perPage: number   // BE 기본값 30 (브랜치 100), 최대 100
  hasNext: boolean  // GitHub이 전체 개수를 주지 않아 totalCount가 없다
}
interface PageParams { page?: number; perPage?: number }
```

명세의 `page`(0-base) · `size` · `totalCount`와 다르다. 근거는 BE [저장소 선택과 분석 요청](../be/repository-analysis-request.md).

### 1-3. 오류 코드 → 화면 처리 (구현됨)

`FE/src/shared/api/errorCodes.ts` 한 곳에서만 매핑한다. 컴포넌트에 코드 문자열 비교를 흩어놓지 않는다.

| 코드 | BE 상수 | HTTP | 발생 상황 | 화면 처리 |
|---|---|---|---|---|
| `G-400-1` | `INVALID_REQUEST_BODY` | 400 | 요청 본문 오류 (저장소 fullName 형식 등) | `SHOW_INLINE_ERROR` |
| `G-400-2` | `INVALID_REQUEST_PARAMETER` | 400 | 파라미터 오류 | `SHOW_INLINE_ERROR` |
| `G-500` | `INTERNAL_SERVER_ERROR` | 500 | 서버 내부 오류 | `SHOW_GENERIC_ERROR` |
| `AUTH-401-1` | `UNAUTHORIZED` | 401 | 세션 없음·만료 (`JwtAuthenticationEntryPoint`) | `REDIRECT_TO_ONBOARDING` |
| `AUTH-401-3` | `INVALID_REFRESH_TOKEN` | 401 | 세션 만료 (refresh 경로) | `REDIRECT_TO_ONBOARDING` |
| `AUTH-401-2` | `OAUTH_TOKEN_EXCHANGE_FAILED` | 401 | code → Access Token 교환 실패 | `REDIRECT_TO_ONBOARDING` |
| `AUTH-400-2` | `OAUTH_INVALID_STATE` | 400 | OAuth state 불일치·쿠키 없음 | `REDIRECT_TO_ONBOARDING` |
| `AUTH-400-1` | `OAUTH_REDIRECT_NOT_ALLOWED` | 400 | `redirectTo`가 허용 목록에 없음 | `SHOW_GENERIC_ERROR` |
| `AUTH-403-3` | `OAUTH_ACCESS_DENIED` | 403 | 사용자가 GitHub 권한 요청을 거부 (콜백 `status=denied&code=`) | `RECONNECT_GITHUB` |
| `AUTH-403-4` | `OAUTH_SCOPE_NOT_GRANTED` | 403 | `read:user repo` 중 일부만 승인 | `RECONNECT_GITHUB` |
| `AUTH-401-4` | `GITHUB_TOKEN_INVALID` | 401 | 저장된 GitHub 토큰 폐기·만료 | `RECONNECT_GITHUB` |
| `AUTH-503-1` | `OAUTH_GITHUB_UNAVAILABLE` | 503 | GitHub 인증 서버 연결 실패 | `SHOW_RETRY` |
| `REPO-403-1` | `REPOSITORY_ACCESS_DENIED` | 403 | 저장소 분석 권한 없음 | `SHOW_FORBIDDEN` |
| `REPO-404-1` | `REPOSITORY_NOT_FOUND` | 404 | 저장소 없음 또는 접근 불가 | `SHOW_INLINE_ERROR` |
| `REPO-404-2` | `BRANCH_NOT_FOUND` | 404 | 브랜치 없음 | `SHOW_INLINE_ERROR` |
| `REPO-409-1` | `REPOSITORY_NOT_ANALYZABLE` | 409 | 보관·비활성 저장소 분석 요청 | `SHOW_UNANALYZABLE` |
| `REPO-429-1` | `GITHUB_RATE_LIMITED` | 429 | GitHub API 한도 초과. `Retry-After` 헤더 → `retryAfterSec` | `SHOW_RATE_LIMIT` |
| `REPO-503-1` | `GITHUB_UNAVAILABLE` | 503 | GitHub API 장애 | `SHOW_RETRY` |

`REPO-404-1`·`REPO-404-2`를 404 화면이 아니라 인라인 오류로 두는 이유: 두 코드는 S2 선택 폼에서 저장소·브랜치를 고른 직후 발생하므로, 페이지를 벗어나지 않고 선택 항목 옆에 표시하는 것이 맞다.

4xx는 재시도하지 않는다. 5xx·네트워크 실패만 2회까지 재시도하고, 429는 자동 재시도 없이 `retryAfterSec`를 안내한다 (`FE/src/app/providers.tsx`).

**FE 합성 코드** — 서버 응답이 봉투가 아닐 때 FE가 만든다. BE 코드와 섞이지 않게 `CLIENT-` 접두를 쓴다.

| 코드 | 상황 | 화면 처리 |
|---|---|---|
| `CLIENT-NETWORK` | `fetch` 자체가 실패 (네트워크 단절, CORS 차단). `status: 0` | `SHOW_RETRY` |
| `CLIENT-ENVELOPE` | 2xx인데 본문이 성공 봉투가 아님 (빈 본문, 204, HTML) | `SHOW_GENERIC_ERROR` |
| `HTTP-{status}` | 비2xx인데 실패 봉투가 아님 (프록시 502, Spring 기본 오류 페이지) | `SHOW_GENERIC_ERROR` |

**BE 미구현 — 명세 유지** (137·138 착수 전 BE 구현 확인)

| 코드 | 명세 의미 | 화면 처리 |
|---|---|---|
| `EVD-404-1` | 성공한 Snapshot 없음 | `SHOW_EMPTY_WITH_CTA` |
| `EVD-404-2` | Registry에 없는 techId | `SHOW_NOT_FOUND` |
| `EVD-404-3` | 해당 Snapshot에서 근거 0건 — 오류가 아니라 정상 빈 결과 | `SILENT_EMPTY` |

관리자 화면(티켓 14)의 코드는 넷 다 `SHOW_INLINE_ERROR`다. 화면 전체를 오류로 덮으면
다른 후보를 계속 처리할 수 없는데, 실제로 막힌 것은 그 한 행이다.

| 코드 | BE 상수 | HTTP | 발생 상황 | 화면 처리 |
|---|---|---|---|---|
| `ADMIN-400-1` | `INVALID_TECHNOLOGY_ID` | 400 | 기술 식별자 형식 오류 | `SHOW_INLINE_ERROR` |
| `ADMIN-404-1` | `TECHNOLOGY_CANDIDATE_NOT_FOUND` | 404 | 후보 없음 | `SHOW_INLINE_ERROR` |
| `ADMIN-409-1` | `TECHNOLOGY_CANDIDATE_ALREADY_DECIDED` | 409 | 다른 관리자가 이미 처리 | `SHOW_INLINE_ERROR` |
| `ADMIN-409-2` | `REGISTRY_DRAFT_EMPTY` | 409 | 발행할 초안 없음 | `SHOW_INLINE_ERROR` |

`ADMIN-409-1`은 장애가 아니다. 관리자 둘이 같은 목록을 보고 같은 행을 누르는 일이 있고,
목록을 새로 읽으면 무엇이 어떻게 처리됐는지 그대로 보인다.

**삭제** (BE에 없고 명세와 충돌): `AUTH-403-1` `AUTH-409-1` `REPO-400-1` `REPO-422-1` `COMMON-400-1` `COMMON-404-1` `COMMON-429-1` `COMMON-503-1`

`SHOW_SELECTION_LOCKED` 액션도 함께 삭제한다. 명세는 진행 중 분석이 있으면 `REPO-409-1`로 선택을 잠그지만, BE는 이 경우를 오류가 아니라 **200 + "이미 진행 중인 분석이 있습니다."**로 응답한다 (`AnalysisController.requestAnalysis`, `submission.created() == false`). 대응 코드가 없는 액션은 두지 않는다.

### 1-4. 캐시 키 (`FE/src/shared/api/queryKeys.ts`)

| 키 | 상태 | 비고 |
|---|---|---|
| `['repositories', 'list', PageParams]` | BE 구현됨 | 기본 staleTime |
| `['repositories', 'branches', fullName, PageParams]` | BE 구현됨 | 〃 |
| `['repositories', 'selection']` | BE 미구현 | 명세 B-FN-003 |
| `['me']` | BE 미구현 | `GET /me` 없음 |
| `['analysis', analysisId, ...]` (증거 계열) | BE 미구현 | 설계 4-1 · `staleTime: Infinity` |
| `['matching', analysisId, target, ...]` (매칭 계열) | BE 미구현 | 설계 4-1 · 기본 staleTime |
| `['admin', 'technology-candidates', limit]` | BE 구현됨 | 티켓 14 · 분석마다 늘어나므로 기본 staleTime |
| `['admin', 'registry']` | BE 구현됨 | 〃 · 승격·거절이 둘 다 무효화한다 |

증거·매칭 두 계열 분리는 설계 4-1의 확정 규약이므로 BE 미구현이어도 키 구조는 유지한다.

### 1-5. Base URL — 버전은 FE가 붙인다

`VITE_API_BASE_URL`은 **nginx의 REST 루트**이지 버전 경로가 아니다. 인프라가 주는 값은 `/api`이고, 같은 자리에 WebSocket 루트 `/ws`가 짝으로 있다.

| 출처 | 값 |
|---|---|
| `Infra/docker/frontend/Dockerfile` | `ARG VITE_API_BASE_URL=/api` (기본값이라 build arg를 넘기지 않아도 적용된다) |
| 루트 `.env.example` | `VITE_API_BASE_URL=/api` · `VITE_WS_URL=/ws` |
| `Infra/nginx/conf.d/default.conf` | `location /api/ { proxy_pass http://gitjob_backend; }` — 경로 재작성 없음 |
| BE | `@RequestMapping("/api/v1/...")` |

버전은 라우팅이 아니라 FE·BE 계약이므로 `client.ts`가 붙인다.

```ts
const API_ROOT = import.meta.env.VITE_API_BASE_URL ?? '/api'
const API_BASE_URL = `${API_ROOT.replace(/\/$/, '')}/v1`
```

이 값을 그대로 base로 쓰면 dev(변수 미설정)만 맞고 **운영 빌드는 `/api/me/...`로 나가 BE에 닿지 못한다.** 환경 변수 정의는 인프라 소유이므로 `FE/.env.example`을 따로 두지 않는다.

## 2. 명세와의 차이 — 팀 공유 필요

| 항목 | Notion 명세 (v1.0) | BE 실구현 | FE 채택 | 후속 |
|---|---|---|---|---|
| 공통 오류 접두 | `COMMON-*` | `G-400-1` `G-400-2` `G-500` | BE | Notion 갱신 또는 BE 수정 — B조 결정 |
| GitHub 연결 만료 | `AUTH-409-1` (409) | `AUTH-401-4` (401) | BE → `RECONNECT_GITHUB` | 〃 |
| 세션 만료 (refresh) | 없음 — 명세는 재발급 없음 | `AUTH-401-3` · `/api/v1/auth/refresh` 경로 존재 | `REDIRECT_TO_ONBOARDING` | refresh 엔드포인트 존치 여부 |
| 분석 불가 저장소 | 200 + `analyzable=false` + `notAnalyzableReason` | 목록은 `analyzable`만 내려주고, 분석 요청 시 `REPO-409-1` (409) | BE → `SHOW_UNANALYZABLE` | `notAnalyzableReason` 필요 여부 (117) |
| 진행 중 분석 충돌 | `REPO-409-1` → 선택 잠김 | 200 "이미 진행 중인 분석이 있습니다." | 액션 삭제 | — |
| 페이징 | `page` 0-base · `size` · `totalCount` | `page` 1-base · `perPage` · `hasNext` | BE | Notion 갱신 |
| 목록 필터 | `sort` `q` `includeForks` `includeArchived` `refresh` | 없음 (최근 갱신 순 고정) | 없음 | 117에서 필요하면 BE에 요청 |
| 응답 `meta` | `generatedAt` `fetchedAt` `cached` | 없음 | 없음 | BE 구현 시 optional 복원 |
| 저장소 항목 필드 | `repositoryId` `githubRepoId` `primaryLanguage` `sizeKb` `pushedAt` `permissions` … | `githubRepositoryId` `fullName` `name` `owner` `isPrivate` `defaultBranch` `description` `language` `updatedAt` `analyzable` | BE — 117에서 `features/analysis/api/`에 정의 | — |
| 콜백 실패 전달 | 성공·실패 모두 FE `/auth/callback`으로 302 | `AUTH-403-3`만 302, `AUTH-400-2`·`AUTH-403-4` 등은 BE 콜백 URL에서 JSON 직접 응답 | 매핑은 두되, 브라우저 이동 중이라 FE 코드가 관여하지 못함 | 실패도 302로 통일할지 BE 확인 |

## 3. 고정 enum 현황 (`FE/src/shared/types/domain.ts`)

| enum | FE 값 | BE / AI 구현 | 처리 |
|---|---|---|---|
| `EvidenceLevel` | `L0` `L1` `L2` `L3` | 없음 | 와이어프레임 1-2 유지 |
| `ContributionLabel` | `SOLE_AUTHOR` `CO_AUTHORED` `PARTIAL_EDIT` `UNVERIFIED` | 없음 | 〃 |
| `JobStatus` | `QUEUED` `RUNNING` `RATE_LIMITED` `SUCCEEDED` `FAILED` `CANCELED` | BE는 문자열 `QUEUED` `COLLECTING` `RUNNING` `ANALYZING` `RATE_LIMITED` `CANCEL_REQUESTED`를 활성 상태로 씀 (`AnalysisJob.java` — "spec에 없는 값, 통일은 별도 티켓"). 조회 API `GET /analyses/{id}` 미구현 | 유지. 미정의 값은 `lookupLabel`이 렌더하지 않고 DEV 경고만 낸다. 136(S3) 착수 전 BE와 확정 |
| `DataStatus` | `READY` `PREPARING` `PARTIAL` `NO_DATA` `INSUFFICIENT_DATA` `NOT_SUPPORTED` `FAILED` | 없음 | 명세 2-3 유지 |

## 4. 미결

1. **명세 갱신** — 2장의 차이를 Notion B조 API 명세서·프론트엔드 설계 6-3장에 반영할지, BE를 명세로 되돌릴지 (B조)
2. **잡 상태 통일** — BE 내부 상태 6종과 와이어프레임 6종의 관계. 136 착수 전 필요
3. **204 사용 여부** — FE는 204를 `CLIENT-ENVELOPE`로 처리한다. BE가 204를 쓸 계획이면 봉투 규약부터 고쳐야 한다
4. **콜백 실패 전달 방식** — 2장 마지막 행
5. **BE 코드·enum 추가 시 FE 통보 절차** — `ErrorCode.java`·상태 문자열이 늘면 이 문서와 `errorCodes.ts`·`domain.ts`를 같은 MR에서 고칠지, 별도 알림으로 갈지

## 5. 원문 출처

- [B조 API 명세서](https://app.notion.com/p/3cdae4cfead28108a0a5cf55da67a004) · [B-FN-002 저장소 목록 조회](https://app.notion.com/p/3cdae4cfead28181bdcdc5b86eda8efa)
- [프론트엔드 설계](https://app.notion.com/p/3ceae4cfead281c5bf9bf1863c5ce610) 4-1 캐시 키 · 5장 공통 컴포넌트 · 6-3 에러 코드 처리
- BE 문서 [저장소 선택과 분석 요청](../be/repository-analysis-request.md)
- BE 코드 `BE/src/main/java/com/example/git_job/` — `global/exceptions/ErrorCode.java` · `global/response/ApiResponse.java` · `global/response/ErrorResponse.java` · `global/security/JwtAuthenticationEntryPoint.java` · `analysis/controller/RepositoryController.java` · `analysis/controller/AnalysisController.java` · `analysis/controller/dto/PageResponse.java` · `analysis/domain/AnalysisJob.java`
