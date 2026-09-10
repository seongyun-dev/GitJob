# Backend 설계 문서

> 상태: 구현된 기반과 남은 C/FE 인수 경계
>
> 기준일: 2026-09-10
>
> 현재 `BE/`에는 Spring Boot 기반, OAuth·저장소·분석 요청·Outbox와 C 호출을 위한 코드가 있다. 구현·로컬 검증·운영 인수 구분은 [현재 상태](../2026-09-10-current-status.md)를 따른다.

## 1. Backend 책임

Backend는 다음 책임을 가진다.

- GitHub OAuth 로그인, 세션, scope와 연결 상태 관리
- 사용자가 접근할 수 있는 저장소 조회와 분석 대상 선택
- 비동기 분석 Job 생성·상태·취소·재실행·Snapshot 관리
- GitHub 분석 결과를 기술 Profile/Evidence로 조회
- 목표 직무·채용 수요·Skill Gap·학습 후보·성장 로드맵 조회
- JOB/GITHUB Trend와 근거 기반 Rule/AI 설명 제공
- 운영 지표, 데이터 품질, lineage와 사용자 데이터 삭제 제공

## 2. 기술 기준

| 영역 | 기준 |
|---|---|
| Runtime | Java 21 |
| Framework | Spring Boot |
| Persistence | Spring Data JPA + PostgreSQL |
| Session/Cache | Redis |
| Event | Kafka |
| API | REST JSON, 필요 시 WebSocket/STOMP push |
| Edge | Nginx가 `/api`와 `/ws` reverse proxy |
| 분석 연동 | Collector/Worker가 Kafka·HDFS/Parquet·Spark와 연결 |

Notion의 개발 환경은 Spring Boot/JPA/Java 21, React, PostgreSQL, Redis, Kafka, Spark/Hadoop/Python, Docker/AWS/Nginx/Jenkins를 기준으로 한다. 기존 초기 회의록의 Java 17·MySQL 표기는 이전 논의로 분류하고 최신 기준과 혼용하지 않는다.

## 3. 논리 모듈 경계

현재 패키지와 후속 기능 경계는 다음 책임을 기준으로 나눈다. 아래 이름은 논리 경계이며 실제 패키지 구조와 일대일 대응을 강제하지 않는다.

```text
com.gitjob
├── common       # 공통 응답, 오류 코드, 인증 예외, traceId
├── auth         # GitHub OAuth, session, connection, alias email
├── github       # GitHub API client, quota, repository, commit/file 수집
├── analysis     # analysis_run, 상태 전이, retry/cancel, snapshot/lineage
├── evidence     # Fact → Evidence, L0~L3, repository/personal level
├── job          # job_role, posting, demand snapshot
├── recommendation # skill gap, recommendation, learning target, roadmap
├── trend        # JOB/GITHUB source signal
└── ops           # metric, unmatched fact, quality, data deletion
```

외부 API 호출과 도메인 판정은 분리한다. GitHub client가 반환한 raw 응답을 Controller가 직접 화면 모델로 노출하지 않고, 수집·정규화·판정 단계를 거쳐 응답 DTO를 만든다.

## 4. 핵심 도메인 모델

ERD Notion 페이지는 현재 비어 있으므로 아래는 요구사항을 만족하기 위한 논리 모델이다. 테이블명·PK 타입은 구현 전에 확정한다.

