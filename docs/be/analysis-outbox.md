# 저장소 분석 Transactional Outbox

`AnalysisRequestService.enqueueAuthorized(userId, payload, traceId)`가 기존 단일
저장소 `analysis_job`과 `analysis_outbox`를 같은 DB 트랜잭션에 저장한다.
둘 중 하나가 실패하면 둘 다 롤백한다. 이 서비스는 Kafka를 호출하지 않는다.
커밋된 `analysis_outbox` 행을 Kafka로 옮기는 일은 Debezium CDC가 담당한다.
호출자는 GitHub 권한·브랜치 검증을 마치고 서버가 생성한 분석 ID를 전달해야 한다.
공개 Controller/GitHub 권한 조회 구현은 아직 없으며 이 변경은 그 서비스 연결 경계다.

## API 서비스에서 연결

```java
// 사용자 권한, 저장소, 브랜치를 검증하고 요청 당시 SHA를 조회한 뒤:
var payload = new RepositoryAnalysisRequestPayload(
        analysisId, analysisRepositoryId, githubRepositoryId,
        repositoryFullName, branchName, commitSha,
        RepositoryAnalysisMode.SNAPSHOT, registryVersion);
var event = analysisRequestService.enqueueAuthorized(userId, payload, traceId);
// DB 트랜잭션 커밋 성공 후 202 Accepted + analysisId를 반환한다.
// 여기에서 producer.publish()를 추가로 호출하지 않는다.
```

현재 `commit_sha` 필수 계약을 유지한다. Worker가 clone 후 SHA를 확정하는 방식은
별도 계약 변경이다. DB 스키마가 단일 저장소 Job이므로 여러 저장소를 요청하면
각각 별도 analysis_id를 사용해야 한다. `analysis_job.repository_id`에는 GitHub
숫자 ID를 문자열로 저장하고, 저장소 이름 및 Registry 버전 등은 이벤트에 보존한다.

## 영속화 경계: JPA와 JDBC

한 트랜잭션 안에서 두 방식을 함께 쓴다. 경계와 이유는 다음과 같다.

| 대상 | 방식 | 이유 |
| --- | --- | --- |
| `analysis_job` | JPA (`AnalysisJobRepository`) | 도메인 테이블. `User`와 같은 규약을 따른다 |
| `analysis_outbox` | `JdbcTemplate` (`AnalysisOutboxStore`) | 인프라 테이블. `FOR UPDATE SKIP LOCKED`가 필요하고, 생명주기·연관관계가 없어 영속성 컨텍스트가 이득이 없다. CDC 모드에서는 Debezium이 WAL에서 읽으므로 애플리케이션이 다시 읽지도 않는다 |

**섞어 쓸 때의 함정.** JPA는 INSERT를 flush 시점(기본은 커밋)까지 미루고 `JdbcTemplate`은
즉시 쓴다. `analysis_outbox.analysis_id`가 `analysis_job`을 참조하므로, 그냥 `save()`를
쓰면 부모 행이 아직 없는 상태에서 Outbox 행이 먼저 들어가 FK 위반이 난다. 그래서
`AnalysisRequestService`는 `saveAndFlush()`로 Job INSERT를 먼저 DB에 보낸다.
두 쓰기는 여전히 같은 트랜잭션이라 함께 롤백된다.

이 모듈에 JDBC 쓰기를 추가할 때는 같은 규칙을 지킨다. 선행하는 JPA 쓰기가 있으면
JDBC를 호출하기 전에 flush한다.

`AnalysisJob`은 `Persistable<String>`을 구현한다. `analysis_id`가 서버 지정 ID라서
이게 없으면 Spring Data가 매번 detached로 보고 `merge()`를 호출해 INSERT마다 SELECT가
한 번 더 나간다.

`status`와 `current_stage`는 enum이 아니라 문자열이다. Python Worker도 이 값을 쓰는데,
Worker가 보내는 값을 enum이 다 포함하지 못하면 조회 시점에 터진다. 계약이 확정되면 좁힌다.

