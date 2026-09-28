# 주간 Repo Activity 집계 (S15P21E102-166)

- Jira: `S15P21E102-166`
- 작성일: 2026-09-12
- 구현: `Infra/spark/jobs/repo_activity_weekly.py`
- 테스트: `AI/tests/test_repo_activity_weekly.py`
- 계보: `S15P21E102-109` Repo Activity Top-N → 이 문서 → `S15P21E102-203` C Archive Activity Export → `S15P21E102-201` C `trend.archive`

> **이 문서의 수치 구분**
>
> §7 "기존 운영 기록"은 **2026-09-08 운영 실행에서 이미 기록된 값**이며 이번 작업에서
> 재실행·재검증하지 않았다. 이번 세션에서 실제로 실행한 것은 §6의 local unit test뿐이다.
> 운영 Spark 실행, HDFS write, image rebuild는 하지 않았다.

## 1. 왜 주간 집계가 따로 필요한가

`Infra/spark/repo_activity_topn.py`(-109)는 기간 전체를 repository 하나당 한 행으로
접는다. Top-N 선정에는 맞지만 추세에는 쓸 수 없다 — 기간 **안의 어느 시점에** 그
repository가 활동했는지를 말할 수 없기 때문이다. 이 job은 -109와 같은 방식으로 Raw를
읽되(4개 필드, 입력 1행 = event 1건, repository 내용은 보지 않음) `week_start` 축을
추가한다.

## 2. 입력

입력은 두 가지이고 **출력은 하나의 계약으로 수렴한다**. `--input-format`이
reader와 completeness gate만 바꾸며, `typed` 이후의 집계·품질·coverage·출력은
공유한다(`S15P21E102-224`).

```text
Historical   Raw JSON (.json.gz)    < HISTORICAL_CUTOFF  ─┐
                                                          ├─→ ACTIVITY_COLUMNS
Realtime     Streaming Parquet     >= HISTORICAL_CUTOFF  ─┘   (repo_id, repo_name,
                                                               event_count, week_start)
```

### 2.1 `--input-format raw-json` (기본, `S15P21E102-166`)

| 항목 | 값 |
|---|---|
| 기본 입력 | `hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz` |
| 기본 기간 | `2026-08-01T00:00:00Z` ~ `2026-09-01T00:00:00Z` (end exclusive) |
| 허용 기간 | `2026-03-01T00:00:00Z` ~ `2026-09-01T00:00:00Z` (-193이 검증한 Historical Raw 구간) |
| 읽는 필드 | `repo.id`, `repo.name`, `type`, `created_at` (+ `_corrupt_record`) |
| completeness gate | `--expected-files` (2026-08 = 744시간) |

`_corrupt_record`는 malformed JSON 측정용이며 grouping key에 절대 들어가지 않는다.

### 2.2 `--input-format stream-parquet` (`S15P21E102-224`)

| 항목 | 값 |
|---|---|
| 기본 입력 | `hdfs:///gitjob/parquet/stream/github.events` (C1 Archiver 출력) |
| 허용 기간 | `2026-09-01T00:00:00Z` 이상, 상한 없음 |
| 읽는 컬럼 | `source`, `source_id`, `schema_version`, `event_type`, `occurred_at`, `payload` |
| completeness gate | expected hour coverage (§2.4) |

C1은 payload를 해석하지 않고 도착한 JSON 텍스트를 그대로 싣는다. 이 job이 그
payload를 여는 첫 소비자이며, Raw reader가 만드는 것과 같은 4개 컬럼으로 맞춘다.

| Raw reader | Stream reader |
|---|---|
| `repo.id` | `get_json_object(payload, '$.repo.id')` |
| `repo.name` | `get_json_object(payload, '$.repo.name')` |
| `type` | `event_type` (승격 컬럼) |
| `created_at` | `occurred_at` (승격 컬럼) |
| `_corrupt_record` | `get_json_object(payload, '$')`가 null인 payload |

`event_type`과 `occurred_at`은 승격 컬럼을 쓴다. payload를 다시 열어 같은 값을
꺼내면 두 값이 어긋날 수 있는 자리가 하나 더 생기고, 봉투가 계약이다(`-103` §4.1).