| 모델 | 핵심 필드/역할 |
|---|---|
| `user` | 내부 사용자 ID, GitHub 식별자, 생성·삭제 상태 |
| `github_connection` | GitHub login, 암호화 Token, granted scope, 연결 시각 |
| `user_email_alias` | verified/noreply 자동 수집 이메일과 manual 별칭, 삭제 가능 여부 |
| `github_repository` | `github_repo_id`, owner, visibility, fork/archived, default branch, push 시각 |
| `repository_selection` | 사용자별 분석 대상 저장 상태 |
| `analysis_run` | `analysis_id`, status, requested/started/finished, parent 분석, criteria |
| `analysis_repository` | 분석별 repository, 기준 `commit_sha`, 상태·오류·수집 범위 |
| `technology_registry` | canonical `tech_id`, 이름, alias/package/tag, category, version |
| `technology_relation` | 선행·후행 기술 관계, 근거·버전 |
| `fact` / `evidence` | fact type, 파일·라인·Commit, rule, level, contribution, 제외 사유 |
| `job_role` / `user_target` | 지원 직무 마스터와 사용자 목표 직무·지역·경력 |
| `job_posting` | raw 위치, 정규화 값, source, duplicate/inclusion 상태 |
| `job_demand_snapshot` | 직무·기간·분모·registry version별 기술 건수/비율 |
| `source_fact_pack` | JOB/GITHUB 지표의 출처·단위·기간 |
| `recommendation_snapshot` | 후보·점수 분해·반대 신호·data gap·formula version |
| `learning_target` | 현재 학습 기술 1건 또는 팀 확정 정책에 따른 목록 |
| `pipeline_run` / `dataset_artifact` / `quality_result` | 수집·분석 실행, 위치·checksum·품질 결과 |

모든 분석·집계 결과는 가능하면 `analysis_id`, `registry_version`, source period를 함께 저장해 나중에 같은 결과를 재현할 수 있어야 한다.

## 5. 인증·보안

### OAuth 흐름

```text
GET /api/v1/auth/github
  → state 생성·세션 저장
  → GitHub authorize
  → GET /api/v1/auth/github/callback?code=...&state=...
  → state 검증·code 교환·사용자 upsert
  → HttpOnly SESSION 쿠키 발급
```

- 최소 scope를 명시하고 사용자가 접근 권한을 부여한 public/private 저장소 범위를 이해할 수 있게 설명한다.
- private 저장소 원문은 해당 사용자 분석에만 사용하고 공개 Trend·다른 사용자의 응답에 포함하지 않는다.
- callback에서 `state` 일치·만료 여부와 `code` 존재를 검증한다.
- Access Token은 암호화해 저장하며 response body·로그·Kafka event에 절대 넣지 않는다.
- 로그아웃은 세션 종료, GitHub 연결 해제는 Token revoke까지 수행하는 별도 동작이다.
- 저장소·분석·Evidence 조회는 현재 세션 사용자의 리소스인지 확인한다.
- `DELETE /api/v1/me`는 사용자 Token·분석·Evidence 삭제 정책과 익명화 범위를 먼저 확정한다.

### 공통 응답과 오류

성공 응답은 기본적으로 다음 envelope을 사용한다.

```json
{
  "message": "요청을 처리했습니다.",
  "data": {}
}
```

실패 응답은 HTTP status와 서비스 오류 코드를 함께 반환한다.

```json
{
  "code": "AUTH-401-1",
  "message": "로그인이 필요합니다."
}
```

모든 요청에는 서버 로그·비동기 이벤트를 연결할 `traceId`를 남기고, 외부 GitHub 오류·quota·재시도 정보는 사용자에게 필요한 수준으로만 노출한다.

## 6. 분석 Job 설계

### 요청과 상태

분석 요청은 동기 결과를 기다리지 않고 `202 Accepted`와 `analysisId`를 반환한다.

```text
QUEUED
  → COLLECTING / RUNNING
  → ANALYZING
  → COMPLETED / SUCCEEDED
  → PARTIAL / PARTIAL_SUCCEEDED

QUEUED·RUNNING·ANALYZING → CANCEL_REQUESTED → CANCELLED / CANCELED
실패 → FAILED
외부 quota 대기 → RATE_LIMITED 또는 RUNNING + retryAfterSec
```

Notion 요구사항은 `QUEUED`, `COLLECTING`, `ANALYZING`, `COMPLETED`, `PARTIAL`, `FAILED`, `CANCELLED`를 사용하고, 최신 API 명세 예시는 `QUEUED`, `RUNNING`, `RATE_LIMITED`, `SUCCEEDED`, `PARTIAL_SUCCEEDED`, `FAILED`, `CANCELED`를 사용한다. 구현 전에 하나의 enum과 화면 표시 문구로 통일한다.

### 멱등성·Snapshot

