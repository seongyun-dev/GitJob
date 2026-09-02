# A→C GitHub Repo Snapshot 입력 계약

> 상태: v1 모델·Schema·Fixture 구현 완료 / 실제 A조 출력 연동 전
>
> 기준일: 2026-09-02
>
> Jira: [S15P21E102-157](https://ssafy.atlassian.net/browse/S15P21E102-157)
>
> 계약 버전: `github-repo-snapshot/v1`
>
> Authoritative source: [`AI/github/contracts.py`](../../AI/github/contracts.py)

## 1. 목적과 범위

이 계약은 A조가 GH Archive에서 활동 Repository를 집계하고 Top-N을 선정한 뒤,
GitHub API와 raw 요청으로 분석 기준 Commit·Tree·Artifact를 확보해 C조에 전달하는
JSON 경계다.

```text
GH Archive Raw
  → Spark Repository 활동량 집계
  → Top-N 선정
  → GitHub Repository/Branch 조회
  → 분석 기준 Commit 고정
  → Tree/Manifest 및 제한된 source 수집
  → GitHubRepoSnapshotBatch
  → C조 Registry mapping·Evidence 분석
```

GH Archive event 집계만으로 `pinned_commit_sha`, `tree_sha`, Manifest 원문은 생기지
않는다. 이 값은 Top-N 선정 후 GitHub Repository/Branch/Commit/Tree 및 raw 파일을
추가 조회해야 만들어진다.

이 계약은 Repository 기술 판정, `tech_id` 정규화, Evidence Level 계산, Manifest
종류 선정, source 추가 조회 조건을 구현하지 않는다. A조는 C조가 정한 수집 대상
규칙을 운영 한도 안에서 실행하고, 확보한 관측값과 Artifact를 추측 없이 전달한다.

이 계약을 추가했다고 해서 GH Archive Top-N을 서비스의 공개 GitHub Trend 지표로
확정한 것은 아니다. 현재 데이터 문서의 Trend MVP는 GitHub Innovation Graph KR
분기 `num_pushers`다. GH Archive 집계와 Repo Snapshot을 어떤 분석·화면에 사용할지는
검증 결과와 별도 기획 결정으로 확정해야 한다.

## 2. 책임 경계

| 구분 | 책임 |
|---|---|
| A조 | GH Archive 전체 Scan, Repository 활동량·순위 집계, Top-N 선정 |
| A조 | GitHub API로 분석 기준 Commit 고정, Tree 조회, 요청된 Manifest/source 수집 |
| A조 | HDFS 등 Artifact 저장 위치·hash·크기, 부분 수집 원인, checkpoint, 실제 적용 한도 전달 |
| C조 입력 경계 | strict validation으로 타입·추가 필드·상태 조합·한도 초과를 거부 |
| C조 분석 | Manifest/source 종류와 추가 조회 조건 정의, Registry mapping, 기술 사용 Evidence 판정 |

`pinned_commit_sha`는 외부 재현성 기준이라 모든 전달 record에 필수다. Commit을 아직
고정하지 못한 후보는 이 Snapshot 계약의 record가 아니며 A조 실행 상태/DLQ에서
관리한다. `tree_sha`는 A조의 변경 감지·캐시에 유용하지만 외부 분석 재현성의 필수
키가 아니므로 선택값이다.

## 3. 계약 자료와 검증 우선순위

1. [`AI/github/contracts.py`](../../AI/github/contracts.py): 필드·enum·cross-field
   validator의 단일 기준
2. [JSON Schema](contracts/github-repo-snapshot-v1.schema.json): 언어 중립 구조 계약
3. [정상 Fixture](../../AI/github/fixtures/github_repo_snapshot_v1.json):
   `COMPLETE`, `PARTIAL`, `FAILED`, `REUSED` 고정 사례
4. [오류 Fixture](../../AI/github/fixtures/invalid_github_repo_snapshot_v1.json):
   필수값·상태·한도·경로 오류 사례
5. 이 문서: 사람을 위한 의미와 운영 경계

JSON Schema는 필드, 타입, enum, pattern, 최소값을 검사한다. 상태별 필수 조합,
timezone, 중복 Repository, 실제 Artifact 합계와 정책 한도의 관계는 Pydantic runtime
validator가 검사하므로 Schema 통과만으로 계약 통과를 단정하지 않는다.

## 4. Batch 필드

| 필드 | 타입 | 필수 | 의미 |
|---|---|---:|---|
| `schema_version` | string | 예 | 정확히 `github-repo-snapshot/v1` |
| `dataset_snapshot_id` | string | 예 | A조가 생성한 이 전달 Dataset의 비공백 식별자 |
| `pipeline_run_id` | string | 예 | 집계·확장 조회 실행 식별자 |
| `collector_version` | string | 예 | A조 수집기/변환기 버전 |
| `generated_at` | date-time | 예 | timezone을 포함한 ISO 8601 생성 시각 |
| `collection_policy` | object | 예 | 이번 실행에 실제 적용된 운영 한도 |
| `records` | array | 예 | Repository Snapshot 목록 |

Batch 안에서 `repo_snapshot_id`, `github_repo_id`, 대소문자를 무시한
`repo_full_name`, `activity_rank`는 중복될 수 없다. record 수와 각 rank는
`top_n_limit`을 초과할 수 없다.

## 5. 실행 정책 필드

| 필드 | 타입 | 규칙·의미 |
|---|---|---|
| `policy_version` | string | 실행 정책 버전, 비공백 |
| `top_n_limit` | integer | Top-N 후보 최대값, 1 이상 |
| `max_api_calls` | integer | GitHub API 최대 호출 예산, 1 이상 |
| `max_runtime_seconds` | integer | 실행 최대 시간, 1초 이상 |
| `max_tree_entries` | integer | Repository별 처리할 Tree entry 최대값, 1 이상 |
| `max_artifact_files` | integer | Repository별 저장 Artifact 최대 개수, 1 이상 |
| `max_artifact_bytes` | integer | Repository별 Artifact 총 byte 최대값, 1 이상 |

위 필드는 운영 기본값을 이 계약에 하드코딩한다는 뜻이 아니다. A조는
`S15P21E102-104` 비용·시간 실측 후 설정값을 정하고, payload에는 해당 실행에 실제
적용한 값을 기록한다. Fixture의 숫자는 계약 검증용 synthetic 값이며 운영 권장값이
아니다.

## 6. Repository Snapshot 필드

| 필드 | 타입 | 필수 | null | 규칙·의미 |
|---|---|---:|---:|---|
| `repo_snapshot_id` | string | 예 | 아니요 | Repository 단위 Snapshot 식별자 |
| `github_repo_id` | integer | 예 | 아니요 | GitHub API Repository ID, 양수 |
| `repo_full_name` | string | 예 | 아니요 | `owner/repository` 형태 |
| `activity_metric` | string | 예 | 아니요 | 순위 계산에 사용한 지표 이름. 의미를 C조가 추정하지 않도록 원천 명칭 보존 |
| `activity_period_start` | date | 예 | 아니요 | 활동 집계 시작일 |
| `activity_period_end` | date | 예 | 아니요 | 활동 집계 종료일, 시작일보다 빠를 수 없음 |
| `activity_count` | integer | 예 | 아니요 | 해당 지표의 관측값, 0 이상 |
| `activity_rank` | integer | 예 | 아니요 | Top-N 내 순위, 1 이상 |
| `pinned_commit_sha` | string | 예 | 아니요 | C조 분석 기준인 소문자 40자리 Git Commit SHA |
| `tree_sha` | string | 예 | 예 | A조 캐시/변경 감지용 Tree SHA, 없어도 외부 계약 유효 |
| `collection_status` | enum | 예 | 아니요 | `COMPLETE`, `PARTIAL`, `FAILED`, `REUSED` |
| `collection_issues` | enum array | 아니요 | 아니요 | 부분/실패 원인, 기본값 `[]` |
| `checkpoint_uri` | string | 아니요 | 예 | Rate Limit 중단 후 재개 지점 |
| `reused_from_snapshot_id` | string | 아니요 | 예 | 동일 Commit으로 재사용한 이전 Snapshot |
| `tree_truncated` | boolean | 예 | 아니요 | GitHub Tree 응답 잘림 관측값 |
| `observed_tree_entries` | integer | 예 | 아니요 | 처리한 Tree entry 수, 0 이상 |
| `artifacts` | array | 아니요 | 아니요 | 확보한 Manifest/source, 기본값 `[]` |

`activity_metric`은 이 계약이 활동량 산식을 정한다는 뜻이 아니다. A조가 사용한
event 종류·집계 단위를 안정된 이름으로 전달해야 하며, C조는 서로 다른 metric을
같은 값으로 합치지 않는다.

## 7. Artifact 필드

| 필드 | 타입 | 규칙·의미 |
|---|---|---|
| `artifact_type` | enum | `MANIFEST` 또는 `SOURCE` |
| `path` | string | Repository root 기준 POSIX 상대 경로. 절대경로, `..`, 역슬래시 금지 |
| `uri` | string | HDFS 등 원문 저장 위치, 비공백 |
| `content_hash` | string | 소문자 SHA-256 형식 64자리 |
| `size_bytes` | integer | 저장 Artifact 크기, 0 이상 |

같은 Repository Snapshot에서 Artifact path는 중복될 수 없다. 파일 개수와 byte
합계는 Batch의 `max_artifact_files`, `max_artifact_bytes`를 초과할 수 없다. 이 계약은
Artifact 원문을 PostgreSQL에 row 단위 저장하거나 API 응답으로 노출하도록 요구하지
않는다.

## 8. 상태와 부분 수집 규칙

| 상태 | 계약 조건 |
|---|---|
| `COMPLETE` | `collection_issues=[]`, checkpoint와 reuse source 없음 |
| `PARTIAL` | 하나 이상의 `collection_issues` 필수. 확보한 Artifact는 유지 |
| `FAILED` | Commit 고정 이후 수집 실패 원인 하나 이상 필수. 확보한 Artifact는 유지 가능 |
| `REUSED` | `reused_from_snapshot_id` 필수, collection issue/checkpoint/tree truncation 없음 |

허용 issue는 `TREE_TRUNCATED`, `TREE_LIMIT_REACHED`, `FILE_LIMIT_REACHED`,
`BYTE_LIMIT_REACHED`, `RATE_LIMITED`, `ARTIFACT_FETCH_FAILED`,
`REPOSITORY_UNAVAILABLE`이다.

- `tree_truncated=true`이면 `TREE_TRUNCATED`가 반드시 있어야 하며 그 반대도 같다.
- `RATE_LIMITED`이면 `checkpoint_uri`가 필수다.
- Tree가 잘렸다는 이유로 무제한 하위 Tree 조회를 수행하지 않는다.
- Rate Limit 발생 시 확보한 Artifact를 폐기하지 않고 checkpoint에서 재개한다.

## 9. Cache와 재사용

A조는 Repository HEAD를 다시 확인한 뒤 이전 Snapshot과
`pinned_commit_sha`가 같으면 TTL과 관계없이 기존 Artifact를 재사용할 수 있다.
이때 새 record는 `collection_status=REUSED`와 `reused_from_snapshot_id`를 기록한다.
SHA가 바뀌면 새 Snapshot을 생성한다.

TTL은 기존 분석물의 유효기간이 아니라 HEAD 재확인 주기다. 구체적인 TTL 값은
비용 실측 전까지 이 계약에서 정하지 않는다.

## 10. 검증 방법

저장소 root에 프로젝트 Python 환경을 준비한 뒤 `AI/`에서 실행한다.

```powershell
$python = "..\.venv\Scripts\python.exe"
& $python -m pytest tests/test_github_repo_contracts.py -q
& $python -m ruff check github tests/test_github_repo_contracts.py
& $python -m ruff format --check github tests/test_github_repo_contracts.py
```

정상 Fixture runtime 검증:

```powershell
& $python -c "from pathlib import Path; from github.contracts import GitHubRepoSnapshotBatch; GitHubRepoSnapshotBatch.model_validate_json(Path('github/fixtures/github_repo_snapshot_v1.json').read_text(encoding='utf-8')); print('valid fixture: PASS')"
```

## 11. 아직 확인하지 못한 범위

- A조 실제 Spark 집계 출력의 `activity_metric`, 날짜, rank 타입
- 실제 GitHub API 호출 결과를 이 Batch로 변환하는 A조 adapter
- HDFS Artifact URI 형식·접근 권한·보존 정책
- `S15P21E102-104`에서 확정할 Top-N/API/time/Tree/file/byte 운영값
- private Repository 수집 시 raw 접근·권한·민감정보 처리
- checkpoint 재개와 동일 SHA Artifact 재사용의 end-to-end 실행
- C조 Manifest/source 요청 규칙과 Registry/Evidence 분석 연결

## 12. 관련 자료

- 계약 코드: [`AI/github/contracts.py`](../../AI/github/contracts.py)
- JSON Schema: [`github-repo-snapshot-v1.schema.json`](contracts/github-repo-snapshot-v1.schema.json)
- 정상 Fixture: [`github_repo_snapshot_v1.json`](../../AI/github/fixtures/github_repo_snapshot_v1.json)
- 오류 Fixture: [`invalid_github_repo_snapshot_v1.json`](../../AI/github/fixtures/invalid_github_repo_snapshot_v1.json)
- 회귀 테스트: [`AI/tests/test_github_repo_contracts.py`](../../AI/tests/test_github_repo_contracts.py)
- 데이터 파이프라인: [`docs/data/README.md`](README.md)
- A조 비용 실측 예정 이슈: [S15P21E102-104](https://ssafy.atlassian.net/browse/S15P21E102-104)
