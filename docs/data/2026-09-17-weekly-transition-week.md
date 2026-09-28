# Historical→Streaming 전환 주차 Weekly 집계

`week_start=2026-08-31` 주차를 Historical Raw + Streaming Parquet 혼합 입력으로
집계하는 `--input-format transition` 의 계약을 기록한다 (S15P21E102-295).

## 왜 세 번째 입력 포맷인가

Weekly 처리 단위는 Monday start이고 **2026-09-01은 화요일**이다. 따라서 9월 첫
주차는 `week_start=2026-08-31` 이며 cutoff를 가로지른다.

- `2026-08-31` → Historical Raw hourly (`/gitjob/raw/gharchive/dt=2026-08-31`)
- `2026-09-01 ~ 09-06` → Streaming Parquet (`/gitjob/parquet/stream/github.events`)

`validate_period()` 는 이 주차를 **두 포맷 모두에서 거부**한다.

```
raw-json        → period_end exceeds exclusive historical_cutoff
stream-parquet  → stream period_start precedes historical_cutoff
```

이 가드는 "한 시간을 두 번 세지 않는다"는 의도된 계약이므로 제거하지 않았다.
`transition` 은 그 계약을 **우회하는 것이 아니라 한 주차에 한정해 명시적으로
분할 적용**한다.

## 입력 계약

```bash
spark-submit .../repo_activity_weekly.py \
  --input-format transition \
  --raw-input    'hdfs:///gitjob/raw/gharchive/dt=2026-08-31/*.json.gz' \
  --stream-input  hdfs:///gitjob/parquet/stream/github.events \
  --transition-boundary 2026-09-01T00:00:00Z \
  --period-start 2026-08-31T00:00:00Z \
  --period-end   2026-09-07T00:00:00Z \
  --output       hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-08/snapshot={id}/repo_activity_weekly/week=2026-08-31
```

`--input` 은 이 모드에서 의미가 없다. 두 reader가 각자의 루트를 받으므로
`resolve_input_path` 는 빈 문자열을 돌려준다.

`--transition-boundary` 는 기본값이 `SUPPORTED_HISTORICAL_CUTOFF` 지만 인자로
드러나 있다. 혼합 읽기를 실수로 요청할 수 없게 하려는 것이다.

### period가 만족해야 하는 4가지

`validate_transition_week()` 가 강제한다.

1. 정확히 7일, **Monday start** — 주차 일부를 읽고 한 주차 행을 쓰지 않도록
2. **boundary를 가운데 둔다** (`start < boundary < end`) — 한쪽에만 걸친 period로
   transition을 돌리는 것은 반대 방향의 같은 이중 계수 위험이다
3. `period_start >= SUPPORTED_HISTORICAL_START`
4. `week_start ∈ SUPPORTED_TRANSITION_WEEK_STARTS` (현재 `("2026-08-31",)`)

4번이 핵심이다. 혼합 입력은 **이름이 명시된 주차에 준 예외**이지 아무 period나
요청할 수 있는 모드가 아니다. cutoff가 나중에 옮겨지면 그때의 전환 주차를
**의도적으로 추가**해야 한다.

## coverage 계약 — 두 게이트는 합쳐지지 않는다

`transition_split()` 이 period를 boundary에서 **half-open으로 맞닿게** 자른다.

```
raw    [2026-08-31T00:00:00Z, 2026-09-01T00:00:00Z)   24 hours
stream [2026-09-01T00:00:00Z, 2026-09-07T00:00:00Z)  144 hours
```

겹치지 않고 맞닿는다는 점이 중요하다. 주차의 모든 시간이 **정확히 하나의
reader**에 속하므로, cross-source dedup이 "아마 필요 없는" 것이 아니라
**구조적으로 불필요**하다.

