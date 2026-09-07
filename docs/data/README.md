# 데이터 플랫폼·파이프라인 문서

> 상태: 수집·저장·정규화·품질 설계 기준
>
> 기준일: 2026-08-28

## 1. 데이터 원칙

GitJob의 데이터는 “화면에 빠르게 보여줄 서비스 데이터”와 “다시 처리할 수 있는 원본·장기 이력”을 분리한다.

| 계층 | 저장 대상 | 기준 저장소 |
|---|---|---|
| Service | 사용자, 분석 실행, Evidence, Registry, 정규화 공고, 집계·추천 Snapshot | PostgreSQL |
| Raw/History | 원본 payload, Stack Exchange dump, 장기 분석 이력, Parquet | HDFS / Parquet |
| Event | 수집·분석 요청/결과·재처리 event | Kafka |
| Cache/Session | 세션, 조회 cache, 작업 보조 상태 | Redis |

PostgreSQL은 raw 본문 전체를 대체하지 않는다. HDFS/Parquet dataset의 `location`, `version`, `checksum`, `rowCount`와 처리 결과를 기록해 결과에서 원본까지 역추적할 수 있게 한다.

공통 조인 키는 표준 기술 식별자 `tech_id`와 판정 기준 `registry_version`이다. 표시 이름·alias를 직접 조인 키로 사용하지 않는다.

## 2. 데이터 흐름

```text
외부 source
  ├─ Worknet / Saramin job posting
  ├─ GitHub repository·activity
  └─ Stack Exchange API / dump
          ↓
       Collector
          ↓ raw event
        Kafka
          ├─ C1 Archiver → HDFS/Parquet
          ├─ C2 Extractor/Normalizer → Fact·정규화 DB
          └─ C3 Aggregator → demand·trend·pain Snapshot
                          ↓
                 PostgreSQL Service API
```

분석 실행은 별도 `analysis.requested` 계열 event로 시작한다. Worker가 저장소별 Commit을 기준으로 수집·파싱·Registry 판정을 실행하고, 결과 event와 품질 결과를 남긴다.

## 3. 수집 대상과 주기

| Source | 수집 데이터 | 기준 주기/한도 | 저장 topic/layer |
|---|---|---|---|
| Worknet | 목록·상세 채용공고 | 일 단위, 명목 1,000건; 상세 호출 budget 때문에 실효량은 500건 미만일 수 있음 | `jobs.raw` |
| Saramin | 승인된 채용공고 | 일 단위 수집 초안 | `jobs.raw` |
| GitHub | 사용자가 권한을 부여한 public/private 저장소 개발 활동·저장소 기술 신호 | 일 단위, API quota 내 최대 5,000/hour 기준 | `repos.raw` |
| Stack Exchange API | 질문·답변·tag 신호 | 주 단위, 최대 10,000/day 기준 | `posts.raw` |
| Stack Exchange dump | Posts·Tags·PostLinks | 최신 dump 확인 후 batch intake | Parquet → replay |

실제 호출 전에는 source별 API 약관·권한·rate limit·보관 정책을 확인한다. 사용자가 권한을 부여한 public/private 저장소 분석과 공개 기술 추세 수집을 분리하고, private 원문은 시장 Trend나 다른 사용자의 AI 입력에 넣지 않으며, 권한 없는 데이터를 수집하지 않는다.

## 4. Kafka 이벤트 계약

### 공통 envelope

모든 raw/event 메시지는 다음 필드를 기준으로 한다.

```json
{
  "event_id": "ev_7712",
  "schema_version": "1",
  "source": "github",
  "source_id": "repo:octocat/gitjob-api:commit:9c1e2f0",
  "event_type": "repository.commit.collected",
  "occurred_at": "2026-08-27T03:30:00Z",
  "ingested_at": "2026-08-27T03:30:02Z",
  "trace_id": "tr_8f21ac",
  "payload": {}
}
```

- `event_id` 또는 `(source, source_id, schema_version)`로 중복을 제거한다.
- `occurred_at`은 source 이벤트 시간, `ingested_at`은 우리 시스템 수집 시간이다.
- Token·비밀번호·불필요한 원본 개인정보는 payload에 넣지 않는다.
- schema 변경은 version을 올리고 consumer가 구버전을 명시적으로 처리한다.

### Topic과 consumer

Notion 데이터 파이프라인 초안의 논리 topic은 `posts.raw`, `jobs.raw`, `repos.raw`이며 posts는 6 partition, jobs/repos는 3 partition을 기준으로 한다. retention은 장기 보관과 cleanup 정책을 별도로 정하고, 삭제가 필요한 임시 topic은 명시적으로 정리한다.

| Consumer | 역할 | 중복 처리 |
|---|---|---|
| C1 Archiver | raw event를 HDFS/Parquet에 적재 | event offset을 경로·metadata에 포함 |
| C2 Extractor | 기술·요구사항·Fact·Registry mapping | `(source, source_id, dict_version)` upsert |
| C3 Aggregator | 월/분기 trend, 수요, Pain 집계 | `(tech_id, period)` Snapshot replace/upsert |

현재 `Infra/.env.example`의 `gitjob.source.events`, `gitjob.analysis.requests`, `gitjob.analysis.results`, `gitjob.analysis.dlq`는 애플리케이션 코드가 들어오기 전의 provisional topic이다. 최종 topic명·partition·retention·consumer group은 위 논리 계약과 맞춰 확정한다.

## 5. Stack Exchange dump 처리

대규모 Stack Exchange 데이터는 API 호출 대신 dump를 받을 수 있다.

1. 최신 collection과 checksum/`Hashes.md`를 확인한다.
2. 필요한 `Posts`, `Tags`, `PostLinks`만 다운로드한다.
3. `PostHistory`, `Votes`는 MVP에서 다운로드하지 않는 기준이다.
4. XML을 메모리에 한 번에 올리지 않고 line-by-line으로 파싱한다.
5. HTML body에서 code block과 일반 본문을 분리하고 escape를 처리한다.
6. `ParentId`를 기준으로 질문·답변을 left join한다.
7. 날짜·tag·source 기준으로 Parquet partition을 만들고 row count를 검증한다.
8. `occurred_at` watermark와 checksum을 기록한 뒤 필요 시 Kafka로 replay한다.

Replay는 checkpoint와 속도 모드(slow/normal/fast)를 지원하고, 작은 10,000건 데이터셋으로 먼저 검증한다. 업로드하지 않은 dump라도 provenance와 처리 버전은 남긴다.

## 6. 채용공고 정규화

채용공고는 raw 보존과 정규화 결과를 분리한다.

```text
raw body
  → 본문 상태 판정
  → 필드 정규화
  → duplicate group
  → INCLUDED / EXCLUDED / REVIEW_REQUIRED
  → 기술 후보 추출
  → Technology Registry mapping
  → REQUIRED / PREFERRED / SKILL 분류
  → job demand Snapshot
```

본문 상태는 `TEXT_AVAILABLE`, `IMAGE_ONLY`, `BLOCKED`, `MISSING`, `PARSE_FAILED`로 구분한다. 권한 없는 OCR을 수행하지 않고, 정규화할 수 없는 값은 null과 사유를 보존한다.

중복 공고는 대표 공고와 duplicate group을 기록한다. 현재 유효하지 않은 공고는 수요 집계에서 제외하되 과거 Snapshot 재현을 위해 삭제하지 않는다. 기술 후보가 제목에서만 발견된 경우 `TITLE_ONLY` 상태를 남긴다.

