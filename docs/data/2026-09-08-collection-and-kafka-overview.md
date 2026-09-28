# 수집 현황과 Kafka 사용 근거

> 상태: 2026-09-08 실측 기준 현황 정리
>
> 기준일: 2026-09-08
>
> 확인 방법: HDFS NameNode 직접 조회, 로컬 산출물 카운트, 저장소 코드 검사.
> 문서에서 인용한 값은 출처를 표기했다.

> **2026-09-08 저녁 갱신.** 이 문서를 쓴 뒤 상태가 바뀐 항목이 있어 해당
> 위치를 각각 표시했다. 요약과 저녁 시점 전체 그림은
> [수집 파이프라인과 Kafka — 팀 브리핑](2026-09-08-collection-kafka-briefing.md)에 있다.
>
> - `jobs.collected` **토픽 생성**(파티션 3) 및 **메시지 1건 발행 검증** (§1.6)
> - 채용공고 A안으로 구현 확정. B안 구현체 삭제 (§1.4)
> - 게임잡 수집 산출물 22건, **HDFS 적재 확인** (§3.3, §5.2)
> - §4.4 커서 결함이 **실제로 발생**해 사람인 백필 2,287건 소실

## 0. 한 장 요약

| 축 | 상태 |
|---|---|
| 수집기 | **6종** (채용 4 · GH Archive 1 · GitHub Repo 1), 총 약 8,200줄 |
| GitHub 공급측 | GH Archive 8,751만 event · Repo 활동 571만 · Repo Snapshot **13,410건** |
| 채용 수요측 | 워크넷 **4,631건** · 사람인 15건 · 게임잡 22건(저녁) |
| Stack Overflow | **0건** — `-113` 미완 |
| Kafka | 브로커 online. `jobs.collected` **생성·발행 검증됨**(저녁). 나머지 토픽·파티션 미확정 |

---

# Part 1. Kafka를 쓰는 이유

## 1.1 원칙 한 줄

**"계속 유입 + 여러 소비자 + 생산·소비 속도 차이"가 동시에 성립할 때만 Kafka를 쓴다.**

하나라도 빠지면 Kafka는 값을 주지 않고 홉만 하나 늘린다. GitJob에서 셋이 다 성립하는 것은 **GH Archive 신규 hourly**와 **Stack Overflow 신규 Q/A**다.

## 1.2 성립하는 이유 넷

### (1) 한 데이터를 여러 소비자가 각자 읽는다

```
github.events ──┬──→ C1 Archiver   HDFS/Parquet 적재
                └──→ C2 Extractor  기술 추출 · Registry 판정
```

두 컨슈머 그룹이 **같은 스트림을 서로 다른 오프셋으로** 소비한다. `-112`의 완료 조건이 이것을 요구한다 — "추출 컨슈머 강제 종료 시 적재·집계가 계속 동작".

Kafka가 없으면 각 소비자가 HDFS를 폴링하고 "어디까지 읽었는지"를 각자 관리해야 한다. 소비자를 추가할 때마다 그 로직이 반복된다.

### (2) 생산 속도와 소비 속도가 다르다

`-105` 744시간 실측이다.

| 지표 | 값 |
|---|---:|
| 월 전체 event | 87,516,869 |
| 시간당 평균 | 117,630 |
| **최대 hourly** | 76,972,242 B (평균의 4.9배) |
| 최대 시간대 환산 event | **약 578,000** |

소비측은 data node의 Spark worker **2 core 1대**다. 생산이 훨씬 빠르므로 Kafka가 없으면 생산을 막거나 넘치는 것을 버려야 한다. Kafka는 버스트를 받아두고 컨슈머가 자기 속도로 당겨가게 한다.

### (3) 되감아 다시 처리할 수 있다

`-108`이 `retention.ms=-1` · `cleanup.policy=delete`를 쓰는 이유이며, 티켓에 "되감기가 설계 근거"로 적혀 있다. `github.events`만 2026-09-17부터 `retention.ms=86400000`(24h)이라 되감기 범위가 24시간으로 제한된다(`S15P21E102-258`). 나머지 topic은 `-1` 그대로다.