- 동일 사용자에게 동일 저장소 분석이 진행 중이면 중복 Job을 만들지 않는다.
- 새 분석은 이전 분석을 덮어쓰지 않고 `parentAnalysisId`와 원인을 보존한다.
- 코드 변경은 최신 Commit으로 새 Snapshot을 만든다.
- Registry/판정 규칙만 변경된 경우에도 재수집 없이 replay할 수 있다.
- 취소된 Job의 부분 결과를 최신 결과로 승격하지 않는다.
- retry/cancel은 같은 요청을 여러 번 받아도 상태가 깨지지 않도록 idempotency key 또는 상태 조건을 사용한다.

## 7. API 카탈로그

아래는 최신 API 명세를 기능별로 정리한 목록이다. `/api/v1`는 현재 GitJob 기준이며, 상태·우선순위는 구현 전 최종 확정한다.

### 인증·계정

| Method | URI | 기능 |
|---|---|---|
| `GET` | `/api/v1/auth/github` | GitHub OAuth 진입 |
| `GET` | `/api/v1/auth/github/callback` | OAuth callback·세션 발급 |
| `GET` | `/api/v1/me` | 내 GitHub 연결·최근 분석 조회 |
| `POST` | `/api/v1/auth/logout` | 세션 로그아웃, 추가 제안 |
| `DELETE` | `/api/v1/auth/github` | GitHub 연결 해제 |
| `GET` | `/api/v1/me/email-aliases` | 별칭 이메일 목록 |
| `POST` | `/api/v1/me/email-aliases` | manual 별칭 이메일 등록 |
| `DELETE` | `/api/v1/me/email-aliases/{aliasId}` | manual 별칭 삭제 |
| `DELETE` | `/api/v1/me` | 사용자 데이터 삭제 |

### 저장소·분석 작업

| Method | URI | 기능 |
|---|---|---|
| `GET` | `/api/v1/me/repositories` | 접근 가능한 저장소 목록·quota |
| `GET` | `/api/v1/me/repositories/selection` | 저장된 분석 대상 조회 |
| `PUT` | `/api/v1/me/repositories/selection` | 분석 대상 저장, 1~20개 |
| `POST` | `/api/v1/analyses` | 비동기 분석 요청 |
| `GET` | `/api/v1/analyses/{analysisId}` | 진행 상태·부분 결과 조회 |
| `POST` | `/api/v1/analyses/{analysisId}/retry` | 최신 Commit/Registry 기준 재실행 |
| `POST` | `/api/v1/analyses/{analysisId}/cancel` | 분석 취소 |
| `GET` | `/api/v1/analyses/{analysisId}/lineage` | 결과→dataset·event lineage 조회 |
| `GET` | `/api/v1/me/analyses` | 분석 이력 목록, 추가 제안 |
| `GET` | `/api/v1/me/analyses/compare` | 두 Snapshot 변화 비교 |

분석 요청 예시는 다음과 같다.

```json
POST /api/v1/analyses
{
  "repoFullNames": ["octocat/gitjob-api"]
}
```

```json
{
  "message": "분석을 등록했습니다.",
  "data": {
    "analysisId": "an_01J9X7",
    "status": "QUEUED",
    "pollAfterSec": 2,
    "statusUrl": "/api/v1/analyses/an_01J9X7"
  }
}
```

### 프로필·직무·추천

| Method | URI | 기능 |
|---|---|---|
| `GET` | `/api/v1/me/profile` | 기술별 Repository/Personal Profile |
| `GET` | `/api/v1/me/technologies/{techId}/evidence` | 파일·라인·Commit Evidence |
| `GET` | `/api/v1/me/target` | 목표 직무 조회 |
| `PUT` | `/api/v1/me/target` | 목표 직무 선택·변경 |
| `GET` | `/api/v1/job-demands` | 직무별 기술 수요 집계 |
| `GET` | `/api/v1/me/skill-gap` | 보유·강화·부족 Skill Gap |
| `GET` | `/api/v1/me/recommendations` | 학습 기술 후보 추천 |
| `GET` | `/api/v1/me/learning-target` | 선택 학습 기술 조회 |
| `PUT` | `/api/v1/me/learning-target` | 학습 기술 선택·변경 |
| `GET` | `/api/v1/me/roadmap` | Evidence 규칙 기반 Growth Roadmap |

