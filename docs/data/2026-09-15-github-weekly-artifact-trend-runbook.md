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

### 3단계 — fixed cohort weekly PUBLIC bundle (S15P21E102-331)

2단계 resolver는 그 주의 후보를 GitHub에서 새로 가져온다. Historical 구간을
그 방식으로 메우면 주차마다 GitHub fetch가 다시 필요하고, 이미 durable하게
가지고 있는 Artifact를 쓰지 못한다. 3단계는 그 재수집을 없애기 위한 경로다.

#### fixed analyzed repo cohort

"Top10000"이 아니다. 2026-03~2026-08 월별 Top10k 수집에서 **유효한 durable
artifact가 남아 있는 repo의 합집합**이며, 2026-09-18 기준 10,419개다. 6개월
전부에 등장하는 repo는 130개뿐이므로 월별 Top10k는 서로 다른 집합이고, 이
cohort는 그 합집합으로만 정의된다. repo identity는 이름이 아니라 GitHub
repository ID다. 이름은 rename으로 바뀌지만 ID는 바뀌지 않는다.

cohort는 기존 published snapshot을 입력으로 재현한다. `select_cohort_records`가
여러 snapshot을 순서대로 받아 repo_id별 첫 레코드를 남기므로, freshness 정책은
호출자가 인자 순서로 정한다.

#### week scoping — 월 단위 period를 절대 상속하지 않는다

C의 head 선택(`worker.store._public_payload_covers_week`)은 record의
`target_period`와 `activity_period_start/end`를 **포함이 아니라 겹침**으로
판정한다. 월 단위 period를 그대로 물려주면 그 달의 모든 주차가 매칭되고,
`select_public_snapshot`은 `occurred_at DESC`로 가장 최신 head를 고른다.
그러면 어떤 주차가 다른 주차의 denominator를 받게 되고, 소비자는 그 export를
`weekly export rows are outside selected PUBLIC_GITHUB`로 거절한다. 거절은
offset을 커밋하므로 **그 주차 이벤트는 재시도되지 않고 사라진다.**

그래서 생성기는 각 record의 `target_period`를 `<월>/<일>`로, `activity_period_start/end`를
그 주 월요일과 일요일로 좁힌다. 이렇게 하면 주차별 head가 자기 주차에만
매칭되고 선택이 1:1이 된다.

#### rank 재계산

`snapshot_input._reconcile`은 `disposition.rank == record.activity_rank`를
요구하고 `_index`는 `top_n_limit`을 넘는 rank를 거부한다. 월간 publication의
부분집합은 rank가 연속도 아니고 그 주를 설명하지도 않으므로, 그 주
`event_count` 기준으로 1..N을 다시 매긴다. `activity_count`도 그 주 값으로
바꾼다.

summary는 `github-repo-fetch-run-summary/v1`을 쓴다. bootstrap schema를 쓰면
전수 커버리지(`len(by_id) == top_n_limit`) 규칙에 걸린다.

수집 실패(`FAILED`) repo는 재사용할 증거가 없으므로 그 주 후보가 아니다.
실패 사실은 그 repo를 실제로 가져온 publication의 failures 객체에 이미 남아
있다. artifact도 language metadata도 없는 repo 역시 denominator에 도달할 수
없으므로 후보에서 제외한다. 2026-08-10 운영 구조로 확인한 결과 이 필터는
후보를 2,198건에서 890건으로 줄이면서 denominator는 679건으로 **동일**했다.

#### 생성 명령

```bash
python -m github.weekly_cohort_snapshot_cli   --week-start 2026-08-10   --cohort-snapshot <월별 snapshot.json>   --week-activity <그 주 repo_id/event_count NDJSON>   --dataset-snapshot-id s15p21e102-weekcohort-2026-08-10-v1   --pipeline-run-id weekcohort-2026-08-10-001   --publication-root hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=s15p21e102-weekcohort-2026-08-10-v1   --generated-at 2026-09-18T12:00:00+00:00   --artifact-uri-prefix hdfs:///gitjob/analysis_input/github/repo_snapshot   --dry-run
```

