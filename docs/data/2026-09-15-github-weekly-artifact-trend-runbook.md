# GitHub Weekly → Artifact → Trend 연결 Runbook

이 문서는 Weekly Repo Activity를 기존 A→C GitHub Snapshot/Artifact 계약에
연결하는 repository-side 경로를 기록한다. 이번 연결은 Redis를 사용하지 않으며,
Production 실행·배포·재시작을 포함하지 않는다.

## 실제 흐름

```text
GH Archive → Kafka github.events → C1 Spark Structured Streaming
→ HDFS Streaming Parquet
→ repo_activity_weekly
→ Weekly candidate (repo_id, repo_name, event_count, week_start)
→ WeeklyArtifactResolver
→ 기존 RepoFetchOrchestrator / ArtifactStore
→ github-repo-snapshot publication
→ 기존 PublicPipelineConsumer → PUBLIC_GITHUB
→ bounded C weekly export
→ WeeklyActivityConsumer → TREND
```

C1의 기본 산출물은
`hdfs:///gitjob/parquet/stream/github.events`이고 checkpoint는
`hdfs:///gitjob/checkpoints/c1/github.events`이다. Weekly 집계는
`hdfs:///gitjob/parquet/github/repo_activity_weekly/period={YYYY-MM}/snapshot={id}/`
아래에 저장되며, 완료 게시본은 기존 Analysis Input namespace를 사용한다.

```text
hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id={id}/
├── artifacts/
├── snapshot.json
├── run-summary.json
├── failures.json
└── _SUCCESS.json
```

`_SUCCESS.json`은 `github-repo-snapshot-publish-manifest/v1`이며,
`github.snapshot_input.load_published_snapshot`가 바이트·SHA·summary/failure
identity를 검증한다. 새 Artifact format이나 별도 DB 저장소는 만들지 않는다.

## SHA와 identity 경계

Historical은 `require_historical_head=True`와 `monthly_event_sha`를 사용한다.
성공한 레코드는 `sha_source=MONTH_EVENT_SHA`이고
`selected_commit_sha=pinned_commit_sha=monthly_event_sha`이다. 이 경로는
`CURRENT_DEFAULT_HEAD`로 fallback하지 않는다.

Weekly 집계 행에는 SHA가 없으므로 기존 공통 경로에 그대로 위임한다.

- 기존 `RepoFetchOrchestrator`가 repository metadata와 default branch head를
  resolve한다.
- 결과는 `sha_source=CURRENT_DEFAULT_HEAD`이고
  `selected_commit_sha=pinned_commit_sha=current_default_head`이다.
- `monthly_event_sha`를 Weekly adapter 입력에 포함하면 즉시 거부한다.

Artifact durable key는 기존 `ArtifactStore`의
`policy + repo_id + commit={pinned_commit_sha} + repo-relative-path`이다.
따라서 repo 이름 변경/transfer는 표시 이름일 뿐 lookup key가 아니며, 같은
`repo_id`라도 SHA가 다르면 재사용되지 않는다. Weekly adapter는 기존
non-Historical cache/checkpoint contract를 사용하며 Historical required-head
경로와 섞지 않는다.

## 실행 경계

### 1단계 — candidate 생성 (S15P21E102-276)

후보 JSON은 손으로 만들지 않는다. Weekly Parquet을 직접 읽는 것은 Spark가 하고,
`repo-activity-weekly-candidates/v1` 계약은 `build_weekly_candidates()` 한 곳에서만
적용된다. Spark 이미지는 `Infra/spark`만 담고 있어 `github` 패키지를 import할 수
없기 때문에 두 단계로 나뉜다.

한 주가 수백만 행이므로 select/sort/limit은 Spark 안에서 끝나고 driver로는
`--limit` 만큼만 내려온다.

```bash
# (1) bounded Top-N read-back — Spark
compose exec -T spark-worker /opt/spark/bin/spark-submit   /opt/gitjob/spark/jobs/weekly_candidate_export.py   --input  hdfs:///gitjob/parquet/github/repo_activity_weekly/period={YYYY-MM}/snapshot={snapshot-id}/repo_activity_weekly   --week   {YYYY-MM-DD}   --limit  1500   --output /tmp/weekly-candidate-rows.json

# (2) 계약 적용 — AI
PYTHONPATH=AI python -m github.weekly_candidate_export_cli   --rows   .local/weekly-artifact/weekly-candidate-rows-{YYYY-MM-DD}.json   --output .local/weekly-artifact/weekly-candidates-{YYYY-MM-DD}.json   --candidate-pool-limit 1500   --manifest-uri hdfs:///gitjob/parquet/github/repo_activity_weekly/period={YYYY-MM}/snapshot={snapshot-id}/repo_activity_weekly/week={YYYY-MM-DD}/_SUCCESS.json   --webhdfs-url {WEBHDFS_URL}
```

`--manifest-uri`는 기본적으로 필수다. `_SUCCESS.json`이 그 주가 끝났다고 말하는
유일한 근거이고, 이것을 건너뛰면 절반만 쓰인 snapshot에서 후보 pool이 만들어져도
resolver는 알아차릴 방법이 없다. 이미 다른 경로로 검증한 주에만
`--skip-manifest-check`를 쓴다.

