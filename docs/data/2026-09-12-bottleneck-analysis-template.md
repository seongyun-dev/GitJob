# 병목 판정 기준 · 튜닝 후보 · 발표 템플릿

- Jira: `S15P21E102-226`
- 작성일: 2026-09-12
- 기준 커밋: `origin/develop` 12adce4
- 선행: [부하 테스트 계획](2026-09-12-load-test-plan.md)

"느려졌다"는 판정이 아니다. 이 문서는 **어떤 숫자가 나오면 병목이라고 부를지**를
미리 정해 둔다. 측정한 뒤에 기준을 정하면 원하는 결론에 맞출 수 있다.

---

## 1. 판정 기준

### 1.1 1차 기준 — 비선형 증가

가장 먼저 보는 것. 데이터량 증가율 대비 소요시간 증가율의 비를 쓴다.

```
증가배수 R = (단계 소요시간 / Baseline 소요시간) ÷ (단계 입력량 / Baseline 입력량)
```

| R | 판정 | 뜻 |
|---|---|---|
| R ≤ 1.2 | **정상** | 선형. 분산처리가 먹히고 있다 |
| 1.2 < R ≤ 1.5 | **관찰** | 약한 열화. 다음 단계에서 확인 |
| R > 1.5 | **병목** | 원인 분해로 진행 (§2) |
| R > 2.0 | **심각** | 그 단계에서 중단하고 원인부터 |

예: 입력 +23%인데 소요 +60% → R = 1.60/1.23 = **1.30** → 관찰.
입력 +23%인데 소요 +90% → R = 1.90/1.23 = **1.54** → 병목.

### 1.2 Spark

| 지표 | 병목 기준 | 근거 |
|---|---|---|
| 최장 stage 비중 | **전체 job 시간의 60% 이상** | 한 stage가 전부면 그 stage만 고치면 된다 |
| task skew (max ÷ median) | **5배 이상** | 파티션 하나가 늦으면 stage가 그만큼 늘어난다 |
| Shuffle Write 증가율 | **입력 증가율의 2배 이상** | 예: 입력 +23%에 shuffle +50% |
| Spill (disk) | **0이 아님** | 워커 메모리가 작아 디스크로 샌다 |
| GC time 비중 | **전체 executor 시간의 15% 이상** | |
| executor memory 사용 | **90% 이상이 지속** | |

> 현재 Spark worker는 2코어급이고 `github.events` partition 6은 "소비 가능한 것보다
> 많게" 의도적으로 잡았다(`kafka-topics.sh` 주석). 따라서 **executor 부족은 놀라운
> 일이 아니라 예상된 1순위 병목**이다.

### 1.3 HDFS

| 지표 | 병목 기준 |
|---|---|
| host `df` available | **30 GB 미만** — 다음 단계 진행 불가 |
| under-replicated | **5분 넘게 0이 아님** |
| pending replication | 단계 종료 후에도 감소하지 않음 |
| DataNode imbalance | **DN1과 DN4의 Used 차이가 20% 이상** |
| 유효 write throughput | 단계가 올라가는데 **MB/s가 정체하거나 감소** |
| block count 증가 | 입력 증가율의 **3배 이상** → small file 문제 |

> RF2에 Live DataNode 2이므로 **한 노드가 밀리면 대안이 없다.** under-replicated는
> RF3 때보다 훨씬 빨리 문제로 드러난다.

### 1.4 Kafka

| 지표 | 병목 기준 |
|---|---|
| consumer lag | **단계 종료 후에도 계속 증가** (일시 증가는 정상) |
| lag 회복 시간 | **입력 구간 길이보다 길다** = 따라잡지 못한다 |
| partition 편차 | 최대/최소 처리량 **3배 이상** = 키 분포 쏠림 |
| producer records/sec | 단계가 올라가는데 정체 |

> `github.events`는 key가 repo id다. 활동량 상위 repo가 특정 partition에 몰리면
> 편차가 커진다 — 측정할 가치가 있는 지점이다.

### 1.5 서버 / 서비스

| 지표 | 병목 기준 |
|---|---|
| CPU | **90% 이상이 job 시간의 50% 넘게 지속** |
| memory | **90% 이상 지속** 또는 swap 발생 |
| disk util | **90% 이상 지속** |
| load average | **코어 수의 2배 초과 지속** |
| API p95 | **Baseline의 3배 초과** |
| error rate | **1% 초과** |

