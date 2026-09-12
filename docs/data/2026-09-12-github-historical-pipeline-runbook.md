# GitHub Historical Pipeline 운영·복구 Runbook

- Jira: `S15P21E102-165`
- 대상: GH Archive → HDFS Raw → Spark Repo Activity → Top-N →
  Repo Artifact Snapshot → C조 Analysis Input
- 성격: **실행·재개·검증 절차**. 각 단계가 왜 그렇게 설계됐는지는 링크한 검증
  문서에 있고 여기서 반복하지 않는다.
- 작성일: 2026-09-12

이 문서는 새로 합류한 팀원이 **문서만 보고** 파이프라인을 돌리고, 중단된 회차를
재개하고, 산출물이 맞는지 확인할 수 있게 하는 것이 목적이다.

이 문서에 적힌 명령과 경로는 전부 현재 `develop`의 스크립트·코드에서 확인한
것이다. 추정으로 만든 명령은 없다. 근거 파일을 각 절에 적어 두었으므로, 코드가
바뀌면 그 파일을 먼저 보고 이 문서를 고친다.

> **읽는 순서 주의** — §7의 수치는 대부분 **과거 검증 예시**다. 측정일이 붙어
> 있고, 그날의 클러스터 구성에서 나온 값이다. 현재 운영 상태는 §7.1의 확인
> 명령으로 직접 조회한다.

---

## 0. 이 문서를 쓰기 전에

### 0.1 관련 문서

| 문서 | 무엇이 있나 |
|---|---|
| [`docs/data/README.md`](README.md) §14 | GH Archive Historical 전체 서사, 설계 근거, sink 선택 이유 |
| [GH Archive 6개월 Historical Bootstrap 검증](2026-09-09-gharchive-six-month-bootstrap.md) | 2026-03~08 Raw 실측 (4,416 files / 660,081,904 events) |
| [6개월 Repo Activity 결과](2026-09-10-gharchive-six-month-repo-activity.md) | Repo Activity 실측과 read-back |
| [Repo Activity Top-N 검증 보고서](2026-09-02-repo-activity-topn-validation.md) | 2026-08 Top-N / Coverage 실측 |
| [GitHub Repo Snapshot 부트스트랩 배치](2026-09-04-repo-snapshot-bootstrap-batch.md) | Artifact 저장 경계와 publish 규칙 |
| [Repo Snapshot Production Canary 검증](2026-09-07-repo-snapshot-production-canary.md) | 운영 canary 실측, 동일 checkpoint 재실행 |
| [MVP 파이프라인 멱등성 및 Replay 검증](2026-09-07-mvp-pipeline-idempotency-replay.md) | 단계별 멱등성 판정 근거 |
| [주간 Repo Activity 집계](2026-09-12-repo-activity-weekly.md) | weekly 집계(-166) 입출력과 실행 |
| [A→C GitHub Repo Snapshot 계약](2026-09-02-a-to-c-github-repo-snapshot-contract.md) | C조 소비 계약 |
| [`docs/infra/2026-08-31-ec2-data-node-runbook.md`](../infra/2026-08-31-ec2-data-node-runbook.md) | data 서버 자체의 기동·`.env.data`·포트 |

### 0.2 책임 경계

A조는 Raw 확보, 구조 집계, Artifact 원문 수집, C조가 소비 가능한 Analysis Input
생성까지 한다. 기술명 정규화, `tech_id` 확정, Evidence Level 판정은 하지 않는다.
자세한 경계는 `PROJECT_GUIDE.md` §2.

---

## 1. 전체 흐름

```text
GH Archive (data.gharchive.org)
  │  python -m collector.gharchive  {plan,download,validate,upload}
  ▼
HDFS Raw            /gitjob/raw/gharchive/dt=YYYY-MM-DD/*.json.gz
  │  Infra/scripts/spark-repo-activity-topn.sh
  ▼
Repo Activity       /gitjob/parquet/github/repo_activity/period=…/snapshot=…/
  │                   ├── repo_activity/     (repo별 event_count, rank)
  │                   ├── topn_coverage/     (Top-N별 coverage)
  │                   └── data_quality/
  │  Infra/scripts/spark-repo-fetch-candidates.sh
  ▼
Top-N candidates    .local/repo-fetch-benchmark/candidates.json   (호스트 파일)
  │  Infra/scripts/repo-snapshot-bootstrap.sh
  ▼
Repo Artifact Snapshot
                    /gitjob/analysis_input/github/repo_snapshot/snapshot_id=…/
  ▼
C조 Analysis Input  (github-repo-snapshot/v1)
```

주간 집계(`repo_activity_weekly`)는 Raw에서 직접 갈라져 나오는 별도 경로이며 위
사슬의 중간 단계가 아니다 — §3.6.

월 단위로 위 사슬을 반복하는 자동화가 `repo-snapshot-monthly-top10k-chain.sh`다
— §3.7.

---

## 2. 주요 HDFS 경로

