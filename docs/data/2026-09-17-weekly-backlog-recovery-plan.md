# 2026-09 Weekly Streaming backlog 복구 실행계획

- Jira: `S15P21E102-296`
- 기준일: 2026-09-17
- 범위: WEEK A / WEEK B 복구 대상 hour 확정, source 검증, batch·checkpoint·disk·검증 계약, 실행 명령
- **이 문서는 실행 기록이 아니다.** 작성 시점에 Kafka publish·cron·HDFS write·deploy는 하나도 수행하지 않았다

`S15P21E102-296`의 census 결과를 전제로 한다. 이 문서는 그 census를 **hour 단위 manifest와
실행 가능한 명령으로 확정**한 것이다.

## 1. 대상 hour manifest

publisher checkpoint(`published` 229건)와 필요한 hour 집합의 차집합으로 도출했다. census의
개수와 완전히 일치한다.

### WEEK A — `week_start=2026-08-31`

Streaming 구간은 2026-09-01 ~ 09-06의 144시간이고 그중 **20시간**이 미발행이다.
2026-08-31 24시간은 Historical Raw로 이미 보존되어 있어 복구 대상이 아니다.

```text
2026-09-04  00 04 08 09 21 23        (6)
2026-09-05  00 01 03 05 08 17        (6)
2026-09-06  01 03 05 07 11 14 19 21  (8)
```

### WEEK B — `week_start=2026-09-07`

168시간 중 **63시간**이 미발행이다. 2026-09-08은 24/24 전량 정상 발행되어 빠져 있다.

```text
2026-09-07  00 12 14 18                                     (4)
2026-09-09  01 03 13 20 22                                  (5)
2026-09-10  00 01 04 10 18 21 22                            (7)
2026-09-11  00 02 03 06 07 08 09 10 11 15 17 18 20 21 22 23 (16)
2026-09-12  00 01 02 03 05 06 07 08 11 12 15 17 19 20 21 23 (16)
2026-09-13  01 03 04 05 06 07 09 10 11 12 13 14 21 22       (14)
2026-09-13  23                                              (1, redownload)
```

`2026-09-13T21`, `T22`는 census의 EMPTY 2시간(`KafkaTimeoutError`)이고, `T23`은 watch
checkpoint에도 local gz에도 없다.

## 2. source availability

82개 local source 전부를 `gzip -t`로 검사했다.

| | hours | gzip valid | invalid | local gz bytes |
|---|---|---|---|---|
| WEEK A | 20 | **20** | 0 | 1,578,132,675 (1.47 GiB) |
| WEEK B (local) | 62 | **62** | 0 | 3,055,438,991 (2.85 GiB) |
| 합계 | 82 | **82** | 0 | 4,633,571,666 (4.31 GiB) |

`2026-09-13T23`만 upstream에서 다시 받아야 한다. HEAD로 존재를 확인했다(본문 미수신).

```text
https://data.gharchive.org/2026-09-13-23.json.gz
HTTP/2 200  content-length: 20,955,079  last-modified: Mon, 14 Sep 2026 00:05:08 GMT
```

2026-09-01~09-03의 작은 파일은 census에서 upstream Content-Length와 일치함이 확인됐고
재다운로드 대상이 아니다.

## 3. expected count — verifier의 전제

`S15P21E102-264` verifier는 `--expected-counts`가 없으면 복구 대상 hour를 전부
`UNKNOWN`으로 **fail-closed** 처리한다. 복구가 관심 갖는 hour는 정확히 publisher
checkpoint가 비어 있는 hour이기 때문이다. 그래서 이 파일을 먼저 만들어 두었다.

```text
/home/ubuntu/workspace/S15P21E102/.local/weekly-recovery-296/weekly-expected-counts.json
```

GH Archive 원본 gz의 줄 수로 만들었다(runbook이 규정한 방법).

| | 값 |
|---|---|
| 집계 hour | **311** (WEEK A streaming 144 + WEEK B 167) |
| 누락 | `2026-09-13T23` 1건 — redownload 후 추가한다 |
| expected 합계 | 18,990,786 |
| WEEK A 144h / 위험 20h | 6,714,184 / **1,674,237** |
| WEEK B 167h / 위험 62h | 12,276,602 / **4,915,805** |