## 7. Technology Registry

Registry는 기술의 canonical record와 변형 표현을 관리한다.

구현 가능한 v1 필드·정규화·버전 계약과 초기 Seed는 [Technology Registry v1 계약](2026-09-01-technology-registry-v1.md)을 따른다.

| 구성 | 예시 |
|---|---|
| canonical key | `tech_id=apache-kafka` |
| display name | Apache Kafka |
| approved mapping | `ALIAS=Kafka`, `STACKOVERFLOW_TAG=apache-kafka` |
| category | `BACKEND`, `AI_DATA`, `INFRASTRUCTURE` |
| status | `ACTIVE`, `DEPRECATED` |
| version | `registry_version` |

`REQUIRED`, `PREFERRED`, `SKILL`, `REVIEW_REQUIRED`는 Registry 필드가 아니라 `S15P21E102-82`가 담당하는 채용공고 후보의 후속 요구조건 분류다. 정확한 alias/package/tag match를 우선하고, 모호하거나 처음 보는 표현은 조회 결과 `AMBIGUOUS`/`UNKNOWN`으로 판정해 `S15P21E102-88`의 별도 review queue에 보낸다. AI가 Registry 항목을 자동 확정하지 않는다. Registry 변경 시 새 버전을 발행하고 소비 결과에 사용 버전을 기록하며, provenance source 검증 자체는 배포 승인을 뜻하지 않는다. 승인 manifest·artifact hash·배포와 Replay 정책은 `S15P21E102-143`에서 결정한다.

## 8. GitHub 분석 데이터

분석 실행마다 저장소별 기준 Commit과 parser/registry 버전을 고정한다.

```text
analysis_run
  └─ analysis_repository
       ├─ repoFullName / github_repo_id
       ├─ commitSha
       ├─ collection status / error
       ├─ raw dataset artifact
       └─ Fact / Evidence result
```

Evidence에는 기술·파일·라인·Commit permalink·matched rule·contribution label을 남긴다. Bot, merge, fork base, generated, format-only noise는 제외 사유를 남겨 판정과 재현에 사용한다.

GitHub 공개 활동 추세는 GitHub Innovation Graph KR의 분기 Programming Languages `num_pushers`를 MVP 지표로 사용한다. 사용자 private 저장소의 원문·활동은 이 집계에 포함하지 않는다. Topic 지표는 연속 수집이 보장될 때만 사용하며, 누락 기간은 보간하지 않고 `NO_DATA`로 표시한다.

## 9. 출처별 집계

| 신호 | 단위 | 기간 예시 | 주의점 |
|---|---|---|---|
| 채용 수요 | 공고 건수·비율 | 월/선택 기간 | 표본·분모·지역·직무를 공개 |
| GitHub 활동 | 분기별 `num_pushers` | 분기 | 개인 활동·star·인기도로 해석하지 않음 |
| Stack Overflow | 질문 수·share·unanswered·accepted | 월/Corpus 기간 | 질문 수를 난이도로 표현하지 않음 |

서로 다른 출처를 weighted score로 합치지 않는다. API와 화면은 source, unit, granularity, period, snapshotAt, denominator을 분리해 전달한다.

## 10. 품질·Lineage·재처리

각 pipeline run은 다음 결과를 남긴다.

- 처리 시작/종료, source, worker 수, parser/registry version
- 입력·출력 row count와 duplicate count
- missing/parse failure/late event count
- checksum, dataset location, partition, offset/checkpoint
- 품질 통과 여부와 경고
- 실패 event와 DLQ 위치

재처리 초안(`S15P21E102-143` 확정 전):

1. consumer는 수동 commit과 checkpoint를 사용한다.
2. 일시적 외부 오류는 backoff와 최대 retry 후 DLQ로 보낸다.
3. Registry만 바뀌면 raw 재수집 없이 C2 replay 후보로 기록하고, 실행 승인·범위는 `S15P21E102-143` 정책을 따른다.
4. 전체 사용자 분석 재실행은 새 analysis Snapshot과 이력을 만든다.
5. C1/C3를 멈추지 않고 가능한 consumer만 rewind한다.
6. 결과에서 `GET /api/v1/analyses/{analysisId}/lineage`로 dataset·event·quality를 역추적한다.

## 11. 성능·복원력 검증

비교 실험은 고정된 dataset hash와 동일한 parser/embedding/cooccurrence 조건으로 수행한다.

| 실험축 | 값 |
|---|---|
| worker 수 | 1 / 2 / 4 |
| Kafka partition | 1 / 3 / 6 |
| volume | 1 / 2 / 4 |
| 반복 | protocol warmup 후 3회, median 기록 |
| 기록 | 처리량, p50/p95, end-to-end 지연, lag, error/retry, resource, Spark version, worker 수, dataset hash |

회복 시나리오는 consumer rewind, worker kill/restart, 외부 quota 대기, 중복 event, late event, DLQ replay를 포함한다.

## 12. 현재 레포와 다음 작업

현재 `Infra/compose/compose.yaml`에는 PostgreSQL·Redis·Kafka·HDFS·Spark·Collector·Worker가 profile로 정의되어 있다. WSL은 단일 Kafka KRaft broker와 HDFS replication 1의 실험 구성이다. Spark Worker UI host port는 확장 충돌을 피하기 위해 publish하지 않으며, `Infra/scripts/spark-smoke.sh`로 기본 동작을 확인하고 `Infra/scripts/spark-benchmark.sh`로 Worker 1/2/4와 dataset 1x/2x/4x를 같은 조건에서 비교한다. 이는 로컬 검증용이며 production HA 데이터 플랫폼을 의미하지 않는다.

구현 순서:

1. event envelope·topic·consumer group 확정
2. PostgreSQL migration과 핵심 schema 작성
3. raw intake·Parquet writer·checksum/manifest 구현
4. Registry·정규화·duplicate/review queue 구현
5. Evidence·demand·trend·Pain Snapshot 생성
6. quality result·DLQ·replay·lineage API 연결
7. worker/partition 벤치마크와 복원력 실험 기록

## 13. GitHub raw 요청 Core primary rate limit 실측

> Jira: `S15P21E102-95`
>
> 측정 시각: 2026-08-31 17:02 KST (08:02 UTC)
>
> 상태: 소량 실측 완료 / 수집·분석 기능 구현 없음

### 측정 방법

1. 환경에 설정된 `GITHUB_TOKEN`으로 `GET https://api.github.com/rate_limit`을
   인증 호출해 `resources.core` 상태를 두 번 확인했다.
2. token을 보내지 않고 공개 repository의 작은 파일 3개를
   `raw.githubusercontent.com`에서 GET 요청했다.
3. raw 본문은 메모리에서 응답 크기만 확인하고 파일이나 Git repository에
   저장하지 않았다.
4. raw 요청 후 같은 인증 정보로 Core 상태를 두 번 다시 확인했다.
5. 인증값은 명령 출력, 응답 기록, 문서에 남기지 않았다.

전후 조회를 두 번씩 수행한 것은 `/rate_limit` 조회 자체 또는 동시 사용에 따른
관측값 변화를 확인하기 위한 control이다.

### 실측 결과

Core 상태:

| 단계 | HTTP | Core limit | Core remaining | Core used |
|---|---:|---:|---:|---:|
| 요청 전 control 1 | 200 | 5,000 | 5,000 | 0 |
| 요청 전 control 2 | 200 | 5,000 | 5,000 | 0 |
| raw 3회 후 control 1 | 200 | 5,000 | 5,000 | 0 |
| raw 3회 후 control 2 | 200 | 5,000 | 5,000 | 0 |

