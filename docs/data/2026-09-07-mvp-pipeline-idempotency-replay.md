# MVP 데이터 파이프라인 멱등성 및 Replay 검증

> 상태: 로컬 코드·Unit Test 기준 검증 완료 / Production 재실행 미수행
>
> 기준일: 2026-09-07
>
> Jira: [S15P21E102-111](https://ssafy.atlassian.net/browse/S15P21E102-111)
>
> 기준 작업트리: `origin/develop@5bdb6965b6bf3065726e4bc434ccd1ab9fa5471e`

## 1. 범위와 판정

이 문서는 현재 MVP에 실제 구현된 Batch·Replay 경계만 고정한다. 준비되지 않은
Serving DB UPSERT, 공통 Clean/Serving sink, 애플리케이션 Kafka Consumer 동작은
구현된 것으로 간주하지 않는다.

| 범위 | 판정 | 현재 보장 |
|---|---|---|
| GH Archive Historical Raw | 충족 | UTC hour별 final object 재사용, byte 검증, 원자적 publish, overwrite 금지 |
| GH Archive Repo Activity Snapshot | 충족 | 고정 입력과 tie-break로 결정적 집계, 기존 output root overwrite 거부 |
| GitHub Repo Snapshot | 충족 | dataset checkpoint 재개와 policy fingerprint + repo ID + pinned SHA cache 재사용 |
| Jobs 로컬 Batch 출력 | 충족 | `(source_site, source_posting_id)`를 업무 키로 사용하고 같은 run 경로는 원자적으로 교체 |
| Jobs 공용 Snapshot/Serving sink | 미구현 | 공용 partition 선택·UPSERT는 이 Jira 범위 밖의 후속 작업 |
| Kafka Replay 도구 | 부분 충족 | NDJSON producer replay와 일회성 producer/consumer smoke만 구현 |
| 애플리케이션 Streaming | 미구현 | Consumer group, offset commit, checkpoint, sink 멱등성, restart 복구가 아직 없음 |

공통 원칙은 Raw와 완료 Snapshot을 불변 결과로 취급하고, checkpoint/state는 완료
결과가 아니라 재개 가능한 실행 상태로만 취급하는 것이다. 다른 dataset, policy,
candidate 집합의 checkpoint를 섞지 않는다.

## 2. GH Archive

### 2.1 Historical Raw

논리 키는 `(source=gharchive, UTC hour)`이며 final 경로는
`/gitjob/raw/gharchive/dt=YYYY-MM-DD/YYYY-MM-DD-H.json.gz`다.

- [`HistoricalDownloader`](../../AI/collector/gharchive/historical.py)는 final gzip이
  이미 유효하면 HTTP 요청 없이 `reused`로 처리한다. checkpoint가 없더라도 final을
  검증한 뒤 checkpoint를 복구한다.
- 완료 checkpoint에는 압축 크기와 SHA-256이 기록된다. final byte가 checkpoint와
  다르면 기존 성공으로 신뢰하지 않는다.
- [`WebHdfsSink`](../../AI/collector/gharchive/sinks.py)는 final 존재 여부를 먼저
  확인하고, 존재하면 압축 해제나 업로드 없이 `reused`로 처리한다.
- 새 파일은 `.uploading-<uuid>`에 `overwrite=false`로 생성한 뒤 rename한다. final을
  덮어쓰지 않으므로 같은 hour를 여러 번 실행해도 HDFS Raw object 수가 늘지 않는다.

따라서 같은 raw/hour replay의 논리 결과는 같은 final byte와 같은 hour 집합이다.
검증 근거는 `test_download_then_rerun_reuses_exact_raw_bytes`,
`test_repeated_store_is_idempotent_across_sink_instances`,
`test_publish_range_reuses_hours_already_in_hdfs`다.

### 2.2 Repo Activity Snapshot/Parquet

[`repo_activity_topn.py`](../../Infra/spark/repo_activity_topn.py)는 repo ID별 집계 후
`activity_count DESC, repo_id ASC` 순서로 `row_number`를 부여한다. 같은 immutable Raw
입력과 같은 코드·인자라면 같은 논리 row와 rank가 나온다.

output root가 이미 존재하면 작업 시작 전에 실패하고, 하위 Parquet도
`errorifexists` 모드로 기록한다. 같은 `snapshot` 경로에 append하거나 overwrite하지
않는다. 다시 계산해야 하면 새 snapshot ID/path를 사용하고, 기존 snapshot은 보존한다.

## 3. GitHub Repo Snapshot

재사용 키는 `RepoFetchPolicy.cache_identity + github_repo_id + pinned_commit_sha`다.
`cache_identity`는 policy label뿐 아니라 모든 유효 fetch policy 값을 직렬화한
SHA-256 fingerprint를 포함한다.

- 같은 dataset의 checkpoint replay: `COMPLETE`, `REUSED`, `NOT_FOUND`, `FAILED` 같은
  terminal repo를 건너뛰고 기존 contract record와 attempts를 그대로 사용한다.
  Repo metadata/tree/raw artifact 요청은 다시 하지 않는다.
- 다른 dataset의 cache reuse: metadata와 default-branch HEAD로 현재 repo ID와 pinned
  SHA를 확인한 뒤 cache key가 같으면 `REUSED`를 반환한다. recursive tree와 raw
  artifact는 다시 fetch하지 않는다.
- SHA 또는 policy fingerprint가 다르면 cache miss이며 새 fetch가 정상 동작이다.
- `RATE_LIMITED` 같은 비-terminal 상태는 같은 dataset-bound checkpoint에서 재개한다.
  checkpoint는 dataset, pipeline run, collector, policy, candidate identity가 다르면
  실패하므로 다른 실행 결과를 섞지 않는다.

Orchestrator cycle마다 quota 안전 확인용 `/rate_limit` control 요청은 남는다. “추가
fetch 없음”은 repo metadata/tree/raw artifact fetch가 없다는 뜻이며, 안전 확인까지
생략한다는 뜻은 아니다.

검증 근거는 `test_same_sha_reuses_complete_cache_across_datasets`,
`test_same_dataset_replay_preserves_batch_and_skips_repo_fetch`,
`test_changed_sha_and_changed_policy_both_miss_cache`, rate-limit resume 테스트들이다.

## 4. Jobs

### 4.1 업무 키와 같은 공고 재수집

Jobs의 기술적 업무 키는 정확히 `(source_site, source_posting_id)`다.
`canonical_job_id`는 서로 다른 source record가 같은 공고일 가능성을 표시하는 semantic
duplicate 후보이므로 transport 멱등성 키로 사용하지 않는다.

현재 JobKorea 수집기는 source가 항상 `JOBKOREA`이고 목록 처리 중 이미 본
`source_posting_id`를 건너뛴다. 따라서 한 collection run의 최종 Batch에는 같은 업무
키가 한 번만 남으며, 건너뛴 수는 manifest의 `duplicates_skipped`에 기록된다. 첫 번째
관측을 유지하며 A조는 서로 다른 사이트 공고의 의미상 동일 여부를 판단하지 않는다.

### 4.2 Snapshot/partition 재처리

로컬 출력 partition은 `output_dir/pipeline_run_id/`다. JSON, CSV, manifest는 temporary
파일에서 final로 원자적으로 교체된다.

- 같은 `CrawlResult`와 같은 `pipeline_run_id`를 replay하면 같은 세 final 파일을
  교체하므로 record를 append하지 않고 byte가 같은 결과를 유지한다.
- 실제 재수집 시간이 달라 새 `pipeline_run_id`가 생기면 별도 run snapshot으로
  보존한다. 소비자는 하나의 `(dataset_snapshot_id, pipeline_run_id)`를 명시적으로
  선택해야 하며 여러 run partition을 단순 union해서는 안 된다.
- 같은 업무 키의 내용이 나중 run에서 바뀌면 새 `content_hash`를 가진 새 관측이다.
  선택된 snapshot 안에서는 한 row이고, 과거 snapshot을 overwrite하지 않는다.

공용 HDFS Jobs Snapshot publisher, “현재 snapshot” 포인터, Serving DB UPSERT는 아직
없다. 따라서 여러 run 중 하나를 승격하거나 replace하는 운영 동작은 구현됐다고
주장하지 않으며 후속 sink 작업에서 원자적 manifest/pointer 규칙을 정해야 한다.

로컬 회귀 근거는
`test_same_run_replay_replaces_outputs_without_duplicate_records`와 수집기의
`seen_ids`/`duplicates_skipped` 처리다.

## 5. Streaming의 실제 구현 경계

현재 [`replay.sh`](../../Infra/scripts/replay.sh)는 newline-delimited payload의 모든
line을 지정 Kafka topic에 다시 보내는 console producer wrapper다. 자체 checkpoint,
event key, 중복 제거 상태가 없다. [`kafka-smoke.sh`](../../Infra/scripts/kafka-smoke.sh)는
매번 임시 topic을 만들고 메시지 한 건을 `--from-beginning --max-messages 1`로 확인한 뒤
topic을 삭제하는 transport smoke다. [`AI/worker`](../../AI/worker/__main__.py)는 health
server만 실행한다.

따라서 현재 확인 가능한 Streaming 범위는 “producer replay 가능”과 “Kafka 한 건
송수신 가능”뿐이다. 애플리케이션 Consumer group/offset commit, checkpoint 복원,
중복 안전 sink, DLQ replay는 구현되지 않아 restart 멱등성 검증 대상이 없다. 이를
가정한 Kafka/Streaming E2E는 수행하지 않았고 후속 구현·검증으로 분리한다.

## 6. 로컬 검증

Production 서버, HDFS 실제 데이터, GitHub 대량 API를 사용하지 않고 다음 관련 테스트를
실행한다.

```powershell
Set-Location AI
python -m pytest tests/test_gharchive_historical.py `
  tests/test_gharchive_cli_and_sinks.py `
  tests/test_gharchive_webhdfs_sink.py `
  tests/test_repo_activity_topn.py `
  tests/test_repo_fetch_orchestrator.py `
  tests/test_repo_snapshot_bootstrap.py `
  tests/test_job_contracts.py `
  tests/test_jobkorea.py
python -m ruff check collector github job JobKorea_Collector_V1 tests
```

Streaming restart E2E와 Production replay는 이 로컬 검증에 포함하지 않는다.
