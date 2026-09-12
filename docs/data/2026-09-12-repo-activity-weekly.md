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

| 항목 | 값 |
|---|---|
| 기본 입력 | `hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz` |
| 기본 기간 | `2026-08-01T00:00:00Z` ~ `2026-09-01T00:00:00Z` (end exclusive) |
| 허용 기간 | `2026-03-01T00:00:00Z` ~ `2026-09-01T00:00:00Z` (-193이 검증한 Historical Raw 구간) |
| 읽는 필드 | `repo.id`, `repo.name`, `type`, `created_at` (+ `_corrupt_record`) |

`_corrupt_record`는 malformed JSON 측정용이며 grouping key에 절대 들어가지 않는다.
`--expected-files`로 입력 파일 수를 명시적으로 고정한다(2026-08 = 744시간).

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

```bash
spark-submit /opt/gitjob/spark/jobs/repo_activity_weekly.py \
  --input 'hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz' \
  --output hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-08/snapshot=<new-id> \
  --expected-files 744 \
  --period-start 2026-08-01T00:00:00Z \
  --period-end 2026-09-01T00:00:00Z \
  --join-ids TOP20K=/approved/top20k.json \
  --join-ids COMPLETE=/approved/complete-snapshot.json
```

`--join-ids`는 `LABEL=PATH` 형식이고 반복 가능하다. cohort 이름을 job이 고정하지
않는다 — Top20k와 COMPLETE는 이번 티켓이 묻는 두 cohort일 뿐이다. PATH는 exporter가
이미 받는 것과 같은 envelope(`repo-fetch-candidates/v1`,
`github-repo-snapshot/v1`, `c-public-repo-analysis/v1`)이므로 변환 없이 양쪽에 쓴다.

`Infra/docker/spark/Dockerfile`이 `Infra/spark`를 통째로 `/opt/gitjob/spark`에
복사하므로, 이 파일은 merge 후 image rebuild만으로 운영 실행 경로에 포함된다.

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