## 발행 방식

`gitjob.analysis.outbox.mode`(`ANALYSIS_OUTBOX_MODE`)가 누가 Kafka에 발행하는지를 정한다.

| mode | 발행 주체 | 백엔드 Kafka Producer | 비고 |
| --- | --- | --- | --- |
| `CDC` (기본) | Debezium Connect | 만들지 않음 | Debezium 없이는 이벤트가 `PENDING`으로 쌓인다 |
| `POLLING` | 백엔드 스케줄러 | 사용 | Debezium 장애 시 되돌아갈 경로 |

두 경로는 같은 행을 읽으므로 절대 동시에 켜지 않는다. `CDC` 모드에서는
`AnalysisOutboxPollingConfiguration`이 로드되지 않아 `ANALYSIS_OUTBOX_ENABLED=true`여도
스케줄러와 Producer 빈이 생성되지 않는다. 이 플래그는 `POLLING` 모드 전용 스위치다.

`POLLING`으로 되돌릴 때는 먼저 커넥터를 멈추고(`DELETE /connectors/analysis-outbox`,
필요하면 `SELECT pg_drop_replication_slot('gitjob_analysis_outbox')`) 백엔드를 재시작한다.
반대로 `CDC`로 돌아올 때는 `ANALYSIS_OUTBOX_MODE=CDC`로 재시작해 스케줄러를 먼저 끈 뒤
커넥터를 등록한다. CDC 스냅샷은 `PENDING` 행만 읽으므로 `POLLING`이 이미
`PUBLISHED`로 바꾼 행은 다시 발행되지 않는다.

## 배포 전 SQL

스키마는 Flyway가 애플리케이션 기동 시 적용한다. Spring Boot가 Flyway를 Hibernate보다
먼저 실행하므로, `validate`가 도는 시점에는 스키마가 이미 있다. 손으로 넣을 SQL은
아래 한 파일뿐이다.

| 파일 | 적용 |
| --- | --- |
| `db/migration/V1__baseline_schema.sql` | Flyway 자동. 스키마 전체(테이블 14개) |
| `db/migration/V2__cdc_heartbeat.sql` | Flyway 자동. CDC heartbeat 테이블 |
| `db/cdc/cdc_prerequisites.sql` | **수동 1회.** CDC 모드에 필요한 롤·GRANT·publication |

`cdc_prerequisites.sql`만 `db/migration` 밖에 둔 이유는 세 가지다. 비밀번호를 치환해
넣어야 하고, `CREATE ROLE`은 스키마 변경이 아니라 클러스터 레벨 객체이며,
`CREATE ROLE`과 `CREATE PUBLICATION`은 재실행할 수 없다. 마이그레이션으로 만들면 한 번
실패한 뒤로 애플리케이션이 아예 기동하지 못한다.

이 파일의 `__CDC_PASSWORD__`, `__DATABASE_NAME__`를 치환해서 적용한다. 비밀번호는
`.env`의 `CDC_DATABASE_PASSWORD`와 같아야 하고, 애플리케이션 DB 비밀번호와는 다른 값을 쓴다.

Flyway 도입 전에는 `db/init.sql`을 사람이 넣어야 했고, 그래서 환경이 어긋났다. 운영 DB는
엔티티가 analysis 테이블을 기대하는 동안 계속 비어 있었다.

`CREATE PUBLICATION`은 `wal_level`이 `logical`이 아니어도 경고만 내고 성공한다.
따라서 SQL이 다 통과해도 CDC 준비가 끝난 것은 아니다. 커넥터 등록 전에 확인한다.

Kafka 자동 토픽 생성은 꺼져 있다. Connect worker가 `topic.creation.default.*`로
대상 토픽(파티션 3, RF 1)과 heartbeat 토픽을 만들 수 있지만, 파티션 수를 직접
정하려면 `gitjob.repository-analysis.requests.v1`을 먼저 만들어 둔다.

