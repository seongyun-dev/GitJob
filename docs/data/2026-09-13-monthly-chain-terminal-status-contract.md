# Historical monthly chain이 자기 출력을 거부한 건 (S15P21E102-194)

- Jira: `S15P21E102-194`
- 발생: 2026-09-13 10:05:27 UTC
- 영향 범위: Historical 2026-03~08 ONE-TIME chain, 2026-08 월 완료 판정
- 데이터 손실: **없음**

## 무슨 일이 있었나

2026-08 Artifact fetch는 끝까지 성공했다. 후보 10,000개가 전부 종결 상태에
도달했고(`progress.percent = 100.0`, `remaining = 0`), HDFS에 `snapshot.json` ·
`run-summary.json` · `failures.json` · `_SUCCESS.json` 네 객체가 모두 게시됐다.
약 4시간 13분(`active_runtime_seconds = 15,194`)이 걸린 작업이다.

그 직후 chain이 자기 결과를 검증하다 죽었다.

```
checkpoint contains non-terminal status
CHAIN_EXIT=1
```

pass-marker가 기록되지 않았고, 다음 달(2026-07)로 넘어가지 못했다.

## 원인

`repo-snapshot-monthly-top10k-chain.sh`의 `validate_bootstrap`은 checkpoint의
모든 repository가 종결 상태인지 확인한다. 그 종결 집합을 producer에서 가져오지
않고 **손으로 복제**하고 있었다.

| 쪽 | 집합 |
|---|---|
| producer `TERMINAL_STATUSES` (`AI/github/repo_fetch_orchestrator.py:51`) | COMPLETE, PARTIAL, FAILED, NOT_FOUND, REUSED, **HISTORICAL_HEAD_UNAVAILABLE** |
| validator (`repo-snapshot-monthly-top10k-chain.sh`) | COMPLETE, PARTIAL, FAILED, NOT_FOUND, REUSED |

`HISTORICAL_HEAD_UNAVAILABLE`은 `S15P21E102-198`에서 들어왔고,
`REPO_REQUIRE_HISTORICAL_HEAD=1`일 때만 생긴다. 그 플래그는 이번
`S15P21E102-194` hardening이 `run_bootstrap()`에 넣은 것이다. 즉 **플래그를 켜는
변경이 chain으로 하여금 자기 출력을 거부하게 만들었다.** 켜기 전에는 그 상태가
아예 발생하지 않아 누락이 드러나지 않았다.

2026-08 실측 분포는 다음과 같다.

| 상태 | 건수 |
|---|---:|
| NOT_FOUND | 6,336 |
| COMPLETE | 3,402 |
| PARTIAL | 224 |
| **HISTORICAL_HEAD_UNAVAILABLE** | **27** |
| FAILED | 11 |
| 합계 | 10,000 |

27건이 검증을 통째로 실패시켰다.

`HISTORICAL_HEAD_UNAVAILABLE`은 미완료가 아니라 **결정**이다. 그 달의 commit을
확정할 수 없었으므로 오늘의 트리를 과거 달에 붙이는 대신 Artifact를 가져오지
않았다는 fail-closed 종결이다. `github/contracts.py`가 이 상태에서 commit 선택
자체를 금지한다.

## 수정

validator의 종결 집합에 `HISTORICAL_HEAD_UNAVAILABLE`을 추가해 producer의
`TERMINAL_STATUSES`와 일치시켰다.

`RATE_LIMITED`는 양쪽 모두에서 제외한 채로 둔다. producer enum 7개 중 유일하게
종결이 아니며, 재시도가 남은 repository가 있는데 달을 봉인하면 불완전한 Top-N이
게시된다.

집합을 producer에서 import하지는 않았다. chain은 배포 호스트의 `python3`로
도는데 그곳에는 AI 패키지도 의존성도 없다. 대신 두 파일을 텍스트로 읽어 집합이
같은지 비교하는 contract test를 추가했다 —
`AI/tests/test_monthly_chain_contract.py`. 복제는 남기되 어긋나면 CI가 잡는다.

## 검증

