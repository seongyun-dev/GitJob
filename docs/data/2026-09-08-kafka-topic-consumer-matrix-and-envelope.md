# Kafka 토픽×컨슈머 매트릭스 · 메시지 봉투 스키마

> 상태: **AI팀 합의 대기 초안** — 확정 전
>
> 기준일: 2026-09-08
>
> Jira: `S15P21E102-102`(매트릭스) · `S15P21E102-103`(봉투 스키마) · 명세 AF2
>
> 조 밖 창구: 정민아 (A조)
>
> 후행: `-108`(토픽 생성) · `-144`(GH Archive 신규) · `-145`(SO 신규 Q/A) · `-112`(컨슈머 3종) · `-146`(API 명세)

두 티켓을 한 회의에서 끝내기 위한 초안이다. **아직 확정이 아니다.** §7 체크리스트에 AI팀 확인이 들어가야 `-108`이 착수된다.

## 1. 채용공고를 Kafka에 넣는다 — 지금은 빠져 있다

**이 절은 사전 지식을 가정하지 않는다.** 아래 "현재 상태"를 처음 듣는 사람이 있을 수 있고, 그렇다면 그 자체가 이 회의에서 가장 먼저 다뤄야 할 일이다.

### 1.0 현재 상태 — 채용공고는 Kafka를 타지 않는다

08-31 회의에서 `jobs.raw` 폐기가 결정됐고, **오늘 코드가 실제로 그렇게 되어 있다.**

- `AI/job/collector/raw_sink.py`가 수집 결과를 `/gitjob/raw/{source}/dt=YYYY-MM-DD/{pipeline_run_id}/`에 WebHDFS로 직접 올린다 (`-107` MR !36)
- 경로 규칙과 전송 방식은 `-110`이 확정한 것을 재사용했다
- `-99` 완료 조건에도 "Snapshot을 HDFS/Parquet에 직접 적재 **(Kafka 미사용)**"으로 박혀 있다

이 결정이 팀에 충분히 전달되지 않았을 가능성이 있다. 그렇다면 **매트릭스를 논의하기 전에 이것부터 맞춰야 한다.** 서로 다른 그림을 들고 파티션 수를 정하면 되돌릴 수 없는 값이 잘못 고정된다.

### 1.1 이미 병합됐다 — 회의는 사후 확인이다

이 문서를 초안으로 쓴 뒤, **`jobs.collected` 구현이 `24d7837`로 develop 에 병합됐다**
(`[S15P21E102-103] data: jobs.collected 봉투 및 Producer 구현`).

| | 08-31 결정 | 현재 develop |
|---|---|---|
| 채용공고 | Kafka 미사용, HDFS 직행 | **Kafka 사용** (`jobs.collected`) |
| 토픽 수 | 2종 | **3종** |

**순서가 뒤집혔다.** 계약을 회의에서 확정한 뒤 구현하려던 것이 반대로 됐으므로,
이 안건은 "제안을 받아들일지"가 아니라 **"이미 들어간 것을 유지할지"** 다.

되돌리려면 develop 에 병합된 코드를 되돌려야 한다. 유지한다면 아래 §1.5 문구 정리만
남는다. **어느 쪽이든 회의에서 명시적으로 확인하고 넘어가야 한다** — 확인 없이 지나가면
"코드가 먼저 들어갔으니 그게 계약"이라는 상태가 기록 없이 굳는다.

### 1.2 무엇을 흘려보내는가 — Claim Check

**공고 원문은 Kafka에 넣지 않는다.** HDFS에 그대로 두고, Kafka에는 "어느 run이 어디에 몇 건 쌓였다"는 **수집 완료 사실만** 발행한다.

```text
수집기 ──→ HDFS Raw          (raw_sink.py 그대로 유지)
   │        /gitjob/raw/{source}/dt=.../{pipeline_run_id}/
   │
   └──→ Kafka  jobs.collected
             payload = { pipeline_run_id, run_path, record_count, ... }
                 │
                 ▼
          C2 Extractor  ── 이벤트를 받고 HDFS에서 원문을 읽는다
```

### 1.3 왜 원문이 아니라 이벤트인가