API 응답의 `x-ratelimit-resource`는 `core`였고 전후
`x-ratelimit-remaining`도 `5000`이었다.

Raw 요청:

| 순서 | 공개 파일 | HTTP | 응답 크기 | rate-limit 관련 헤더 |
|---|---|---:|---:|---|
| 1 | `octocat/Hello-World`의 `README` | 200 | 13 bytes | 없음 |
| 2 | `github/gitignore`의 `Python.gitignore` | 200 | 4,657 bytes | 없음 |
| 3 | `github/gitignore`의 `Node.gitignore` | 200 | 2,165 bytes | 없음 |

- raw 요청 수: 3회
- raw 성공: 3/3
- 관측된 Core remaining 변화: `5000 → 5000`, delta 0
- 확인한 raw rate-limit 헤더: `x-ratelimit-*`, `ratelimit-*`, `retry-after`
- 위 헤더는 세 응답 모두 존재하지 않았다.

### 실측 결론

이번 조건에서는 공개 파일에 대한 비인증 `raw.githubusercontent.com` GET 3회가
같은 시점의 인증된 GitHub REST API Core primary rate limit remaining을 감소시키지
않았다. 따라서 **이번에 측정한 public raw GET은 인증된 Core bucket에 포함되지
않은 것으로 관측됐다.**

이는 소량 public 파일 요청에 대한 실측 결론이다. raw domain에 별도 제한이 없거나
모든 repository·인증·파일 유형에서 항상 같은 결과가 나온다는 정책 결론으로
일반화하지 않는다.

### S15P21E102-104 Repo Mapping 호출 비용에 주는 영향

- public file 본문을 raw URL로 직접 가져오는 요청은 이번 실측 기준 Core primary
  호출 비용에서 제외할 수 있다.
- repository metadata, branch/commit, tree, Contents API 등 `api.github.com` 요청은
  기존대로 Core 호출 비용에 포함해 계산해야 한다.
- raw URL을 얻기 위해 Contents API 등을 먼저 호출한다면 그 **URL 조회 API 호출**은
  Core 비용이며, 이후 **public raw 본문 GET**만 별도 요청으로 구분한다.
- Core 비용과 별개로 raw 요청 수, 전송량, timeout/retry, CDN·abuse/secondary 제한
  가능성은 별도 budget과 관측 지표로 관리한다.

### 아직 확인되지 않은 사항

- private repository의 raw 파일과 인증 방식
- Git LFS, 대용량 파일, redirect가 있는 URL
- 장시간·고동시성 요청에서의 제한과 secondary/abuse 제한
- raw domain 자체의 별도 quota 또는 throttle 정책
- 다른 token 종류, 계정, GitHub Enterprise 환경에서의 결과
- API와 raw 요청을 다른 네트워크·지역에서 수행했을 때의 차이

## 14. GH Archive Historical 시간별 덤프 수집

> Jira: `S15P21E102-105`
>
> 기준일: 2026-09-01
>
> 상태: **2026년 8월 Historical Bootstrap 완료** — 744 hourly archives가 HDFS Raw에 적재됨
>
> Raw 경로 `/gitjob/raw/{source}/dt=` 확정, 적재 방식 WebHDFS 확정
>
> 생성 dataset: 744 files / 10.85 GiB 압축 / 87,516,869 events

### 문제

Repo 활동량 집계와 Top-N 산출(`S15P21E102-109`)에는 정해진 기간의 GitHub 이벤트가
전량 필요하다. 이를 GitHub REST API로 직접 모으면 Core primary rate limit
5,000/hour에 묶여 부트스트랩 자체가 성립하지 않는다. 또한 수집이 중간에 끊겼을 때
어디까지 받았는지와 빠진 시간대가 있는지를 확인할 수 없으면 Spark 입력의 완전성을
주장할 수 없다.

### 결정

GH Archive가 공개하는 시간 단위 `.json.gz` 덤프를 Raw 원본 그대로 수집한다.
수집기는 `AI/collector/gharchive`에 두고 `python -m collector.gharchive`로 실행한다.

| 항목 | 값 |
|---|---|
| source | `gharchive` |
| base URL | `https://data.gharchive.org` |
| `historical_start` | `2026-08-01T00:00:00Z` (inclusive) |
| `historical_cutoff` | `2026-09-01T00:00:00Z` (exclusive) |
| 대상 파일 수 | 744 hourly file (31일 × 24시간) |
| 첫 파일 / 마지막 파일 | `2026-08-01-0.json.gz` / `2026-08-31-23.json.gz` |
| Raw 논리 경로 | `/gitjob/raw/{source}/dt=YYYY-MM-DD/` |
| Raw 적재 방식 | NameNode WebHDFS HTTP API (`WebHdfsSink`) |

`historical_cutoff`는 exclusive 경계다. 이 시각 이후 데이터는 historical 경로로
유입되지 않으며, P1 신규 Collector(`S15P21E102-144`)가 같은 값을 하한으로 사용해
두 수집 경로가 겹치지 않게 한다.

### 선택 이유

- GH Archive 덤프는 GitHub REST Core 한도를 소비하지 않는다. 부트스트랩 기간 전량
  확보가 API 한도와 무관해진다.
- 파일이 시간 단위로 고정되어 있어 "받아야 할 목록"을 시간 범위에서 결정적으로
  생성할 수 있다. 744개 URL을 하드코딩하지 않으며, 같은 이유로 결번 검사의 기준이
  코드 밖 목록이 아니라 시간 계약이 된다.
- 원본 `.json.gz`를 변형 없이 보존하므로 Spark 재처리와 replay가 가능하다.
- 런타임 의존성을 늘리지 않기 위해 HTTP 클라이언트는 표준 라이브러리 `urllib`을
  사용한다. `AI/requirements.txt`는 변경하지 않았다.

### 검토한 대안

| 대안 | 제외 이유 |
|---|---|
| GitHub REST API로 이벤트 직접 수집 | Core 5,000/hour로 744시간 부트스트랩 불가 |
| 744개 URL을 고정 목록 파일로 관리 | 기간 변경 시 목록이 어긋나고 결번 검사 근거가 사라짐 |
| 다운로드 직후 파싱·정규화까지 수행 | Raw 보존 원칙 위반이며 재처리가 불가능해짐 |
| `requests`/`httpx` 도입 | 런타임 의존성 추가 대비 이득 없음 |

### 현재 구현 범위

`AI/collector/gharchive`:

| 파일 | 책임 |
|---|---|
| `historical.py` | 시간 범위 계약, URL·경로 생성, 다운로드/재시도, gzip 검증, checkpoint, 결번 검사 |
| `sinks.py` | HDFS Raw 경로 규칙, WebHDFS adapter(배포 기본), Hadoop CLI adapter(대안), 범위 발행 |
| `__main__.py` | `plan` / `download` / `validate` / `upload` CLI |

동작:

- 시간 범위를 순회해 대상 파일 목록을 생성한다.
- 받는 중인 파일은 `.part`로 두고, Content-Length 일치와 gzip 전체 해제(CRC 포함)를
  통과한 뒤에만 `os.replace`로 최종 파일이 된다. 부분 파일이 정상 파일로 승격되지
  않는다.
- 시간대별 결과를 checkpoint(JSON)에 기록한다. 기록 항목은 상태, 원본 URL, 파일명,
  압축/해제 크기, sha256, 시도 횟수, 완료 시각이다. 이벤트 본문은 넣지 않는다.
  checkpoint 자체도 임시 파일 기록 후 `os.replace`로 원자적으로 교체한다.