**publisher checkpoint와의 교차검증: 229개 발행 hour 전부에서 delta 0, 불일치 0건.**
-264 runbook은 대조군 5시간으로 이 방법을 검증했는데, 여기서는 발행된 229시간 전량으로
확인됐다.

**이 파일은 아직 완성본이 아니다.** 현재 311시간 기준이고, `2026-09-13T23`을
redownload한 뒤 그 hour의 gz 줄 수를 넣어 **312시간 기준으로 갱신**해야 한다. 갱신
전에 WEEK B verifier를 돌리면 그 hour가 `UNKNOWN`으로 나와 fail-closed로 FAIL한다 —
이것은 계약대로 동작하는 것이며 갱신을 빼먹었다는 신호다.

> census의 WEEK B 위험 hour expected는 4,915,804로 1건 적다. 이 파일 기준은
> 4,915,805다. 4.9M분의 1(0.00002%) 차이이며, gz 줄 수 방식이 229시간 전량에서
> checkpoint와 정확히 일치하므로 **이 파일을 truth source로 삼는다.**

## 4. checkpoint 계획

복구 전용 state를 backlog와 분리한다. 기존 checkpoint 2개는 evidence baseline이므로
쓰지 않는다.

```text
.local/gharchive-watch/                      ← 기존. 읽기만 한다
  watch-checkpoint.json     sha256 29ac1364…d2c4   (311 hours)
  publish-checkpoint.json   sha256 c3bbc14a…ca058  (229 hours)
  hours/…                   ← source. publish 의 --output-root

.local/weekly-recovery-296/                  ← 복구 전용 (신규)
  weekly-expected-counts.json                ← 작성 완료
  publish-checkpoint.json                    ← pass 가 여기에만 기록한다
  evidence/<pass-id>/…                       ← before/after snapshot
  redownload/                                ← 2026-09-13T23 전용 output-root + checkpoint
```

pass마다 `--publish-checkpoint`는 복구 전용 파일을, `--output-root`는 기존 hours
디렉터리를 가리킨다. `--hours`로 대상을 명시하므로 checkpoint가 비어 있어도 그 hour만
나간다.

**단 하나의 side effect**: publisher는 `publish-progress.json`과
`publish-rejected-events.jsonl`을 `--output-root` 안에 쓴다. 즉 기존 hours 디렉터리에
파일 2개가 새로 생긴다. 기존 gz와 두 checkpoint는 바뀌지 않는다. 이 두 파일은
`S15P21E102-257`의 lineage 증거이므로 보존한다.

pass 시작 전마다 두 기존 checkpoint의 sha256을 위 값과 대조한다. 달라졌다면 즉시 중단한다.

## 5. disk budget

2026-09-17 실측.

| | 여유 |
|---|---|
| service host root | 89 GB / 309 GB |
| data host root | 85 GB / 309 GB |
| HDFS Present / Remaining | 717.85 GB / **341.66 GB** |
| Kafka log dir | 42 MB |

`dfs.replication=2`, rack 2개(`/rack-a` 데이터 3 DN, `/rack-b` 서비스 DataNode4)이므로
**논리 용량이 양쪽 호스트에 각각 한 벌씩** 들어간다. rack-a의 3개 DataNode가 보고하는
84.38 GB는 같은 파일시스템이며 합산되지 않는다.

정상 발행 기준 HDFS logical expansion 2.8~3.5x (census 대조군).

| | local gz | HDFS logical | 호스트당 물리 증가 |
|---|---|---|---|
| WEEK A (20h) | 1.47 GiB | 4.1 ~ 5.2 GiB | 4.1 ~ 5.2 GiB |
| WEEK B (63h) | 2.87 GiB | 8.0 ~ 10.0 GiB | 8.0 ~ 10.0 GiB |
| 합계 | 4.33 GiB | 12.1 ~ 15.2 GiB | **12.1 ~ 15.2 GiB** |

Kafka 쪽은 gz 대비 약 **4.98배**로 실린다(canary 실측: 49,454,090 → 246,349,303).

| pass | hours | gz | Kafka 적재 |
|---|---|---|---|
| WEEK B `--max-hours 6` | 6 | 약 296 MB | 약 1.5 GB |
| WEEK A `--max-hours 4` | 4 | 약 316 MB | 약 1.6 GB |

