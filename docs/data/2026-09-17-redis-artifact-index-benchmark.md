# Weekly Artifact Redis Index 성능 벤치마크

- Jira: `S15P21E102-293` (설계·구현 `S15P21E102-288`, 계측 baseline `S15P21E102-275`, Before canary `S15P21E102-283`)
- 측정일: 2026-09-17
- 담당: 안성윤

## 1. 목적

Weekly Artifact Resolver에 Redis artifact index를 도입했을 때 **처리시간·GitHub API 호출·artifact 쓰기**가
얼마나 줄어드는지를, 동일 입력·동일 실행환경에서 재현 가능한 형태로 측정한다.

`RedisArtifactIndex`는 durable artifact 저장소의 **인덱스**이지 저장소 자체가 아니다
(`AI/github/redis_artifact_index.py` 클래스 docstring: *"Index durable artifact references without
becoming their source of truth."*). 따라서 이 벤치마크가 측정하는 것은 "Redis 서버의 속도"가 아니라
**이미 durable하게 존재하는 artifact를 GitHub 재수집 없이 되쓰는 경로의 효과**다.

## 2. run 정의

| ID | run | pipeline_run_id | 성격 |
|---|---|---|---|
| **A** | Before cold | `s15p21e102-283-weekly-canary-20260916` | Redis 도입 전 공식 baseline. 2026-09-16 측정 |
| **B** | publish warm | `s15p21e102-283-weekly-publish-20260916` | 로컬 캐시 warm·Redis 없음. **공식 control 아님** (§10) |
| **W** | warm-up control | `s15p21e102-293-redis-warmup-20260917` | Redis ON이지만 namespace가 비어 hit 0. **공식 비교 기준** |
| **C** | Redis measured | `s15p21e102-293-redis-measured-20260917` | Redis namespace warm. 측정 대상 |

W와 C는 한 쌍이다. W가 artifact root와 Redis index를 채우고(비교에서 제외), C가 그 warm 상태에서 측정한다.

## 3. 고정 입력과 dataset identity

```
week_start        2026-03-02   (period 2026-03-02 ~ 2026-03-08, candidate week_start에서 파생)
candidate count   1500         rank 1 → 1500 오름차순
candidate sha256  8de70ed2dec7e74dff6e4823677d8e9bbdff396223a318364b5ac9654bb73c0e
schema_version    repo-activity-weekly-candidates/v1
정책              pool 1500 / valid quota 100 / batch 1
collection_policy max_api_calls 60000, max_artifact_bytes 1048576, max_artifact_files 24,
                  max_tree_entries 100000, max_runtime_seconds 86400, top_n_limit 1500,
                  policy_version repo-fetch-policy/v1
collector         gitjob-repo-fetch-orchestrator/v2
```

네 run 모두 **바이트 단위로 같은 candidate 파일**을 입력으로 썼다. A/W/C 실행 전후로 SHA를 재확인했고 변하지 않았다.

| ID | dataset_snapshot_id |
|---|---|
| A | `s15p21e102-weekly-20260302-20260913-v2` |
| B | `s15p21e102-weekly-20260302-20260913-v2` |
| W | `s15p21e102-293-redis-warmup-20260917` |
| C | `s15p21e102-293-redis-measured-20260917` |

## 4. 실행환경

```
호스트        data host (Historical 2026-03 chain과 동거. benchmark는 별도 one-shot 컨테이너)
image        gitjob/worker:redis-bench-21796de   Id 65769b0fb0ed
             Created 2026-09-17T02:56:48Z, develop 21796de(clean)에서 빌드
             포함: -288(3f8332e) / -275(4dd7457) / -293(c894d4f)
실행         docker compose run --rm --no-deps -T  (worker 서비스는 profiles 로 묶여 있어
             기동 중인 Production 서비스를 건드리지 않는다. WORKER_IMAGE 오버라이드로 :local 미변경)
credential   GITHUB_API_TOKEN_WEEKLY → 컨테이너 GITHUB_TOKEN
             authenticated user songmin2 (id 180504442)
             Historical의 GITHUB_API_TOKEN은 guitarmaster01247 (id 281841021)
             → 서로 다른 GitHub user id 이므로 primary rate-limit pool 분리
artifact     --artifact-store file  --artifact-root /work/artifacts
             materialization_context = file:///work/artifacts   (W·C 공유)
             호스트 .local/weekly-redis-bench/artifacts, policy=a8d0e97f72ee0978
Redis        7.4.0,  WEEKLY_REDIS_DB=3
             namespace gitjob:benchmark:weekly:artifact-index:s15p21e102-293-20260917
             TTL 2592000s (30일)
             key = <ns>:repo={repo_id}:sha={pinned_commit_sha}
                       :policy=sha256(cache_policy_version)[:16]
                       :context=sha256(materialization_context)[:16]
             실측 policy=a8d0e97f72ee0978  context=57a3fef015667462
```

**artifact root를 W와 C가 공유해야 하는 이유**는 두 가지이며 각각 단독으로 치명적이다.

1. Redis key에 `context = sha256(materialization_context)[:16]`이 들어가고
   `FileArtifactStore.materialization_context = root.as_uri()`이다. root가 다르면 key가 달라져 100% miss다.
2. `lookup()`은 `all(artifact_store.validate_artifact(a) for a in artifacts)`를 통과해야 hit을 반환한다.
   `validate_artifact`는 대상 파일을 **다시 읽어 size와 sha256을 대조**한다. 다른 root에는 파일이 없으므로
   전부 `durable_fallback`으로 떨어져 GitHub 재수집으로 회귀한다.

반대로 **local cache는 반드시 분리**해야 한다. 조회 순서가
`self.cache.get(...)` → `redis_index.lookup(...)` → GitHub이므로, cache를 물려주면 1단계에서 전부 hit되어
Redis가 한 번도 호출되지 않는다. C는 cache 파일이 없는 상태에서 시작했다.

| 경로 | W | C |
|---|---|---|
| artifact root | `/work/artifacts` | **동일** |
| Redis namespace | 동일 (시작 시 비어 있음) | 동일 (warm) |
| cache | `/work/warmup/weekly-cache.json` | `/work/measured/weekly-cache.json` (시작 시 부재) |
| checkpoint / state / summary / failures | `/work/warmup/*` | `/work/measured/*` |

## 5. validity gates

C 실행 결과에 대해 전부 PASS.

| gate | 결과 |
|---|---|
| `durable_hit == 0` | PASS (0) — local cache 누수 없음 |
| `reused_artifact_count == redis_hit_count − redis_durable_fallback_count` | PASS (70 == 70 − 0) |
| `sum(status_counts) == candidates_examined` | PASS (346 == 346) |
| `wall_runtime_seconds − rate_limit_wait_seconds == active_runtime_seconds` | PASS |
| candidate sha256 동일 | PASS (`8de70ed2…4bb73c0e`) |
| candidate ordering rank 1 → 1500 | PASS |
| Before evidence sha256 무변경 | PASS (`b0fe7ea8…a04c4`) |
| Production Redis namespace 무변경 | PASS (db0~db4에서 `gitjob:weekly:artifact-index:*` 0건) |

## 6. raw metrics

| run | examined | valid | wall(s) | active(s) | rl_wait(s) | API total | core | raw | artifact writes |
|---|---|---|---|---|---|---|---|---|---|
| A | 353 | 100 | 1395.5038163207937 | 1119.6355182670522 | 275.868298 | 2972 | 1311 | 1661 | 506 |
| B | 346 | 100 | 868.45 | 868.45 | 0 | 2378 | 1125 | 1253 | 107 |
| W | 353 | 100 | 1125.41 | 1125.41 | 0 | 2971 | 1307 | 1664 | 506 |
| C | 346 | 100 | 937.35 | 937.35 | 0 | 2461 | 1211 | 1250 | 100 |

disposition:

| run | COMPLETE | PARTIAL | NOT_FOUND | FAILED | REUSED |
|---|---|---|---|---|---|
| A | 234 | 57 | 45 | 17 | 0 |
| B | 78 | 56 | 44 | 16 | 152 |
| W | 234 | 57 | 45 | 17 | 0 |
| C | 160 | 56 | 44 | 16 | 70 |

**W의 disposition 4항목이 A와 완전히 일치한다.** 같은 candidate·ordering·policy가 재현됐다는 근거다.

Redis / durable 계측 (C):

| 지표 | 값 |
|---|---|
| `redis_lookup_count` | 290 |
| `redis_hit_count` | 70 |
| `redis_miss_count` | 220 |
| `redis_hit_rate` | 0.241379 |
| `redis_durable_validation_count` | 70 |
| `redis_durable_fallback_count` | 0 |
| `redis_error_count` / `redis_fail_open_count` | 0 / 0 |
| `redis_lookup_latency_p50_ms` / `p95_ms` | 0.737 / 12.051 |
| `durable_lookup_count` / `durable_hit` / `durable_miss` | 290 / 0 / 290 |
| `durable_lookup_latency_p50_ms` / `p95_ms` | 0.010 / 0.013 |

W의 Redis 계측은 `lookup 296 / hit 0 / miss 296`으로, namespace가 비어 있어 의도대로 cold pass였다.

## 7. RPS 재계산

저장된 `repos_per_second` 필드는 **비교에 쓰지 않는다.** `summary()`가 `**_baseline_metrics()`를
마지막에 전개해 기존 키를 덮어쓰므로, 계측 도입 이전 run(A)은 wall 기준이고 이후 run은 active 기준이다.
같은 이름에 다른 기준이 담겨 그대로 비교하면 틀린다.

```
wall_rps   = candidates_examined / wall_runtime_seconds
active_rps = candidates_examined / active_runtime_seconds
```

| run | wall_rps | active_rps |
|---|---|---|
| A | 0.252955 | 0.315281 |
| B | 0.398409 | 0.398409 |
| W | 0.313664 | 0.313664 |
| C | **0.369127** | **0.369127** |

## 8. 공식 비교 — W → C

| 지표 | W | C | 변화 |
|---|---|---|---|
| wall runtime | 1125.41s | 937.35s | **−16.71%** (speedup **1.2006x**) |
| active runtime | 1125.41s | 937.35s | **−16.71%** (speedup **1.2006x**) |
| GitHub API total | 2971 | 2461 | **−17.17%** |
| core calls | 1307 | 1211 | −7.35% |
| raw calls | 1664 | 1250 | −24.88% |
| artifact writes | 506 | 100 | **−80.24%** |
| examined당 active time | 3.1881 s/repo | 2.7091 s/repo | −15.03% |
| examined당 API | 8.4164 | 7.1127 | −15.49% |
| examined당 artifact writes | 1.4334 | 0.2890 | −79.84% |
| valid artifact | 100 | 100 | 동일 |

`examined`가 353 → 346으로 달라진 것은 실패가 아니다. REUSED가 valid quota에 산입되므로
quota 100 도달 시점(rank)이 달라진다. 따라서 총량과 함께 **examined당 정규화 지표**를 같이 본다.
정규화 후에도 개선이 유지된다.

## 9. A → C를 공식 비교로 쓰지 않는 이유

A → C의 wall 개선은 −32.83%(1.4888x)로 계산되지만 **이 수치를 Redis 성능으로 제시하면 안 된다.**

A의 wall 1395.50s에는 GitHub **secondary rate limit(HTTP 429) 대기 275.868298s**가 통째로 들어 있다
(`rate_limit_wait_count = 1`, 당시 core remaining 4904/5000이었으므로 primary 고갈이 아니다).
W와 C에는 이 대기가 없었다. 즉 32.83% 중 상당 부분은 Redis가 아니라 **429를 만나지 않은 운(運)**이다.

active 기준으로 보면 A → C는 −16.28%(1.1945x)로 W → C의 −16.71%와 사실상 같다.
그럼에도 공식 기준을 W로 두는 이유는, W가 A와 달리 **같은 날·같은 호스트·같은 고정 이미지·같은 token·
같은 file artifact store**에서 실행되어 Redis 외 변수가 최소화됐기 때문이다.

## 10. B를 control로 쓰지 않는 이유

B(publish warm)는 artifact URI가 **hdfs 1,253건 + file 399건 혼합**이다.
A·W·C는 전부 100% `file://`이다. 즉 B는 저장 백엔드 자체가 다르고, WebHDFS 네트워크 쓰기가 섞여 있어
I/O 비용 구조가 다르다. 또한 B는 계측 도입 이전 이미지로 실행되어 `redis_*`·`durable_*` 필드가 없다.

B의 REUSED 152는 Redis가 아니라 **로컬 JSON 캐시**에서 나왔다. 이 값이 C의 70보다 큰 것은
Redis 인덱스 커버리지가 로컬 캐시보다 좁기 때문이다(§11). 두 수치는 같은 축의 값이 아니므로
"로컬 캐시가 Redis보다 낫다" 또는 그 반대의 결론을 여기서 끌어낼 수 없다.

## 11. Redis hit / REUSED / fallback semantics

`redis_hit_count`와 `reused_artifact_count`는 **다른 것을 센다.** `lookup()` 내부 단계가 각기 다른 카운터에 기록된다.

| 의미 | 필드 |
|---|---|
| index 조회 시도 (`sha_source == CURRENT_DEFAULT_HEAD`인 경우만) | `redis_lookup_count` |
| payload 발견 + 형식/identity 일치 | `redis_hit_count` |
| durable 재검증 시도 (artifact 재read + sha256) | `redis_durable_validation_count` |
| 재검증 실패 → GitHub 회귀 | `redis_durable_fallback_count` |
| Redis 오류 → fail-open (miss로 처리) | `redis_error_count` / `redis_fail_open_count` |
| **실제 artifact 재사용** | `reused_artifact_count` (status `REUSED`) |

실제 재사용으로 이어진 수는 `redis_hit_count − redis_durable_fallback_count`다.
이번 측정은 fallback 0이라 70 = 70이지만, 일반적으로 두 값은 같지 않다.

**인덱싱 커버리지**: `put()`은 `collection_status is COMPLETE` **and** `artifacts` 비어있지 않음
**and** `sha_source == CURRENT_DEFAULT_HEAD`일 때만 동작한다. 즉 PARTIAL·NOT_FOUND·FAILED와
artifact가 없는 COMPLETE는 인덱싱되지 않는다. W에서 COMPLETE 234 중 `empty_artifact_count` 134를 뺀
**100건**이 인덱싱됐고, 실제 Redis db3 키 수도 정확히 100이었다.

**latency 해석 주의**: `redis_lookup_latency_*`는 순수 Redis RTT가 아니다.
`lookup()`의 `finally: record_latency(...)`가 durable 재검증까지 감싼다.
따라서 p95 12.051ms는 hit 시의 artifact 재read + sha256 비용을 포함하고,
p50 0.737ms는 검증 전에 반환되는 miss 220건이 지배한다.

## 12. attribution limitation

- **재사용 경로의 귀속은 명확하다.** C의 `durable_hit = 0`이므로 REUSED 70건은 전부 Redis 인덱스를 통해
  발생했고 로컬 캐시 기여는 0이다.
- **그러나 runtime 개선 전체를 "Redis 서버 단독 효과"로 표현하면 안 된다.** 모든 Redis hit은
  공유 artifact root에서의 durable 재검증을 통과해야 성립한다(validation 70 / fallback 0).
  artifact root가 비어 있었다면 70건 전부 fallback해 GitHub 재수집으로 돌아갔을 것이다.
- 정확한 표현은 **"Redis index + warm durable artifact root의 결합 효과"**다.

## 13. presentation-safe claim

> 동일 입력과 동일 실행환경에서 Redis 인덱스 미적중 기준 실행과 비교했을 때,
> Redis 기반 artifact 재사용 경로를 적용한 실행에서 처리시간을 약 16.7% 단축했고,
> GitHub API 호출을 약 17.2%, artifact 쓰기를 약 80.2% 줄였다.
> 70건의 artifact 재사용은 전부 Redis 인덱스 경로에서 발생했으며
> valid artifact 100건이라는 결과 품질은 동일하게 유지됐다.

## 14. 발표에서 금지할 표현

| 금지 | 이유 |
|---|---|
| "Redis로 32.8% 빨라졌다" | A의 wall에 포함된 429 대기 275.87s가 W·C에 없었을 뿐. 확률적 요인 |
| "Redis 조회 지연 p95 12ms" | 이 값은 durable 재검증(artifact 재read + sha256) 비용을 포함. 순수 RTT 아님 |
| "Redis가 로컬 캐시보다 빠르다/느리다" | B는 저장 백엔드가 달라 비교 불가. 커버리지 정의도 다름 |
| "Redis 서버 도입만으로 개선됐다" | warm durable artifact root가 없으면 재사용 0건 |
| "평균 16.7% 개선된다" / 신뢰구간 제시 | 각 조건 1회 실행(n=1). 일반화 근거 없음 |

## 15. n=1 limitation

A·B·W·C 각각 **1회씩만** 실행했다. 반복 측정이 없으므로 분산·신뢰구간·통계적 유의성을 주장할 수 없다.
네트워크 지연, GitHub 응답 시간, 호스트 부하(측정 중 Historical 2026-03 chain이 동시 실행 중이었다)가
결과에 섞여 있다. 수치는 **단일 관측**으로 읽어야 하며, 발표 시 "약 15~17%" 수준의 범위 표현이 안전하다.

## 16. evidence 파일과 SHA

**A — Before (immutable reference, dir `dr-xr-xr-x`, 파일 `-r--r--r--`)**
`.local/benchmark-evidence/redis-before-20260916/`

| 파일 | sha256 |
|---|---|
| `MANIFEST.json` | `f9a0988d28408d94d1127e7d27f7cd926e7881b69b4f1c993f43d4b3666f42ff` |
| `weekly-candidates-2026-03-02.json` | `8de70ed2dec7e74dff6e4823677d8e9bbdff396223a318364b5ac9654bb73c0e` |
| `weekly-run-summary.json` | `b0fe7ea87f7a663ad97633b5ee3c4727a0f4db442b2103fc02a28cc1f90a04c4` |
| `weekly-state.json` | `de1665629adbe3f8044aa415fbfa50a2b2e16a6e717c1d13d2b496a1811844a0` |
| `weekly-snapshot.json` | `14d36d731e2a91459011c7ce188af234994aa0ec901f5dd16fd3092c4f979551` |
| `weekly-failures.json` | `35efd958c956ff25131d15cdd43ed5f00f3d2f13c2ef2ac7f8d9be8eabb007f1` |

**W — warm-up** `.local/weekly-redis-bench/warmup/`

| 파일 | sha256 |
|---|---|
| `weekly-run-summary.json` | `0393a21fb12418601a35b3d4147baebee0a5c99876d30e0f990107a8a6d5d02e` |
| `weekly-state.json` | `bd91a39628aa3e9cdbba48710b9630890a6304e025a239d2f179554a65c2f732` |
| `weekly-snapshot.json` | `0d773e5445853fbabedd65c8b3bc66de06fb566eec457a51363040fea108bd96` |
| `weekly-failures.json` | `aae4f3924949d49f6f97690db6371d889b16f635a7d813481328d6a52d709866` |

**C — measured** `.local/weekly-redis-bench/measured/`

| 파일 | sha256 |
|---|---|
| `weekly-run-summary.json` | `5c04d0672add57ed3a275c8e188ef3564eeb8383eba70d3df8b6470d3c9cc50e` |
| `weekly-state.json` | `3d1cf625c1ae84962b4866c0fddaf542b37f413fc3035388c0f484686537ba45` |
| `weekly-snapshot.json` | `e6730d57df762a951d9a51d412cca0765cdb9a4e5df5d1582e4e2ce64de5ecdc` |
| `weekly-failures.json` | `5c9448baa4f2fee415d55fb34c23584479ad385bbb7c375e1d48bce770597bf8` |

**공통 입력** `.local/weekly-redis-bench/candidates/weekly-candidates-2026-03-02.json`
→ `8de70ed2dec7e74dff6e4823677d8e9bbdff396223a318364b5ac9654bb73c0e` (A 원본과 동일)

**공유 artifact root** `.local/weekly-redis-bench/artifacts/policy=a8d0e97f72ee0978`
→ W·C 종료 시점 2,260 파일 / 11,672,323 B

> A의 evidence 디렉터리만 읽기 전용으로 고정되어 있다. W·C 출력은 아직 가변 경로에 있으므로,
> 장기 보존이 필요하면 같은 방식으로 `.local/benchmark-evidence/` 아래에 복사하고 SHA를 대조할 것.
> 위 SHA는 그 복사본의 무결성 검증 기준으로 그대로 쓸 수 있다.

## 17. 재현 절차

1. candidate SHA를 fail-closed로 검사한다. 불일치면 중단한다.
2. 이동 표적인 `gitjob/worker:local`을 커밋 기준 태그로 고정한다 (`gitjob/worker:redis-bench-<sha>`).
3. benchmark 전용 디렉터리를 만든다. `artifacts/`는 두 phase가 공유하고, `warmup/`·`measured/`는 분리한다.
4. Redis benchmark namespace와 DB가 비어 있는지, Production namespace와 겹치지 않는지 확인한다.
5. Phase A(warm-up) 실행 → artifact root와 Redis index를 채운다. 비교에서 제외한다.
6. `measured/`에 cache 파일이 없는지 확인한 뒤 Phase B(measured)를 실행한다.
7. §5의 validity gate를 전부 통과했는지 확인한다. 하나라도 실패하면 결과를 폐기한다.
8. RPS는 저장 필드를 쓰지 말고 §7 공식으로 재계산한다.
