# S15P21E102-104 GitHub Repo Fetch 비용 검증 보고서

- 작성일: 2026-09-02
- Jira: S15P21E102-104
- 프로젝트: GitJob
- 범위: 2026-08 1개월 Historical Dataset을 대상으로 Repo Fetch를 장기 Offline Batch로 운용할 수 있는지 실측으로 확인한다. 최적 Top-N을 통계적으로 확정하거나 571만 Repo 전수 분석 전략을 세우는 것은 이 Jira의 목표가 아니다.
- 실측 근거: `.local/benchmark-checkpoint.json` (PAT, n=50, 2026-09-02T02:38~02:45Z), `.local/root-manifest-probe.json` (raw 952회, n=28), `.local/manual-probe-log.json` (비인증 진단 47회)

## 1. 결론

**2026-08 1개월 Historical Dataset을 대상으로 활동량 순 Repo Enrichment를 장기 Offline Batch로 수행한다.** checkpoint/resume으로 중단·재개가 가능하며 이미 처리한 Repo는 재호출하지 않는다. 초기에는 Top 20k → 50k → 100k 순으로 확장하고, C조 기술 Mapping 결과가 MVP에 충분하다고 판단되는 시점에 **2026-08 FINAL Snapshot** 하나를 고정한다. 서비스는 그 Snapshot만 조회한다. 1개월 결과가 충분하면 동일 Pipeline을 3개월 또는 6개월 Historical Dataset으로 확장한다.

**Top-N은 영구 cutoff가 아니라 처리 우선순위다.**

## 2. 이번 Jira가 답해야 했던 것

| 질문 | 답 | 근거 |
|---|---|---|
| 장시간 Batch로 돌릴 수 있는가 | 예. Phase 1(Top 20k)이 약 10시간 | §3, §7 |
| 중단해도 이어서 할 수 있는가 | 예. rate limit 도달 시 reset까지 대기 후 재개 (`--max-cycles`) | §4 |
| 이미 처리한 Repo를 다시 부르는가 | 아니오. 재실행 시 fetch 요청 **0건** 실측 | §4 |
| Repo 하나 확인 비용은 | 수집 3 core / 2.47 MB / 2.63초, 404 1 core / 93 B | §3 |
| Full Tree 요청을 줄일 여지가 있는가 | 있다. root probe가 tree와 27/27 일치, core 0회 | §6 |
| 1개월 MVP Snapshot을 위한 실용적 방식은 | Top 20k → 50k → 100k 단계 확장 후 FINAL 고정 | §7, §8 |

## 3. Repo Fetch 비용 실측

n=50 rank-stratified 표본, 실제 GitHub REST API.

| 결과 | n | core 호출 | 응답량 | 소요 |
|---|---|---|---|---|
| 수집 성공 | 28 | **3.00** (metadata + branch HEAD + recursive tree) | 평균 2.47 MB / 중앙값 1.07 MB / 최대 9.71 MB | 평균 2.63초 |
| 404 | 22 | **1.00** | 93 B | 0.35초 |
| 동일 SHA 재검증 | 9 | **1.00** | 7.1 KB | 0.47초 |
| root manifest probe | 28 | **0** (raw 호스트) | 1.8 KB | — |

Stage별 응답량: A_METADATA 161,907 B (0.23%) / B_HEAD 736,199 B (1.06%) / **C_TREE 68,227,560 B (98.63%)** / D_MANIFEST 50,789 B (0.07%).

### 예산 회계

```
logged core 요청 (main run)          106
+ revalidation run                     9
+ rename 1건의 301 hop 과금            3
= 118  =  rate_limit_after.used      118   ✓
```

정확히 닫힌다. 이것이 두 가지를 동시에 증명한다. (1) `/rate_limit` 제어 호출은 예산을 **0** 소비한다. (2) `urllib`이 301 rename redirect를 따라가고 GitHub은 **양쪽 hop을 과금**하는데 계측은 마지막 응답만 기록한다 — 즉 "성공 Repo core 정확히 3회"는 요청 수로는 참이고 예산으로는 거짓이다. `budget_consumed`를 추가해 분리했다.

### 수집 성공 ≠ 분석 가능

HTTP 200을 받은 28개 중 **의존성 manifest를 가진 것은 6개(21.4%)**뿐이다. 다운로드 bytes의 87.6%가 manifest 0인 Repo에 쓰였다.