전부 코드에서 확인한 경로다. 첫 세그먼트(`gitjob`)는 **환경 격리 경계**이고 CI는
`gitjob-ci`를 쓴다(`.env.ci.example`). 임의로 새 root를 만들지 않는다.

| 계층 | 경로 | 근거 |
|---|---|---|
| Raw | `/gitjob/raw/gharchive/dt=YYYY-MM-DD/*.json.gz` | `AI/collector/gharchive/sinks.py` `DEFAULT_RAW_ROOT = "/gitjob/raw"` |
| Repo Activity | `/gitjob/parquet/github/repo_activity/period={YYYY-MM}/snapshot={id}/` | `spark-repo-activity-topn.sh` |
| ├ | `…/repo_activity/` | `Infra/spark/repo_activity_topn.py:451` |
| ├ | `…/topn_coverage/` | 같은 파일 `:452` |
| └ | `…/data_quality/` | 같은 파일 `:453` |
| Weekly Activity | `/gitjob/parquet/github/repo_activity_weekly/period={YYYY-MM}/snapshot={id}/` | [weekly 문서](2026-09-12-repo-activity-weekly.md) §4 |
| Analysis Input | `/gitjob/analysis_input/github/repo_snapshot/snapshot_id={id}/` | `repo-snapshot-bootstrap.sh` |
| ├ 원문 Artifact | `…/artifacts/` | `--webhdfs-artifact-root` |
| ├ Snapshot | `…/snapshot.json` | `AI/github/repo_snapshot_bootstrap.py:187` |
| ├ 실행 요약 | `…/run-summary.json` | 같은 파일 `:188` |
| ├ 실패 목록 | `…/failures.json` | 같은 파일 `:189` |
| └ 완료 매니페스트 | `…/_SUCCESS.json` | 같은 파일 `:210` |

호스트(서버 로컬) 산출물은 HDFS가 아니라 `.local/` 아래에 있고 Git에 올리지
않는다 — §3.8.

---

## 3. 정상 실행 절차

### 3.1 공통 환경

모든 `Infra/scripts/*.sh`는 `Infra/scripts/_lib.sh`의 규약을 따른다.

| 변수 | 기본값 | data 서버에서 쓰는 값 |
|---|---|---|
| `ENV_FILE` | `<repo>/.env.wsl` | `.env.data` |
| `COMPOSE_OVERRIDE_FILE` | `Infra/compose/compose.wsl.yaml` | `Infra/compose/compose.ec2-data.yaml` |
| `PROFILES` | `core` (없으면 `ENV_FILE`의 `COMPOSE_PROFILES`) | `data` |

따라서 data 서버에서의 호출 형태는 항상 이렇다.

```bash
ENV_FILE=.env.data \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
PROFILES=data \
  ./Infra/scripts/<script>.sh
```

이 세 값이 빠지면 스크립트는 WSL 기본값으로 동작한다. 조용히 다른 환경을
가리키는 대표적인 실수이므로 매 실행마다 명시한다.

HDFS를 읽는 명령은 NameNode 컨테이너에서 실행한다. collector/worker 이미지에는
Hadoop CLI도 JRE도 없다(의도된 slim 이미지 — `docs/data/README.md` §14).

```bash
compose exec -T hdfs-namenode hdfs dfs -ls /gitjob/raw/gharchive
```

여기서 `compose`는 `_lib.sh`의 helper(`docker compose --project-directory <repo>
--env-file $ENV_FILE -f compose.yaml -f $COMPOSE_OVERRIDE_FILE --profile …`)와
같은 인자를 뜻한다. 스크립트 밖에서 직접 칠 때는 같은 인자를 그대로 쓴다.

### 3.2 실행 전 확인

1. 다른 세션이 같은 클러스터에서 작업 중인지 확인한다. **DataNode
   decommission·rebalance 중에는 이 파이프라인을 시작하지 않는다.**
2. 프로필과 컨테이너 상태:
   ```bash
   ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
   PROFILES=data ./Infra/scripts/healthcheck.sh
   ```
3. HDFS 여유 공간. **판단 기준은 `dfsadmin -report`의 Configured Capacity가 아니라
   host `df`다** — 논리 DataNode들이 같은 물리 파일시스템을 공유한다.
   ```bash
   df -h /
   compose exec -T hdfs-namenode hdfs dfsadmin -report | head -20
   ```
4. 쓰려는 출력 경로가 이미 있는지 확인한다. 있으면 §4.2로 간다.
   ```bash
   compose exec -T hdfs-namenode hdfs dfs -test -e <output-path> && echo EXISTS
   ```
5. Artifact 단계를 돌 거라면 worker에 `GITHUB_API_TOKEN`이 있는지 확인한다.
   **값을 출력하지 않는다.**
   ```bash
   compose run --rm --no-deps -T repo-snapshot-bootstrap sh -c 'test -n "$GITHUB_API_TOKEN" && echo present'
   ```

### 3.3 1단계 — GH Archive → HDFS Raw