### 2.3 중복 제거 — `(source, source_id, schema_version)`

Raw는 시간당 파일 하나가 그대로 한 번 읽히므로 중복이 구조적으로 없다. Streaming은
다르다. 발행자는 한 시간을 **전부 보낸 뒤에야** checkpoint에 기록하므로, 도중에
실패하면 다음 회차가 그 시간을 다시 보내고 이미 들어간 부분이 중복된다
(`AI/collector/gharchive/events.py`).

그래서 집계 전에 `-102` §4.1이 정한 consumer 측 dedup key로 제거한다. `event_id`
단독이 아니라 **세 값의 조합**이다 — C2도 같은 세 값으로 dedup하므로 여기서 더 좁은
키를 새로 만들면 두 소비자의 판단이 갈린다.

`source_id`는 `"{hour_key}/{event_id}"`이므로 같은 event id라도 다른 시간에서 온
것은 다른 event로 남는다.

### 2.4 Completeness gate — 파일 수가 아니라 hour coverage

Raw의 744는 사실이다. GH Archive가 UTC 시간당 파일 하나를 발행하고 그 수를 세면
된다. **Streaming Parquet의 part-file 수는 같은 의미를 갖지 않는다** — Spark가 배치
크기와 partition 수에 따라 정하므로 같은 데이터가 실행마다 다른 파일 수로 쓰인다.

대신 **요청한 기간의 UTC hour가 모두 있는지**를 본다.

- expected: `[period_start, period_end)`의 모든 UTC hour (`expected_stream_hours`)
- observed: `substring_index(source_id, '/', 1)`의 distinct 값
- 하나라도 비면 `RuntimeError`로 중단하고 빠진 hour를 나열한다(최대 20개 표시)

새 metadata 체계를 만들지 않았다. `source_id`의 hour 접두사는 **발행자가 자기
checkpoint에 기록하는 바로 그 단위**이고, `-105`/`-179`가 "expected hours 4,416"으로
센 단위와 같다.

한계: 어떤 시간에 event가 0건이면 빠진 것과 구분되지 않는다. 실측 평균이 시간당
약 117,600건(`-105`)이므로 실제로 0건인 시간은 관측된 적이 없고, 그런 시간이 생기면
누락으로 보고된다.

### 2.5 cutoff 경계 — 같은 시간을 두 번 세지 않는다

`-102` §2.4가 경계를 정한다: cutoff 이전은 Raw, cutoff 이후는 Kafka. 이 job은 그
경계를 두 겹으로 지킨다.

1. **구조적 보장** — `validate_period`가 입력 포맷별로 기간을 거부한다.
   `raw-json`은 `period_end > cutoff`를, `stream-parquet`은
   `period_start < cutoff`를 거부한다. 두 경로가 같은 시간을 요청할 수 없다.
2. **관측 가능한 방어** — stream 입력에 cutoff 미만 event가 실제로 있으면 조용히
   버리지 않고 개수와 함께 중단한다. `c1_archiver_stream`이 자기 guard에 적용하는
   규칙과 같다 — 경계가 어긋난 발행자가 조용한 성공처럼 보이면 안 된다.

`dt` 파티션(C1의 `occurred_at` 날짜)은 스캔 범위를 좁히는 데만 쓴다. 소속 판정은
`occurred_at`의 정확한 비교가 한다.

### 2.6 late-arriving event — 현재는 반영되지 않는다

주차 출력은 immutable snapshot이고 `errorifexists`로만 쓴다. 따라서 **이미 publish된
주차에 뒤늦게 도착한 event는 그 snapshot에 반영되지 않는다.**

이번 범위에서는 watermark나 snapshot versioning을 만들지 않았다. 현재 설계 안에서
가능한 최소 정책은 하나다 — 해당 주차를 포함하는 기간으로 **새 snapshot_id를 만들어
다시 집계한다.** 기존 snapshot은 덮어쓰지 않으며, 두 snapshot 중 어느 것을 쓸지는
C조가 `dataset_snapshot_id`로 고른다.

