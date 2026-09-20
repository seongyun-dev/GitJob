# 공고 검색 Projection 배포·롤백 runbook

- Jira: `S15P21E102-360`
- schema: `c_compute` migration 7
- 기본 안전 상태: demand `legacy`, personalized matching `legacy`
- 운영 수치의 Source of Truth: 동일 데이터·selector로 실행한 명령 출력과 관측 시스템

이 문서는 명령을 실행했다고 간주하지 않는다. 각 gate의 실제 출력, 시각, 이미지 SHA,
Projection ID를 배포 기록에 붙여야 다음 단계로 넘어갈 수 있다. 비밀 값과 DSN은 기록하지
않는다.

## 1. 배포 전 gate

1. PostgreSQL backup 위치와 restore 담당자·명령을 운영 기록에 적는다.
2. DB와 서비스 호스트 디스크 사용률을 기록한다. 예상 dual-write까지 포함해 90%를 넘으면
   중단한다.
3. 배포할 Worker 이미지 SHA를 고정한다. 이미지에는 migration 001~007이 모두 있어야 한다.
4. `.env.data` 또는 실제 Worker 환경은 아래 기본값으로 시작한다.

```dotenv
C_JOB_DEMAND_PROJECTION_MODE=legacy
C_JOB_DEMAND_PROJECTION_FALLBACK=false
C_JOB_DEMAND_PROJECTION_SHADOW_RATE=0.01
C_JOB_DEMAND_PROJECTION_SHADOW_QUEUE=4
C_JOB_MATCHING_ACTIVE_MODE=legacy
```

운영 명령은 data 서버의 저장소 root에서 실행한다. 현재 2-host
HDFS/Spark topology와 같은 Compose project를 선택하도록 아래 배열을 한 번만
정의하고, 이후의 모든 `${COMPOSE[@]}` 명령에 동일하게 사용한다.

```bash
cd /opt/gitjob
COMPOSE=(docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2-data-cluster.yaml \
  --profile data)
"${COMPOSE[@]}" config --quiet
```

격리 PostgreSQL 검증은 운영 DB가 아닌 빈 테스트 DB에서 먼저 수행한다.

```powershell
$env:C_COMPUTE_TEST_DATABASE_URL = '<isolated-test-dsn>'
Set-Location AI
& .\.venv\Scripts\python.exe -m pytest tests/test_compute_store.py `
  tests/test_compute_matching.py tests/test_job_projection_store.py -q
```

## 2. migration 005~007

Worker 런타임보다 migration을 먼저 적용한다. `C_COMPUTE_DATABASE_URL`은 대상 DB를
명시해야 하며 명령 출력에 값을 표시하지 않는다.

```bash
"${COMPOSE[@]}" run --rm -e C_COMPUTE_DATABASE_URL worker \
  python -m worker.migrate
"${COMPOSE[@]}" run --rm -e C_COMPUTE_DATABASE_URL worker python -c \
  "from worker.api import configured_database_url; from worker.store import ComputeStore; import sys; sys.exit(0 if ComputeStore(configured_database_url()).ready() else 1)"
```

명령을 실행하는 셸에는 비밀 저장소에서 읽은 `C_COMPUTE_DATABASE_URL`이 설정되어 있어야 한다.
Compose의 `POSTGRES_*` 기본값으로 migration 대상을 추정하지 않는다.

006~007은 한 migration transaction에서 `user_result`, `user_result_head`,
`matching_source`, `matching_calculation`, `matching_job`, `job_projection_head`에 DDL lock을
잡고, 기존 fact source를 신규 테이블로 backfill한 뒤 FK를 검증한다.
적용 전에 장기 transaction과 대기 lock이 없는지 확인하고, 트래픽이 낮은 시간에 실행한다.
`lock_timeout=5s`에 걸리면 재시도 루프를 돌리지 말고 blocker transaction을 조사한다.
기존 006 적용 DB의 `user_result_head.updated_at/result_id`가 null이 아닌지도 먼저 확인한다.

```sql
SELECT count(*) AS user_result_head_rows,
       pg_size_pretty(pg_total_relation_size('c_compute.user_result_head')) AS head_size,
       (SELECT count(*) FROM c_compute.matching_job) AS matching_job_rows,
       pg_size_pretty(pg_total_relation_size('c_compute.matching_job')) AS matching_size,
       (SELECT count(*) FROM c_compute.matching_source) AS matching_source_rows,
       pg_size_pretty(pg_total_relation_size('c_compute.matching_source')) AS source_size;