모듈: `python -m collector.gharchive` (`AI/collector/gharchive/__main__.py`).
하위 명령은 `plan`, `download`, `validate`, `upload`, `watch`, `publish`.
Historical bootstrap에서 쓰는 것은 앞의 넷이다. `watch`/`publish`는 P1 온라인
수집(`S15P21E102-144`) 경로이며 이 사슬에 넣지 않는다.

공통 인자:

| 인자 | 기본값 | 의미 |
|---|---|---|
| `--start` | `2026-08-01T00:00:00Z` | 포함 하한 (UTC 시각) |
| `--end` | `2026-09-01T00:00:00Z` | **제외** 상한 |
| `--historical-start` / `--historical-cutoff` | 위와 동일 | bootstrap 경계. 온라인 collector와 공유하는 값이라 함부로 바꾸지 않는다 |
| `--output-root` | `<repo>/.local/gharchive` | 로컬 다운로드 위치 |
| `--checkpoint` | 없음 | **회차마다 명시한다.** 재개의 유일한 근거 |

`upload` 전용:

| 인자 | env | 기본값 |
|---|---|---|
| `--webhdfs-url` | `WEBHDFS_URL` | 없음 (필수) |
| `--raw-root` | `RAW_ROOT` | `/gitjob/raw` |
| `--webhdfs-user` | `WEBHDFS_USER` | `hadoop` |

클러스터 밖에서 호출해 WebHDFS 307 redirect의 DataNode 이름이 풀리지 않으면
`WEBHDFS_DATANODE_HOSTS`로 매핑한다(`.env.example` 참고). data 노드 안에서 돌 때는
비워 둔다.

실행 순서는 월 단위로 끊는다. 예(2026-07):

```bash
run=.local/gharchive-<jira>/
python -m collector.gharchive plan \
  --start 2026-07-01T00:00:00Z --end 2026-08-01T00:00:00Z

python -m collector.gharchive download \
  --start 2026-07-01T00:00:00Z --end 2026-08-01T00:00:00Z \
  --checkpoint "$run/checkpoint.json" > "$run/2026-07-download.json"

python -m collector.gharchive validate \
  --start 2026-07-01T00:00:00Z --end 2026-08-01T00:00:00Z \
  --checkpoint "$run/checkpoint.json" > "$run/2026-07-validate.json"

python -m collector.gharchive upload \
  --start 2026-07-01T00:00:00Z --end 2026-08-01T00:00:00Z \
  --checkpoint "$run/checkpoint.json" > "$run/2026-07-upload.json"
```

**성공 판정** — 종료 코드와 요약 JSON 두 가지를 본다.

| 종료 코드 | 뜻 |
|---|---|
| `0` | `missing` 0, `invalid` 0 (upload는 `failed` 0). 정상 |
| `1` | 실행은 됐으나 누락·무효·실패가 있다. 요약 JSON을 본다 |
| `2` | checkpoint/HDFS/인자 오류. stderr에 `{"error": …}` |

요약 JSON에서 확인할 것: `expected`와 `completed` 일치, `missing` 0, `invalid` 0,
`failed` 0, `published_bytes`. 적재 방식은 **WebHDFS**가 기본이다
(`HdfsCliSink`는 배포 이미지에서 실행되지 않는다 — `docs/data/README.md` §14).

### 3.4 2단계 — Spark Repo Activity

```bash
ENV_FILE=.env.data \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
PROFILES=data \
GHARCHIVE_RAW_INPUT='hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz' \
REPO_ACTIVITY_OUTPUT='hdfs:///gitjob/parquet/github/repo_activity/period=2026-08/snapshot=<new-id>' \
GHARCHIVE_EXPECTED_FILES=744 \
  ./Infra/scripts/spark-repo-activity-topn.sh
```

| env | 기본값 | 비고 |
|---|---|---|
| `GHARCHIVE_RAW_INPUT` | `${RAW_ROOT}/gharchive/dt=2026-08-*/*.json.gz` | |
| `REPO_ACTIVITY_OUTPUT` | `…/period=2026-08/snapshot=s15p21e102-109-baseline` | **회차마다 새 id로 덮어 지정한다** |
| `GHARCHIVE_EXPECTED_FILES` | `744` | 월별 시간 수. 30일 달은 `720` |
| `REPO_ACTIVITY_TOP_N` | `100,500,1000,3000,5000,10000,20000` | |
| `HDFS_URI` / `RAW_ROOT` / `PARQUET_ROOT` / `SPARK_MASTER_URL` | `.env`에서 읽음 | |

출력은 `{REPO_ACTIVITY_OUTPUT}/` 아래 `repo_activity/`, `topn_coverage/`,
`data_quality/` 세 개다.

**성공 판정**: 표준출력에 JSON summary 한 덩어리가 나온다. `output.root`,
`input.*`, `parquet_file_count`, `parquet_bytes`와 행 수가 들어 있다. job은 쓰기
직후 스스로 read-back 해서 행 수가 달라지면 예외로 죽는다
(`repo_activity_topn.py:631`). 즉 **summary가 나왔다는 것 자체가 read-back
통과를 뜻한다.** summary는 파일로 남겨 둔다.

