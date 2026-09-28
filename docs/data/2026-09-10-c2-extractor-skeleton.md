# C2 Extractor 골격 — `-112` 두 번째 컨슈머

> 기준일: 2026-09-10
> 대상: `S15P21E102-112` 컨슈머 골격 중 C2
> 선행: [C1 Archiver 골격](2026-09-10-c1-archiver-skeleton.md)
> 계약: [`2026-09-08-kafka-topic-consumer-matrix-and-envelope.md`](2026-09-08-kafka-topic-consumer-matrix-and-envelope.md)

---

## 1. C2 는 Spark 가 아니다 — C1 과 갈라지는 지점

C1 문서에 `-112` 가 Spark Structured Streaming 을 기재했다고 적었고 C1 은
그대로 했다. **C2 는 하지 않는다.** 취향이 아니라 sink 때문이다.

| 이유 | 내용 |
|---|---|
| 출력이 **upsert** | `-102` §2.2 가 `(source, source_id, dict_version)` upsert 를 요구한다. Spark JDBC sink 는 append 뿐이라 결국 `foreachBatch` + 손으로 쓴 SQL 이 된다. Spark 의 writer 가 주는 게 없다 |
| Claim Check | `jobs.collected` 해석은 **메시지당 HDFS 읽기**다. 컬럼 스캔이 아니다 |
| 판정이 순수 Python | `registry.mapper`·`job.collector.technology` 가 Registry 를 들고 있다. executor 에서 돌리면 레지스트리 데이터를 매 잡마다 실어 보내고 거기서 버전 관리도 해야 한다 |
| 이미 있다 | `-121` 이 `common.kafka.ConsumerTransport` 를 며칠 전에 넣었다. 수동 커밋과 DLQ 까지 같은 모양의 작업용이다 |

### 1.1 이게 `-108`·`-112` 충돌을 해소한다

C1 문서 §1.1 은 이 충돌을 "`-102` §5 의 1번을 채택"으로 처리했다. C2 까지 놓고
보면 **애초에 충돌이 아니었다.**

| | 오프셋 | `-108` `--describe` |
|---|---|---|
| C1 Archiver | Spark 체크포인트 | 보이지 않음 (의도) |
| C2 Extractor | consumer group 수동 커밋 | **보인다** |

`-108` 은 수동 커밋을, `-112` 는 체크포인트를 적었는데 **둘은 같은 컨슈머를
말한 게 아니다.** C1 은 체크포인트로 아카이브하고 C2 는 커밋된 그룹으로
upsert 한다. 서로 다른 메커니즘이라 진행이 독립인 것은 구조적으로 보장된다.

C1 문서 §1.2 의 발견(**C3 는 어떤 토픽도 구독하지 않는다**)은 그대로다.
컨슈머 그룹은 2개다.

---

## 2. 한 메시지가 한 레코드가 아니다

균일한 파이프를 만들면 안 되는 이유가 여기 있다.

| 토픽 | 한 메시지는 | 해석 |
|---|---|---|
| `github.events` | 이벤트 하나 | payload 가 곧 레코드 |
| `so.raw` | 포스트 하나 | payload 가 곧 레코드 |
| `jobs.collected` | **수집 회차 하나** | Claim Check — HDFS 에서 배치를 읽어 공고 전부로 팬아웃 |

`-103` §4.3 이 `jobs.collected` 를 Claim Check 봉투로 정했다. 봉투에는
`run_path`·`files`·`record_count` 만 있고 공고는 없다. **오늘 사람인 회차
528건이 메시지 1건이다.** 이걸 레코드 하나로 다루면 하루치 수집 전체에 대해
fact 하나를 쓰게 된다.

### 2.1 중복 제거 키는 봉투의 것이 아니라 레코드의 것이다

`-103` §4.2 는 `worknet`·`saramin` 의 `source_id` 를 **`pipeline_run_id`** 로
정했다. 그건 *회차*다. fact 의 `source_id` 는 공고의 `source_record_id` 여야
한다 — 봉투 것을 쓰면 회차 안 모든 공고가 키 하나로 뭉갠다.

`MessageOrigin.envelope_source_id` 에 회차를 따로 남겨 추적은 유지한다.

---

## 3. AI팀과의 이음매

`-102` §2.2 가 C2 를 둘로 나눴다 — 골격은 A조, **판정 로직은 AI팀**.
`contracts.ExtractionSeam` 이 그 경계를 코드로 적은 것이다.

```python
class ExtractionSeam(Protocol):
    def extract(self, record: ResolvedRecord) -> Sequence[FactRecord]: ...
```

이음매 앞은 이 패키지(전송·해석·저장), 뒤는 **레코드가 무엇을 뜻하는지**
정하는 쪽이다. 기존 구현 `registry.mapper.RegistryMapper` 와
`job.collector.technology.extract_technology_mentions` 를 받을 수 있는 모양으로
맞췄다.

**fact 0건은 실패가 아니다.** 기술 신호가 없는 GH Archive 이벤트가 정상이고
흔하다.

---

## 4. 저장소는 Protocol 이고 테이블이 아니다

`FactStore` 를 Protocol 로 뒀다. 스키마는 BE 의 Flyway
(`BE/src/main/resources/db/migration`)에 있고 **C2 출력용 테이블은 아직
없다.** 여기서 DDL 을 만들면 BE 스키마에 소유자가 둘이 된다. 테이블 합의는
이 골격과 별개 단계다.

`upsert()` 는 **호출 단위로 원자적**이어야 한다. 메시지가 커밋 단위이므로
저장 단위도 메시지여야 한다 — 쪼개면 크래시가 오프셋을 반쯤 쓴 메시지 뒤에
남기고 재시도가 이중 기록한다.

---

