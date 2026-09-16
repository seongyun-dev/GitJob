# registry 교체가 Weekly 완료 이벤트를 유실시킨 경로와 재처리 절차

- Jira: `S15P21E102-283`
- 기준일: 2026-09-16
- 범위: `gitjob.repo-activity-weekly.completed.v1` → Weekly Trend Consumer → TREND. Historical / Redis 경로는 범위 밖

## 1. 현상

`S15P21E102-282`(`KAFKA_AUTO_OFFSET_RESET=earliest`) 배포 후 2026-03-02 주의 완료 이벤트가 소비됐는데도 downstream이 하나도 생기지 않았다.

| 관측 | 값 |
|---|---|
| Service / Data Production SHA | `b598aad` |
| consumer env | `KAFKA_AUTO_OFFSET_RESET=earliest` |
| group `gitjob-weekly-trend-prod-v1` | CURRENT-OFFSET `-` → **1**, LAG 0 |
| `/state/weekly-exports` | 비어 있음 |
| `c_compute.snapshot` kind=TREND | **0건** |
| `c_compute.head` TREND | 없음 |

offset은 전진했는데 결과가 없다. 즉 이벤트가 **처리되지 않은 채 소비 완료로 기록**됐다.

## 2. 원인 확정

기존 ticket:

```text
event_id     weekly-activity-ab84e845...09458d
kind TREND   state FAILED   attempt 12   error_code WEEKLY_ACTIVITY_RETRY
request_hash f8d2a3e6db103c84...
updated_at   2026-09-13 21:10:04Z        ← 2026-09-16 처리에서 갱신되지 않음
```

ticket이 갱신되지 않았다는 것은 `claim()`의 UPDATE에 도달하지 못했다는 뜻이다. 해시를 직접 재계산해 확인했다.

```text
event_id 재계산                       weekly-activity-ab84e845...09458d   (저장값과 일치)
request_hash(registry-20260911.1)     f8d2a3e6db103c84...                 (저장값과 일치)
request_hash(registry-20260910.2)     3afe95e665eb2c79...                 (현재 CURRENT)
```

`public.technology_registry`의 CURRENT가 9/13 이후 `registry-20260911.1` → `registry-20260910.2`로 되돌아갔다. Weekly consumer는 처리 시점 CURRENT에서 resolve한 `registry_version`을 `claim()` request에 넣었으므로, **같은 Kafka record가 다른 request가 되어** `IdempotencyConflict`가 발생했다.

그 다음이 유실 지점이다.

```text
IdempotencyConflict(ValueError)
  → except (ValueError, TypeError, KeyError, IdempotencyConflict)
  → 이 시점 ticket is None → _fail_owned(None, ...)가 True 반환
  → Outcome.REJECTED
  → run_once()는 RETRY가 없으면 commit → offset 0 → 1
```

처리권을 얻지 못했고 아무것도 계산하지 않았는데 성공적으로 소비한 것처럼 commit됐다.

### 계약 판정

- `IdempotencyConflict` docstring이 정의하는 계약은 *"reused an event ID for a different **immutable** request"* 다. `request_hash`에는 immutable event input만 들어가야 한다.
- `registry_version`은 `PostgresRegistryStore.resolve_version()`이 처리 시점 CURRENT 행에서 resolve하는 **mutable dependency**이며 Kafka 이벤트 payload에 존재하지 않는다. `include_partial` / `algorithm_version`도 같은 성격이다.
- 대조: `worker/intake.py`는 `event_id = "job-intake-" + digest(request)`라 event_id 범위와 request_hash 범위가 같아 drift가 구조적으로 불가능하다. Weekly만 event_id 범위가 request_hash 범위의 진부분집합이었고, 그 차집합에 mutable 값이 들어 있었다.
- `c_compute.event`는 `request_hash`만 저장하고 request 본문을 보관하지 않는다. 따라서 "stored request 재사용"으로는 회수할 수 없다.

## 3. 수정

| 위치 | 변경 |
|---|---|
| `AI/worker/weekly_activity_intake.py` | claim request를 `dataset_snapshot_id`, `week_start`, `manifest_uri`, `manifest_sha256`로 축소. `registry_version` / `include_partial` / `algorithm_version` 제거 |
| `AI/worker/weekly_activity_intake.py` | `except IdempotencyConflict:` 절을 ValueError 절 **앞에** 두고 `RETRY` 반환 (offset 미commit) |
| `AI/worker/store.py` | `claim()`의 request_hash 불일치 conflict를 `settled`(COMPLETED, lease 살아 있는 RUNNING)에만 적용. 미종료 ticket은 재claim하고 stored hash를 실제 수행 내용으로 갱신 |