**오늘 실제 사례가 나왔다.** Registry v1에 `linux`·`sql`·`aws`가 없어 기술 멘션 1,047건 중 **420건(40.1%)이 `UNKNOWN`으로 떨어진다**(§4.1). Registry를 고치면 이미 들어온 이벤트를 다시 판정해야 하는데, 원본 재수집 없이 오프셋만 되감으면 된다.

### (4) 장애가 번지지 않는다

컨슈머 하나가 죽어도 오프셋이 각자이므로 나머지가 계속 돌고, 재기동 시 중단 지점부터 이어받는다.

## 1.3 Kafka를 쓰지 않는 곳과 그 근거

| 데이터 | 경로 | 근거 |
|---|---|---|
| GH Archive **과거** 744시간 | HDFS 직행 | **1회성** 부트스트랩. 순서 보장도 replay도 불필요. 10.85 GiB를 브로커에 왕복시킬 이득이 없다. `-105`가 약 18분에 완료 |
| Stack Overflow **공식 Dump** | HDFS 직행 | 위와 같음 (`-113`) |
| Repo Snapshot (`-114`) | HDFS `analysis_input` | A조가 Batch로 publish, C조가 read |
| 채용공고 원문 | **미확정** | §1.4 |

**과거분 744시간이 원칙의 반례가 아니라 적용례다.** 한 번만 처리하고, 소비자가 Spark 하나고, 파일이 이미 다 있어 속도 차이가 없다. 셋 중 하나도 성립하지 않으므로 Kafka를 쓰지 않는다.

## 1.4 채용공고 — 미확정 (A안 / B안)

두 방향을 구현해두고 결정을 기다리는 상태다.

| | A안 `jobs.collected` | B안 `jobs.raw` |
|---|---|---|
| 회차당 메시지 | **1건** | 레코드 수 + 1건 |
| 4,631건 백필이면 | **1건** | **4,632건** |
| 공고 본문 | HDFS 에만 | Kafka payload 에 |
| `occurred_at` | 회차 완료 시각 | **공고 등록일** |
| 근거 | 08-31 `jobs.raw` 폐기 결정을 되돌리는 제안 | 현재 `docs/data/README.md` §3·§4 |
| 구현 | **채택.** `-103`으로 develop 머지(`24d7837`) | ~~`AI/job/collector/event_sink.py`~~ 저녁에 삭제 |

§1.1 원칙을 적용하면 채용공고는 셋 중 어느 것도 뚜렷하게 성립하지 않는다.

- 유입: 하루 2~4회 배치, 약 600건/일 — GH Archive 대비 네 자릿수 적음
- 소비자: 실시간 소비자가 **없다.** 기술 추출(`-81`/`-82`)과 수요 집계 모두 배치
- 속도 차이: 없음

또한 채용공고는 **가변 상태의 주기적 스냅샷**이지 append-only 이벤트가 아니다. 같은 공고가 수정되면 새 `content_hash`로 다시 관측된다. `cleanup.policy=delete`는 상태성 데이터에 맞는 정책이 아니다.

반면 **회차 완료**는 한 번 일어나면 불변이고 순서가 의미 있는 진짜 이벤트다. A안이 싣는 것이 그것이다.

**단, 문서가 아직 B안을 말한다.** `docs/data/README.md` §3이 채용공고를 `jobs.raw`에 배정하고 있어, A안으로 가려면 그 문서를 함께 고쳐야 한다. 회의 결정 사항이다.

> **저녁 갱신.** 구현은 A안으로 굳었다 — B안 구현체를 삭제하고 `jobs.collected`
> 토픽을 만들었다. `docs/data/README.md` §3은 게임잡 행만 고쳤고 워크넷·사람인
> 행은 아직 `jobs.raw`다. **회의 확인은 여전히 남아 있다**(`-102` 체크리스트 9개
> 미체크). 파티션 3은 되돌리기 어려우므로 그 항목부터 확인받는 것이 좋다.

## 1.5 Kafka가 주지 않는 것

- **저장소가 아니다.** 원본의 기준은 HDFS다. Kafka는 전달 경로다
- **멱등성을 공짜로 주지 않는다.** `event_id` 또는 `(source, source_id, schema_version)`으로 **컨슈머가** 중복을 제거해야 한다. `-103` 봉투에 그 필드가 있는 이유다
- **exactly-once가 아니다.** at-least-once + 멱등 sink 조합으로 만든다. C1/C2/C3 각각에 중복 처리 키가 정의되어 있다

