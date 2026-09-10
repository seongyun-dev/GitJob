# Frontend 설계 문서

> 상태: 주요 화면 초안과 남은 API 인수 경계
>
> 기준일: 2026-09-10
>
> `S15P21E102-192`로 Vite/React 주요 화면 초안이 `develop`에 들어왔다. 화면 존재는 실계정 B/C API 연결 완료를 뜻하지 않는다.
>
> `FE/src/shared/`(봉투·페이징·오류 코드·캐시 키)의 실제 계약은 [FE shared API 계약](shared-api-contract.md)을 따른다. 관리자 운영 화면은 [Admin System Monitoring 화면](admin-monitoring-screen.md)을 따른다 — 인프라가 바뀔 때 고칠 곳(topology config)과 도메인 상태·공용 UI 상태의 구분이 거기 있다. 아래 6장·7장의 폴더 구조와 상태 목록은 2026-08-28 초안이며, 구현된 구조는 Notion 프론트엔드 설계 3장과 그 문서가 우선한다.

## 1. Frontend 책임

- GitHub 로그인부터 저장소 선택, 분석 진행, 결과 확인까지의 사용자 흐름 제공
- 기술 Profile과 Evidence를 규칙과 출처가 보이는 형태로 표현
- 목표 직무·Skill Gap·학습 추천·What-if·신규 부합 공고·Trend 화면 제공
- 분석 상태·부분 결과·외부 API 오류를 사용자에게 이해 가능한 상태로 표시
- 서버를 단일 진실 공급원으로 삼아 타이머·진행률·순위·권한 상태를 표시
- `/api` REST 요청과 `/ws` 실시간 연결을 화면 컴포넌트에서 분리

## 2. 기술 기준

| 영역 | 기준 |
|---|---|
| UI | React |
| API | `fetch` 또는 `axios` 중 하나로 통일, 선택은 팀 결정 |
| 상태 | 화면 내부는 local state, 여러 화면 공유 값은 전역 store |
| 실시간 | WebSocket/STOMP 검토; 분석 상태는 polling 우선 구현 가능 |
| 배포 | Vite 기반 `dist/`를 Nginx가 제공한다는 현재 Dockerfile 가정 |
| URL | 기본 API `/api`, WebSocket `/ws` |

GitJob의 사용자 화면은 분석 서비스 UI를 중심으로 React를 사용한다. 현재 계약에는 별도의 Canvas 기반 화면을 포함하지 않는다.

## 3. 사용자 흐름

```text
로그인
  → GitHub 권한(scope) 확인
  → 저장소 목록 조회
  → 분석 대상 선택·저장
  → 분석 요청
  → 진행 상태·부분 결과
  → 기술 Profile / Evidence
  → 목표 직무 선택
  → Skill Gap / 학습 후보
  → 학습 기술 선택
  → What-if / 신규 부합 공고 / Trend / 근거 설명
  → 이력·Snapshot 비교·설정
```

### 화면별 책임

| 화면/영역 | 핵심 내용 | 연결 API |
|---|---|---|
| GitHub 로그인 | OAuth 진입, public/private scope 설명, 권한 거부 안내 | `/api/v1/auth/github`, callback |
| 저장소 선택 | owner, visibility, fork, archived, 언어, 최근 push, quota | `/api/v1/me/repositories`, `/selection` |
| 분석 진행 | `analysisId`, 전체/완료 수, 현재 저장소, 부분 실패, 재시도·취소 | `/api/v1/analyses*` |
| 기술 Profile | 기술별 Repository/Personal Level, 근거 수, 분석 기준 | `/api/v1/me/profile` |
| Evidence 상세 | 파일 경로·라인·Commit·규칙·본인 기여·다음 행동 | `/api/v1/me/technologies/{techId}/evidence` |
| 목표 직무 | 지원 직무 master 검증, 지역·경력 선택 | `/api/v1/me/target` |
| Skill Gap | 보유/강화/부족 상태, 수요 비율·판정 근거 | `/api/v1/me/skill-gap` |
| 학습 후보 | 순위, 점수 분해, Evidence 요구, 반대 신호·data gap | `/api/v1/me/recommendations` |
| 학습 지원 | 학습 기술, What-if, 신규 부합 공고, 근거 설명 | `/learning-target`, `/recommendations`, `/matching-jobs` |
| Trend/Radar | JOB/GITHUB를 분리한 출처별 지표 | `/trends`, `/trends/compare`, `/tech-radar` |
| 이력·설정 | Snapshot 비교, 연결 해제, 데이터 삭제 | `/me/analyses/compare`, `/auth/github`, `/me` |