- 재실행 시 이미 검증된 파일은 다시 받지 않는다.
- `validate`는 파일이 아예 없는 시간대(`missing_hours`)와 파일은 있으나 gzip 검증에
  실패한 시간대(`invalid_archives`)를 분리해 보고한다. 두 집합은 겹치지 않으며
  `expected = completed + missing + invalid`가 성립한다. 결번과 손상은 원인과 대응이
  다르므로 같은 카운터로 합치지 않는다.
- 요청 범위가 `historical_start` 이전이거나 `historical_cutoff` 이후면 HTTP 요청
  전에 거부한다.

### 검증 방법 / 결과

`AI/`에서 `pytest`(58 tests), `ruff check .`, `ruff format --check .`가 모두 통과한다.
아래는 실제 `data.gharchive.org`를 대상으로 실행한 결과다.

표본 구간: 2026-08-01 00:00~03:00 UTC (3시간)

| 항목 | 실측값 |
|---|---:|
| 파일 수 | 3 / 3 성공 |
| 압축 크기 | 62,827,856 B (59.92 MiB) |
| 해제 크기 | 315,798,427 B (301.17 MiB) |
| 이벤트 수 | 507,926 |
| 소요 시간 | 17.8초 |

시간대별:

| 파일 | events | 압축 크기 |
|---|---:|---:|
| `2026-08-01-0.json.gz` | 171,167 | 21,375,585 B |
| `2026-08-01-1.json.gz` | 167,181 | 20,730,659 B |
| `2026-08-01-2.json.gz` | 169,578 | 20,721,612 B |

동작 검증:

| 시나리오 | 결과 |
|---|---|
| 동일 범위 재실행 | `downloaded=0`, `reused=3`, 1.2초. 재다운로드 없음 |
| 파일 1개 삭제 후 `validate` | 해당 시간만 `missing_hours`로 검출, exit code 1 |
| 파일 1개 삭제 후 `download` | 삭제된 1개만 재수집, 나머지는 reuse |
| 파일을 1 MiB로 truncate 후 `validate` | `invalid_archives`로 검출, `missing_hours`에는 미포함 |
| 결번과 손상 동시 발생 | `missing` 1건 / `invalid` 1건으로 분리 집계, 재실행 시 둘 다 복구 |
| `historical_cutoff` 초과 요청 | HTTP 요청 없이 거부, exit code 2 |
| `historical_start` 이전 요청 | HTTP 요청 없이 거부, exit code 2 |
| 744시간 `plan` | `expected_files=744`, `2026-08-01-0` ~ `2026-08-31-23` |

전송 계층 특성도 함께 확인했다. 대상 파일은 `Content-Type: application/gzip`이며
`Content-Encoding`이 없으므로 전송 중 자동 압축 해제가 일어나지 않는다. 저장된
바이트는 원본 그대로다.

### HDFS Raw 적재: 실제 Runtime 검증

아래 표기는 세 상태를 구분한다.

| 표기 | 뜻 |
|---|---|
| 설계상 가능 | 근거를 들어 판단했으나 실행하지 않음 |
| 코드 구현됨 | 코드와 단위 테스트는 있으나 실제 Runtime에서 돌린 적 없음 |
| **Runtime 검증됨** | J15E102A의 실제 HDFS/Spark에서 실행해 결과를 확인함 |

#### 검증에 사용한 실제 Runtime

측정일 2026-09-01, J15E102A(`j15e102a.p.ssafy.io`, Tailscale `100.70.66.38`).

| 구성 | 값 |
|---|---|
| NameNode / DataNode | `gitjob-data-hdfs-namenode-1` / `gitjob-data-hdfs-datanode-1` (`apache/hadoop:3.4.1`) |
| `fs.defaultFS` | `hdfs://hdfs-namenode:8020` |
| Live DataNode | 1 |
| Configured Capacity / DFS Remaining | 308.93 GB / 296.91 GB |
| Spark | `gitjob-data-spark-master-1`, `gitjob-data-spark-worker-1`, Spark 3.5.3 |
| Collector / Worker | `gitjob-data-collector-1`, `gitjob-data-worker-1` |

HDFS와 Spark Runtime은 정상 기동 상태다. Runtime 검증됨.

#### Raw 경로: `/gitjob/raw/{source}/dt=YYYY-MM-DD/`로 정정

이전 문서는 Raw 논리 경로를 `/raw/{source}/dt=`로 기록했다. 실제 Infra 설정을 근거로
다시 확인해 `/gitjob/raw/{source}/dt=`로 정정했다.

| 근거 | 내용 |
|---|---|
| `.env.example:132,135` | `HADOOP_CLUSTER_NAME=gitjob`, `PARQUET_ROOT=hdfs:///gitjob/parquet` |
| `.env.ci.example:37,40` | `HADOOP_CLUSTER_NAME=gitjob-ci`, `PARQUET_ROOT=hdfs:///gitjob-ci/parquet` |
| `Infra/compose/compose.yaml:354-356` | `hdfs dfs -mkdir -p /gitjob /gitjob/parquet` 뒤 `/gitjob`과 `/gitjob/parquet`을 **각각** chown |

정정 이유는 두 가지다.

1. 최상위 경로 세그먼트가 환경마다 다르다(`gitjob` / `gitjob-ci`). 즉 첫 세그먼트는
   **환경 격리 경계**이고 `parquet`은 그 아래 계층 이름이다. Raw를 `/raw`에 두면 운영과
   CI가 같은 Raw namespace를 공유해 이 격리가 깨진다.
2. `hdfs-bootstrap`이 `/gitjob`을 `/gitjob/parquet`과 별도로 만들고 별도로 chown한다.
   `/gitjob`이 parquet 전용 상위 디렉터리였다면 `mkdir -p /gitjob/parquet` 하나로
   충분했다. 별도 취급은 `/gitjob` 아래에 parquet 외 계층이 온다는 전제로 읽힌다.

`sinks.py`의 `DEFAULT_RAW_ROOT`를 `/gitjob/raw`로 바꾸고 근거를 docstring에 남겼다.
CI용 `/gitjob-ci/...` 분기는 이번 이슈에서 구현하지 않았다.

#### 3시간 표본 실제 적재 (HdfsCliSink 로직 검증) — Runtime 검증됨

`historical.py`, `sinks.py`를 이 branch 커밋본 그대로 서버에 복사해 sha256 일치를
확인한 뒤 실행했다. 서버에서 downloader로 다시 수집한 파일의 sha256과 바이트 수가
로컬 실측과 완전히 같았다. 같은 코드가 다른 장비에서 같은 바이트를 만든다는 확인이다.

`HdfsCliSink.store()`를 `raw_root` 미지정(기본값) 으로 실제 호출한 결과 목적지는
`hdfs:///gitjob/raw/gharchive/dt=2026-08-01/`이었다. 파일당 4개 명령
(`-test -e` → `-mkdir -p` → `-put`(임시 경로) → `-mv`), 총 12개 명령.

| 항목 | 결과 |
|---|---|
| 적재 파일 수 | 3 / 3 |
| 파일 크기 | 21,375,585 / 20,730,659 / 20,721,612 B (로컬 원본과 동일) |
| `.uploading-*` 잔여 | 없음 |
| read-back sha256 | 3개 모두 **MATCH** |
| gzip 무결성 (HDFS read-back) | 3개 모두 `gunzip` 성공 |
| 이벤트 수 (HDFS read-back) | 171,167 / 167,181 / 169,578 = **507,926** (로컬 실측과 동일) |