다만 **manifest 없음이 분석 불가는 아니다.** manifest 0인 22개 중 16개는 tree entry 100개 이상(중앙값 5,545)의 실제 소스 트리다. 확장자·import 기반 탐지는 이들에서도 기술을 뽑을 수 있다. 기술 판정은 C조 범위이므로 A조는 "분석 가능한 artifact가 있는가"까지만 기록한다(`has_analyzable_artifact`).

## 4. Checkpoint / Resume

| 항목 | 실측 |
|---|---|
| 동일 checkpoint 재실행 시 A/B/C/D 요청 | **각 0건** |
| 제어 호출 | 2회, 예산 소비 0 |
| `remaining` 전 / 후 | 4882 / 4882 |

- `SUCCEEDED` / `NOT_FOUND` / `PARTIAL`은 skip, `RATE_LIMITED` / `FAILED`만 재시도.
- rate limit 도달 시 종료하지 않고 `x-ratelimit-reset`까지 대기 후 다음 cycle 재개(`--max-cycles N`).
- checkpoint는 요약만 저장하고 GitHub 응답 원문을 저장하지 않는다. 쓰기는 임시 파일 후 원자적 교체.
- 대용량 실행을 위해 `--flush-every N` 추가. 매 Repo마다 전체 파일을 재직렬화하면 실행당 O(N²)이 되어 Top-50,000에서 저장 지연(1.36초/repo)이 fetch 예산(1.37초/repo)과 같아진다. 강제 종료 시 손실은 최대 N건이며 재fetch로 복구된다.

## 5. 404 Repo 처리

50개 중 22개(44%)가 404였다. 실측 진단 결과:

| 분류 | n |
|---|---|
| `OWNER_GONE` (계정 자체가 404) | 19 |
| `REPO_GONE_OWNER_ALIVE` (계정 200, public_repos 0) | 3 |
| `RENAMED_OR_TRANSFERRED` | **0** |

`GET /repositories/{repo_id}` 22건 전부 404, 대조군(수집 성공 3건)은 3/3 200. **`repo_id`로 회수된 Repo는 0개다.**

이름 기반 조회는 이미 rename을 처리한다 — `urllib`이 301을 따라가고 GitHub REST는 rename된 Repository를 301로 연결한다(표본의 rename 1건은 정상 수집됨). 따라서 **production 경로에 `repo_id` fallback을 넣지 않는다.** 회수율 0%인데 호출 비용만 늘린다. 진단용 `--classify-missing`으로만 남긴다(기본 off, missing Repo당 최대 2 core).

`NOT_FOUND`는 terminal로 유지한다. 단 GitHub은 삭제·정지·private·지역차단을 모두 404로 응답하므로 **"삭제됨"이 확정된 것은 아니다.** MVP에는 영향이 없다(어느 쪽이든 지금 가져올 수 없다). 구분이 필요해지면 2026-09 GH Archive에 해당 `repo_id`가 재등장하는지 교차하면 되고, GitHub API 호출은 필요 없다.

## 6. Tree 병목과 root probe PoC

**왜 병목인가:** recursive tree가 전체 응답량의 **98.63%**를 차지한다. 성공 Repo당 평균 2.47 MB, 최대 9.71 MB. core 호출 3회 중 1회이기도 하다.

**대안 PoC** (`AI/github/root_manifest_probe.py`): 수집 성공 28건의 pinned commit SHA에 대해 `raw.githubusercontent.com`으로 root manifest를 probe했다.

| 항목 | 값 |
|---|---|
| raw 요청 | 952회 (basename 30종 + liveness 4종) |
| **REST core 호출** | **0** (raw 호스트는 REST core 예산 밖) |
| 전송량 | Repo당 1.8 KB (tree 대비 **-99.9%**) |
| tree가 manifest를 찾은 Repo | 6 |
| root probe가 찾은 Repo | **6** |
| **tree와의 일치** | **27/27 = 100%** (recall 1.0) |
| basename을 12종→30종으로 확장 시 추가 발견 | **0건** |

즉 이 표본에서 2.47 MB짜리 recursive tree는 root probe 대비 **추가 정보를 주지 않았다.** 확장 목록이 아무것도 더 찾지 못했다는 것은 manifest가 없는 22개가 목록의 한계가 아니라 실제로 manifest를 갖지 않는다는 뜻이다.

### 권고 (후속 S15P21E102-150 Repo Fetch Orchestrator)

