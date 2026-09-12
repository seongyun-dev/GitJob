# Monthly Artifact Fetch 품질 보강

> Jira: S15P21E102-198
>
> 상태: 구현 및 2026-07 Top100/Top1,000 Runtime Canary 검증 완료
>
> 기준 branch: `fix/S15P21E102-198-artifact-fetch-quality`

## 범위

이번 변경은 전체 Monthly Top10k를 재실행하지 않고, 월별 Artifact Fetch가 활동
기간과 같은 Commit을 우선 분석하고 선언 파일을 더 결정적으로 선택하도록 보강한다.
기존 HDFS Raw, immutable Snapshot, -194 chain, Top50k partial 결과는 수정하지 않는다.

## Commit 선택 lineage

Repo Activity Spark 출력의 `monthly_event_sha`는 해당 기간 마지막 유효
`PushEvent.payload.head`(UTC `created_at` 기준, 같은 시각이면 SHA 정렬 tie-break)다.
Orchestrator는 이 SHA의 Commit API와 root tree를 먼저 조회한다.

| `sha_source` | 선택 기준 | 월별 Trend 입력 |
|---|---|---|
| `MONTH_EVENT_SHA` | 월별 PushEvent SHA의 Commit/tree 확인 성공 | 포함 |
| `HISTORICAL_HEAD_UNAVAILABLE` | 월 SHA 누락 또는 해당 Commit/tree 조회 불가 | 제외 가능 |
| `CURRENT_DEFAULT_HEAD` | historical 전용 모드가 아닌 기존 실행의 호환 경로 | 월별 실행에서 사용 금지 |

`selected_commit_sha`와 `pinned_commit_sha`는 동일한 선택 Commit이고,
`tree_sha`는 그 Commit object의 실제 Git tree SHA다. 기존
`github-repo-snapshot/v1` 소비자를 깨지 않도록 lineage 필드는 optional 확장이다.
월별 실행은 `REPO_REQUIRE_HISTORICAL_HEAD=1`을 명시한다. 이 모드에서는 월 SHA나
해당 Commit/tree를 얻지 못해도 현재 default branch HEAD를 조회하지 않는다. 대신
checkpoint에 `HISTORICAL_HEAD_UNAVAILABLE`과 실패 이유를 남기고 Snapshot record에서는
제외한다. Cache fingerprint에도 historical-head-required 모드와 manifest selection
policy version이 포함되어 이전 fallback 결과를 잘못 재사용하지 않는다.

## Manifest priority

현재 C 분석 `ManifestScanner`가 실제로 읽는 형식만 selector에 추가했다.

- root manifest를 먼저 선택한다.
- 실제 module/workspace의 manifest를 다음 순서로 선택한다.
- `requirements-dev.txt`, `requirements/*.txt`, `gradle/libs.versions.toml`,
  `*.csproj`를 지원한다.
- `examples`, `samples`, `tests`, `generated`, `fixtures` 경로는 후순위다.
- `vendor`, `build`, `node_modules` 등 기존 제외 경로는 계속 제외한다.
- `Pipfile`, `environment.yml`, `build.sbt`, `Package.swift`는 현재 C scanner
  지원이 확인되지 않아 이번 selector에 추가하지 않는다.
- `Dockerfile`, Compose 파일, `.github/workflows/*.yml|yaml`, `Jenkinsfile`을
  제한적으로 추가한다.
- Kubernetes는 `k8s`, `kubernetes`, `manifests`, `deploy`, `deployment` 디렉터리의
  conventional basename만 선택한다. 일반 YAML은 Kubernetes로 간주하지 않는다.

파일 제한에 걸리면 checkpoint/run-summary의 각 Repo row에
`selection_metrics`를 남긴다.

```json
{
  "manifest_candidate_count": 8,
  "manifest_selected_count": 3,
  "manifest_excluded_count": 5,
  "manifest_excluded_reasons": ["FILE_LIMIT_REACHED"]
}
```

## Recursive tree metadata