## CDC 발행 흐름 (기본)

```
AnalysisRequestService  --COMMIT-->  analysis_job + analysis_outbox
                                            |
                                     PostgreSQL WAL (wal_level=logical)
                                            |
                        Debezium PostgresConnector (slot gitjob_analysis_outbox)
                                            |
                                  EventRouter SMT (outbox)
                                            |
                            gitjob.repository-analysis.requests.v1
```

커넥터 정의는 `Infra/cdc/connector.json` 하나이며 테스트도 이 파일을 그대로 읽는다.
`__DATABASE_HOST__`, `__DATABASE_PORT__`, `__DATABASE_NAME__`만 등록 시점에 치환한다.
비밀번호는 `${env:CDC_DATABASE_PASSWORD}` 참조라서 Kafka에 저장되는 커넥터 설정과
`GET /connectors/.../config` 응답에는 평문 비밀번호가 남지 않는다.

Kafka 레코드는 Outbox 행에서 이렇게 만들어진다.

| Kafka | 출처 | 설명 |
| --- | --- | --- |
| topic | `topic` 컬럼 | 저장 당시의 목적지를 그대로 쓴다. 설정을 바꿔도 과거 행은 원래 토픽으로 간다 |
| key | `analysis_repository_id` | 한 저장소의 요청은 같은 파티션에 남아 순서가 보장된다 |
| value | `event_json` | 애플리케이션이 직렬화한 JSON 원문 |
| header `id` | `event_id` | Consumer 멱등 키 |

key/value/header 모두 `StringConverter`를 쓴다. 그래서 Connect 스키마 envelope도,
JSON 문자열을 다시 감싸는 이중 인코딩도 없이 `event_json`이 바이트 그대로 전달된다.
Debezium은 이벤트를 새로 만들지 않고 이미 커밋된 JSON을 옮기기만 하므로
`docs/data/contracts/repository-analysis-request-v1.schema.json` 계약은 그대로다.

커넥터는 `skipped.operations=u,d,t`로 INSERT(스냅샷 read 포함)만 라우팅한다.
Outbox 행을 나중에 UPDATE/DELETE 해도 재발행되지 않고, `tombstones.on.delete=false`라
tombstone도 나가지 않는다.

첫 기동 스냅샷은 `snapshot.select.statement.overrides`로 두 조건을 건다.

```sql
WHERE status = 'PENDING' AND created_at > now() - interval '7 days'
```

`status` 조건은 `POLLING` 시절에 이미 `PUBLISHED`/`FAILED`가 된 행을 거른다.
`created_at` 조건은 **재발행 폭발을 막는다.** CDC 모드에서는 아무도 행을 `PUBLISHED`로
바꾸지 않으므로 모든 행이 영구히 `PENDING`이고, 시간 경계가 없으면 슬롯을 삭제하고
재등록할 때마다 **그때까지 누적된 전체**가 한꺼번에 다시 나간다. 6개월 뒤에는 6개월치다.
7일은 Kafka retention(168시간)과 맞춘 값이다. 그보다 오래된 요청은 브랜치가 이미
움직였을 가능성이 높아 재발행보다 재요청이 맞다.

`errors.tolerance=none`이라 변환/직렬화 오류를 만나면 이벤트를 버리지 않고 태스크가
FAILED로 멈춘다. Outbox 행은 DB에 남아 있으므로 원인을 고치고 재시작하면 이어서
발행된다. 조용히 유실되는 것보다 멈추는 편이 안전하다는 선택이다.

`analysis_outbox`는 오래 비어 있을 수 있다. 캡처 대상 테이블에 WAL이 없으면 Debezium이
슬롯 LSN을 확정하지 못해 WAL이 계속 쌓이므로, 10초마다 `cdc_heartbeat`를 UPDATE하는
`heartbeat.action.query`를 두고 publication에 그 테이블을 포함시킨다.