## 5. 커밋 순서 — 잃느냐 막히느냐

규칙은 `-121` 것이고 이유도 같다.

| 상황 | 커밋 | 근거 |
|---|:---:|---|
| 정상 처리 | ✅ 저장 **후** | 먼저 커밋하면 작업 중 죽었을 때 메시지가 사라진다 |
| fact 0건 | ✅ | 실패가 아니다 |
| **영구 실패** | ✅ + DLQ | 커밋 안 하면 파티션이 영원히 막힌다 |
| **일시 실패** | ❌ | NameNode 순단이 수집 회차를 잃게 하면 안 된다. 공고는 다시 못 받는다 |

`ResolutionError` 와 `UnusableMessage` 를 나눈 것이 이 표다. 봉투가 깨진
것은 몇 번을 다시 줘도 안 되고, NameNode 가 잠깐 죽은 것은 다음에 된다.

**한 폴에 재시도가 하나라도 있으면 그 폴 전체를 커밋하지 않는다.** 배치를
커밋하면 재시도 요청 메시지를 지나치기 때문이다. 이미 처리한 것이 다시 와도
upsert 키가 있어 replace 가 된다.

---

## 6. Claim Check 자체의 실패 모드

포인터와 데이터가 어긋나는 것이 이 패턴이 들여오는 유일한 새 위험이다.
`-103` §4.3 이 봉투에 `record_count` 를 넣어 뒀으므로 공짜로 검사한다.

```
UnusableMessage: .../job_analysis_input.json holds 1 records but the envelope
declared 9; the Claim Check and its batch disagree
```

이 검사가 없으면 잘린 업로드가 **더 작은 회차로 조용히 추출된다.** 뭔가
빠졌다는 신호가 어디에도 남지 않는다.

---

## 7. 검증

`test_extractor_resolve.py` 26건 · `test_extractor_consumer.py` 14건.
Spark 도 브로커도 DB 도 없이 돈다 — 가짜 전송으로 구동한다.

고정한 것:

| 항목 | 테스트 |
|---|---|
| 회차 1건 → 공고 N건 팬아웃 | `test_a_collection_run_fans_out_to_every_posting` |
| 키가 회차가 아니라 공고 | `test_the_fact_key_is_the_posting_not_the_run` |
| 건수 불일치 거부 | `test_a_count_mismatch_is_refused` |
| 0건 회차는 정상 | `test_an_empty_run_resolves_to_nothing_without_failing` |
| NameNode 순단은 재시도 | `test_an_unreachable_namenode_is_retryable_not_fatal` |
| 영구 실패는 커밋+DLQ | `test_an_unusable_message_is_committed_so_the_partition_moves` |
| 재시도 1건이 폴 전체 커밋을 막음 | `test_one_retry_holds_the_commit_for_the_whole_poll` |
| 메시지 하나가 upsert 한 번 | `test_the_whole_message_is_one_upsert_call` |

`python -m extractor --dry-run` 은 **저장도 커밋도 하지 않고 실제로 해석만**
한다 — Claim Check 의 HDFS 읽기 포함. AI팀 판정과 BE 테이블이 생기기 전에
A조 몫을 확인하는 방법이다.

### 7.1 실측 (2026-09-10, 노트북 브로커 + 운영 HDFS)

수집기 컨테이너 안에서 `jobs.collected` 전량을 dry-run 했다. 봉투는 노트북
브로커에서, 배치는 **운영 HDFS** 에서 읽었다.

```text
{"topic": "jobs.collected", "dry_run": true,
 "outcomes": {"EXTRACTED": 8}, "distinct_fact_keys": 9371}
```

**메시지 8건이 공고 9,371건으로 팬아웃했다.** §2 가 말한 그대로다 — 이걸
레코드 하나씩으로 다뤘다면 fact 가 8개 나왔을 것이다.

거부 0건이므로 8건 모두 봉투가 `-103` §4.1 을 만족했고 `record_count` 가
배치와 일치했다. 운영 HDFS 의 채용공고 총계는 회차 11건 15,537건인데,
`jobs.collected` 에 봉투가 있는 것은 8건뿐이다 — 나머지는 발행 경로가 붙기
전에 수집된 회차다.

`distinct_fact_keys` 가 봉투가 가리킨 공고 수보다 작으면 `(source,
source_id, dict_version)` 중복이 있었다는 뜻이고, 그게 upsert 가 하는 일이다.

**호스트에서는 재현되지 않는다.** `localhost:9094` 는 TCP 로는 열리는데
`kafka-python` 부트스트랩이 실패한다(브로커 4.0.0). 컨테이너 안 `kafka:9092`
로는 정상이며, 배포 형태도 그쪽이다.

---

## 8. 의존과 남은 것

**이 브랜치는 `-189`(WebHDFS 적재 대상 수정)에 의존한다.** Claim Check 읽기가
클러스터 밖에서 이뤄지면 `WEBHDFS_DATANODE_HOSTS` 재작성이 필요하다.
`-189` MR 이 먼저 머지돼야 한다.

| 항목 | 상태 |
|---|---|
| 판정 로직 | **AI팀.** 이음매는 준비됨 |
| fact 테이블 DDL | **BE 합의 필요.** §4 |
| C3 Aggregator | 배치. 컨슈머가 아니다 |
| 운영 전환 | 운영 브로커 토픽 3종 생성에 종속 |
| `so.raw` | 발행자 없음(`-145`). 구독은 하지만 검증할 데이터가 없다 |
| DLQ 토픽 | `KAFKA_TOPIC_EXTRACTOR_DLQ` 를 읽지만 아직 선언되지 않았다. `-121` 의 `gitjob.repository-analysis.dlq.v1` 과 payload 가 달라 섞으면 안 된다 |
