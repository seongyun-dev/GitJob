# GitJob MVP 데이터 파이프라인 E2E Runbook

- 작성일: 2026-09-12
- 기준 커밋: `origin/develop` 01689e1 (`-224`·`-225`·`-227`·`-228`·`-229`·`-230` 머지 포함)
- 목적: MVP 전체 흐름을 순서대로 올리고, 각 단계가 끝났는지 **판정 가능한 기준**으로 확인한다
- 성격: 실행·판정 절차. 각 단계의 설계 근거는 링크한 문서에 있고 여기서 반복하지 않는다

> 이 문서의 명령과 경로는 전부 현재 `develop`의 스크립트·코드에서 확인한 것이다.
> 추정으로 만든 명령은 없다. **작성 시점에 파이프라인을 실행하지 않았다** — HDFS
> DataNode 정리가 진행 중이었다. 따라서 각 단계의 PASS 기준은 "이렇게 확인한다"
> 이지 "이렇게 나왔다"가 아니다.

관련 문서: [GitHub Historical Pipeline 운영·복구 Runbook](2026-09-12-github-historical-pipeline-runbook.md) ·
[주간 Repo Activity 집계](2026-09-12-repo-activity-weekly.md) ·
[부하 테스트 계획](2026-09-12-load-test-plan.md)

---

## 0. 공통 환경

모든 `Infra/scripts/*.sh`는 `_lib.sh` 규약을 따른다. **세 값을 매번 명시한다** —
빠지면 WSL 기본값으로 조용히 다른 환경을 가리킨다.

| 변수 | Data Server | Service Server |
|---|---|---|
| `ENV_FILE` | `.env.data` | `.env.service` |
| `COMPOSE_OVERRIDE_FILE` | `Infra/compose/compose.ec2-data.yaml` | `Infra/compose/compose.ec2.yaml` |
| `PROFILES` | `data` | `core,app` |

HDFS 조회는 NameNode 컨테이너에서 한다. collector/worker 이미지에는 Hadoop CLI도
JRE도 없다(의도된 slim 이미지).

```bash
compose exec -T hdfs-namenode hdfs dfs -ls /gitjob
```

### 이 문서가 쓰는 판정 표기

| 표기 | 뜻 |
|---|---|
| **코드 있음** | 코드와 단위 테스트는 있으나 운영에서 실행된 적 없음 |
| **운영 검증됨** | 실제 서버에서 실행해 결과를 확인함 |
| **실행 경로 있음 / 미등록** | 스크립트나 서비스 정의는 있으나 crontab 등록·기동이 안 됨 |
| **배선 없음** | 코드는 있으나 이를 호출하는 스케줄러·서비스가 없음 |

---

## A. HDFS

### [A-1] 클러스터 health

- **선행**: DataNode 정리·re-replication 완료
- **실행 위치**: Data Server
- **실행**
  ```bash
  compose exec -T hdfs-namenode hdfs dfsadmin -report
  compose exec -T hdfs-namenode hdfs fsck /gitjob
  df -h /
  ```
- **필요 env**: `ENV_FILE=.env.data`, `COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml`, `PROFILES=data`
- **PASS**
  - Live DataNode = **2** (Data Server DN1 · Service Server DN4)
  - `fsck` = `HEALTHY`
  - Missing blocks 0, Corrupt blocks 0
  - **Under-replicated blocks 0** — RF3 legacy 정리가 끝났다는 뜻
  - host `df` 여유 공간 확보 (판단 기준은 `dfsadmin` capacity가 아니라 host `df`.
    논리 DataNode가 같은 파일시스템을 공유하므로 capacity는 과대평가된다)
- **FAIL 시 확인**
  - `hdfs dfsadmin -report`의 Dead/Decommissioning 노드
  - `hdfs fsck /gitjob -files -blocks -locations`로 어느 블록인지
  - `docs/infra/2026-09-11-hdfs-datanode-hostname-rereplication-fix.md`
- **재실행**: 조회 전용. 멱등
- **gate**: **여기가 통과하지 않으면 B~G 전부 시작하지 않는다.** 모든 단계가 HDFS에 쓴다

### [A-2] replication policy RF2