`--cohort-snapshot`은 반복 지정하며 앞에 온 snapshot이 우선한다.
`--artifact-uri-prefix`는 하드코딩하지 않고 주입한다. C의
`ReadOnlyWebHdfsReader`는 `path.startswith(prefix + "/")`로만 검사하므로
`hdfs:///gitjob/analysis_input/github/repo_snapshot` **하나면 29개 artifact
root를 모두 덮는다.** leaf root를 쓰면 주차마다 6개가 필요해 4개 상한에 걸린다.
`--dry-run`은 무엇이 만들어질지만 출력하고 아무것도 쓰지 않는다.

#### idempotency

같은 입력은 같은 바이트를 만든다. JSON은 `sort_keys=True`,
`separators=(",", ":")`로 직렬화한다. `store_immutable`이 기존 객체와 바이트를
비교하므로 같은 내용의 재실행은 no-op이고, 내용이 달라지면 쓰기가 거부된다.
CLI도 같은 이유로 이미 존재하는 출력 디렉터리를 덮어쓰지 않고 종료 코드 1로
거절한다. 입력이 실제로 달라졌다면 새 `--dataset-snapshot-id`가 필요하다.

#### Production 실행은 별도 절차

이 생성기는 bundle을 만들 뿐이다. HDFS publish, `C_INTAKE_CONFIG`에 public
source 등록(최대 8개)과 worker 재시작, bounded export 생성, Kafka 완료 이벤트
처리는 모두 별도 승인 절차다. 특히 운영 `PUBLIC_GITHUB` head 목록을 read-only로
확인해 기존 head가 대상 주차와 겹치지 않는지 판정하기 전에는 canary를 실행하지
않는다.

### 4단계 — weekly PUBLIC 게시와 intake 운영 (S15P21E102-367)

3단계는 bundle 바이트까지만 만든다. 그것을 HDFS에 올리고 C가 읽게 만들고 export 입력을
꺼내는 연결층이 `AI/github/weekly_public_publish_cli.py`다.

2026-09-20에 2026-03-09~03-30 네 주를 게시한 도구는 저장소 밖에 있었고 지금은 없다. 이 CLI는
그 도구를 복원한 것이 아니라, **남아 있는 산출물과 바이트 동일성이 검증된 primitive**로 다시 만든
것이다. 03-09 발행본의 `failures.json` 141바이트가 `_canonical()` 출력과 정확히 일치하는 것을
테스트로 고정해 두었다.

#### export의 `--repo-ids`는 bundle이 아니라 PUBLIC 결과다

이걸 틀리면 주차가 조용히 사라진다. `export_c_archive_activity`는
`c-public-published-result/v1` 과 `c-public-repo-analysis/v1|v2` 일 때만
`included_in_denominator`가 false인 행을 버린다. `github-repo-snapshot/v1`(= bundle의
`snapshot.json`)을 주면 **후보 전체의 repo_id**를 쓴다. bundle은 그 주 cohort 후보 전부라
C가 denominator에서 제외한 repo가 수천 개 섞여 있고, 그 id가 export에 들어가면
`WeeklyActivityConsumer`가 `weekly export rows are outside selected PUBLIC_GITHUB`로 거절한다.
**거절은 오프셋을 커밋하므로 그 주차 이벤트는 재시도되지 않고 소실된다.**

그래서 CLI는 `ComputeStore.select_public_snapshot(registry_version, include_partial, week_start)`이
돌려준 payload를 그대로 파일로 쓴다. 소비자가 head를 고를 때 쓰는 바로 그 호출이므로,
export가 쓰는 denominator와 소비자가 검증할 denominator가 같은 것임이 보장된다.

#### 게시 순서와 멱등성

`snapshot.json` → `run-summary.json` → `failures.json` → **`_SUCCESS.json` 마지막**이다.
`load_published_snapshot`이 marker를 먼저 읽고 거기 적힌 sha256으로 나머지를 검증하므로,
marker의 존재가 "이 marker가 가리키는 바이트는 이미 전부 있다"는 뜻이 되어야 한다.
중간에 죽으면 marker가 없어 발행본으로 인정되지 않는다.
`store_immutable`이 바이트를 비교하므로 같은 입력 재실행은 아무것도 쓰지 않고,
입력이 달라졌으면 **marker 이전에** `FileExistsError`로 멈춘다. 그때는 덮어쓰지 말고
새 `--dataset-snapshot-id`로 간다.

