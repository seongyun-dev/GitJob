# FE shared API 계약 — BE 실구현 기준

> 상태: 결정 확정 (2026-09-09, FE 담당) · 코드 반영은 `S15P21E102-170` 브랜치에서 진행
> · 1-6은 `S15P21E102-208`에서 추가 (2026-09-11, B조 API 명세서 v0.1 기준)
>
> 기준일: 2026-09-11
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

`EVD-404-2`는 BE 구현됨(`TECHNOLOGY_NOT_IN_REGISTRY`). 근거가 0건인 것은 오류가 아니라
200 + `dataStatus: INSUFFICIENT_DATA` 로 내려간다.

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
| `['me', 'technologies']` | BE 구현됨 | 기술별 판정 한 장 (지표·기술·저장소) |
| `['me', 'technologies', techId, 'evidence']` | BE 구현됨 | 근거 상세 · permalink 포함 |
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

### 1-6. Evidence 조회 계약 (BE 미구현 — 티켓 208에서 선고정)

엔드포인트가 아직 없다(명세 상태 `시작 전`). 그런데도 응답 타입을 먼저 고정하는
이유는 137·138이 화면을 붙일 때 계약을 다시 정하지 않게 하려는 것이다.

**근거는 [B조 API 명세서](https://app.notion.com/p/3d7a6b738a2880c69427df7300fa6c18)
v0.1이다.** 이 문서 머리말의 우선순위 규칙("BE에 구현된 것은 BE 코드를 따르고, 아직
없는 것만 Notion 명세를 유지한다")대로, 둘 다 BE에 없으므로 명세가 기준이다.
필드명·타입·optional 여부를 명세의 예시 응답에서 그대로 옮겼다.

| 기능 ID | 엔드포인트 | 화면 | FE 타입 |
|---|---|---|---|
| B-FN-010 | `GET /me/profile` | S6 | `TechnologyProfile` |
| B-FN-011 | `GET /me/technologies/{techId}/evidence` | S7 | `TechnologyEvidence` |

코드는 `FE/src/features/evidence/api/`에 있다. `types.ts`가 타입,
`parseEvidence.ts`가 런타임 검증, `evidenceApi.ts`가 경로·쿼리다.

쿼리 파라미터는 전부 optional이고 **기본값을 서버가 정한다**(`scopeType` 기본 `ALL`,
`includeExcluded` 기본 false). FE가 기본값을 만들어 보내면 서버 기본값이 바뀔 때 두
곳이 어긋나므로 지정하지 않은 값은 보내지 않는다.

응답 구조에서 놓치기 쉬운 것 넷.

- **레벨은 항상 두 개가 함께 온다**(`repoLevel` · `personalLevel`). 명세가 "하나만
  내려보내면 화면에서 축이 혼동된다"고 적었다. 둘을 합쳐 단일 숙련도 숫자로 만들지
  않는다.
- **`criteria`는 필수다.** 명세가 "숫자를 반환하므로 criteria 객체를 반드시 함께
  반환한다"고 못 박는다. 수치의 출처이므로 값과 함께 화면에 남아야 한다.
- **`partial`·`missingScope`**가 같은 응답에 실린다. 일부 저장소 분석이 실패한
  결과를 감추고 목록만 보여주면 사용자는 전체를 본 것으로 오해한다.
- **`unmetRules`·`nextActions`는 객체 배열이다.** 각각 `{rule, description}`,
  `{fromLevel, targetLevel, ruleId, message}`다. 문자열 배열이 아니다.

오류 코드는 각 명세의 `실패 응답 정의` 표를 `errorCodes.ts`에 반영했다.
`PRF-404-1`(종료된 분석 없음) · `PRF-409-1`(지정 분석 진행 중) · `ANL-403-1`(남의
analysisId) · `EVD-404-1`(그 기술 근거 0건) · `EVD-404-2`(Registry에 없는 techId).

**타입 선언만 두지 않고 런타임 검증을 함께 둔다.** 이 계약은 실제 응답으로 확인한 적이
없으므로 선언만 두면 어긋났을 때 `undefined`가 화면 깊은 곳까지 흘러간다.
`parseEvidence`가 `data` 안쪽을 검사하고, 어긋나면 `CLIENT-ENVELOPE`로 끊는다
(1-3의 기존 매핑을 쓰고 새 코드를 만들지 않는다). 명세의 예시 응답 두 건이 그대로
통과하는 것과, 구 필드명·문자열 배열·미정의 카테고리가 거부되는 것을 확인했다.

**항목을 버리지 않고 응답 전체를 실패시킨다.** 근거 한 줄을 조용히 떨어뜨리면
사용자는 실제보다 근거가 적다고 믿는데, 이 제품에서 그건 표시 오류가 아니라 사실
왜곡이다.

**알려진 필드만 옮겨 담는다.** 명세가 금지한 원본 코드 본문이나, 아래 2장의
`contributionScore`처럼 FE 확정 규칙과 충돌하는 값이 실려 와도 FE 상태·캐시에
들어오지 않는다.

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
| Evidence `scopeType` | 조회 필터 `REPOSITORY`/`PERSONAL`/`ALL` (B-FN-011) | Registry `evaluation_scope`는 `REPOSITORY`/`PERSONAL` 2종 (`CK_EVIDENCE_RULE_SCOPE`) | 둘 다 — 층이 다르다. 필터는 3종(`ALL` 포함), 근거 항목의 소속은 2종 | — |
| 본인 기여 표현 | `contributionScore: 0.4` (숫자) | 없음 | **미채택** — 타입에 넣지 않았다 | 아래 미결 6. FE 확정 규칙과 정면 충돌 |
| 분석 상태 | `QUEUED` `RUNNING` `RATE_LIMITED` `SUCCEEDED` `PARTIAL_SUCCEEDED` `FAILED` `CANCELED` (7종) | `AnalysisJob`의 활성 상태 6종 (집합이 또 다름) | 미정 — `domain.ts`는 아직 6종(`PARTIAL_SUCCEEDED` 없음) | 미결 2와 같은 건. 136 착수 전 3자 확정 |
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
6. **`contributionScore` 채택 여부** (208) — 명세 B-FN-011은 근거마다 `contributionScore: 0.4`라는 **비율 숫자**를 내려보낸다. 그런데 `shared/types/domain.ts`의 `ContributionLabel`은 "비율 값을 노출하지 않는다(와이어프레임 1-1 금지 규칙). **숫자를 받는 자리를 만들지 않는 것이 이 타입의 목적이다**"라고 적혀 있다. 확정 규칙 둘이 정면으로 충돌하므로 FE가 혼자 정하지 않고 필드를 받지 않았다. 셋 중 하나를 골라야 한다 — (가) 명세가 라벨(`SOLE_AUTHOR` 등)을 함께 주고 FE는 라벨만 쓴다, (나) 금지 규칙을 푼다, (다) 명세에서 뺀다. 화면 `09 Evidence Detail`의 `기여자` 열이 이 결정을 기다린다
7. **`SILENT_EMPTY` 액션의 대응 코드 소멸** (208) — 예전 명세의 `EVD-404-3`이 유일한 사용처였는데 v0.1 B-FN-011 실패 표에서 빠졌고, 그 자리를 `EVD-404-1`이 대신하면서 처리도 `SHOW_EMPTY_WITH_CTA`로 바뀌었다. 액션 자체를 지우려면 `QueryStatePanel`의 표기 표까지 함께 고쳐야 해서(137·138 소유) 타입만 남겨 두었다
8. **봉투 `meta` 복원 여부** (208) — 명세 v0.1은 `meta`에 `generatedAt`·`analysisId`·`datasetSnapshotId`·`registryVersion`을 정의한다. BE `ApiResponse`에 없어 FE는 제외한 상태인데(1-1), Evidence 응답은 `criteria` 안에 `registryVersion`을 따로 담고 있어 같은 값이 두 곳에 생길 수 있다. BE 구현 시 어느 쪽을 쓸지 정해야 한다
9. **페이징 규약 재확인** (208) — 명세 v0.1이 "목록은 `page`·`size`·`totalCount`를 사용한다"고 다시 적었다. BE 실구현은 `page`(1-base)·`perPage`·`hasNext`이고 FE는 BE를 따랐다(1-2). 아직 구현되지 않은 목록 API(`/job-postings`·`/me/analyses` 등)가 어느 쪽으로 갈지 정해야 한다

## 5. 원문 출처

- [B조 API 명세서 v0.1](https://app.notion.com/p/3d7a6b738a2880c69427df7300fa6c18) — 활성 API 37개. 1-6이 따르는 [B-FN-010 기술 프로필 조회](https://app.notion.com/p/8b9a6b738a2882949c5181d7c7a6c26b) · [B-FN-011 기술 Evidence 근거 조회](https://app.notion.com/p/f8ca6b738a2882caba2d81f58ab9c18a)
- [B조 API 명세서(이전 판)](https://app.notion.com/p/3cdae4cfead28108a0a5cf55da67a004) · [B-FN-002 저장소 목록 조회](https://app.notion.com/p/3cdae4cfead28181bdcdc5b86eda8efa)
- [프론트엔드 설계](https://app.notion.com/p/3ceae4cfead281c5bf9bf1863c5ce610) 4-1 캐시 키 · 5장 공통 컴포넌트 · 6-3 에러 코드 처리
- BE 문서 [저장소 선택과 분석 요청](../be/repository-analysis-request.md)
- BE 코드 `BE/src/main/java/com/example/git_job/` — `global/exceptions/ErrorCode.java` · `global/response/ApiResponse.java` · `global/response/ErrorResponse.java` · `global/security/JwtAuthenticationEntryPoint.java` · `analysis/controller/RepositoryController.java` · `analysis/controller/AnalysisController.java` · `analysis/controller/dto/PageResponse.java` · `analysis/domain/AnalysisJob.java`