이것이 충분하지 않다고 판단되면 후속 Jira로 다룬다. 이 문서가 현재 동작을 숨기지
않기 위해 여기에 적는다.

## 3. 주차 기준과 timezone

| 항목 | 규칙 |
|---|---|
| 주 시작 | **월요일** |
| timezone | **UTC** (`spark.sql.session.timeZone=UTC`) |
| Spark 표현 | `date_format(date_trunc('week', created_at), 'yyyy-MM-dd')` |
| 순수 함수 | `week_start_of(created_at)` — Spark 없이 동일 경계를 계산 |
| 경계 예 | `2026-08-09T23:59:59Z` → `2026-08-03`, `2026-08-10T00:00:00Z` → `2026-08-10` |

월요일은 C 소비자가 요구하는 값이다. `AI/trend/archive.py`의 `_period_index()`는
`WEEK` period가 월요일이 아니면 `WEEK period must start on Monday`로 거절한다.

offset이 붙은 `created_at`(`+09:00` 등)은 UTC로 변환한 뒤 주차를 판정한다. timezone이
없는 naive 값은 **거절**한다 — zone을 추측하면 event가 말없이 다른 주로 넘어간다.

### 부분 주차

달의 시작·끝이 월요일인 경우는 없으므로 어떤 기간이든 첫 주와 마지막 주는 부분 주차다.
`week_start`의 의미는 "이 event들이 발생한 주"이므로 부분 주차를 버리면 실제 event를
버리는 것이고, 말없이 포함하면 3일짜리 주와 7일짜리 주를 나란히 비교하게 된다. 두 주
모두 쓰되 `weeks` dataset의 `fully_within_period`로 구분한다.

2026-08 기본 기간의 주차는 6개이고 그중 4개만 완전하다.

| week_start | fully_within_period |
|---|---|
| 2026-07-27 | false (기간 시작 이전에 열린 주) |
| 2026-08-03 | true |
| 2026-08-10 | true |
| 2026-08-17 | true |
| 2026-08-24 | true |
| 2026-08-31 | false (기간 종료 이후까지 이어지는 주) |

## 4. Output

```text
{output}/
├── repo_activity_weekly/
│   ├── week=2026-07-27/
│   ├── week=2026-08-03/
│   └── ...                 # 주차당 디렉터리 하나
├── weekly_event_type/
├── weeks/
├── join_coverage/          # --join-ids 를 준 경우에만
└── data_quality/
```

기존 Raw를 수정하지 않고 `errorifexists`로만 쓴다. 같은 snapshot 경로가 이미 있으면
job이 시작 단계에서 중단한다.

운영 경로 규약은 -109와 같다.

```text
hdfs:///gitjob/parquet/github/repo_activity_weekly/period={YYYY-MM}/snapshot={snapshot-id}/
```

### repo_activity_weekly schema

```text
repo_id: bigint
repo_name: string
event_count: bigint
week_start: string   # YYYY-MM-DD, 월요일
```

### weekly_event_type schema

```text
week_start: string
event_type: string
event_count: bigint
repo_count: bigint
```

### weeks schema

```text
week_start: string
week_end: string             # week_start + 7일 (exclusive)
row_count: bigint
repo_count: bigint
event_count: bigint
fully_within_period: boolean
period_start: string
period_end: string
```

### join_coverage schema

```text
label: string                # 호출자가 지정 (예: TOP20K, COMPLETE)
cohort_repo_count: bigint
matched_repo_count: bigint
missing_repo_count: bigint
coverage_ratio: double
active_week_count: bigint
matched_row_count: bigint
matched_event_count: bigint
period_start: string
period_end: string
```

### data_quality schema

```text
input_path: string
input_file_count: bigint
period_start: string
period_end: string
total_input_events: bigint
repo_id_null_count: bigint
repo_name_null_count: bigint
created_at_null_count: bigint
invalid_event_count: bigint
malformed_json_count: bigint
valid_repo_event_count: bigint
row_count: bigint
unique_repo_id_count: bigint
week_count: bigint
repo_name_collision_count: bigint
```

## 5. 출력 모양은 소비자가 정한 것이다