## 1.6 현재 브로커 상태

2026-09-08 실측(Kafka UI API).

```json
{"name":"gitjob","status":"online","brokerCount":1,
 "topicCount":0,"onlinePartitionCount":0}
```

~~**브로커는 떠 있고 토픽은 0개다.**~~ `-108`이 생성 예정이며, 파티션 수는 생성 시점에 고정되어 이후 변경 시 키 해싱이 바뀐다.

> **저녁 갱신.** `jobs.collected`를 생성했다 — 파티션 3, `retention.ms=-1`,
> `cleanup.policy=delete`. `-102` §3.2 표를 그대로 따랐다.
>
> `github.events`·`so.raw`는 **일부러 만들지 않았다.** 파티션 확정 체크박스
> (`- [ ] ⑤ 파티션 6/3/3 확정`)가 열려 있고, 파티션은 줄일 수 없다.
>
> 발행도 검증했다. 적재가 끝난 게임잡 회차를 재료로 크롤링 요청 0건으로
> 메시지 1건을 넣고 브로커에서 꺼내 확인했다. 키는 `gamejob`,
> 공고 18건이 메시지 1건이다(Claim Check 동작 확인).

---

# Part 2. 수집기 인벤토리

## 2.1 채용공고 수집기 4종

전부 `job-analysis-input/v1` 계약(`-90`)으로 출력하고, 계약 매핑은 `-99`의 `job/collector/normalize.py`에 위임한다.

| 수집기 | Jira | 줄 수 | 상태 | 특징 |
|---|---|---:|---|---|
| `Worknet_Collector_V1` | `-148` | 1,543 | 운영 | 공공데이터. 직종 코드 서버측 필터. 요청 간격 1.0초 |
| `Saramin_Collector_V1` | `-148` | 1,230 | 운영 | robots.txt 허용 팝업 경로만 요청. 요청 간격 2.0초 |
| `JobKorea_Collector_V1` | `-159` | 2,277 | 임시 | PaddleOCR 이미지 공고 인식, Streamlit GUI 포함 |
| `GameJob_Collector_V1` | — | 1,644 | **미결** | §5.2 |

### 공용 계층 (`-99`)

```
AI/job/collector/
├── interface.py    ListingRow · PostingDetail · SiteCollector
├── normalize.py    계약 매핑 (body_status · content_hash · posting_status)
├── technology.py   기술 추출 (RULE_BASED_V1)
├── html_tree.py    표준 라이브러리 기반 HTML 트리
├── http.py         요청 간격 · 지수 백오프 3회 · 차단 감지
├── raw_sink.py     HDFS Raw 적재 (WebHDFS)
├── schedule.py     스케줄 · 실행 이력 · 결번 감지 · 차단 계측 · 알림
└── __main__.py     CLI
```

외부 파싱 의존성이 없다. 표준 라이브러리와 `pydantic`만 사용한다.

## 2.2 GH Archive 수집기

| 항목 | 값 |
|---|---|
| 위치 | `AI/collector/gharchive` (1,468줄) |
| Jira | `-105` |
| source | `data.gharchive.org` 시간 단위 `.json.gz` |
| 적재 | WebHDFS (`WebHdfsSink`). Hadoop CLI 어댑터는 대안으로 유지 |
| 특징 | `.part` 임시 파일 → Content-Length·gzip CRC 검증 통과 후 `os.replace`. checkpoint 재개, 결번(`missing_hours`)과 손상(`invalid_archives`) 분리 집계 |

## 2.3 GitHub Repo 수집기

| 파일 | Jira | 역할 |
|---|---|---|
| `github/client.py` | `-150` | 인증 REST + 비인증 raw, retry, rate-limit 헤더 |
| `github/repo_fetch_policy.py` | `-150` | Tree entry 필터, deterministic Artifact 선택 |
| `github/repo_fetch_store.py` | `-150` | immutable Artifact, cross-period Cache, checkpoint |
| `github/repo_fetch_orchestrator.py` | `-150` | metadata → pinned Commit → Tree → manifest/source |
| `github/repo_snapshot_bootstrap.py` | `-114` | Top-N 장기 배치, 진행률·ETA, Rate Limit wait/resume |
| `github/repo_fetch_benchmark.py` | `-104` | 비용 실측 |
| `github/root_manifest_probe.py` | `-104` | Tree 대안 PoC (REST core 0회) |