| | 현행 | 대안 |
|---|---|---|
| 흐름 | Metadata → branch HEAD → **recursive Tree** → Manifest | Metadata → pinned SHA → **cheap root probe** → 필요한 Repo만 Tree |
| core / 수집 Repo | 3.00 | 약 2.2 |
| 전송량 / 수집 Repo | 2.47 MB | 약 0.53 MB (**-78%**) |
| manifest 판정 | 전 depth 완전 | root 일치 100%(n=28), 하위 depth는 21%에서만 |

**적용 가치가 있다고 판단한다.** 다만 이번 -104에서 production 경로를 교체하지 않는다. n=28은 root probe를 확정하기에 작고, `raw.githubusercontent.com`의 rate limit은 GitHub 공식 문서에 아예 기재되어 있지 않아 대량 의존 시 리스크가 있다. -150에서 더 큰 표본으로 확인한 뒤 적용한다.

부가 발견 (문서 근거, 미검증): `GET /repos/{o}/{r}/git/trees/{tree_sha}`의 경로 파라미터는 공식 문서상 *"The SHA1 value or ref (branch or tag) name"* 이다. 사실이면 branch 이름을 직접 넣어 **Stage B를 데이터 손실 없이 삭제**할 수 있다(core 3→2). 실호출 1회로 확인 가능하며 -150 항목으로 넘긴다.

## 7. MVP Bootstrap 방식

**Top-N은 "어떤 Repo부터 먼저 분석할 것인가"를 정하는 우선순위이지 영구 cutoff가 아니다.**

2026-08 Repo Activity rank 순으로 Phase를 확장한다. Phase는 같은 후보 목록에 대한 `--limit N`일 뿐이고, checkpoint가 `repo_id` 키이므로 **다음 Phase는 새 Repo에 대해서만 비용을 지불한다.**

| Phase | 404율 | core 호출 | 응답량 (현행) | 응답량 (root probe) | 소요 (1 PAT) |
|---|---|---|---|---|---|
| Phase 1 · Top 20,000 | 24% | 50,345 | 37 GB | 8 GB | 약 10시간 |
| Phase 2 · Top 50,000 (누적) | 24~52% | 97,528 ~ 125,862 | 59 ~ 94 GB | 13 ~ 20 GB | 20 ~ 26시간 |
| Phase 3 · Top 100,000 (누적) | 24~62% | 176,100 ~ 251,724 | 94 ~ 187 GB | 20 ~ 40 GB | 37 ~ 52시간 |

- 404율은 **실제로 표본을 뽑은 rank에서만** 가져왔다: rank 1~20,043은 7/29 = 24.1%, rank 49,958~200,043은 15/21 = 71.4%. rank 20,044~49,957은 표본이 없어 보간하지 않고 **범위로 제시**한다.
- 1 PAT = 5,000 core/hr, safety 200 → cycle당 4,800.
- 20k / 50k / 100k는 **사용자에게 노출되는 Snapshot이 아니라 개발 중간 checkpoint다.**

Coverage 참고 (S15P21E102-109 실측): Top 20k = 24.56%, Top 50k = 39.05%, Top 100k = 53.46% (2026-08 valid event 기준, **시도** coverage).

## 8. 2026-08 FINAL Snapshot 고정 시점

C조가 기술 Mapping을 수행하고 다음이 확인되면 그 시점의 결과로 **2026-08 FINAL Snapshot** 하나를 고정한다.

- 기술 트렌드가 화면에서 의미 있게 보이는가
- 기술별 표본 수가 충분한가
- 발표·시연에 쓸 수 있는가

Snapshot은 `-109`가 세운 규칙을 그대로 상속한다: `period=2026-08` / `snapshot=<jira>-<YYYYMMDD>` / `errorifexists` / 동일 snapshot이면 시작 단계 중단. 서비스는 FINAL Snapshot만 조회한다. 중간 Phase 결과는 발행하지 않으므로 Snapshot 버전 간 분모 비교 문제가 생기지 않는다.

## 9. 1개월 → 3개월 → 6개월 확장

**현재 구현은 이미 기간에 종속되지 않는다.**

- `Infra/spark/repo_fetch_candidates.py`는 `--input-root`를 CLI 인자로 받고, `Infra/scripts/spark-repo-fetch-candidates.sh`는 `REPO_ACTIVITY_INPUT_ROOT` 환경변수를 읽는다. 다른 달로 바꾸려면 `period=YYYY-MM/snapshot=...`만 가리키면 된다. 코드 변경 없음.
- 이번에 checkpoint에 `dataset_key`를 추가했다. 후보 payload의 `input_root`와 묶여 있어 **2026-08 checkpoint로 2026-09를 이어받으려 하면 즉시 실패한다.** 기간마다 checkpoint 파일을 분리한다.