### 추세·학습 지원·운영

| Method | URI | 기능 |
|---|---|---|
| `GET` | `/api/v1/technologies/{techId}/trends` | JOB/GITHUB 출처별 추세 |
| `GET` | `/api/v1/trends/compare` | 후보 기술 교차 비교, merged score 없음 |
| `GET` | `/api/v1/tech-radar` | R2/R5 계산 Tech Radar |
| `GET` | `/api/v1/me/explanations` | Fact 기반 AI/Rule 설명 |
| `GET` | `/api/v1/ops/metrics` | 운영 지표·lag·DLQ·quota |
| `GET` | `/api/v1/ops/unmatched-facts` | Registry 미매칭 Fact |

### 관리자 운영 화면

| Method | URI | 기능 |
|---|---|---|
| `GET` | `/api/v1/admin/technology-candidates` | 미등록 기술 후보 검토 |
| `GET` | `/api/v1/admin/monitoring/overview` | 서버·target 현재 상태와 자원 지표 |
| `GET` | `/api/v1/admin/monitoring/timeseries` | CPU·Memory·Network 시계열 |

`/api/v1/admin/**`는 `SecurityConfig`가 ADMIN으로 제한한다. 모니터링 두 엔드포인트는
Prometheus HTTP API를 읽어 화면 모양으로 바꾸는 thin proxy이며, 계약과 PromQL, 제공하지
않는 범위는 [Admin Monitoring API](admin-monitoring-api.md)에 있다. 후보 검토 화면은
[기술 후보 검토](technology-candidate-review.md)를 따른다.

## 8. 레벨·Evidence 규칙