### 3.5 3단계 — Top-N candidates

```bash
ENV_FILE=.env.data … PROFILES=data \
REPO_ACTIVITY_INPUT_ROOT='hdfs:///gitjob/parquet/github/repo_activity/period=2026-08/snapshot=<2단계와 동일한 id>' \
REPO_FETCH_PHASE_TOP_N=20000 \
REPO_FETCH_CANDIDATES_OUTPUT="$PWD/.local/repo-fetch-monthly/2026-08/candidates.json" \
  ./Infra/scripts/spark-repo-fetch-candidates.sh
```

> **주의 — 기본값끼리 연결되지 않는다.** `spark-repo-activity-topn.sh`의 출력
> 기본값은 `snapshot=s15p21e102-109-baseline`인데
> `spark-repo-fetch-candidates.sh`의 입력 기본값은
> `snapshot=s15p21e102-109-20260902`다. 기본값만 믿고 순서대로 실행하면 3단계가
> 2단계 산출물을 읽지 않는다. **`REPO_ACTIVITY_INPUT_ROOT`를 2단계 출력과 같은
> 값으로 반드시 명시한다.**

| env | 기본값 |
|---|---|
| `REPO_FETCH_COVERAGE_N` | `20000,50000,100000,200000,300000,500000` |
| `REPO_FETCH_SAMPLE_SIZE` | `50` |
| `REPO_FETCH_CANDIDATE_MODE` | `stratified` |
| `REPO_FETCH_PHASE_TOP_N` | `20000` |
| `REPO_FETCH_CANDIDATES_OUTPUT` | `<repo>/.local/repo-fetch-benchmark/candidates.json` |

산출물은 HDFS가 아니라 **호스트 파일**이다. 스크립트가 컨테이너에서
`compose cp`로 꺼내 온다. 이 파일이 4단계의 불변 입력이 된다.

### 3.6 (선택) 주간 Repo Activity

2단계와 병렬인 별도 집계다. 사슬의 필수 단계가 아니다.

```bash
spark-submit /opt/gitjob/spark/jobs/repo_activity_weekly.py \
  --input 'hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz' \
  --output hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-08/snapshot=<new-id> \
  --expected-files 744 \
  --period-start 2026-08-01T00:00:00Z \
  --period-end 2026-09-01T00:00:00Z
```

`--join-ids LABEL=PATH`는 반복 가능한 선택 인자다. 상세와 스키마는
[주간 Repo Activity 집계](2026-09-12-repo-activity-weekly.md).

### 3.7 4단계 — Repo Artifact Snapshot

```bash
ENV_FILE=.env.data \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
PROFILES=data \
REPO_SNAPSHOT_ID=<snapshot-id> \
REPO_PIPELINE_RUN_ID=<pipeline-run-id> \
REPO_FETCH_CANDIDATES_OUTPUT="$PWD/.local/repo-fetch-monthly/2026-08/candidates.json" \
REPO_FETCH_PHASE_TOP_N=20000 \
REPO_ACTIVITY_PERIOD_START=2026-08-01 \
REPO_ACTIVITY_PERIOD_END=2026-08-31 \
  ./Infra/scripts/repo-snapshot-bootstrap.sh
```

필수:

- `REPO_SNAPSHOT_ID` — 경로에 그대로 들어간다. `^[A-Za-z0-9][A-Za-z0-9._-]*$`만
  허용. **재개할 때 반드시 같은 값을 쓴다.**
- `REPO_PIPELINE_RUN_ID` — 마찬가지로 재개 간 고정.
- worker의 `GITHUB_API_TOKEN` — 없으면 스크립트가 시작 단계에서 죽는다.

선택: `REPO_BOOTSTRAP_STATE_ROOT`(기본 `<repo>/.local/repo-snapshot-bootstrap`),
`REPO_REQUIRE_HISTORICAL_HEAD=1`, `WEBHDFS_URL`, `WEBHDFS_USER`.

**성공 판정**:

| 종료 코드 | 뜻 | 다음 행동 |
|---|---|---|
| `0` | 전량 terminal + publish 완료 | §5로 검증 |
| `2` | 미완 (rate limit 한도 초과 등) | §4.1로 재개 |

publish가 끝나면 HDFS에 `snapshot.json`, `run-summary.json`, `failures.json`,
`_SUCCESS.json`이 올라간다. 각 객체는 write 직후 read-back 비교를 통과해야 하고,
불일치하면 `WebHDFS read-back mismatch: <name>`으로 죽는다
(`repo_snapshot_bootstrap.py:195`).

#### 월 단위 자동화 (S15P21E102-194)

2~4단계를 여러 달에 대해 detach 상태로 이어 돌리는 chain이 있다.

```bash
ENV_FILE=.env.data … PROFILES=data \
  ./Infra/scripts/repo-snapshot-monthly-top10k-chain.sh
```

