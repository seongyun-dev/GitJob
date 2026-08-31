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

| 구성 | 예시 |
|---|---|
| canonical key | `tech_id=kafka` |
| display name | Apache Kafka |
| aliases | Kafka, kafka-clients |
| package/tag | Maven artifact, Stack Overflow tag |
| category | backend, database, infrastructure 등 |
| requirement type | REQUIRED, PREFERRED, SKILL |
| version | `registry_version` |
| review state | approved, ambiguous, unknown |

정확한 alias/package/tag match를 우선하고, 모호하거나 처음 보는 표현은 `AMBIGUOUS`/`UNKNOWN`으로 review queue에 보낸다. AI가 Registry 항목을 자동 확정하지 않는다. Registry 변경은 C2 replay를 발생시키며 과거 분석 Snapshot을 덮어쓰지 않는다.

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

재처리 규칙:

1. consumer는 수동 commit과 checkpoint를 사용한다.
2. 일시적 외부 오류는 backoff와 최대 retry 후 DLQ로 보낸다.
3. Registry만 바뀌면 raw를 재수집하지 않고 C2 replay를 실행한다.
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

## 14. 원문 출처

- [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d)
- [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c)
- [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)
- [개발 환경](https://app.notion.com/p/77f0dff912cf8305a10b017245b40a78)
- [환경 변수](https://app.notion.com/p/0b60dff912cf836084ee01fb375e5cbd)