| 파일 | read-back sha256 |
|---|---|
| `2026-08-01-0.json.gz` | `43b6517c67e22543b24723eee89f7946e51446c5a05c96e823f07b5b935a9fb5` |
| `2026-08-01-1.json.gz` | `a7ff6c9688de87dc26bb7284144ae4eb5dbcf1631dd9b217501d063539fb1bfe` |
| `2026-08-01-2.json.gz` | `4bc515d473f99cb8d89d60930585d13163503825265415e5c141fc826ebb8924` |

원본 `.json.gz`가 변형 없이 보존됨을 read-back 해시 일치로 확인했다.

**재적재**: 같은 파일로 다시 호출하면 `-test -e` 3회만 실행되고 `-put`은 0회다. 중복
생성도 overwrite도 없이 기존 경로를 재사용한다. Runtime 검증됨.

**실패 시 정리**: `-put` 실패와 `-mv` 실패를 각각 주입해 재현한 결과 임시 파일이 HDFS에
남지 않았다. 최초 검증에서는 남았고(아래) 수정 후 다시 확인했다.

#### Runtime에서 발견한 결함과 수정

`-put` 성공 후 `-mv`가 실패하면 `.uploading-<uuid>` 임시 파일이 HDFS에 그대로 남았다.
최종 경로가 만들어지지 않는 원자성은 지켜졌지만, 재시도마다 새 uuid가 생기므로 실패가
반복되면 고아 파일이 누적된다.

`store()`에서 `-put`/`-mv`를 `try`로 묶고 `HdfsSinkError` 발생 시
`hdfs dfs -rm -f -skipTrash <temporary>`로 정리하도록 최소 범위 수정했다. 단위 테스트를
추가하고 실제 HDFS에서 두 실패 지점 모두 재확인했다.

#### collector Runtime 구조와 `hdfs` CLI 부재 원인

| 항목 | 실측 |
|---|---|
| collector·worker 이미지 | **동일 이미지** (`sha256:6f17ff03…`), 둘 다 `Infra/docker/worker/Dockerfile` |
| base / 크기 | `python:3.12-slim-bookworm` (Debian 12), **214MB** |
| 추가 패키지 | `curl` 뿐 |
| Java / Hadoop | `/usr/lib/jvm` 없음, `/opt/hadoop` 없음, `java`·`hadoop`·`hdfs` 모두 PATH에 없음 |
| 네트워크 | collector·worker·NameNode 모두 `gitjob-data_default` 공유 |
| NameNode RPC 8020 | collector에서 **TCP 연결 성공** |
| WebHDFS 9870 | collector에서 **HTTP 200** |
| DataNode 9864 | collector에서 **HTTP 302** |

`hdfs` CLI가 없는 이유는 장애가 아니라 **이미지 설계**다. collector/worker 이미지는
의도적으로 slim Python 런타임이며 Hadoop client도 JRE도 설치하지 않는다. 막히는 지점은
**바이너리 부재 한 가지**이고 네트워크 경로는 이미 열려 있다.

collector 컨테이너에서 실제로 재현한 실패는
`FileNotFoundError: [Errno 2] No such file or directory: 'hdfs'`이며
`_run_command`가 `HdfsSinkError("hdfs CLI is not available")`로 변환한다.

Python 3.12와 Hadoop CLI를 **동시에** 갖춘 실행 위치가 없다. Hadoop CLI가 있는 NameNode
컨테이너의 Python은 2.7.5라서 이 코드를 실행할 수 없다.

#### 적재 방식 결정: WebHDFS

세 후보를 실측 비용으로 비교했다.

| 기준 | A. 이미지에 Hadoop client | **B. WebHDFS sink (채택)** | C. Spark로 적재 이동 |
|---|---|---|---|
| 현재 코드 적합 | `HdfsCliSink` 그대로, 코드 0줄 | 같은 sink 경계로 신규 구현, `hdfs_raw_path()` 재사용 | 현재 sink 설계 폐기 |
| 구현량 | Dockerfile만 | sink + orchestration + 테스트 | 큼 |
| 이미지 영향 | 214MB에 JRE+client 추가. `apache/hadoop:3.4.1`은 3.3GB. **공용 이미지라 worker도 함께 증가** | **변경 없음** (stdlib `urllib`) | `gitjob/spark:local` 1.56GB |
| 호출 지연 (실측) | `hdfs dfs` 1회 **약 2.0~2.6초** (JVM cold start) | 20 MiB 파일 1개 PUT **212 ms** | job 기동 오버헤드 |
| 744 파일 환산 | 파일당 4회 × 744 = **2,976회 JVM 기동 ≈ 100분 이상** | 744회 HTTP ≈ 수 분 | 별도 산정 |
| 추가 Infra 작업 | 이미지 재빌드 | **없음** (WebHDFS 이미 활성) | 없음 |
| `-109`와 책임 분리 | 좋음 | 좋음 | **Raw 적재 주체가 Spark가 되어 수집·적재와 집계 책임이 섞임** |

**B를 채택했다.** 코드 변경만 보면 A가 최소지만, `hdfs dfs` 호출당 약 2초의 JVM cold
start 때문에 744시간 적재에서 전송이 아닌 프로세스 기동에 100분 이상이 들어간다. 또
Raw sink 하나 때문에 collector와 worker 공용 이미지에 JRE와 Hadoop client가 함께 들어간다.
C는 Raw 적재 주체가 Spark가 되어 `S15P21E102-109`와 책임이 섞이므로 제외했다.

`HdfsCliSink`는 **제거하지 않았다.** Hadoop CLI가 있는 실행 위치를 위한 대안 구현으로
유지하며, 두 sink는 같은 Raw 경로 규칙·임시 경로·rename·멱등성 모델을 공유한다.

#### WebHdfsSink 구조

`AI/collector/gharchive/sinks.py`:

| 요소 | 역할 |
|---|---|
| `RawSink` (Protocol) | `exists(hour, filename)` + `store(local_path, hour)` 두 메서드 경계 |
| `WebHdfsSink` | NameNode WebHDFS HTTP API 어댑터. 배포 기본 방식 |
| `HdfsCliSink` | `hdfs dfs` 어댑터. CLI가 있는 환경용 대안 |
| `WebHdfsTransport` / `UrllibWebHdfsTransport` | HTTP 경계. stdlib `urllib` 사용, 테스트에서 fake 주입 |
| `publish_downloaded_range()` | 시간 범위를 순회해 sink로 발행하고 시간대별 결과를 집계 |

`store()` 절차는 HDFS CLI 방식과 같은 원자성 모델을 유지한다.

1. `op=GETFILESTATUS` — 최종 경로가 있으면 업로드 없이 그 위치를 반환한다.
2. `op=MKDIRS` — `dt=` partition 디렉터리를 만든다.
3. `op=CREATE&overwrite=false` — 임시 경로 `<final>.uploading-<uuid>`를 열고 NameNode가
   반환한 **307 redirect Location(DataNode)** 으로 본문을 스트리밍한다. 파일은 메모리에
   올리지 않고 `Content-Length`와 함께 파일 객체로 전달한다.
4. `op=RENAME` — 임시 경로를 최종 경로로 배치한다. HDFS RENAME은 대상이 이미 있으면
   덮어쓰지 않고 `false`를 반환하므로, **최종 파일 overwrite가 구조적으로 불가능하다.**