이미 조회한 recursive tree에서 다음 12개 언어의 파일 수와 정렬된 대표 path 최대
3개를 `language_metadata`로 보존한다. source 원문은 추가 저장하지 않는다.

`C`, `C++`, `C#`, `Go`, `Python`, `Java`, `Kotlin`, `JavaScript`, `TypeScript`,
`HTML`, `CSS`, `SQL`

## Runtime Canary

두 Canary는 각각 새 immutable Snapshot을 사용했으며 기존 Snapshot을 overwrite하지
않았다. Data Server의 checkpoint/state/HDFS를 2026-09-12에 다시 읽어 검증했다.

| 항목 | Top100 fix-004e | Top1,000 fix-004e |
|---|---:|---:|
| terminal | 100/100 | 1,000/1,000 |
| COMPLETE | 70 | 629 |
| PARTIAL | 8 | 58 |
| NOT_FOUND | 18 | 291 |
| FAILED | 2 | 5 |
| HISTORICAL_HEAD_UNAVAILABLE | 2 | 17 |
| Snapshot records / MONTH_EVENT_SHA | 78 | 687 |
| current default HEAD fallback | 0 | 0 |
| Artifact | 163 | 1,630 |
| Artifact 보유 Repo | 27 | 259 |
| language metadata Repo | 37 | 344 |
| API requests | 418 | 4,027 |
| rate-limit wait | 0 | 0 |
| active runtime | 214.32초 | 2,493.00초 |

Top1,000 candidate는 1,000건, rank 1..1,000, duplicate/null repo_id 0이며 SHA-256은
`d9c65a25c0d99bb05054ba0f43c7e228afca0cc7b8818535059635d5010c9a90`이다.
992건에 `monthly_event_sha`가 있었고, 그중 687건이 Commit/tree 확인을 마쳐 Snapshot에
포함됐다. 누락 또는 조회 불가 17건은 별도 상태로 남았으며 default HEAD fallback은
없었다.

Top1,000 언어 metadata 실측은 다음과 같다. Repo 수는 해당 언어가 관측된 Snapshot
record 수이고 파일 수는 recursive tree에서 집계된 합계다.

| 언어 | Repo | 파일 |
|---|---:|---:|
| C | 11 | 1,000 |
| C++ | 9 | 10,946 |
| C# | 4 | 73 |
| Go | 13 | 1,342 |
| Python | 180 | 61,733 |
| Java | 13 | 22,100 |
| Kotlin | 5 | 650 |
| JavaScript | 161 | 59,766 |
| TypeScript | 48 | 127,766 |
| HTML | 246 | 31,621 |
| CSS | 94 | 17,551 |
| SQL | 24 | 1,483 |

Top1,000에서 수집된 DevOps Artifact는 Dockerfile 52, Compose 14, GitHub Actions
907건이다. conventional 조건을 만족한 Kubernetes와 Jenkins Artifact는 이 표본에서
0건이었다. 0건은 일반 YAML을 Kubernetes로 넓혀 해석하지 않은 결과다.

HDFS Snapshot은 다음 경로에 게시됐다.

- `hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=s15p21e102-198-202607-top100-canary-20260911-fix-004e`
- `hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=s15p21e102-198-202607-top1000-canary-20260911-fix-004e`

두 경로 모두 `_SUCCESS.json`이 존재한다. Top1,000의 `snapshot.json`,
`run-summary.json`, `failures.json`은 `_SUCCESS.json`에 기록된 SHA-256과 HDFS
read-back SHA-256이 모두 일치했다.

## 검증과 비범위

회귀 테스트는 월별 SHA 성공, historical fallback 금지, cache reuse, tree lineage,
root/module manifest priority, 12개 언어 metadata, DevOps conventional path와 일반 YAML
제외를 다룬다. 관련 pytest 103개, Ruff check/format, JSON Schema parse, shell syntax가
통과했다.

전체 월별 Top10k 실행, C의 Technology Registry/Evidence 판정, 기존 Snapshot overwrite,
-194 chain restart는 이번 품질 보강 범위가 아니다.