| 근거 | 내용 |
|---|---|
| 이미 구현된 적재를 버리지 않는다 | `raw_sink.py`가 `-110` 경로 규칙으로 WebHDFS 적재를 끝냈다. 원문을 Kafka로 옮기면 이 코드를 걷어내고 C1이 다시 써야 한다 (`-107` MR !36 구조 변경) |
| 브로커 용량 | `retention.ms=-1`이 설계 근거인데, 원문을 넣으면 공고가 영구 누적된다. 이벤트만이면 회차당 1건 |
| 대용량 왕복 없음 | 백필 1회 4,800건이 메시지 4,800건이 아니라 **1건**이 된다 |
| 순서 보장 단위가 맞다 | 공고 개별 순서는 의미가 없다. 의미 있는 순서는 **회차 순서**이고, 이벤트가 정확히 그 단위다 |

### 1.4 그래서 무엇이 좋아지는가

채용공고를 Kafka에서 뺀 대가가 이미 드러나 있다.

- **채용공고 분석을 당길 방법이 없다.** `-81`/`-82`의 `job/classifier.py`가 수집 결과를 처리하는데, 지금은 **사람이 손으로 돌려야** 한다. 트리거가 없다
- **적재 결과를 아무도 모른다.** `raw_sink`가 실패해도 로컬 이력에만 남는다. 오늘 백필이 로컬에만 쌓이고 업로드를 따로 해야 하는 상황이 그 예다
- **소비자 추가가 불가능하다.** 수요 집계·품질 검사가 붙으려면 각자 HDFS를 폴링해야 한다

`jobs.collected`가 생기면 셋 다 이벤트 구독으로 풀린다.

### 1.5 함께 정리할 문구

제안을 받아들이면 문서 두 곳의 문구가 어긋난다. 회의에서 함께 정리한다.

| 위치 | 현재 문구 | 조치 |
|---|---|---|
| `-99` 완료 조건 | "Snapshot을 HDFS/Parquet에 직접 적재 **(Kafka 미사용)**" | `-99`는 이미 완료. **적재 방식은 유지**되므로 완료 상태는 그대로 두고, 이벤트 발행이 추가됐음을 코멘트로 남긴다 |
| `-102` 작업 내용 | "채용공고가 Kafka 경로에서 **제외되는** 근거 명시" | 이 문서로 대체. 제외 근거가 아니라 **포함 방식**을 기재 |

## 2. `-102` 토픽 × 컨슈머 그룹 매트릭스

### 2.1 토픽 3종

| 토픽 | 프로듀서 | 실리는 것 | 유입 |
|---|---|---|---|
| `github.events` | `-144` GH Archive 신규 감시 | **원문** event | 시간당 1회 배치 발행 |
| `so.raw` | `-145` SO 신규 Q/A 수집 | **원문** 질문·답변·tag | 일 단위, 최대 10,000/day |
| `jobs.collected` | `-107` 수집 스케줄러 | **메타데이터**(Claim Check) | 회차당 1건, 하루 4건 |

**이름이 다른 것은 의도적이다.** 앞 둘은 원문이 실리고 `jobs.collected`는 사실만 실린다. `jobs.raw`로 부르면 원문이 들어 있다고 오해한다.

`so.raw`는 08-31에 예약 해제 → 실제 토픽으로 승격됐다.

### 2.1.1 이 세 종이 브로커의 전부가 아니다 — `-121`이 토픽을 추가했다

`S15P21E102-121`(저장소 분석 요청 API와 Outbox CDC 발행, develop `f147f07`)이
BE 쪽 토픽을 하나 만들었다. 이 문서 초안을 쓴 뒤에 들어왔다.

| 토픽 | 주인 | 용도 |
|---|---|---|
| `gitjob.repository-analysis.requests.v1` | BE (`-121`) | 저장소 분석 요청. `analysis_outbox` → Debezium CDC |
| `gitjob.connect.configs` · `.offsets` · `.status` | Debezium Connect | Connect 내부 상태 |

`ANALYSIS_OUTBOX_MODE=CDC`가 기본이므로 Connect 내부 토픽 3종도 같은 브로커에 생긴다.
**즉 실제 토픽 수는 수집 3종 + BE 1종 + Connect 3종이다.**

