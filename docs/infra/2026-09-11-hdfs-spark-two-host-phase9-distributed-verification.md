# S15P21E102-207 Phase 9 Spark 분산 처리 검증

- 수행일: 2026-09-11 (UTC 기준 00:47-01:15)
- 대상: 양쪽 EC2의 Spark Worker, HDFS 4 DataNode
- 상태: `PASS` — 완료 조건 7개 모두 충족, Phase 5 재복제 항목도 재검증 완료
- 계획: [HDFS·Spark 2-Host Split Plan](2026-09-10-hdfs-spark-two-host-split-plan.md)
- 이전 단계: [Phase 8 driver·BlockManager 포트 고정](2026-09-11-hdfs-spark-two-host-phase8-driver-port-pinning.md)
- 선행 수정: [DataNode 간 재복제 경로 수정](2026-09-11-hdfs-datanode-hostname-rereplication-fix.md)

## 1. 범위

계획 7절 Phase 9의 세 단계를 순서대로 수행했다. 운영 Raw는 읽기만 했고 모든 출력은
`/gitjob/demo` 아래 별도 경로에 썼다. 기존 운영 Parquet과 그 배치는 바꾸지 않았다.

시작 시점 상태는 다음과 같다.

| 항목 | 결과 |
|---|---|
| Live / Dead DataNode | 4 / 0 |
| fsck `/gitjob` | HEALTHY |
| under / mis-replicated | 0 / 0 |
| Spark alive worker | 2 (`100.70.66.38`, `100.71.215.74`) |
| service core/app | 전부 healthy, `/health` `200` |

## 2. Phase 5 재복제 항목 재검증

Phase 8까지 미해결로 남아 있던 "죽은 DataNode 재복제" 항목을 먼저 재시험했다.
[재복제 경로 수정](2026-09-11-hdfs-datanode-hostname-rereplication-fix.md) 이후
동작이 달라졌을 것으로 보았기 때문이다.

00:48:07 UTC에 DataNode-4를 `docker stop`으로 중지하고 dead 전환(630초)을 기다렸다.
전환 직후 NameNode 집계는 Phase 5와 정반대였다.

```text
Live datanodes (3):
Dead datanodes (1):
Under replicated blocks: 243
Low redundancy blocks with highest priority to recover: 3
```

Phase 5에서는 같은 위치가 모두 0이었다. 이번에는 DataNode-4가 보유한 243개 블록이
전부 재복제 대기열에 올랐고 120초 만에 수렴했다.

| 경과 | under-replicated | data host 여유 |
|---:|---:|---:|
| 20s | 186 | 174 GiB |
| 40s | 141 | 173 GiB |
| 60s | 95 | 173 GiB |
| 80s | 66 | 172 GiB |
| 100s | 26 | 172 GiB |
| 120s | **0** | 172 GiB |

canary 3블록도 살아남은 rack-a 노드 두 곳으로 재복제됐다.

```text
blk_1073763521  Live_repl=2  [/rack-a/100.70.66.38:9866, /rack-a/100.70.66.38:9886]
```

DataNode-4를 다시 올리자 01:02:32에 Live 4로 복귀했고, 30초 안에 rack 교차 배치까지
자동 복원돼 under-replicated와 mis-replicated가 모두 0이 됐다.

```text
blk_1073763521  Live_repl=2  [/rack-a/100.70.66.38:9866, /rack-b/172.18.0.1:9866]
```

즉 **host 하나를 잃어도 HDFS가 스스로 이중화를 회복하고, 복귀 시 교차 배치로
되돌린다.** Phase 5 문서 11절의 "재복제 미검증" 결론은 정정했다. 당시 0으로 관측된
이유는 그 단계의 DataNode-4가 canary 3블록만 보유해 대상이 극소수였고, canary가
정상 동작하던 rack-b → rack-a 방향만 시험했기 때문으로 본다.

## 3. 1단계 — synthetic shuffle canary

HDFS를 쓰지 않고 Spark 네트워크 경계만 분리해 검증하기 위해 도구를 추가했다.

```text
Infra/spark/shuffle_canary.py
Infra/scripts/spark-shuffle-canary.sh
```

`spark.range`로 생성한 20만 행을 `groupBy`로 집계해 실제 exchange를 강제하고, 결과를
정렬 순서로 digest한다. 행 수와 id 합계를 closed-form과 대조해 shuffle이 행을
잃거나 중복시키지 않았음을 산술로 확인한다.

