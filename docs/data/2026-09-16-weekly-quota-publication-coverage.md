# Weekly quota publication이 A→C 로더에서 거부된 경로와 수용 계약

- Jira: `S15P21E102-287`
- 기준일: 2026-09-16
- 범위: `github/snapshot_input.py`의 bootstrap publication 커버리지 판정. Historical full-coverage 흐름은 변경 없음

## 1. 현상

정상 완료된 Weekly quota publication을 `load_published_snapshot()`이 거부해 `PublicPipelineConsumer`가 입력을 읽지 못했다. PUBLIC_GITHUB가 생기지 않아 Weekly E2E 전체가 멈췄다.

```
SnapshotInputError: bootstrap publication lacks complete candidate coverage or stopped early
```

## 2. 원인

`S15P21E102-274`의 Weekly resolver는 `valid_artifact_quota` 도달 시 **의도적으로 조기 종료**한다. 반면 `_reconcile()`은 bootstrap summary에 `top_n_limit` 전수 커버리지만 허용했다.

실측 (`s15p21e102-283-weekly-recovery-20260916`):

| 값 | |
|---|---|
| `collection_policy.top_n_limit` | 1500 (= `--candidate-pool-limit`) |
| `summary.repos` rows | 346 (= `candidates_examined`, rank 1..346 연속) |
| `valid_artifact_count` / `quota` | 100 / 100, `quota_reached` true, `quota_shortfall` 0 |
| `record_count` | 290 |
| `snapshot_published` / `stopped_reason` | true / null |

346 ≠ 1500이므로 거부. **quota < pool인 모든 Weekly publication이 동일하게 거부된다.**

publication 자체는 정상이었다 — `file://` URI 0, `hdfs://` 506, HDFS 실존재 506/506, `_SUCCESS` checksum 일치.

## 3. 수용 계약

기존 조건은 그대로 두고, 정상 quota 완료를 summary의 **실제 필드로 증명할 수 있을 때만** 부분 커버리지를 허용한다. 두 경우 모두 `snapshot_published is True` / `stopped_reason is None`을 요구한다.

**A. 전수 커버리지 (기존)** — `len(by_id) == top_n_limit`

**B. quota 완료 (신규)** — 아래 전부
- `quota_reached is True`
- `quota_shortfall == 0`
- `candidates_examined == len(by_id)`
- `len(by_id) <= top_n_limit`
- `max(rank) == len(by_id)` — pool은 rank 순으로 소비되므로 quota 종료는 **prefix**를 남긴다. rank가 이미 서로 다르므로 최대 rank가 개수와 같다는 것이 1..examined 무결 커버리지를 증명한다

`quota_shortfall`이 핵심이다. 이것이 "valid 100을 다 채웠다"와 "pool이 바닥나 60에서 멈췄다"를 가른다. crash / partial checkpoint / 임의 조기 종료 / shortfall 존재 / `stopped_reason` 존재 / record-examined 불일치는 기존대로 거부된다. 또 fetch 실패한 candidate를 건너뛴 선택은 prefix 조건에서 걸린다.

`_SourceModel`이 `extra="ignore"`라 quota 필드는 파싱되지 않고 있었다. `_Summary`에 optional로 추가했을 뿐 **schema_version은 올리지 않았다** — Historical summary에는 이 필드가 없어 `None`이 되고 A 경로만 적용된다.

## 4. 검증

| 항목 | 결과 |
|---|---|
| `test_snapshot_input.py` | 17 passed / 0 failed (신규 7건 포함) |
| 신규 수용 테스트를 미수정 코드에 적용 | `test_quota_completion_is_accepted_without_full_pool_coverage` **FAIL** (수정이 실제 원인을 고침을 증명) |
| 실제 publication 로드 (미수정) | `SnapshotInputError` |
| 실제 publication 로드 (수정) | **PASS** — records 290, candidate_count 346, complete_with_artifacts 100 |
| 광범위 회귀 | 135 passed / 0 failed (resolver·intake·consumer·publish·candidate export·Historical·monthly chain·C export) |
| compile / `git diff --check` | exit 0 / clean |

`test_public_intake.py`·`test_archive_input_v2.py`의 IMPORT-FAIL(`httpx2` 미설치)은 미수정 트리에서도 동일한 기존 환경 문제다.

## 5. Historical 영향

없음. Historical monthly Top10k는 `top_n_limit` 전수 커버리지를 채우므로 A 경로로 그대로 통과하고, MONTH_EVENT_SHA·기존 bootstrap publication 계약은 건드리지 않았다. `test_gharchive_historical.py` 11 passed, `test_monthly_chain_contract.py` 4 passed, `test_repo_snapshot_bootstrap.py` 5 passed.

## 6. 남은 blocker

이 수정은 로더 거부만 해소한다. PUBLIC_GITHUB 생성 경로는 별도다 — shared worker의 `public_sources`가 `max_length=4` 상한을 모두 사용 중이라 신규 source를 추가할 수 없다(`S15P21E102-286`).