retention 24h가 pass 사이에 정리한다. pass 간격 3시간 이상이면 동시에 살아 있는 pass는
최대 8개, 즉 Kafka 피크는 약 12 GB다. `Kafka log dir ≤ 25 GB` 규칙 안이다.

**중단 임계**: 서비스 호스트 root free 40 GB 미만이면 다음 pass를 시작하지 않고,
30 GB 미만이면 진행 중인 복구를 중단한다.

## 6. 검증 위치

### VERIFY BEFORE (각 주차 복구 시작 전 1회)

현재 결손 상태를 수치로 고정한다. WEEK A는 `37.9%`, WEEK B는 `40.5%` coverage로
FAIL이 나오는 것이 정상이며, 이것이 after와 비교할 기준선이다.

### VERIFY AFTER (각 주차 복구 완료 후, aggregation 전)

PASS 계약은 `S15P21E102-264`가 정한다.

```text
missing = 0, partial = 0, unknown = 0, overfull_after_dedup = 0
모든 hour: deduplicated_event_count == expected_event_count
합계: expected_event_total == deduplicated_event_total
duplicate raw rows: 허용하되 수치 보고
```

`COMPLETE` 외의 분류가 하나라도 있으면 aggregation으로 넘어가지 않는다. verifier는
FAIL 시 종료 코드 1이다.

hour 존재 여부만 보는 `missing_stream_hours` 게이트로는 판정하지 않는다 — census가
보였듯 위험 82시간 중 80시간이 "존재"하면서 결손 상태였다.

### 실행 환경 주의

`spark-worker` 컨테이너에는 **bind mount가 하나도 없다.** `/opt/gitjob/spark/jobs/`의
verifier는 이미지 안에 있어 실행 가능하지만, -264 runbook이 쓰는
`/opt/gitjob/state/gharchive-watch/…` 경로는 존재하지 않는다. 따라서 checkpoint와
expected-counts 파일은 실행 직전에 `docker cp`로 넣거나 `compose run --rm -v`로
마운트한다. 직접 실행 시 `PYTHONPATH=/opt/gitjob/spark`가 필요하다.

Spark 여유는 1 core / 1024 MB다(C1 archiver가 2 core / 2048 MB 상주). verifier는 그
한도로 실행한다.

## 7. 복구 순서

`S15P21E102-259` canary PASS 전에는 1단계도 시작하지 않는다.

```text
 0. 게이트     -258 Production 반영 확인 → -259 1-hour canary PASS
 1. WEEK B     verify BEFORE (기준선 40.5%)
 2. WEEK B     redownload 2026-09-13T23 (1시간) → expected-counts 갱신
 3. WEEK B     publish 63h = --max-hours 6 x 11 pass
 4. WEEK B     verify AFTER → PASS 필수
 5. WEEK B     aggregation → candidate → Artifact → publication → PUBLIC_GITHUB
               → C export → TREND
 ── 여기서 -295 배포를 기다린다 ──
 6. WEEK A     -295 transition mode merge 및 배포
 7. WEEK A     verify BEFORE (기준선 37.9%)
 8. WEEK A     publish 20h = --max-hours 4 x 5 pass
 9. WEEK A     verify AFTER → PASS 필수
10. WEEK A     transition aggregation → downstream E2E
```

WEEK B를 먼저 하는 이유는 코드 의존이 없기 때문이다. WEEK A는 `week_start=2026-08-31`이
Historical/Streaming cutoff를 가로질러 `S15P21E102-295`의 transition mode 없이는
`validate_period()`가 fail-closed로 거부한다.

**WEEK A와 WEEK B를 동시에 republish 하지 않는다.**

### pass 간 진행 조건

다음을 전부 만족하기 전에는 다음 pass를 시작하지 않는다. 기준 간격 3시간 이상.

1. 직전 pass의 C1 lag = 0 (checkpoint end offsets == Kafka log-end offsets)
2. Kafka log dir ≤ 25 GB
3. HDFS missing / corrupt / under-replicated = 0
4. service host root free ≥ 40 GB
5. 기존 checkpoint 2개 sha256 불변

## 8. fail / rollback 기준