| | raw 측 | stream 측 |
|---|---|---|
| 게이트 | 시간당 파일 존재 | hour coverage |
| 기대값 | 24 files (`expected_raw_hour_files`) | 144 hours (`expected_stream_hours`) |
| 누락 판정 | `missing_raw_hour_files` | `missing_stream_hours` |
| dedup | **없음** | `DEDUP_KEYS` dropDuplicates |
| boundary guard | boundary 이상 이벤트 → RuntimeError | boundary 미만 이벤트 → RuntimeError |

두 게이트를 하나로 합치지 않았다. "전부 있다"의 의미가 서로 다르기 때문이다 —
Raw는 시간당 파일 하나를 발행하므로 부재가 곧 누락 파일이고, C1이 쓰는 Parquet
part 파일 수는 아무것도 말해주지 않아 hour coverage만이 게이트가 된다. 합치면
진 쪽의 검증이 약해진다.

Raw 게이트는 개수가 아니라 **이름**으로 비교한다. "24개 중 23개"는 어느 시간을
가져와야 하는지 말해주지 않는다.

```
raw input is missing 1 of 24 expected hourly files: ['2026-08-31-5.json.gz']
```

## union 지점

두 분기 모두 기존 5컬럼 typed intermediate를 만든 뒤 `unionByName` 한다.

```
(repo_id, repo_name, event_type, created_at_ts, _corrupt_record)
```

이후 quality block / aggregation / digest / row count / Top-N 이 **전부 그대로**
돌고, 어느 행이 어느 half에서 왔는지 구분하지 못한다. 그게 요점이다 —
`week_start` 는 이벤트 instant의 속성이지 그것을 찾아낸 reader의 속성이 아니다.

## 왜 교차 dedup을 추가하지 않았는가

08-31과 09-01 이후는 시간 구간이 disjoint이고, 양쪽 boundary guard가 교차 유입을
RuntimeError로 막는다. Raw에는 publisher 재전송 경로 자체가 없다(기존 주석:
*"Raw has no such path and is left untouched"*).

교차 identity를 새로 만들어 검사하는 것은 **boundary가 이미 보장하는 것을 다시
주장하는 일**이다. 참고로 `build_event_schema()` 는 `repo{id,name}` / `type` /
`created_at` 4필드만 읽고 GH Archive의 `id`(event id)를 읽지 않으므로, 통합
envelope identity를 만들려면 schema 확장이 필요하지만 이번 범위에서 불필요하다.

## downstream

```
week_start = 2026-08-31
week_end   = 2026-09-07 (exclusive)
사용자 표기 8/31 ~ 9/6
```

`AI/worker/store.py:_target_period_covers_week` 는 월 shorthand를
`requested_week` 의 월과 `week_end` 의 월 **양쪽**으로 매칭하므로 이 주차는 8월
필터와 9월 필터 모두에 노출된다. `_period_overlaps_week` 의 overlap semantics도
그대로다. API/schema 변경은 필요하지 않다.

월 경계를 걸치는 주차는 이미 Weekly 설계에 포함돼 있다 —
`weeks.fully_within_period` 가 그 목적의 필드다.

## S15P21E102-264 verifier와의 관계

transition의 stream 측 게이트도 **hour 존재 여부**만 본다. 부분 적재된 hour는
행이 하나라도 있으면 `observed` 이므로 통과한다.

따라서 순서는 그대로다.

```
-264 verifier (완전성)  →  PASS  →  transition aggregation  →  lineage verifier
```

`test_partial_hour_still_satisfies_the_presence_gate` 가 이 한계를 테스트로
고정해 둔다.

## 범위 밖

- 일반 cutoff contract 제거/완화 — 하지 않았다
- `raw-json` / `stream-parquet` 기존 동작 변경 — 하지 않았다
- 임의 구간 mixed-period 지원
- publisher recovery 및 Production 실행 → S15P21E102-296
- Historical raw event를 Kafka로 재발행

## 참고

- `docs/data/2026-09-12-repo-activity-weekly.md` — Weekly 집계 계약
- `docs/data/2026-09-17-weekly-7day-completeness-verifier.md` — 선행 완전성 검증
- S15P21E102-296 — 2026-09 Weekly backlog 복구 및 E2E 운영 실행
