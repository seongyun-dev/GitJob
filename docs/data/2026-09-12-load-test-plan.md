# GitJob 부하 테스트 계획

- Jira: `S15P21E102-226`
- 작성일: 2026-09-12
- 기준 커밋: `origin/develop` 12adce4
- 목적: MVP 정상화 후 데이터량을 단계적으로 늘려 **어디가 먼저 막히는지** 측정한다
- 선행: [MVP E2E Runbook](2026-09-12-mvp-e2e-runbook.md)의 최종 PASS 조건 7개

> 이 계획은 **아직 실행하지 않았다.** 아래 표의 값 칸은 전부 비어 있고, 채우는 것이
> 실행 단계의 일이다. Baseline 열의 실측만 기존 검증 문서에서 인용했다.

---

## 1. 무엇을 늘리는가

"데이터량"이 파이프라인마다 다른 것을 뜻하므로 축을 먼저 고정한다.

| 축 | 단위 | 늘리는 방법 | 근거 |
|---|---|---|---|
| **GH Archive Historical** | UTC hour 수 | 기간을 늘린다 (1개월 → 2개월 → …) | Raw는 시간당 파일 1개, 745±24시간/월 |
| **GH Archive Realtime** | 시간당 event 수 | 기간을 늘린다 | 시간당 event 수는 원천이 정하므로 우리가 못 늘린다 |
| **Repo Activity / Weekly** | 입력 event 수 | 위 두 축을 따라감 | |
| **채용공고** | 회차당 공고 수 | source 수 × 회차 수 | 4 source × 2회/일 (`-230` 이후) |

**핵심 제약**: GH Archive의 시간당 이벤트 밀도는 우리가 조절할 수 없다. 따라서
증가는 **기간 확장**으로만 만든다. 아래 단계는 그 전제로 설계했다.

---

## 2. 단계 정의

Baseline은 **2026-08 한 달**로 잡는다. 6개월 전량은 이미 수집돼 있으므로 추가
수집 없이 기간만 넓혀 단계를 만들 수 있다 — 부하 테스트가 GH Archive에 대한
재다운로드를 유발하지 않는다.

| 단계 | 기간 | hours | Baseline 대비 | 증가폭 |
|---|---|---:|---:|---:|
| **Baseline** | 2026-08 | 744 | 100% | — |
| **S1 (120%)** | 2026-08 + 2026-07 상반 | 888 | 119% | +19% |
| **S2 (150%)** | 2026-07 ~ 2026-08 | 1,488 | 200% → **조정** | |
| **S3 (180%)** | | | | |
| **S4 (220%)** | | | | |

⚠️ **월 단위로 끊으면 100% → 200%로 건너뛴다.** 20~30% 유지를 위해 **일 단위**로
자른다. 아래가 실제로 쓸 단계다.

| 단계 | 기간 (UTC, end exclusive) | hours | Baseline 대비 | 이전 단계 대비 |
|---|---|---:|---:|---:|
| **Baseline** | 2026-08-01 ~ 2026-09-01 | 744 | 100% | — |
| **S1** | 2026-07-25 ~ 2026-09-01 | 912 | 123% | +23% |
| **S2** | 2026-07-16 ~ 2026-09-01 | 1,128 | 152% | +24% |
| **S3** | 2026-07-05 ~ 2026-09-01 | 1,392 | 187% | +23% |
| **S4** | 2026-06-21 ~ 2026-09-01 | 1,728 | 232% | +24% |

전 구간이 이미 HDFS에 있는 2026-03~08 안에 들어간다. **신규 수집 0건.**

### 왜 이 방향으로 넓히는가

끝을 `2026-09-01T00:00:00Z`(= `HISTORICAL_CUTOFF`)에 고정하고 **시작을 앞으로 당긴다.**
cutoff를 넘기면 Raw 경로가 아니라 Streaming 경로가 되므로 배치 축이 바뀐다.