확장 흐름: GH Archive Raw → 월별 Repo Activity 집계 → 동일 Repo Enrichment → 월별 Technology Trend Snapshot. **이번 Jira에서 3/6개월을 실제 실행하지는 않는다.**

## 10. 코드 변경 및 단순화

### 인수 및 변경

| 파일 | 상태 | 줄 수 |
|---|---|---|
| `AI/github/repo_fetch_benchmark.py` | 수정 | 1,154 → 1,525 |
| `AI/github/root_manifest_probe.py` | **신규** (Tree 대안 PoC) | 301 |
| `AI/tests/test_repo_fetch_benchmark.py` | 수정 | 382 → 762 |
| `Infra/spark/repo_fetch_candidates.py` | 변경 없음 | 213 |
| `Infra/scripts/spark-repo-fetch-candidates.sh` | 변경 없음 | 44 |

Codex의 -104 작업물은 저장소가 아니라 staging 경로에 커밋되지 않은 채로 있었고, 유실 없이 인수했다. 기존 checkpoint를 파괴하지 않았고 성공 Repo 28건을 다시 Full Fetch하지 않았다.

### 고친 결함

| ID | 결함 | 수정 |
|---|---|---|
| D1 | 성공·실패 혼합 평균으로 비용과 coverage를 산정 | 결과별 원가 분리(`outcome_metrics`), 시도/수집 분리 |
| D2 | rate limit 도달 시 **중단**만 하고 재개 불가 | `--max-cycles`: reset까지 대기 후 다음 cycle 재개 |
| D3 | HTTP 403 + `Retry-After`(2차 제한)를 영구 실패로 처리 | `RATE_LIMITED`로 분류 |
| D4 | 재검증이 historical 이름으로 조회 | `canonical_repo_name` 우선 |
| D5 | 404 사유 미구분 | `--classify-missing` (기본 off) |
| F1 | `core_calls`가 실제 예산과 다름 (301 양쪽 과금) | `budget_consumed` 추가 |
| F2 | checkpoint에서 `requests` 제거 시 지표가 조용히 0 | 저장된 scalar로 fallback |
| F3 | checkpoint 저장이 실행당 O(N²) | `--flush-every` |
| F4 | coverage를 HTTP 200 기준으로 계산 | `has_analyzable_artifact` / `artifact_rate` |

### MVP 기준 단순화

검토 결과 다음을 제거했다. 검증된 checkpoint/resume/rate-limit/retry/idempotency는 손대지 않았다.

- `estimate_bootstrap`의 **`duration_scenarios`(1/3/5/7일 모델링) 제거.** MVP는 날짜가 아니라 Phase 단위로 계획한다.
- 기본 projection 크기를 `(20k, 50k, 100k, 200k, 300k, 500k)` → **`MVP_PHASE_SIZES = (20k, 50k, 100k)`**.
- Monte Carlo / power-law / rank×cohort 용량 모델 스크립트 삭제, 측정값만 쓰는 60줄짜리 `.local/mvp_cost.py`로 대체.

파일 분리는 하지 않았다. `repo_fetch_benchmark.py`는 이미 `UrllibTransport` / `GitHubClient` / `CheckpointStore` / `RepoFetchBenchmark` / 통계 함수로 경계가 나뉘어 있고, 쪼개면 `python -m github.repo_fetch_benchmark` 단일 진입점만 깨진다. `root_manifest_probe.py`는 책임이 다르고(REST core 미사용 측정 도구) -150에서 재사용되므로 별도 파일로 뒀다.

## 11. 테스트 / Secret

| 게이트 | 결과 |
|---|---|
| `pytest AI/tests` | **25 passed** (인수 시 13) |
| 테스트의 실제 API 호출 | **0.** `ScriptedTransport` 및 주입된 fake fetch만 사용 |
| `ruff check` / `ruff format --check` | 통과 |
| CRLF / 행 끝 공백 / EOF newline | 0 / 0 / 정상 |
| PAT·PEM·Authorization·AWS key 스캔 | 검출 0건 |
| PAT 전송 경로 | `api.github.com`에만 첨부, `raw.githubusercontent.com`에는 미첨부 (실행 검증) |
| Raw API 응답 커밋 | 없음. 실행 산출물은 `.local/`(gitignore) |
| staging 임시 PEM | 열람·복사·커밋하지 않았고 저장소 트리에 없음 |