- **실행**: `compose exec -T hdfs-namenode hdfs getconf -confKey dfs.replication`
- **PASS**: `2`, 그리고 신규 write가 RF2로 생성됨
- **FAIL**: 기존 RF3 파일이 남아 있으면 under-replicated로 보인다 — A-1과 함께 판단
- **gate**: A-1과 동일

---

## B. 채용공고

### [B-1] Crawler 회차 실행

- **상태**: 코드 있음 / **crontab 미등록**
- **실행 위치**: Data Server (현재는 수동)
- **구성**: [AI/schedule.toml](../../AI/schedule.toml) — **4개 source**
  (`WORKNET`, `SARAMIN`, `GAMEJOB`, `CAREER`), 각 morning/evening 2회,
  총 **8개 run 블록**
- **JOBKOREA는 MVP 대상이 아니다** — `-230`(2026-09-13)이 `-196`을 부분 철회해
  `enabled = false`로 두었다. 선언과 수집기(`AI/JobKorea_Collector_V1/`)와 테스트는
  그대로 있으므로 `schedule.toml`의 run 블록은 10개이고 그중 8개가 enabled다.
  근거와 재검토 조건은
  [잡코리아 제외 결정](2026-08-31-jobkorea-retention-decision.md)에 있다.
  `python -m job.collector --render cron`은 **8줄**을 낸다
- **주의**: `compose`의 `collector` 컨테이너는 `python -m collector`를 실행하는데
  이 엔트리포인트는 **health 서버만 띄운다**([AI/collector/__main__.py](../../AI/collector/__main__.py)).
  수집을 돌리는 것은 스케줄러이고, 그 스케줄러가 아직 운영에 등록되지 않았다
- **필요 env**: `GITHUB_API_TOKEN` 불필요. 사이트별 설정은 `schedule.toml`
- **출력 경로**: `hdfs:///gitjob/raw/jobs/{source}/dt=YYYY-MM-DD/{RUN_ID}/`
- **PASS**: 회차 manifest의 `expected`/`completed` 일치, `failed` 0,
  `source_admission` 블록 존재
- **FAIL 시 확인**: 회차 디렉터리의 `manifest.json`, collector 로그
- **재실행**: cursor와 identity store가 `collector-state` named volume에 있어
  중복 수집을 막는다. **volume이 없으면 매일 첫 회차가 `ids_known_before_run=0`으로
  시작해 같은 공고를 다시 수집한다**(2026-09-08~11 실측 12.8%)
- **gate**: 회차가 하나라도 성공해야 B-2로

### [B-2] analysis_input 게시

- **상태**: **배선됨** — 별도 단계가 아니라 **수집 회차의 일부**다
- **모듈**: [AI/job/collector/analysis_input.py](../../AI/job/collector/analysis_input.py) (`-220`)
- **호출 지점**: 네 수집기가 회차 끝에서 `publish_from_env`를 직접 부른다.
  운영자가 따로 실행할 것이 없다

  | 수집기 | 호출 |
  |---|---|
  | `AI/Worknet_Collector_V1/crawler.py` | `:822` |
  | `AI/Saramin_Collector_V1/crawler.py` | `:764` |
  | `AI/GameJob_Collector_V1/crawler.py` | `:935` |
  | `AI/Career_Collector_V1/crawler.py` | `:903` |

  `JobKorea_Collector_V1`에는 이 호출이 없다. `-230`으로 비활성이라 MVP에 영향이
  없지만, 되살릴 때는 게시 경로도 함께 붙여야 한다
- **입력**: B-1의 회차 디렉터리 (`manifest.json` + batch)
- **출력**: `hdfs:///gitjob/analysis_input/jobs/{source}/{RUN_ID}/`
- **PASS**: 게시된 3개 파일과 `analysis_input_publish.json` 기록.
  manifest의 `output_sha256`이 batch 바이트와 묶여 있어야 한다
- **FAIL**: 조기 종료·detail 실패·invalid record가 있는 회차는 게시하지 않는다
  (`worker.intake.load_job_output`이 거부한다). **거부는 정상 결과이고 수집을
  실패시키지 않는다** — 신뢰할 수 있는 회차만 목적지에 두는 것이 목적이므로,
  한 바이트도 옮기기 전에 거절한다
- **재실행**: `store_immutable` — 같은 내용 멱등, 다른 내용 거부
- **gate**: 게시 완료 후 B-3