---

## 3. Baseline 실측 (기존 검증 문서 인용)

새로 측정한 값이 아니다. 측정일과 출처를 붙인다.

| 항목 | 값 | 출처 |
|---|---:|---|
| Raw files (2026-08) | 744 | `-105` / `-179` |
| Raw 압축 | 11,654,413,308 B | `-179` |
| Raw 해제 | 57,458,023,922 B | `-179` |
| events | 87,516,869 | `-105` |
| 시간당 평균 events | 약 117,600 | `-105` |
| Repo Activity unique repos | 5,711,133 | `-109` |
| Weekly rows | 7,967,178 | `-166` |
| Weekly parquet | 200 files / 261,039,111 B | `-166` |
| 6개월 Spark 전량 count 소요 | 2시간 41분 43초 | `-179`, 2026-09-09 |
| Top-20,000 valid coverage | 24.5638% | `-109` |

**6개월(4,416h) 전량 count가 2h41m**이었으므로, 744h 기준 Baseline job은 대략
25~30분대가 예상된다. 이것은 예상이지 실측이 아니다 — Baseline 실행이 첫 할 일이다.

---

## 4. 측정 지표와 수집 방법

⚠️ **이 절이 이 계획에서 가장 중요하다.** 원하는 지표 전부가 자동 수집되지는 않는다.

`docs/be/admin-monitoring-api.md` §7이 명시한다 — **HDFS logical capacity/block
health, Spark application/executor/stage, Collector business counter, Kafka topic
business 지표는 Prometheus exposition endpoint나 exporter가 없다.** 모니터링 API는
`coverage: NOT_COLLECTED`로 알린다.

| 영역 | 지표 | 수집 경로 | 자동/수동 |
|---|---|---|---|
| **서버** | CPU, memory, network | node-exporter → Prometheus → `/api/v1/admin/monitoring/timeseries` | **자동** |
| 서버 | disk I/O | node-exporter `node_disk_*_bytes_total` — 수집되나 API에 없음 | Prometheus 직접 질의 |
| 서버 | load average | `node_load1` 수집 여부 미확인 | `uptime` 수동 |
| **Kafka** | lag, records/sec, bytes/sec | kafka-exporter → Prometheus | **자동** |
| Kafka | partition별 처리량 | kafka-exporter | **자동** |
| **HDFS** | DFS Used/Remaining, block count | `hdfs dfsadmin -report` | **수동 CLI** |
| HDFS | under-replicated, pending replication | `hdfs fsck /gitjob` | **수동 CLI** |
| HDFS | DataNode imbalance | `hdfs dfsadmin -report` 노드별 Used | **수동 CLI** |
| HDFS | read/write throughput | job 소요시간 ÷ 처리 바이트로 역산 | **계산** |
| **Spark** | job duration | **job이 stdout에 내는 summary JSON의 `runtime_seconds`** | **자동(로그)** |
| Spark | stage/task duration, shuffle R/W, spill, GC | Spark UI / History Server | **수동 캡처** |
| Spark | executor CPU/memory | Spark UI Executors 탭 | **수동 캡처** |
| Spark | skew | Stage 탭의 task duration 분포 | **수동 캡처** |
| **서비스** | job completion time | 위 summary + wall clock | **자동(로그)** |
| 서비스 | API latency, error rate | nginx/backend 로그 | 수동 |

### 이미 있는 계측을 최대한 쓴다

`repo_activity_topn.py`와 `repo_activity_weekly.py`는 **실행마다 구조화된 summary
JSON을 stdout에 출력한다** — `runtime_seconds`, `input.file_count`,
`total_input_events`, `parquet_file_count`, `parquet_bytes`, `executor_count`,
`default_parallelism`, `shuffle_partitions`, `data_quality` 전부 들어 있다.
**부하 단계마다 이 JSON을 파일로 남기는 것이 1차 데이터다.** 새 계측을 만들 필요가 없다.