5. 실패 시 `op=DELETE`로 임시 경로를 정리한 뒤 원래 오류를 다시 던진다.

`urllib`은 PUT에 대해 307을 따라가지 않으므로 redirect를 코드가 명시적으로 처리한다.
`requirements.txt`에 새 의존성을 추가하지 않았다.

`publish_downloaded_range()`는 **존재 확인 → gzip 검증 → 발행** 순서다. 이미 적재된
시간대는 다시 압축 해제하지 않고 `reused`로 보고하며, gzip 검증을 통과하지 못한 로컬
파일은 sink에 전달되지 않는다. 결과는 `uploaded` / `reused` / `missing` / `invalid` /
`failed`로 분리되고 서로 겹치지 않는다.

#### Runtime endpoint 설정

기존 `.env` 네이밍 규칙(`HDFS_URI`, `PARQUET_ROOT`)에 맞춰 값을 추가했다.

| 변수 | 값 | 용도 |
|---|---|---|
| `WEBHDFS_URL` | `http://hdfs-namenode:9870/webhdfs/v1` | WebHDFS API base (버전 prefix 포함) |
| `WEBHDFS_USER` | `hadoop` | 비보안 HDFS의 `user.name` |
| `RAW_ROOT` | `hdfs:///gitjob/raw` | Raw root. `PARQUET_ROOT`와 같은 표기 |

`compose.yaml`의 collector 서비스에 위 세 값을 `${VAR:-default}` 형태로 전달했다. IP와
Tailscale 주소는 하드코딩하지 않고 Compose 서비스명 `hdfs-namenode`를 사용한다.
`RAW_ROOT`는 `hdfs:///gitjob/raw`와 `/gitjob/raw` 두 표기를 모두 받는다. Dockerfile은
변경하지 않았고 Hadoop/JRE도 추가하지 않았다.

CLI는 `python -m collector.gharchive upload`이며 `--webhdfs-url` / `--raw-root` /
`--webhdfs-user`로 덮어쓸 수 있다. endpoint가 없으면 실행 전에 거부한다.

#### collector 컨테이너 실제 적재 — Runtime 검증됨

**실행 주체가 collector 컨테이너 자신이다.** 이 branch의 `gharchive` 모듈을 컨테이너에
주입하고 `sha256`이 로컬과 일치함을 확인한 뒤 `python -m collector.gharchive upload`를
실행했다.

| 항목 | 결과 |
|---|---|
| 1회차 | `uploaded=3, reused=0, failed=0`, `published_bytes=62,827,856`, **2,974 ms** |
| 2회차 (동일 범위) | `uploaded=0, reused=3`, **1,237 ms** — 업로드 0회 |
| HDFS 경로 | `/gitjob/raw/gharchive/dt=2026-08-01/` |
| 파일 크기 | 21,375,585 / 20,730,659 / 20,721,612 B (로컬 원본과 동일) |
| read-back sha256 | 3개 모두 **MATCH** |
| gzip 무결성 | 3개 모두 `gunzip` 성공 |
| 이벤트 수 | 171,167 + 167,181 + 169,578 = **507,926** |
| `.uploading-*` 잔여 | 없음 |
| `/gitjob/parquet` | 변경 없음 (검증 전후 동일) |

| 파일 | read-back sha256 |
|---|---|
| `2026-08-01-0.json.gz` | `43b6517c67e22543b24723eee89f7946e51446c5a05c96e823f07b5b935a9fb5` |
| `2026-08-01-1.json.gz` | `a7ff6c9688de87dc26bb7284144ae4eb5dbcf1631dd9b217501d063539fb1bfe` |
| `2026-08-01-2.json.gz` | `4bc515d473f99cb8d89d60930585d13163503825265415e5c141fc826ebb8924` |

실제 HTTP 흐름은 파일당 5개 요청으로 관측됐다.

```text
GETFILESTATUS(404) -> MKDIRS(200) -> CREATE(307) -> [DataNode] PUT(201) -> RENAME(200)
```

이미 적재된 시간대는 `GETFILESTATUS(200)` 1회로 끝난다.

**실패 주입 (실제 WebHDFS 대상)**

| 주입 지점 | 결과 |
|---|---|
| `RENAME` 실패 | `HdfsSinkError` 발생, 최종 경로 미생성, `DELETE` 실행, `.uploading-*` 잔여 없음 |
| DataNode 업로드 실패 | `HdfsSinkError` 발생, 최종 경로 미생성, `DELETE` 실행, `.uploading-*` 잔여 없음 |

#### 744시간 Historical Bootstrap 완료 — Historical Dataset 생성 완료

2026년 8월 전체를 실제로 수집해 HDFS Raw에 적재했다. 이 절은 표본 검증이 아니라
**완성된 dataset의 기록**이다.

| 항목 | 값 |
|---|---|
| 실행 코드 commit | `325e9a261aebc58c0a4c7ac18cb34d145486a022` |
| Historical 범위 | `2026-08-01T00:00:00Z` ~ `2026-09-01T00:00:00Z` (cutoff, exclusive) |
| expected hours | **744** |
| HDFS 실제 파일 수 | **744** |
| partition 수 | **31** (`dt=2026-08-01` ~ `dt=2026-08-31`), 각 24개 |
| 누락 partition | 없음 |
| 0바이트 파일 | 없음 |
| `.uploading-*` 잔여 | 없음 |
| uploaded / reused | 720 / 24 |
| missing / invalid / failed | **0 / 0 / 0** |
| 총 압축 크기 | **11,654,413,308 B = 10.85 GiB (11.65 GB)** |
| 총 해제 크기 (checkpoint 합) | 57,458,023,922 B = **53.51 GiB** |
| 전체 Event 수 (Spark) | **87,516,869** |
| HDFS Raw 사용량 | 10.9 G (`dfs.replication=1`) |
| 실행 시간 | 일별 루프 1,035초 + 24시간 sanity 41초 = **약 18분** |
| end-to-end throughput | 약 10.8 MB/s (다운로드 + gzip 검증 + WebHDFS 적재 직렬 합산) |

`reused=24`는 앞선 24시간 sanity check에서 이미 적재한 `dt=2026-08-01`이다. 재실행에서
업로드를 반복하지 않고 건너뛴 것이므로 멱등성이 실데이터 규모에서도 성립함을 보여준다.

#### 실행 방식과 진행 기록

하루(24시간) 단위로 `download` → `upload`를 31회 반복했다. 하루 단위로 끊은 이유는
장시간 실행의 진행 상황을 남기고, 중단 시 어디까지 끝났는지 확인할 수 있게 하기
위해서다. 로컬 파일과 checkpoint를 지우지 않았으므로 재실행하면 완료된 시간대는
download가 reuse, upload가 `reused`로 건너뛴다.

일별로 `expected` / `downloaded` / `reused` / `missing` / `invalid` / `failed` /
`published_bytes` / 누적 경과시간을 기록했다. 31일 전체에서 **비정상 종료 코드나
실패 카운트가 발생한 일자는 없었다.**

`WebHdfsSink`에는 아직 재시도/backoff가 없다. 실행 중 일시적 5xx나 네트워크 실패가
나오면 해당 시간대를 `failed`로 기록한 뒤 재실행으로 치유하는 방식을 쓰기로 했으나,
**이번 744시간 실행에서 실제로 발생한 WebHDFS 오류는 0건**이었다. 따라서 실측 근거가
없는 상태에서 재시도 기능을 선행 추가하지 않았다.

#### Integrity 검증 방식과 선택 이유

