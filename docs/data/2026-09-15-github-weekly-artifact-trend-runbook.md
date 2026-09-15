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

실제 Weekly Parquet read-back 행은 `build_weekly_candidates()`에 넣어
deterministic event-count descending / repo-id tie-break top-N 후보로 만든다.
후보 JSON을 직접 사용할 때는 `repo-activity-weekly-candidates/v1`를 사용한다.

```powershell
$env:PYTHONPATH='AI'
python -m github.weekly_artifact_resolver `
  --candidates .local/weekly-candidates.json `
  --output .local/weekly-snapshot.json `
  --summary-output .local/weekly-run-summary.json `
  --failure-output .local/weekly-failures.json `
  --state-output .local/weekly-state.json `
  --checkpoint .local/weekly-checkpoint.json `
  --cache .local/weekly-cache.json `
  --artifact-root .local/weekly-artifacts `
  --dataset-snapshot-id {weekly-snapshot-id} `
  --pipeline-run-id {weekly-run-id}
```

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