`CDC` 모드에서 Outbox의 `status`는 백엔드가 갱신하지 않는다. 정상 행은 계속
`PENDING`, `attempts=0`, `published_at IS NULL`로 남는다. 실제 발행 여부는 DB가 아니라
커넥터 offset과 Kafka에서 확인한다.

전달 보장은 여전히 at-least-once다. Connect가 offset을 flush하기 전에 죽으면 같은
`event_id`가 다시 나갈 수 있으므로 Consumer는 `event_id`/`analysis_repository_id`로
멱등 처리해야 한다.

### 등록

`wal_level=logical`은 재시작해야 적용되므로 postgres 컨테이너가 새로 떠야 한다.
`compose.yaml`의 `command`가 바뀌었으니 `up.sh`가 알아서 재생성하며, 데이터 볼륨은 유지된다.

```bash
# 1) core 프로필로 postgres/kafka/kafka-connect 기동
PROFILES=core ./Infra/scripts/up.sh

# 2) 백엔드를 띄운다. 스키마는 이때 Flyway가 적용하므로 넣을 SQL이 없다.
#    3)의 GRANT와 publication이 analysis_outbox/cdc_heartbeat를 참조하므로
#    이 단계를 건너뛰면 3)이 "relation does not exist"로 실패한다.
PROFILES=core,app ./Infra/scripts/up.sh

# 3) CDC 객체 적용. 치환이 필요한 것은 이 파일뿐이다
source .env.wsl && sed -e "s/__CDC_PASSWORD__/$CDC_DATABASE_PASSWORD/" -e "s/__DATABASE_NAME__/$POSTGRES_DB/" BE/src/main/resources/db/cdc/cdc_prerequisites.sql | docker compose --project-directory . --env-file .env.wsl -f Infra/compose/compose.yaml -f Infra/compose/compose.wsl.yaml --profile core exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"

# 4) 커넥터 등록 (재실행해도 안전하다)
./Infra/scripts/cdc-register.sh
```

`ON_ERROR_STOP=1`이 없으면 중간에 실패해도 계속 진행돼 반쯤 적용된 DB가 남는다.

**SQL을 백엔드보다 먼저 적용한다.** 모든 환경이 `JPA_DDL_AUTO=validate`이므로 스키마가
없거나 엔티티와 어긋나면 백엔드가 아예 기동하지 않는다. 절반만 만들어진 DB를 안고
운영되는 것보다 낫기 때문에 의도한 동작이며, 순서를 지키면 마주칠 일이 없다.
`SchemaValidationTest`가 이 정합성을 미리 확인해 준다.

`cdc-register.sh`는 `PUT /connectors/<name>/config`를 사용한다. 이미 등록된 커넥터에
다시 실행해도 replication slot과 source offset이 유지되어 재발행이 일어나지 않는다.

## POLLING 발행 흐름 (롤백 경로)

기본 10초 초기 지연 후 2초 간격으로 최대 20건을 처리한다. 각 이벤트는 별도
트랜잭션에서 `FOR UPDATE SKIP LOCKED`로 잠근다. 다른 서버는 이미 잠긴 행을 건너뛴다.
Kafka ACK를 기다린 뒤에만 `PUBLISHED`로 갱신한다. 분석 Job은 여전히 `QUEUED`이며
분석 상태 전이는 추후 Worker 결과 Consumer가 담당한다.

현재 구현은 Kafka 전송 중 DB 연결과 행 잠금을 유지하는 단순한 relay다.
Producer `max.block.ms=5000`, `delivery.timeout.ms=10000`, relay ACK timeout 기본
10초로 대기를 제한한다. 따라서 한 건의 전송은 최대 약 15초까지 DB 연결을 점유할 수 있다.
대규모 처리량이 필요하면 짧은 claim 트랜잭션과 lease/fencing 방식으로 확장한다.

