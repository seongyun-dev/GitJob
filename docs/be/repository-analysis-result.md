# 분석 결과 계약

분석 worker가 판정을 끝내고 BE에게 돌려주는 이벤트다. 요청 방향
([repository-analysis-request.md](repository-analysis-request.md))의 반대편이고,
같은 봉투 구조를 쓴다.

```
BE  ──요청──▶  outbox → Debezium → gitjob.repository-analysis.requests.v1  ──▶  worker
BE  ◀──결과──  gitjob.repository-analysis.results.v1                       ◀──  worker
```

계약을 이루는 것은 네 가지다. 요청 방향이 이미 그렇게 되어 있다.

| | 결과 방향 |
| --- | --- |
| 합의 문서 | `docs/data/contracts/repository-analysis-result-v1.schema.json` |
| 발행 측 | `AI/analysis/results.py` |
| 소비 측 | `BE/.../analysis/event/RepositoryAnalysisResultEvent.java` |
| 토픽 | `gitjob.repository-analysis.results.v1` |

**양쪽이 모두 검증한다.** 중복이 아니다. 두 서비스는 따로 배포되고, 토픽에
며칠 앉아 있던 메시지는 그때 돌던 버전이 쓴 것이다. 그래서 같은 규칙을
`test_analysis_results.py`와 `RepositoryAnalysisResultEventTest`가 각각 검증한다.

## 왜 DB 직접 쓰기가 아닌가

worker는 이미 같은 데이터베이스에 붙어 있다. `repo_analysis.event_claim`을
읽고 쓴다. 그런데 `analysis_evidence`와 `analysis_job`에는 손대지 않는다.

그 테이블들은 Spring 서비스의 것이다. JPA 엔티티로 매핑돼 있고 배포가
`ddl-auto=validate`로 뜬다. 다른 언어의 두 번째 writer가 생기면 컬럼 하나
바꿀 때마다 두 저장소 마이그레이션이 된다. C조가 `c_compute` 스키마를 갖는
것과 같은 경계다.

**읽기는 다르다.** worker는 판정을 위해 Registry 테이블을 읽는다. 읽는 쪽은
스키마 주인을 제약하지 않는다.

## 봉투

```json
{
  "event_id":       "ev_result_1",
  "schema_version": "repository-analysis-result/v1",
  "event_type":     "repository.analysis.completed",
  "occurred_at":    "2026-09-10T01:02:03Z",
  "trace_id":       "tr_1",
  "payload":        { }
}
```

`schema_version`이 다르면 DLQ로 간다. 모르는 버전을 조용히 무시하면 그 분석은
영원히 끝나지 않은 상태로 남는다.

`trace_id`는 요청 이벤트에서 그대로 복사한다. 한 분석이 요청부터 결과까지
하나의 trace여야 한다.

## payload

| 필드 | 설명 |
| --- | --- |
| `analysis_id` | BE가 이것으로 `user_id`·`repository_id`를 찾는다 |
| `request_event_id` | 이 결과가 답하는 요청. 재배달과 재분석을 구분한다 |
| `registry_version` | worker가 **실제로** 평가에 쓴 버전 |
| `commit_sha` | 분석한 커밋. permalink의 절반 |
| `status` | `COMPLETED` / `FAILED` |
| `error_code` | 실패 시 필수 |
| `error_detail` | 운영자용. git stderr 등. UI는 `error_code`로 분기한다 |
| `technologies[]` | 기술별 판정 결과 |
| `evidence[]` | 그 판정을 뒷받침한 fact들 |
| `candidates[]` | 매칭 안 된 의존성 |
| `stats` | 운영 지표 |

### `user_id`는 없다

worker는 분석의 주인이 누구인지 끝내 모른다. `analysis_id`만으로 BE가 찾을 수
있고, 토픽은 요청보다 오래 산다. 신원을 여기 넣을 이유가 없다.

### 실패도 이 토픽으로 온다

DLQ가 이미 실패한 요청을 담고 있지만, **DLQ는 운영자용이다.** 저장소가 삭제된
사용자는 화면에서 "실패"를 봐야 하고, 그것이 `analysis_job`에 닿는 경로는 이
토픽뿐이다. DLQ에만 남는 실패는 job을 `QUEUED`에 영원히 묶어둔다.

`error_code` 어휘는 worker가 `repo_analysis.event_claim`에 기록하는 것과 같다.

