# FE 협의·승인 대기 항목

> 상태: FE 단독으로 정할 수 없는 것만 모은 목록. 결정 기록이 아니라 요청 목록이다.
>
> 기준일: 2026-09-13 · 기준 커밋: `develop` `daebee1`
>
> 처음 읽는 경우: [FE shared API 계약](shared-api-contract.md)

## 1. 이 문서의 기준

FE 화면 작업 중 **다른 조의 결정이나 구현이 있어야 진행되는 항목**만 적었다. FE가
혼자 고칠 수 있는 것(코드 분할, 에러 바운더리, 테스트 도입 등)은 여기 없다.

각 항목의 근거는 실제 코드에서 확인했다. 명세 문서가 아니라 `develop` `daebee1`의
소스를 기준으로 하며, 파일 경로를 함께 적어 두었으므로 확인 후 반박할 수 있다.

"미구현"이라고 적은 것은 해당 커밋에 코드가 없다는 뜻이고, 담당 조의 일정이나
계획을 판단한 것이 아니다.

## 2. B조 — 가장 많이 막혀 있다

### 2-1. 조회 API가 없어 화면이 fixture로만 도는 것

현재 FE 화면 13개가 `withDesignFixture`로만 값을 받는다. 그중 아래는 **BE 엔드포인트
자체가 없어** FE가 붙을 대상이 없다.

> 2026-09-15 갱신(`S15P21E102-279`). 아래 여덟 중 여섯이 연결됐다. 계약은
> [C 계산 결과 공개 API 계약](../be/c-compute-public-api.md)이다.

| 화면 | 경로 | 상태 |
|---|---|---|
| 직무 선택 | `/roles` | **연결됨** — `GET/PUT /api/v1/me/target` + `GET /api/v1/job-demands`. 직무 목록 API가 없어 카드 3열 대신 입력·미리보기 폼이다 |
| 공고 매칭 | `/jobs` | **연결됨** — `GET /api/v1/me/job-matches` |
| Skill Gap | `/skill-gap` | **연결됨** — `GET /api/v1/me/skill-gap` |
| 다음 기술 | `/recommendations` | **연결됨** — `GET /api/v1/me/recommendations` |
| What-if | `/what-if` | **연결됨** — `GET /api/v1/me/recommendations/{techId}/what-if` |
| 기술 상세 | `/technologies/:techId` | 여전히 fixture. 기술 단건 상세 API가 없다 |
| 트렌드 | `/trends`, `/trends/:techId` | **연결됨** — `GET /api/v1/trends/compare`, `GET /api/v1/technologies/{techId}/trends`. 월별 기간과 목표 직무를 보내면 같은 공고 조건의 JOB 출처도 조회한다 |
| 마이페이지 | `/mypage` | 여전히 fixture. 분석 이력 API가 없다 |

캐시 키는 `analysisId`를 빼고 서버가 만든 `targetKey` 기반으로 바꿨다. 요청이
`analysisId`도 `snapshotId`도 보내지 않기 때문이다 — 어느 계산 결과를 읽을지는 BE가
로그인 사용자와 저장된 목표 직무로 정한다.

**남은 요청**: 기술 단건 상세와 분석 이력 API가 MVP 범위인지. 범위에서 빠지면 FE가
두 라우트를 접는다.

### 2-2. `GET /me` 부재

앱 헤더 오른쪽 사용자 영역이 비어 있다. 확정 디자인 `Final v2`는 `마지막 분석 오늘
10:42`와 아바타를 두지만, 사용자 이름·아바타를 주는 API가 없어 아무것도 렌더하지
않는다(`FE/src/app/layouts/AppHeader.tsx`). 없는 값을 demo 문자열로 채우지 않는다.

**요청**: `GET /me` 구현 여부. 구현하지 않기로 하면 헤더 오른쪽을 영구히 비우는
것으로 디자인을 확정해야 한다.

### 2-3. 분석 상태 enum 불일치 — 확인 필요

`GET /api/v1/analyses/{analysisId}`는 **구현되어 있다**
(`BE/.../analysis/controller/AnalysisController.java`). 그런데 상태값 집합이 세 곳에서
서로 다르다.

| 출처 | 값 |
|---|---|
| BE `AnalysisJob.java` | `QUEUED` `COLLECTING` `RUNNING` `ANALYZING` `RATE_LIMITED` `CANCEL_REQUESTED` `SUCCEEDED` `FAILED` |
| FE `domain.ts` `JOB_STATUSES` | `QUEUED` `RUNNING` `RATE_LIMITED` `SUCCEEDED` `FAILED` `CANCELED` |
| B조 API 명세 v0.1 | 위 FE 6종 + `PARTIAL_SUCCEEDED` |

- FE가 모르는 BE 값 3개: `COLLECTING` `ANALYZING` `CANCEL_REQUESTED`
- BE에 없는 FE 값 1개: `CANCELED`
- 명세에만 있는 값 1개: `PARTIAL_SUCCEEDED`

