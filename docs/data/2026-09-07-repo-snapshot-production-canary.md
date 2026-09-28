# GitHub Repo Snapshot Production Canary 검증

> Jira: [S15P21E102-163](https://ssafy.atlassian.net/browse/S15P21E102-163)
>
> 선행: [S15P21E102-162](https://ssafy.atlassian.net/browse/S15P21E102-162) data-node 배포 상태 확인
>
> 계약: `github-repo-snapshot/v1` (변경 없음)
>
> 검증 수준: 공개 Repo 1건 Production Runtime 실측

## 1. 배경과 범위

S15P21E102-114 문서에 기록된 data-node canary는 변경 소스를 read-only bind한 one-off
Worker에서 실행한 결과이며 배포된 image로 실행한 것이 아니다. 그 문서는 "코드 병합과
production image 배포 후 별도 batch 실행"을 남은 과제로 두었다.

이 문서는 S15P21E102-162에서 배포 상태를 확인한 data-node에서, 배포된 image 그대로
공개 Repo 1건을 수집 -> Artifact -> HDFS publish -> read-back까지 실행한 **실측 결과**만
기록한다.

코드 변경은 없다. Top 20,000 수집은 실행하지 않았다.

## 2. 검증 환경

| 항목 | 값 |
|---|---|
| 실행 위치 | data-node (`j15e102a`) |
| 기준 커밋 | `origin/develop` `9966955` |
| Image | Canary 당시 full image ID/digest는 기존 기록에 보존되지 않아 확정 불가 |
| 실행 스크립트 | `Infra/scripts/repo-snapshot-bootstrap.sh` |
| 환경 | `ENV_FILE=.env.data`, `COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml`, `PROFILES=data` |
| Snapshot ID | `s15p21e102-163-canary-20260907` |
| Pipeline run ID | `s15p21e102-163-canary-run1` |
| 후보 수 | `REPO_FETCH_PHASE_TOP_N=1` |
| Checkpoint 경로 | 스크립트 기본값: `<repo-root>/.local/repo-snapshot-bootstrap/s15p21e102-163-canary-20260907/checkpoint.json` (실행 당시 `REPO_BOOTSTRAP_STATE_ROOT` override는 기록되지 않음) |

후보 입력은 Spark Top-N job을 실행하지 않고 `repo-fetch-candidates/v1` 1건을 직접
작성했다. `load_candidates()`가 요구하는 것은 `schema_version`, 비어 있지 않은
`input_root`, 각 row의 `repo_id`/`repo_name`/`activity_count`/`rank`뿐이므로 1 Repo
canary에 Spark 실행은 필요하지 않다. 따라서 이번 Canary에서는
`Spark Top-N output → candidates.json → load_candidates() → Bootstrap` 실제 연결
경로를 검증하지 않았다.

PAT는 env file을 통해 Worker 환경변수로만 전달했고 CLI 인자에 값을 넣지 않았다.

## 3. 수집 결과 (실측)

대상 Repo는 `pallets/flask` (`repo_id=596892`)이다.

| 항목 | 실측 결과 |
|---|---:|
| `collection_status` | `COMPLETE` |
| Snapshot 계약 | `github-repo-snapshot/v1` |
| `record_count` | 1 |
| Artifact | 5개 |
| 실패 Repo | 0 |
| Repo Core 요청 | 3 |
| Repo raw 요청 | 5 |
| control Core 요청 | 1 |
| checkpoint | 생성됨 |
| HDFS publish | 성공 |

Repo당 Core 3회는 metadata, default branch HEAD, recursive tree 세 호출이다.
S15P21E102-114 canary 실측(Core 3 / raw 5 / Artifact 5)과 같은 값이며, 배포 image
경로에서도 Repo당 요청량은 달라지지 않았다.

`control Core 요청=1`은 코드상 실행 시작 전에 `GitHubClient.core_rate_limit()`이
`/rate_limit`을 조회하는 사전 확인 1회이며, Repo Core 3회와 별도로 집계된다.

## 4. HDFS publish와 read-back (실측)

```text
hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=s15p21e102-163-canary-20260907/
```

Snapshot에 기록된 Artifact URI로 바이트를 다시 읽어 계약의 SHA-256과 비교했다.

| 항목 | 실측 결과 |
|---|---:|
| read-back 성공 Artifact | 5 / 5 |
| SHA-256 일치 | 5 / 5 |
| `READBACK_OK` | 5 |

동일 checkpoint 재실행 후에도 published Artifact 5개 및 checksum이 기존 결과와
동일함을 확인했다. 재실행 후 read-only HDFS listing에서 Artifact 파일 5개를
확인했고, 각 바이트의 SHA-256이 `snapshot.json`의 `content_hash`와 모두 일치했다.

| Artifact path | 현재 read-only SHA-256 |
|---|---|
| `pyproject.toml` | `d4b8029dc2ce71866e45fee381bdfb91e0cfc35a67715c5e591bdde80cfc25f8` |
| `examples/celery/pyproject.toml` | `093a91a28634f15a48c51dbd725ae553825f2d81f776d8b3a06e879ccc7eb153` |
| `examples/celery/requirements.txt` | `96eaefbbd532b79f687e17d0418807257cddf6f9c1d15aad0b11683ebf23a382` |
| `examples/javascript/pyproject.toml` | `d86a7577ac38b09613b280340d93585852990e4edd77746030b289517c74dbbc` |
| `examples/tutorial/pyproject.toml` | `1b2ff9761cb43059ed8df3f1c27d93cd93c3bf9297fe7fe5716da943a75012ac` |

## 5. 동일 checkpoint 재실행 (실측)

같은 `REPO_SNAPSHOT_ID`/`REPO_PIPELINE_RUN_ID`로 다시 실행한 결과는 다음과 같다.

- terminal Repo의 결과를 재사용했고 추가 Repo fetch는 0건
- `attempts=1` 유지
- 기존 `generated_at` 유지
- 기존 fetch counter 유지

## 6. 미검증 / 제약

- 이 결과의 표본은 공개 Repo 1건이므로 Top 20,000 전체의 성공률이나 Artifact 분포를
  대표하지 않는다.
- Top 20,000 전체 수집의 Artifact count, HDFS small-file 영향, 총 runtime은 미측정이다.
- Top 20,000 실행에서는 GitHub API rate limit wait/resume이 핵심 운영 경로이며, 해당
  경로는 이번 1 Repo Canary에서는 발생하지 않아 대표되지 않는다.
- Canary 당시 full image ID/digest는 기존 기록에 보존되지 않아 확정할 수 없다. 요청한
  data-node read-only `docker image inspect`도 SSH private key 권한 오류로 수행되지
  않았으므로 현재 image를 Canary image라고 추정하지 않는다.
- 이번 Canary는 수동 1 Repo candidate를 사용했으므로 Spark Top-N output →
  `candidates.json` → `load_candidates()` → Bootstrap 연결은 미검증이다.
- 다른 `snapshot_id`에서 shared cache로 `REUSED`가 생성되는 경로는 이번 검증에서
  실행하지 않았다.
- private Repository와 권한별 404 구분은 이번 범위 밖이다.
- C조의 별도 consumer read 검증은 S15P21E102-160 범위이며, 이번 문서는 A조의
  Snapshot publish/read-back 결과만 다룬다.

## 7. 판정

기록된 Canary 배포 image 실행 결과 기준으로 수집, HDFS publish, read-back, 동일
checkpoint 재실행이 모두 정상 동작했다. Top 20,000 Bootstrap 진행을 막는 blocker는
확인되지 않았다.

## 8. 관련

- Jira: S15P21E102-163 / S15P21E102-162 / S15P21E102-114
- 코드: `Infra/scripts/repo-snapshot-bootstrap.sh`, `AI/github/repo_snapshot_bootstrap.py`, `AI/github/repo_fetch_orchestrator.py`
- 문서: [S15P21E102-114 Repo Snapshot 부트스트랩 배치](2026-09-04-repo-snapshot-bootstrap-batch.md), [A→C GitHub Repo Snapshot 계약](2026-09-02-a-to-c-github-repo-snapshot-contract.md)