실패 시 같은 event_id, 생성 시각, payload, 토픽을 재사용하며
5초 → 10초 → 20초 … 최대 5분 지수 backoff를 적용한다.
10회 실패하면 Outbox를 `FAILED`로 보존한다. 잘못된 JSON/계약은 즉시 `FAILED`다.
원문 예외나 토큰을 Outbox에 저장하지 않고 고정 오류 코드만 남긴다.
종료 인터럽트/DB 오류는 트랜잭션을 롤백하여 다음 poll에서 복구한다.

Kafka ACK 직후 DB 커밋 전에 죽거나 ACK가 지연되면 중복 발행할 수 있다.
Exactly-once가 아니므로 Worker 및 결과 저장에서는 event_id/analysis_repository_id로
멱등 처리해야 한다. Kafka Producer의 enable.idempotence만으로 해결되지 않는다.

## 운영 확인 및 복구 (CDC)

```bash
# 커넥터/태스크 상태. RUNNING이 아니면 trace에 원인이 담긴다.
curl -s localhost:8084/connectors/analysis-outbox/status
# 어디까지 읽었는지
curl -s localhost:8084/connectors/analysis-outbox/offsets
# 일시 중지한 태스크 재개
curl -s -X POST localhost:8084/connectors/analysis-outbox/restart?includeTasks=true
```

```sql
-- 슬롯이 살아 있는지와 아직 확정되지 않은 WAL 크기.
-- active=false로 오래 남으면 WAL이 계속 쌓여 디스크를 채운다.
SELECT slot_name, active, confirmed_flush_lsn,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS retained
FROM pg_replication_slots WHERE slot_name = 'gitjob_analysis_outbox';

-- heartbeat가 도는지. 10초 간격이라 now()와 크게 벌어지면 안 된다.
SELECT updated_at FROM cdc_heartbeat WHERE id = 1;
```

커넥터를 오래 내려둘 때는 슬롯을 반드시 삭제한다. 슬롯을 남긴 채 방치하면
PostgreSQL이 WAL을 계속 보관해 디스크가 찬다.

```sql
SELECT pg_drop_replication_slot('gitjob_analysis_outbox');
```

슬롯을 삭제하면 그 사이 커밋된 WAL은 사라진다. 다시 등록하면 `snapshot.mode=initial`이
최근 7일치 `PENDING` 행을 다시 스냅샷한다. 아직 발행되지 않은 행은 이렇게 회복되지만,
**이미 Kafka로 나간 행도 함께 재발행된다.** Consumer 멱등성이 이를 흡수한다.

### 재등록 전에 확인할 것

재발행 규모는 최근 7일치 `PENDING` 행 수와 같다. 재등록 전에 세어 본다.

```sql
SELECT count(*) FROM analysis_outbox
WHERE status = 'PENDING' AND created_at > now() - interval '7 days';
```

이 값이 감당하기 어려우면 오래된 행을 먼저 아카이브한다. CDC 모드에서는 상태가 계속
`PENDING`이므로 **보존 정책이 선택 사항이 아니라 재등록을 안전하게 만드는 전제다.**
발행 여부는 DB가 아니라 커넥터 offset으로 판단해야 하므로, 아카이브 기준은 상태가
아니라 나이로 잡는다.

```sql
-- 예: 30일 지난 행을 아카이브 테이블로 옮긴다. 기준일은 운영에서 정한다.
CREATE TABLE IF NOT EXISTS analysis_outbox_archive (LIKE analysis_outbox INCLUDING ALL);
WITH moved AS (
    DELETE FROM analysis_outbox
    WHERE created_at < now() - interval '30 days'
    RETURNING *
)
INSERT INTO analysis_outbox_archive SELECT * FROM moved;
```

DELETE는 `skipped.operations`에 걸려 Kafka로 나가지 않는다. 다만 `analysis_job`을
참조하는 FK가 있으므로 Job을 먼저 지우면 안 된다.

### 특정 이벤트만 재발행