```bash
... ./Infra/scripts/spark-repo-activity-topn.sh | tee .local/loadtest/S1-activity.json
```

### 기존 벤치마크 도구의 한계

`Infra/scripts/spark-benchmark.sh`가 `BENCHMARK_WORKERS=1,2,4`,
`BENCHMARK_DATASET_MULTIPLIERS=1,2,4`로 스케일 실험을 지원한다. **그러나 2호스트
레이아웃에서는 스스로 거부한다** — `DATA_TS_IP`가 설정돼 있으면
`spark-benchmark.sh --scale is single-host only`로 종료한다(워커마다 호스트 네트워크
포트가 고정이라 `--scale`이 충돌한다). 현재 구성에서는 **실제 job을 기간만 바꿔
돌리는 것이 유일한 방법**이고, 이 계획이 그렇게 설계된 이유다.

`spark-shuffle-canary.sh`는 HDFS를 건드리지 않고 두 호스트 간 shuffle만 강제한다.
단계마다 돌리면 shuffle 경로의 열화를 저장소와 분리해 볼 수 있다.

---

## 5. 단계별 실행 절차

각 단계에서 **같은 순서로 같은 것을 측정한다.** 순서가 바뀌면 비교가 깨진다.

1. **사전 스냅샷** — `hdfs dfsadmin -report`, `hdfs fsck /gitjob`, `df -h /` 저장
2. **Repo Activity 실행** — 새 `snapshot=` id로, summary JSON을 파일로 저장
3. **Weekly 실행** — 새 `snapshot=` id로, summary JSON 저장
4. **Spark UI 캡처** — Stages(정렬: Duration), Executors 탭
5. **사후 스냅샷** — 1과 동일
6. **Prometheus 질의** — 실행 구간의 CPU/memory/network/disk I/O max
7. **표 기록** — §6

⚠️ 출력 경로는 매 단계 **새 snapshot id**를 쓴다. `errorifexists`라 재사용하면
시작 단계에서 거부된다. 그리고 **기존 snapshot을 지우지 않는다** — 단계 간 비교
대상이다.

---

## 6. 기록 표

### 6.1 단계 요약

| 항목 | Baseline | S1 (123%) | S2 (152%) | S3 (187%) | S4 (232%) |
|---|---|---|---|---|---|
| 기간 | 2026-08 | 07-25~ | 07-16~ | 07-05~ | 06-21~ |
| 입력 hours | 744 | 912 | 1,128 | 1,392 | 1,728 |
| 입력 events | 87,516,869 | | | | |
| 입력 압축 bytes | 11.65 GB | | | | |
| **Activity job 소요(s)** | | | | | |
| **Weekly job 소요(s)** | | | | | |
| 소요 배수 (vs Baseline) | 1.00 | | | | |
| throughput (events/s) | | | | | |
| 출력 parquet files | | | | | |
| 출력 parquet bytes | | | | | |
| unique repos | 5,711,133 | | | | |
| **PASS / FAIL** | | | | | |

### 6.2 자원

| 항목 | Baseline | S1 | S2 | S3 | S4 |
|---|---|---|---|---|---|
| max CPU % (Data) | | | | | |
| max CPU % (Service) | | | | | |
| max memory % (Data) | | | | | |
| max memory % (Service) | | | | | |
| disk read B/s peak | | | | | |
| disk write B/s peak | | | | | |
| network B/s peak | | | | | |
| load average peak | | | | | |

### 6.3 HDFS

| 항목 | Baseline | S1 | S2 | S3 | S4 |
|---|---|---|---|---|---|
| DFS Used (전) | | | | | |
| DFS Used (후) | | | | | |
| DFS Remaining | | | | | |
| host df available | | | | | |
| block count | | | | | |
| under-replicated | 0 | | | | |
| pending replication | 0 | | | | |
| DN1 Used / DN4 Used | | | | | |
| imbalance % | | | | | |
| fsck | HEALTHY | | | | |