`Infra/spark/jobs/export_c_archive_activity.py`(-203)가 유일한 소비자이고 그 결과가
`AI/trend/archive.py`로 들어간다. 둘이 합쳐 네 가지를 고정한다.

| 고정 사항 | 근거 |
|---|---|
| 컬럼은 `repo_id`, `repo_name`, `event_count`, (WEEK이면) `week_start` | `export_c_archive_activity._activity_quality()` — `event_count`가 -109의 `activity_count`보다 우선 |
| `week_start`는 월요일 ISO date 문자열 | `trend.archive._period_index()` |
| 한 번의 source read에 `week_start`가 **정확히 하나** | `export_c_archive_activity._validate_activity_period()` |
| 그 안에서 `repo_id`당 **한 행**, null·음수·공백 이름 없음 | `export_c_archive_activity._activity_quality()` |

세 번째가 주차별 디렉터리로 쓰는 이유다. 출력 전체를 exporter에 넘기면 period binding
검증에서 실패한다. 네 번째가 `week_start`를 **데이터 컬럼**으로 남기는 이유다.
`partitionBy("week_start")`를 쓰면 디렉터리 모양은 같아지지만 파일에서 컬럼이 사라지고,
exporter가 하는 것처럼 partition 디렉터리 하나를 직접 읽으면 검증 대상 컬럼 자체가
없어진다. 그래서 디렉터리 이름은 `week=`이고 컬럼은 그 옆에 함께 쓴다.

job은 쓰기 직후 각 주차 디렉터리를 다시 읽어 컬럼 목록, 행 수, `repo_id` 중복,
`week_start` 단일성, null, 음수 count를 재검증한다. 하나라도 어긋나면 실패한다.

## 6. 로컬 재현 (Spark 없이)

`aggregate_weekly_rows()`, `week_start_of()`, `activity_rows_for_week()`,
`assert_week_slice_is_consumable()`, `join_coverage_row()`, `load_repo_ids()`는 모두
순수 함수다. Spark job은 같은 판정을 `groupBy`/`date_trunc`로 분산 수행한다.

```powershell
cd AI
$env:PYTHONPATH = (Get-Location).Path + ";" + (Resolve-Path ..\Infra\spark).Path
python -m pytest tests/test_repo_activity_weekly.py -q
```

**2026-09-12 이번 세션 실측**

| 항목 | 결과 |
|---|---|
| `tests/test_repo_activity_weekly.py` | **44 passed** |
| `AI` 전체 suite (변경 포함) | 20 failed, 1893 passed, 107 skipped |
| `AI` 전체 suite (변경 제외, `origin/develop` 0aa433f) | 20 failed, 1849 passed, 107 skipped |
| `ruff check` / `ruff format --check` (신규 2파일) | PASS |

전체 suite의 실패 20건은 `test_public_pipeline.py`(18), `test_public_intake.py`(1),
`test_public_run.py`(1)로 **변경 전 develop에서 동일하게 재현**된다. 이번 변경과 무관하며
이 branch에서 고치지 않는다.

주차 경계·timezone·결정성·중복/null·repo_id 집계·소비자 schema·Top-N JOIN 호환은
모두 위 테스트로 덮여 있다. 소비자 계약 검증은 assertion을 새로 쓰지 않고
`export_c_archive_activity.validate_source_period_binding()`과
`trend.archive.iter_bounded_activity_stream()`을 직접 호출해 확인한다.

## 7. 기존 운영 기록 (2026-09-08, 이번에 재검증하지 않음)

아래는 Jira `S15P21E102-166`에 기록된 **과거 운영 실행 결과**다. 이번 세션에서
Spark를 실행하지 않았으므로 재검증된 값이 아니다.

| 항목 | 기록된 값 |
|---|---|
| 입력 | `hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz` |
| 출력 | `hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-08/snapshot=s15p21e102-109-weekly-20260908/` |
| rows | 7,967,178 |
| unique repos | 5,711,133 |
| 유효 event | 87,516,805 (식별자 누락 64건 제외) |
| Parquet | 200 files / 261,039,111 bytes |
| Top20k coverage | 20,000 / 20,000 |
| COMPLETE coverage | 13,101 / 13,101 |
| duplicate key / null | 0 |