그리고 provisional 4종이 **여전히 `.env.example`에 남아 있다.**

```text
KAFKA_TOPIC_SOURCE_EVENTS=gitjob.source.events
KAFKA_TOPIC_ANALYSIS_REQUESTS=gitjob.analysis.requests
KAFKA_TOPIC_ANALYSIS_RESULTS=gitjob.analysis.results
KAFKA_TOPIC_ANALYSIS_DLQ=gitjob.analysis.dlq
```

`-121`은 새 이름을 추가했을 뿐 이 넷을 지우지 않았다. `gitjob.analysis.requests`와
`gitjob.repository-analysis.requests.v1`이 같은 목적으로 동시에 선언되어 있다.

**명명 규칙이 세 갈래로 갈렸다.**

| 형태 | 예 | 출처 |
|---|---|---|
| prefix 없음, 버전 없음 | `github.events` · `so.raw` | `docs/data/README.md` §4 논리 계약 |
| `gitjob.` prefix, 버전 없음 | `gitjob.source.events` | provisional |
| `gitjob.` prefix + `.v1` | `gitjob.repository-analysis.requests.v1` | `-121` |

토픽 이름은 파티션 수처럼 나중에 바꾸기 어렵다. 컨슈머 설정과 운영 문서가 전부 이름을
참조하기 때문이다. **이 회의에서 규칙을 하나로 정한다** (§7-③).

### 2.2 컨슈머 그룹 3종

`docs/data/README.md` §4의 C1/C2/C3를 승계한다.

| 그룹 | 역할 | 중복 처리 키 | 소유 |
|---|---|---|---|
| C1 Archiver | raw event를 HDFS/Parquet에 적재 | event offset을 경로·metadata에 포함 | A조 (`-112` 골격, `-110` Sink) |
| C2 Extractor | 기술·요구사항·Fact·Registry mapping | `(source, source_id, dict_version)` upsert | **판정 로직 AI팀**, 골격 A조 |
| C3 Aggregator | 월/분기 trend·수요·Pain 집계 | `(tech_id, period)` Snapshot replace/upsert | **판정 로직 AI팀**, 골격 A조 |

### 2.3 매트릭스

| | `github.events` | `so.raw` | `jobs.collected` |
|---|:---:|:---:|:---:|
| **C1 Archiver** | ✅ 구독 | ✅ 구독 | ❌ |
| **C2 Extractor** | ✅ 구독 | ✅ 구독 | ✅ 구독 |
| **C3 Aggregator** | ❌ | ❌ | ❌ |

**C1이 `jobs.collected`를 구독하지 않는 이유**: 적재가 이미 끝난 뒤에 발행되는 이벤트다. C1이 다시 적재하면 같은 파일을 두 번 쓴다.

**C3는 어떤 토픽도 직접 구독하지 않는다.** C2가 만든 Fact·정규화 결과를 입력으로 집계한다. 원본 event를 다시 읽어 집계하면 C2의 Registry 판정과 어긋나고 `registry_version`이 결과에 남지 않는다.

**C1과 C2는 같은 토픽을 독립 오프셋으로 소비한다.** C2(추출)가 죽어도 C1(적재)이 계속 돌아야 한다는 것이 `-112`의 완료 조건이다.

### 2.4 Kafka를 거치지 않는 경로

**소스 단위로 갈리는 것이 아니라 과거분/신규분으로 갈린다.** 이 절을 소스별 목록으로
읽으면 GH Archive 와 Stack Overflow 가 Kafka 를 쓰지 않는 것으로 오해된다. 둘 다 쓴다.

| 소스 | 과거분 | 신규분 |
|---|---|---|
| GH Archive | HDFS 직행 (`-105` **완료**) | **Kafka `github.events`** (`-144`) |
| Stack Overflow | HDFS 직행 (`-113`) | **Kafka `so.raw`** (`-145`) |
| 채용공고 | — (소급 수집 불가) | **Kafka `jobs.collected`** (`-103` 병합됨) |