`flock`으로 중복 실행을 막고(`.local/gharchive-monthly-artifact/.chain.lock`),
durable checkpoint와 HDFS 게이트가 진행의 근거다. **tmux 세션과 Spark
application id는 참고 정보일 뿐 진행 상태의 근거가 아니다**(스크립트 헤더 주석).

### 3.8 산출물·로그 위치 정리

HDFS 경로는 §2. 호스트 쪽은 전부 `.local/` 아래이며 Git에 올리지 않는다.

| 무엇 | 위치 |
|---|---|
| GH Archive 로컬 다운로드 | `.local/gharchive/` (`--output-root`) |
| GH Archive checkpoint / 회차 요약 | `--checkpoint`로 지정한 경로. 관례상 `.local/gharchive-<jira>/` |
| Artifact 회차 상태 루트 | `.local/repo-snapshot-bootstrap/<snapshot_id>/` |
| ├ 불변 입력 사본 | `…/candidates.json` |
| ├ 재개 근거 | `…/checkpoint.json`, `…/state.json` |
| ├ 최종 Snapshot | `…/snapshot.json` |
| ├ 실행 요약 | `…/run-summary.json` |
| └ 실패 목록 | `…/failures.json` |
| Repo/SHA 캐시 (회차 공용) | `.local/repo-snapshot-bootstrap/cache.json` |
| Top-N candidates | `.local/repo-fetch-benchmark/candidates.json` 또는 `REPO_FETCH_CANDIDATES_OUTPUT` |
| 월 chain 상태 | `.local/gharchive-monthly-artifact/chain-state.json` |
| 월 chain 마커·요약 | `…/pass-markers/`, `…/summaries/` |
| 월 chain 로그 | `…/logs/activity-<month>.log`, `…/logs/artifact-<month>.log` |

---

## 4. 재실행 / 장애 복구

### 4.1 중단된 회차 재개

**핵심 규칙: 같은 `REPO_SNAPSHOT_ID`, 같은 `REPO_PIPELINE_RUN_ID`, 같은
candidates 파일로 같은 명령을 다시 실행한다.** 재개 전용 플래그는 없다.

각 단계의 재개 근거는 다음과 같다.

| 단계 | 재개 근거 | 이미 끝난 작업은 |
|---|---|---|
| 1. GH Archive | `--checkpoint` JSON의 시간별 상태 | 다시 받지 않는다. sink는 `-test -e`로 확인 후 skip |
| 2. Repo Activity | 없음(원자적 단위) | 출력 경로가 있으면 **시작 단계에서 거부**된다 — §4.2 |
| 3. candidates | 없음 | 같은 입력이면 결과가 같다 |
| 4. Artifact | `checkpoint.json` + `state.json` + `cache.json` | fetch 요청 0건으로 넘어간다 |

4단계 재개 시 스크립트가 먼저 하는 일은 candidates 비교다.

```text
candidate file differs from the immutable snapshot input
```

이 오류는 **회차의 입력이 바뀌었다**는 뜻이다. 후보 목록을 바꾸고 싶으면 같은
snapshot_id로 이어 돌리면 안 되고 새 snapshot_id로 시작해야 한다.

이미 최종 Snapshot을 쓴 뒤 재개했는데 내용이 달라지면 이렇게 죽는다.

```text
frozen final Snapshot differs from resumed checkpoint
```

조용히 덮어쓰지 않고 멈추는 것이 의도된 동작이다. 원인을 규명하기 전에는 파일을
지우지 않는다.

### 4.2 immutable output 충돌

2단계는 쓰기 전에 출력 경로 존재를 검사하고, Spark 쓰기 자체도
`mode("errorifexists")`다(`repo_activity_topn.py:288,454,486,532`).

```text
output already exists; refusing to overwrite: hdfs:///gitjob/parquet/github/repo_activity/period=…/snapshot=…
```

처리 방법은 **하나뿐이다 — 새 `snapshot=` 값으로 다시 실행한다.** 기존 경로를
지우고 같은 id로 다시 쓰지 않는다. Snapshot overwrite 금지는 `PROJECT_GUIDE.md`
§3의 규칙이고, 이미 그 id를 참조한 하위 산출물·문서가 있을 수 있다.

4단계 publish도 같은 원칙이지만 조금 다르게 동작한다. `store_immutable`은 같은
경로에 **같은 내용**이면 그대로 성공으로 넘어가고(재개 시 정상), **다른 내용**이면
`FileExistsError: immutable WebHDFS object exists with different content`로 죽는다
(`AI/common/webhdfs.py:258`).

### 4.3 Rate Limit 대기와 `active` / `wall` 구분

GitHub core rate limit에 걸리면 bootstrap은 실패하지 않고 reset까지 대기한 뒤
이어서 진행한다. `run-summary.json` / `state.json`에 남는 필드:

| 필드 | 뜻 |
|---|---|
| `active_runtime_seconds` | 실제로 API를 호출하며 일한 시간 |
| `rate_limit_wait_count` | 대기에 들어간 횟수 |
| `rate_limit_wait_seconds` | 대기로 보낸 총 시간 |
| `wall_runtime_seconds` | `active + rate_limit_wait_seconds` |

**해석 규칙: 진척과 비용 추정은 `active`로 하고, 일정 예측은 `wall`로 한다.**
`wall`이 길다고 해서 처리량이 나쁜 것이 아니다. 대기 시간이 반영된 값이다.

한 번 대기 예상 시간이 `max_wait_seconds`(기본 **7,200초 = 2시간**)를 넘으면
대기하지 않고 미완으로 종료한다(종료 코드 `2`). 재개하면 저장해 둔
`next_resume_epoch`까지 기다렸다가 이어서 돈다
(`repo_snapshot_bootstrap.py:300`).

### 4.4 실패 Repo 확인과 재처리 기준

`failures.json`(호스트·HDFS 양쪽)과 `run-summary.json`을 본다.

```bash
python -m json.tool .local/repo-snapshot-bootstrap/<snapshot_id>/run-summary.json
python -m json.tool .local/repo-snapshot-bootstrap/<snapshot_id>/failures.json | head -40
```

**먼저 알아야 할 것 — terminal은 "성공"이 아니라 "이 회차에서 더 건드리지
않는다"는 뜻이다.** `AI/github/repo_fetch_orchestrator.py:51`의
`TERMINAL_STATUSES`는 여섯 개다.

```text
COMPLETE  PARTIAL  FAILED  NOT_FOUND  REUSED  HISTORICAL_HEAD_UNAVAILABLE
```

`FAILED`와 `NOT_FOUND`도 terminal이다. 따라서 **같은 snapshot_id로 재개해도 이미
`FAILED`로 기록된 Repo는 다시 시도되지 않는다.** 재개가 이어서 처리하는 것은
아직 terminal에 도달하지 않은 항목(미착수, rate limit으로 끊긴 지점)뿐이다.
publish는 후보 전부가 terminal이 됐을 때 일어나므로, 실패가 섞인 채로도 회차는
완료될 수 있다.

판단 기준:

| 상태 | 뜻 | 재처리 |
|---|---|---|
| `COMPLETE` | 정상 수집 | 불필요 |
| `REUSED` | 동일 Repo/SHA/정책이라 캐시 재사용 | 불필요 |
| `NOT_FOUND` | 404. Repository·계정 소멸 | **하지 않는다.** 아래 각주 참조 |
| `PARTIAL` | 예산 상한·truncation으로 부분 수집 | 정책을 바꿔 다시 받으려면 **새 snapshot_id로 새 회차**를 연다 |
| `FAILED` | 수집 실패 | 재개로는 안 된다. 원인을 보고 새 회차를 열지 판단한다 |
| `HISTORICAL_HEAD_UNAVAILABLE` | 기간 기준 HEAD를 못 잡음 | `REPO_REQUIRE_HISTORICAL_HEAD` 정책과 함께 판단 |

`NOT_FOUND`를 재처리하지 않는 근거: rename fallback은 production에 넣지 않기로
했다. 실측에서 표본 50개 중 22개(44%)가 404였고 `repo_id`로 회수된 것은 0/22였다
— [Repo Fetch Cost Benchmark](2026-09-02-repo-fetch-cost-benchmark.md).

**`PARTIAL`을 "기술 없음"으로 해석하지 않는다**(`PROJECT_GUIDE.md` §5). C조에
넘길 때 이 구분을 반드시 같이 전달한다 — §5.5.

일시적 오류(타임아웃, 5xx)로 끊긴 실행은 해당 Repo가 아직 terminal이 아니므로
재개가 이어받는다. 이미 `FAILED`가 찍혔다면 그 회차 안에서는 되돌릴 수 없다.

### 4.5 partial / failed 상태 조회

```bash
# 회차가 어디까지 갔나
python -m json.tool .local/repo-snapshot-bootstrap/<snapshot_id>/state.json

# publish까지 갔나 (HDFS)
compose exec -T hdfs-namenode hdfs dfs -ls \
  /gitjob/analysis_input/github/repo_snapshot/snapshot_id=<snapshot_id>/

# 월 chain은 어디까지 갔나
python -m json.tool .local/gharchive-monthly-artifact/chain-state.json
```

`_SUCCESS.json`이 없으면 그 snapshot은 **완료되지 않은 것**이다. C조에 넘기지
않는다.

---

## 5. 검증

### 5.1 HDFS read-back

```bash
# 파일 수와 바이트
compose exec -T hdfs-namenode hdfs dfs -count /gitjob/raw/gharchive/dt=2026-08-01
compose exec -T hdfs-namenode hdfs dfs -du -s /gitjob/raw/gharchive

# 블록 건강도 (read-only)
compose exec -T hdfs-namenode hdfs fsck /gitjob
compose exec -T hdfs-namenode hdfs dfsadmin -report
```

