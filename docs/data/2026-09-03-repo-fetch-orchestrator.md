# GitHub Repo Fetch Orchestrator

> Jira: [S15P21E102-150](https://ssafy.atlassian.net/browse/S15P21E102-150)
>
> 상태: 구현·Unit Test·공개 GitHub 표본 Runtime 검증 완료 / HDFS Runtime 검증 전
>
> 기준 develop: `1ef4a3bcccfb02a1cc2fab9673984193ce3abb4e`

## 1. 목적과 Jira 범위

Repo Activity 우선순위 후보를 입력받아 GitHub Repository의 분석 기준 Commit을
고정하고, recursive Tree에서 필요한 Artifact만 선택·저장한 뒤 C조가 소비하는
`github-repo-snapshot/v1`을 생성한다.

Jira에서 실제 확인한 완료 조건은 다음과 같다.

- Tree → named manifest → 필요한 source 순서 검증
- SHA가 같은 Repository의 외부 재조회 최소화와 Cache 재사용
- API/raw 요청 횟수와 실패 사유의 Repository 단위 기록
- Rate Limit 중단 후 같은 Repository부터 재개
- 후행 `S15P21E102-114`가 같은 인터페이스로 Bootstrap Batch 실행

이번 구현은 Artifact 수집과 입력 계약 생성까지만 담당한다. `tech_id`, Technology
Registry Mapping, Evidence Level, Required/Preferred, 추천, What-if는 만들지 않는다.

## 2. S15P21E102-157 선행 검증

최신 develop에 아래 커밋과 산출물이 실제 포함되어 있음을 확인했다.

- commit: `b3cfd8a525afcbb42e9b3f321b78ff43f56c6168`
- Pydantic: `AI/github/contracts.py`
- JSON Schema: `docs/data/contracts/github-repo-snapshot-v1.schema.json`
- 정상/오류 Fixture: `AI/github/fixtures/`
- 회귀 테스트: `AI/tests/test_github_repo_contracts.py`
- 계약 문서: `docs/data/2026-09-02-a-to-c-github-repo-snapshot-contract.md`

계약 버전은 `github-repo-snapshot/v1`이고 모든 모델은 unknown field를 거부한다.
Repository는 양수 `github_repo_id`와 `owner/repository` 형식의 `repo_full_name`으로
식별한다. `pinned_commit_sha`는 모든 전달 record에 필수이며 `tree_sha`는 optional이다.
`pinned_commit_sha`는 고정한 Git commit object의 SHA이고, `tree_sha`는 그
commit object의 중첩 `commit.tree.sha`인 Git tree SHA다. 두 값은 서로 다른
lineage 필드로 보존한다. Recursive Tree API의 최상위 `sha`는 요청 ref를
반환하는 응답도 있으므로 `tree_sha`를 덮어쓰는 근거로 사용하지 않는다.

Artifact는 `MANIFEST` 또는 `SOURCE`와 repository-relative POSIX path, 원문 URI,
SHA-256 `content_hash`, `size_bytes`를 전달한다. Batch lineage는
`dataset_snapshot_id`, `pipeline_run_id`, `collector_version`,
`collection_policy.policy_version`으로, Cache lineage는
`reused_from_snapshot_id`로 표현한다.

상태는 `COMPLETE`, `PARTIAL`, `FAILED`, `REUSED`이고 부분/실패 원인은
`collection_issues`로 전달한다. `RATE_LIMITED`는 `checkpoint_uri`가 필수다.

### 생산자와 소비자 책임

| 필드/단계 | A조 | C조 |
|---|---|---|
| Repo Activity·rank·기간 | 채움 | 입력 검증·소비 |
| pinned Commit·Tree SHA | 조회·채움 | 재현 기준으로 소비 |
| Artifact URI/hash/size | 수집·저장·채움 | Registry/Evidence 분석 입력으로 소비 |
| collection status/issues | 관측 결과를 채움 | 실패와 기술 부재를 구분 |
| `tech_id`·Evidence Level | 생성하지 않음 | 후속 분석에서 생성 |

C조는 A→C 입력 계약 필드를 보충하지 않는다. A조가 계약을 완성해 전달하고 C조는
그 이후 의미 분석 결과를 별도 계약으로 만든다.

## 3. Contract Gap 판단

별도 Repo Snapshot Model/Schema/Fixture는 만들지 않았다. 기존 `-157` 계약으로
pinned Repository의 Artifact selection 결과, partial/failure, checksum, checkpoint,
Cache reuse lineage를 표현할 수 있다.

다음 차이는 의도적인 실행 상태 경계이며 계약 변경 사유가 아니다.

- metadata/HEAD 404처럼 Commit을 고정하지 못한 `NOT_FOUND`는
  `pinned_commit_sha`가 필수인 C조 Snapshot record가 아니다.
- `NOT_FOUND`, pre-pin 인증 실패, Rate Limit은 Orchestrator checkpoint와 실행
  summary에 남긴다. 가짜 SHA로 C조 record를 만들지 않는다.
- historical `repo_name`은 checkpoint에 보존하고, C조 record에는 GitHub가 반환한
  canonical `repo_full_name`을 기록한다.
- source language·확장자 집계는 v1 계약과 이 Jira의 필수가 아니다. 필요해질 때
  C조 소비 요구를 먼저 확인한다.

## 4. 구현 구조

| 파일 | 책임 |
|---|---|
| `AI/github/client.py` | 인증된 REST와 비인증 raw 요청, retry, rate-limit header |
| `AI/github/repo_fetch_policy.py` | Tree entry 필터와 deterministic Artifact 선택 |
| `AI/github/repo_fetch_store.py` | immutable Artifact, cross-period Cache, checkpoint |
| `AI/github/repo_fetch_orchestrator.py` | 호출 순서, 상태 전환, v1 Batch 생성, CLI |
| `AI/github/repo_fetch_benchmark.py` | 기존 benchmark; 공통 client/policy만 import |

기존 benchmark의 Transport/Client를 두 번째 실제 소비자가 재사용할 수 있도록
`github.client`로 추출했다. 기존 benchmark API는 re-export해 기존 테스트 소비자를
깨지 않는다.

## 5. 수집 흐름과 정책

```text
Repo Activity candidate
  → Core rate-limit safety 확인
  → Repository metadata/canonical name
  → default branch HEAD / pinned_commit_sha + root tree_sha
  → (policy fingerprint, repo_id, pinned SHA) Cache
  → recursive Tree
  → named manifest 선택
  → manifest가 없고 source 수집이 활성화된 경우에만 source 선택
  → raw fetch / checksum / immutable store
  → github-repo-snapshot/v1
```

기본 정책은 `-104` 결정을 따른다.

- manifest 최대 24개
- source 기본 0개; 활성화 시 파일 앞 8 KiB
- 파일당 256 KiB
- Repository당 Artifact 총 1 MiB
- 최대 depth 8, 최대 Tree entry 100,000
- vendor/build/generated 계열 경로 제외

root manifest probe를 선행하지 않는다. recursive Tree를 먼저 받고 local에서 named
manifest를 선택한다. source fallback은 manifest가 없고 명시적으로 활성화됐을 때만
동작한다.

정책 label만 같은데 실제 limit가 바뀐 경우도 재사용하지 않도록 모든 policy 값을
SHA-256 fingerprint로 묶는다. Cache key는 이 fingerprint, `github_repo_id`,
`pinned_commit_sha`의 조합이다.

## 6. Cache, Checkpoint, Replay

- Cache는 `COMPLETE` record만 저장한다.
- 다른 기간이라도 policy와 Repo/SHA가 같으면 새 record를 `REUSED`로 만들고 기존
  Artifact URI를 재사용한다.
- SHA 또는 policy 값이 하나라도 바뀌면 Cache miss다.
- checkpoint는 dataset, pipeline run, collector, policy fingerprint와 candidate
  identity에 묶인다. 다른 입력으로 재사용하면 실패한다.
- 이전 Cache에 `tree_sha == pinned_commit_sha`가 남아 있어도 같은 pinned
  commit의 HEAD tree SHA를 확인한 뒤 Artifact URI/checksum은 건드리지 않고
  tree metadata만 repair한 후 `REUSED`할 수 있다.
- `COMPLETE/PARTIAL/FAILED/NOT_FOUND/REUSED`는 재실행에서 Repo fetch를 건너뛴다.
- `RATE_LIMITED`는 terminal이 아니며 다음 실행에서 같은 Repo를 다시 시작한다.
- checkpoint/cache JSON 전체 재작성은 기본 100 Repo 단위로 batch하고 정상 종료 및
  Rate Limit 중단 시 flush한다.
- Artifact와 최종 Snapshot은 동일 경로의 다른 내용으로 덮어쓰지 않는다.

## 7. 후행 Batch 인터페이스

`Infra/spark/repo_fetch_candidates.py`가 만든 `repo-fetch-candidates/v1` JSON을 입력으로
사용한다. PAT는 CLI 인자가 아니라 환경변수 이름으로만 참조한다.

```powershell
$env:GITHUB_TOKEN = "<runtime secret>"
$python = "..\.venv\Scripts\python.exe"
& $python -m github.repo_fetch_orchestrator --candidates ..\.local\repo-fetch-candidates.json --output ..\.local\github-repo-snapshot.json --summary-output ..\.local\github-repo-fetch-summary.json --checkpoint ..\.local\github-repo-fetch-checkpoint.json --cache ..\.local\github-repo-fetch-cache.json --artifact-root ..\.local\github-artifacts --dataset-snapshot-id s15p21e102-150-20260903 --pipeline-run-id s15p21e102-150-run-001 --period-start 2026-08-01 --period-end 2026-08-31 --limit 20000
```

Rate Limit 또는 budget으로 중단되면 checkpoint/summary만 갱신하고 최종 Snapshot
경로에는 publish하지 않는다. 같은 명령으로 재개해 terminal 상태가 된 뒤에만
immutable Snapshot을 publish한다.

## 8. 검증 상태

Unit Test는 fake transport와 임시 filesystem만 사용하며 실제 GitHub를 호출하지
않는다.

- 정상 Repo와 recursive Tree 순서
- manifest 우선, manifest 부재 시 source 8 KiB
- 404/empty/malformed/timeout/retry
- Tree truncation과 file/tree/byte limit
- 동일 SHA Cache hit, 변경 SHA와 변경 policy Cache miss
- Rate Limit 전/후 pinned 상태와 checkpoint resume
- 동일 dataset replay/idempotency
- `github-repo-snapshot/v1` runtime validation
- 기존 benchmark와 `-157` 계약 regression

현재 관련 suite 결과: **67 passed**.

### 공개 GitHub 표본 Runtime

2026-09-03에 공개 Repository `pallets/flask`(GitHub repo id `596892`) 1개를
대상으로 환경변수 PAT를 사용해 소량 검증했다. PAT 값과 Authorization header는
출력하거나 저장하지 않았다.

| 단계 | 상태 | Repo Core 요청 | raw 요청 | 확인 결과 |
|---|---:|---:|---:|---|
| 최초 수집 | `COMPLETE` | 3 | 5 | Artifact 5개, issue 없음 |
| 동일 SHA·다음 dataset | `REUSED` | 2 | 0 | 기존 Snapshot lineage 일치 |
| 동일 checkpoint replay | `REUSED` | 0 | 0 | Batch 동일, attempts 1 유지 |

최초 rate-limit control의 Core remaining은 4,987, 모든 검증 뒤 control은
4,982였다. 별도로 manifest 상한을 2개로 낮춘 실행에서는
`FILE_LIMIT_REACHED`와 Artifact 2개를 가진 `PARTIAL`이 관측되어 limit 상태도
명시적으로 기록됨을 확인했다.

### 기존 Repository baseline issue

현재 Branch 전체 Pytest는 **218 passed, 1 failed**였다. 동일한 최신
`origin/develop`(`1ef4a3bcccfb02a1cc2fab9673984193ce3abb4e`)를 임시
worktree에서 실행해도 **202 passed, 1 failed**였고, 두 failure 모두
`technology-registry-v1.schema.json`의 CRLF/LF byte mismatch였다.

전체 Ruff도 현재 Branch와 `origin/develop` 모두 기존 파일
`AI/llm/test_server.py`, `AI/tests/test_repo_fetch_benchmark.py`의 I001 2건이
동일했다. format check도 두 기준 모두 기존 `AI/llm/test_server.py` 1건이
동일했다. 이번 변경 파일을 대상으로 한 Ruff check/format check는 통과했다.
따라서 이 세 결과는 이번 Branch가 만든 regression이 아니다.

## 9. 미검증·후속 위험

- `FileArtifactStore`의 local `file://` URI만 구현·검증했다. HDFS/WebHDFS Artifact
  adapter, 접근 권한, 보존 정책은 `-114` Runtime 환경과 함께 검증해야 한다.
- GitHub raw host가 Range를 무시하면 client는 source 본문을 8 KiB로 잘라 저장하지만
  네트워크 전송량은 더 클 수 있다.
- source fallback 기본값은 0이다. C조가 요청할 source path/확장자 규칙은 별도 합의
  없이 넓히지 않는다.
- private Repository 수집과 권한별 404 구분은 검증하지 않았다.