MR 검토 후 canary 자체도 분산 실행을 판정하도록 보강했다. shuffle map stage의 각
입력 partition에서 executor hostname을 태깅하고 group별 `collect_set`에 보존한다.
모든 입력 partition이 모든 group key를 포함하도록 크기를 제한하므로 source host가
2개 이상이면 reducer가 반대 host의 map output을 반드시 가져온다. 기본
`CANARY_MIN_HOSTS=2`이며 한 host만 참여하면 행 수와 합계가 맞아도 실패한다.

```json
{"groups": 64, "partitions": 8, "total_rows": 200000,
 "observed_rows": 200000, "rows_match": true,
 "expected_id_sum": 19999900000, "observed_id_sum": 19999900000, "sum_match": true,
 "source_hosts": ["spark-worker", "spark-worker2"], "source_host_count": 2,
 "min_hosts": 2, "hosts_match": true,
 "content_sha256": "c265a33d82c0ea8b0d4cfe5618dd7197e4a2aec0203bf72c6c8247f62714af8f"}
```

stage 0의 task가 양쪽 host에서 실행됐고(data 7, service 1), executor 로그에 교차
host shuffle fetch가 남았다.

```text
Getting 8 (184.9 KiB) non-empty blocks including 7 (162.0 KiB) local
  and 0 host-local and 0 push-merged-local and 1 (22.9 KiB) remote blocks
```

remote block 1개(22.9 KiB)가 service 호스트 executor에서 Tailscale을 거쳐 data
호스트로 전송된 것이다. 계획의 "shuffle read/write 관측" 조건은 이 줄로 충족한다.

### 도구에서 발견한 결함

첫 실행에서 `groups`가 지정하지 않은 값 `1000`으로 보고됐다. 원인은 wrapper가
`${GROUPS:-64}`를 쓴 것이었다. `GROUPS`는 bash가 호출자의 그룹 ID 배열로 정의하는
내장 변수여서 기본값이 적용되지 않고 primary GID(`id -g` = 1000)가 들어갔다.
`CANARY_GROUPS` 등으로 개명해 수정했다.

```text
8b6c991 [S15P21E102-207] fix: shuffle canary 변수명이 셸 내장 GROUPS 와 충돌
```

## 4. 2단계 — HDFS canary

Phase 5가 만든 `/gitjob/demo/distributed-proof`를 읽었다. 이 경로는 세 블록 모두
`/rack-a`와 `/rack-b`에 replica가 있다.

```json
{"input": "hdfs:///gitjob/demo/distributed-proof", "row_count": 118987,
 "content_sha256": "6fddb16ab44a801054a17157fe955f7f3da5b91a7550be39200b453f2720eea0"}
```

task는 data 2개, service 4개로 분산됐다. service 쪽이 더 많은 것은 해당 블록의
replica가 DataNode-4에도 있어 locality 기반 스케줄링이 작동한 결과다. 교차 host
replica가 읽기 경로에서 실제로 쓰인다는 뜻이다.

## 5. 3단계 — 1일치 GH Archive 실제 job

`dt=2026-03-01` 하루치(24파일, 932 MB)를 입력으로 Repo Activity job을 실행했다.
출력은 운영 경로가 아닌 `/gitjob/demo/phase9` 아래에 썼다.

| 항목 | 결과 |
|---|---|
| 종료 | 정상 (`Successfully stopped SparkContext`), 오류 0 |
| 소요 | 약 2분 |
| 전체 task | 661 |
| **task 분포** | **data 376 / service 285** |
| executor 실패·재시도 | 0 |
| shuffle 단계 | 14 |
| 출력 크기 | 27.0 MB logical / 54.0 MB stored |
| 출력 replication | 2.0, under/mis-replicated 0 |

Phase 8에서 적용한 `spark.hadoop.dfs.replication=2`가 실제 job에서도 그대로
동작해 모든 출력 블록이 두 host에 하나씩 배치됐다.

### 단일 Worker 결과와의 대조

같은 입력을 `SPARK_CORES_MAX=1`로 다시 실행해 단일 executor(data host only,
task 661개 전부 `100.70.66.38`)로 산출한 뒤 내용 digest를 비교했다.

| 실행 | row_count | content_sha256 |
|---|---:|---|
| 2-host 분산 | 853,307 | `36dc95e8…b49b1af7` |
| 단일 Worker | 853,307 | `36dc95e8…b49b1af7` |

두 값이 동일하다. 분산 실행이 결과를 바꾸지 않음을 실제 데이터로 확인했다.

### 내용 digest 판정 정정