FE는 미정의 값을 렌더하지 않고 DEV 경고만 낸다. 즉 **지금 분석 진행 화면을 실제 API에
연결하면 수집·분석 중 상태가 화면에서 사라진다.**

**요청**: 세 집합 중 무엇을 기준으로 할지. 분석 진행 화면(136) 착수 전에 필요하다.

### 2-4. 분석 취소 경로

FE에 `CANCELED` 종료 상태가 있고 BE에 `CANCEL_REQUESTED`가 있는데, 취소를 요청하는
엔드포인트가 컨트롤러에 없다.

**요청**: 취소가 MVP 범위인지. 범위면 엔드포인트가 필요하고, 아니면 FE에서 `CANCELED`와
취소 버튼 자리를 빼야 한다.

### 2-5. `contributionScore` — 확정 규칙 둘이 정면 충돌

명세 B-FN-011은 근거마다 `contributionScore: 0.4`라는 **비율 숫자**를 내려보낸다.
그런데 `FE/src/shared/types/domain.ts`의 `ContributionLabel`은 비율 값을 노출하지
않는 것이 타입의 목적이라고 적혀 있다(와이어프레임 1-1 금지 규칙).

FE가 혼자 정할 수 없어 필드를 받지 않았다. 셋 중 하나를 골라야 한다.

1. 명세가 라벨(`SOLE_AUTHOR` 등)을 함께 주고 FE는 라벨만 쓴다
2. 금지 규칙을 푼다
3. 명세에서 뺀다

**막고 있는 것**: `09 Evidence Detail`의 `기여자` 열. Evidence 화면을 실제 API에
연결하는 작업이 이 결정을 기다린다.

### 2-6. 페이징 규약

| 출처 | 형태 |
|---|---|
| BE 실구현 | `page`(1-base) · `perPage` · `hasNext` |
| 명세 v0.1 | `page` · `size` · `totalCount` |

FE는 BE 실구현을 따랐다. 아직 만들지 않은 목록 API(공고 목록, 분석 이력 등)가 어느
쪽으로 갈지 정해야 한다. 섞이면 FE가 목록마다 다른 파서를 갖게 된다.

### 2-7. 응답 봉투 `meta` 복원 여부

명세 v0.1은 `meta`에 `generatedAt`·`analysisId`·`datasetSnapshotId`·`registryVersion`을
정의하는데 BE `ApiResponse`에 없어 FE는 제외했다. 한편 Evidence 응답은 `criteria` 안에
`registryVersion`을 따로 담고 있어 같은 값이 두 곳에 생길 수 있다.

**요청**: 어느 쪽을 정본으로 할지.

### 2-8. 그 외 B조 확인 사항

| 항목 | 내용 |
|---|---|
| 204 사용 여부 | FE는 204를 `CLIENT-ENVELOPE` 오류로 처리한다. BE가 204를 쓸 계획이면 봉투 규약부터 고쳐야 한다 |
| `/auth/refresh` 존치 | 경로는 있는데 명세에 재발급이 없다. 쓰지 않을 거면 지우는 편이 낫다 |
| 저장소 목록 필터 | 명세의 `sort`·`q`·`includeForks`·`includeArchived`·`refresh`가 실구현에 없다(최근 갱신 순 고정). 필요하면 요청하겠다 |
| enum 추가 시 통보 | `ErrorCode.java`·상태 문자열이 늘 때 `errorCodes.ts`·`domain.ts`를 같은 MR에서 고칠지, 별도 알림으로 갈지 |
| 콜백 실패 전달 | 분석 실패 사유를 화면에 어떻게 내릴지 |

## 3. C조

FE는 C를 직접 호출하지 않는다(BE 경유). 다만 화면 표기를 정하는 정책이 C에 있다.

### 3-1. Evidence Level L0~L3 의미 확정

`FE/src/shared/constants/evidenceLevel.ts`의 `LEVEL_MEANING`이 `null`로 비어 있다.
등급 정책(S15P21E102-127)이 확정되지 않아 화면에는 `L0`~`L3` **값만** 찍는다.
"없음 / 노출 / 구현 / 운영" 같은 의미 설명을 production copy로 굳히지 않았다.

**요청**: 정책 확정 시 표기 문구. 확정되면 FE는 상수 한 곳만 채우면 된다.

### 3-2. `DataStatus` 표기 기준

FE는 `READY`·`PREPARING`·`PARTIAL`·`NO_DATA`·`INSUFFICIENT_DATA`·`NOT_SUPPORTED`·
`FAILED` 7종을 갖고 있다. 공개 분석 품질이 `INSUFFICIENT_DATA`로 나오는 경우가 실제로
있었는데(C 검증 기록 3절), 그 상태를 사용자에게 어떤 문구로 보여줄지가 정해지지 않았다.

## 4. A조