#### 0단계 — week_activity 입력 만들기 (S15P21E102-369)

`weekly_public_publish_cli --week-activity`가 읽을 파일은
`Infra/spark/jobs/export_weekly_cohort_activity.py`가 만든다. 고정 cohort와 그 주
aggregate를 **left semi join**해서 `repo_id`/`event_count`/`week_start` NDJSON을 쓴다.

left join이면 안 된다. aggregate는 event groupBy라 그 주 활동이 없는 repo는 행이 없고
(2026-03-09 aggregate 3,854,460행의 `event_count` 최솟값 1, 0건 없음), left join은
활동 0인 repo에 0을 만들어 넣어 그 주 후보를 부풀린다.

**cohort는 2026-03-09 발행본을 바이트까지 재현한 조합으로 고정한다.**

- 소스는 월별 Top10k 스냅샷 **202604·202605·202606·202607·202608** 다섯 개다. 202603은 한 건도 기여하지 않았으므로 넘기지 않는다
- **최신 월부터** 넘긴다. `select_cohort_records`가 먼저 본 레코드를 남기기 때문이다. 발행본 5,089건 **전부**가 그 repo를 담은 가장 최신 스냅샷에서 왔다(5,089/5,089, 예외 0). 오래된 순으로 넘기면 다른 발행본이 나온다
- 멤버십은 그 다섯 스냅샷 아래 **artifact 디렉터리가 있는 repo**(10,211)다. 레코드 전체(18,575)를 넘기면 후보가 5,741로 부풀고, 여섯 번째 스냅샷(202603)까지 포함하면 5,090이 되어 1건 어긋난다

이 조합으로 2026-03-09를 재생성하면 semijoin 5,112행 → 발행본 5,089건이고,
`snapshot.json`·`run-summary.json`·`failures.json`·`_SUCCESS.json` **네 개가 모두 운영본과 바이트 동일**하다.

#### 주차 하나를 처리하는 11단계

1. **aggregate 확인** — `.../repo_activity_weekly/week=<월요일>/`에 `_SUCCESS`와
   `_SUCCESS.json`이 있고 `row_count`가 기록돼 있는지 본다. `_SUCCESS.json`이 없으면
   완료 이벤트도 나가지 않은 주차다.
2. **bundle dry-run** — `--dry-run`으로 record_count와 객체 크기만 확인한다. 아무것도 쓰지 않는다.
3. **immutable publish** — `--webhdfs-url`을 주고 실행한다. 출력 JSON의 `republished`가
   true면 이미 같은 바이트가 있었다는 뜻이다.
4. **`C_INTAKE_CONFIG`에 source 등록** — 주차마다 항목 하나다. `root_uri`는 방금 게시한 루트,
   `artifact_root_uris`에는 `hdfs:///gitjob/analysis_input/github/repo_snapshot` 하나면
   29개 artifact root를 전부 덮는다. **`checkpoint_dir`는 주차마다 반드시 달라야 한다.**
5. **worker restart** — config는 프로세스 기동 시 읽는다. CLI는 이 단계를 절대 대신하지 않는다.
6. **PUBLIC head COMPLETED 확인** — `GET /internal/v1/c/intake/status`의 `public_sources`에서
   해당 index가 `COMPLETED`가 될 때까지 기다린다. 2026-09-20 실측으로 주차당 약 30분이었다.
7. **export repo-id source 생성** — CLI를 `--repo-ids-out`과 `--registry-version`으로 다시
   실행한다. head가 아직 없으면 파일을 만들지 않고 종료코드 3으로 끝난다.
8. **Spark archive export** — `Infra/spark/jobs/export_c_archive_activity.py`를
   `--granularity WEEK`, `--period <월요일>`, `--repo-ids <7단계 파일>`로 실행한다.
   Spark 이미지에는 `AI/`가 없으므로 이 단계만 별도다.
9. **Kafka offset 전진 확인** — 소비자는 재시작하지 않는다. 최대
   `WEEKLY_ACTIVITY_MAX_RETRY_DELAY_SECONDS`(기본 900초) 안에 backoff에서 깨어나
   막혀 있던 오프셋을 다시 받는다. `CURRENT_OFFSET`이 1 늘고 `LAG`이 1 줄면 성공이다.