```
REPOSITORY_NOT_FOUND       REPOSITORY_NOT_ACCESSIBLE   REPOSITORY_TOO_LARGE
CLONE_TIMEOUT              CLONE_FAILED                GIT_NOT_AVAILABLE
REGISTRY_VERSION_UNKNOWN
```

### 실패는 findings를 싣지 못한다

`FAILED`인데 `technologies`나 `evidence`가 차 있으면 계약 위반이다. 그대로
두면 BE가 실패로 표시할 분석의 Evidence 행을 쓰게 된다. 양쪽 모델이 모두
거절한다.

### 매칭 0건은 성공이다

기술을 하나도 안 쓰는 저장소는 정상적으로 `COMPLETED` + 빈 배열이다. 실패와
구분되는 것은 `status`뿐이다.

**이게 위험한 지점이다.** 잘못된 `registry_version`으로 규칙을 조회하면 0행이
나오고, 결과는 이것과 똑같이 생긴다. 그래서 worker는 요청한 버전이 Registry에
없으면 `REGISTRY_VERSION_UNKNOWN`으로 **명시적으로 실패**해야 한다. 조용히 빈
결과를 내면 안 된다.

## `evidence[]`

`analysis_evidence` 컬럼과 거의 1:1이다.

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

`fact_payload`는 규칙의 `fact_field` 어휘로 키를 잡는다(`MODULE`, `COORDINATE`,
`ECOSYSTEM`, `SCOPE`, `LANGUAGE`, `FILE_PATH`). jsonb라 새 fact 종류가 생겨도
계약을 바꿀 필요가 없다.

`code_snippet`은 선택이다. 체크아웃은 job이 끝나면 지워지므로 이것이 유일한
오프라인 사본이고, 없으면 UI가 GitHub을 왕복해야 근거를 보여줄 수 있다.

**개수 상한은 worker가 규칙별로 건다.** 스키마의 `maxItems: 2000`은 메시지
크기 방어선이지 선별 기준이 아니다. spring-petclinic 하나가 import 471건이다.

## `candidates[]`

매칭되지 않은 **의존성**이다. import는 후보로 쓰지 않는다.

```
Java/C#의 import 경로에는 신뢰할 만한 패키지 경계가 없다.
  org.springframework.web        (3세그먼트)
  org.springframework.data.redis (4세그먼트)   ← 고정 깊이로는 못 가른다
  jakarta.persistence            (2세그먼트)

매니페스트 항목은 이미 관리자가 승격할 단위다.
  org.postgresql:postgresql
```

덤으로, 매니페스트에만 나타나는 것들이 잡힌다. petclinic의 `postgresql`,
`h2`, `caffeine`, `mysql-connector-j`는 드라이버·캐시 구현이라 소스 import에
전혀 등장하지 않는다.

`coordinate`는 **버전을 뗀** 값이다. 안 떼면 같은 라이브러리가 릴리스마다 새
후보로 갈라져 카운트가 파편화된다.

| 생태계 | 정규화 |
| --- | --- |
| `MAVEN` | `group:artifact` |
| `NPM` | 스코프 포함 이름 (`@tanstack/react-query`) |
| `PYPI` | PEP 503 — 소문자, `_`·`.` → `-` |
| `NUGET` | 소문자 id |

`scope`(`implementation`, `testImplementation`, `devDependencies`…)를 지금
담아두는 이유는, 나중에 "프로덕션에서 쓴다"와 "테스트에서만 쓴다"를 구분하고
싶어질 때 재파싱하지 않기 위해서다.

`occurrence_count`는 이 저장소 안의 선언 횟수다. 관리자 화면 정렬은 이것이
아니라 **distinct 사용자 수**로 한다 — 답해야 할 질문은 "몇 줄인가"가 아니라
"몇 명에게 영향이 있는가"다. worker는 전 사용자 집계를 알 수 없으므로 관찰만
보내고 BE가 집계한다.

## BE 소비 — 결과가 DB에 닿는 곳

```
gitjob.repository-analysis.results.v1
    -> RepositoryAnalysisResultConsumer
    -> AnalysisResultService  (한 트랜잭션)
         analysis_evidence            INSERT
         technology_candidate(_observation)  UPSERT + 재집계
         analysis_job                 SUCCEEDED | FAILED
```

### 멱등성은 job 상태로 잡는다