> 두 EC2는 동일 사양이고 논리 DataNode들이 **같은 물리 파일시스템**을 공유한다.
> 따라서 disk I/O 포화는 HDFS·Spark shuffle·Parquet write가 서로를 밀어내는 형태로
> 나타난다. 단일 원인으로 읽지 않는다.

### 1.6 기준을 이렇게 잡은 이유

연구실 기준(p99, µs 단위, 장시간 soak)이 아니다. 6주 프로젝트에서 **한 번의 실행으로
판정 가능**하고, **Spark UI와 CLI 조회만으로 얻을 수 있는** 값만 골랐다. 반복 측정
평균이 아니라 단일 실행 값을 쓰므로, 경계에 걸치면 "관찰"로 두고 다음 단계에서
재확인한다.

---

## 2. 원인별 튜닝 후보

**실제 코드·구성에서 조절 가능한 것만** 적는다. 각 항목에 조절 지점을 명시한다.

### 2.1 Spark

| 후보 | 조절 지점 | 언제 |
|---|---|---|
| shuffle partition 조정 | `spark.sql.shuffle.partitions` — 현재값은 job summary에 찍힌다 | 최장 stage 비중 높음 / task 수가 코어 대비 과소·과다 |
| executor memory | compose의 spark-worker 설정 | Spill > 0, GC 비중 높음 |
| worker 수 | Service Server의 spark-worker 2 활용 | CPU 포화, task 대기 |
| 입력 partition 수 | glob 범위 · `repartition` | 입력 파일 수 대비 task 수가 안 맞을 때 |
| skew 처리 | `repo_id` 기준 group by에 salting | task skew 5배 이상 |
| 출력 파일 수 | `coalesce` | block count 급증 (small file) |

> ⚠️ `repo_activity_weekly.py`의 출력 layout은 **C조 exporter 계약에 묶여 있다**
> (주차당 디렉터리 하나, `week_start`는 데이터 컬럼). `coalesce`로 파일 수를 줄이는
> 것은 가능하지만 **`partitionBy`로 바꾸면 안 된다** — 컬럼이 파일에서 사라져
> exporter의 period binding이 깨진다.

### 2.2 Kafka

| 후보 | 조절 지점 | 언제 |
|---|---|---|
| `batch_flush_size` | `AI/common/kafka.py` `KafkaPythonTransport.batch_flush_size` (현재 5,000) | producer throughput 정체 |
| `request_timeout_ms` | 같은 파일 (현재 20,000) | 타임아웃 빈발 |
| consumer parallelism | C1의 `maxOffsetsPerTrigger` (`spark-c1-archiver.sh` `MAX_OFFSETS_PER_TRIGGER`, 현재 10,000) | consumer가 못 따라감 |
| partition 수 | `kafka-topics.sh` | 편차 3배 이상 |

> ⚠️ **partition은 줄일 수 없다.** `github.events`는 이미 6이고 이는 현재 워커가
> 소비할 수 있는 것보다 많게 잡은 값이다. 늘리는 것은 키 재해싱을 유발해 per-key
> 순서를 깬다 — 마지막 수단이다.

### 2.3 HDFS

| 후보 | 조절 지점 | 언제 |
|---|---|---|
| 출력 파일 수 축소 | Spark `coalesce` | block count가 입력의 3배 이상 증가 |
| block size | `dfs.blocksize` | 파일 대부분이 block size보다 훨씬 작을 때 |
| 오래된 snapshot 정리 | 검증 후 수동 | host df 부족 |

> ⚠️ **replication은 튜닝 대상이 아니다.** RF2가 최종 목표이고 DataNode가 2개다.
> RF를 1로 낮추면 노드 하나 손실이 곧 데이터 손실이다. `setrep`은 이 계획에서
> 금지한다.
>
> ⚠️ **snapshot 삭제는 되돌릴 수 없다.** 단계 간 비교 대상이므로 테스트가 전부
> 끝난 뒤에만, 무엇을 지우는지 확인하고 한다.

### 2.4 Crawler

| 후보 | 조절 지점 | 언제 |
|---|---|---|
| source 병렬화 | `AI/schedule.toml`의 `at` 시각 분산 (현재 09:10/09:30/09:50/10:10/… 이미 20분 간격) | 회차가 겹쳐 서로를 밀 때 |
| request pacing | 사이트별 collector 설정 | 원천 rate limit |

