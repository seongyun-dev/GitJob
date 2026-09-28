# GitHub 저장소 분석 파이프라인 — 구현 정리

> 기준일: 2026-09-11 · 브랜치 `feat/S15P21E102-121-be-github-analyze-repo`
>
> 이 문서 하나만 읽어도 "저장소를 분석해서 기술 숙련도를 뽑는다"가 실제로
> 어떻게 돌아가는지 알 수 있게 쓴 것이다. 배경 지식은 없다고 가정한다.

---

## 목차

1. [한 장 요약](#1-한-장-요약)
2. [무엇을 푸는 문제인가](#2-무엇을-푸는-문제인가)
3. [전체 흐름](#3-전체-흐름)
4. [DB 설계](#4-db-설계)
5. [① 요청 접수와 Outbox](#5--요청-접수와-outbox)
6. [② CDC — Outbox를 Kafka로](#6--cdc--outbox를-kafka로)
7. [③ Worker — 요청을 잡는다](#7--worker--요청을-잡는다)
8. [④ 클론](#8--클론)
9. [⑤ 파싱 — tree-sitter](#9--파싱--tree-sitter)
10. [⑥ 매니페스트 스캔](#10--매니페스트-스캔)
11. [⑦ 판정 — 매핑과 규칙](#11--판정--매핑과-규칙)
12. [⑧ 결과 발행](#12--결과-발행)
13. [⑨ BE가 결과를 받는다](#13--be가-결과를-받는다)
14. [⑩ 기술 후보와 관리자 화면](#14--기술-후보와-관리자-화면)
15. [⑪ 결과를 화면으로 — 조회 API](#15--결과를-화면으로--조회-api)
16. [토큰 암호화](#16-토큰-암호화)
17. [실측 결과](#17-실측-결과)
18. [테스트](#18-테스트)
19. [실행 방법](#19-실행-방법)
20. [⑫ 개인 판정 — 누가 이 근거를 썼는가](#20--개인-판정--누가-이-근거를-썼는가)
21. [아직 안 한 것](#21-아직-안-한-것)

---

## 1. 한 장 요약

```
사용자가 저장소를 고름
        │
        ▼
   [BE] analysis_job + analysis_outbox 한 트랜잭션                       ①
        │
        ▼
   [Debezium] outbox 테이블의 INSERT를 읽어 Kafka로                       ②
        │  gitjob.repository-analysis.requests.v1
        ▼
   [Worker] 요청 선점 (fencing token)                                    ③
        ├─ git clone (기여 판정을 켜면 full)                             ④
        ├─ tree-sitter 파싱 → import / API 호출                          ⑤
        ├─ 매니페스트 스캔 → 선언된 의존성                                ⑥
        └─ 판정: 사실 → 기술 → L0~L3                                     ⑦
        │
        ▼
   [Worker] 결과 발행                                                    ⑧
        │  gitjob.repository-analysis.results.v1
        ▼
   [BE] analysis_job SUCCEEDED + analysis_evidence + 기술 후보 적재        ⑨
        │
        ▼
   [관리자 화면] 후보 검토 → 레지스트리 초안 → 발행                        ⑩
        │
        ▼
   [조회 API] 쌓인 근거를 화면이 읽어 간다                                 ⑪
        GET /me/technologies · /me/technologies/{techId}/evidence
        │
        ▼
   [개인 판정] 본인이 쓴 근거만으로 같은 규칙을 다시 판정                    ⑫
        blame → 커밋 → GitHub 계정 → 절 커버리지
```

핵심 설계 결정 세 가지만 먼저 말하면:

| 결정 | 왜 |
|---|---|
| **판정은 Worker가 한다** | 규칙 평가에 필요한 건 파싱 결과 전체(파일 수만 개)다. BE로 넘기면 그걸 다 보내야 한다. |
| **규칙은 DB에 있다** | JSON 파일이면 배포해야 바뀐다. DB면 관리자 화면에서 바꾼다. |
| **레지스트리 버전은 불변이다** | 분석 결과가 "어떤 규칙으로 판정됐는지"를 들고 있어야 반년 뒤에 되짚을 수 있다. |

---

## 2. 무엇을 푸는 문제인가

GitHub 저장소를 보고 **"이 사람은 Spring Boot를 어느 정도 쓰는가"**를 말해야
한다. 이력서에 "Spring Boot 능숙"이라고 적힌 것과, 저장소에 실제로 남은
흔적은 다르다.

그래서 숙련도를 네 단계로 나눈다.

| 단계 | 뜻 | 근거 |
|---|---|---|
| **L0** | 선언했다 | `build.gradle`에 의존성이 적혀 있다 |
| **L1** | 코드에서 불러온다 | `import org.springframework.boot...` |
| **L2** | 실제로 다룬다 | 그 라이브러리의 API를 호출한다 |
| **L3** | 운영 수준으로 쓴다 | 설정·튜닝·고급 기능 (아직 2개 기술만) |

**L0과 L1의 차이가 중요하다.** Spring Boot 프로젝트를 만들면 `spring-boot`가
자동으로 의존성에 들어간다. 하지만 코드에서 한 번도 import 하지 않았다면
그건 "쓴다"고 말하기 어렵다. 반대로 `import`가 있으면 최소한 코드가 그것을
안다는 뜻이다.

**L2는 한 단계 더 간다.** import만 있고 호출이 없으면 "설정 파일에 한 줄
넣었다"일 수 있다. `optimizer.zero_grad()`, `loss.backward()`를 호출했다면
PyTorch로 학습 루프를 돌려 본 것이다.

---

## 3. 전체 흐름

컴포넌트는 넷이다.

| 컴포넌트 | 언어 | 하는 일 |
|---|---|---|
| **BE** | Java 21 · Spring Boot | 요청 접수, 결과 저장, 관리자 API |
| **Worker** | Python | 클론·파싱·판정 |
| **Kafka + Debezium** | — | 둘 사이의 비동기 연결 |
| **PostgreSQL** | — | 모든 상태의 원본 |

**왜 비동기인가.** 저장소 클론과 파싱은 수 초에서 수 분 걸린다. HTTP 요청이
그동안 열려 있으면 타임아웃도 나고, 서버 재시작 한 번에 진행 중인 분석이
전부 사라진다. 요청을 DB에 적어 두고 워커가 가져가면 둘 다 해결된다.

---

## 4. DB 설계

### 4-1. 테이블 지도

```
── 분석 실행 ──────────────────────────────────────
analysis_job                 분석 한 건의 상태
analysis_outbox              보낼 이벤트 (CDC가 읽어간다)
analysis_evidence            판정의 근거 한 줄 한 줄
cdc_heartbeat                CDC 슬롯이 안 밀리게 하는 더미 쓰기

── 기술 레지스트리 ─────────────────────────────────
technology_registry          버전 카탈로그 (DRAFT / CURRENT / RETIRED)
  └ technology               그 버전이 아는 기술
      ├ technology_category  직무 도메인 (BACKEND, AI_DATA ...)
      ├ technology_mapping   "무슨 기술인가"
      └ evidence_rule        "어느 수준인가"
          └ evidence_rule_clause          절
              └ evidence_rule_predicate           술어
                  └ evidence_rule_predicate_value       기대값

── 기술 후보 ──────────────────────────────────────
technology_candidate             레지스트리에 없던 의존성
technology_candidate_observation 그걸 누가 어디서 봤는지

── 기여 ───────────────────────────────────────────
analysis_evidence_commit     근거 한 줄을 누가 썼는지 (V14 이후 채워진다)
repository_commit            커밋 → GitHub 계정 캐시

── 사용자 ─────────────────────────────────────────
user                         GitHub 로그인 + role (USER / ADMIN)
                             access_token_enc — AES-GCM 암호문 (V12)
```

마이그레이션은 Flyway `V1` ~ `V14`이고 `ddl-auto=validate`다. 스키마는
마이그레이션 파일만이 바꾼다.

| 버전 | 내용 |
|---|---|
| V1 | 베이스라인 스키마 |
| V2 | CDC 하트비트 |
| V3 | 초기 레지스트리 시드 |
| V4 | 레지스트리 버전 관리 + 무결성 제약 |
| V5 | 레지스트리 라이프사이클 (DRAFT/CURRENT/RETIRED) |
| V6 | 규칙이 해석된 기술(TECH_ID)을 참조하도록 변경 |
| V7 | `registry-20260910.1` — 기술 29개 |
| V8 | 기술 후보 + 관찰 테이블 |
| V9 | `registry-20260910.2` — L2 규칙 23개 추가 |
| V10 | `user.role` 컬럼 |
| V11 | 레지스트리 스냅샷 메타데이터 (C조) |
| V12 | GitHub Access Token 암호화 (`access_token_enc`) |
| V13 | `analysis_job.repository_full_name` |
| V14 | 근거 작성자 (`analysis_evidence.commit_sha` + 멱등 제약) |

### 4-2. 레지스트리 버전이 기본키에 들어간 이유

`technology`, `technology_mapping`, `evidence_rule` … 내용 테이블은 전부
기본키에 `registry_version`이 들어 있다.

```sql
PRIMARY KEY (tech_id, registry_version)
```

이렇게 하면 **발행된 버전은 물리적으로 수정할 수 없다.** 새 버전을 만들어
통째로 복사하는 것 말고는 방법이 없다.

왜 그렇게까지 하냐면, `analysis_evidence`의 각 행이 `registry_version`을
들고 있기 때문이다.

```
analysis_evidence
  rule_id           = "spring-boot.l1.java-import"
  registry_version  = "registry-20260910.2"
```

반년 뒤에 "이 근거는 어떤 규칙이 만들었나"를 물으면 그 버전의 규칙을 그대로
꺼내 볼 수 있다. 규칙을 제자리에서 고칠 수 있게 두면, 이미 만들어진 근거의
설명이 소리 없이 달라진다.

### 4-3. `technology_registry` 상태

```
DRAFT ──publish()──▶ CURRENT ──다음 publish()──▶ RETIRED
```

**CURRENT는 항상 정확히 하나다.** 부분 유니크 인덱스가 강제한다.

```sql
CREATE UNIQUE INDEX ... ON technology_registry (status) WHERE status = 'CURRENT';
```

둘이면 요청마다 다른 규칙으로 판정되고, 그 차이는 결과를 나란히 비교하기
전까지 드러나지 않는다.

현재 상태:

```
registry-20260908.1   RETIRED
registry-20260910.1   RETIRED
registry-20260910.2   CURRENT   ← 기술 29 · 매핑 117 · 규칙 83
```

---

## 5. ① 요청 접수와 Outbox

사용자가 저장소를 고르면 BE가 **한 트랜잭션**에서 두 행을 쓴다.

```sql
INSERT INTO analysis_job   (analysis_id, user_id, repository_id, branch_name,
                            commit_sha, status, current_stage, requested_at)
       VALUES (..., 'QUEUED', 'QUEUED', now());

INSERT INTO analysis_outbox (event_id, analysis_id, analysis_repository_id,
                             topic, event_json, status, created_at, next_attempt_at)
       VALUES (..., 'gitjob.repository-analysis.requests.v1', '{...}', 'PENDING', ...);
```

### 왜 Outbox 패턴인가

"DB에 저장하고 Kafka로 보낸다"를 그냥 하면 둘 중 하나만 성공하는 순간이 생긴다.

```
DB 커밋 성공 → Kafka 발행 실패    분석이 영영 시작 안 됨
Kafka 발행 성공 → DB 커밋 실패    없는 분석의 결과가 돌아옴
```

Outbox는 **보낼 메시지를 같은 DB에 같은 트랜잭션으로 적는다.** 커밋되면 둘 다
있고, 롤백되면 둘 다 없다. 실제 발행은 별도 프로세스(CDC)가 그 테이블을 보고
한다.

### `analysis_job` 상태

```
QUEUED ──▶ RUNNING ──▶ SUCCEEDED
                   └─▶ FAILED
```

`current_stage`는 그 안에서 더 잘게 나뉜다 (CLONING, PARSING, JUDGING …).

---

## 6. ② CDC — Outbox를 Kafka로

Debezium이 PostgreSQL의 **논리 복제 슬롯**을 읽는다. 폴링이 아니라 WAL(쓰기
로그)을 직접 구독하는 방식이라, INSERT가 커밋되는 즉시 흘러나온다.

```json
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "plugin.name":     "pgoutput",
  "slot.name":       "gitjob_analysis_outbox",
  "table.include.list": "public.analysis_outbox",

  "transforms":      "outbox",
  "transforms.outbox.type": "io.debezium.transforms.outbox.EventRouter",
  "transforms.outbox.table.field.event.id":      "event_id",
  "transforms.outbox.table.field.event.key":     "analysis_repository_id",
  "transforms.outbox.table.field.event.payload": "event_json",
  "transforms.outbox.route.by.field":            "topic"
}
```

**EventRouter**가 하는 일이 핵심이다. Debezium이 기본으로 내보내는 건
"analysis_outbox 테이블에 이런 행이 생겼다"는 변경 이벤트인데, 그걸 벗겨서
`event_json` 안에 든 실제 이벤트만 남기고, `topic` 컬럼 값을 보고 어느 토픽으로
보낼지 정한다.

메시지 키를 `analysis_repository_id`로 잡은 것도 의도가 있다. 같은 저장소의
이벤트는 같은 파티션에 가므로 **순서가 보장된다.**

### 하트비트가 왜 필요한가

복제 슬롯은 "여기까지 읽었다"를 표시해 두고, 그 지점 이후의 WAL을 서버가
지우지 못하게 붙잡는다. `analysis_outbox`에 아무 변화가 없으면 슬롯이
움직이지 않고, 그동안 **다른 테이블의** WAL까지 쌓여서 디스크가 찬다.
`cdc_heartbeat`에 주기적으로 쓰는 이유가 이것이다.

### Outbox 행은 PENDING으로 남는다

CDC 모드에서는 발행 주체가 Debezium이므로 아무도 `status`를 `PUBLISHED`로
바꾸지 않는다. 지금 6행이 전부 PENDING이고, 그게 정상이다. 다만 이 테이블이
무한히 커지므로 **보존 정책이 필요하다** (아직 없음, [18장](#18-아직-안-한-것)).

---

## 7. ③ Worker — 요청을 잡는다

워커는 Kafka에서 요청을 받고, 처리하기 전에 **DB에서 선점**한다.

### 왜 Kafka 컨슈머 그룹만으로는 부족한가

Kafka는 같은 파티션을 한 컨슈머에게만 준다. 그런데 컨슈머가 GC로 멈췄다가
브로커에게 죽은 것으로 판정되고, 파티션이 다른 워커에게 넘어간 뒤에 다시
깨어나면 — **두 워커가 같은 요청을 처리하고 있다.** 늦게 깨어난 쪽이 나중에
결과를 쓰면 최신 결과를 덮어쓴다.

### 펜싱 토큰 (fencing token)

`analysis_outbox` 행을 조건부로 UPDATE 해서 선점하고, 성공한 쪽만 **번호**를
받는다.

```python
Claim(status="ACQUIRED", token=1)   # 이 워커가 임자
Claim(status="TAKEN")               # 다른 워커가 이미 잡음
Claim(status="DONE")                # 이미 끝난 요청
```

결과를 쓸 때 토큰을 함께 검사한다. 좀비 워커의 토큰은 이미 낡았으므로
`finish()`가 0행을 갱신하고, 워커는 "내 자리가 아니었다"를 알고 조용히
물러난다.

### 재시도 예산

일시적 실패(네트워크, GitHub 순단)는 토큰 번호를 예산으로 쓴다. **5회**까지
재시도하고, 넘으면 FAILED로 확정하고 DLQ로 보낸다.

```python
except TransientCloneError as transient:
    if token >= self.max_attempts:          # 5
        self.claims.finish(event_id, token, "FAILED", transient.code)
        self._to_dlq(message, transient.code)
        return
    self.claims.release(event_id, transient.code)
    raise                                    # 오프셋 커밋 안 함 → 재배달
```

### 순서가 중요하다

```
판정 → 결과 발행 → claim.finish → Kafka 오프셋 커밋
```

발행보다 finish가 먼저면, 발행 직전에 죽었을 때 "끝났다고 표시됐는데 결과는
없는" 상태가 된다. 오프셋 커밋이 마지막인 이유도 같다 — 커밋 전에 죽으면
재배달되고, 결과 이벤트는 멱등하므로 두 번 와도 안전하다.

---

## 8. ④ 클론

```bash
git fetch --depth 1 origin <sha>        # 기본
git fetch origin <sha>                  # ANALYSIS_ATTRIBUTE_AUTHORS=true
```

- **`--depth 1`** — 기본값. 판정은 현재 코드로만 하므로 히스토리가 필요 없다.
- **기여 판정을 켜면 히스토리를 받는다.** `git blame` 에 필요하다. 얕은 체크아웃에서
  blame 은 실패하지 않고 모든 줄을 tip 커밋에 돌리므로, 이 둘은 한 스위치로 묶여
  있다 ([20장](#20--개인-판정--누가-이-근거를-썼는가)).
- **크기 상한 2GB** — 넘으면 `REPOSITORY_TOO_LARGE`로 명시적 실패.
- **임시 디렉터리** — 처리가 끝나면 지운다. 저장소를 보관하지 않는다.

실패는 코드로 구분한다.

```
REPOSITORY_NOT_FOUND    REPOSITORY_NOT_ACCESSIBLE   REPOSITORY_TOO_LARGE
CLONE_TIMEOUT           CLONE_FAILED                GIT_NOT_AVAILABLE
```

일시적인 것(타임아웃, 순단)과 확정적인 것(없는 저장소)을 나누는 게 목적이다.
확정적인 실패를 5번 재시도하는 것은 낭비다.

---

## 9. ⑤ 파싱 — tree-sitter

### tree-sitter가 뭔가

정규식으로 `import`를 찾으면 주석 안의 import, 문자열 안의 import까지 잡힌다.
tree-sitter는 **진짜 파서**라 코드의 구문 트리를 만든다. 언어별 문법이
플러그인으로 있고, 트리에서 원하는 노드를 **쿼리**로 뽑는다.

### 지원 언어 6종

`python` · `java` · `javascript` · `typescript` · `tsx` · `csharp`

각 언어마다 두 가지 쿼리를 쓴다.

**import 쿼리** — 무엇을 불러왔는가

```scheme
; Java
(import_declaration (scoped_identifier) @module)
```

**call 쿼리** — 무엇을 호출했는가 (L2 판정용)

```scheme
; Python
(call function: (attribute
    object:    (_) @receiver
    attribute: (identifier) @method))
```

`optimizer.zero_grad()`에서 `receiver=optimizer`, `method=zero_grad`를 뽑는다.

### 제외 규칙

```python
EXCLUDED_DIRECTORIES = { node_modules, .git, venv, build, dist, target, ... }
EXCLUDED_SUFFIXES    = ( .min.js, .min.ts, .bundle.js, .d.ts )
max_files  = 50,000
max_calls  = 200,000
```

`node_modules`를 세면 "이 사람은 lodash 전문가"가 된다. 남의 코드는 근거가
아니다.

---

## 10. ⑥ 매니페스트 스캔

의존성 **선언**은 코드가 아니라 설정 파일에 있다.

| 생태계 | 읽는 파일 |
|---|---|
| npm | `package.json` |
| Maven/Gradle | `pom.xml`, `build.gradle`, `build.gradle.kts`, `libs.versions.toml` |
| PyPI | `requirements*.txt`, `pyproject.toml` |
| NuGet | `*.csproj` |

**빌드를 실행하지 않는다.** `gradle dependencies`를 돌리면 정확하지만, 남의
저장소의 빌드 스크립트를 실행하는 것은 임의 코드 실행이다. 파일을 읽어서
파싱만 한다.

`scope`도 함께 남긴다 (`MAIN` / `TEST` / `DEV`). 나중에 "프로덕션에서 쓴다"와
"테스트에서만 쓴다"를 구분하기 위해서다.

---

## 11. ⑦ 판정 — 매핑과 규칙

여기가 이 시스템의 심장이다.

### 두 단계로 나눈 이유

```
사실(fact) ──① 매핑──▶ tech_id ──② 규칙──▶ L0 / L1 / L2 / L3
```

| 단계 | 답하는 질문 | 테이블 |
|---|---|---|
| **매핑** | 이게 **무슨** 기술인가 | `technology_mapping` |
| **규칙** | **어느 수준**으로 쓰는가 | `evidence_rule` |

한 단계로 합치면, 기술 하나를 추가할 때마다 L0·L1·L2 규칙 세 벌에 좌표를
전부 적어야 한다. 나누면 좌표는 매핑에 한 번만 적고, 규칙은 `tech_id`만
가리킨다.

### ① 매핑 — 사실을 기술로

사실은 세 종류다.

| fact_type | 어디서 | 예 |
|---|---|---|
| `DEPENDENCY` | 매니페스트 | `org.springframework.boot:spring-boot-starter` |
| `IMPORT` | 소스 코드 | `org.springframework.boot.SpringApplication` |
| `API_CALL` | 소스 코드 | `optimizer.zero_grad()` |

매핑은 이 문자열을 `tech_id`로 바꾼다. 현재 CURRENT 버전의 매핑 117개 구성:

```
IMPORT_PATH / PREFIX  =  51    import 경로의 접두사
PACKAGE     / EXACT   =  56    패키지 좌표 정확 일치
PACKAGE     / PREFIX  =  10    패키지 좌표 접두사
```

**PREFIX 경계가 생태계마다 다르다.** 이게 함정이다.

| 생태계 | 경계 문자 | 예 |
|---|---|---|
| Maven | `.` `:` `-` | `org.springframework.boot` → `org.springframework.boot:spring-boot-starter-web` ✓ |
| NuGet | `.` | |
| npm | `/` | `@nestjs` → `@nestjs/core` ✓ |
| PyPI | 없음 | 접두 매칭 자체를 안 쓴다 |

경계를 안 보면 `org.spring`이 `org.springframework`에 걸린다. PyPI는 패키지
이름에 계층 구조가 없어서 `re`가 `requests`에 걸리는 식이라 아예 금지했다.

### ② 규칙 — 기술을 수준으로

규칙은 네 단계 트리다.

```
evidence_rule                      규칙 하나 = 기술 하나의 한 수준
  └ evidence_rule_clause           절 — "이 조건이 만족돼야 한다"
      └ evidence_rule_predicate    술어 — "이 필드를 이 방식으로 비교한다"
          └ ..._predicate_value    기대값 — 여러 개면 OR
```

**PyTorch L2 규칙**을 실제 DB에서 꺼내 보면:

```
rule_id                       type  group  clause          fact_type   field   op     expected
pytorch.l0.dependency         L0      1    resolved-tech   DEPENDENCY  TECH_ID EXACT  pytorch
pytorch.l1.import             L1      1    resolved-tech   IMPORT      TECH_ID EXACT  pytorch
pytorch.l2.training-loop      L2      1    api-call        API_CALL    METHOD  EXACT  backward
pytorch.l2.training-loop      L2      1    api-call        API_CALL    METHOD  EXACT  zero_grad
pytorch.l2.training-loop      L2      1    api-call        API_CALL    METHOD  EXACT  no_grad
pytorch.l2.training-loop      L2      1    api-call        API_CALL    METHOD  EXACT  state_dict
pytorch.l2.training-loop      L2      1    api-call        API_CALL    METHOD  EXACT  load_state_dict
pytorch.l2.training-loop      L2      1    import-present  IMPORT      TECH_ID EXACT  pytorch
```

읽는 법:

- `group_no`가 같은 절들은 **AND**다.
- 한 절 안의 기대값 여러 개는 **OR**다.
- 즉 이 L2 규칙은 **"(위 5개 메서드 중 하나 호출) AND (pytorch import 있음)"**.

### L2에 절이 두 개여야 하는 이유 — 실제로 겪은 버그

처음에는 메서드 이름만 봤다. 그랬더니:

```
turtle.py      backward()   → PyTorch L2 ✗   (거북이 그래픽 라이브러리)
statistics.py  groupby()    → pandas L2  ✗   (itertools.groupby)
```

메서드 이름은 흔하다. `import`가 함께 있어야 그 라이브러리를 쓴 것이다.
두 절을 같은 그룹에 넣어 AND로 묶자 두 오탐이 모두 사라졌다.

### 규칙 어휘

DB에 실제로 쓰이는 값 전부:

```
fact_type       DEPENDENCY · IMPORT · API_CALL
fact_field      TECH_ID · MODULE · METHOD · CALL
match_operator  EXACT · PREFIX
role            REQUIRED
```

### 현재 규칙 구성 (registry-20260910.2)

```
L0 = 29    L1 = 29    L2 = 23    L3 = 2        합계 83
```

L0·L1은 기술 29개 전부에 있다. L2는 23개, L3는 아직 2개뿐이다.

### 잘못된 버전은 조용한 실패다

규칙을 없는 버전으로 조회하면 0행이 나오고, 결과는 **"이 저장소는 아무 기술도
안 쓴다"**와 똑같이 생긴다. 그래서 워커는 요청받은 버전이 없으면
`REGISTRY_VERSION_UNKNOWN`으로 **명시적으로 실패한다.** 조용히 빈 결과를
내지 않는다.

---

## 12. ⑧ 결과 발행

워커가 Kafka로 결과 이벤트를 보낸다.

```json
{
  "event_id":       "res_ev_request_1",
  "schema_version": "repository-analysis-result/v1",
  "event_type":     "repository.analysis.completed",
  "occurred_at":    "2026-09-10T01:02:03Z",
  "trace_id":       "tr_1",
  "payload": {
    "analysis_id":      "an_p111558",
    "status":           "COMPLETED",
    "registry_version": "registry-20260910.2",
    "technologies":     [ { "tech_id": "spring-boot", "level": "L2" }, ... ],
    "evidence":         [ ... ],
    "candidates":       [ ... ],
    "stats":            { ... }
  }
}
```

`evidence[]` 한 건은 `analysis_evidence` 컬럼과 거의 1:1이다.

```json
{
  "rule_id":     "spring-boot.l1.java-import",
  "fact_type":   "IMPORT",
  "file_path":   "src/main/java/App.java",
  "start_line":  3,
  "end_line":    3,
  "fact_payload": { "MODULE": "org.springframework.boot.SpringApplication",
                    "LANGUAGE": "java" },
  "code_snippet": null
}
```

### 계약 규칙 두 가지

**실패는 findings를 싣지 못한다.** `FAILED`인데 `technologies`나 `evidence`가
차 있으면 계약 위반이다. 그대로 두면 BE가 실패한 분석의 근거 행을 쓰게 된다.
양쪽 모델이 모두 거절한다.

**매칭 0건은 성공이다.** 기술을 하나도 안 쓰는 저장소는 정상적으로
`COMPLETED` + 빈 배열이다.

### 멱등성

결과 이벤트 ID는 요청 이벤트 ID에서 결정론적으로 만든다.

```python
def result_event_id(request_event_id: str) -> str:
    candidate = f"res_{request_event_id}"
    if len(candidate) <= 80:
        return candidate
    return "res_" + sha256(request_event_id.encode()).hexdigest()[:40]
```

같은 요청을 두 번 처리해도 결과 ID가 같다. BE는 이미 SUCCEEDED인 분석의
결과를 다시 받으면 무시한다.

---

## 13. ⑨ BE가 결과를 받는다

Kafka 컨슈머(`gitjob-analysis-results` 그룹)가 결과를 받아서 한 트랜잭션에 쓴다.

1. `analysis_job` → `SUCCEEDED` / `FAILED`
2. `analysis_evidence` 일괄 INSERT
3. `technology_candidate` 갱신

수동 커밋이고 at-least-once다. 같은 결과가 두 번 와도 1번에서 걸러진다.

---

## 14. ⑩ 기술 후보와 관리자 화면

### 후보가 왜 생기나

워커가 매니페스트에서 본 의존성 중 **레지스트리에 없는 것**을 후보로 남긴다.
레지스트리에 기술 29개밖에 없으니 현실 저장소에는 모르는 좌표가 잔뜩 나온다.

후보는 **DEPENDENCY 사실에서만** 만든다. import 경로에서도 만들 수 있지만,
`java.util`, `os`, `sys` 같은 표준 라이브러리가 후보 목록을 채운다.

### 왜 자동 등록하지 않나

petclinic 한 저장소에서 나온 실제 후보 10건이 이유를 그대로 보여준다.

```
com.github.ben-manes.caffeine:caffeine        캐시 라이브러리   → 등록
com.h2database:h2                             인메모리 DB       → 등록
com.puppycrawl.tools:checkstyle               빌드 도구         → 거절
io.spring.javaformat:spring-javaformat-...    빌드 도구         → 거절
io.spring.nohttp:nohttp-checkstyle            빌드 도구         → 거절
org.webjars.npm:bootstrap                     정적 자원 포장    → 판단 필요
javax.cache:cache-api                         스펙 인터페이스   → 판단 필요
```

좌표만 보고는 라이브러리인지 빌드 플러그인인지 구분할 규칙이 없다. 사람이
본다.

### 관찰을 따로 저장하는 이유

```
technology_candidate              집계값 (distinct_user_count 등)
technology_candidate_observation  누가 어느 분석에서 봤는지 원본
```

카운터를 증가시키기만 하면 되돌릴 수 없다. 같은 분석이 두 번 반영됐는지 알
방법이 없고, 분석이 지워졌을 때 뺄 값도 없고, 한 번 틀어진 값은 복구가
불가능하다. 관찰 행을 남기면 집계는 **언제나 다시 계산할 수 있는 함수**가 된다.

```sql
UPDATE technology_candidate c SET distinct_user_count = totals.users, ...
FROM (SELECT count(DISTINCT user_id) AS users, ...
      FROM technology_candidate_observation WHERE candidate_id = ?) AS totals
WHERE c.candidate_id = ?
```

### 순위는 사용자 수로만

```sql
ORDER BY distinct_user_count DESC, distinct_repository_count DESC, coordinate
```

발생 횟수로 정렬하면 모노레포 하나가 순서를 정한다. 관리자가 답할 질문은
"몇 줄이 언급하는가"가 아니라 **"몇 명에게 쓸모가 있는가"**다.

### 거절해도 지우지 않는다

`status <> 'REJECTED'`로 걸러 보여줄 뿐 행은 남고 관찰 수는 계속 는다. 세 명이
쓸 때 거절한 것이 삼백 명이 쓸 때는 다른 판단일 수 있다. 그래서 **거절 사유를
필수로** 받는다 — 사유가 없으면 다음 사람이 같은 판단을 처음부터 다시 한다.

### 승격은 초안에 쌓인다

```
CURRENT (registry-20260910.2)      ← 지금 판정에 쓰인다. 안 바뀐다.
   │  openDraft() — 통째로 복사
   ▼
DRAFT  (registry-20260910.3)       ← 승격이 여기 쌓인다
   │  publish()
   ▼
CURRENT (registry-20260910.3)      ← 이후 요청되는 분석부터
RETIRED (registry-20260910.2)      ← 행은 그대로
```

**초안을 빈 상태가 아니라 복사본으로 여는 게 중요하다.** 새 기술만 담은 초안을
발행하면 기존 29개가 전부 사라진다. 그러면 모든 저장소가 "거의 아무것도 안
쓴다"로 나오는데, 그건 정상 결과처럼 보여서 눈에 안 띈다.

승격 한 번이 만드는 것:

| 테이블 | 내용 |
|---|---|
| `technology` | 기술 자체 |
| `technology_category` | 고른 직무 도메인마다 한 행 |
| `technology_mapping` | `PACKAGE` · 후보의 생태계·좌표 · **`EXACT`** |
| `evidence_rule` 이하 | `{tech_id}.l0.dependency` 규칙 한 벌 |

- **`EXACT`인 이유** — `PREFIX`로 넓히면 아무도 쓰는 걸 본 적 없는 아티팩트까지
  그 기술로 판정된다. 관찰한 것보다 넓은 근거는 만들지 않는다.
- **L0만 만드는 이유** — 승격된 후보는 의존성 좌표라 "선언했다"까지가 관찰된
  사실이다. L1·L2는 이 승격이 갖고 있지 않은 매핑이 있어야 답한다.

### 경합 처리

승격은 초안 편집과 후보 상태 변경을 **한 트랜잭션**에서 한다. 상태 변경은
`WHERE status IN ('NEW','REVIEWING')`이라 다른 사람이 먼저 처리했으면 0행이
갱신되고, 그때 예외를 던져 초안 편집까지 되돌린다.

되돌리지 않으면 기술은 레지스트리에 들어갔는데 후보는 다른 사람의 결정을 달고
남는다. 그 후보가 다시 승격되면 같은 기술이 두 번 등록된다.

### API

`/api/v1/admin/**`는 `SecurityConfig`가 `hasRole("ADMIN")`으로 제한한다.
역할은 `user.role` 컬럼(V10)에 있고 JWT 필터가 `ROLE_`를 붙여 권한으로 만든다.

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| GET | `/api/v1/admin/technology-candidates?limit=50` | 후보 목록 (1~200) |
| GET | `.../registry` | `{current, draft}` |
| POST | `.../{id}/promote` | 초안에 등록 |
| POST | `.../{id}/reject` | 거절 |
| POST | `.../registry/publish` | 초안 발행 |

오류는 공통 실패 봉투를 쓴다.

| 코드 | 상태 | 뜻 |
|---|---|---|
| `ADMIN-400-1` | 400 | 기술 식별자 형식이 아니다 |
| `ADMIN-404-1` | 404 | 후보가 없다 |
| `ADMIN-409-1` | 409 | 이미 처리된 후보다 |
| `ADMIN-409-2` | 409 | 발행할 초안이 없다 |

`ADMIN-409-1`은 장애가 아니다. 관리자 둘이 같은 목록을 보고 같은 행을 누르는
일은 정상이고, 뒤에 누른 쪽은 목록을 새로 읽으면 무엇이 어떻게 처리됐는지
그대로 보인다.

### 화면

`FE/src/features/admin/pages/TechnologyCandidatePage.tsx`,
경로 `/admin/technology-candidates`.

- 후보 목록 — 사용자 수 순, 행마다 승격/거절 폼
- 레지스트리 패널 — 적용 중 버전 · 대기 초안 · 발행 버튼
- 승격 폼은 좌표에서 만든 식별자와 표시명을 미리 채운다.
  `io.jsonwebtoken:jjwt-api` → `io-jsonwebtoken-jjwt-api`
- **직무는 기본값을 두지 않는다.** 백엔드로 기본 처리하면 잘못 들어간 게
  화면에서 안 드러난다.
- 낙관적 업데이트를 하지 않는다. 미리 지운 행을 409 받고 되살리는 것보다
  서버가 실제로 뭘 받아들였는지 다시 읽는 편이 정확하다.
- 라우트를 숨기지 않는다. 숨겨도 보호가 안 되고, 접근 제어는 BE가 한다.

---

## 15. ⑪ 결과를 화면으로 — 조회 API

⑩까지가 전부 **쓰기 경로**였다. 요청을 받아 판정해서 저장하는 데까지. 그것을
다시 꺼내 보여주는 읽기 경로가 없어서, 분석이 끝나도 화면은 비어 있었다.

| 엔드포인트 | 하는 일 |
|---|---|
| `GET /api/v1/analyses/{analysisId}` | 진행 상황. 등록 응답의 `statusUrl`이 가리키는 곳 |
| `GET /api/v1/me/technologies` | 지표 + 기술별 판정 + 판정에 쓰인 저장소 |
| `GET /api/v1/me/technologies/{techId}/evidence` | Level로 묶은 근거 + GitHub permalink |

프로필은 셋을 **한 응답으로** 내려준다. 따로 부르면 그사이 분석이 하나 끝났을 때
지표와 목록이 서로 어긋난 화면이 된다.

### 집계 단위: 저장소마다 최신 성공 분석

분석은 저장소 하나에 한 건씩 만들어진다. 같은 저장소를 두 번 분석하면 행이 둘
생기는데, 둘을 합치면 **지운 코드가 근거로 남는다.**

```sql
SELECT DISTINCT ON (repository_id) analysis_id, repository_id, ...
FROM analysis_job WHERE user_id = ? AND status = 'SUCCEEDED'
ORDER BY repository_id, completed_at DESC
```

### Level은 최고치를 채택한다

한 기술이 저장소 A에서는 import만(L1), B에서는 호출까지(L2) 확인될 수 있다. 이때
답은 "이 사람은 L2를 해 봤다"이다. 평균을 내면 실제로 한 일이 사라지고, 최저치를
쓰면 안 쓴 저장소가 판정을 끌어내린다.

`rule_type`이 `L0`..`L3` 문자열이라 사전순 최대가 곧 최고 Level이다.

### 근거는 Level마다 따로 자른다

전체에 하나의 `LIMIT`을 걸면 안 된다. 정렬이 Level 내림차순이라 **L2가 상한을
채우는 순간 L0과 L1이 통째로 사라지고**, 화면은 "의존성 선언이 없다"로 읽힌다.
실제로 Spring Security 한 기술이 저장소 하나에서 L2 40건 · L1 40건을 낸다.

```sql
row_number() OVER (PARTITION BY r.rule_type ORDER BY file_path, start_line) AS rank_in_level,
count(*)     OVER (PARTITION BY r.rule_type)                               AS total_in_level
```

같은 윈도우 함수가 자르기 전 총계도 준다. 그래서 "근거 40건 · 상위 20건만 표시"라고
말할 수 있다. 잘렸다는 사실을 감추면 화면이 "근거는 이게 전부"라고 거짓말을 한다.

### 응답은 Level → 파일 → 라인으로 접는다

평평하게 두면 같은 파일의 연속된 import 세 줄이 세 행을 차지한다. `SecurityConfig.java`
하나가 5행이 되고, 화면은 "왜 L2인가"가 아니라 로그가 된다.

```
L2 구현   Spring Security 필터 체인 구성        근거 40건 · 파일 16개
  cseongbo/Tripplannerz / config/SecurityConfig.java
    IMPORT L10 · IMPORT L11 · IMPORT L12 · API_CALL L30 · API_CALL L32
  …
L1 노출   Spring Security import                근거 40건 · 파일 18개
L0 없음   Spring Security 의존성 선언           근거  2건 · 파일  1개
```

### permalink는 커밋을 고정한다

```
https://github.com/{owner}/{repo}/blob/{commit_sha}/{path}#L{n}
```

브랜치 이름으로 걸면 그 줄이 나중에 밀리거나 지워졌을 때 링크가 엉뚱한 코드를
가리키고, **근거가 조용히 거짓이 된다.**

저장소 이름이 필요해서 V13이 `analysis_job.repository_full_name`을 추가했다. 조회
시점에 GitHub에 숫자 id로 물어보는 방법도 있지만 호출 한도를 쓰고, 저장소가
삭제되거나 비공개로 바뀌면 과거 근거를 영영 못 읽는다. 이름은 바뀔 수 있으므로
**분석 당시의 이름**으로 박아 둔다 — 동일성 판단은 계속 `repository_id`가 한다.

V13 이전 분석은 이 값이 `NULL`이라 링크를 만들지 못한다. 지어내지 않고 경로만
보여준다.

### Personal Level은 비운다

화면의 `PERSONAL` 칸은 항상 미판정이다. "본인 Commit이 확인된 범위"를 알려면 근거
라인마다 작성자를 봐야 하는데 `analysis_evidence_commit`을 **아직 아무도 채우지
않는다.** Repository Level을 대신 넣으면 화면이 "본인이 썼다"고 말하게 된다.
[20장](#20--개인-판정--누가-이-근거를-썼는가)이 그 작업이다.

### 빈 결과는 오류가 아니다

`dataStatus`가 셋을 구분한다.

| 값 | 뜻 |
|---|---|
| `READY` | 판정된 기술이 있다 |
| `INSUFFICIENT_DATA` | 분석은 했는데 Registry가 아는 기술이 안 나왔다 |
| `NO_DATA` | 분석한 적이 없다 |

뒤의 둘은 사용자가 해야 할 일이 다르다. 하나로 합치면 화면이 잘못된 안내를 한다.

---

## 16. 토큰 암호화

`user.access_token`이 **평문**이었다. scope가 `read:user,repo`라 DB를 읽을 수 있는
사람은 그 사용자의 비공개 저장소를 전부 읽을 수 있었다. V1의 TODO가 가리키던
작업이고 V12가 그것을 메운다.

엔티티 필드는 `String` 그대로 두고 `AttributeConverter`가 영속화 시점에만 바꾼다.
그래서 이 값을 쓰는 코드는 하나도 달라지지 않았다.

```java
@Convert(converter = EncryptedStringConverter.class)
@Column(name = "access_token_enc")
private String accessToken;
```

### CBC가 아니라 GCM인 이유

기존 빈 설정 `new AesBytesEncryptor(key, salt)`에 실제 취약점이 있었다. Spring의
`CipherAlgorithm.CBC`는 기본 IV 생성기가 `NULL_IV_GENERATOR` — **0으로 채운 고정
IV**다. IV를 출력에 붙이지도 않는다. 결과적으로:

- **결정적 암호화** — 같은 토큰이 언제나 같은 암호문이 되어, 토큰이 같은 두 행이
  DB에서 그대로 드러난다
- **인증 없음** — 변조를 잡지 못한다

GCM에 난수 IV 16바이트를 명시했다. 인증 태그 16바이트가 붙어 한 바이트만 바뀌어도
복호화가 실패한다. 이 빈을 쓰는 곳이 없을 때 바꿔서 비용이 0이었다 — 배포한 뒤
알고리즘을 바꾸면 저장된 토큰을 전부 재암호화해야 한다.

**이 컬럼으로는 조회할 수 없다.** 매번 다른 바이트가 되므로 `WHERE access_token_enc = ?`는
절대 맞지 않는다.

### 평문을 옮기지 않았다

백필하려면 `UPDATE` 문 안에 평문이 들어가고, 그 문장은 WAL을 타고 흐른다. 토큰이
없는 사용자는 다음 요청에서 `GITHUB_TOKEN_INVALID` → "다시 로그인해 주세요"를 받고,
재로그인 한 번으로 암호화된 값이 채워진다.

**대신 남아 있는 토큰을 조용히 버리지도 않는다.** V12 는 `access_token` 에 값이
한 건이라도 있으면 컬럼을 지우기 전에 예외를 던지고 멈춘다.

```sql
IF EXISTS (SELECT 1 FROM "user" WHERE "access_token" IS NOT NULL) THEN
    RAISE EXCEPTION 'V12 cannot drop user.access_token while GitHub tokens remain; ...';
```

토큰을 잃는 줄 모르고 배포하는 것보다, 애플리케이션에서 암호화 이관을 하든 재로그인
정책을 택하든 **명시적으로 고른 뒤** 다시 적용하는 편이 낫다. 백필을 안 하는 것과
가드를 두는 것은 상충하지 않는다 — 전자는 평문을 WAL 에 흘리지 않겠다는 것이고,
후자는 그 결정의 대가를 운영자가 모르고 치르지 않게 하는 것이다.

### 평문은 디스크에서 지워지지 않았다

백필의 WAL 노출은 피했지만, `DROP COLUMN` 자체는 **논리적 삭제**다. PostgreSQL 은
`pg_attribute` 에 `attisdropped` 를 세울 뿐 힙 튜플의 바이트를 건드리지 않는다.
그 튜플이 다시 쓰이기 전까지(`UPDATE` · `VACUUM FULL` · `CLUSTER`) 회수할 수 있고,
이미 만들어진 WAL 세그먼트와 베이스 백업에도 남아 있다.

**V12 가 없앤 것은 "애플리케이션 경로로 읽히는 평문"이지 "디스크 위의 평문"이
아니다.** 백필을 WAL 노출을 근거로 거부했으므로 같은 기준을 여기에도 적어 둔다 —
두 조치의 보호 수준이 다르다는 것을 감추지 않기 위해서다.

완전히 지우려면 `VACUUM FULL "user"` 후 기존 백업·WAL 을 폐기해야 한다.
마이그레이션에 넣지 않은 이유가 둘이다. `VACUUM FULL` 은 트랜잭션 안에서 실행될 수
없는데 Flyway 가 마이그레이션을 트랜잭션으로 감싸고, `ACCESS EXCLUSIVE` 락을 잡아
그동안 `user` 테이블 접근이 전부 막힌다. 운영 절차로 다룰 일이다.

> 이 설명을 V12 파일 주석이 아니라 여기에 둔 것도 이유가 있다. 적용된 마이그레이션은
> 주석만 고쳐도 체크섬이 바뀌어 Flyway 가 거부하고, 그것을 이미 실행한 사람은
> 전부 `repair` 를 돌려야 한다.

### 복호화 실패를 삼키지 않는다

`null`을 돌려주면 호출자는 "토큰이 없다"로 읽고 재로그인을 시킨다. 그러면 **잘못된
키로 새 값이 덮여 쓰이고 설정 오류는 끝까지 드러나지 않는다.** 시끄럽게 실패하는
편이 맞다.

---

## 17. 실측 결과

### 처음으로 전 구간이 실물로 돌았다

2026-09-11, 로그인 → 저장소 선택 → `POST /api/v1/analyses` → CDC → 워커 → 결과
저장까지 **HTTP로 관통한 첫 사례**다. 그전의 성공 기록은 전부 outbox에 직접 넣은
합성 데이터였다.

실제 사용자(`cseongbo`)의 분석 3건:

```
cseongbo/Tripplannerz     SUCCEEDED
(비공개 저장소)            SUCCEEDED
(비공개 저장소)            FAILED   REPOSITORY_NOT_ACCESSIBLE
```

마지막 하나가 [8장](#8--클론)의 제약이 실제로 드러난 것이다 — 워커가 익명으로
clone하므로 비공개 저장소는 받아오지 못한다.

기술 판정 결과:

```
spring-security  L2   근거 82        lombok           L1   근거 46
spring-boot      L2   근거 45        spring-data-jpa  L1   근거 24
react            L2   근거 42        junit            L1   근거 10
redis            L2   근거 22        axios            L1   근거  9
                                     postgresql       L0   근거  1
                                     mysql            L0   근거  1
```

Java와 TypeScript가 한 사람의 저장소에서 같이 잡혔다. `react`·`axios`가 나온 것은
파싱이 6개 언어를 함께 본다는 증거다.

### 개인 판정도 실물로 돌았다

2026-09-11, 워커를 재빌드해 `cseongbo/cardGGaduekMainServiceBackend`(커밋
`dc90016`)를 **같은 커밋으로 두 번** 돌려 `-w -M` 전후를 비교했다.

```
근거          90 건   (90건 전부 commit_sha 가 채워졌다)
SOLE_AUTHOR   46
UNVERIFIED    44
```

라벨 분포는 두 번이 **같다.** 줄 단위로 대조하니 한 줄이 움직였다.

```
SpendPredictionService.java:43
  before  9734616e  (2025-08-19)
  after   138e1ad4  (2025-08-11)
```

8/19 커밋이 그 줄의 **공백만** 고쳤다는 뜻이고, `-w`가 원래 작성자에게 돌려준
것이다. 두 커밋 모두 작성자가 같은 팀원이라 라벨까지 바뀌지는 않았다. 수정은
동작하고, 이 저장소에서는 결과를 바꾸지 않았다.

기술별로는 이렇게 갈렸다.

| 기술 | `SOLE_AUTHOR` | `UNVERIFIED` |
|---|---|---|
| `spring-security` | 32 | 12 |
| `redis` | 11 | 8 |
| `lombok` | 2 | 22 |
| `mysql` | 1 | — |
| `junit` | — | 2 |

`lombok`이 22:2로 남의 것이다. 팀 프로젝트에서 개인 판정이 저장소 판정보다 낮게
나오는 것이 정상이라는 증거다 — 저장소는 `lombok`을 쓰지만 이 사람이 그것을
들여온 것은 아니다.

> **컨테이너가 둘이다.** `gitjob-worker-1`과 `gitjob-analysis-worker-1`은 같은
> 이미지를 쓰지만 컨슈머 그룹이 다르다. 저장소 분석을 처리하고
> `ANALYSIS_ATTRIBUTE_AUTHORS`를 들고 있는 쪽은 **`gitjob-analysis-worker-1`**
> 이다. 로그를 앞의 것에서 보면 아무 일도 안 일어난 것처럼 보인다.

### 속도

`spring-projects/spring-petclinic` 한 건을 라이브 스택에서 돌린 기록:

```
02:16:00.208  cloned        1.9MB
02:16:00.239  parsed        471 imports
02:16:00.250  dependencies  55 declared
02:16:00.269  registry      117 mappings · 60 rules
02:16:00.305  judged        기술 7 · Evidence 97 · 후보 10
02:16:00.440  published     COMPLETED
```

전 구간 **250ms**. 이 기록은 L2 규칙(V9) 이전이라 규칙이 60개다.

멱등성도 확인했다 — 같은 결과를 다시 발행하면 `Result ignored, job already
SUCCEEDED`.

### DB 누적 (2026-09-11 기준)

```
analysis_job                       9   (SUCCEEDED 6 · FAILED 3)
analysis_outbox                    9   (PENDING 9 — CDC 모드에서 정상)
analysis_evidence                651
technology_candidate              72
technology_candidate_observation  93
technology_registry                3   (CURRENT = registry-20260910.2)
```

레지스트리는 기술 29 · 매핑 117 · 규칙 83으로 그대로다.

이 숫자는 위의 기여 판정 실측 **이전**이다. 그 뒤 재분석 2건이 더해져
`analysis_evidence_commit`과 `repository_commit`이 처음으로 채워졌다.

---

## 18. 테스트

| 대상 | 결과 |
|---|---|
| **BE** | **272 passed · 0 failed** |
| **AI (worker)** | **1,741 passed · 1 failed · 106 skipped** |
| **FE** | `tsc --noEmit` 통과 · `oxlint` 통과 |

AI의 실패 1건(`test_registry_contracts`)은 이 작업 범위 밖의 기존 실패다.

`AI/`에는 venv가 없다. 호스트 파이썬에 `pytest`가 없으므로 워커 이미지 안에서
돌린다 — `test_analysis_blame`은 진짜 git 저장소를 만들어 쓰기 때문에 `git`이
있는 환경이어야 한다.

```bash
docker run --rm -v "$PWD/AI:/w" -w //w gitjob/worker:local   sh -c 'pip install -q pytest && python -m pytest tests -q'
```

집계와 변환은 조용히 틀리는 종류라 실제 PostgreSQL로 고정한 것이 많다.

| 테스트 | 무엇을 막는가 |
|---|---|
| `TechnologyProfileStoreTest` | 저장소별 최신 분석만 세는지, Level 최고치를 채택하는지, 남의 분석이 안 섞이는지 |
| `TechnologyEvidenceResponseTest` | 같은 파일이 접히는지, 잘림이 보고되는지, permalink가 커밋을 고정하는지 |
| `EncryptedStringConverterTest` | 평문이 컬럼에 남지 않는지, 같은 값이 매번 다른 바이트가 되는지, 변조를 잡는지 |
| `UserAccessTokenEncryptionTest` | Hibernate가 변환기를 Spring 빈으로 받아 가는지 (원시 바이트를 JDBC로 직접 확인) |
| `SchemaValidationTest` | 엔티티 매핑이 마이그레이션과 어긋나지 않는지 |
| `RegistryDraftStoreTest` | 초안이 CURRENT의 복사본인지, CURRENT가 언제나 하나인지 |
| `test_analysis_blame` | 얕은 체크아웃이 거부되는지 — 거부 안 했을 때 무엇이 나왔을지까지 함께. 공백만 바꾼 커밋이 기여를 가져가지 않는지 |
| `TechnologyProfileStoreTest` (Personal) | 절이 둘인 규칙에 한쪽만 본인 것이면 안 서는지, 저장소를 가로질러 조립하지 않는지 |
| `test_entrypoints` | 기여 판정과 히스토리가 한 스위치인지, 기본이 off 인지 |

---

## 19. 실행 방법

### 인프라 (PowerShell)

```powershell
docker compose --env-file .env -f Infra/compose/compose.yaml --profile app up -d
```

- 루트 `.env`에 `KAFKA_CLUSTER_ID`, `POSTGRES_*`, `JWT_SECRET` 등이 필요하다.
- `POSTGRES_PORT`가 5432인데 네이티브 PostgreSQL이 떠 있으면 포트 충돌이 난다.

### BE만 따로 (IntelliJ)

컨테이너의 postgres·redis·kafka를 쓰고 애플리케이션만 IDE에서 띄운다.
Flyway가 기동 시 마이그레이션을 적용한다.

### FE 개발 서버

```bash
cd FE && npm install && npm run dev
```

Vite가 `/api`를 `http://localhost:8080`(nginx)으로 프록시한다. 8080의 프론트
컨테이너는 빌드된 번들이라 소스 변경이 보이지 않으므로, 개발 중에는 5173을 본다.

로그인 후 브라우저가 도착할 화면은 `FRONTEND_CALLBACK_URL`이 정한다. 개발 서버를
보는 동안에는 `.env`에서 5173으로 돌려 둔다.

```
FRONTEND_CALLBACK_URL=http://localhost:5173/auth/callback
```

`GITHUB_REDIRECT_URI`와 헷갈리면 안 된다. 그쪽은 **GitHub이** 호출하는 주소라 OAuth
앱 설정과 일치해야 하고 8080 그대로 둔다.

### CDC 커넥터 등록

```bash
Infra/scripts/cdc-register.sh
```

> Git Bash에서 컨테이너 내부 경로가 Windows 경로로 변환되는 문제가 있다.
> `//opt/kafka/bin/...`처럼 슬래시를 두 번 쓰면 변환을 막을 수 있다.
> `MSYS_NO_PATHCONV=1`은 같은 명령에 호스트 경로가 섞여 있으면 오히려 깨진다.

### 관리자 화면 접근

`user.role`이 `ADMIN`이어야 한다.

```bash
docker exec gitjob-postgres-1 psql -U gitjob -d gitjob -c "UPDATE \"user\" SET role='ADMIN' WHERE user_id=1"
```

---

## 20. ⑫ 개인 판정 — 누가 이 근거를 썼는가

⑪까지는 **저장소**가 그 기술을 어떻게 쓰는지였다. 이 장은 **그 사람**이 어떻게
썼는지다. 화면의 `PERSONAL` 칸이 여기서 나온다.

### 점수를 만들지 않는다

Personal Level 은 **Repository Level 과 같은 판정을, 본인이 쓴 근거만으로 다시 한
것**이다. 기여도·기간을 가중치로 더하지 않는다.

| | Repository | Personal |
|---|---|---|
| 규칙 | 같은 규칙 | 같은 규칙 |
| 사실 | 모든 근거 | 본인이 쓴 근거만 |

같은 자로 재기 때문에 얻는 것이 셋이다.

**① 두 값이 비교 가능하다.** 화면이 나란히 놓는데 한쪽이 규칙 판정이고 한쪽이
가중치 합이면 나란히 둘 이유가 없다. 차이 자체가 정보가 되려면 같은 자여야 한다.

**② `Personal ≤ Repository` 가 자동으로 성립한다.** 부분집합이 더 많은 규칙을
만족할 수 없다. 각주의 *"Personal Level이 Repository Level보다 낮은 기술은 저장소에는
구현이 있으나 본인 기여 근거가 확인되지 않은 경우"* 가 그냥 참이 된다.

**③ 설명할 수 있다.** "왜 personal L1인가" → *"L2 규칙의 `API_CALL` 절을 만족하는
근거 중 본인이 쓴 것이 없다."* 파일과 라인을 그대로 가리킨다.

### 흐름

```
워커                                    BE
────                                    ──
full clone (히스토리 포함)
근거 파일만 git blame -L start,end
  근거 ─→ 그 줄을 마지막에 바꾼 commit_sha
결과 이벤트에 실음  ──────────────────▶  analysis_evidence.commit_sha 저장
  (신원 판단은 안 함)                     ↓ 별도 트랜잭션
                                        커밋 → GitHub 계정 해석
                                        repository_commit 에 캐시
                                        analysis_evidence_commit 적재
                                          ↓ 조회 시점
                                        본인 근거로 절 커버리지 재판정
```

### 왜 워커가 신원을 모르는가

워커는 **"어느 커밋"** 까지만 답하고 **"누구의 커밋"** 은 답하지 않는다. 후자를
알려면 요청자의 신원이 필요한데, 요청 토픽은 그 신원보다 오래 산다
(`contracts.py`: *"토픽이 자격증명보다 오래 산다"*).

BE 는 이메일을 비교하지 않는다. GitHub 이 커밋의 이메일을 등록 계정과 이미
맞춰 두었으므로 `GET /repos/{o}/{r}/commits/{sha}` 의 `author.login` 을 받아 쓴다.
`user:email` scope 도, 남의 이메일을 우리 시스템에 들이는 일도 필요 없다.

### 클론은 full 이어야 한다 — 측정으로 정했다

`spring-petclinic`, 근거 파일 40개 blame:

| 전략 | 클론 | 디스크 | blame | 판정 |
|---|---|---|---|---|
| `--depth 1` | 1.4s | 3MB | 2.1s | ❌ **답이 틀림** |
| **`full`** | 4.0s | 13MB | 2.7s | ✅ |
| `--filter=blob:none` | 2.5s | 4MB | **10분 37초** | ❌ |
| `--filter=tree:0` | 3.0s | 3MB | **35분 18초** | ❌ |

부분 클론은 클론에서 1~1.5초 아끼고 blame 에서 **240~800배** 돌려준다. 없는 blob
하나하나가 원격 왕복이다.

### 얕은 클론은 실패하지 않는다 — 거짓말을 한다

이 작업에서 가장 중요한 발견이다.

```
blame 이 지목한 커밋 : 818c4136…  (단 하나)
저장소의 커밋 수     : 1
실패 건수            : 0
```

`--depth 1` 에는 커밋이 하나뿐이라 **모든 줄을 그 tip 커밋 작성자에게 돌린다.**
출력은 멀쩡하고 오류도 없다. 검증을 "blame 이 되는가" 로 했으면 통과했을 것이다.

그래서 `blame_files` 는 얕은 저장소에서 **결과를 내는 대신 거부한다.**

```python
if is_shallow(repository):
    raise ShallowRepositoryError(...)
```

배포 스위치도 하나로 묶었다. `ANALYSIS_ATTRIBUTE_AUTHORS` 가 `with_history` 와
`attribute_authors` 를 함께 켠다 — 따로 두면 "기여 판정만 켜고 히스토리는 끈"
조용히 틀린 설정을 만들 수 있다.

### 포맷터가 기여를 가져가지 않게 한다 — `-w -M`

이 모듈의 오차는 거의 전부 *본인 기여를 놓치는* 쪽이다. 방향이 반대인 것이 딱
하나 있었다.

동료가 `import` 한 줄을 쓰고, 그 뒤에 누가 그 줄의 **들여쓰기만** 바꾼다. 기본
`git blame`은 그 줄의 작성자를 들여쓰기를 바꾼 사람으로 옮긴다. 그러면 만들지도
않은 기술이 그 사람의 개인 판정에 잡힌다 — 과대평가다. 다른 오차와 달리 이것만은
없는 기여를 주장하게 된다.

두 사람짜리 저장소로 재현했다.

```
커밋 1  동료가  import …SpringApplication;  을 쓴다
커밋 2  우리가  그 줄의 들여쓰기만 바꾼다

그 줄을 blame 하면
  기본   → 커밋 2  (우리)      ❌
  -w     → 커밋 1  (동료)      ✅
```

`-M`은 같은 이유로 파일 안에서 옮겨진 코드를 따라간다.

줄을 **건드리지 않고 위치만 밀린** 경우(위에 빈 줄 하나를 넣는 식)는 git이 이미
스스로 따라간다. `-w`가 무엇을 *더* 막는지 드러나도록 그 경우도 함께 테스트로
고정해 뒀다.

`--no-color`는 주지 않는다. `git blame`이 `--no-color-lines`·`--no-color-by-age`와
모호하다며 거부하고, porcelain 출력은 애초에 색이 없다.

### 판정: 절 커버리지, 엄격

개수를 세지 않는다. `spring-security` L2 규칙은 두 절이 AND 다.

```
API_CALL    2건  (SecurityConfig.java)
IMPORT     18건  (9개 파일)
```

IMPORT 18건을 전부 본인이 썼어도 **API_CALL 이 하나도 없으면 L1** 이다. 82건 중
2건짜리 절이 L2 를 결정한다 — 그게 L2 의 정의(호출까지 했다)이기 때문이다.

세는 것은 `SOLE_AUTHOR` 와 `CO_AUTHORED` 뿐이다. `PARTIAL_EDIT` 는 정의상 *그 근거
줄을* 본인이 쓰지 않았다는 뜻이라 레벨의 근거가 아니다.

### 순서: 저장소 안에서 판정, 저장소 밖에서 최고치

```sql
mine  AS (... WHERE c.contribution_type IN ('SOLE_AUTHOR','CO_AUTHORED'))
holds AS (... GROUP BY mine.analysis_id, r.rule_id  -- 저장소 안에서 절 커버리지
               HAVING 모든 REQUIRED 절이 덮였는가)
SELECT tech_id, max(rule_type) FROM holds GROUP BY tech_id   -- 그다음 최고치
```

뒤집으면 저장소 A 의 IMPORT 와 저장소 B 의 API_CALL 을 붙여 L2 를 만든다. 어느
저장소에서도 하지 않은 일이다. 실제로 같은 규칙이 저장소 7개에 걸쳐 있어 이 실수가
가능하다.

### 저장되는 것과 계산되는 것

```
저장                                       계산
────                                       ────
analysis_evidence.commit_sha   (V14)       Repository Level   ← 조회 시점
analysis_evidence_commit                   Personal Level     ← 조회 시점
repository_commit              커밋 캐시
```

**Level 은 어디에도 저장하지 않는다.** 근거에서 유도되는 값이라 저장하면 둘을
맞출 책임이 생기고, 규칙 버전이 바뀌면 판정만 낡는다. 근거에 `registry_version` 이
박혀 있으니 계산하면 자동으로 맞는다.

V14 가 채운 빈칸 셋:

| | 왜 |
|---|---|
| `analysis_evidence.commit_sha` | 근거가 어느 커밋에서 왔는지 |
| `UQ_REPOSITORY_COMMIT` | 커밋 캐시의 동일성 |
| `UQ_EVIDENCE_COMMIT_USER` | 재배달 시 기여가 두 배로 세어지는 것 방지 |

### 실패해도 근거를 버리지 않는다

기여 판정은 근거 적재와 **다른 트랜잭션**이다. 같은 트랜잭션이면 GitHub 이 잠깐
느렸다는 이유로 이미 판정된 근거 651건이 롤백된다.

```java
results.apply(event);            // 근거 커밋됨
try {
    authorship.attribute(job);   // 별도 트랜잭션
} catch (RuntimeException unavailable) {
    log.warn("authorship deferred: ...");
}
```

커밋 조회에 상한도 뒀다. 한 분석이 사용자의 시간당 한도를 다 쓰면 그 뒤 저장소
분석이 전부 막힌다.

### null 은 "안 썼다"가 아니다

`personalLevel` 이 `null` 이면 **확인되지 않았다**는 뜻이다 — 기여 판정을 끄고
돌렸거나, 얕은 체크아웃이었거나, GitHub 이 커밋을 계정과 연결하지 못했다. 계정에
등록하지 않은 이메일로 커밋하면 본인 코드여도 그렇게 된다.

그때 기여는 **과소평가**된다. 없는 기여를 주장하는 것보다 낫다. 화면은 `L0` 가
아니라 "미판정"으로 쓴다.

---

## 21. 아직 안 한 것

| 항목 | 상태 |
|---|---|
| ~~개인 판정 라이브 검증~~ | **끝났다.** 재빌드 후 실물로 돌려 근거 90건에 기여 판정이 붙었다([17장](#17-실측-결과)) |
| 기존 분석 9건의 기여 판정 | 소급되지 않는다. `commit_sha`가 없어 재분석해야 한다. 지금까지 재분석한 것은 저장소 1개다 |
| `UNVERIFIED`가 두 가지를 뭉갠다 | "팀원이 썼다"와 "GitHub이 커밋을 계정과 연결하지 못했다"가 같은 값이다. 화면에서 구분하려면 `UNLINKED_COMMIT`이 따로 필요하다 |
| 사용 기간 | 미착수. `repository_commit.authored_at`이 채워지므로 재료는 생겼다 |
| `CO_AUTHORED` · `PARTIAL_EDIT` | 값은 있지만 안 나온다. 근거가 한 줄짜리라 `SOLE_AUTHOR`/`UNVERIFIED`로만 갈린다 |
| ~~비공개 저장소 분석~~ | S15P21E102-280에서 on-demand 내부 credential broker를 구현했다. 실제 EC2 배포·사용자 canary는 별도 검증이 필요하다 |
| `analysis_outbox` 보존 정책 | 행이 무한히 쌓인다. 정리 배치가 필요하다 |
| L3 규칙 | 기술 29개 중 2개만 있다 |
| FE 조회 클라이언트 이원화 | `evidenceApi.ts`(티켓 208)와 `technologiesApi.ts`가 같은 엔드포인트를 본다. 하나로 정리해야 한다 |
| 인증된 왕복 검증 | BE 응답을 눈으로 본 적이 없다. 집계 SQL은 실제 PostgreSQL로 검증했다 |
| `.uv-python` / `.uv-cache-review` 제외 | `EXCLUDED_DIRECTORIES`에 없다 |

### 문서 불일치 하나

`docs/fe/shared-api-contract.md`가 `AUTH-403-1`을 **"삭제 (BE에 없고 명세와 충돌)"**
목록에 두고 있는데, BE에 `ANALYSIS_ACCESS_DENIED(AUTH-403-1)`이 생겼다. FE의
`errorCodes.ts`가 이 코드를 모르면 남의 분석을 조회했을 때 일반 오류로 떨어진다.

---

## 관련 문서

- [기술 Registry와 Evidence 규칙](be/technology-registry.md) — 규칙 테이블 상세
- [기술 후보 검토](be/technology-candidate-review.md) — 관리자 화면 상세
- [분석 Worker](be/repository-analysis-worker.md)
- [요청 계약](be/repository-analysis-request.md) · [결과 계약](be/repository-analysis-result.md)
- [Outbox와 CDC](be/analysis-outbox.md)
- [FE shared API 계약](fe/shared-api-contract.md)
- [기술 요약 LLM 계약](ai/technology-summary-contract.md) — 판정 결과를 로컬 LLM 에
  보내 요약을 받는 입출력. 수준은 규칙이 정하고 LLM 은 설명만 쓴다
- [스키마 JSON](be/technology-registry-schema.json)