### [B-3] C Worker intake

- **소비자**: [AI/worker/intake.py](../../AI/worker/intake.py)
- **PASS**: intake가 회차를 읽고 fact를 생성, `distinct_fact_keys`가 공고 수와 정합
- **FAIL 시 확인**: worker 로그, `load_job_output` 거부 사유
- **gate**: F(API)로

---

## C. GitHub Historical

상세 절차는 [Historical Runbook](2026-09-12-github-historical-pipeline-runbook.md)에
있다. 여기서는 gate만 요약한다.

### [C-1] Raw — **운영 검증됨**

- 2026-03~08 6개월, **4,416 files / 660,081,904 events / 120,146,905,981 B 압축**
- PASS: expected hours == HDFS files, missing/duplicate/invalid 0
- gate: C-2

### [C-2] Repo Activity — **운영 검증됨**

- `Infra/scripts/spark-repo-activity-topn.sh`
- 출력 `…/repo_activity/`, `…/topn_coverage/`, `…/data_quality/`
- PASS: stdout JSON summary가 나오면 read-back 통과 (job이 스스로 행 수를 대조하고
  불일치 시 예외)
- gate: C-3

### [C-3] Weekly Repo Activity

- `Infra/spark/jobs/repo_activity_weekly.py --input-format raw-json`
- 2026-08 실측 **7,967,178 rows / 5,711,133 repos / 200 parquet files / 261,039,111 B**
- PASS: `assert_week_slice_is_consumable` 통과, duplicate key/null 0
- gate: C-4 또는 E

### [C-4] Top-N candidates

- `Infra/scripts/spark-repo-fetch-candidates.sh`
- ⚠️ **`REPO_ACTIVITY_INPUT_ROOT`를 C-2 출력과 같은 값으로 반드시 명시한다.**
  두 스크립트의 기본값이 서로 다른 snapshot을 가리켜 연결되지 않는다
- gate: C-5

### [C-5] Artifact Snapshot

- `Infra/scripts/repo-snapshot-bootstrap.sh`
- 종료 코드 0 = publish 완료 / 2 = 미완(재개)
- PASS: `_SUCCESS.json`이 존재하고 객체별 sha256이 일치
- gate: E

---

## D. GitHub Realtime

**현재 상태: 실행 경로는 전부 저장소에 있으나 운영에서 도는 구간은 0개다.**
`-227`(publisher CLI)·`-228`(C1 서비스)·`-229`(watcher cron)이 머지되면서 "호출자가
없다"는 상태는 끝났다. 남은 것은 **토픽 생성과 crontab 등록, 그리고 첫 기동**이다.

### [D-1] Kafka topic 선언

- **실행 위치**: Service Server
- **실행**: `./Infra/scripts/kafka-topics.sh --check` → 이상 없으면 인자 없이 실행
- **선언 대상**: `github.events:6`, `so.raw:3`, `jobs.collected:3`,
  `gitjob.repository-analysis.*.v1:3`, `gitjob.repo-activity-weekly.completed.v1:1`
  (마지막은 `-225`에서 추가됨)
- **PASS**: `--check`가 mismatch 0
- ⚠️ `KAFKA_AUTO_CREATE_TOPICS_ENABLE=false`이므로 **토픽 없이 publish하면 실패한다.**
  파티션 수는 줄일 수 없으므로 선언 전 확정
- **gate**: D-2

### [D-2] watcher — **실행 경로 있음 / 미등록**

- 코드: [AI/collector/gharchive/watch.py](../../AI/collector/gharchive/watch.py)
- 실행: `python -m collector.gharchive watch --checkpoint <path>`
- 실행 스크립트: `./Infra/scripts/gharchive-watch.sh` (`-229`) — `flock -n`으로 중복
  실행을 거부하고 로그를 `.local/gharchive-watch/logs/`에 남긴다
- ⚠️ **crontab 등록은 아직 하지 않았다.** 붙여넣을 두 줄은
  [Historical Runbook §7.3](2026-09-12-github-historical-pipeline-runbook.md)에 있다.
  `AI/schedule.toml`은 채용공고 전용이므로 여기에 넣지 않는다