---

# Part 3. 실제 수집된 데이터

## 3.1 HDFS 실측 (2026-09-08 NameNode 직접 조회)

```text
/gitjob/raw/gharchive                          31 partitions (dt=2026-08-01 ~ 08-31)
/gitjob/raw/worknet                             1 partition  (dt=2026-09-08)
/gitjob/parquet/github/repo_activity
/gitjob/parquet/github/repo_activity_weekly
/gitjob/analysis_input/github/repo_snapshot/    4 snapshots
```

NameNode 상태: Live DataNode 1 / Dead 0, **13,071 files · 5,856 blocks · 11.45 GiB / 308.9 GiB**.

## 3.2 GitHub 공급측

| Dataset | 규모 | 출처 |
|---|---|---|
| GH Archive Raw 2026-08 | **744 files · 87,516,869 events · 10.85 GiB** | `-105` |
| Repo Activity 집계 | **5,711,133 unique repos**. Top-20,000 valid coverage 24.5638% | `-109` |
| **Repo Snapshot Phase 1** | **records 13,410** — COMPLETE 13,101 · PARTIAL 291 · FAILED 18, **Artifact 4,876개** | `-114` (오늘 실측) |
| Repo Snapshot canary | 3 snapshots (`-114` ×2, `-163` ×1) | `-114`, `-163` |

`snapshot_id=s15p21e102-114-phase1-20260907-fix-001`이 실제로 존재하며 `snapshot.json` 12.5MB다. **개별 저장소의 manifest·source Artifact가 확보된 상태다.**

## 3.3 채용 수요측

| Source | 수집 | 범위 | HDFS |
|---|---:|---|---|
| **워크넷** | **4,631건** | 2026-07-10 ~ 09-08 (60일) | **적재 완료** `dt=2026-09-08` |
| 사람인 | 15건 | 2026-09-06 ~ 09-07 | 미적재 (로컬만) |
| 잡코리아 | 0건 | — | — |
| 게임잡 | **22건**(저녁) | 2026-07-01 ~ 09-08 | **적재 완료** `dt=2026-09-08` |

### 워크넷 백필 상세 (2026-09-08)

```
pipeline_run_id   WORKNET-20260908T003203Z
records           4,631        pages_read 95
invalid           0            detail_errors 0
body_status       TEXT_AVAILABLE 4,628 · PARSE_FAILED 3
기술 멘션         1,047건 / 50종
종료              page 95 — no rows, listing exhausted (상한·차단 아님)
소요              약 2시간 29분
크기              22MB (job_analysis_input.json 20.5MB)
```

등록일 분포: 2026-07 **616건** · 2026-08 **2,772건** · 2026-09 **1,243건**.
7월이 적은 것은 워크넷 보존 한계(약 2개월)로 보인다.

HDFS 적재 검증: read-back SHA-256 **3/3 일치**, 재실행 시 전부 `unchanged`(멱등성 확인).

### 기술 수요 상위 (MATCHED 기준)

```
java 170 · cpp 102 · csharp 90 · python 86 · react 32
dotnet 23 · docker 19 · postgresql 16 · javascript 16 · spring-boot 16
```

요구유형: `MENTIONED` 459 · `PREFERRED` 394 · `REQUIRED` 194.

## 3.4 Stack Overflow

**0건.** `-113`(공식 Dump 입수)이 미완이며 그것이 `-145`(신규 Q/A → `so.raw`)를 막고 있다.
요구사항에서 `SO-RAG-001`은 **필수 기능**이지만 corpus가 없어 구현이 불가능한 상태다.

---

# Part 4. 확인된 결함과 한계

## 4.1 Registry v1 누락 — 40.1% 유실

워크넷 4,631건에 `-81` Mapper를 실제 실행한 결과다.

```
기술 멘션 1,047건
  MATCHED   627
  UNKNOWN   420   ← 40.1%, 고유 40종
```

상위: `linux` 69 · `sql` 42 · `aws` 34 · `git` 29 · `html` 28 · `rest-api` 27 · `oracle` 24 · `mysql` 20 · `php` 19 · `spring` 18.