`event_id`는 바꾸지 않았다. 바꾸면 Production에 남은 ticket을 가리키지 못해 회수가 불가능해진다.

`claim()` 완화의 판단 기준은 "불일치가 실제로 위험한 순간은 호출자가 남의 결과를 받아가는 때뿐"이다. COMPLETED ticket은 `results`를 이 request의 답으로 돌려주고, lease가 살아 있는 RUNNING은 그 결과를 만들고 있다. 이 둘은 계속 conflict다. FAILED이거나 lease가 만료된 RUNNING은 아무것도 게시하지 않았으므로 새 내용으로 다시 도는 것이 맞다. `kind` / `owner` scope 불일치는 상태와 무관하게 conflict로 남는다.

이 완화 덕분에 registry 교체로 굳은 legacy ticket이 **행 삭제·수동 hash 수정·schema migration 없이** 회수된다.

## 4. 검증

격리 Postgres(throwaway container, tmpfs, 전용 docker network — Production DB 미접촉)에서 store 계약을 수정 전/후로 대조 실행했다.

| 계약 | 수정 전 | 수정 후 |
|---|---|---|
| 미종료 ticket 재claim (내용 변경) | FAIL | PASS |
| legacy weekly poisoned ticket 회수 | FAIL | PASS |
| COMPLETED + 내용 변경 → conflict | PASS | PASS |
| lease 살아 있는 RUNNING + 내용 변경 → conflict | PASS | PASS |
| owner scope 변경 → conflict | PASS | PASS |
| 동일 내용 replay → COMPLETED 단락 | PASS | PASS |

테스트: 오프라인 159 passed / 0 failed / 3 intentional skip. Postgres 연결 시 `test_weekly_activity_intake.py` 26 passed, `test_compute_store.py` 17 passed. `test_compute_matching.py`의 `httpx2` IMPORT-FAIL은 수정 전 트리에서도 동일한 기존 환경 문제다.

## 5. 재처리 절차

offset이 이미 1로 commit되어 기존 record는 자동 재배달되지 않는다. **공식 producer 재실행**으로 동일 logical event를 1회 다시 announce한다.

1. `S15P21E102-283` Production 배포
2. Weekly canary 실행 — candidate export(`S15P21E102-276`) → resolver(`S15P21E102-274`) → PUBLIC_GITHUB snapshot → C export
3. `AI/github/weekly_activity_publish_cli.py --dry-run`으로 manifest·이벤트 내용 확인
4. 같은 CLI를 `--dataset-snapshot-id s15p21e102-weekly-20260302-20260913-v2`로 실행
5. consumer가 legacy FAILED ticket을 재claim하고 TREND 생성
6. 이후 중복 재배달은 COMPLETED duplicate로 단락

2단계가 선행이어야 하는 이유: 9/13 실패는 `WEEKLY_ACTIVITY_RETRY`(입력 미비)였다. `MountedWeeklyExportReader`가 읽는 `/state/weekly-exports/public=<id>/snapshot=<id>/week=<date>/`는 **입력**이며 C export가 생성한다. 입력 없이 먼저 재announce하면 다시 RETRY한다.

duplicate 안전성: 재발행 envelope의 `occurred_at`은 주 시작일로 고정이고 payload도 동일하므로 `event_id`와 `request_hash`가 모두 불변이다. `store_immutable`은 동일 내용이면 기존 URI를 반환하므로 HDFS에 새로 쓰는 것도 없다.

### 하지 않는 것

- ticket 행 삭제 / `request_hash` 수동 수정
- registry CURRENT rollback
- Kafka offset reset / consumer group 삭제
- 통제되지 않은 event republish

## 6. canonical source

```text
hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-03/
  snapshot=s15p21e102-weekly-20260302-20260913-v2/repo_activity_weekly/week=2026-03-02
dataset_snapshot_id  s15p21e102-weekly-20260302-20260913-v2
row_count            3,735,673
row_digest           typed-json-v2 / 51b65d68...36b2f
```

2026-03에는 스냅샷이 둘 있으나 `_SUCCESS.json` publish manifest를 가진 것은 `-v2` 하나뿐이다. 구버전 `s15p21e102-weekly-20260302-20260913`에는 manifest가 없어 candidate export CLI가 거부한다.