기록된 출력의 내부 디렉터리 구조는 이 문서 §4의 layout과 **동일하다고 확인되지 않았다**.
행당 평균 32.8 bytes(261,039,111 / 7,967,178)는 위 4개 컬럼 수준의 얇은 schema와는
맞지만, repository별 event type map이나 actor 집계가 들어간 schema와는 맞지 않는다.
이는 크기 기반 추정이며 실측이 아니다. 운영 재실행 시 §4 layout으로 새 snapshot ID에
쓰고, 기존 snapshot은 덮어쓰지 않는다.

## 8. 실행

Historical Raw (기본):

```bash
spark-submit /opt/gitjob/spark/jobs/repo_activity_weekly.py \
  --input-format raw-json \
  --input 'hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz' \
  --output hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-08/snapshot=<new-id> \
  --expected-files 744 \
  --period-start 2026-08-01T00:00:00Z \
  --period-end 2026-09-01T00:00:00Z \
  --join-ids TOP20K=/approved/top20k.json \
  --join-ids COMPLETE=/approved/complete-snapshot.json
```

Streaming Parquet (cutoff 이후):

```bash
spark-submit /opt/gitjob/spark/jobs/repo_activity_weekly.py \
  --input-format stream-parquet \
  --input hdfs:///gitjob/parquet/stream/github.events \
  --output hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-09/snapshot=<new-id> \
  --period-start 2026-09-01T00:00:00Z \
  --period-end 2026-10-01T00:00:00Z \
  --join-ids TOP20K=/approved/top20k.json
```

`--expected-files`는 `raw-json`에서만 쓰인다. `stream-parquet`의 gate는 §2.4의 hour
coverage다. 출력 경로 규약은 두 입력이 같으므로, 어느 쪽에서 나온 snapshot인지는
`snapshot=` ID에 담는 것이 운영상 안전하다(예: `...-stream-20260912`). job은 ID를
강제하지 않고 실행 요약의 `input.format`으로 기록한다.

실행 요약(stdout JSON)에는 `input.format`, `input.completeness_gate`가 들어가고,
stream 실행에는 `stream` 블록이 추가된다 — `deduplicated_event_count`,
`out_of_period_event_count`, `below_cutoff_event_count`, `expected_hour_count`,
`observed_hour_count`.

`--join-ids`는 `LABEL=PATH` 형식이고 반복 가능하다. cohort 이름을 job이 고정하지
않는다 — Top20k와 COMPLETE는 이번 티켓이 묻는 두 cohort일 뿐이다. PATH는 exporter가
이미 받는 것과 같은 envelope(`repo-fetch-candidates/v1`,
`github-repo-snapshot/v1`, `c-public-repo-analysis/v1`)이므로 변환 없이 양쪽에 쓴다.

`Infra/docker/spark/Dockerfile`이 `Infra/spark`를 통째로 `/opt/gitjob/spark`에
복사하므로, 이 파일은 merge 후 image rebuild만으로 운영 실행 경로에 포함된다.

## 8.1 Snapshot 확정과 완료 이벤트 (S15P21E102-225)

집계가 끝났다고 C조가 읽어도 되는 것은 아니다. 파일이 있다는 것은 절반만 쓰인
회차도 똑같이 만족한다. 그래서 주차마다 확정 신호와 검증 수단을 붙인다.

```text
DATA WRITE → read-back VERIFY → MANIFEST → COMPLETION EVENT
```

manifest 게시가 실패하면 완료 이벤트를 발행하지 않는다. 이벤트는 manifest 를
write 하고 **다시 읽어 확인한 뒤에만** 나간다 — 읽히지 않는 URI 를 가리키는
이벤트를 C조에 보내지 않기 위해서다.

### 주차당 manifest 1개, 이벤트 1건

`export_c_archive_activity` 가 한 read 에 주차 하나만 허용하므로 C조가 실제로
소비하는 단위는 주차다. 한 snapshot 이 여러 주차를 담아도 주차마다 따로 만든다.

```text
{snapshot}/week=2026-08-31/_SUCCESS.json  → completion event 1건
{snapshot}/week=2026-09-07/_SUCCESS.json  → completion event 1건
```