Notion에서 화면 번호가 문서마다 다르게 사용되므로 구현에서는 `S1` 같은 번호보다 위 화면 이름과 기능 ID를 기준으로 route와 component를 연결한다.

## 4. 화면 설계 원칙

### 4.1 Evidence를 먼저 보여준다

Profile·Gap·추천 카드에는 단순 기술명이나 점수만 두지 않는다.

- 기술명과 표준 `techId`
- Repository Level / Personal Level
- Evidence 개수와 대표 근거
- 규칙 ID(`L0-a`~`L3-e`)와 판정 설명
- 기준 `analysisId`, `registryVersion`, 분석 Commit
- 미충족 규칙(`unmetRules`)과 다음 행동(`nextActions`)

### 4.2 출처별 데이터는 섞지 않는다

채용공고 건수/비율과 GitHub 기간별 활동은 단위와 기간이 다르다. 차트의 축·범례·단위를 각각 표시하고 “종합 Trend 점수”로 합치지 않는다.

### 4.3 과장된 시각화 금지

와이어프레임 공통 규칙에 따라 다음을 렌더링하지 않는다.

- 근거 없는 매칭 퍼센트·기여 퍼센트·“학습자의 22%”
- 별, 게이지, 트로피 등 숙련도를 오해시키는 장식
- 데이터가 없는 영역의 임의 숫자·차트
- 질문 수를 기술 난이도로 번역한 문구

`dataStatus`가 `PREPARING`, `NO_DATA`, `INSUFFICIENT_DATA`이면 상태 설명·기준 시각·재시도 안내를 보여주고 가짜 성공 화면을 만들지 않는다.

## 5. 상태 관리

### 전역 상태 후보

```text
auth
├── isLoggedIn
├── githubLogin
├── grantedScopes
└── latestAnalysis

analysis
├── analysisId
├── status
├── repositoryProgress
├── partialResults
└── lastUpdatedAt

selection
├── repositories
├── selectedRepoFullNames
└── editable

target
├── jobRoleCode
├── region
└── careerLevel

learning
└── selectedTechId
```

한 데이터의 복사본을 화면별로 중복 저장하지 않는다. 서버 응답의 `updatedAt`, `registryVersion`, `analysisId`를 기준으로 캐시를 무효화한다.

### 서버 상태와 UI 상태 구분

| 종류 | 예시 | 보관 위치 |
|---|---|---|
| 서버 상태 | Profile, Evidence, demand, recommendation, 분석 진행률 | API cache/query layer |
| 세션 상태 | 로그인 사용자, scope, 세션 만료 | auth store |
| 화면 상태 | 모달 열림, 필터, 선택된 탭 | 컴포넌트 local state |
| 임시 입력 | 직무·분석 대상 form | form state |
| 실시간 연결 | WebSocket 연결·구독 ID | websocket manager |

## 6. API 연동 규칙

API 주소는 화면 파일에 직접 작성하지 않고 `FE/src/api` 같은 모듈에 둔다.

```text
src/
├── api/          # authApi, repositoryApi, analysisApi, profileApi ...
├── components/   # Button, Modal, StatusBadge, EvidenceRow ...
├── pages/        # Login, Repository, Analysis, Profile ...
├── store/        # auth, analysis, target, learning
├── websocket/    # 단일 연결·subscribe/unsubscribe
├── types/        # API DTO·공통 상태 enum
└── utils/        # 날짜·format·error mapping
```

공통 처리 규칙:

- 인증 API는 `credentials: include`와 HttpOnly `SESSION` 쿠키를 사용한다.
- 성공 envelope은 `{ message, data }`, 실패 envelope은 `{ code, message }`다.
- `401`은 세션 만료 안내 후 로그인 화면으로 이동한다.
- `403`은 scope 또는 리소스 권한 부족 문구를 표시한다.
- `409`는 진행 중 분석·삭제·변경 충돌을 현재 상태와 함께 안내한다.
- `429`는 `retryAfterSec`가 있으면 재시도 시각을 보여준다.
- `503`/`PREPARING`은 “아직 데이터가 준비되지 않음”과 “서버 장애”를 구분한다.
- 사용자가 재로그인해도 동일한 `analysisId`의 상태를 다시 조회할 수 있어야 한다.

## 7. 분석 진행 표시

분석 응답은 전체 Job과 저장소별 세부 상태를 포함한다.

```text
QUEUED
  → RUNNING/COLLECTING
  → ANALYZING
  → SUCCEEDED/COMPLETED
  → PARTIAL_SUCCEEDED/PARTIAL

사용자 취소
  → CANCEL_REQUESTED
  → CANCELED/CANCELLED
```

Frontend는 서버가 보내는 상태와 `completedCount/totalCount/currentRepository/lastUpdatedAt`를 사용한다. 브라우저의 경과 시간을 기반으로 진행률을 임의 계산하지 않는다.

현재 API 명세에는 polling과 SSE/WebSocket push 중 선택이 미결이다. MVP는 `pollAfterSec`를 이용한 polling을 기본으로 구현하고, 분석 진행 push가 확정되면 같은 상태 store에 event를 주입한다.

## 8. WebSocket/STOMP 규칙

현재 GitJob 분석 API의 실시간 방식은 최종 확정 전이다. 도입한다면 다음 원칙을 지킨다.

- 앱 생명주기에서 WebSocket 연결은 한 번만 만든다.
- 화면마다 새 연결을 만들지 않고, 화면 진입 시 구독하고 이탈 시 해제한다.
- 서버의 분석 상태·알림만 신뢰하고 클라이언트에서 상태를 역산하지 않는다.
- 재연결 시 `analysisId`를 기준으로 REST snapshot을 먼저 동기화한 뒤 구독한다.
- 중복 event는 `eventId` 또는 `version`으로 제거한다.
- STOMP destination과 event envelope은 BE/AI와 별도 계약으로 확정한다.

분석 상태 채널의 WebSocket/STOMP 계약은 분석 진행·부분 결과·재연결에만 사용하며 다른 도메인의 채널과 혼용하지 않는다.

## 9. 접근성·오류·보안 UX

- OAuth 권한을 왜 요청하는지 public/private 저장소 차이를 설명한다.
- 저장소 목록은 keyboard로 선택할 수 있고 선택 개수·상한을 즉시 표시한다.
- 분석 취소·GitHub 연결 해제·데이터 삭제는 확인 모달을 거친다.
- Evidence permalink는 새 탭으로 열고, 원본 코드 전체를 서비스 화면에 복사하지 않는다.
- Token·비밀번호·민감한 환경 변수는 화면·client log에 출력하지 않는다.
- 로딩, 빈 결과, 부분 성공, 실패, 권한 부족을 서로 다른 상태로 표현한다.

## 10. 현재 레포와 다음 작업

현재 `FE/`에는 React Router·React Query 기반 앱, 공통 API/상태 UI와 저장소 선택·분석 진행·Evidence·추천·Trend 등 주요 화면 초안이 있다. `package-lock.json`, `npm run lint`, `npm run typecheck`, `npm run build`가 검증 진입점이다. 화면의 정적/fixture 표현과 실제 B/C API 응답 연결은 구분한다.

구현 순서:

1. `auth`와 GitHub OAuth callback 후 `/me` 분기 연결
2. 저장소 목록·선택·분석 요청/상태를 실제 B API와 연결
3. C Snapshot을 B 인증 조회 API를 통해 Profile/Evidence·추천·Trend 화면에 연결
4. polling·재전달·부분 실패·사용자 격리·접근성 E2E 테스트 추가
5. 이력·Snapshot 비교·설정 화면과 API 연결

## 11. 원문 출처

- [와이어프레임](https://app.notion.com/p/4590dff912cf8278b234819b7b0bd5d5)
- [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c)
- [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)
- [주요 기능](https://app.notion.com/p/1fa0dff912cf8349a0c70160b65eb3c2)
- [회의록](https://app.notion.com/p/5900dff912cf82f8ade6816778a1ec77)