`fsck`는 `HEALTHY`, missing/corrupt blocks 0이어야 한다. under-replicated는
DataNode 구성 변경 중에는 수렴 중일 수 있으므로 인프라 담당과 확인한다.

### 5.2 `_SUCCESS` / manifest

`_SUCCESS.json`은 단순한 빈 마커가 아니라 **객체별 sha256을 담은 매니페스트**다
(`repo_snapshot_bootstrap.py:199`).

```bash
compose exec -T hdfs-namenode hdfs dfs -cat \
  /gitjob/analysis_input/github/repo_snapshot/snapshot_id=<id>/_SUCCESS.json
```

```json
{
  "schema_version": "github-repo-snapshot-publish-manifest/v1",
  "dataset_snapshot_id": "<id>",
  "objects": {
    "snapshot": {"uri": "hdfs://…/snapshot.json", "sha256": "…"},
    "summary":  {"uri": "hdfs://…/run-summary.json", "sha256": "…"},
    "failures": {"uri": "hdfs://…/failures.json", "sha256": "…"}
  }
}
```

### 5.3 checksum 대조

매니페스트의 sha256과 실제 객체를 대조한다.

```bash
compose exec -T hdfs-namenode hdfs dfs -cat \
  /gitjob/analysis_input/github/repo_snapshot/snapshot_id=<id>/snapshot.json \
  | sha256sum
```

Parquet은 파일 바이트가 실행마다 달라진다(빌드 문자열과 part-file UUID가 박힌다).
두 회차를 비교할 때는 `hdfs dfs -checksum`이 아니라 **행 기준 digest**를 쓴다.

```bash
INPUT=hdfs:///gitjob/parquet/github/repo_activity/period=2026-08/snapshot=<id>/repo_activity \
  ./Infra/scripts/spark-dataset-digest.sh
```

### 5.4 row count / null / duplicate

2단계 job이 스스로 만드는 것을 쓴다.

- job summary(stdout)의 행 수와 `parquet_file_count` / `parquet_bytes`
- `data_quality/` — 무효·null repo 식별자 집계
- `topn_coverage/` — Top-N별 `selected_repo_count`, `coverage_valid`,
  `coverage_total`
- job 내부 read-back 행 수 대조 — 불일치 시 예외(`repo_activity_topn.py:631`)

중복 rank 확인은 `topn_coverage`의 단조성과 `repo_activity`의 `rank` 유일성으로
본다. 6개월 회차에서 duplicate rank 0이 확인된 전례가 있다
([6개월 Repo Activity 결과](2026-09-10-gharchive-six-month-repo-activity.md)).

### 5.5 소비 계약 / C조 handoff

C조에 넘길 때 전달하는 것은 파일이 아니라 **식별자 + URI + checksum** 세 가지다.

1. `dataset_snapshot_id` — `_SUCCESS.json`의 값
2. `snapshot.json`의 HDFS URI — `_SUCCESS.json` `objects.snapshot.uri`
3. sha256 — `_SUCCESS.json` `objects.snapshot.sha256`

스키마는 `docs/data/contracts/github-repo-snapshot-v1.schema.json`이고 계약
설명은 [A→C GitHub Repo Snapshot 계약](2026-09-02-a-to-c-github-repo-snapshot-contract.md).
Fixture는 `AI/github/fixtures/github_repo_snapshot_v1.json`.

handoff 전 확인:

- `_SUCCESS.json`이 존재한다
- `failures.json`을 함께 전달한다 (실패가 있다는 사실을 숨기지 않는다)
- `PARTIAL` 항목의 의미를 명시한다 — 기술 없음이 아니라 수집 불완전

---

## 6. 금지사항 / 주의사항

**절대 하지 않는다**

- NameNode format (`hdfs namenode -format`). 기존 Raw 전량을 잃는다.
- 기존 snapshot 경로 overwrite. 충돌하면 새 id로 간다 — §4.2.
- 검증 없이 HDFS volume·named volume 삭제.
- 운영 경로에서 `hdfs dfs -rm -r`. 특히 `/gitjob/raw`는 재수집에 수십 시간이
  든다(6개월 = 111.9 GiB 압축).
- `.env.*`, 토큰, PAT를 문서·로그·커밋에 넣기. 토큰 확인은 존재 여부만 본다 —
  §3.2.
- 같은 snapshot_id로 candidates를 바꿔 재개하기.
- `PARTIAL`을 "해당 기술 없음"으로 해석하기.
- A조 산출물에 `tech_id`·Evidence Level·Required/Preferred 판정 넣기.

**주의**

- **DataNode decommission·rebalance 중에는 이 파이프라인을 시작하지 않는다.**
  진행 중이면 인프라 담당과 먼저 확인한다.
- `ENV_FILE` / `COMPOSE_OVERRIDE_FILE` / `PROFILES` 셋을 매번 명시한다. 빠지면
  WSL 기본값으로 조용히 다른 환경을 가리킨다.