| 상황 | 조치 |
|---|---|
| publisher가 hour를 `failed`로 기록 | 그 pass에서 중단. `publish-progress.json`이 마지막 ACK 지점을 들고 있으므로 같은 hour를 다시 돌리면 그 지점부터 재개된다. 처음부터 다시 보내지 않는다 |
| oversized rejection 발생 | 정상 동작이다. `publish-rejected-events.jsonl`의 `hour`/`source_id`/`bytes`/`limit`/`reason`을 기록하고 계속 진행한다. expected count에서 해당 건을 차감해 verifier와 대조한다 |
| C1 lag가 수렴하지 않음 | 다음 pass 중단. C1을 재시작하지 않고 checkpoint와 로그를 먼저 본다 |
| verifier `PARTIAL` | 해당 hour만 다시 publish. HDFS는 건드리지 않는다 |
| verifier `OVERFULL_AFTER_DEDUP` | **자동 조치 없음.** 재발행으로 설명되지 않으므로 사람이 판단한다 |
| verifier `UNKNOWN` | expected-counts에 그 hour가 없다는 뜻이다. 먼저 채운다 |
| root free < 30 GB | 즉시 중단 |
| 기존 checkpoint sha256 변경 | 즉시 중단. 다른 작업이 backlog state를 건드린 것이다 |

**롤백할 수 없는 것**: Kafka에 나간 이벤트는 회수할 수 없고 HDFS에 적재된 행도 지우지
않는다. 복구가 만드는 중복은 `DEDUP_KEYS = (source, source_id, schema_version)`가
접는다 — census에서 raw 18,279,061행 → dedup 2,627,179행으로 확인됐다. **따라서 사전
cleanup도, 실패 후 HDFS 삭제도 하지 않는다.** 되돌리기가 아니라 다시 채우는 것이 복구
방식이다.

## 9. 명령

`$R = /home/ubuntu/workspace/S15P21E102`, `$S = $R/.local/gharchive-watch`,
`$W = $R/.local/weekly-recovery-296`. 전부 데이터 호스트(J15E102A)에서 실행한다.

### 9.0 pass 전 불변 확인

```bash
sha256sum $S/watch-checkpoint.json $S/publish-checkpoint.json
# 29ac1364ad80bee0459e4aacf31288f9f93b97adc9c6f4c016f0eff443d7d2c4  watch
# c3bbc14a4ee754a6dcdcba3373197d99988dc99340b9675fe5c7479ebe0ca058  publish
df -h /
docker exec gitjob-service-kafka-1 du -sh /tmp/kraft-combined-logs
```

### 9.1 redownload — 2026-09-13T23 (정확히 1시간)

```bash
cd $R && docker compose \
  --project-directory "$R" --env-file "$R/.env.data" \
  -f "$R/Infra/compose/compose.yaml" -f "$R/Infra/compose/compose.ec2-data.yaml" \
  --profile data run --rm --no-deps -T \
  --user "$(id -u):$(id -g)" \
  --volume "$W/redownload:/data/redownload" \
  collector \
  python -m collector.gharchive download \
  --start 2026-09-13T23:00:00Z --end 2026-09-14T00:00:00Z \
  --historical-start 2026-09-13T23:00:00Z --historical-cutoff 2026-09-14T00:00:00Z \
  --output-root /data/redownload/hours \
  --checkpoint  /data/redownload/watch-checkpoint.json
```

받은 뒤 `gzip -t`, sha256, `zcat | wc -l`을 기록하고 그 줄 수를
`weekly-expected-counts.json`에 `2026-09-13T23:00:00Z` 키로 추가한다.

### 9.2 publish 1 pass (WEEK B 예시 — 첫 6시간)

```bash
cd $R && docker compose \
  --project-directory "$R" --env-file "$R/.env.data" \
  -f "$R/Infra/compose/compose.yaml" -f "$R/Infra/compose/compose.ec2-data.yaml" \
  --profile data run --rm --no-deps -T \
  --user "$(id -u):$(id -g)" \
  --volume "$S:/data/gharchive-watch" \
  --volume "$W:/data/recovery" \
  collector \
  python -m collector.gharchive publish \
  --output-root /data/gharchive-watch/hours \
  --publish-checkpoint /data/recovery/publish-checkpoint.json \
  --max-hours 6 \
  --hours 2026-09-07T00:00:00Z,2026-09-07T12:00:00Z,2026-09-07T14:00:00Z,2026-09-07T18:00:00Z,2026-09-09T01:00:00Z,2026-09-09T03:00:00Z
```