| 항목 | 내용 |
|---|---|
| S9 파이프라인 운영 화면 | A조 소유라 FE가 라우트를 만들지 않았다(`router.tsx`). 필요해지면 알려주면 만든다 |
| 랜딩 공통 셸 | 티켓 204(안성윤) 소유다. 하단바 작업(245)은 마지막 장 정렬 변경에 한정했고 Hero·소개 섹션 구성은 건드리지 않았다. 이 경계가 맞는지 확인 필요 |

## 5. 팀 전체 결정

### 5-1. 개인정보 처리방침 — 보관 기간·파기 절차

하단바에서 여는 처리방침 화면(`/privacy`)을 만들었다. 수집 항목·이용 목적·제3자
제공 없음 등은 실제 코드(`User.java`)와 `README.md`의 원칙에서 확인해 적었다.

**정해지지 않은 것**: 보관 기간과 파기 절차. 임의의 기간(`3년` 등)을 적으면 지키지
못할 약속이 되므로 9조에 "확정하지 않았습니다"라고 그대로 적었다.

**요청**: 기간·절차 확정. 확정되면 9조를 교체하고 시행일을 넣는다.

### 5-2. 처리방침의 성격

현재 상단에 "SSAFY 교육 과정에서 만든 프로젝트이며 상용 서비스가 아닙니다"를 고지로
달았다. 이 표현을 유지할지, 외부 공개 시 다른 문구가 필요한지 확인이 필요하다.

### 5-3. 팀원 역할 표기

조 편성(A/B/C)과 담당 영역은 전달받아 팀 소개 화면에 반영했다. 개인별 세부 역할
(A1/A2 같은 내부 분담)은 넣지 않았다.

**요청**: 개인별 역할을 화면에 노출할지. 노출하면 `FE/src/shared/constants/team.ts`에
필드를 추가한다.

### 5-4. 팀 소개의 "맡는 일"과 MVP 범위 차이

팀 소개 화면의 C조 "맡는 일"에 `Stack Overflow 분석`·`RAG`가 들어 있다. 그런데
[현재 상태 문서](../2026-09-10-current-status.md) 3절은 이 둘을 **현재 MVP 범위에서
제외**한다고 적고 있다.

역할 분담을 적은 것이라 그대로 두었지만, 소개 화면이 "지금 만들고 있는 것"으로
읽힐 수 있다.

**요청**: 그대로 둘지, 현재 범위만 남길지.

### 5-5. 로고 원본

`FE/src/assets/gitjob-logo.png`가 1362×420 · 318KB인데 표시 높이는 26~36px이다.
프로덕션 번들 에셋의 절반 이상을 이 파일이 차지한다. `BrandLogo.tsx`에 이미
SVG 교체 TODO가 있다.

**요청**: 디자이너에게 SVG 워드마크 요청.

### 5-6. 로그인 전용 화면의 소유 티켓

`Final v2`의 `02 SSAFY Login`에 해당하는 화면이 아직 없고 소유 티켓도 모른다
(`router.tsx` 주석). 현재는 GitHub 단독 로그인이라 랜딩 CTA가 바로 OAuth로 간다.

**요청**: 이 화면이 필요한지, 필요하면 누가 맡는지.

## 6. 협의가 아니라 문서 정정이 필요한 것

아래는 결정할 것이 아니라 **이미 구현됐는데 문서가 따라가지 못한** 경우다. FE가
[shared-api-contract.md](shared-api-contract.md)를 고치면 된다.

| 문서의 서술 | 실제 |
|---|---|
| Evidence 계열 "BE 미구현 — 명세 유지" | `GET /api/v1/me/technologies`, `GET /{techId}/evidence` 구현됨 (`d1a9497`) |
| 캐시 키 표의 `['analysis', ...]` "BE 미구현" | 위와 같음 |
| "조회 API `GET /analyses/{id}` 미구현" | 구현됨 (`AnalysisController.java`, `includeRepositories` 파라미터 있음) |

이 상태로 두면 FE가 "붙일 API가 없다"고 판단해 이미 열린 연결을 놓친다. 실제로 Evidence
화면은 훅(`useTechnologyProfile.ts`)까지 만들어 두고도 페이지가 `null`을 넘기고 있다.

## 7. 우선순위

| 순위 | 항목 | 대상 | 이유 |
|---|---|---|---|
| 1 | 2-5 `contributionScore` | B조 | Evidence 실연결의 유일한 블로커. 나머지 재료는 다 있다 |
| 2 | 2-3 분석 상태 enum | B조 | 지금 붙이면 진행 중 상태가 화면에서 사라진다 |
| 3 | 2-1 미구현 조회 API 범위 | B조 | 화면 8개의 존폐가 걸려 있다 |
| 4 | 5-1 처리방침 보관 기간 | 팀 | 공개 전에는 채워야 한다 |
| 5 | 3-1 Evidence Level 표기 | C조 | 없어도 값은 보이므로 급하지 않다 |
| 6 | 나머지 | — | 화면을 막고 있지 않다 |

1·2번이 풀리면 FE는 **제품에서 처음으로 실데이터가 뜨는 화면**을 만들 수 있다.