> ⚠️ concurrency를 올리는 것은 **외부 사이트에 대한 요청량 증가**다. `schedule.toml`의
> `source_admission` 기록과 기준 A 판단이 있는 source들이므로 임의로 올리지 않는다.
> 부하 측정 목적이라면 기존 회차 **재처리**로 대신한다.

---

## 3. 발표용 결과 템플릿

한 장에 `문제 발견 → 원인 → 개선 → 결과`가 들어가게 쓴다.

### 3.1 한 장 템플릿

---

> ## [병목 N] {한 줄 제목 — 어디가 막혔는가}
>
> **발견**
> 데이터량을 Baseline 대비 **{X}배**까지 늘렸을 때 처리시간은 선형에 가깝게
> 증가했으나, **{단계}** 구간에서 {지표}가 **{Y}배** 급증하며 전체 Job 시간이
> **{Z}배**가 되었다. (증가배수 R = **{R}**, 판정 기준 1.5 초과)
>
> | | Baseline | {직전 단계} | **{병목 단계}** |
> |---|---|---|---|
> | 입력량 | 744h | {} | {} |
> | Job 시간 | {} | {} | **{}** |
> | R | 1.00 | {} | **{}** |
> | {병목 지표} | {} | {} | **{}** |
>
> **원인**
> {Spark UI / CLI에서 확인한 사실. 추정과 사실을 구분해 쓴다}
> - 최장 stage: `{stage}` — 전체의 {}%
> - {근거 지표}
>
> **개선**
> {무엇을 바꿨는지, 조절 지점과 값을 명시}
> - `{설정}`: {before} → {after}
>
> **결과**
>
> | 지표 | 개선 전 | 개선 후 | 변화 |
> |---|---|---|---|
> | Job time | {} | {} | **−{}%** |
> | {병목 지표} | {} | {} | **−{}%** |
> | max CPU | {} | {} | {}%p |
> | R | {} | {} | {} |
>
> **남은 것**
> {한 줄. 해결되지 않은 부분을 숨기지 않는다}

---

### 3.2 작성 예시 (형식 참고용 — 실측 아님)

> ## [병목 1] 2.2배 구간에서 Shuffle Write 급증
>
> **발견** — 데이터량을 1.87배까지 늘리는 동안 처리시간은 1.9배로 거의 선형이었다
> (R = 1.02). 2.32배 구간에서 Shuffle Write가 3.4배로 뛰며 Job 시간이 2.7배가
> 되었다. R = 1.16... *(이하 실측으로 채움)*
>
> **원인** — `groupBy(repo_id, week_start)` stage가 전체의 72%. task max/median 6.8배.
>
> **개선** — `spark.sql.shuffle.partitions` 200 → 48 (executor 코어 대비 과다 분할).
>
> **결과** — Job time −31%, Shuffle Write −18%, CPU utilization +14%p.
>
> **남은 것** — skew 자체는 남아 있다. salting은 적용하지 않았다.

### 3.3 발표에서 보여주기 좋은 그래프 3개

1. **입력량 대비 Job 시간** (x: Baseline/S1/S2/S3/S4, y: 초) — 선형 기준선을 같이
   그려서 어디서 벌어지는지 한눈에 보이게. **R 값을 막대 위에 라벨로.**
2. **Job 시간의 stage별 분해 누적 막대** — 어느 stage가 커지는지가 원인 설명 그 자체
3. **개선 전/후 비교 막대** — Job time · Shuffle · CPU 세 지표를 나란히

보조로 쓸 만한 것: HDFS Used 증가 곡선(용량 한계가 언제 오는지), Kafka lag 시계열
(Realtime 경로가 가동된 뒤).

---

## 4. 기록 원칙

- **측정 전에 기준을 고정한다.** 이 문서 §1을 측정 후에 바꾸지 않는다
- **단일 실행 값임을 명시한다.** 평균이 아니다
- **실패와 중단도 기록한다.** "S4에서 df 부족으로 중단"은 결과이지 공백이 아니다
- **추정과 실측을 구분한다.** 이 프로젝트의 다른 문서들이 지키는 규칙과 같다
- 개선 후 수치는 **같은 단계에서 같은 절차로** 다시 측정한 값만 쓴다
