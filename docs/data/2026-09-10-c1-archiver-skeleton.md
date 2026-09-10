# C1 Archiver 골격 — `-112` 착수 기록

> 기준일: 2026-09-10
> 대상: `S15P21E102-112` 컨슈머 골격 중 C1
> 계약: [`2026-09-08-kafka-topic-consumer-matrix-and-envelope.md`](2026-09-08-kafka-topic-consumer-matrix-and-envelope.md) (`-102`·`-103`)

---

## 1. `-102` §5 를 정정해야 하는 것

`-102` §5 가 남긴 충돌 1건은 **충돌이 아니었고**(§1.1), 대신 §5 가 세지
않은 것이 하나 있다(§1.2). `-108` 완료 조건을 고칠 때 둘 다 반영해야 한다.

### 1.1 오프셋 소유 주체 — 충돌이 아니라 컨슈머가 다른 것이었다

| 티켓 | 기재 |
|---|---|
| `-108` | 컨슈머 **수동 커밋**. 완료 조건 "그룹 3종이 독립 오프셋 보유 확인" |
| `-112` | Spark Structured Streaming + **체크포인트** |

`-102` §5 는 이 둘을 충돌로 보고 "체크포인트 단일 기준"과 "관측용 group id
병행" 중 하나를 고르라고 했다.

> **이 절은 C2 를 만들면서 정정됐다.** 처음에는 §5 의 1번을 채택한다고
> 적었다. C2 까지 놓고 보니 **두 티켓은 같은 컨슈머를 말한 것이 아니었다.**
> 고를 문제가 아니라 기록할 구분이었다.

| | 오프셋 위치 | `--describe` | 왜 |
|---|---|:---:|---|
| **C1** Archiver | Spark 체크포인트 | 안 보임 | Parquet 아카이브. Spark 가 맞다 |
| **C2** Extractor | consumer group 수동 커밋 | **보임** | Postgres **upsert**. Spark JDBC sink 는 append 뿐이라 결국 손으로 쓴 SQL 이 된다 |

**메커니즘이 아예 다르므로 진행 독립성이 구조적으로 보장된다.** 그리고
`-108` 의 `--describe` 검사는 **C2 에서 그대로 작동한다** — 죽은 조건이
아니었다.

C1 쪽 결정은 그대로다. 이 골격은 `kafka.group.id` 를 **설정하지 않는다.**
옵션조차 두지 않았고(`test_no_group_id_option_is_offered`), 오프셋이 두 군데
있으면 재기동 시 어느 쪽을 믿을지 규칙이 없어지기 때문이다. `--describe` 에
C1 이 안 보이는 것은 결함이 아니라 의도다.

양방향 되감기 실측은
[`docs/plans/2026-09-10-consumer-group-decision-request.md`](../plans/2026-09-10-consumer-group-decision-request.md) §4 에 있다.

### 1.2 C3 는 어떤 토픽도 구독하지 않는다 (새로 발견)

`-102` §2.3 매트릭스를 그대로 읽으면 C3 Aggregator 의 구독은 세 토픽 모두
`❌` 다. §2.2 도 C3 의 입력을 "C2 가 만든 Fact·정규화 결과"로 적었다.

**따라서 Kafka 컨슈머 그룹은 3개가 아니라 2개다.** `-108` 의 완료 조건
"그룹 **3종**이 독립 오프셋 보유"는 §1.1 이 해소되든 아니든 구조적으로
성립할 수 없다. C3 는 체크포인트도 그룹도 갖지 않는 배치다.

### 1.3 제안하는 완료 조건

> **C1·C2 가 서로의 진행에 영향을 주지 않는다.** 한쪽을 되감아도 다른
> 쪽 위치가 변하지 않음을 확인한다.

C1 은 체크포인트 경로가 `(consumer, topic)` 단위로 분리돼 있고, C2 는 자신의
consumer group 을 갖는다. 두 위치를 각각 따로 확인할 수 있다는 것이 이 문구가
검증 가능한 이유다.

---

## 2. 인프라를 기다리지 않아도 되는 이유

`docs/data/2026-09-10-remaining-work.md` 는 "① 인프라 요청 → ② `-112`" 순서로
적었다. **그 순서는 운영 배포에는 맞지만 개발 착수에는 맞지 않는다.**

운영 브로커(`j15e102`)에는 토픽이 없지만 노트북 브로커에는 3종이 다 있다
(2026-09-10 실측).

```text
github.events    8,840,612 건
jobs.collected           8 건
so.raw                   0 건   ← 발행자 없음 (-145)
```

`github.events` 880만 건이 로컬에 있으므로 C1 골격은 오늘 만들고 검증할 수
있다. ①은 **운영 전환 조건**이지 착수 조건이 아니다.

---

## 3. 설계 결정