현재 기준은 `level-policy/v2`다. 레벨은 숙련도나 운영 능력 점수가 아니라
기술의 직접 의존성·실제 구현·사용자 작성 근거를 구분한다.
원본은 [사용자 기술 증거 판별 정책 v2](https://app.notion.com/p/78215fc50ec7823d81e481e5ce71e50e),
C 소비 계약은 [Evidence와 보유 판정](../ai/c-recommendation.md)이다.
`S15P21E102-127` 계약 정합성 보완, 기준일 2026-09-10.

| 수준 | 예시 규칙 |
|---|---|
| `L0` 미확인 | 정책상 직접 의존성 미확인. 분석 실패를 기술 미사용으로 단정하지 않음 |
| `L1` 의존성 확인 | 파일·Commit 근거가 있는 직접 의존성 |
| `L2` 프로젝트 구현 확인 | 직접 의존성·승인된 구현 근거·저장소 참여 자격 확인 |
| `L3` 사용자 직접 구현 확인 | L2 조건과 사용자 작성 구현 라인 근거 확인 |

저장소의 기술 관측과 사용자의 참여·귀속을 별도로 보존한다. 접근 권한만으로 참여를
인정하거나 서로 다른 저장소의 근거를 합쳐 L3로 만들지 않는다. import·설정만으로
실제 구현을 확정하지 않으며 retry·DLQ·테스트 등 운영성 근거도 L3로 자동 승격하지 않는다.
레벨이 미확정이어도 독립적으로 확인된 기술 관측은 삭제하지 않는다. 추천의 보유 판정과
Evidence 레벨은 서로 다른 계약이며, 미확정 상태는 `UNKNOWN`으로 남긴다.

이전 발견/적용/활용/심화 표는 폐기된 설계다. 새 producer는 v2를 적용해야 한다.
실제 Fact 추출·규칙 평가·작성자 귀속 구현과 운영 인수는 이 문서 정리만으로 완료되지 않는다.

Evidence 응답에는 다음을 포함한다.

- `factType`, `matchedRule`, `level`
- `repoFullName`, `filePath`, `lineNo`, `commitSha`, GitHub permalink
- `scopeType`(`REPOSITORY`/`PERSONAL`/`ALL`)
- `inherited`, `excludedReason`, `unmetRules`, `nextActions`

봇·merge·fork base·generated·format-only 코드는 제외 사유를 남기며, 응답에는 원본 코드 본문을 넣지 않는다.

## 9. 현재 레포 구현과 다음 작업

현재 Backend에는 기본 보안 코드와 분석 작업·이벤트를 한 트랜잭션에 저장하는
Transactional Outbox가 구현되어 있고, 저장된 이벤트는 Debezium CDC가 Kafka로
발행한다(백엔드가 직접 발행하는 폴링 relay는 롤백 경로로만 남겨 둔다).
저장소 목록·브랜치 조회와 분석 요청 API가 그 앞단에 연결되어 있다.
!46의 Worker 결과 이벤트 소비·분석 상태 반영 코드도 포함되어 있다.
실제 Kafka 소비부터 사용자 조회·C 계산까지의 운영 인수 완료와는 구분한다.
[저장소 선택·분석 요청](repository-analysis-request.md),
[Outbox·CDC 구현·SQL 적용·복구 안내](analysis-outbox.md),
[저장소 분석 Worker](repository-analysis-worker.md),
[Admin Monitoring API](admin-monitoring-api.md)를 참고한다. `Infra/compose`와 Dockerfile은 `BE/gradlew`, Java 21,
`/actuator/health`, `bootJar`를 실행 계약으로 사용한다. 전체 Backend 구현 순서는 다음과 같다.

1. Spring Boot 기본 실행·Actuator·공통 오류 envelope 작성
2. PostgreSQL/Redis/Kafka 연결 및 migration 전략 확정
3. OAuth callback·세션·scope 보안 구현
4. 저장소 선택·분석 Job 상태 전이 구현
5. Worker 결과를 Evidence Snapshot으로 저장
6. 프로필·직무·Gap·추천 API 연결
7. 설명·운영 API와 권한·품질 검증 추가

`JPA_DDL_AUTO`는 로컬·Docker·운영 모두 `validate`다. Hibernate가 스키마를 만들거나 고치지 않는 대신 Flyway가 `db/migration`을 기동 시 적용하고, Spring Boot가 Flyway를 Hibernate보다 먼저 실행하므로 `validate`가 도는 시점에는 스키마가 이미 있다. 엔티티와 스키마가 어긋나면 기동 시점에 바로 드러난다. CDC의 롤·publication은 비밀번호 치환이 필요해 마이그레이션이 아니라 `db/cdc/cdc_prerequisites.sql`로 남아 있다.

`baseline-on-migrate`는 꺼 두었다. 켜면 Flyway가 이력 없는 기존 스키마를 확인 없이 V1으로 간주하고 넘어가는데, 그러면 실제 스키마와 마이그레이션이 어긋난 채로 조용히 통과한다. 대신 이력이 없는 비어 있지 않은 데이터베이스에서는 기동을 거부한다. 예전 방식으로 `db/init.sql`을 손으로 넣어둔 로컬 데이터베이스가 여기 해당하며, 볼륨을 지우고 다시 만들면 된다(루트 README의 `로컬 실행` 참고). 운영 데이터베이스는 비어 있었으므로 V1부터 그대로 적용된다.

전환 이후 남은 배포 절차와 후속 티켓은 `docs/be/2026-09-09-flyway-rollout-followups.md`에 있다. 임시 문서이며 항목이 모두 끝나면 삭제한다.

## 10. 미결정 사항

- 분석 상태 enum과 `CANCELLED/CANCELED`, `COMPLETED/SUCCEEDED` 표기
- `analysisId`를 ULID로 할지 BIGINT로 할지
- polling만 제공할지 SSE/WebSocket push를 병행할지
- 목표 직무 변경 시 즉시 재계산할지 조회 시 계산할지
- 추천 점수 계산 위치(R5 산출값 전달 vs Backend 계산)
- AI 설명의 사전 생성/조회 시점
- `/lineage`를 일반 사용자에게 노출할지 운영자 전용으로 둘지

## 11. 원문 출처

- [개발 환경](https://app.notion.com/p/77f0dff912cf8305a10b017245b40a78)
- [환경 변수](https://app.notion.com/p/0b60dff912cf836084ee01fb375e5cbd)
- [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d)
- [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c)
- [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)
- [데이터 베이스 모델 (ERD)](https://app.notion.com/p/bcf0dff912cf83b88784019264537765)