MR 검토에서 위 실행에 사용한 초기 digest가 모든 값을 문자열로 바꾸고 구분자로
연결해 타입, null sentinel과 필드 경계를 구분하지 못한다는 결함이 확인됐다. 위
두 hash는 당시 실행 기록으로 유지하지만 서로 다른 일반 Parquet 데이터까지 항상
구분하는 강한 증거로 사용하지 않는다.

후속 구현은 정렬된 Spark schema JSON과 `to_json(struct(...))`로 만든 행 JSON을
각각 길이 prefix와 함께 hash하는 `typed-json-v2` 형식으로 변경했다. 컬럼 타입,
명시적 null, JSON escaping과 필드 경계를 보존하며 row 순서와 Parquet part 파일
배치에는 영향을 받지 않는다. 이후 기준 결과 비교는 같은 digest format끼리만
수행한다.

### MR 검토 반영 후 재검증

2026-09-11 03:16~03:17 KST, 두 Worker가 `ALIVE`이고 active application이 없는
상태에서 검토 반영본(`ce1794f`)을 운영 컨테이너의 임시 경로로 복사해 다시 실행했다.
컨테이너 재생성이나 HDFS 쓰기는 수행하지 않았다.

강화된 shuffle canary는 map stage에 실제 참여한 executor hostname을 수집하며,
최소 두 호스트가 확인되지 않으면 행 수와 합계가 맞아도 실패한다. 재검증 결과는
다음과 같다.

```json
{"groups_match": true, "rows_match": true, "sum_match": true,
 "hosts_match": true, "source_host_count": 2,
 "source_hosts": ["spark-worker", "spark-worker2"], "total_rows": 200000}
```

같은 시간 `/gitjob/demo/distributed-proof`를 새 digest로 읽어 schema와 타입을
포함한 결과가 정상 생성되는 것도 확인했다.

```json
{"digest_format": "typed-json-v2", "row_count": 118987,
 "schema_sha256": "eefaaeba40b9223eef99d5eb6999a7456d7290b754b2e9d78cf1ebb597f362f7",
 "content_sha256": "504e1637f7b5a2ffc50ccc8cb0cb02977b1695140151d2253cf4f950616901f5"}
```

## 6. 완료 조건 대조

| 계획 조건 | 결과 |
|---|---|
| Spark Worker 2개 `ALIVE` | PASS |
| 서로 다른 두 Tailscale IP에서 executor 실행 | PASS |
| 양쪽 executor가 각각 하나 이상의 task 수행 | PASS (376 / 285) |
| shuffle read/write 관측 | PASS (remote block fetch 확인) |
| executor failure/retry 없음 | PASS (0건) |
| 단일 Worker 기준 결과와 checksum 동일 | PASS (`36dc95e8…`) |
| 실행 중 service API, DB, Kafka health 정상 | PASS (`/health` `200`, 컨테이너 ID 불변) |

## 7. 기존 서비스 영향

service 서버 core/app 컨테이너 ID는 작업 전후 동일하고 전부 healthy를 유지했다.
`/health`는 계속 `200`이었다. MemAvailable은 job 실행 중 9 GiB에서 8 GiB로 내려갔고
계획 6절의 최소 4 GiB 기준을 유지했다. Spark Worker-2의 restart count는 0이다.

DataNode-4 중지 구간에도 service 스택은 영향을 받지 않았다. 중지한 것은 DataNode
컨테이너뿐이고 Spark Worker-2는 계속 실행 중이었다.

## 8. 정리와 최종 상태

`phase9-single` 비교용 출력은 삭제했다. `phase9` 출력은 Phase 10 관측과 재현
확인을 위해 남겼다.

| 검증 | 결과 |
|---|---|
| Live / Dead DataNode | 4 / 0 |
| fsck `/gitjob` | HEALTHY |
| under / mis-replicated | 0 / 0 |
| missing / corrupt | 0 / 0 |
| data host 여유 | 175 GiB (44% 사용) |

## 9. 남은 항목과 다음 Phase

- 계획은 1일치 이후 1개월 입력으로 확대하도록 한다. 6개월 전체는 별도 승인 대상이다
- `ts-input`이 tailnet 전체를 허용하는 범위 문제(Phase 8 2절)는 미결정이다
- Phase 3의 Saramin `.uploading-*` 임시 파일 2개는 그대로 남아 있다
- Phase 4·5·8에서 "범위 밖 backlog"로 기록한 mis-replicated 240건은 재복제 경로
  수정 이후 전부 자동 해소돼 현재 0이다

Phase 9는 `PASS`다. Phase 10에서 Collector와 분석 Worker를 재개하고 최소 30분
동안 public HTTP/HTTPS, Backend health, Kafka consumer lag, HDFS·Spark 상태와
service host 자원을 관측한다.