`--candidate-pool-limit`은 `WEEKLY_CANDIDATE_POOL_LIMIT`으로도 준다. 1500은
`S15P21E102-274`의 pool 기본값과 같은 값이며, resolver는 그 pool 안에서 valid 100을
채운다. 후보 생성기는 NOT_FOUND나 artifact 유무를 판단하지 않는다 — 그것은
resolver의 몫이다.

### 2단계 — resolver 실행 (S15P21E102-323)

`Infra/scripts/weekly-artifact-resolver.sh`로 실행한다. 이전 판의 예시는
host에서 `PYTHONPATH=AI python -m ...`을 돌리는 형태였는데, host에는 AI
패키지의 의존성이 설치되어 있지 않아 `ModuleNotFoundError`로 끝난다.
candidate 생성과 마찬가지로 CLI는 이미지 안에 있고 파일은 host에 있으므로
wrapper가 그 경계를 넘긴다.

```bash
ENV_FILE=.env.data \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data-cluster.yaml \
PROFILES=data \
WEEKLY_CANDIDATES=.local/weekly-artifact/weekly-candidates-{YYYY-MM-DD}.json \
WEEKLY_ARTIFACT_STATE_ROOT=.local/weekly-artifact \
WEEKLY_SNAPSHOT_ID={weekly-snapshot-id} \
WEEKLY_RUN_ID={weekly-run-id} \
  ./Infra/scripts/weekly-artifact-resolver.sh
```

wrapper가 고정하는 것은 두 가지다.

**service는 `worker`다.** `collector`에는 `REDIS_*` 블록이 없어서 그쪽에서
resolver를 돌리면 `--enable-redis-artifact-index`를 줘도 index가 만들어지지
않는다. 그런데 run summary의 Redis 지표는 전부 0으로 찍히고, 이는 namespace가
정말 비어 있을 때와 구분되지 않는다. `-323`부터 orchestrator가 이 조합을
거부하지만, wrapper는 애초에 지원되는 쪽을 실행한다.

**Weekly 계약값이다.** pool 1500 / quota 100 / batch 1이며, Historical의
Top-10000이 환경변수로 흘러들어오지 않는다.

`worker`의 environment에 없는 `GITHUB_API_TOKEN`·`WEBHDFS_URL`·`WEBHDFS_USER`는
`ENV_FILE`에서 읽어 명시 전달한다. `weekly-snapshot-publish.sh`가
`KAFKA_BOOTSTRAP_SERVERS`를 넘기는 방식과 같다.

#### Redis Artifact Index

compose가 `worker`에 `WEEKLY_REDIS_ARTIFACT_INDEX_ENABLED`를 주므로 기본
활성화다. Production은 db 1, namespace `gitjob:weekly:artifact-index:v1`,
TTL 30일이며 셋 다 코드 기본값이다. benchmark의 db 3 /
`gitjob:benchmark:...`는 이 경로에서 쓰이지 않는다.

Redis는 index이지 source of truth가 아니다. HIT이어도 durable artifact가
검증을 통과해야 REUSED가 되고, broker 장애·timeout은 기존 resolver 경로로
fail-open한다. Redis 때문에 Weekly 전체가 실패하지는 않는다.

> 2026-09-17 Week A 최초 Production 실행은 lookup 270 / hit 0 / miss 270,
> error 0 / fail-open 0이었다. 장애가 아니라 Production namespace가 비어
> 있었기 때문이며, benchmark가 보인 단축 효과는 index가 warm해진 다음
> Weekly부터 나타난다.

Production WebHDFS publish는 `--webhdfs-artifact-root`와 `--publish-root`를
명시적으로 함께 지정해야 하며, 이번 작업에서는 실행하지 않는다. publish가
완료되면 기존 `snapshot_input` 경로가 이를 읽고, `PublicPipelineConsumer`가
Artifact를 분석해 `PUBLIC_GITHUB`를 만든다. 그 다음 C exporter가 Weekly
manifest/row digest에 결속된 bounded export를 만들고
`WeeklyActivityConsumer`가 registry/include_partial가 호환되는
`PUBLIC_GITHUB`와 export를 확인한 뒤에만 TREND를 저장한다.

`PUBLIC_GITHUB_NOT_READY`는 Artifact 파일 하나가 없다는 뜻이 아니라,
해당 week·registry·include_partial과 호환되는 C snapshot head가 아직 없거나
bounded export의 upstream binding이 맞지 않는다는 뜻이다. 따라서 Resolver가
생성한 A Snapshot만으로 C 완료를 주장하지 않는다.

## 오프라인 검증 계약

`AI/tests/test_weekly_artifact_resolver.py`는 다음을 검증한다.

- 같은 `repo_id + resolved SHA` replay가 기존 Artifact를 재사용
- 같은 `repo_id + 다른 SHA`는 새 extraction 수행
- Historical `MONTH_EVENT_SHA` cache와 Weekly `CURRENT_DEFAULT_HEAD` 격리
- `monthly_event_sha` Weekly 입력 거부
- repo rename/transfer에서도 repo_id + SHA identity 유지
- replay 중복 Artifact 생성 방지
- 기존 snapshot publication contract를 생성하고 C handoff 경계를 넘지 않음

Production에서 최종 Trend PASS를 기록하려면 별도로 Weekly `_SUCCESS.json`,
`PUBLIC_GITHUB` compatible head, C export manifest/metadata/data checksum 및
TREND snapshot/head를 read-only로 확인해야 한다. 이 repository-side 변경은
그 확인을 대신하지 않는다.