744개 전체를 다시 내려받아 sha256을 재계산하는 방식은 쓰지 않았다. 같은 바이트를 두 번
전송하는 비용만 늘고, 그 비용으로 새로 증명되는 것이 크기·해제 가능성 검증과 크게
다르지 않기 때문이다. 대신 세 층으로 나눴다.

| 층 | 대상 | 방법 | 결과 |
|---|---|---|---|
| 전수 (metadata) | 744 / 744 | downloader checkpoint의 파일명·압축 크기·sha256 기록과 HDFS `-ls` 결과를 대조 | **불일치 0건.** checkpoint 744건 전부 `complete`, 크기 mismatch 0, HDFS에만 있는 파일 0, checkpoint에만 있는 시간대 0, sha256 누락 0 |
| 전수 (해제 가능성) | 744 / 744 | Spark가 744개 `.json.gz` 전량을 읽어 record를 계산. 손상 gzip은 task 실패로 드러난다 | **744 files 판독 성공**, 87,516,869 events, exit 0 |
| 표본 (read-back sha256) | 8건 | HDFS에서 다시 읽어 sha256을 계산하고 checkpoint 기록값과 비교 | **8/8 MATCH** |

표본은 월 초(08-01, 08-02), 월 중(08-15, 08-16), 월 말(08-30, 08-31)에 더해 크기
이상치인 최대(08-07 17시, 76,972,242 B)와 최소(08-20 22시, 824,873 B)를 포함했다.
평범한 구간만 뽑으면 이상치에서만 나타나는 문제를 놓칠 수 있기 때문이다.

checkpoint에는 시간대별 sha256이 이미 기록되어 있으므로, 나중에 특정 시간대를 의심하게
되면 그 파일만 read-back으로 재검증할 수 있다. 전수 재검증을 미리 수행할 필요는 없다.

#### 실제 데이터 규모와 편차

| 항목 | 실측 |
|---|---:|
| hourly 파일 수 | 744 |
| 총 압축 크기 | 11,654,413,308 B (10.85 GiB) |
| 평균 hourly 압축 크기 | 15,664,534 B (14.94 MiB) |
| 중위 hourly 압축 크기 | 18,954,982 B (18.08 MiB) |
| 최소 hourly | **824,873 B** (`2026-08-20-22.json.gz`) |
| 최대 hourly | **76,972,242 B** (`2026-08-07-17.json.gz`) |
| 최대/최소 배수 | **93.3배** |

일별 압축 크기도 87.2 MiB(08-20)에서 509.3 MiB(08-07)까지 벌어졌다.

최소 크기 파일들이 손상이 아닌지 개별 확인했다. `2026-08-20`의 21·22·23시는 각각
803 / 697 / 757 events로 정상 gzip이며 내용도 들어 있다. 즉 해당 시간대에 GH Archive
원본의 이벤트 양 자체가 적었던 것이고 우리 수집 문제가 아니다.

이전 문서의 744시간 추정치와 실측을 비교하면 다음과 같다.

| 항목 | 3시간 표본 선형 외삽 | 실측 | 차이 |
|---|---:|---:|---:|
| 압축 크기 | 약 14.51 GiB | **10.85 GiB** | 약 -25% |
| 해제 크기 | 약 73 GiB | **53.51 GiB** | 약 -27% |
| Event 수 | 약 1.26억 | **8,752만** | 약 -31% |

외삽에 사용한 3시간 표본(2026-08-01 00~02시, 169,309 events/hour)이 월 평균
(117,630 events/hour)보다 높은 구간이었기 때문이다. **시간 단위 표본으로 월 규모를
선형 추정하면 안 된다는 것이 이번 실측으로 확인됐다.** `S15P21E102-109`의 Spark 자원
산정에는 위 실측값을 쓴다.

`S15P21E102-105` Jira에 기록된 3시간 표본(223,329 events / 141.46 MiB 해제)도 측정
구간이 다르므로 어느 쪽을 오류로 판단하지 않는다.

#### 용량 사전 점검 결과

실행 전 확인한 값이다.

| 항목 | 값 |
|---|---|
| HDFS Configured Capacity | 308.93 GB |
| 실행 전 DFS Remaining | 297.02 GB |
| `dfs.replication` (읽기만) | **1** — 저장 배수 없음 |
| 3시간 실측 기반 744시간 예상 | 약 15.58 GB |
| 예상 / Remaining | 약 5.2% |
| 실행 후 DFS Used / Used% | 10.94 GB / 3.82% |
| 실행 후 DFS Remaining | 275.28 GB |

예상치가 잔여 공간의 5% 수준이어서 그대로 진행했고, 실제 사용량은 예상보다 작았다.
`dfs.replication` 설정은 조회만 했고 변경하지 않았다.

#### Spark 전량 read smoke — Runtime 검증됨

744시간 전체를 대상으로 확인했다. 집계·Top-N·Coverage·Parquet 출력은
`S15P21E102-109` 범위이므로 수행하지 않았다.

| 항목 | 결과 |
|---|---|
| `inputFiles()` | **744** |
| 전체 record 수 | **87,516,869** |
| 필드 접근 | `type`, `repo.id`, `repo.name` 정상 |
| 샘플 | `IssuesEvent` / `1209911366` / `ElrohirGT/HoraPico` 등 |
| 소요 / 종료 코드 | 315초 / 0 |

schema를 명시해 inference용 추가 스캔을 피했다. Python driver로 데이터를 모으지 않고
Spark가 분산 처리한 결과만 받았다.

#### 상태 구분 정리

| 항목 | 상태 |
|---|---|
| GH Archive downloader / resume / 결번 / gzip 검증 / cutoff | **Runtime 검증됨** |
| `WebHdfsSink` 적재·멱등성·실패 정리 | **Runtime 검증됨** (collector 컨테이너에서 실행) |
| `publish_downloaded_range` 결과 분리 | **Runtime 검증됨** (3시간) / 단위 테스트 |
| Spark의 Raw 판독 | **Runtime 검증됨** (read only) |
| `HdfsCliSink` | 로직은 Runtime 검증됨(주입 runner). **기본 runner는 배포 이미지에서 실행 불가** |
| **744시간 전량 적재** | **Historical Dataset 생성 완료** (744/744, missing·invalid·failed 0) |
| `-109` 집계·Top-N·Coverage | **미구현** |
| Repo Mapping / Manifest Fetch | **미구현** |

#### 이번 작업에서 하지 않은 것

- Hadoop client·JRE 설치, Docker image 변경, 서버 package 설치, 네트워크·UFW·SSH 변경
- `HdfsCliSink` 제거
- 744시간 전량 수집·적재
- `S15P21E102-109`의 집계·Top-N·Coverage·Parquet
- Kafka, Repo Mapping, Source/Manifest Fetch
- CI용 `/gitjob-ci` Raw 분기 (`.env.ci.example`은 그대로. compose 기본값이 있어 CI는 깨지지 않음)

### 아직 미확정 / 미검증

- **`HdfsCliSink` 기본 runner는 현재 배포 이미지에서 실행할 수 없다.** 배포 기본 방식은
  `WebHdfsSink`이며, CLI 어댑터는 Hadoop CLI가 있는 실행 위치용 대안으로만 유지한다.
- 이번 실행은 collector 컨테이너에서 수행했으나, 배포된 이미지에는 아직 `gharchive`
  모듈이 없어 검증을 위해 모듈을 주입했다. merge 후 이미지 재빌드로 해소된다.