Outbox 행을 UPDATE하지 않는다. `skipped.operations`에 걸려 무시된다. 같은 `event_json`을
**새 `event_id`로 다시 INSERT**한다.

```sql
INSERT INTO analysis_outbox
    (event_id, analysis_id, analysis_repository_id, topic, event_json,
     status, attempts, created_at, next_attempt_at)
SELECT 'ev_' || gen_random_uuid(), analysis_id, analysis_repository_id, topic, event_json,
       'PENDING', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM analysis_outbox WHERE event_id = :event_id;
```

`analysis_repository_id`는 **그대로 둔다.** 이 값이 Kafka 키라서, 재발행 이벤트가 원본과
같은 파티션에 원본 뒤로 붙는다. 예전에는 이 컬럼에 UNIQUE 제약이 있어 이 절차가
제약 위반으로 실패했다. 제약은 `003_analysis_outbox_drop_repository_unique.sql`에서
제거했다 — 요청마다 새 UUID를 쓰는 구조라 실제로 걸린 적이 없으면서 유일한 복구
경로만 막고 있었다. Outbox 행의 유일성은 `event_id` 기본키가 계속 보장한다.

## 운영 확인 및 복구 (POLLING)

아래 상태 컬럼은 `POLLING` 모드에서만 갱신된다.

```sql
SELECT status, count(*) FROM analysis_outbox GROUP BY status;
SELECT event_id, analysis_id, attempts, last_error_code, next_attempt_at
FROM analysis_outbox WHERE status = 'FAILED' ORDER BY created_at;
```

발행 중단 상태는 Outbox의 FAILED이며 분석 실패 확정이 아니다. timeout 시 이미
전달됐을 수도 있어 analysis_job을 임의로 FAILED로 바꾸지 않는다. 운영 모니터링은
FAILED 건수 및 오래된 PENDING을 확인해야 한다. 알림/운영 API는 별도 연결 사항이다.

원인을 해결한 후 지정한 이벤트만 재발행한다. 실제 ID로 매개변수를 바인딩한다.

```sql
UPDATE analysis_outbox
SET status = 'PENDING', attempts = 0, next_attempt_at = CURRENT_TIMESTAMP,
    last_error_code = NULL
WHERE event_id = :event_id AND status = 'FAILED';
```

성공한 이벤트는 자동 삭제하지 않는다. 보존 기간/삭제 정책은 운영에서 정해야 한다.
`ANALYSIS_OUTBOX_ENABLED=false`는 scheduler만 중단하며 enqueue는 계속 DB에 저장한다.

## 검증

```powershell
# Docker Desktop이 떠 있으면 CDC 파이프라인과 스키마 정합성까지 함께 검증된다.
# 없으면 그 둘만 자동으로 건너뛰고 나머지는 그대로 돈다. 켜고 끌 플래그가 없다.
.\gradlew.bat test

# 특정 묶음만:
.\gradlew.bat test --tests 'com.example.git_job.analysis.*'
.\gradlew.bat test --rerun-tasks --tests '*CdcIntegrationTest'
.\gradlew.bat test --rerun-tasks --tests '*SchemaValidationTest'

# Docker가 있어도 느린 컨테이너 테스트를 건너뛰고 싶을 때.
$env:DOCKER_TESTS = 'false'

# Outbox 테스트는 기본이 H2다. 같은 테스트를 실제 PostgreSQL에서도 돌려 본다.
$env:OUTBOX_TEST_DATABASE = 'postgres'
try {
    .\gradlew.bat test --rerun-tasks --tests '*AnalysisOutboxIntegrationTest'
} finally {
    Remove-Item Env:OUTBOX_TEST_DATABASE
}
```

기본 테스트는 H2 PostgreSQL 호환 모드다. PostgreSQL 실행은 Testcontainers가
임시 postgres:16-alpine 컨테이너를 생성·정리하며 운영 DB를 사용하지 않는다.
Kafka Producer는 테스트 더블로 ACK·실패·timeout을 제어한다.

