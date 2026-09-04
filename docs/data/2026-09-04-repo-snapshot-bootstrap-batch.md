# GitHub Repo Snapshot 부트스트랩 배치

> Jira: [S15P21E102-114](https://ssafy.atlassian.net/browse/S15P21E102-114)
>
> Phase 1: Repo Activity 연속 rank Top 20,000
>
> 입력 계약: `github-repo-snapshot/v1` (변경 없음)

## 1. 범위

S15P21E102-150 Repo Fetch Orchestrator를 Repo Activity Top-N에 장기 실행한다.
checkpoint와 진행률, Core Rate Limit, active runtime과 대기 시간을 기록하고 완료된
Snapshot과 실패 Repo 보고서를 C조가 읽을 수 있는 HDFS namespace에 publish한다.

A조는 Repo 후보, pinned commit/tree, Artifact, checksum, lineage와 수집 상태만 만든다.
`tech_id`, Technology Registry Mapping, Evidence L0~L3, Required/Preferred, Skill Gap,
Recommendation, Serving 집계와 B조 DB UPSERT는 이 배치의 범위가 아니다.

## 2. Artifact 저장 경계

```text
RepoFetchOrchestrator
  -> ArtifactStore
       -> FileArtifactStore       # local test/canary
       -> WebHdfsArtifactStore    # shared bootstrap output
```

Worker image는 Python 3.12 slim이고 Hadoop CLI/JRE가 없다. 이미 설치된 Python 표준
라이브러리 `urllib`만으로 WebHDFS `GETFILESTATUS`, `MKDIRS`, `CREATE`, `RENAME`,
`OPEN`, `DELETE`를 수행하므로 Python dependency 추가는 없다.

기존 GH Archive sink의 범용 HTTP transport만 `AI/common/webhdfs.py`로 추출했다.
시간별 gzip 이름과 `/gitjob/raw/gharchive/dt=...`에 결합된 Raw sink는 Repo Artifact
저장에 재사용하지 않는다. 두 저장소 모두 temporary object를 만든 뒤 atomic rename하며,
이미 존재하는 최종 경로의 다른 바이트를 덮어쓰지 않는다.

`RepoArtifact.uri`는 non-blank string 계약이므로 `hdfs:///...` URI를 그대로 담을 수
있다. Pydantic Model, JSON Schema와 Fixture 변경은 필요하지 않다.

### Canonical namespace

기존 `PROJECT_GUIDE.md`의 analysis input convention을 적용한다.

```text
/gitjob/analysis_input/github/repo_snapshot/snapshot_id={snapshot_id}/
  snapshot.json
  run-summary.json
  failures.json
  _SUCCESS.json
  artifacts/
    policy={policy_hash}/repo_id={repo_id}/commit={pinned_commit_sha}/{repo_path}
```

`_SUCCESS.json`은 세 JSON URI와 SHA-256을 담으며 모든 object의 write/read-back이
끝난 뒤 마지막으로 생성된다. 소비자는 이 marker가 없는 namespace를 FINAL로 읽지
않는다.

Contract에는 `hdfs:///gitjob/analysis_input/...` URI가 기록된다. Producer의
`file://` 경로에 의존하지 않으며 Worker와 C조 실행 위치가 같은 HDFS namespace를
사용하면 WebHDFS로 실제 바이트를 read-back할 수 있다. 최종 세 JSON은 publish 직후
동일 바이트를 다시 읽어 검증한다.

## 3. HDFS small-file 판단

S15P21E102-150의 50 Repo rank-stratified runtime checkpoint를 다시 집계한 결과,
성공 28 Repo에서 Artifact 25개, 총 50,789 bytes가 저장됐다. 시도 Repo 기준으로는
평균 0.5개와 약 1,016 bytes다. 이 관측 비율을 Top 20k에 단순 투영하면 약 10,000개,
약 19.4 MiB다.

정책 상한은 Repo당 24개/1 MiB이므로 이론상 480,000개/20 GiB다. 10,000개의 작은
파일도 HDFS NameNode metadata 관점에서 효율적이지 않지만 Phase 1에서 관측 가능한
범위다. 반면 상한에 가까워지면 파일별 object 구조를 확대하면 안 된다.

이번 Phase 1은 다음 이유로 파일 단위 저장을 유지한다.

- v1 Contract가 Artifact 하나마다 URI, path, hash, size를 전달한다.
- bundle/JSONL/Parquet을 도입하려면 member offset 또는 bundle index라는 새 소비 규약이
  필요하며 현재 C조 Contract에는 없다.
- 예상 10,000개는 실제 Top 20k 결과로 확인할 수 있다.

Top 20k 완료 후 실제 Artifact count/bytes와 NameNode 영향을 다시 측정한다. 결과가
예상보다 크면 Top 50k 전에 Repo 단위 bundle과 index를 별도 Contract/Jira로 합의한다.
현재 작업에서 C조 입력 규약을 임의로 바꾸지 않는다.

## 4. Candidate와 실행

`Infra/spark/repo_fetch_candidates.py`는 기존 stratified canary mode를 유지하면서
`top-n` mode를 제공한다. Top-N mode는 rank 1부터 N까지 정확히 한 번씩 존재하지
않으면 실패한다. Bootstrap CLI도 입력 개수와 연속 rank를 다시 검증한다.

```bash
REPO_FETCH_CANDIDATE_MODE=top-n \
REPO_FETCH_PHASE_TOP_N=20000 \
PROFILES=data \
./Infra/scripts/spark-repo-fetch-candidates.sh
```

Snapshot ID와 pipeline run ID는 resume 동안 바꾸지 않는다. PAT는 env file에서 Worker
환경으로만 전달하며 CLI 인자, 로그, checkpoint에 값을 쓰지 않는다.

```bash
REPO_SNAPSHOT_ID=s15p21e102-114-phase1-20260904 \
REPO_PIPELINE_RUN_ID=s15p21e102-114-run-001 \
REPO_FETCH_PHASE_TOP_N=20000 \
PROFILES=data \
./Infra/scripts/repo-snapshot-bootstrap.sh
```

실행 스크립트는 host의 `.local/repo-snapshot-bootstrap`을 one-off Worker container의
`/var/lib/gitjob/repo-bootstrap`에 bind mount한다. Candidate, checkpoint,
cross-snapshot COMPLETE cache, 진행 상태와 local 최종본은 one-off container 종료나
재시작 뒤에도 남는다. 일반 `worker` 서비스에는 volume이나 startup dependency를
추가하지 않는다. 같은 환경변수로 스크립트를 다시 실행하면 terminal Repo는 건너뛰고
마지막 non-terminal Repo부터 다시 처리한다.

## 5. 상태, 진행률과 publish 규칙

Repo 처리마다 `state.json`에 다음을 갱신한다.

- terminal/total/remaining/percent
- status count
- throughput과 active-time ETA
- 마지막 Repo rank/status/API request count
- 최신 Core remaining/reset

Rate Limit 응답 또는 safety threshold 도달 시 reset까지 대기한 뒤 재개한다. 누적
`rate_limit_wait_seconds`는 `active_runtime_seconds`와 분리한다. checkpoint의 Repo
API/Core/raw 요청 수와 HTTP status는 retry cycle 전체에 걸쳐 누적하므로 실제 요청량을
잃지 않는다.

기본 S15P21E102-104 비교 기준은 Top 20k Core 50,345회와 active runtime 10시간이다.
최종 `run-summary.json`은 실제 Core 요청, active/wait/wall runtime과 추정 대비 차이를
기록한다.

`API_CALL_BUDGET`, `RUNTIME_BUDGET`, 알 수 없는 reset 또는 비정상적으로 긴 wait로
중단되면 checkpoint/상태/실패 보고서만 갱신한다. 불완전한 `snapshot.json`은 local과
HDFS 모두 publish하지 않는다. 모든 후보가 terminal일 때만 다음을 publish한다.

- Contract validation을 통과한 `snapshot.json`
- 실패 Repo(`FAILED`, `NOT_FOUND`)의 `failures.json`
- 요청량/runtime/rate-limit 집계 `run-summary.json`

## 6. 검증 범위

Unit Test는 실제 네트워크 없이 다음을 검증한다.

- WebHDFS immutable create/rename/read와 동일 object replay
- 다른 content overwrite 거부
- Rate Limit wait 후 같은 checkpoint를 이용한 cycle resume
- active runtime과 wait time 분리
- incomplete cycle의 FINAL publish 금지
- WebHDFS final JSON read-back
- 기존 GH Archive WebHDFS sink 회귀
- retry 전후 checkpoint 요청량 누적

관련 WebHDFS/GH Archive/Repo Fetch/Bootstrap/Contract 테스트는 119개가 모두
통과했다. 전체 `AI/tests`는 227 passed, 1 failed였고, 유일한 실패는
`technology-registry-v1.schema.json`의 CRLF와 모델 생성 결과 LF 차이다. 깨끗한
`origin/develop` 사본에서도 같은 테스트가 같은 이유로 실패하므로 이번 변경의
regression이 아니다. 변경 Python 파일은 Ruff check/format을 모두 통과했다. 전체
Ruff check의 I001 10건과 format check의 `AI/llm/test_server.py` 1건은 기존 파일의
baseline이며, `origin/develop`에는 I001 11건과 동일 format failure가 존재한다.

### data-node Runtime canary

2026-09-04에 배포 서비스를 재기동하거나 Compose를 적용하지 않고, 현재 변경 소스를
read-only bind한 one-off Worker에서 공개 Repo 1개를 실행했다.

| 항목 | 실측 결과 |
|---|---:|
| Snapshot | `s15p21e102-114-canary-20260904-01` |
| Repo / 상태 | 1 / `COMPLETE` |
| Artifact | 5개, 9,828 bytes |
| 실제 Repo 요청 | 8회(Core 3, raw 5) |
| active runtime | 3.538초 |
| Rate Limit wait | 0초(발생하지 않음) |
| Core 상태 | limit 5,000 / remaining 4,997 / used 3 / reset 기록 |
| 실패 Repo | 0 |

Artifact 5개와 최종 Snapshot/summary/failures 3개는 canonical WebHDFS namespace에
저장됐다. 실행 중인 기존 `worker` container에서 각 Artifact를 다시 읽어 Contract의
SHA-256과 비교했고 모두 일치했다. `_SUCCESS.json`에 기록된 최종 JSON 세 개의
SHA-256도 모두 일치했다. Snapshot은 `github-repo-snapshot/v1` Pydantic validation을
통과했고 진행 상태에는 100%, COMPLETE 1, throughput 0.283 repo/s, ETA 0초가 기록됐다.

동일 checkpoint를 재실행했을 때 cycle/control 요청만 1회 증가했고 Repo attempts 1,
Repo API 8/Core 3/raw 5는 변하지 않았다. 즉 terminal Repo 재수집은 0건이었다.

같은 shared cache를 사용해 새 Snapshot
`s15p21e102-114-canary-20260904-02`를 실행한 결과 metadata/HEAD Core 2회, raw 0회로
`REUSED`가 생성됐다. `reused_from_snapshot_id`와 첫 Snapshot의 Artifact URI 5개가
유지됐다.

수정 Compose는 서버에 적용하지 않고 `/tmp` 사본에 대해 `config --quiet`으로
검증했다. 일반 `data` profile의 기존 서비스 목록은 변하지 않고 별도 `tools` profile의
`repo-snapshot-bootstrap`만 추가된다. 이 one-off 서비스에서 token 존재 여부(값은
출력하지 않음)와 WebHDFS HTTP 200도 확인했다. 기존 6개 data container는 검증 전후
계속 healthy였으며 재기동하지 않았다.

같은 data-node에서 GitHub API 수집 없이 Spark candidate job만 one-off로 실행했다.
Repo Activity Snapshot으로부터 20,000개, 3,397,784-byte
`repo-fetch-candidates/v1` JSON을 생성했고 rank 1~20,000 연속성, rank 중복 없음,
`repo_id` 20,000개 고유성을 확인했다. 이는 Top 20k 입력 준비 검증이며 Top 20k Repo
Fetch를 실행한 것은 아니다.

## 7. 남은 확인

- Top 20k 전체 GitHub 수집은 이번 MR에서 실행하지 않았다. 코드/MR 병합과 production
  image 배포 후 고정 candidate/snapshot ID로 별도 장기 batch를 실행하는 편이 안전하다.
- C조의 의미 분석 consumer는 아직 develop에 없으므로 이번 검증은 C조 Worker 위치에서
  WebHDFS URI의 bytes를 읽을 수 있는 수준까지다.
- Top 20k 실제 small-file count와 HDFS logical/disk usage는 완료 후 다시 측정한다.
- private Repository와 권한별 404 구분은 이 Phase 1 공개 Repo 범위에서 검증하지 않는다.
- 실제 primary Rate Limit 도달은 의도적으로 유발하지 않았다. reset wait/resume와
  active/wait 분리는 fake clock unit test로 검증했고, runtime에서는 remaining/reset
  기록만 확인했다.