at-least-once라 같은 결과가 두 번 온다. 별도 처리 이력 테이블 대신 **job의
상태를 표식으로** 쓴다 — 진행 중인 job만 닫고, 재배달은 이미 terminal인 것을
보고 멈춘다.

취소 사례가 덤으로 맞아떨어진다. 사용자가 취소한 뒤 도착한 결과가 job을
되살리면 안 되는데, terminal 가드가 이미 그것을 막는다.

관찰 테이블의 `UNIQUE (candidate_id, analysis_id)`가 두 번째 방어선이다. 두
방어선이 독립이라 한쪽 가정이 틀려도 카운트가 부풀지 않는다.

**Evidence와 상태는 같은 트랜잭션에서 움직인다.** 끝난 job에 Evidence가 없으면
"이 저장소는 아무 기술도 안 쓴다"로 읽히는데, 그건 정상 결과라 버그와
구분되지 않는다.

### 기술 후보 집계

worker는 **관찰만** 보낸다. "몇 명에게 영향이 있는가"는 전 사용자 집계라
worker가 알 수 없다. `user_id`와 `repository_id`도 이벤트에 없고 job에서 온다.

카운터를 증가시키지 않고 **관찰에서 다시 계산한다.** 증가 방식은 되돌릴 수
없다 — 같은 분석이 이미 반영됐는지 알 수 없고, 분석이 지워지면 무엇을 뺄지
모르며, 한 번 틀어진 합계는 복원할 방법이 없다.

| | |
| --- | --- |
| 정렬 기준 | `distinct_user_count`. occurrence로 세면 모노레포 하나가 순위를 지배한다 |
| 후보 키 | `(ecosystem, coordinate)`. scope는 키가 아니다 |
| `scope` | 모든 선언이 일치할 때만 값이 있고, 갈리면 `NULL` |
| 거부한 후보 | 계속 세되 기본 목록에서 뺀다. 매주 다시 1위로 올라오면 화면이 무용지물이다 |
| 승격·거부 결정 | 나중에 다시 관찰돼도 덮이지 않는다 |

`scope`가 갈리는 것은 가정이 아니라 관측된 사실이다. spring-petclinic은
`pom.xml`과 `build.gradle`을 둘 다 갖고 있어 `com.h2database:h2`가 한쪽은
`runtime`, 다른 쪽은 `runtimeOnly`다. scope를 키에 넣었을 때 후보가 둘로
갈라지는 것을 실제로 보고 고쳤다.

### 실제로 돌린 결과

spring-petclinic 요청 하나로 끝까지 확인했다.

```
analysis_job       SUCCEEDED / COMPLETED / completed_at 있음
analysis_evidence  97행 · 규칙 10종 · 전부 code_snippet 있음
technology_candidate  10개 (caffeine · h2 · checkstyle · webjars · cache-api ...)
                      8개는 scope NULL — pom.xml 과 build.gradle 이 갈렸다
```

같은 메시지를 다시 발행하니 `Result ignored, job already SUCCEEDED`가 찍히고
Evidence 97행·관찰 10행 그대로였다.


## 검증

```bash
cd AI && python -m pytest tests/test_analysis_results.py -q
```

pydantic 모델과 **커밋된 JSON Schema 양쪽**에 같은 예시를 통과시킨다. 한쪽에만
필드를 추가하면 배포가 아니라 테스트가 깨진다. 직렬화 왕복도 확인한다 — 이쪽에서
필드 이름을 바꾸면 B의 스키마가 거절하는 메시지가 나가는데, 그건 운영에서야
드러난다.

BE 쪽은 `RepositoryAnalysisResultEventTest`가 같은 규칙을 검증한다.

## 아직 하지 않은 것

1. **관리자 화면** — 후보 목록 조회·승격·거부. 집계와 `topCandidates`는 있고
   HTTP API와 UI가 없다
2. **승격이 DRAFT 버전을 거치는 흐름** — V5가 만든 수명 주기를 쓴다. 승격이
   `CURRENT`에 바로 INSERT하면 과거 분석의 근거가 소급해서 바뀐다
3. **진행률 이벤트** — `COLLECTING`/`ANALYZING` 중간 상태. 완료 이벤트 하나로
   시작했고, 필요해지면 별도 이벤트로 추가한다
4. **본인 기여 판정(L2)** — commit author 대조가 필요한데 `--depth 1`에는
   히스토리가 없다