**두 종류다.** canonical 자체가 없는 경우와, canonical은 있는데 표기를 못 잡는 경우(`react.js` → `react`, `nextjs`, `vuejs`, `nodejs`). 후자는 같은 기술이 반쪽만 잡혀 **집계가 조용히 틀어진다.**

`spring-boot`은 등록돼 있으나 **`spring`이 없다.**

담당: `-143`.

## 4.2 기술 Coverage 8.5%

```
기술 멘션이 있는 공고  394 / 4,631  (8.5%)
```

`-94` 기준 B가 "Coverage < 60%면 제외 후보"인데 **워크넷 자체가 크게 못 미친다.** 잡코리아를 30%로 제외한 기준과 대조된다.

4,631을 단일 분모로 쓰면 모든 기술 점유율이 하향 왜곡된다. source별 분모 분리는 `-146` 범위다.

## 4.3 직무 축이 없다 — 핵심 기능 차단

```
raw_job_category      0 / 4,631  (0.0%)
career_level       4,629 / 4,631  (100%) — 그중 4,579건이 그냥 "경력"
region             1,475 / 4,631  (31.9%)
```

**워크넷 레코드에 직무 값이 하나도 없다.** 그런데 제품의 핵심이 목표 직무별 수요 비교(`JOB-DMD-001`, `job_demand_snapshot`)다.

원인은 워크넷 파서만 `raw_job_category`를 채우지 않는 것이다. 계약·인터페이스·정규화·분류기 배선은 모두 되어 있고, 나머지 3개 수집기는 채운다.

```
사람인      parser.py:106   _job_sector(item)
잡코리아    parser.py:385   raw_category
게임잡      parser.py:180   _listing_job_category(anchor)
워크넷      ──              없음
```

실제 상세 페이지에는 값이 있다 — `모집 직종: IT개발·데이터`(2026-09-08 확인).

**다만 이것만으로는 부족하다.** 사람인은 `백엔드/서버개발, 데이터엔지니어, AI(인공지능), 클라우드, API`처럼 5개 태그를 주는데 워크넷은 대분류 하나다. `raw_job_category` → 제품 `job_role` 매핑은 별도 분석 단계이며 粒度 차이를 흡수해야 한다.

## 4.4 스케줄러 커서 결함 (장시간 실행)

`schedule.py`의 커서는 **페이지마다** 저장되지만 레코드 본문은 크롤 완료 후 한 번에 쓰인다. 장시간 실행이 중간에 죽으면 데이터는 사라지고 커서에는 수집됨으로 남아, 재실행 시 그 공고가 영구히 건너뛰어진다.

하루 2회 짧은 회차에서는 드러나지 않는다. 중단 시 재실행 전에 커서를 지워야 한다.

> **저녁 갱신 — 실제로 발생했다.** 사람인 백필(2개월 창, `--max-pages 100`)이
> 46/100 페이지에서 **2,287건**을 모은 상태로 전원 종료를 만나 전부 소실됐다.
> 커서에는 수집됨으로 남아 있어서 격리했다
> (`data/saramin/backfill-cursor.ABANDONED-20260908T221512.json`).
>
> `schedule.py`가 아니라 각 수집기의 문제다 — `cursor.save()`는 페이지마다,
> `write_outputs()`는 `run()` 종료 후 한 번이다. 워크넷·사람인·게임잡 전부
> 같은 구조다. 티켓이 필요하다.

## 4.5 티켓 간 충돌 2건

| 충돌 | 내용 |
|---|---|
| `-108` ↔ `-112` | `-108`은 "수동 커밋 + 그룹 3종 독립 오프셋", `-112`는 Spark Structured Streaming. **Spark SS는 consumer group에 커밋하지 않아** `-108` 완료조건을 `--describe`로 확인할 수 없다 |
| 토픽 명명 | `github.events`(논리 계약) · `gitjob.source.events`(provisional) · `gitjob.repository-analysis.requests.v1`(`-121`) 세 갈래 공존. provisional 4종이 `.env.example`에 그대로 남아 있다 |

---

# Part 5. 채용 source 심사 결과

## 5.1 기준 A 적용 결과

`-94` §4 기준 A: **정식 수집 경로가 없거나 판례·약관상 금지되면 Coverage와 무관하게 제외.** A는 B·C보다 상위다.