## 12. 이번 Jira에서 하지 않은 것 (후속 이관)

MVP에 필요하지 않다고 판단해 중단한 항목이다.

| 항목 | 이관 |
|---|---|
| n=100 이상 정교한 재표본, rank × cohort 모델 | 후속 (필요해지면) |
| 전체 5,711,133 Repo 전수 분석 경제성 | 후속 |
| 30일/70일 장기 Bootstrap 세밀 모델링 | 후속 |
| 최적 Top-N 통계적 확정 | 불필요 — Top-N은 우선순위이지 cutoff가 아니다 |
| 24시간 SHA churn 실측 | 후속 (재검증 주기 설계 시) |
| `--max-cycles` 실 API 3시간 검증 | Phase 1 실행이 그 자체로 검증이 된다 |
| Snapshot 버전 간 분모 비교 규칙 | 불필요 — FINAL Snapshot 하나만 발행한다 |
| 3/6개월 실제 실행 | 후속 (1개월 결과 확인 후) |
| `trees/{ref}` branch 이름 수용 확인 (core 3→2) | **-150** |
| root probe production 적용 | **-150** |
| GraphQL 다중 alias 배치 비용 확인 | **-150** (1회 호출로 확인 가능) |

## 13. 재현 방법

```bash
# 후보 생성 — 다른 기간이면 --input-root만 바꾼다
REPO_ACTIVITY_INPUT_ROOT=hdfs:///gitjob/parquet/github/repo_activity/period=2026-08/snapshot=s15p21e102-109-20260902 \
  Infra/scripts/spark-repo-fetch-candidates.sh

# Phase 1 (GITHUB_API_TOKEN 또는 GITHUB_TOKEN 필요, 출력 금지)
PYTHONPATH=AI:Infra/spark python -m github.repo_fetch_benchmark \
  --candidates .local/repo-fetch-candidates.json \
  --checkpoint .local/benchmark-2026-08.json \
  --summary    .local/summary-phase1.json \
  --limit 20000 --max-cycles 24 --flush-every 200 \
  --safety-threshold 200 --max-manifests 10

# Phase 2 / 3 — 같은 checkpoint, --limit만 올린다 (완료 Repo는 재호출하지 않음)
#   --limit 50000  /  --limit 100000

# Tree 대안 PoC (REST core 0회)
PYTHONPATH=AI python -m github.root_manifest_probe \
  --checkpoint .local/benchmark-2026-08.json \
  --out .local/root-manifest-probe.json --widen

# 비용 요약 (API 0회)
python .local/mvp_cost.py

# 테스트 / lint (실제 API 호출 없음)
PYTHONPATH=AI:Infra/spark python -m pytest AI/tests -q
python -m ruff check . && python -m ruff format --check .
```

## 14. 판정

**A — MR 가능.**

완료 조건 대비:

| # | 조건 | 상태 |
|---|---|---|
| 1 | 1개월 Historical Bootstrap 방식 설명 | §1, §7 |
| 2 | Repo Fetch 비용 실측 | §3 (n=50, 실 API) |
| 3 | checkpoint / resume 검증 | §4 (재실행 fetch 0건 실측) |
| 4 | 404 처리 검증 | §5 (22건 전건 분류) |
| 5 | same SHA reuse 검증 | §3 (n=9, core -66.7%) |
| 6 | Tree 병목 실측 | §3, §6 (98.63%) |
| 7 | cheap probe 대안 PoC | §6 (27/27 일치, core 0회) |
| 8 | 테스트 통과 | §11 (25 passed) |
| 9 | Secret 안전 | §11 |
| 10 | 1개월 → 3/6개월 확장 구조 | §9 (`--input-root` 파라미터, `dataset_key` 가드) |
| 11 | docs 정리 | 이 문서 |
| 12 | README 요약 | `docs/data/README.md` |

12개 조건이 모두 충족됐다. n=100/300/500 재표본은 완료 조건이 아니며, MVP 판단에 필요한 실측(비용·resume·404·Tree·probe)은 전부 실제 API로 확보했다.

남은 불확실성은 정직하게 기록한다: rank 20,044~49,957 구간에 표본이 없어 Phase 2·3의 404율을 범위로 제시했고, root probe는 n=28 근거이며 `raw.githubusercontent.com`의 rate limit은 공식 문서에 없다. 셋 다 MVP 실행을 막지 않으며 Phase 1을 실제로 돌리면 자연히 해소된다.