### manifest

`_SUCCESS.json` 은 주차 디렉터리 안에 들어간다. 계약은
`docs/data/contracts/repo-activity-weekly-publish-manifest-v1.schema.json`.

```json
{
  "schema_version": "repo-activity-weekly-publish-manifest/v1",
  "dataset_snapshot_id": "...",
  "week_start": "2026-08-31",
  "data_uri": "hdfs:///gitjob/parquet/github/repo_activity_weekly/period=.../snapshot=.../week=2026-08-31",
  "row_count": 12345,
  "row_digest": {"format": "typed-json-v2", "value": "<sha256>"}
}
```

**digest 는 byte checksum 이 아니다.** Parquet part 파일은 실행마다 다른 UUID 와
`created_by` 빌드 문자열을 담아서, 같은 데이터도 `hdfs dfs -checksum` 이 다르게
나온다. `Infra/spark/dataset_digest.py` 가 정렬된 schema 와 canonical JSON 행을
해싱하는 이유가 그것이고, 이 값은 그 함수를 그대로 재사용한다. 주차별 read-back
에서 계산하므로 Parquet 을 한 번 더 훑지 않는다.

### 완료 이벤트

| 항목 | 값 |
|---|---|
| topic | `gitjob.repo-activity-weekly.completed.v1` |
| partition | 1 (주차당 1건, 순서가 유일한 의미) |
| retention | `-1` |
| key / `source_id` | `{dataset_snapshot_id}/{week_start}` |
| payload | `dataset_snapshot_id`, `week_start`, `manifest_uri` **3필드뿐** |

`github.events` Raw topic 과 완전히 분리한다. `selected_repo_count`, coverage,
Registry 44 순회, 기술별 Trend 는 C조가 계산한다 — A조가 숫자를 실어 보내면 같은
값이 틀릴 자리가 하나 더 생긴다.

### 실행 (S15P21E102-227)

publisher 는 Spark weekly job 이 stdout 에 낸 summary JSON 을 입력으로 받는다. 그
summary 의 `output.weeks_written` 이 주차별 `uri` / `row_count` / `row_digest` 를
이미 담고 있으므로, write 시점에 계산한 digest 가 Parquet 재스캔 없이 manifest 에
도달한다.

```bash
export ENV_FILE=.env.data
# 2호스트 운영은 cluster overlay 다. deploy.sh 가 쓰는 것과 같아야 하고,
# Spark 계열의 host networking 선언이 이 파일에 있다.
export COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data-cluster.yaml
export PROFILES=data
export WEEKLY_SNAPSHOT_ID=s15p21e102-224-stream-20260913

# 1) 집계 — summary JSON 이 호스트에 남는다
WEEKLY_PERIOD=2026-09 WEEKLY_INPUT_FORMAT=stream-parquet WEEKLY_PERIOD_END=2026-10-01T00:00:00Z   ./Infra/scripts/weekly-repo-activity.sh

# 2) 무엇이 게시될지 먼저 본다 — WebHDFS 와 Kafka 를 건드리지 않는다
./Infra/scripts/weekly-snapshot-publish.sh --dry-run

# 3) 실제 게시
./Infra/scripts/weekly-snapshot-publish.sh
```

두 래퍼가 컨테이너 경계를 넘긴다. 집계는 `spark-worker` 안에서 돌고 summary 는
`.local/weekly-repo-activity/<snapshot_id>-summary.json` 으로 떨어지며, 게시는 그
디렉터리를 읽기 전용으로 마운트한 `worker` 컨테이너에서 돈다. **호스트에서 직접
`python -m …` 을 실행하면 안 된다** — 의존성이 없고 `hdfs-namenode`/`kafka` 가
Compose 네트워크 밖에서 해석되지 않는다.

`--dataset-snapshot-id` 는 Spark 가 실제로 쓴 경로의 `snapshot=` 세그먼트와 일치해야
한다. 다르면 CLI 가 거부한다 — 그렇지 않으면 디렉터리가 속하지 않은 snapshot id 를
가리키는 manifest 가 게시되고, 바이트는 내부적으로 일관되므로 아무 곳에서도 걸리지
않는다.