| 후보 | 기준 A | 근거 |
|---|---|---|
| 워크넷 | **통과** | 공공데이터 |
| 사람인 | **통과** | 오픈 API + robots.txt 허용 경로 |
| 잡코리아 | 미통과 | 판례·소송, robots.txt가 공고 상세 금지 |
| 게임잡 | 미통과 | 운영사가 잡코리아와 **동일 법인**(웍스피어, 사업자등록번호 110-81-34859) |
| 링커리어 | 미통과 | 이용약관 제20조가 크롤링·스크래핑 명시 금지 |
| 자소설닷컴 | 판정 불가 | 약관 페이지가 SPA라 본문 확인 불가 |
| 공공데이터 채용 API | **통과** | 재정경제부, 이용허락범위 제한 없음. 단 기준 B 의심 |

상세 근거는 [채용 source 후보 기준 A 심사 기록](2026-09-08-source-criterion-a-review.md).

## 5.2 게임잡 수집기의 위치

수집기 코드가 존재한다(`AI/GameJob_Collector_V1`, 브랜치
`data/S15P21E102-171-gamejob-collector`, Jira `-171`).

> **저녁 갱신.** 산출물이 생겼다 — 22건(1일 범위 4건 + 2개월 백필 18건),
> HDFS 적재 확인. `schedule.toml`에서 `enabled = false`이고 회귀 테스트가
> 이를 고정한다(`test_gamejob_is_declared_but_never_scheduled`). 켜는 전제는
> 웍스피어와의 데이터 제공 계약이다.
>
> 목록 실측: `?Page=N`이 무시되어 80페이지가 3,200행을 돌려주는데 고유 공고는
> **40건**이다. 이 경로로 얻을 수 있는 전부다.

**§5.1 판정과 어긋난다.** 팀이 `-94`에서 잡코리아를 적법성으로 제외했고 게임잡은 같은 법인이 운영하므로, 사용 여부는 팀 결정 사항으로 남아 있다. 이 문서는 코드 존재와 판정 상태를 함께 기록하는 데 그친다.

---

# 부록. 재현 명령

```bash
# 채용공고 수집
python -m Worknet_Collector_V1 --occupation-preset dev --days-back 1
python -m Saramin_Collector_V1 --category-preset dev --days-back 1

# 스케줄러
python -m job.collector --render cron     # crontab 줄 생성
python -m job.collector --run worknet-morning
python -m job.collector --check           # 결번 점검
python -m job.collector --blocks          # 최근 7일 차단

# Registry 유실 재현
PYTHONPATH=AI python -c "
from pathlib import Path
from job.contracts import JobAnalysisInputBatch
from job.classifier import classify_job_batch
from registry.contracts import load_registry
from registry.mapper import RegistryMapper
reg = load_registry(Path('AI/registry/data/technology_registry_v1.json'), repository_root=Path('.'))
batch = JobAnalysisInputBatch.model_validate_json(
    Path('data/worknet/WORKNET-20260908T003203Z/job_analysis_input.json').read_text(encoding='utf-8'))
out = classify_job_batch(batch, RegistryMapper(reg))
print(sum(1 for r in out.records for t in r.technologies if str(t.match_status)=='UNKNOWN'))
"

# HDFS 현황
curl -s "http://100.70.66.38:9870/webhdfs/v1/gitjob/raw?op=LISTSTATUS&user.name=hadoop"

# Kafka 브로커 상태
curl -s "http://100.71.215.74:8082/api/clusters"

# 테스트
python -m pytest AI/tests -q
```

## 관련 문서

- [데이터 플랫폼·파이프라인](README.md) — §3 수집 대상, §4 Kafka 계약
- [Kafka 토픽×컨슈머 매트릭스·봉투 스키마](2026-09-08-kafka-topic-consumer-matrix-and-envelope.md) — 합의 대기 초안
- [채용 source 후보 기준 A 심사 기록](2026-09-08-source-criterion-a-review.md)
- [GH Archive Historical 실측](README.md#14-gh-archive-historical-시간별-덤프-수집) — `-105`
- [Repo Activity Top-N 검증](2026-09-02-repo-activity-topn-validation.md) — `-109`
- [Repo Snapshot 부트스트랩 배치](2026-09-04-repo-snapshot-bootstrap-batch.md) — `-114`
