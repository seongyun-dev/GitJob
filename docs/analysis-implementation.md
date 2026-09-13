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
20. [다음 — 커밋 기여도](#20-다음--커밋-기여도)
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
        ├─ git clone --depth 1                                          ④
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

── 사용자 ─────────────────────────────────────────
user                         GitHub 로그인 + role (USER / ADMIN)
                             access_token_enc — AES-GCM 암호문 (V12)
```

마이그레이션은 Flyway `V1` ~ `V13`이고 `ddl-auto=validate`다. 스키마는
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
git clone --depth 1 --branch <branch> --single-branch <url> <tmpdir>
```

- **`--depth 1`** — 전체 히스토리는 필요 없다. 판정은 현재 코드로만 한다.
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
[20장](#20-다음--커밋-기여도)이 그 작업이다.

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

### 기존 토큰을 조용히 삭제하지 않는다

V12는 기존 `access_token` 값이 한 건이라도 있으면 암호화 컬럼으로 전환하기 전에
실패한다. 현재 공용 DB는 V11까지 적용됐고 2026-09-13 확인 당시 사용자와 토큰이 모두
0건이므로 그대로 적용할 수 있다. 배포가 늦어져 토큰이 생기면 애플리케이션 메모리에서
AES-GCM으로 암호화해 `access_token_enc`에 백필하거나, 재로그인 정책을 명시적으로
선택한 뒤 기존 값을 비워야 한다. 암호문만 UPDATE하면 새 SQL/WAL에 평문을 다시 싣지
않으므로 WAL은 백필 자체를 금지하는 이유가 아니다.

V12의 컬럼 삭제는 과거 평문의 물리적 완전 삭제를 보장하지 않는다. 기존 테이블 저장
공간·WAL·백업의 잔존 데이터 처리는 별도 운영 범위이며, 이 마이그레이션은 테이블
재작성이나 백업 삭제를 수행하지 않는다.

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

### 현재 DB 전체 누적

```
analysis_job                       9   (SUCCEEDED 6 · FAILED 3)
analysis_outbox                    9   (PENDING 9 — CDC 모드에서 정상)
analysis_evidence                651
technology_candidate              72
technology_candidate_observation  93
technology_registry                3   (CURRENT = registry-20260910.2)
```

레지스트리는 기술 29 · 매핑 117 · 규칙 83으로 그대로다.

---

## 18. 테스트

| 대상 | 결과 |
|---|---|
| **BE** | **264 passed · 0 failed** |
| **AI (worker)** | **1,554 passed · 1 failed · 64 skipped** |
| **FE** | `tsc --noEmit` 통과 · `oxlint` 통과 |

AI의 실패 1건(`test_registry_contracts`)은 이 작업 범위 밖의 기존 실패다.

집계와 변환은 조용히 틀리는 종류라 실제 PostgreSQL로 고정한 것이 많다.

| 테스트 | 무엇을 막는가 |
|---|---|
| `TechnologyProfileStoreTest` | 저장소별 최신 분석만 세는지, Level 최고치를 채택하는지, 남의 분석이 안 섞이는지 |
| `TechnologyEvidenceResponseTest` | 같은 파일이 접히는지, 잘림이 보고되는지, permalink가 커밋을 고정하는지 |
| `EncryptedStringConverterTest` | 평문이 컬럼에 남지 않는지, 같은 값이 매번 다른 바이트가 되는지, 변조를 잡는지 |
| `UserAccessTokenEncryptionTest` | Hibernate가 변환기를 Spring 빈으로 받아 가는지 (원시 바이트를 JDBC로 직접 확인) |
| `SchemaValidationTest` | 엔티티 매핑이 마이그레이션과 어긋나지 않는지 |
| `RegistryDraftStoreTest` | 초안이 CURRENT의 복사본인지, CURRENT가 언제나 하나인지 |

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

## 20. 다음 — 커밋 기여도

"이 근거를 **본인이** 썼는가"를 판정하는 작업이다. 아직 구현하지 않았고, 조사해서
나온 설계를 남겨 둔다.

### 이미 준비된 것

```
analysis_evidence_commit   contribution_type, matched_line_count   ← 0행
repository_commit          author_email, github_login, authored_at ← 0행
FE ContributionLabel       주 작성자 / 공동 작업 / 일부 수정 / 미확인
```

FE 타입은 **비율 숫자를 받지 못하게** 막혀 있다(와이어프레임 1-1 금지). 라벨 4종만
넣으면 된다.

### 막는 것 세 가지

**① `--depth 1`이라 blame이 불가능하다.** `clone.py` 주석이 이미 예고하고 있다 —
*"Contribution analysis will need history later; that is a larger `--depth`, not a
different mechanism."*

**② 요청 페이로드에 사용자 신원이 없다.** 워커가 "누구 커밋인지" 알 방법이 없다.
이건 의도된 것이다(`contracts.py`: *"토픽이 자격증명보다 오래 산다"*). 여기에
이메일을 넣으면 그 원칙이 깨진다.

**③ 이메일 매칭은 밑천이 없다.** scope가 `read:user,repo`라 `/user/emails`가
막히고 프로필 이메일도 비공개다. 지금 가진 신원은 `github_id` 하나뿐이다.

### 제안 — GitHub에게 직접 묻는다

③ 때문에 이메일 매칭을 1차 수단으로 삼으면 안 된다.

```
워커                                   BE
────                                   ──
히스토리 포함 클론
근거 파일만 git blame -L start,end
  → 근거마다 "이 줄을 마지막에 바꾼 커밋 SHA"
결과에 commit_sha 실어 보냄  ────────▶  distinct SHA를 GitHub에 조회
  (신원 판단 안 함)                      GET /repos/{o}/{r}/commits/{sha}
                                         → author.login 을 GitHub이 해석해 준다
                                       repository_commit 에 캐시
                                       본인이면 analysis_evidence_commit 기록
```

이메일을 한 번도 다루지 않는다. scope를 늘릴 필요도, 남의 이메일을 Kafka에 실을
필요도 없다. 호출 비용은 저장소당 distinct 커밋 수이고, 캐시하면 재분석 때 0건이다.

| 라벨 | 조건 |
|---|---|
| 주 작성자 | 근거 줄 전부가 본인 커밋 |
| 공동 작업 | 근거 줄 일부가 본인 |
| 일부 수정 | 근거 줄은 남이 썼지만 그 파일을 본인이 건드린 적 있음 |
| 미확인 | 본인 흔적 없음, 또는 GitHub이 계정을 연결하지 못한 커밋 |

### 정해야 할 것

**클론 비용.** petclinic이 depth 1에 1.9MB였는데 full은 수십 MB다.
`--filter=blob:none`이 대안인데 근거 파일만 blame하므로 유리할 수 있다. **재 보고
정할 일**이지 지금 단정할 수 없다.

**Personal Level을 어떻게 셀지.** L2 규칙은 `API_CALL AND IMPORT` 두 절이다. 본인이
import 한 줄만 썼을 때 L2를 줄 것인가. 느슨하게 하면 Repository Level과 거의 같아져
구분 자체가 의미를 잃는다. 화면 각주가 이미 *"Personal Level이 Repository Level보다
낮은 기술은…"*이라고 둘이 자주 갈리는 것을 전제하므로 **엄격한 쪽**을 권한다.

---

## 21. 아직 안 한 것

| 항목 | 상태 |
|---|---|
| 커밋 기여도 · Personal Level | [20장](#20-다음--커밋-기여도)의 설계까지. 구현 안 됨 |
| 비공개 저장소 분석 | 워커가 익명으로 clone한다. `REPOSITORY_NOT_ACCESSIBLE`로 실패 |
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
- [스키마 JSON](be/technology-registry-schema.json)
