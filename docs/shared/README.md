# 공통 개발 컨벤션

> 상태: 팀 공통 규칙 통합본
>
> 기준일: 2026-08-28

## 1. GitLab·Jira 흐름

작업은 Jira 이슈를 기준으로 만들고, 브랜치·커밋·Merge Request에서 이슈 키를 유지한다.

| 항목 | 규칙 | 예시 |
|---|---|---|
| 이슈 라벨 | `Feat`, `Refactor`, `Test`, `Bug` | `Feat` |
| 컴포넌트 | `AI`, `Front`, `Back`, `Infra` | `Back` |
| 브랜치 | `{label}/{JIRA-KEY}-branch` | `feat/GIT-123-branch` |
| 커밋 | `<type>: <JIRA-KEY> <message>` | `feat: GIT-123 add analysis api` |
| MR 제목 | `[{JIRA KEY}] {label}: {title}` | `[GIT-123] feat: analysis status` |
| MR 라벨 | `Feature`, `BE` 등 작업 분류 | `Feature`, `BE` |

label은 브랜치에서 소문자로 사용하고, 커밋 type과 Jira key를 생략하지 않는다. MR에는 관련 Jira 이슈, 변경 요약, 테스트 결과, 환경 변수 변경 여부를 포함한다.

## 2. 저장소 구조

```text
BE/       Spring Boot API·도메인·migration
FE/       React 화면·상태·API client
AI/       Collector·Worker·RAG/AI 처리
Infra/    Compose·Dockerfile·Nginx·Jenkins·운영 스크립트
docs/     설계·운영·요구사항·검증 문서
```

파트 간 공통 계약은 코드보다 먼저 `docs/`에 기록한다. API, Kafka event, 환경 변수, DB schema를 변경하면 관련 파트 문서와 원문 출처를 함께 갱신한다.

## 3. Frontend 규칙

권장 디렉터리:

```text
src/
├── pages/        # 화면 단위
├── components/   # 공통 버튼·모달·입력·상태 표시
├── api/          # REST 요청 함수와 URL
├── websocket/    # WebSocket 연결·구독
├── types/        # 공통 DTO·상태 enum
├── store/        # 여러 화면이 공유하는 상태
└── utils/        # 포맷·공통 함수
```

- 컴포넌트·파일명은 PascalCase: `LoginPage.tsx`, `AnalysisProgressPage.tsx`
- 변수·함수명은 camelCase: `repositoryName`, `startAnalysis`
- 클릭 이벤트는 `handle` 접두사: `handleLogin`
- boolean은 `is`, `has`, `can` 접두사: `isReady`, `canStartAnalysis`
- API 주소를 화면 파일에 직접 작성하지 않는다.
- 한 화면에서만 쓰는 값은 local state, 여러 화면이 쓰는 값은 store로 관리한다.
- WebSocket 연결은 한 곳에서 관리하고 화면 이탈 시 구독을 해제한다.
- 타이머·참가자·권한은 서버 응답을 기준으로 렌더링한다.

## 4. Backend 규칙

- Controller는 인증·입력 검증·응답 변환에 집중하고 도메인 판정은 service/domain에서 수행한다.
- 외부 GitHub 응답과 내부 API DTO를 분리한다.
- 모든 REST 응답은 `{ message, data }` 또는 `{ code, message }` envelope을 사용한다.
- 서비스 오류 코드는 HTTP status와 함께 문서화한다.
- 비동기 event에는 `event_id`, `schema_version`, `trace_id`와 발생/수집 시각을 포함한다.
- Token·비밀번호·개인정보를 로그·응답·event에 기록하지 않는다.
- 분석·Registry·parser version을 결과와 함께 저장한다.
- DB migration 없이 운영 schema를 자동 변경하지 않는다.

## 5. 협업·리뷰 체크리스트

### 구현 전

- [ ] Jira 이슈·담당 파트·완료 기준이 있다.
- [ ] API/DB/event/환경 변수 변경 범위를 확인했다.
- [ ] 개인정보·외부 API quota·권한 영향을 확인했다.

### MR 작성 전

- [ ] 브랜치명·커밋명·MR 제목에 Jira key가 있다.
- [ ] 단위/통합 테스트를 실행했다.
- [ ] 실패 응답과 empty/partial 상태를 확인했다.
- [ ] 문서와 원문 Notion 링크를 갱신했다.
- [ ] secret·`.env`·PEM·Token이 diff에 없다.

### 리뷰 시

- [ ] 사용자의 리소스 소유권과 scope를 검증하는가
- [ ] 중복 event·재시도·부분 실패가 안전한가
- [ ] 데이터가 없을 때 dummy를 만들지 않는가
- [ ] 원본 코드·민감정보·근거 없는 수치가 노출되지 않는가
- [ ] 운영 로그로 traceId와 실패 원인을 추적할 수 있는가

## 6. 문서 작성 규칙

- 문서 상단에 상태와 기준일을 기록한다.
- 구현된 것, 설계된 것, 미결정인 것을 문장과 표에서 구분한다.
- 숫자·상태·API 경로는 출처 또는 관련 기능 ID를 남긴다.
- 다른 문서에서 재사용하는 용어는 [아키텍처](../architecture.md)의 정의를 우선한다.
- 현재 실행 계약에 포함하지 않는 과거 표나 회의록은 실행 문서와 분리해 보관한다.

## 7. 원문 출처

- [깃랩/지라 컨벤션 가이드](https://app.notion.com/p/e2a0dff912cf824a85340178601b1997)
- [회의록](https://app.notion.com/p/5900dff912cf82f8ade6816778a1ec77)
- [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)