- 3단계 입력을 기본값에 맡기지 않는다 — §3.5의 경고.
- 여유 공간 판단은 host `df`로 한다. `dfsadmin -report`의 capacity는 같은
  파일시스템을 공유하는 논리 DataNode들의 합산값이라 과대평가된다.
- 월 chain은 `flock`을 쓴다. 두 번째 실행은 즉시 거부되는 것이 정상이다.
- `WebHdfsSink`에는 재시도/backoff가 없다. 실측에서 오류 0건이었기 때문에 넣지
  않았다 — 오류가 관측되면 그때 최소 구현을 검토한다.

---

## 7. 데이터 기준

### 7.1 현재 운영 상태 — 조회로 확인한다

**이 문서는 현재 클러스터의 수치를 박아 두지 않는다.** DataNode 구성이 바뀌는
중이면 문서에 적힌 숫자가 곧 틀리기 때문이다. 아래로 직접 확인한다.

```bash
compose exec -T hdfs-namenode hdfs dfsadmin -report    # live DataNode, capacity
compose exec -T hdfs-namenode hdfs fsck /gitjob        # 블록 건강도
compose exec -T hdfs-namenode hdfs dfs -du -s -h /gitjob/raw /gitjob/parquet /gitjob/analysis_input
df -h /                                                 # 물리 여유 공간 (판단 기준)
```

서버·네트워크·포트 구성은 [data node runbook](../infra/2026-08-31-ec2-data-node-runbook.md),
2호스트 분산 구성의 경위는 `docs/infra/2026-09-1*-hdfs-spark-two-host-*.md` 계열
문서에 있다.

### 7.2 과거 검증 예시 — 재현되지 않는 값

아래는 **그 날짜, 그 구성에서 측정된 값**이다. 현재 상태가 아니고, 지금 다시
돌렸을 때 같은 수치가 나온다는 보장도 없다. 규모 감각과 sanity check 용도로만
쓴다.

**GH Archive Raw 6개월** (측정 2026-09-09, `S15P21E102-179`)

| 항목 | 값 |
|---|---:|
| 기간 | 2026-03-01 ~ 2026-08-31 UTC |
| expected / HDFS files | 4,416 / 4,416 |
| missing / duplicate / invalid | 0 / 0 / 0 |
| 압축 | 120,146,905,981 B (약 111.90 GiB) |
| 해제 | 622,296,167,176 B (약 579.56 GiB) |
| 이벤트 | 660,081,904 |

2026-08은 재다운로드 없이 기존 744시간을 **재사용(REUSED)**했다. 상세는
[6개월 Bootstrap 검증](2026-09-09-gharchive-six-month-bootstrap.md).

**Repo Activity 6개월** (측정 2026-09-09, `S15P21E102-193`)

| 항목 | 값 |
|---|---:|
| input files | 4,416 |
| raw events | 660,081,904 |
| valid repo events | 660,076,996 |
| invalid / null | 4,908 |
| unique repos | 47,466,125 |
| duplicate rank | 0 |

**Repo Activity 2026-08 1개월** (측정 2026-09-02, `S15P21E102-109`)

| 항목 | 값 |
|---:|---:|
| input files / events | 744 / 87,516,869 |
| unique repos | 5,711,133 |
| Top-20,000 valid coverage | 24.5638% |

**Artifact Fetch 비용** (측정 `S15P21E102-104`)

| 항목 | 값 |
|---|---|
| Repo 1개 수집 | core 3.00회 / 2.47 MB / 2.63 s |
| 404 Repo | core 1.00회 |
| 동일 SHA 재검증 | core 1.00회 (−66.7%) |
| 404 비율(표본 50) | 22개 (44%) |

**단일 호스트 시절 Runtime 예시** (측정 2026-09-01) — 현재 구성과 다르다.
Live DataNode 1, Spark worker 1, `fs.defaultFS = hdfs://hdfs-namenode:8020`.
3시간 표본 적재에서 read-back sha256 3/3 MATCH, 재적재 시 `-put` 0회.
`docs/data/README.md` §14 참조.

---

## 8. 이 문서의 한계

- 명령은 현재 `develop`의 스크립트 인자에서 그대로 옮긴 것이고, 이 문서를 쓰면서
  **파이프라인을 실행하지는 않았다**(DataNode decommission 중). 실행 결과 예시는
  전부 기존 검증 문서의 실측이다.
- `S15P21E102-165`가 요구한 "Production 실측 결과 반영"은 §7.2의 기존 실측을
  인용하는 형태로 충족했다. 새 회차를 돌려 얻은 수치는 없다.
- `TERMINAL_STATUSES`(`AI/github/repo_fetch_orchestrator.py:51`)와
  `run-summary.json`의 전체 필드 목록은 코드가 단일 근거다. 상태나 필드가 늘면
  §4.3/§4.4 표를 갱신한다.
- 실패한 Repo를 회차 안에서 되돌리는 경로는 현재 없다. 운영하며 필요해지면 별도
  Jira로 다룬다 — 이 문서는 현재 동작만 기술한다.