- 설계 주기: 시간당 1회 (`DEFAULT_PUBLICATION_LAG` 30분, `:30` 폴링 전제)
- **PASS**: 종료 코드 0, `not_yet_published`는 정상이고 `gap`은 확인 대상
- **gate**: D-3

### [D-3] publish — **실행 경로 있음 / 미등록**

- 실행 스크립트: `./Infra/scripts/gharchive-publish.sh` (`-229`) — watcher와 **별도
  checkpoint**(`publish-checkpoint.json`)를 쓰고, `KAFKA_BOOTSTRAP_SERVERS`가 없으면
  시작 단계에서 non-zero로 끝난다
- topic `github.events`, key = repo id, **원문 event 1건 = message 1건**(claim-check 아님)
- 시간 단위 all-or-nothing. 실패하면 checkpoint에 기록하지 않아 다음 회차가 재전송
- **PASS**: `failed` 0, `missing` 0
- **gate**: D-4

### [D-4] C1 Spark Structured Streaming — **실행 경로 있음 / 미기동**

- 상시 실행: `compose --profile data up -d spark-c1-archiver` (`-228`) —
  `restart: unless-stopped`가 프로세스 종료와 재부팅 복구를 담당한다
- 수동 단발: `./Infra/scripts/spark-c1-archiver.sh` (기본 `ONCE=1`)
- ⚠️ **이 서비스를 `--scale` 하지 않는다.** C1은 consumer group을 쓰지 않아
  checkpoint가 유일한 소유권 기록이고, 복제본이 늘면 둘 다 소유자라고 믿는다
- checkpoint: `hdfs:///gitjob/checkpoints/c1/{topic}` — **consumer group을 쓰지 않는다**
  (의도. `kafka-consumer-groups.sh --describe`에 C1이 안 나오는 것이 정상이고 lag 지표가 없다)
- 출력: `hdfs:///gitjob/parquet/stream/github.events` (`dt` 파티션),
  거부분 `…/stream/_rejected/github.events`
- **PASS**: 쿼리가 살아 있고 checkpoint offset이 전진, `_rejected`가 비정상 증가하지 않음
- **gate**: D-5

### [D-5] Weekly Repo Activity (streaming 입력) — `-224` 머지됨

```bash
spark-submit /opt/gitjob/spark/jobs/repo_activity_weekly.py \
  --input-format stream-parquet \
  --input hdfs:///gitjob/parquet/stream/github.events \
  --output hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-09/snapshot=<id> \
  --period-start 2026-09-01T00:00:00Z --period-end 2026-10-01T00:00:00Z
```

- **PASS**: stdout summary의 `input.format=stream-parquet`,
  `stream.observed_hour_count == stream.expected_hour_count`,
  `stream.below_cutoff_event_count == 0`
- **FAIL**: 누락 hour는 오류로 중단하고 빠진 hour를 나열한다.
  `--expected-files`는 stream에서 쓰이지 않는다 (part-file 수는 비결정적)
- **재실행**: 출력 경로가 있으면 거부. **새 snapshot id로 다시 실행한다**
- **gate**: D-6

### [D-6] manifest + completion event — `-225`·`-227` 머지됨

- 실행: `python -m github.weekly_activity_publish_cli --summary <json>
  --dataset-snapshot-id <id> [--dry-run]` (`-227`, worker 이미지)
- **먼저 `--dry-run`을 돌린다.** 첫 실전 실행이 불변 객체를 쓰므로 id 오타가 아무도
  의도하지 않은 디렉터리가 되고 `store_immutable`이 그것을 덮어쓰지 못하게 한다
- 순서: `DATA WRITE → read-back VERIFY → MANIFEST → COMPLETION EVENT`
- 주차당 `_SUCCESS.json` 1개 + 완료 이벤트 1건
- topic `gitjob.repo-activity-weekly.completed.v1`, payload 3필드
- **PASS**: 주차 디렉터리에 `_SUCCESS.json`, `row_digest.value`가 sha256,
  topic에 주차 수만큼 메시지
- **FAIL**: manifest 실패 시 이벤트가 나가지 않는 것이 정상 동작
- **gate**: E

---

## E. C조 handoff

### [E-1] manifest 검증