WEEK A는 `--max-hours 4`에 그 주차 hour만 넣는다. pass 구성은 위 manifest 순서를 그대로
6개씩(WEEK B) / 4개씩(WEEK A) 끊는다 — WEEK B 11 pass, WEEK A 5 pass.

### 9.3 C1 수렴 확인

```bash
docker exec gitjob-service-kafka-1 /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server localhost:9092 --topic github.events --time -1
docker exec gitjob-data-hdfs-namenode-1 \
  hdfs dfs -ls /gitjob/checkpoints/c1/github.events/commits | tail -2
docker exec gitjob-data-hdfs-namenode-1 \
  hdfs dfs -cat /gitjob/checkpoints/c1/github.events/offsets/BATCH_ID
```

두 offset 집합이 같으면 lag 0이다.

### 9.4 verifier

```bash
docker cp $S/publish-checkpoint.json gitjob-data-spark-worker-1:/tmp/publish-checkpoint.json
docker cp $W/weekly-expected-counts.json gitjob-data-spark-worker-1:/tmp/expected-counts.json

docker exec -e PYTHONPATH=/opt/gitjob/spark gitjob-data-spark-worker-1 \
  /opt/spark/bin/spark-submit \
  --master spark://100.70.66.38:7077 \
  --total-executor-cores 1 --executor-memory 1g --driver-memory 1g \
  --conf spark.hadoop.fs.defaultFS=hdfs://100.70.66.38:8020 \
  --conf spark.hadoop.dfs.client.use.datanode.hostname=true \
  /opt/gitjob/spark/jobs/weekly_activity_verify.py \
  --input hdfs:///gitjob/parquet/stream/github.events \
  --period-start 2026-09-07T00:00:00Z \
  --period-end   2026-09-14T00:00:00Z \
  --publish-checkpoint /tmp/publish-checkpoint.json \
  --expected-counts    /tmp/expected-counts.json \
  --report-output      /tmp/weekly-verify-2026-09-07.json
```

WEEK A는 `--period-start 2026-09-01T00:00:00Z --period-end 2026-09-07T00:00:00Z`로
Streaming 구간만 검증한다. 2026-08-31 Historical 24시간은 `S15P21E102-295`의 transition
mode가 별도로 검증한다.

## 10. -295 의존 구간과 일반 구간

| 구간 | -295 의존 | 이유 |
|---|---|---|
| WEEK B 전체 (63h publish → aggregation → downstream) | **없음** | 168시간 전부 cutoff 이후 Streaming이다. 기존 `stream-parquet` 경로 그대로 |
| WEEK A Streaming 20h publish | **없음** | publish는 Kafka·C1·HDFS 경로이고 Weekly 집계가 아니다 |
| WEEK A verifier (09-01~09-06) | **없음** | Streaming 구간만 본다 |
| **WEEK A aggregation 이후 전부** | **있음** | `week_start=2026-08-31`이 `SUPPORTED_HISTORICAL_CUTOFF=2026-09-01`을 가로질러 `raw-json`·`stream-parquet` 양쪽에서 fail-closed로 거부된다 |

즉 **WEEK A도 publish와 검증까지는 -295 없이 진행할 수 있다.** 막히는 것은 aggregation
부터다. 이 분리 덕분에 -295 배포를 기다리는 동안 WEEK A raw 복구를 끝내 둘 수 있다.

## 11. 작성 시점 상태

| 게이트 | 상태 |
|---|---|
| `S15P21E102-258` develop merge | 완료 (`405ccc2`) |
| `S15P21E102-258` Production 반영 | **미완료** — Connect가 아직 `DailyRollingFileAppender` |
| `S15P21E102-259` 1-hour canary | **미실행** — source(`2026-09-16T00`)만 확보 |
| `S15P21E102-264` verifier | develop 존재, spark 이미지에 포함 확인 |
| `S15P21E102-295` transition mode | **미구현** (`해야 할 일`) |

복구는 -258 Production 반영과 -259 canary PASS 이후에만 시작한다.