### 3.1 토픽마다 쿼리 하나, 체크포인트 하나

`{checkpoint_root}/{consumer}/{topic}` 으로 나눈다.

```text
hdfs:///gitjob/checkpoints/c1/github.events
hdfs:///gitjob/checkpoints/c1/so.raw
```

§1.3 완료 조건을 **관측 가능하게** 만드는 것이 이 분리다. 디렉터리가 나뉘어
있으면 `so.raw` 위치를 유지한 채 `github.events` 만 되감을 수 있고, 각각을
따로 확인할 수 있다. `consumer` 세그먼트가 C1 과 C2 가 같은 토픽을 읽으면서
진행을 공유하지 않게 하는 부분이다.

### 3.2 출력은 Raw 가 아니라 Parquet 아래

```text
hdfs:///gitjob/parquet/stream/{topic}/dt=YYYY-MM-DD/
hdfs:///gitjob/parquet/stream/_rejected/{topic}/
```

`-112` 가 경로를 정하지 않아 **골격 단계의 결정이며 `-110` Sink 소유자 확인이
필요하다.** Raw 아래에 두지 않은 이유는 Raw 가 원본 바이트의 자리이기
때문이다 — GH Archive 의 시간별 gzip 과 수집기 회차 디렉터리가 거기 있고,
`-190` 의 검증이 그 파일 수를 센다. 마이크로배치 Parquet 을 섞으면 그 집계가
깨지고 얻는 것이 없다.

### 3.3 payload 는 열지 않는다

봉투 필드(`-103` §4.1)만 컬럼으로 올리고 `payload` 는 도착한 JSON 문자열
그대로 싣는다. `repo_activity_topn.py` 가 "Raw 계층을 일부러 불투명하게
유지한다"고 적은 것과 같은 선이다. 아카이버가 payload 를 파싱하면 유지할
스키마가 하나 늘고, **저장만 하면 될 데이터에 실패할 이유가 생긴다.**

### 3.4 Kafka offset 을 행에 싣는다

`-102` §2.2 가 C1 의 중복 처리 키를 "event offset 을 경로·metadata 에 포함"
으로 정했다. `kafka_topic`·`kafka_partition`·`kafka_offset` 을 컬럼으로 둬서,
되감기로 같은 이벤트가 두 번 들어와도 쿼리로 제거할 수 있게 한다.

### 3.5 컷오프는 버리지 않고 격리한다

GH Archive 는 `HISTORICAL_CUTOFF = 2026-09-01T00:00:00Z` 이전이 배치 경로,
이후가 Kafka 경로다 (`-102` §2.4). `-144` 완료 조건은 **한 시각이 두 경로로
들어오지 않는 것**이다 — 겹치면 중복, 벌어지면 결번.

그래서 경계를 검사하되 **탈락한 레코드를 조용히 버리지 않고** 사유와 함께
`_rejected/` 에 쓴다. 버리면 "프로듀서의 경계가 우리와 다르다"와 "조용히
성공했다"가 구분되지 않는다. `README.md` §14.1 이 이미 그 실패로 한 번
치렀다.

사유 문자열에 사건 시각과 경계 값이 둘 다 들어간다 — 코드를 읽지 않고도
프로듀서 쪽 경계와 대조할 수 있어야 하기 때문이다.

### 3.6 커넥터 JAR 을 이미지에 굽는다

데이터 노드 실측으로 `/opt/spark/jars` 에 kafka 관련 JAR 이 **없다**.

`--packages` 로 제출 시 받을 수도 있지만, 스트리밍 쿼리는 오래 살고 스스로
재기동한다. 매 재기동을 Maven 도달성에 걸면 **Maven 장애가 C1 정지로
번역된다.** `Infra/docker/spark/Dockerfile` 에서 빌드 시 받고 Maven 이 함께
게시하는 `.sha1` 로 검증한다.

버전은 커넥터 POM 에서 해석한 값이다. `kafka-clients` 는 브로커 버전이 아니라
Spark 의 `<kafka.version>` 을 따르므로 **3.4.1** 이다 (브로커는 4.0.0).

| artifact | 버전 |
|---|---|
| `spark-sql-kafka-0-10_2.12` | 3.5.3 |
| `spark-token-provider-kafka-0-10_2.12` | 3.5.3 |
| `kafka-clients` | 3.4.1 |
| `commons-pool2` | 2.11.1 |

---

## 4. 실행하며 드러난 것 2건

문서만으로는 안 나왔고 실제로 돌려서 나왔다.

### 4.1 `hdfs:///` 를 Spark 체크포인트가 거부한다

```text
IllegalArgumentException: Uri without authority:
hdfs:/gitjob/checkpoints/c1/github.events
```