10. **Trend 확인** — 그 주 WEEK point가 생겼는지, value가 `active_repo_count`이고
    denominator가 `sample_repo_count`인지 본다.
11. **다음 batch** — 위를 반복한다.

#### batch 크기는 8이 아니라 4로 간다

`public_sources` 상한은 8이지만 8을 채우지 않는다. **항목 하나가 검증에 실패하면 워커 전체가
죽고 Historical 폴링까지 같이 멈춘 전례가 있다**(S15P21E102-286의 주석). 한 번에 넣는 수를
줄이면 그 폭발 반경이 줄고, aggregate 배치도 4주 단위였으므로 대조하기도 쉽다.
그래서 04-06부터 08-17까지 20주는 **4주씩 5회**로 나눈다. 각 회차마다 9단계에서 오프셋이
4만큼 전진한 것을 확인한 뒤 다음으로 넘어간다.

첫 회차는 4주가 아니라 **2026-04-06 한 주만** 돌리는 canary다.

#### 이 CLI가 하지 않는 것

`C_INTAKE_CONFIG`를 고치지 않고, 워커를 재시작하지 않고, Spark를 실행하지 않는다.
config 변경과 재시작은 공용 워커의 상태를 바꾸는 일이라 명령 한 줄 뒤에 숨기지 않는다.

## 오프라인 검증 계약

`AI/tests/test_weekly_artifact_resolver.py`는 다음을 검증한다.

- 같은 `repo_id + resolved SHA` replay가 기존 Artifact를 재사용
- 같은 `repo_id + 다른 SHA`는 새 extraction 수행
- Historical `MONTH_EVENT_SHA` cache와 Weekly `CURRENT_DEFAULT_HEAD` 격리
- `monthly_event_sha` Weekly 입력 거부
- repo rename/transfer에서도 repo_id + SHA identity 유지
- replay 중복 Artifact 생성 방지
- 기존 snapshot publication contract를 생성하고 C handoff 경계를 넘지 않음

`AI/tests/test_weekly_cohort_snapshot.py`와
`AI/tests/test_weekly_cohort_snapshot_cli.py`는 3단계를 검증한다.

- 그 주 활동한 repo만 후보가 되고, 활동 없는 repo는 빠진다
- 재사용 가능한 증거가 없는 repo와 `FAILED` 수집은 후보가 아니다
- `target_period`와 `activity_period_start/end`가 그 주 월~일로 좁혀진다
- `activity_rank`가 1..N으로 재계산되고 summary rank와 일치한다
- summary가 weekly run schema를 쓰고 개수가 정합한다
- 같은 입력이 같은 바이트를 만든다
- 한 주차 bundle이 다른 주차를 cover하지 않는다
- 실제 `load_published_snapshot()`이 생성물을 그대로 받아들인다
- `--artifact-uri-prefix` 밖의 artifact URI를 거부한다
- CLI가 기존 출력 디렉터리를 덮어쓰지 않고, 다른 주차 activity 행을 거부한다

`AI/tests/test_weekly_public_publish_cli.py`는 4단계를 검증한다.

- `_SUCCESS.json`이 항상 마지막에 저장된다
- 같은 바이트 재실행은 아무것도 새로 쓰지 않는다
- 같은 경로에 다른 바이트면 marker 이전에 거절되고 기존 marker가 그대로 남는다
- marker 이전 실패는 유효한 발행본을 남기지 않는다
- `--dry-run`은 한 바이트도 쓰지 않는다
- 그 주 PUBLIC head가 없으면 repo-id source 파일을 만들지 않는다
- head가 있으면 선택된 payload를 통째로 저장하고, `included_in_denominator`가 false인
  행도 보존해 exporter가 직접 거를 수 있게 한다
- 인식할 수 없는 schema의 payload는 거절한다
- 월 단위 PUBLIC은 주차를 cover하지 못한다(S15P21E102-337 selector 직접 검증)
- 2026-03-09 운영 발행본의 `failures.json` 141바이트와 직렬화가 일치한다

Production에서 최종 Trend PASS를 기록하려면 별도로 Weekly `_SUCCESS.json`,
`PUBLIC_GITHUB` compatible head, C export manifest/metadata/data checksum 및
TREND snapshot/head를 read-only로 확인해야 한다. 이 repository-side 변경은
그 확인을 대신하지 않는다.