`historical_cutoff = 2026-09-01T00:00:00Z` 가 GH Archive 두 경로의 경계다. `-144` 의
완료 조건이 **"같은 시각 데이터가 HDFS(과거분)와 Kafka(신규분)로 이중 유입되지 않음"**
이며, 겹치면 중복이고 벌어지면 결번이다.

과거분이 HDFS 직행인 이유는 소스 때문이 아니라 §1.1 원칙 셋이 하나도 성립하지 않기
때문이다 — 1회성 처리, 소비자 하나(Spark), 파일이 이미 다 있어 속도 차이 없음.
10.85 GiB 를 브로커에 왕복시킬 이득이 없다.

Kafka 를 아예 거치지 않는 것은 다음이다.

| 항목 | 경로 | 이유 |
|---|---|---|
| Repo Snapshot (`-114`) | HDFS `analysis_input` | A조가 Batch로 publish, C조가 read |
| 분석 Job 요청/결과 | BE 소유 (`-121`) | §2.1.1 |

## 3. 파티션 수 — 오늘 결정해야 한다

**`-108`이 토픽을 만드는 순간 고정된다.** 나중에 늘리면 키 해싱이 바뀌어 순서 보장 근거가 깨진다.

### 3.1 실측 유입량

`-105` 744시간 실측이다.

| 지표 | 값 |
|---|---:|
| 월 전체 event | 87,516,869 |
| 시간당 평균 event | 117,630 |
| 평균 hourly 압축 | 15,664,534 B |
| **최대 hourly** | **76,972,242 B** (`2026-08-07-17`) |
| 최소 hourly | 824,873 B |
| 최대/최소 | **93.3배** |

최대 시간대를 평균 대비로 환산하면 **한 시간에 약 578,000 event가 한 번에 발행**된다. `-144`가 hourly 파일 단위로 밀어 넣으므로 유입이 평탄하지 않고 **버스트**다.

`so.raw`는 최대 10,000/day, `jobs.collected`는 **하루 4건**이다.

### 3.2 제안

| 토픽 | 파티션 | 메시지 키 | 근거 |
|---|---:|---|---|
| `github.events` | **6** | repo id | 578k burst를 병렬 소비할 여지. 지금 Spark worker가 2 core라 다 못 쓰지만 파티션은 못 늘린다 |
| `so.raw` | **3** | post id | 일 10,000건. 6은 과잉 |
| `jobs.collected` | **3** | `source_site` | 하루 4건이라 1이면 충분하지만, **같은 사이트 회차의 순서 보장**을 키로 얻으려면 최소 사이트 수만큼 필요하다. 사이트가 늘 수 있어 3 |
| `gitjob.repository-analysis.requests.v1` | **미정** | — | **`-121` 소유. 이 문서가 정하지 않는다.** `-108`이 생성 대상에 포함하는지, BE가 자체 생성하는지부터 확인해야 한다 |

`jobs.collected`의 3은 A안(Claim Check) 기준이다. 키가 `source_site`라 파티션을 늘려도
사이트 수만큼만 쓴다. **원문을 싣는 B안으로 정하면 키가 레코드별이 되므로 6이 맞다** —
분산이 고르게 되고 컨슈머 확장 여지가 생긴다. 설계 결정이 파티션 수를 정한다.

Notion 초안은 `posts.raw` 6 / `jobs.raw`·`repos.raw` 3이었다. **그 6은 SO 전체 Dump가 Kafka를 통과한다는 전제**였다. Dump가 HDFS 직행으로 빠지면서 부하 프로파일이 뒤집혔고, 이제 큰 쪽은 `github.events`다.

현재 data node 실측은 4 vCPU / Spark worker 2 core·2 GiB다. 파티션을 늘려도 지금 소비 병렬도 상한은 2다. 그래도 6을 제안하는 이유는 **확장이 불가능한 방향**이기 때문이다.

> **결정 필요**: 6 / 3 / 3으로 확정할지.

## 4. `-103` 메시지 봉투 스키마

### 4.1 공통 필드

`docs/data/README.md` §4의 envelope를 기준으로 한다. **세 토픽이 같은 봉투를 쓴다.**