SELECT pid, now() - xact_start AS transaction_age, wait_event_type, wait_event
FROM pg_stat_activity
WHERE datname = current_database() AND xact_start IS NOT NULL
ORDER BY xact_start;
SELECT locktype, relation::regclass, mode, granted, pid
FROM pg_locks
WHERE relation IN ('c_compute.user_result'::regclass,
                   'c_compute.user_result_head'::regclass,
                   'c_compute.matching_source'::regclass,
                   'c_compute.matching_calculation'::regclass,
                   'c_compute.matching_job'::regclass,
                   'c_compute.job_projection_head'::regclass)
ORDER BY relation, granted, pid;
```

행 수·relation size로 maintenance window를 정하고, 장기 transaction이나 미승인 대기 lock이
있으면 007 적용을 시작하지 않는다.

DB에서 `c_compute.schema_version`이 1~7을 한 번씩 가지는지 확인한다. 기존 checksum 불일치,
15초 statement timeout, lock timeout이 발생하면 배포를 중단하고 원인을 조사한다. 적용된
SQL을 수정하거나 version 행을 수동으로 덮어쓰지 않는다.

## 3. backfill과 publish

자동 intake와 동일한 검증 입력·Registry를 사용한다. dry-run은 DB를 쓰지 않는다.

```bash
"${COMPOSE[@]}" run --rm -e C_COMPUTE_DATABASE_URL worker \
  python -m worker.job_projection_backfill --dry-run
"${COMPOSE[@]}" run --rm -e C_COMPUTE_DATABASE_URL worker \
  python -m worker.job_projection_shadow
```

dry-run의 `projection_version_id`, job/fact/source count와 100 selector 결과를 보관한다.
`mismatch_count`가 0이 아니면 publish하거나 flag를 바꾸지 않는다. `CURRENT_MARKET`의
CLOSED/deadline 차이는 v4 정책 결과와 fixture로 설명되지 않으면 실패로 취급한다.

```bash
"${COMPOSE[@]}" run --rm -e C_COMPUTE_DATABASE_URL worker \
  python -m worker.job_projection_backfill --publish
"${COMPOSE[@]}" exec -T worker sh -c \
  'curl -fsS -H "Authorization: Bearer $C_COMPUTE_TOKEN" http://127.0.0.1:8080/ready'
"${COMPOSE[@]}" exec -T worker sh -c \
  'curl -fsS -H "Authorization: Bearer $C_COMPUTE_TOKEN" http://127.0.0.1:8080/internal/v1/c/intake/status'
```

`/ready`의 `job_projection.status=READY`, stored/job count 일치, missing fact 0을 확인한다.
로그에서 version, build/publish duration, fact inserted/reused, source 상태, active/closed/
unknown/deadline-expired 수를 기록한다. source 일부가 실패 또는 partial이면 publish 입력으로
승격하지 않는다.

## 4. 단계 활성화

각 단계는 Worker 재시작 후 `/ready`와 대표 selector를 다시 확인한다.

환경 변수만 바꾼 뒤 `docker compose restart`를 사용하면 기존 container 환경이 유지된다.
각 flag 변경은 env 파일 반영 후 아래처럼 Worker container를 재생성하고, 새 container에서
실제 환경 값과 `/ready`를 확인한다.

```bash
"${COMPOSE[@]}" up -d --no-deps --force-recreate worker
"${COMPOSE[@]}" exec -T worker sh -c \
  'env | grep -E "^C_JOB_(DEMAND_PROJECTION|MATCHING_ACTIVE)_"'