**먼저 `--dry-run` 을 돌린다.** 첫 실전 실행은 불변 객체를 쓰므로,
`--dataset-snapshot-id` 의 오타가 아무도 의도하지 않은 디렉터리가 되고
`store_immutable` 이 그것을 덮어쓰지 못하게 한다.

종료 코드는 0(게시 완료) 또는 1(실패)이다. manifest 는 올라갔는데 이벤트가 실패한
경우도 1 이며, 메시지가 그 사실을 말한다 — 재실행하면 동일 바이트를 멱등 재게시하고
이벤트를 다시 보낸다. 브로커가 설정돼 있지 않으면 manifest 만 게시하고
`broker_configured: false` 로 알린다.

### 멱등성과 late event

`store_immutable` 이 목적지가 이미 있으면 bytes 를 비교한다. 같은 내용이면 기존
URI 를 돌려주고(재실행 멱등), 다른 내용이면 `FileExistsError` 다. manifest 가 row
digest 를 담으므로 **같은 `dataset_snapshot_id` 로 행이 달라진 주차는 조용히
게시될 수 없다.**

따라서 §2.6 의 late event 정책이 여기서 강제된다. 이미 게시된 주차에 뒤늦은
event 를 반영하려면 기존 Snapshot 을 고치는 것이 아니라 **새 `dataset_snapshot_id`
로 새 경로, 새 manifest, 새 완료 이벤트**를 만든다. `snapshot=` 가 경로에 있으므로
새 id 는 새 디렉터리이고, C조가 먼저 읽은 것은 그대로 남는다.

### 실행 경계

이미지가 이 분리를 강제한다. `Infra/docker/spark` 는 `Infra/spark` 만 복사하므로
Spark executor 안에는 `common.webhdfs` 도 `common.kafka` 도 없다. `Infra/docker/worker`
는 `AI/` 전체를 담지만 Spark 도 Hadoop CLI 도 JRE 도 없다. 그래서 digest 는 행을
이미 읽고 있는 Spark 쪽에서 계산하고, 게시와 발행은 client 가 있는 worker 쪽
(`AI/github/weekly_activity_publish.py`)에서 한다. `repo_snapshot_bootstrap.py` 도
같은 이유로 같은 모양이다.

## 9. C조 해석 한계

`week_start`는 **기술 사용 시작일이 아니라 해당 Repo에서 GitHub event가 발생한
주차**다. C조는 현재 Snapshot에서 그 기술을 사용하는 것으로 판정된 Repo의 주간 활동
추세로만 해석한다.

`gh_archive_event_count / EVENTS / WEEK`는 `trend.github`의 Innovation Graph
`num_pushers / UNIQUE_PUSHERS / QUARTER`와 출처·단위·기간이 다르며 합산하지 않는다
(`docs/ai/c-archive-trend.md`).

repository가 주중에 이름을 바꾸면 그 주 마지막 event의 이름을 쓴다(-109 규칙의 주별
적용). 같은 `repo_id`의 이름이 주별로 달라질 수 있으므로 **JOIN key는 `repo_id`이고
`repo_name`은 표시용**이다. 이름이 두 개 이상 관측된 행 수는 `data_quality`의
`repo_name_collision_count`에 남는다.

## 10. 남은 항목 — unique actor 집계

Jira 작업 내용의 "안정적으로 산출 가능한 이벤트별 count, unique actor 집계" 중
**이벤트별 count는 구현했다** (`weekly_event_type`). event type은 -109가 이미 선언한
Raw schema의 `type` 필드라 추가 가정이 없다.

**unique actor 집계는 넣지 않았다.** 저장소 어디에도 — collector, Spark job, 계약,
문서 — `actor` 필드를 언급한 코드가 없어 Raw layer에서의 존재 여부·모양·null 여부가
확인되지 않는다. 확인 없이 `actor.id`를 read schema에 넣으면 추측이 틀렸을 때 조용히
null만 생산한다. 추가하려면 운영 Raw 한 시간 분량의 실제 필드를 먼저 read-only로
확인한 뒤 별도 작업으로 진행한다.