| 필드 | 타입 | 필수 | 의미 |
|---|---|:---:|---|
| `schema_version` | string | ✅ | 봉투 구조 버전. 변경 시 올리고 consumer가 구버전을 명시적으로 처리 |
| `source` | string | ✅ | `gharchive` · `stackexchange` · `worknet` · `saramin` |
| `source_id` | string | ✅ | 원천 식별자. `(source, source_id, schema_version)`이 중복 제거 키 |
| `event_type` | string | ✅ | 원천 event 종류 |
| `occurred_at` | RFC3339 | ✅ | **원천에서 사건이 일어난 시각** |
| `ingested_at` | RFC3339 | ✅ | **우리 시스템이 수집한 시각** |
| `payload` | object | ✅ | 토픽별 본문 |
| `event_id` | string | 권장 | 단독 중복 제거 키 |
| `trace_id` | string | 권장 | 운영 로그 연결 |

Token·비밀번호·불필요한 개인정보는 `payload`에 넣지 않는다.

### 4.2 source별 매핑

| source | `occurred_at` | `source_id` | `payload` |
|---|---|---|---|
| `gharchive` | event의 **`created_at`** | hourly 파일 + event id | 원문 event |
| `stackexchange` | 질문/답변 생성 시각 | post id | 원문 post |
| `worknet` · `saramin` | 회차 **수집 완료 시각** | `pipeline_run_id` | §4.3 |

GH Archive `created_at`을 `occurred_at`으로 쓰는 것이 `-103` 티켓에 명시된 결정이다.

### 4.3 `jobs.collected` payload

`-107`이 이미 만드는 값을 그대로 싣는다. **새로 계산하는 값이 없다.**

```json
{
  "event_id": "jobs-WORKNET-20260908T003000Z",
  "schema_version": "1",
  "source": "worknet",
  "source_id": "WORKNET-20260908T003000Z",
  "event_type": "job.collection.completed",
  "occurred_at": "2026-09-08T00:32:14Z",
  "ingested_at": "2026-09-08T00:32:15Z",
  "trace_id": "tr_9c2e11",
  "payload": {
    "run_name": "worknet-morning",
    "site": "WORKNET",
    "pipeline_run_id": "WORKNET-20260908T003000Z",
    "collector_version": "worknet-v1",
    "record_count": 158,
    "status": "SUCCESS",
    "run_path": "hdfs:///gitjob/raw/worknet/dt=2026-09-08/WORKNET-20260908T003000Z",
    "files": [
      "hdfs:///gitjob/raw/worknet/dt=2026-09-08/WORKNET-20260908T003000Z/job_analysis_input.json",
      "hdfs:///gitjob/raw/worknet/dt=2026-09-08/WORKNET-20260908T003000Z/postings.csv",
      "hdfs:///gitjob/raw/worknet/dt=2026-09-08/WORKNET-20260908T003000Z/manifest.json"
    ]
  }
}
```

출처는 전부 기존 구조다.

- `run_name` · `site` · `status` · `record_count` · `pipeline_run_id` → `schedule.py`의 `RunRecord`
- `run_path` · `files` → `raw_sink.py`의 `RawUploadResult` (`run_path`, `uploaded`, `unchanged`)
- `record_count` → 배치의 `records` 길이

### 4.4 발행 규칙

| 상황 | 동작 |
|---|---|
| 적재 성공 (`RawUploadResult.ok`) | 발행 |
| **적재 실패** | **발행하지 않는다.** C2가 없는 파일을 읽으러 간다. 실패는 `-107`의 이력·알림이 이미 처리한다 |
| 발행 실패 | **수집·적재는 유지한다.** 예외를 던지지 않는다. 공고는 이미 쌓였고 그 이력을 잃는 것이 더 나쁘다 — `-107`의 알림 발송 실패 처리와 같은 원칙 |
| 같은 run 재실행 | `event_id = "jobs-" + pipeline_run_id`가 같으므로 C2가 중복 제거한다. `raw_sink`가 같은 경로를 `unchanged`로 처리하는 것과 짝이 맞는다 |
| SUCCESS_EMPTY 회차 (0건) | 발행한다. record_count: 0. 0건도 사실이며, 결번과 구분되어야 한다 |

### 4.5 왜 두 시각을 나누는가

**리플레이 지연을 측정하기 위해서다.**