- `WebHdfsSink`에는 재시도/backoff가 없다. 744시간 실행에서 WebHDFS 오류가 0건이었기
  때문에 실측 근거 없이 추가하지 않았다. 실패가 관측되면 그때 최소 구현을 검토한다.
- 동시 적재(병렬 업로드)는 시도하지 않았다. 시간대 직렬 처리로 약 18분에 끝나 병렬화가
  필요하지 않았다.
- 이 dataset은 `historical_cutoff` 이전 구간의 **1회 부트스트랩**이다. 2026-09-01 이후
  구간은 P1 신규 Collector(`S15P21E102-144`) 담당이며 이 경로로 적재하지 않는다.
- GH Archive 원본 자체의 시간대 누락 여부는 구분하지 않는다. 다만 744개가 모두 받아졌으
  므로 이번 구간에는 원본 누락이 없었다.
- `S15P21E102-109`의 Repo 활동량 집계, Top-N, Coverage, Parquet Analysis Input은
  수행하지 않았다. Spark는 read smoke까지만 확인했다.
- Repo Mapping / HEAD·Tree·Manifest Fetch는 이번 이슈 범위가 아니다.

### 책임 경계

이 작업은 Raw 확보까지만 담당한다. 수집된 이벤트에서 기술명을 정규화하거나,
`tech_id`를 부여하거나, 어떤 기술이 사용됐는지 판정하지 않는다. 기술 의미 분석은
C조 범위다.

### 후속 작업

| Jira | 연계 |
|---|---|
| `S15P21E102-109` | 이 Raw를 Spark로 전량 읽어 Repo 활동량 집계와 Top-N·Coverage 산출 |
| `S15P21E102-144` | P1 신규 Collector가 `historical_cutoff`를 하한으로 사용해 수집 구간 중복 방지 |
| `S15P21E102-105` | Historical Bootstrap 완료. Dataset 잔여 작업 없음 |

## Repo Activity Aggregation

- Jira: S15P21E102-109
- 입력: GH Archive Historical 2026-08 (744 files, 87,516,869 events)
- 처리: Spark Repo Activity / Top-N / Coverage (5,711,133 unique repos; Top-20,000 valid coverage 24.5638%)
- 상세: [S15P21E102-109 Repo Activity Top-N 검증 보고서](2026-09-02-repo-activity-topn-validation.md)

## Repo Fetch Cost Benchmark

- Jira: S15P21E102-104
- 결론: 2026-08 1개월 Historical Dataset을 활동량 순 Offline Batch로 Enrichment한다. Top-N은 영구 cutoff가 아니라 처리 우선순위이며, Top 20k → 50k → 100k로 확장한 뒤 C조 기술 Mapping이 충분해지는 시점에 2026-08 FINAL Snapshot 하나를 고정한다
- 실측: 수집 Repo 1개 = core 3.00회 / 2.47MB / 2.63s, 404 Repo = core 1.00회, 동일 SHA 재검증 = core 1.00회(-66.7%)
- checkpoint/resume: 재실행 시 fetch 요청 0건, rate limit 도달 시 reset 대기 후 재개
- 404: 50개 중 22개(44%). rename이 아니라 Repository·계정 소멸이며 `repo_id` 회수 0/22 → production에 fallback 미적용
- Tree 병목: recursive tree가 응답량의 98.63%. root manifest probe가 tree와 27/27 일치, REST core 0회, 전송량 -99.9% → 후속 -150 적용 권고
- 기간 확장: `--input-root`로 다른 period 재사용 가능, checkpoint는 `dataset_key`로 기간 간 혼용 차단
- 판정: A — MR 가능
- 상세: [S15P21E102-104 GitHub Repo Fetch 비용 검증 보고서](2026-09-02-repo-fetch-cost-benchmark.md)

## GitHub Repo Fetch Orchestrator

- Jira: S15P21E102-150
- 입력: `repo-fetch-candidates/v1` Repo Activity 우선순위
- 출력: C조 `github-repo-snapshot/v1` 계약을 그대로 재사용
- 처리: metadata → pinned Commit → recursive Tree → manifest/source → checksum·URI
- 재사용: 전체 policy fingerprint + `github_repo_id` + pinned SHA Cache
- 재개: dataset-bound checkpoint, `RATE_LIMITED` Repo부터 재시작
- 상태: 구현·Unit Test·공개 GitHub 표본 Runtime 검증 완료 / HDFS Runtime 검증 전
- 상세: [S15P21E102-150 GitHub Repo Fetch Orchestrator](2026-09-03-repo-fetch-orchestrator.md)

## GitHub Repo Snapshot 부트스트랩 배치

- Jira: S15P21E102-114
- Phase 1: Repo Activity 연속 rank Top 20,000
- 실행: checkpoint/resume, 진행률·throughput·ETA, Rate Limit wait/restart
- 전달: `github-repo-snapshot/v1`과 Artifact를 WebHDFS shared namespace에 publish
- 책임 경계: A조 Snapshot 생성까지이며 Technology Registry/Evidence 의미 분석 제외
- 상세: [S15P21E102-114 Repo Snapshot 부트스트랩 배치](2026-09-04-repo-snapshot-bootstrap-batch.md)

## Repo Snapshot Production Canary

- Jira: S15P21E102-163
- 대상: `pallets/flask` (`repo_id=596892`) 1건, Canary 당시 배포 image 기준(현재 image와 동일하다고 추정하지 않음)
- 결과: `collection_status=COMPLETE`, `record_count=1`, `github-repo-snapshot/v1`, Artifact 5개, 실패 0
- 요청량: Repo Core 3 / raw 5, control Core 1 (S15P21E102-114 canary 실측과 동일)
- HDFS: `snapshot_id=s15p21e102-163-canary-20260907` publish 후 read-back 5/5, SHA-256 5/5 일치; checkpoint 재실행 후 read-only listing에서도 Artifact 5개·checksum 5/5 동일
- 재실행: 동일 checkpoint에서 terminal 결과 재사용, `attempts=1` 유지, 추가 fetch 0건
- 제한: Canary 당시 full image digest는 기존 기록에 없어 확정 불가; Spark Top-N output → `candidates.json` → `load_candidates()` → Bootstrap 경로와 Top 20,000 rate-limit wait/resume은 이번 1 Repo Canary에서 대표되지 않음
- 판정: Top 20,000 Bootstrap 진행 blocker 없음 (표본은 공개 Repo 1건)
- 상세: [S15P21E102-163 Repo Snapshot Production Canary 검증](2026-09-07-repo-snapshot-production-canary.md)

## MVP 데이터 파이프라인 멱등성·Replay 검증

- Jira: S15P21E102-111
- GH Archive: UTC hour Raw 재사용·불변 publish, Repo Activity snapshot overwrite 거부
- Repo Snapshot: dataset checkpoint와 policy fingerprint + repo ID + pinned SHA cache 재사용
- Jobs: `(source_site, source_posting_id)` 업무 키, 같은 run 원자적 replacement
- Streaming: producer replay/smoke만 구현; application checkpoint·offset·sink 멱등성은 후속
- 상세: [S15P21E102-111 MVP 데이터 파이프라인 멱등성 및 Replay 검증](2026-09-07-mvp-pipeline-idempotency-replay.md)

## 15. 원문 출처

- [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d)
- [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c)
- [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)
- [개발 환경](https://app.notion.com/p/77f0dff912cf8305a10b017245b40a78)
- [환경 변수](https://app.notion.com/p/0b60dff912cf836084ee01fb375e5cbd)