저장소는 루트를 전부 authority 없는 형태로 쓴다 — `.env.example` 의
`PARQUET_ROOT`·`RAW_ROOT`, `raw_sink.py` 의 `DEFAULT_RAW_ROOT` 가 모두
`hdfs:///gitjob/...` 다. 대부분의 Spark·Hadoop API 는 받아주는데 **Structured
Streaming 체크포인트 리졸버만 거부한다.**

`normalize_location()` 이 authority 없는 스킴을 떼어 내고 bare path 를 넘긴다.
NameNode 주소를 여기 박아 넣지 않은 이유는, 그러면 클러스터 주소가 두 군데
생기고 서로 어긋날 수 있기 때문이다. `spark.hadoop.fs.defaultFS` 가 그 주소가
있어야 할 유일한 자리다.

### 4.2 스키마 추론이 실패한다

```text
PySparkValueError: [CANNOT_DETERMINE_TYPE]
```

`event_id` 가 전부 비어 있는 배치가 오면 Spark 가 그 컬럼의 타입을 정하지
못한다. 추론에 맡기면 **배치 내용에 따라 아카이브 컬럼이 달라진다**는 더 큰
문제도 함께 있어서, `ARCHIVE_COLUMNS`·`REJECTED_COLUMNS` 로 스키마를 선언했다.
행 생성기와 선언이 어긋나지 않는지는 테스트가 지킨다.

---

## 5. 검증 (2026-09-10, 노트북 브로커 실측)

`github.events` 를 `--max-offsets-per-trigger 2000 --once` 로 읽었다.

```text
ROWCOUNT                     85,828
DISTINCT dt                  [2026-09-01]
DISTINCT source              ['gharchive']
OFFSET RANGE                 0 ~ 14,490
DUPLICATE (partition,offset) 0
_rejected/                   없음
```

샘플 1행:

```text
schema_version   '1'
source           'gharchive'
source_id        '2026-09-01T00:00:00Z/14172383030'
event_type       'PullRequestEvent'
event_id         'gharchive-14172383030'
occurred_at      '2026-09-01T00:00:01+00:00'
ingested_at      '2026-09-09T06:04:17.578215+00:00'
kafka_partition  3
kafka_offset     0
dt               '2026-09-01'
payload          {"id": "14172383030", "type": "PullRequestEvent", ...}
```

확인된 것:

| 항목 | 결과 |
|---|---|
| 커넥터 | 이미지에 구운 4종으로 Kafka 읽기 성공 |
| 체크포인트 | `/gitjob/checkpoints/c1/github.events/{offsets,commits}` 생성·커밋 |
| 파티션 | `occurred_at` 기준 `dt=2026-09-01` 로 정확히 분리 |
| 컷오프 | 거부 0건 — 프로듀서 경계와 이 잡의 경계가 일치한다 |
| 중복 | `(partition, offset)` 중복 0 |
| 봉투 | `-103` §4.1 필드가 그대로 컬럼으로 |

**전량 드레인은 하지 않았다.** `availableNow` 는 880만 건을 전부 읽으므로
골격 검증에 필요한 만큼만 돌리고 중지했다. 남은 백로그는 체크포인트에 위치가
남아 있어 이어서 읽는다.

---

## 6. 파일

| 경로 | 내용 |
|---|---|
| `Infra/spark/c1_archiver_stream.py` | 스트리밍 잡. `pyspark` 는 `main()` 안에서 임포트 |
| `Infra/scripts/spark-c1-archiver.sh` | 제출 스크립트. 기본 `--once` |
| `Infra/docker/spark/Dockerfile` | 커넥터 JAR 4종 + sha1 검증 |
| `AI/tests/test_c1_archiver_stream.py` | 봉투·경로·컷오프 규칙 (Spark 불필요) |

`pyspark` 를 함수 안에서 임포트하는 것은 `repo_activity_topn.py` 의 방식이고,
그래서 순수 규칙을 Spark 없이 테스트할 수 있다. `AI/conftest.py` 가
`Infra/spark` 를 경로에 넣는다.

---

## 7. 남은 것

| 항목 | 상태 |
|---|---|
| C2 Extractor 골격 | 별도 MR 로 구현됨 — [`2026-09-10-c2-extractor-skeleton.md`](2026-09-10-c2-extractor-skeleton.md). `jobs.collected` 는 **Claim Check** 라 토픽마다 구현이 다르다 |
| C3 Aggregator | 배치. §1.2 대로 컨슈머가 아니다 |
| 운영 전환 | ①에 종속 — 운영 브로커 토픽 3종 생성 |
| `so.raw` | 발행자 없음 (`-145`). C1 이 구독은 하지만 검증할 데이터가 없다 |
| 출력 경로 확정 | §3.2 는 골격 결정. `-110` Sink 소유자 확인 필요 |