`ingested_at - occurred_at`이 원천 공개 지연 + 우리 폴링 주기의 합이다. 이 값이 없으면 `-144`의 폴링 주기가 적절한지 판단할 근거가 사라진다. 하나로 합치면 재처리할 때 **과거 event가 방금 일어난 것처럼 보인다.**

`-112`의 late event 처리와 watermark도 `occurred_at` 기준이어야 한다.

### 4.6 검증

`-103` 완료 조건이 "샘플 메시지 검증 통과"다. 합성 데이터를 쓰지 않아도 된다.

- `github.events` — `-105`가 받아둔 실제 event. HDFS `/gitjob/raw/gharchive/dt=2026-08-01/`
- `jobs.collected` — 오늘 백필 run의 실제 `manifest.json`과 `raw_upload.json`

> **결정 필요**: 봉투를 JSON Schema + Pydantic으로 고정할지. `-90`·`-80`·`-157`이 모두 그 방식이고 `-146` API 명세에 실린다.

## 5. 티켓 간 충돌 1건 — 오프셋 관리 주체

**티켓 두 개가 서로 다른 것을 말한다.**

| 티켓 | 기재 |
|---|---|
| `-108` | "컨슈머 **수동 커밋** 설정" / 완료 조건 "그룹 3종이 **독립 오프셋 보유** 확인" |
| `-112` | 08-31 정정: 단순 Kafka Consumer + 수동 커밋 → **Spark Structured Streaming + 체크포인트** |

Spark Structured Streaming은 **오프셋을 자체 체크포인트에서 관리하고 Kafka consumer group에 커밋하지 않는다.** 그러면 `-108` 완료 조건을 `--describe`로 확인할 수 없다.

1. **체크포인트를 단일 기준으로 삼는다.** `-108` 완료 조건을 "그룹 3종이 서로의 진행에 영향을 주지 않음"으로 바꾸고 체크포인트 경로 분리로 검증한다
2. Spark의 `kafka.group.id`로 관측용 오프셋을 남긴다. 단 **관측용이지 복구 기준이 아니다.** 두 기준이 공존하면 재기동 시 어느 쪽을 믿는지 모호해진다

> **결정 필요**: 1번을 권한다. 2번은 "오프셋이 두 군데 있다"는 상태를 만든다.

## 6. `-108`에 넘길 설정값

이 회의 결과가 그대로 내일 `-108` 입력이 된다.

| 항목 | 값 | 출처 |
|---|---|---|
| 토픽 | `github.events` · `so.raw` · `jobs.collected` **3종** | §2.1 |
| 파티션 | 6 / 3 / 3 (제안) | §3.2 |
| `retention.ms` | `-1` (무기한) | `-108` 티켓 |
| `cleanup.policy` | `delete` | `-108` 티켓 — **되감기가 설계 근거** |
| 프로듀서 | 멱등성 활성화 | `-108` 티켓 |
| 오프셋 | §5 결정에 따름 | — |

`compact`가 아니라 `delete`인 것은 특정 시점으로 되감아 다시 읽는 것이 복구 절차이기 때문이다.

## 7. AI팀 확인 체크리스트

`-102` 완료 조건이 "매트릭스 문서 확정, **AI팀 확인 완료**"다.

- [ ] ① §1.1 — **`jobs.collected`가 `24d7837`로 이미 병합된 것을 확인**했고, 되돌리지 않고 유지하는 데 동의
- [ ] ② §1.1 — Claim Check(원문은 HDFS, Kafka는 메타데이터)에 동의
- [ ] ③ §2.1.1 — **토픽 명명 규칙을 하나로 확정**한다. 세 갈래(`github.events` / `gitjob.source.events` / `gitjob.repository-analysis.requests.v1`)가 공존한다
- [ ] ③-1 §2.1.1 — provisional 4종(`gitjob.source.events`·`gitjob.analysis.*`)을 **`.env.example`에서 제거할지**. `-121`이 같은 목적의 새 이름을 추가했는데 옛 이름이 남아 있다
- [ ] ③-2 §3.2 — `gitjob.repository-analysis.requests.v1`의 파티션 수와 **생성 주체**(`-108`인지 BE인지). Connect 내부 토픽 3종도 같은 브로커에 생긴다
- [ ] ④ §2.3 — C1은 `jobs.collected` 미구독, C3는 C2 출력만 소비에 동의
- [ ] ⑤ §3.2 — 파티션 6 / 3 / 3 확정
- [ ] ⑥ §4.1·4.3 — 봉투 필드와 `jobs.collected` payload 확정
- [ ] ⑦ §4.4 — 적재 실패 시 미발행, 발행 실패 시 수집 유지 원칙에 동의
- [ ] ⑧ §5 — 오프셋 관리 주체 (체크포인트 단일 기준 권장)
- [ ] ⑨ C2 판정 로직 인터페이스 — AI팀 삽입 지점. **로직 미도착 시 `-112`는 통과 처리로 진행**