### 6.4 Spark

| 항목 | Baseline | S1 | S2 | S3 | S4 |
|---|---|---|---|---|---|
| executor count | | | | | |
| shuffle partitions | | | | | |
| 최장 stage 이름 | | | | | |
| 최장 stage 소요(s) | | | | | |
| **최장 stage 비중 %** | | | | | |
| Shuffle Read | | | | | |
| Shuffle Write | | | | | |
| Spill (memory/disk) | | | | | |
| max task duration | | | | | |
| median task duration | | | | | |
| **skew 비 (max/median)** | | | | | |
| GC time 비중 % | | | | | |

### 6.5 Kafka (Realtime 경로가 가동된 뒤에만)

| 항목 | Baseline | S1 | S2 | S3 | S4 |
|---|---|---|---|---|---|
| producer records/sec | | | | | |
| producer bytes/sec | | | | | |
| consumer records/sec | | | | | |
| **consumer lag (peak)** | | | | | |
| lag 회복 시간(s) | | | | | |
| partition별 편차 % | | | | | |

⚠️ **C1 Archiver는 consumer group을 쓰지 않는다**(의도된 설계). 따라서
`kafka-consumer-groups.sh --describe`에 C1이 나오지 않고 **lag 지표가 존재하지
않는다.** C1의 진척은 checkpoint offset으로만 본다. kafka-exporter의 lag은 C2
extractor 등 group을 쓰는 소비자에만 적용된다.

### 6.6 E2E

| 항목 | Baseline | S1 | S2 | S3 | S4 |
|---|---|---|---|---|---|
| Raw → Activity 완료(min) | | | | | |
| Activity → Weekly 완료(min) | | | | | |
| Weekly → manifest 완료(min) | | | | | |
| **전체 E2E(min)** | | | | | |
| API p95 (ms) | | | | | |
| error rate % | | | | | |

---

## 7. 단계 중단 기준

다음 중 하나라도 걸리면 **그 단계에서 멈추고 원인을 기록한다.** 다음 단계로 넘어가
데이터를 더 쌓지 않는다.

| 조건 | 이유 |
|---|---|
| host `df` available < 30 GB | 다음 단계 출력이 들어갈 자리가 없다 |
| `fsck`가 HEALTHY가 아님 | 저장소 문제를 부하 문제로 오해하게 된다 |
| under-replicated > 0이고 5분 내 회복 안 됨 | RF2에서 한 노드가 밀리고 있다 |
| job이 Baseline의 5배 초과 | 병목이 이미 명확하다. 더 키울 이유가 없다 |
| OOM / executor lost | 자원 한계. §튜닝 후보로 |

---

## 8. 이 계획의 한계

- **Realtime 경로는 아직 부하를 걸 수 없다.** watcher·producer·C1이
  아직 **등록·기동되지 않았다**. `-228`(C1 compose service)과 `-229`(watcher cron
  스크립트)로 실행 경로는 갖춰졌지만 토픽 생성·crontab 등록·첫 기동이 남아 있고,
  `github.events` offset은 0이다. §6.5는 그 경로가 실제로 도는 뒤에 채운다
- **Spark 지표는 수동 캡처다.** exporter가 없으므로 단계마다 사람이 UI를 봐야 한다.
  자동화하려면 Spark metrics sink 설정이 필요하고 그것은 별도 범위다
- **채용공고 축은 이 계획에 포함하지 않았다.** 크롤링 부하는 외부 사이트에 대한
  요청량이라 마음대로 늘리는 것이 적절하지 않다. 늘린다면 concurrency가 아니라
  기존 회차 재처리로 측정한다
- 값은 전부 비어 있다. **Baseline 실행이 첫 작업이고, 그때까지 이 문서의 숫자는
  기존 문서 인용뿐이다**