| 항목 | 결과 |
|---|---|
| producer enum 7개 / TERMINAL 6개 추출 | PASS |
| validator 집합과 diff → 누락 1건 확정 | `HISTORICAL_HEAD_UNAVAILABLE` |
| **수정 전** validator를 실제 2026-08 checkpoint에 적용 | `checkpoint contains non-terminal status` 재현 |
| **수정 후** validator를 같은 checkpoint에 적용 | PASS, 상태 분포 정상 출력 |
| contract test 4건 (수정본) | 4 PASS |
| 같은 test를 수정 전 코드에 적용 | 2 FAIL (회귀 탐지 유효) |
| `write_month_summary` → summary + pass-marker 생성 (임시 경로) | PASS, `status=PASS` `processed=10000` |
| 다음 월 transition 조건 | marker 존재 시 `continue`로 2026-08 skip 확인 |

pytest가 이 환경(호스트·worker 이미지)에 없어 테스트 함수를 직접 실행했다. CI에서
pytest로 다시 확인해야 한다.

## Resume 계약

2026-08을 다시 만들지 않는다는 것이 코드로 보장된다.

- **Artifact**: `RepoFetchOrchestrator`가 checkpoint 상태가 `TERMINAL_STATUSES`에
  있으면 `continue`한다(`repo_fetch_orchestrator.py:288`). 10,000건이 모두 종결이라
  repository 단위 GitHub API 호출은 0이다.
- **Publish**: `_publish`는 로컬 `snapshot.json`이 이미 있으면 재생성하지 않고
  읽어서 쓰며, 재개된 checkpoint와 다르면 `frozen final Snapshot differs`로
  중단한다. `store_immutable`은 같은 바이트면 기존 URI를 돌려주므로 재게시는
  no-op이다.
- **Activity / Candidate**: `_SUCCESS` 3종과 `candidates.json`이 그대로 있어
  skip된다. Activity는 `assert_activity_quality`가 `monthly_event_sha` 컬럼을 다시
  확인한 뒤에만 재사용된다.

**재개 시 `MONTHLY_ARTIFACT_RUN_DATE=20260913`을 반드시 고정한다.** `run_date`가
`activity_snapshot` · `artifact_snapshot` · `pipeline_run` · `publish_root` ·
`bootstrap_root` · `canary_snapshot` 경로에 들어간다. UTC 자정을 넘겨 지정 없이
재개하면 snapshot id가 바뀌어 위 재사용이 전부 무효가 되고 10,000건을 다시
가져온다. `pass-markers`와 `candidates.json`은 월 기준 키라 완료된 달은 영향이
없다.

## 모니터링

`pgrep -f monthly-top10k-chain.sh`를 명령줄에 직접 쓰면 그 명령줄 자체가 패턴에
걸려 죽은 chain을 살아 있다고 보고한다. 이번 장애 중 실제로 `proc=2` 오탐이
나왔다.

`chain-probe.sh`는 패턴을 파일 안에 두고(호출 명령줄은 `bash chain-probe.sh`뿐)
세 신호 — exact-command PID, tmux 세션, chain-state heartbeat age — 중 **2개
이상**이 살아 있을 때만 ALIVE로 판정한다. 양방향으로 시험했다.

| 조건 | 신호 | 판정 |
|---|---|---|
| 아무것도 없음 | 0/3 | DEAD |
| decoy 프로세스만 | 1/3 | DEAD (단일 신호로 판정하지 않음) |
| decoy + tmux | 2/3 | ALIVE |
| 정리 후 | 0/3 | DEAD |

시험에는 production chain을 쓰지 않았다. 같은 basename의 decoy를 `/tmp`에 만들어
띄우고 직접 정리했으며, 이후 chain-state · pass-marker · 15,768,008 bytes
checkpoint가 모두 그대로임을 확인했다.

## 남은 위험

1. **이 수정이 아직 배포되지 않았다.** 데이터 서버는 이전 커밋에 있고, 수정 없이
   재개하면 같은 지점에서 다시 죽는다 — 재실행만으로는 풀리지 않는다.
2. **2026-07~03이 남아 있다.** `HISTORICAL_HEAD_UNAVAILABLE`은 매달 나올 수
   있으므로 수정 없이는 모든 달이 같은 벽에 부딪힌다.
3. **Spark 배치 슬롯은 1개다.** C1이 2코어를 상시 점유해 chain의 Spark 단계와 다른
   배치(Weekly 등)가 경합한다. 2026-08 진행 중 실제로 양방향 대기가 한 번씩
   발생했다.
4. **`run_date` 보존이 사람 기억에 의존한다.** chain이 최초 `run_date`를 기록하고
   재개 시 자동으로 이어받게 하면 없앨 수 있다. 이번 범위 밖.