- C측 리더: [AI/github/snapshot_input.py](../../AI/github/snapshot_input.py) `load_published_snapshot`
- **PASS**: `_SUCCESS.json`의 객체별 `uri`가 같은 root이고 sha256이 일치
- Artifact Snapshot은 `objects{snapshot,summary,failures}`,
  Weekly Snapshot은 `row_digest`(`typed-json-v2`)

### [E-2] completion event 소비

- topic `gitjob.repo-activity-weekly.completed.v1`
- C조는 `(dataset_snapshot_id, week_start)`로 멱등 처리
- **PASS**: 이벤트 수신 후 해당 `manifest_uri`를 읽어 digest 검증까지 통과

### [E-3] C Trend 시작 조건

- Weekly는 exporter 경유: `Infra/spark/jobs/export_c_archive_activity.py`
  → ndjson/csv → `AI/trend/archive.py`
- ⚠️ exporter는 **spark-submit 수동 실행**이고 래퍼 스크립트도 호출자도 없다
- **PASS**: `ArchiveActivityMetadata`의 `dataset_snapshot_id`/`source_hash`/`period`가
  분모 정합성 검증(`reconcile_denominators`)을 통과
- **gate**: F

---

## F. Backend / API

### [F-1] 서비스 기동 확인

```bash
ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml \
PROFILES=core,app ./Infra/scripts/verify-deployment.sh
```

- **PASS**: postgres/redis/kafka/kafka-connect/backend/frontend/nginx 전부 healthy
- **gate**: F-2

### [F-2] 데이터가 API로 조회되는지

- 관리자 모니터링: `GET /api/v1/admin/monitoring/overview`,
  `GET /api/v1/admin/monitoring/timeseries?metric={cpu|memory|network}&range=60m`
- 분석 결과 조회는 C조 Snapshot을 읽는 B조 API
- **PASS**: 200 응답 + 비어 있지 않은 payload
- **FAIL**: backend 로그, `analysis_outbox` CDC 상태
- **gate**: G

---

## G. Frontend

### [G-1] 사용자 화면 확인

- **PASS**: 저장소 선택 → 분석 진행 → Evidence/추천/Trend 화면에 **실제 데이터**가 보임
- **FAIL**: 브라우저 네트워크 탭의 API 응답, nginx 로그
- ⚠️ `docs/2026-09-10-current-status.md`가 "실계정 로그인부터 C 결과까지 E2E"를
  **완료로 보지 않는 항목**으로 명시한다

---

## MVP 최종 PASS 조건

아래 **일곱 개가 동시에** 참이어야 MVP 정상화로 본다.

1. **HDFS** — Live DataNode 2, `fsck HEALTHY`, under-replicated 0, host `df` 여유 확보
2. **채용공고** — 4개 source 중 최소 1회차가 Raw → `analysis_input` → C intake까지 도달
3. **Historical** — 6개월 Raw에서 Repo Activity와 Weekly가 생성되고 read-back 통과
4. **Realtime** — `github.events` offset이 **0이 아니고 증가 중**이며 C1 checkpoint가 전진
5. **Weekly Snapshot** — 주차 디렉터리에 `_SUCCESS.json`이 있고 `row_digest` 검증 통과
6. **C handoff** — 완료 이벤트가 발행되고 C조가 manifest를 읽어 Trend 계산을 시작
7. **E2E** — Frontend 화면에 그 결과가 보임

### 지금 어디까지 와 있나 (`origin/develop` 01689e1 기준)

| 조건 | 상태 | 남은 것 |
|---|---|---|
| 1 HDFS | RF2 convergence 진행 중 | 완료 확인 |
| 2 채용공고 | 실행 경로 있음 | **crontab 등록** (8줄) |
| 3 Historical | **운영 검증됨** | — |
| 4 Realtime | 실행 경로 있음 | **토픽 생성** + **crontab 등록**(2줄) + **C1 기동** |
| 5 Weekly Snapshot | 실행 경로 있음 | 4 이후 |
| 6 C handoff | 실행 경로 있음 | 5 이후 |
| 7 E2E | — | 2·6에 종속 |

**코드로 막힌 곳은 더 이상 없다.** `-227`·`-228`·`-229`가 마지막 실행 경로 셋을
채웠고, 남은 것은 전부 *실행*이다 — 토픽 생성, crontab 등록, 첫 기동. 그리고 그
셋은 HDFS RF2 convergence가 끝난 뒤에 한다.