`AnalysisOutboxCdcIntegrationTest`와 `SchemaValidationTest`는 Docker 유무로 실행이
갈린다(`DockerAvailable#check`). 환경변수 플래그를 쓰지 않는 이유는, 플래그를 잊으면
CDC 파이프라인과 스키마 정합성이 검증되지 않은 채 빌드가 초록색으로 끝나기 때문이다.
CDC 테스트는 임시 네트워크에 PostgreSQL/Kafka/Debezium Connect를 띄우고
`Infra/cdc/connector.json`과 `002_analysis_outbox_cdc.sql`을 주소·비밀번호만 바꿔
그대로 적용한다. 검증 대상: 스냅샷이 `PENDING`만 재생하는지, 롤백된 트랜잭션이
Kafka에 도달하지 않는지, Kafka 계약(topic/key/JSON 원문/`id` 헤더)이 유지되는지,
Connect worker를 교체해도 저장된 설정과 offset으로 이어서 발행하는지.

검증 대상: 트랜잭션 원자성/외부 롤백, JSON 보존, ACK 이후 상태 변경, 중복 poll,
비동기·동기 전송 실패, backoff/횟수 제한, 잘못된 이벤트, ACK 후 DB 실패,
복수 relay의 잠금 경합 및 롤백 복구.

2026-09-07 검증: 기존 이벤트/Producer와 H2 Outbox 테스트 총 23개 통과,
동일 Outbox 테스트 11개를 실제 PostgreSQL 16 임시 컨테이너에서도 통과했다.
전체 애플리케이션 contextLoads의 기존 JWT 런타임 의존성 문제는 별도 항목이다.

2026-09-08 검증: analysis 패키지 26개 전부 통과(CDC 포함).
그중 CDC 3개는 PostgreSQL 16.4 + Kafka 4.0.0 + Debezium Connect 3.4.3 컨테이너에서
실제 왕복을 검증했다.

같은 날 스키마를 임시 PostgreSQL 16.4 컨테이너에서 단독 실행해 테이블 14개와
`idx_analysis_outbox_pending`이 오류 없이 생성되는 것을 확인했고, 이어서 CDC 객체도 같은
DB에 적용되는 것을 확인했다. 이때 `CREATE PUBLICATION`이 `wal_level` 경고만 남기고
성공하는 것도 함께 관찰했다.

2026-09-08 Flyway 전환 검증(S15P21E102-172): 빈 데이터베이스에 애플리케이션을 띄워
`flyway_schema_history`에 V1·V2가 `success`로 남고 테이블 16개가 생성되며 `validate`가
통과하는 것을 확인했다. 같은 커밋에서 테스트 109개 전부 통과(건너뜀 0)했고, 그중 CDC 3개는
새 `db/cdc/cdc_prerequisites.sql` 경로로 Debezium 왕복까지 확인했다.
`DatabaseScriptConsistencyTest`는 Docker 없이 항상 돌며, `uq_analysis_job_active`의 상태
목록이 `AnalysisJob.IN_PROGRESS_STATUSES`와 어긋나지 않았는지 확인한다.

같은 날 `analysis_job`을 JPA 엔티티로 전환한 뒤 26개 재실행해 전부 통과했다.
CDC 테스트와 `OUTBOX_TEST_DATABASE=postgres` 실행은 EntityManagerFactory를
`hibernate.hbm2ddl.auto=validate`로 띄우므로, `AnalysisJob` 매핑이 배포용
마이그레이션이 만든 스키마와 일치하는지도 함께 검증된다. H2 실행은 스키마가 근사치라 `none`이다.

참고: [Debezium PostgreSQL connector](https://debezium.io/documentation/reference/stable/connectors/postgresql.html),
[Debezium Outbox Event Router](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html),
[PostgreSQL SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html),
[Spring TransactionTemplate](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/support/TransactionTemplate.html).