```

1. `C_JOB_DEMAND_PROJECTION_MODE=shadow`: legacy 응답 유지, bounded 1% 비교.
2. offline 100 selector와 운영 shadow에서 비의도 mismatch 0 확인.
3. `C_JOB_DEMAND_PROJECTION_MODE=projection`: 내부 트래픽부터 활성화.
4. cold/warm 성능·오류율을 gate와 비교한 뒤 전체 활성화.
5. 24시간 정상 관측 뒤 `C_JOB_MATCHING_ACTIVE_MODE=projection` 활성화.

matching mode가 켜지면 resolve의 compute version에 Projection ID가 포함된다. 기존 결과는
STALE이어도 활성 공고만 제공하며, BE scheduler가 새 identity 계산을 요청한다. 새 결과의
모든 child와 `user_result`가 저장된 transaction에서만 target head가 교체된다.

## 5. 성능과 계약 검증

동일 input union과 동일 selector 목록을 사용한다. Worker 재시작 직후 첫 요청, exact selector
10회, 100 selector를 각각 측정한다. 기록할 값은 C endpoint p50/p95/max, BE p50/p95/max,
Projection SQL 실행/버퍼, RSS peak, Snapshot INSERT 수/bytes, 오류·fallback·mismatch율이다.

인수 gate:

- Projection DB p95 100ms 이하
- C cold p95 300ms 이하, max 1초 이하
- BE cold p95 500ms 이하
- Preview COHORT/DEMAND Snapshot INSERT 0
- 비의도 ID/count mismatch 0
- restart 후 warm cache 없이 같은 목표 충족

SQL은 운영과 같은 분포의 staging/복제본에서 `EXPLAIN (ANALYZE, BUFFERS)`로 실행한다.
운영 DB에 부하 테스트나 테스트 migration을 실행하지 않는다. 이 저장소에서 실제 측정하지
않은 수치는 배포 기록에 성공으로 쓰지 않는다.

## 6. 롤백

응답 오류, mismatch, p95 1초 초과, incomplete 수집으로 대량 소멸, 디스크 90% 예상 중 하나면
즉시 다음 순서로 롤백한다.

1. `C_JOB_MATCHING_ACTIVE_MODE=legacy`
2. `C_JOB_DEMAND_PROJECTION_MODE=legacy`
3. Worker 재생성 후 `/ready`, legacy preview, 추천·매칭·What-if 확인
4. 실패 version은 감사·차단 행과 함께 보존하고 신규 테이블을 삭제하지 않음

head 자체가 잘못됐고 이전 PUBLISHED version으로 돌려야 할 때만 아래 전용 명령을 사용한다.
현재 head를 `--expected-current`로 다시 확인하는 CAS, 대상의 state/job count/missing fact
검증, 실패 version 차단, 감사 행 기록이 한 transaction에서 수행된다. 직접 UPDATE는 금지한다.

```bash
"${COMPOSE[@]}" run --rm -e C_COMPUTE_DATABASE_URL worker \
  python -m worker.job_projection_head \
  --expected-current "$FAILED_PROJECTION_ID" \
  --to "$PREVIOUS_PROJECTION_ID" \
  --actor "$OPERATOR_ID" \
  --reason "$INCIDENT_REASON"
```

rollback 뒤 `/ready`와 대표 selector를 확인한다. 차단된 version은 일반 publish로 다시 head가
될 수 없으며, 원인을 수정한 새 input/version을 발행해야 한다.

## 7. retention·GC와 restore

구 COHORT/RECOMMENDATION Snapshot은 이 작업에서 삭제하지 않는다. 다음 audit가 모두 0이고
Projection 7일 정상, fallback 승인 수준, restore rehearsal 성공인 경우에만 별도 maintenance
작업을 만든다.

- `user_c_snapshot`의 구 recommendation/cohort 참조
- `matching_calculation`, `matching_source`, `matching_job` legacy/null fact 참조
- `registry_review`와 cohort fan-out 참조
- current/previous `user_result_head`가 아닌 결과의 보존 기간·복구 필요성

먼저 삭제 후보 ID·행 수·논리 bytes만 출력하는 dry-run을 실행한다. 승인 후에도 대량 DELETE와
`VACUUM FULL`/compaction은 분리한다. OS 디스크 반환을 DELETE 성공으로 추정하지 않는다.
restore rehearsal은 별도 DB에 backup을 복구한 뒤 migration readiness, legacy Snapshot 조회,
Projection head, current/previous user result를 확인한다.