```text
AI팀 확인:            /  일자:
A조 확인: 정민아      /  일자: 2026-09-__
```

## 8. 확정 후 파급

| 티켓 | 기한 | 받는 것 |
|---|---|---|
| `-108` | 09-09 | 토픽 3종·파티션·retention·오프셋 방침 |
| **`-107`** | 열림 (MR !36) | **`jobs.collected` producer 추가가 신규 작업으로 붙는다.** 아직 미구현 — §9 |
| `-144` | 09-10 | 봉투 스키마, `github.events` 발행 대상. 커서 경계는 `-105`의 `historical_cutoff` |
| `-145` | 차단 중 | 봉투 스키마, `so.raw`. `-113`의 `dump_snapshot_at` 대기 |
| `-112` | 09-11 | 구독 대상 3종, 그룹 3종, 오프셋 방침 |
| `-146` | 다음 주 | 봉투 스키마가 API 명세에 실림 |

## 9. 구현 상태

이 문서는 계약이며, 아래는 오늘 기준 실제 코드 상태다.

### 구현됨 (로컬 검증)

| 파일 | 역할 |
|---|---|
| `AI/common/events.py` | §4.1 봉투. 세 토픽 공용 |
| `AI/common/kafka.py` | Producer 경계. `KafkaTransport` Protocol + `kafka-python` 어댑터 |
| `AI/job/collector/events.py` | `jobs.collected` 조립·발행, §4.4 규칙 |
| `AI/job/collector/__main__.py` | 이력 기록 후 `_announce()` 호출 |
| `AI/tests/test_collection_events.py` | 17건 |

`AI/` 전체 **585 passed**, Ruff check·format 통과. 테스트는 fake transport만 쓰므로
브로커도 `kafka-python`도 없이 돈다.

`kafka-python==3.0.11`을 `AI/requirements.txt`에 추가했다. 순수 Python이라
`python:3.12-slim-bookworm` 이미지에 컴파일러 없이 들어간다. import는 실제 발행
시점까지 지연되므로, 패키지가 없는 체크아웃에서도 나머지 경로는 전부 동작한다.

### 미검증

- **실제 브로커로 발행해본 적이 없다.** 토픽이 아직 없다 (`-108`, 내일)
- `enable_idempotence=True`가 `kafka-python` 3.0.11에서 받는 인자인지 실호출로 확인되지 않았다
- C2가 `jobs.collected`를 구독하는 코드가 없다 (`-112`)

### 병합 상태

`-107`(MR !36)은 `3a50925`로, producer 는 `24d7837`로 **둘 다 develop 에 병합됐다.**
`-103` 티켓은 `Closes`로 닫혔다.

다만 `-103` 완료 조건은 "스키마 확정, **샘플 메시지 검증 통과**"이고, 토픽이 아직
0개이므로 실제 검증은 남아 있다. `-108` 직후 1회 발행으로 확인한다.

## 10. 출처

- [데이터 플랫폼·파이프라인 문서](README.md) §4 Kafka 이벤트 계약
- [GH Archive Historical 실측](README.md#14-gh-archive-historical-시간별-덤프-수집) — 744시간 / 87,516,869 events
- Jira 의존 사슬: `S15P21E102-102`·`S15P21E102-103`·`S15P21E102-108`·`S15P21E102-112`
- `AI/job/collector/raw_sink.py` · `AI/job/collector/schedule.py` — payload 출처 (`-107`)
