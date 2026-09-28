# 공고 검색 Projection 및 계산 결과 경량화 작업 계획

- 상태: MR `!270`/`6b5960c` 병합·배포 완료, 운영 성능 gate 미달 보완 진행
- 작성일: 2026-09-20
- 기준 브랜치: `develop`
- 기준 커밋: `82edca8` (`origin/develop`, 2026-09-20 14:23 KST)
- 관련 작업: `S15P21E102-334` 후속
- Jira: `S15P21E102-360`
- 1차 목표: 직무·지역·경력 변경의 cold 수요 조회를 500ms 이내로 줄인다.
- 2차 목표: 기존 추천·매칭·What-if 의미를 유지하면서 대형 COHORT/RECOMMENDATION
  JSON 중복을 제거한다.

> MR `!270` 병합 이후 실제 운영에서 확인된 Projection request hot path, Current Market,
> current-result backfill 보완의 단일 실행 기준은
> [2026-09-20-job-projection-query-hot-path-plan.md](./2026-09-20-job-projection-query-hot-path-plan.md)다.
> 이 문서는 원 설계·계약·구현 이력을 보존하고, 후속 문서가 최신 develop과 운영 실측을 기준으로
> 실행 순서와 완료 조건을 확장한다.

이 문서는 구현자가 별도의 대화 기록을 보지 않고도 작업 범위, 데이터 의미, 배포 순서,
검증 및 롤백 방법을 결정할 수 있도록 작성한다. 추정 수치와 실제 인수 기준을 구분한다.

### 작업 준비 상태

| 항목 | 상태 | 실행 규칙 |
|---|---|---|
| 원격 동기화 | 완료 | 로컬 `develop`을 `origin/develop`의 `82edca8`까지 fast-forward 했다. |
| Jira | 완료 | `S15P21E102-360` 작업을 생성하고 이송민에게 할당했다. |
| 작업 브랜치 | 완료 | 최신 `develop`에서 `feat/S15P21E102-360-branch`를 생성했다. |
| 첫 커밋 | 준비 | 이 문서를 `[S15P21E102-360] docs: 공고 검색 Projection 전환 계획과 인수 기준 문서화`로 커밋한다. |
| MR | 단일 MR | Phase 1/2를 커밋과 feature flag로 나누되 MR은 하나만 만든다. |
| 선행 변경 | 병합 확인 필요 | `S15P21E102-352`, `S15P21E102-353`과 겹치는 파일은 두 작업의 병합 결과를 반영한 뒤 수정한다. |

현재 원격 브랜치 기준 직접 충돌 가능성이 있는 선행 작업은 다음과 같다.

- `S15P21E102-352`: `AI/job/demand.py`, `AI/tests/test_current_market_demand.py`
- `S15P21E102-353`: `AI/job/cohort.py`, `AI/job/demand.py`,
  `AI/tests/test_current_market_demand.py`, `docs/ai/c-job-demand.md`

신규 migration, Projection store/materializer처럼 겹치지 않는 파일부터 구현할 수 있다. 위 두 이슈가
병합되기 전 `demand.py`/`cohort.py`를 먼저 크게 수정하지 않는다. 병합 후에는 작업 브랜치에서
`git merge origin/develop`로 반영한다. 이미 공유한 브랜치의 history를 바꾸는 rebase/force-push는
사용하지 않는다.

---

## 1. 결론

현재 서비스에는 다음 구조가 가장 적합하다.

1. 파싱·직무 분류·요구사항 추출 결과를 공고별로 한 번만 저장한다.
2. 직무·지역·경력·기술·상태·마감일을 검색 가능한 버전 Projection으로 게시한다.
3. `/job-demands/preview`는 Snapshot을 생성하지 않고 PUBLISHED Projection을 조회한다.
4. 추천·Skill Gap·Job Match·What-if는 한 계산에서 나온 **현재 결과 세트**를 계속 공유한다.
5. 과거 날짜별 사용자 Snapshot을 영구 보관하지 않는다. `(user_id, target_key)`별 최신
   완료 결과와 안전한 교체를 위한 직전 결과만 유지한다.
6. 월별 Trend는 실제 역사 기능이므로 기존 불변 집계를 유지한다.
7. COHORT/RECOMMENDATION 대형 JSON 제거는 Preview 전환 안정화 후 진행한다.

첫 구현 MR에서 1~3과 관측·롤백까지만 활성화한다. 개인 추천 저장 계약은 같은 MR에
섞지 않는다. 하나의 MR로 전체 로드맵을 구현해야 하는 경우에도 기능 플래그와 배포
게이트는 반드시 분리한다.

---

## 2. 문제와 운영 기준선

### 2.1 사용자 체감 실측

2026-09-20 운영 브라우저/Backend 로그에서 확인한 값이다.

| 요청 | Backend/브라우저 관측 |
|---|---:|
| `INFRASTRUCTURE + 제주` cold | Backend 10.525s, 브라우저 약 11.3s |
| `INFRASTRUCTURE + 제주+서울` cold | Backend 4.371s, 브라우저 약 5.1s |
| `INFRASTRUCTURE + 서울` cold | Backend 6.074s |
| `INFRASTRUCTURE + 전체` cache hit | Backend 34ms |
| `/api/v1/job-demands` 최근 성공 요청 | 평균 2.980s, p95 10.525s, 최대 30.036s |

FE debounce는 400ms다. cache hit은 이미 충분히 빠르므로 병목은 FE가 아니라 새로운 정확한
조건 조합을 처리하는 C의 cold 경로다.

### 2.2 현재 cold 경로

```text
FE 400ms debounce
  -> BE JobDemandService
  -> C POST /internal/v1/c/job-demands/preview
  -> selector 정규화와 exact criteria cache 조회
  -> prepared union의 모든 공고 순회
  -> 역할/지역/경력/상태/마감/품질 판정
  -> CohortJob, exclusion, matching_jobs 생성
  -> 전체 COHORT JSON 직렬화/hash/검증/INSERT
  -> DEMAND Snapshot 생성/INSERT
  -> DEMAND Snapshot 재조회 후 반환
```

`S15P21E102-334`는 파싱·분류·요구사항 추출을 prepared union에서 재사용하고, exact
criteria cache와 1회 preview 왕복을 추가했다. 따라서 같은 조건의 재조회는 빠르다. 남은
병목은 조건 조합마다 전체 객체 그래프와 Snapshot을 다시 만드는 일이다.

### 2.3 운영 DB 실측

2026-09-20 서비스 PostgreSQL 16.4에서 읽기 전용으로 측정했다.

| 관계 | live rows | `pg_total_relation_size` |
|---|---:|---:|
| `c_compute.snapshot` | 1,231 | 1,381MB |
| `c_compute.registry_review_cohort` | 216,904 | 114MB |
| `c_compute.matching_job` | 20,563 | 29MB |
| `c_compute.registry_review` | 6,381 | 27MB |
| `c_compute.matching_source` | 3,017 | 5.8MB |
| `c_compute.head` | 890 | 496KB |
| `c_compute.event` | 550 | 440KB |
| `c_compute.matching_calculation` | 106 | 424KB |

`c_compute.snapshot`의 구성은 main heap 768KB, index 184KB, TOAST 1,380MB다. Snapshot
종류별 논리 payload는 다음과 같다.

| kind | rows | payload 합계 | 평균 | 최대 |
|---|---:|---:|---:|---:|
| COHORT | 154 | 약 1,162MB | 약 7.7MB | 약 12.75MB |
| DEMAND | 167 | 약 223KB | 약 1.3KB | 약 3.3KB |
| RECOMMENDATION | 106 | 약 63MB | 약 610KB | 약 1.4MB |
| PUBLIC_GITHUB | 10 | 약 84MB | 약 8.6MB | - |
| TREND | 749 | 약 4.15MB | 약 5~6KB | - |

서비스 서버 디스크는 약 309GB 중 251GB를 사용해 82%다. 새 Projection 자체는 수십 MB
수준으로 예상하지만, 구 Snapshot과 장기간 이중 보관하지 않는다.

### 2.4 추가 중복

`registry_review_cohort`는 6,381개 review와 152개 cohort 사이에 216,904개 연결을 갖는다.
review당 평균 34개, 최대 151개 cohort에 연결된다. 같은 source review가 조건별 cohort마다
반복 연결되는 구조다. 이는 2차 경량화 대상이며 1차 Preview MR에서 변경하지 않는다.

---

## 3. 범위와 비범위

### 3.1 1차 필수 범위

- 버전이 있는 공고 검색 Projection 스키마
- 기존 prepared union에서 Projection을 만드는 materializer
- BUILDING/PUBLISHED/FAILED 상태와 원자적 head 교체
- Projection 기반 `ACTIVE_MATCHING` 및 `CURRENT_MARKET` demand preview
- 기존 Python 결과와 신규 Projection 결과의 shadow 비교
- feature flag 기반 구경로 롤백
- latency, build, mismatch, lag 지표
- migration/backfill/deploy/runbook 및 회귀 테스트
- 마감 공고의 live 의미를 명시하고 테스트로 고정

### 3.2 2차 범위

- Job Match 조회 시 현재 활성 상태 결합
- What-if의 count/ID/list에 동일 활성 집합 적용
- Projection 변경 시 개인 결과 stale 표시 및 비동기 재계산
- Recommendation payload의 `jobs`, `matching_jobs` 제거
- `job_fact_id` 기반 shared source 참조
- `(user_id, target_key)`별 최신 결과 pointer
- COHORT Snapshot 참조를 Projection identity로 이전
- Registry review의 cohort fan-out 제거
- 구 COHORT/RECOMMENDATION payload retention 및 GC

### 3.3 명시적 비범위

- LLM 기술 요약 지연 개선
- GitHub repository/branch 외부 API 지연 개선
- Collector 수집 주기 변경
- Kafka/Spark/HDFS 처리량 튜닝
- 월별 Trend 의미 변경
- 모든 JSONB 필드의 완전 정규화
- 모든 지역/직무/경력 조합 사전 계산
- BE가 C 소유 테이블을 직접 조회하는 구조

---

## 4. 변경하지 않아야 하는 기존 기능과 의미

### 4.1 공통

- C가 공고 파싱, 분류, 요구사항, 수요, 추천 의미의 소유자다.
- BE는 C API를 호출하며 C 테이블을 직접 조회하지 않는다.
- 입력 manifest/hash 검증을 생략하지 않는다.
- 동일 source/posting의 충돌을 임의로 덮어쓰지 않는다.
- `canonical_job_id`만으로 cross-source 공고를 병합하지 않는다.
- `source_site:source_posting_id` identity 정책을 유지한다.
- Registry/parser/quality/requirements/aggregation 버전을 결과 identity에 포함한다.

### 4.2 `ACTIVE_MATCHING`

다음 현재 의미를 그대로 재현한다.

- 대상 직무가 반드시 존재한다.
- source 불일치, role 불일치, 명시적 CLOSED, `deadline <= as_of`, 미래 수집/게시,
  확정 지역/경력 불일치는 제외한다.
- 본문 미확보와 source record conflict는 matching 모집단에서 제외한다.
- 상태/지역/경력/게시일 UNKNOWN은 확정 불일치가 아니라 CONDITIONAL이다.
- 복수 지역은 교집합이 아니라 요청 지역 중 하나와의 overlap이다.
- 요구사항의 OR clause와 required level 의미를 보존한다.
- 기술 집계는 공고 ID 기준 distinct다. required/preferred/general은 겹칠 수 있고 total은
  세 집합의 합이 아니라 합집합이다.

### 4.3 `CURRENT_MARKET`의 의도적 의미 수정

현재 구현은 이름과 달리 CLOSED 및 deadline 경과 공고를 분모에서 제외하지 않는다.
제품 결정은 “현재 시장과 현재 노출 목록에서 확정 마감 공고가 보이면 안 된다”다.

신규 Projection 경로에서는 다음을 적용한다.

- `posting_status=CLOSED` 제외
- `deadline <= as_of` 제외
- 상태 UNKNOWN과 deadline 미상은 시장에 남기되 데이터 상태로 구분
- body/requirement 해석 실패는 분모에는 남기고 기술 count에는 해석된 관측만 반영
- source/region/career 범위 밖과 미래 관측은 기존처럼 분모에서도 제외

이는 단순 최적화가 아닌 계약 의미 변경이다. 다음을 함께 수행한다.

- demand aggregation/quality 계약 버전 증가
- 기존/신규 shadow 비교에서 CLOSED/deadline 차이는 별도 `EXPECTED_POLICY_DIFF`로 분류
- BE/FE의 `basis.asOf`, denominator와 기술 count를 새 결과에서 함께 사용
- `docs/ai/c-job-demand.md` 갱신

### 4.4 `MONTHLY_DEMAND`

- 1차 Projection Preview 전환 대상이 아니다.
- 당시 관측 수요이므로 현재 CLOSED 또는 마감 경과 공고를 포함한다.
- 완료된 서울 달력 월과 기존 posting date 정책을 유지한다.
- `CURRENT_MARKET`의 live 정책을 월별 Trend에 적용하지 않는다.

---

## 5. 목표 구조

```text
verified collector batches
        |
        v
prepare/classify/extract once
        |
        +------------------------------+
        |                              |
        v                              v
immutable job_fact              job_projection_version
full parsed requirements        BUILDING -> PUBLISHED/FAILED
and display payload                    |
                                      v
                              job_projection_job
                              searchable arrays/status/time
                                      |
                                      v
                              job_projection_head
                                      |
                  +-------------------+-------------------+
                  |                                       |
                  v                                       v
          demand preview query                     personalized compute
          no Snapshot INSERT                       existing path in phase 1
```

### 5.1 왜 완전 정규화하지 않는가

현재 검색 대상은 약 3천 공고다. 직무·지역·경력·기술은 다중 값이므로 배열이 자연스럽고,
상세 요구절과 원문 근거는 조회/계산 때 한 공고 단위로 함께 읽는다. 따라서 다음 하이브리드를
쓴다.

- 필터와 집계에 쓰는 값: typed column 또는 `text[]`
- 복잡한 요구절과 화면 상세: `job_fact.payload jsonb`
- 사용자별 평가: 기존 `matching_job` 계열

실제 `EXPLAIN ANALYZE`가 배열 unnest를 병목으로 증명할 때만 `job_technology` 자식 테이블을
추가한다.

---

## 6. 제안 DB 스키마

정확한 이름은 구현 중 기존 naming convention과 충돌 여부를 확인하되 의미와 제약은
아래를 유지한다. 새 migration은 기존 파일을 수정하지 않고
`BE/src/main/resources/db/c-compute/005_job_search_projection.sql`로 추가한다.

### 6.1 `c_compute.job_fact`

공고 내용 버전 하나를 한 번 저장한다.

| 열 | 타입/제약 | 의미 |
|---|---|---|
| `job_fact_id` | `char(64) PK` | canonical payload SHA-256 |
| `schema_version` | `varchar(64) NOT NULL` | 초기값 `job-fact/v1` |
| `job_key` | `varchar(256) NOT NULL` | `SOURCE:posting_id` |
| `source_site` | `varchar(32) NOT NULL` | 정규화 source |
| `source_posting_id` | `varchar(192) NOT NULL` | source identity |
| `content_hash` | `varchar(128) NOT NULL` | collector content hash |
| `registry_version` | `varchar(128) NOT NULL` | 기술 ID 해석 버전 |
| `parser_version` | `varchar(128) NOT NULL` | 분류/parser 버전 |
| `requirements_version` | `varchar(128) NOT NULL` | 요구절 추출 버전 |
| `payload` | `jsonb NOT NULL` | 불변 파싱/요구사항/표시 정보 |
| `payload_hash` | `char(64) NOT NULL` | 저장 무결성 |
| `created_at` | `timestamptz NOT NULL` | 최초 저장 |

제약:

- `UNIQUE(job_key, content_hash, payload_hash)`
- 동일 `job_fact_id` 재삽입은 payload/hash가 같을 때만 idempotent
- `job_fact_id`는 schema/job/content hash뿐 아니라 Registry/parser/requirements version과
  canonical payload를 함께 hash한다. 같은 원문이어도 해석 정책이 바뀌면 다른 fact다.
- runtime UPDATE/DELETE 금지
- 한 행 payload 최대 크기 검증 유지

### 6.2 `c_compute.job_projection_version`

| 열 | 타입/제약 | 의미 |
|---|---|---|
| `projection_version_id` | `varchar(80) PK` | 입력+정책 hash |
| `state` | `varchar(16) CHECK` | BUILDING/PUBLISHED/FAILED |
| `input_union_id` | `varchar(128) NOT NULL` | verified input lineage |
| `input_signature` | `char(64) NOT NULL` | 입력 집합 hash |
| `registry_version` | `varchar(128) NOT NULL` | Registry |
| `parser_version` | `varchar(128) NOT NULL` | classifier/parser |
| `quality_version` | `varchar(128) NOT NULL` | 품질 정책 |
| `requirements_version` | `varchar(128) NOT NULL` | 요구절 정책 |
| `aggregation_version` | `varchar(128) NOT NULL` | demand 정책 |
| `observed_at` | `timestamptz NOT NULL` | 입력 관측 시각 |
| `published_at` | `timestamptz NULL` | head 승격 시각 |
| `job_count` | `integer NOT NULL` | 검증 대상 수 |
| `build_stats` | `jsonb NOT NULL` | 중복/충돌/UNKNOWN/크기 통계 |
| `error_code` | `varchar(64) NULL` | 실패 원인 |

동일 `input_signature + compute versions`는 동일 version ID를 만든다. 시간이나 난수를 identity에
넣지 않는다.

### 6.3 `c_compute.job_projection_job`

| 열 | 타입/제약 | 의미 |
|---|---|---|
| `projection_version_id` | FK | 소속 버전 |
| `job_key` | `varchar(256)` | 안정 공고 ID |
| `job_fact_id` | FK | 계산·표시 payload 버전 |
| `source_site` | `varchar(32)` | source filter |
| `role_codes` | `text[]` | 표준 직무, 복수 가능 |
| `region_codes` | `text[]` | 표준 17지역, 복수 가능 |
| `region_state` | `varchar(16) CHECK` | KNOWN/NATIONWIDE/UNKNOWN |
| `career_codes` | `text[]` | ENTRY/EXPERIENCED 등 |
| `career_state` | `varchar(16) CHECK` | KNOWN/UNRESTRICTED/AMBIGUOUS/UNKNOWN |
| `posting_status` | `varchar(16) CHECK` | ACTIVE/CLOSED/UNKNOWN |
| `body_status` | `varchar(32) CHECK` | 기존 `BodyStatus` 전체 값 |
| `posted_at` | `timestamptz NULL` | 게시 시각 |
| `deadline` | `timestamptz NULL` | 종료 exclusive 경계 |
| `collected_at` | `timestamptz NOT NULL` | 관측 시각 |
| `required_tech_ids` | `text[]` | distinct sorted IDs |
| `preferred_tech_ids` | `text[]` | distinct sorted IDs |
| `general_tech_ids` | `text[]` | distinct sorted IDs |
| `quality_flags` | `text[]` | review/conflict 상태 |

기본키는 `(projection_version_id, job_key)`다. 배열은 null 대신 정렬된 빈 배열을 쓴다.
`source_record_id`, source URL, 회사명, 제목, 원문 region/career는 `job_fact.payload`에
보존한다.

PostgreSQL enum type은 사용하지 않는다. 정책 값 추가 시 type ALTER와 교차 배포가 묶이는 것을
피하려고 `varchar + CHECK`를 사용하며, 값 추가는 새 forward migration으로 수행한다.

### 6.4 `c_compute.job_projection_head`

| 열 | 타입/제약 | 의미 |
|---|---|---|
| `stream` | PK | 초기에는 `JOB_SEARCH` 하나 |
| `projection_version_id` | FK | 현재 PUBLISHED 버전 |
| `updated_at` | timestamptz | 승격 시각 |

head 교체는 version의 행 수/hash 검증과 같은 transaction에서 수행한다. BUILDING/FAILED
버전은 조회하지 않는다.

### 6.5 초기 인덱스

- `job_projection_job(projection_version_id, source_site)`
- `job_projection_job(projection_version_id, posting_status, deadline)`
- `GIN(role_codes)`
- `GIN(region_codes)`
- `GIN(career_codes)`
- 기술 배열 GIN은 detail/filter 요구가 생길 때 추가한다. demand aggregation은 필터 후
  `unnest`하므로 초기에는 `EXPLAIN ANALYZE` 결과로 결정한다.

다열 B-tree를 무작정 늘리지 않는다. 실제 selector 조합은 선택 항목이 가변적이고 PostgreSQL은
여러 인덱스를 bitmap AND/OR로 조합할 수 있다. 인덱스 채택은 운영과 같은 분포의
`EXPLAIN (ANALYZE, BUFFERS)`로 결정한다.

`deadline > now()` 형태의 partial index나 `is_active` generated column은 만들지 않는다.
현재 시각은 immutable expression이 아니며 시간이 지나도 자동 갱신되지 않는다. status와
deadline을 저장하고 요청의 `as_of`로 판정한다.

---

## 7. Materializer 설계

### 7.1 입력

새 parser를 만들지 않는다. `IntakeRunner`가 이미 검증하고 준비한 다음 결과를 재사용한다.

- verified input union
- deduplicated records
- classification
- requirements
- conflict set
- Registry/parser/quality/requirements versions

직무는 현재 `_matches_role()`이 요청마다 계산하므로 materialize 시 모든 표준 직무에 대해
한 번 계산해 `role_codes`에 저장한다. 지역·경력은 기존 `match_region`,
`match_career_level`과 동일한 normalization 함수를 공유한다. SQL용 별도 재구현으로 의미를
복제하지 않는다.

### 7.2 게시 절차

1. 입력 manifest와 hash를 기존 경로로 검증한다.
2. 결정론적 `projection_version_id`를 계산한다.
3. 이미 PUBLISHED인 동일 version이면 그대로 재사용한다.
4. version을 BUILDING으로 insert한다.
5. `job_fact`를 batch insert/COPY한다.
6. `job_projection_job`을 batch insert/COPY한다.
7. 행 수, job key uniqueness, payload hash, 배열 정렬, 통계 합계를 검증한다.
8. version을 PUBLISHED로 바꾸고 head를 같은 transaction에서 교체한다.
9. 실패하면 FAILED/error_code를 남기고 이전 head를 유지한다.

요청 thread에서 backfill/materialize하지 않는다. intake 완료 시 생성하며 preview는 PUBLISHED
head만 읽는다.

### 7.2.1 최초 backfill과 운영 명령

최초 배포와 장애 복구를 위해 one-shot 진입점을 추가한다.

```powershell
cd AI
& .\.venv\Scripts\python.exe -m worker.job_projection_backfill --dry-run
& .\.venv\Scripts\python.exe -m worker.job_projection_backfill --publish
```

신규 모듈 `AI/worker/job_projection_backfill.py`는 기존 intake source discovery, manifest/hash
검증, prepared union 생성 코드를 호출한다. Snapshot JSON을 역으로 읽어 Projection을 만들지
않는다. `--dry-run`은 DB를 변경하지 않고 version ID, 공고 수, source별 상태, 예상 insert/reuse,
오류를 출력한다. `--publish`는 materializer의 동일 함수를 호출하므로 자동 intake와 별도 의미를
갖지 않는다.

Worker 시작 시 head가 없다는 이유만으로 자동 backfill하지 않는다. DDL 적용과 입력 검증을
운영자가 확인한 뒤 명시적으로 실행한다. head가 없으면 projection mode는 404/fallback 정책을
따른다.

### 7.3 완전/불완전 수집

- complete full-active snapshot만 해당 source scope의 새 현재 상태를 확정한다.
- rate limit, partial collection, manifest/hash 실패는 기존 활성 공고의 부재를 CLOSED로
  해석하지 않는다.
- 불완전 source가 섞인 새 union은 기존 정상 source membership을 이어받거나 version 게시를
  보류한다. 선택은 기존 input union 정책과 source별 snapshot contract를 따른다.
- 명시적 CLOSED observation은 complete 여부와 별개로 CLOSED로 보존할 수 있지만 source
  conflict이면 review로 남긴다.

### 7.4 보유 정책

초기에는 다음만 보존한다.

- 현재 head
- 직전 정상 head 1개
- 진행 중인 compute/result가 참조하는 version
- 최근 7일 FAILED metadata(자식 행은 즉시 정리 가능)

참조 중인 `job_fact`는 삭제하지 않는다. 보유 기간과 참조 관계가 구현되기 전에는 자동 GC를
활성화하지 않는다.

---

## 8. Projection 조회 설계

1차에서는 `/internal/v1/c/job-demands/preview`만 새 조회를 사용한다.
`/internal/v1/c/job-cohorts/resolve`와 `/internal/v1/c/analyses/completed`는 기존
COHORT/DEMAND Snapshot 경로를 그대로 사용한다. 두 endpoint가 같은
`IntakeRunner.resolve_job_selector()`를 공유한다는 이유로 resolve 구현 전체를 Projection으로
바꾸면 개인 추천 계산 입력이 사라지므로 금지한다. preview 전용
`query_projected_demand(selector)` 경계를 추가한다.

### 8.1 요청 처리

1. 기존 `JobCohortResolveSelector`로 입력을 받는다.
2. 기존 함수로 criteria를 정규화한다.
3. head와 version compute metadata를 한 transaction snapshot에서 읽는다.
4. criteria에 맞는 `job_projection_job`을 필터링한다.
5. denominator와 matching/strict/review 통계를 계산한다.
6. 기술별 required/preferred/general job ID 집합을 만든다.
7. 기존 `_demand_rows()`와 동일한 rank/tie-break를 적용한다.
8. `DemandSnapshot`과 동일한 응답 DTO를 만들되 Snapshot INSERT는 하지 않는다.

preview 응답은 Snapshot ID를 외부로 반환하지 않으므로 BE 계약 변경이 필요 없다.

### 8.2 identity

조회 결과의 `cohort_id`는 다음 canonical hash로 만든다.

```text
projection_version_id
+ normalized criteria
+ quality/requirements/aggregation versions
+ live-market policy version
```

Preview identity는 저장 Snapshot을 의미하지 않는다. 같은 Projection과 criteria는 같은 ID를
만들어 basis와 로그 상관관계에 사용한다.

### 8.3 집계 주의사항

- 한 공고의 같은 기술은 category당 한 번만 센다.
- total은 category count의 합이 아니라 공고 ID 합집합이다.
- 한 공고가 required와 preferred에 동시에 있어도 total은 1이다.
- denominator가 0이면 ratio divide-by-zero가 없어야 한다.
- rank는 count 내림차순, `tech_id` 오름차순 tie-break다.
- category별 rank와 total rank를 각각 유지한다.
- CONDITIONAL 공고의 포함 여부는 기존 ACTIVE_MATCHING demand v3와 동일해야 한다.
- current market의 requirement 미해석 공고는 denominator에는 남지만 tech count에는 기여하지
  않는다.

---

## 9. Shadow 비교와 정확성 게이트

### 9.1 비교 모드

feature flag 예시:

- `C_JOB_DEMAND_PROJECTION_MODE=legacy|shadow|projection`

동작:

- `legacy`: 기존 Snapshot 경로만 사용
- `shadow`: 사용자 응답은 legacy, background/같은 요청에서 Projection 결과 비교
- `projection`: Projection 응답, 오류 시 자동 legacy fallback 여부는 별도 flag

fallback은 무한히 숨기지 않는다. 발생 횟수와 원인을 metric/log로 남긴다.

운영 shadow는 기본 1% 또는 명시 selector 검사로 제한한다. legacy 계산이 이미 수 초이므로
모든 사용자 요청에 두 경로를 동기 실행하지 않는다. 배포 전 100개 selector 비교는 별도 검증
명령으로 수행하고, 운영 shadow 결과가 응답 지연을 늘리지 않게 bounded executor/queue를 쓴다.
queue가 가득 차면 비교를 건너뛰고 `projection_shadow_skipped_total`을 증가시킨다.

### 9.2 비교 항목

- normalized criteria
- selected job ID set
- denominator/matching_count/input/duplicate/excluded/review count
- 기술 ID set
- required/preferred/general/total count
- 각 category ratio
- 전체/category rank
- status
- `as_of`

CURRENT_MARKET의 CLOSED/deadline 제외는 의도적 차이로 별도 집계한다. 그 밖의 차이는 모두
회귀다.

### 9.3 selector 매트릭스

- 5개 지원 직무 각각
- 지역 없음, 단일 지역, 복수 지역, 전국
- 신입, 경력, 신입+경력, 무관
- region/career UNKNOWN 공고 포함 입력
- posting status ACTIVE/CLOSED/UNKNOWN
- deadline 과거/정확히 as_of/미래/null
- body unavailable
- duplicate/source conflict
- multi-role/multi-region 공고
- required/preferred 중복 기술
- OR requirement clause
- 빈 결과와 min_jobs 미달
- CURRENT_MARKET 공식 source 제한

고정 fixture뿐 아니라 운영 최신 Projection에서 무작위 selector 최소 100개를 비교한다.

### 9.4 활성화 조건

다음을 모두 만족해야 `projection`으로 전환한다.

- 의도하지 않은 job ID 차이 0건
- 의도하지 않은 기술 count/rank 차이 0건
- 고정 테스트 100% 통과
- 운영 shadow 무작위 100개 100% 통과
- DB query p95 100ms 이하
- C endpoint cold p95 300ms 목표, 최대 1s 이하
- BE `/api/v1/job-demands` cold p95 500ms 이하
- build 실패 시 이전 head로 정상 조회
- worker restart 후 별도 warm-up 없이 동일 성능

---

## 10. 개인 추천·매칭 2차 설계

이 절은 1차 Preview 전환 후 착수한다. 1차 구현 중 기존 personalized compute를 변경하지
않는다.

### 10.1 유지해야 하는 일관성

한 result에서 다음은 같은 공고 집합을 사용해야 한다.

- demand denominator
- Gap 기술
- 추천 후보 순위
- current matching IDs/count
- What-if projected/new IDs/count
- 설명 문구에 포함되는 수치
- Job Match 평가와 목록

목록에서 CLOSED만 제거하고 저장 count를 그대로 반환하면 이 계약이 깨진다.

### 10.2 결과 저장

```text
user_result
  result_id
  user_id
  target_key
  evidence_version
  projection_version_id
  compute_contract_version
  status
  compact recommendation/gap/what-if metadata

user_result_head
  (user_id, target_key) -> current result_id

matching_job
  result_id + job_fact_id + personal assessment
```

새 결과의 모든 자식 행을 먼저 같은 transaction에 저장한 뒤 head를 교체한다. 계산 실패 시
기존 head를 유지한다.

### 10.3 target 전환

현재는 `(user_id, target_key)`별 최신 결과를 재사용한다. 이 기능을 유지한다.

- 사용자당 하나의 전역 current row로 축소하지 않는다.
- target별 최신 1개와 안전한 직전 1개를 보존한다.
- 오래된 target 결과는 LRU/TTL로 정리할 수 있지만 재선택 시 COMPUTING 상태를 정확히
  표시해야 한다.

### 10.4 마감 공고

- list/detail/What-if 조회는 현재 Projection active set과 result job IDs를 교집합한다.
- filter는 pagination 전 적용한다.
- total/count/hasNext도 같은 집합에서 계산한다.
- 평가 내용과 요구사항 표시는 계산 때 사용한 `job_fact_id`를 사용한다.
- 최신 공고 내용이 달라진 경우 과거 assessment와 최신 requirements를 섞지 않는다.
- Projection version이 바뀌면 result를 STALE로 표시하고 비동기 재계산한다.
- 새 결과 완료 전에는 이전 결과를 제공할 수 있지만 마감 공고는 숨기고 basis 시각을 유지한다.

### 10.5 idempotency 변경

기존 event ID의 `cohort_snapshot_id` 자리는 다음 input fingerprint로 대체한다.

```text
projection_version_id
+ normalized criteria hash
+ selected job membership hash
+ evidence_version
+ compute versions
+ BE contract version
```

동일 입력 재시도는 같은 event/result를 반환하고, Projection 또는 정책이 바뀌면 새 identity가
생겨야 한다.

### 10.6 구 Snapshot 호환

- 새 schema/version을 추가하고 구 RecommendationSnapshot validator를 수정하지 않는다.
- C read endpoint는 new result table을 우선하고 기존 snapshot ID는 legacy reader로 읽는다.
- BE는 교차 배포 기간 동안 두 ID 형식을 받을 수 있어야 한다.
- 구 결과 backfill은 가능한 것만 수행하며, 무결성 확인 없이 새 READY 결과로 승격하지 않는다.

---

## 11. 파일별 구현 지도

### 11.1 AI/C

| 파일 | 변경 |
|---|---|
| `AI/worker/store.py` | migration version 5, projection write/read transaction |
| `AI/worker/intake.py` | prepared union 완료 후 materializer 호출, report 확장 |
| `AI/worker/api.py` | preview Projection/shadow/flag 경로 |
| `AI/job/cohort.py` | 기존 normalization/role/quality 함수를 materializer와 공유 가능하게 분리 |
| `AI/job/demand.py` | 저장 Cohort 없이 projection 집계 결과를 동일 DTO로 구성 |
| `AI/job/projection.py` | 신규 모델, identity, materialization, query result 조립 |
| `AI/worker/projection_store.py` | 신규 DB persistence/query 경계 |
| `AI/job/matching.py` | 2차 active join 및 `job_fact_id` 참조 |
| `AI/recommendation/engine.py` | 2차 slim result schema 및 source lookup 분리 |

`cohort.py`의 기존 private 함수를 복사하지 않는다. 같은 normalization이 legacy와 projection에
공유되게 이름/위치를 정리하고 회귀 테스트를 유지한다.

### 11.2 DB

| 파일 | 변경 |
|---|---|
| `BE/src/main/resources/db/c-compute/005_job_search_projection.sql` | 신규 테이블/제약/인덱스/권한 |
| `BE/src/main/resources/db/c-compute/006_current_result.sql` | 2차 result pointer/ref 구조 |
| `BE/src/main/resources/db/c-compute/README.md` | 적용 순서와 rollback 설명 |

기존 `001~004`는 checksum 때문에 수정하지 않는다.

### 11.3 BE

1차에서는 C preview 응답 모양을 유지하므로 변경을 최소화한다.

| 파일 | 변경 가능성 |
|---|---|
| `JobDemandService.java` | 필요 시 basis/status additive 대응만 |
| `CComputeApi.java` | 계약이 유지되면 변경 없음 |
| `CComputeSyncService.java` | 2차 input fingerprint/result ID 전환 |
| `ComputeResultReader.java` | 2차 current/stale result 상태 |
| `JobMatchService.java` | 2차 active count/page 계약 |
| `SkillGapService.java` | 2차 slim result read |
| `WhatIfService.java` | 2차 활성 count/list 일치 |

### 11.4 FE

1차 필수 변경은 없다. 성능 안정화 후 다음을 검토한다.

- debounce 400ms -> 150~250ms A/B 측정
- basis/asOf 표시 유지
- 2차 STALE/COMPUTING 상태 문구
- 마감 공고 상세 접근 시 CLOSED/not-found 처리

---

## 12. 테스트 계획

### 12.1 단위 테스트

- projection identity 결정론
- 입력 순서 변경과 동일 재전달이 같은 version
- content/policy 변경이 다른 version
- 역할 alias/title regex 완전 동등
- 17지역 alias, 복수 지역, 전국, UNKNOWN
- 경력 혼합/무관/UNKNOWN
- deadline exclusive 경계와 timezone
- status ACTIVE/CLOSED/UNKNOWN
- required/preferred/general distinct와 total union
- build stats reconciliation
- BUILDING/FAILED version 조회 불가

### 12.2 PostgreSQL 통합 테스트

- migration 001~005 순차 적용
- 동일 migration checksum 및 version readiness
- 동일 version 재게시 idempotency
- 두 publisher 경합 시 head 한 개
- build 실패 시 이전 head 유지
- fact hash 충돌/불일치 거절
- 배열 index query 결과
- 0/3,000/50,000 공고 경계
- runtime role이 published fact/update/delete를 수행하지 못함

### 12.3 API 계약 테스트

- preview 200/202/404/422 의미 유지
- 응답 JSON additive/compatible
- BE `JobDemandService`가 legacy fallback과 projection 응답 모두 처리
- READY/PREPARING/INSUFFICIENT_DATA/EMPTY 상태
- limit/rank/basis 일치
- 다른 내부 endpoint와 인증 계약 변화 없음

### 12.4 2차 기능 회귀

- Skill Gap 기술과 근거 동일
- 추천 후보 순서와 tie-break 동일
- Job Match required/preferred verdict 동일
- What-if count와 ID/list 완전 일치
- 마감 후 list/detail/count 동시 제외
- 공고 내용 변경 시 과거 assessment와 최신 requirement 혼합 금지
- target A -> B -> A 전환
- Projection 교체 중 retry/idempotency
- 다른 사용자의 결과 404
- legacy Snapshot dual-read
- 월별 Trend 결과 불변

### 12.5 성능 테스트

동일 데이터와 selector 목록으로 legacy/projection을 각각 cold 실행한다.

- Worker 재시작 후 첫 요청
- exact selector 반복 10회
- 무작위 selector 100개
- 1/4/8 동시 요청
- 단일/복수 지역
- 데이터 3천/1만/5만 건 합성

수집 항목:

- C endpoint p50/p95/p99/max
- BE endpoint p50/p95/p99/max
- DB execution/planning time, buffers, returned rows
- materialization time/bytes/rows
- Python RSS/tracemalloc peak
- Snapshot INSERT count와 bytes
- cache hit/miss
- error/fallback/mismatch rate

---

## 13. 관측 항목

최소 다음 구조화 로그/metric을 추가한다.

- `projection_version_id`
- `projection_state`
- `projection_build_duration_ms`
- `projection_publish_lag_seconds`
- `projection_job_count`
- `projection_fact_inserted/reused`
- `projection_query_duration_ms`
- `projection_query_selector_hash`
- `projection_shadow_mismatch_total{kind}`
- `projection_fallback_total{reason}`
- `projection_build_failure_total{reason}`
- active/closed/unknown/deadline-expired 공고 수
- source별 complete/partial 입력 상태

기존 `/health`가 green이어도 public intake 일부가 `TypeError`로 실패한 운영 사례가 있다.
Projection readiness는 process health와 분리한다.

readiness 조건:

- migration version 충족
- PUBLISHED head 존재
- head version 행 수/hash 검증 성공
- publish lag 허용 범위 이내

public source 일부 실패는 전체 process DOWN 대신 degraded metric으로 노출하되, 해당 실패가
Projection publish 정책에 미친 영향을 기록한다.

---

## 14. 배포 계획

### 14.1 사전 준비

- 현재 DB backup 및 restore 절차 확인
- 서비스 디스크 여유 확인
- migration 005 실행 시간 사전 측정
- 신규 테이블 예상 크기 기록
- feature flag 기본 `legacy`
- 구/신 결과 비교용 selector fixture 확정

### 14.1.1 C migration runner 제약

`c-compute` DDL은 Flyway가 아니라 `python -m worker.migrate`가 명시적으로 적용한다.

- `AI/worker/store.py`의 `MIGRATION_VERSION`을 4에서 5로 올린다.
- `MIGRATION_FILES` 끝에 005 경로를 추가한다.
- 적용 이력과 checksum은 `c_compute.schema_version`에 남긴다.
- 기존 001~004는 절대 수정하지 않는다.
- runner는 transaction advisory lock `331029`, `statement_timeout=15s`를 사용한다.
- runtime 연결은 `statement_timeout=15s`, `lock_timeout=5s`다.

따라서 005의 각 DDL은 staging/운영 유사 데이터에서 15초 이내인지 먼저 확인한다. 15초를
넘는 index가 필요하면 transaction runner 안에서 `CREATE INDEX CONCURRENTLY`를 억지로
실행하지 않는다. 초기 테이블은 비어 있으므로 migration에서 기본 index를 만들고 backfill 전에
완료하는 방식을 우선한다. 운영 데이터가 들어간 뒤의 추가 index는 별도 승인된 runbook과
maintenance 절차로 실행한다.

### 14.2 순서

```text
1. migration 005 적용
2. legacy-compatible Worker 배포
3. Projection backfill/materialize
4. head 검증
5. mode=shadow
6. 무작위 100 selector 동등성 및 성능 검증
7. mode=projection (내부/일부 트래픽)
8. 전체 활성화
9. 24시간 관측
10. 2차 personalized result 작업 시작
```

Worker가 migration 005를 요구하는 readiness를 먼저 배포해서는 안 된다. 다음 중 하나를 쓴다.

- migration 선적용 후 Worker 배포
- 또는 Worker가 4/5 모두 읽을 수 있는 교차 배포 버전을 먼저 배포

### 14.3 롤백

Projection 장애 시:

1. `C_JOB_DEMAND_PROJECTION_MODE=legacy`
2. Worker 재시작/설정 reload
3. 기존 Snapshot preview 경로 확인
4. 실패 version은 FAILED로 남기고 head를 이전 정상 version으로 복구
5. 신규 테이블은 즉시 삭제하지 않음

롤백 동안 legacy COHORT/DEMAND 생성이 계속 가능해야 한다. 1차 안정화 전에는 기존 코드와
테이블을 제거하지 않는다.

### 14.4 데이터 정리

다음이 모두 끝난 뒤에만 구 payload 정리를 시작한다.

- Projection 7일 이상 정상 운영
- legacy fallback 0 또는 승인된 수준
- personalized result 2차 전환 완료
- Registry review FK 이전 완료
- BE `user_c_snapshot` 참조 이전 완료
- 복구 rehearsal 성공

대량 DELETE만으로 OS 디스크가 즉시 반환된다고 가정하지 않는다. 새 테이블 전환,
`VACUUM FULL` 또는 운영에 맞는 compaction은 별도 점검과 maintenance window를 필요로 한다.

---

## 15. Jira·브랜치·커밋 및 MR 구성

### 15.1 Jira 등록 내용

- Jira: [S15P21E102-360](https://ssafy.atlassian.net/browse/S15P21E102-360)
- 이슈 유형: `작업`
- 라벨: `AI`, `Back`, `C`, `Feat`
- 담당자: 이송민
- 제목: `[AI/BE] 공고 검색 Projection 기반 수요·추천 조회 최적화`
- 관련 이슈: `S15P21E102-334`
- 선행 반영 확인: `S15P21E102-352`, `S15P21E102-353`

설명 본문:

```text
배경
- S15P21E102-334에서 계산 입력 재사용과 API 왕복을 줄였지만, 직무·지역·경력 변경 시
  cold 수요 조회는 여전히 4.3~10.5초, 최대 30초가 걸린다.
- 요청마다 대형 COHORT Snapshot을 생성·직렬화·저장하는 구조가 병목이다.

목표
- 공고별 정규화 결과를 한 번 저장하고 versioned search projection으로 게시한다.
- demand preview는 published projection을 조회하여 C p95 300ms, BE p95 500ms 이내로 줄인다.
- 기존 추천·매칭·What-if 결과 의미와 legacy rollback 경로를 유지한다.
- 이후 같은 MR 안에서 현재 사용자 결과 포인터와 active posting 필터를 도입해 대형 Snapshot
  중복을 줄인다.

범위
- c_compute migration 005와 projection/fact/head schema
- backfill/materialize/publish 명령 및 원자적 head 전환
- legacy|shadow|projection feature flag와 동등성/성능 계측
- preview 조회 전환, BE cache 계약 정합화
- 현재 결과 포인터, active matching/What-if 일관성, payload 경량화
- 배포·롤백·보존/정리 runbook 및 회귀 테스트

완료 조건
- legacy 대비 의도하지 않은 job id/count 차이 0건
- 무작위 selector 100개 shadow 비교 통과
- projection DB p95 100ms, C endpoint cold p95 300ms, max 1s 이내
- BE 사용자 응답 p95 500ms 이내
- 월별 Trend, 추천, 매칭, What-if 회귀 테스트 통과
- 재시작 후 warm cache 없이 목표 성능 충족
- feature flag만으로 legacy 경로 롤백 가능
- migration/backfill/publish/rollback/restore rehearsal 문서화

제외
- 원본 수집기 재작성
- 기존 Snapshot 즉시 삭제
- Registry review 및 과거 감사 데이터의 즉시 제거
```

### 15.2 브랜치 준비 명령

현재 브랜치는 아래 절차로 생성했다.

```powershell
git fetch --prune origin
git switch develop
git pull --ff-only origin develop
git switch -c feat/S15P21E102-360-branch
git status --short --branch
```

브랜치를 원격에 처음 올릴 때는 첫 커밋과 검증이 끝난 뒤 다음을 실행한다.

```powershell
git push -u origin feat/S15P21E102-360-branch
```

### 15.3 단일 MR의 커밋 경계

`S15P21E102-334`의 아래 세 커밋은 변경 요약이 영어였지만, 이는 이전 본인 작업의 주된
관례와 다르다.

- `[S15P21E102-334] AI: reuse prepared job cohort inputs`
- `[S15P21E102-334] C/BE: reduce matching and demand round trips`
- `[S15P21E102-334] FE: prefetch matching pages and cache demand queries`

그 이전 본인 작업은 `[Jira 키] feat/fix/bug/test/docs: 한글 설명`을 주로 사용했다. 예시는
`[S15P21E102-294] feat: 실제 비교 공고 전체를 수요·추천·매칭에 반영`,
`[S15P21E102-311] test: 결과 계약 경계 회귀 테스트 갱신`이다. 이번 작업은 이 한글 관례를
따른다.

1. `[S15P21E102-360] docs: 공고 검색 Projection 전환 계획과 인수 기준 문서화`
2. `[S15P21E102-360] feat: 공고 검색 Projection 스키마 추가`
3. `[S15P21E102-360] feat: 검색용 공고 Projection 생성·게시`
4. `[S15P21E102-360] test: 기존 수요 계산과 Projection 동등성 검증`
5. `[S15P21E102-360] feat: 게시된 Projection 기반 수요 미리보기 조회`
6. `[S15P21E102-360] feat: Projection shadow 계측과 기능 플래그 추가`
7. `[S15P21E102-360] fix: BE 수요 캐시와 Projection 계약 정합화`
8. `[S15P21E102-360] feat: 버전형 현재 사용자 결과 포인터 추가`
9. `[S15P21E102-360] feat: 현재 매칭·What-if에서 활성 공고만 반영`
10. `[S15P21E102-360] test: 활성 결과와 payload 경량화 회귀 검증`
11. `[S15P21E102-360] docs: Projection 배포·롤백 runbook 추가`

불필요하게 AI/BE/TEST를 한 커밋에 섞지 않는다. 각 커밋은 단독으로 테스트 가능하거나 다음
커밋 전까지 production 경로에서 비활성인 상태여야 한다. schema와 runtime 코드는 호환 순서를
지키며, 중간 커밋에서도 기존 서비스 경로를 깨지 않는다.

### 15.4 단일 MR 작성 형식

- MR 제목: `[S15P21E102-360] AI/BE: 공고 검색 Projection 기반 수요·추천 조회 최적화`
- source: `feat/S15P21E102-360-branch`
- target: `develop`
- 관련 Jira: 실제 Jira 링크
- MR은 하나만 생성한다.
- Phase 1과 Phase 2는 커밋 및 feature flag로 구분한다.
- Projection 활성화는 Phase 1 gate 통과 후, personalized 결과 활성화는 Phase 2 gate 통과 후 한다.

MR 본문은 최소한 다음 순서를 사용한다.

1. 배경과 기존 병목
2. 변경 요약(Projection / preview / personalized result)
3. 의도적으로 유지한 기존 의미
4. 의도적으로 바꾼 CURRENT_MARKET 마감 정책
5. migration·backfill·배포 순서
6. feature flag와 rollback
7. 테스트 명령 및 실제 결과
8. 성능 Before/After
9. 환경 변수 변경
10. 미완료 또는 후속 관측 항목

---

## 16. 예상 효과와 중단 기준

### 16.1 예상치

다음은 현재 운영 데이터 규모에 기반한 추정이며 인수 결과가 아니다.

| 영역 | 현재 | 예상/목표 |
|---|---:|---:|
| demand cold | 4.3~10.5s, 최대 30s | C p95 <=300ms, BE p95 <=500ms |
| demand cache hit | 약 34ms | 30~100ms, 큰 변화 없음 |
| Snapshot 직렬화/INSERT | 요청당 최대 7~13MB급 | Preview에서는 0 |
| Recommendation 조회 | 평균 약 1.3s | 2차 후 200~500ms 추정 |
| Skill Gap 조회 | 평균 약 3.9s | 2차 후 300~800ms 추정 |
| Job Match 조회 | 평균 약 0.6s | 2차 후 200~400ms 추정 |
| Snapshot/링크 저장량 | 약 1.5GB | 장기적으로 약 0.9~1.2GB 감소 가능 |

### 16.2 중단/재설계 기준

- Projection query p95가 1s를 넘음
- legacy와 비의도 job ID 차이가 1건이라도 있음
- role/region/career UNKNOWN 의미를 동일하게 표현할 수 없음
- incomplete collection에서 대량 공고 소멸 발생
- materialization이 intake 주기보다 오래 걸림
- dual-write로 디스크 사용률 90% 초과 예상
- migration/index 생성이 허용 downtime을 초과

이 경우 인덱스를 무조건 추가하지 않고 `EXPLAIN ANALYZE`, 데이터 분포, materialized 배열
크기를 먼저 확인한다. 필요하면 기술 배열만 자식 테이블로 분리한다.

---

## 17. 위험 등록부

| 위험 | 영향 | 방지/탐지 |
|---|---|---|
| legacy/projection 의미 drift | 잘못된 추천·수요 | job ID 및 count shadow 100% 비교 |
| 부분 publish | 일부 공고만 조회 | BUILDING 후 원자 head swap |
| incomplete 수집을 폐쇄로 오인 | 정상 공고 대량 소멸 | complete snapshot만 부재 확정 |
| CURRENT_MARKET 정책 변경 혼입 | 수치가 갑자기 변함 | version bump, expected diff 분리 |
| deadline timezone/off-by-one | 당일 공고 조기 제외 | 서울/UTC 경계 테스트 |
| 최신 상세와 과거 평가 혼합 | 매칭 근거 오류 | immutable `job_fact_id` 참조 |
| 조회 필터만 바꿔 count 불일치 | What-if/KPI 오류 | 같은 active set으로 count/page 계산 |
| compute 중 head 변경 | 입력 혼합 | 시작 시 projection version pinning |
| retry identity 충돌 | 409/중복 계산 | 결정론적 input fingerprint |
| target 결과 하나로 덮어쓰기 | A->B->A 재사용 상실 | `(user,target_key)`별 head |
| 기존 FK가 Snapshot 삭제 방해 | migration/GC 실패 | review/matching 참조 선이전 |
| TOAST 삭제 후 디스크 미반환 | 용량 개선 착시 | 실제 relation size와 compaction 계획 |
| 인덱스 과다 | write/build 지연 | 최소 인덱스 후 실측 추가 |
| public intake false-green | stale projection | 별도 source/degraded/readiness metric |
| 교차 배포 계약 불일치 | 404/500 | dual-read, additive contract, flag |

---

## 18. 완료 정의

### 18.1 1차 완료

- [ ] migration 005가 신규/기존 DB에서 적용된다.
- [ ] 기존 migration checksum을 변경하지 않았다.
- [ ] 최신 verified input으로 PUBLISHED Projection을 만들 수 있다. (로컬 materialize 검증 완료,
  격리 PostgreSQL publish는 DSN 부재로 미실행)
- [ ] build 실패가 기존 head를 바꾸지 않는다.
- [x] legacy/projection 동등성 테스트가 의도적 live 정책 차이 외 전부 일치한다.
- [ ] 운영 shadow 100 selector가 통과한다.
- [ ] C cold p95 <=300ms, max <=1s다.
- [ ] BE cold p95 <=500ms다.
- [ ] Worker restart 후 첫 조회가 목표를 만족한다.
- [x] Preview가 COHORT/DEMAND Snapshot을 새로 INSERT하지 않는다.
- [ ] legacy flag 롤백을 실제로 실행해 검증했다.
- [ ] 문서와 dashboard/runbook이 갱신됐다. (문서·runbook·readiness/구조화 로그 완료,
  운영 dashboard 연결은 미실행)

### 18.2 2차 완료

- [x] 마감 공고가 list/detail/What-if에서 동시에 제외된다.
- [x] count, ID, 목록, pagination이 같은 active 집합을 사용한다.
- [x] Skill Gap/추천/매칭이 같은 result identity를 공유한다.
- [ ] 새 result publish가 원자적이고 실패 시 기존 결과가 남는다.
- [ ] target A->B->A가 정상 동작한다.
- [x] legacy Snapshot 사용자 조회가 유지된다.
- [x] 월별 Trend가 변경되지 않는다.
- [ ] COHORT/Recommendation payload 제거 전 참조 audit가 0이다.
- [ ] retention/GC dry-run과 restore rehearsal이 성공한다.

---

## 19. 구현 시작 전 남은 확인 사항

다음은 문서가 빠져서가 아니라 구현 시 값만 확정하면 되는 항목이다.

- Jira 번호: `S15P21E102-360`으로 확정·반영 완료
- 운영 feature flag 전달 방식(env/config)
- Projection publish lag 허용값(초기 제안: 수집 완료 후 5분)
- target별 결과 TTL/보유 개수(초기 제안: 최신+직전, 30일 미사용 정리)
- CURRENT_MARKET 계약 버전 이름
- maintenance window와 실제 DB backup 위치

이 값들은 핵심 구조를 바꾸지 않는다. Jira 번호를 제외한 값은 보수적인 기본값으로 구현한
뒤 설정 가능하게 둔다.

---

## 20. 검증 명령

환경 변수와 비밀 값은 각 기존 runbook을 사용하며 명령이나 로그에 출력하지 않는다.

### 20.1 AI

```powershell
cd AI
& .\.venv\Scripts\python.exe -m pytest tests/test_job_cohort.py -q
& .\.venv\Scripts\python.exe -m pytest tests/test_current_market_demand.py -q
& .\.venv\Scripts\python.exe -m pytest tests/test_job_demand.py -q
& .\.venv\Scripts\python.exe -m pytest tests/test_job_union_intake.py -q
& .\.venv\Scripts\python.exe -m pytest tests/test_job_projection.py -q
& .\.venv\Scripts\python.exe -m pytest tests/test_job_projection_store.py -q
& .\.venv\Scripts\python.exe -m pytest
```

신규 테스트 파일명은 위 이름을 사용한다. 저장소 통합 테스트는 격리 PostgreSQL DSN을 사용하고
운영 DB에는 쓰지 않는다.

### 20.2 BE

```powershell
cd BE
.\gradlew.bat test
```

### 20.3 FE

1차에서 FE를 수정하지 않아도 회귀 확인을 수행한다.

```powershell
cd FE
npm test
npm run lint
npm run build
```

### 20.4 문서와 diff

```powershell
git diff --check
git status --short
```

운영 전에는 `--dry-run`, migration version 5, `/ready`, Projection head, shadow mismatch,
legacy rollback을 순서대로 확인한다.

### 20.5 2026-09-20 로컬 최종 검증 결과

- 최신 `develop` 병합 후 AI Python 3.12 전체 테스트: `3769 passed, 139 skipped`
- 이번 변경 Python 파일 Ruff: 통과
- 최신 `develop` 병합 후 BE 전체 테스트: `618 passed, 1 skipped, 1 failed`
  - 실패 1건은 로컬 PostgreSQL 미기동으로 인한 기존 `GitJobApplicationTests.contextLoads()`의
    connection refused다.
- BE 변경 서비스 집중 테스트: 통과
- FE 테스트: `241 passed`
- FE lint: 통과. 기존 `CountUp.tsx` 경고 1건은 유지된다.
- FE build/typecheck: 통과. 기존 chunk size 경고는 유지된다.
- Docker Compose config와 `git diff --check`: 통과

현재 환경에는 `C_COMPUTE_TEST_DATABASE_URL`이 없고 Docker daemon도 실행할 수 없으므로,
PostgreSQL migration/publish 원자성 통합 테스트와 운영 데이터 shadow·성능·rollback·restore gate는
수행하지 않았다. 해당 항목은 완료로 간주하지 않으며 이 문서의 체크박스와 runbook 순서를 유지한다.

---

## 21. 조사 근거

설계 판단에 사용한 PostgreSQL 16 공식 문서다.

- JSONB GIN과 expression index:
  <https://www.postgresql.org/docs/16/datatype-json.html#JSON-INDEXING>
- 배열 `&&`, containment을 지원하는 GIN operator class:
  <https://www.postgresql.org/docs/16/gin-builtin-opclasses.html>
- 다열 index의 leftmost 특성과 과도한 다열 index 주의:
  <https://www.postgresql.org/docs/16/indexes-multicolumn.html>
- 여러 index의 bitmap AND/OR 결합:
  <https://www.postgresql.org/docs/16/indexes-bitmap-scans.html>
- partial index 적용 조건과 과도한 partial index 주의:
  <https://www.postgresql.org/docs/16/indexes-partial.html>
- generated column은 immutable expression만 허용:
  <https://www.postgresql.org/docs/16/ddl-generated-columns.html>
- 큰 JSONB의 TOAST 압축/out-of-line 저장:
  <https://www.postgresql.org/docs/16/storage-toast.html>
- Materialized View와 전체 refresh/concurrent 제약:
  <https://www.postgresql.org/docs/16/rules-materializedviews.html>
  <https://www.postgresql.org/docs/16/sql-refreshmaterializedview.html>
- 실제 plan/runtime/buffer 확인:
  <https://www.postgresql.org/docs/16/sql-explain.html>

외부 문서는 일반 기능의 근거로만 사용한다. 최종 인덱스와 성능 판정은 이 서비스의 운영 분포와
동일한 데이터에서 측정한 결과를 우선한다.

---

## 22. 문서 자체 점검

| 점검 질문 | 포함 위치 | 결과 |
|---|---|---|
| 왜 바꾸는가와 실측 기준이 있는가 | §2 | 포함 |
| 첫 MR과 후속 범위가 구분되는가 | §3, §15 | 포함 |
| 기존 ACTIVE_MATCHING 의미가 고정됐는가 | §4.2 | 포함 |
| CURRENT_MARKET 의도적 변경이 분리됐는가 | §4.3 | 포함 |
| 월별 Trend가 보호되는가 | §4.4 | 포함 |
| 구현 가능한 스키마와 제약이 있는가 | §6 | 포함 |
| parser 재사용 및 초기 backfill 방법이 있는가 | §7 | 포함 |
| preview와 personalized resolve 경계가 분리되는가 | §8 | 포함 |
| 동등성 검증이 count가 아닌 job ID까지 보는가 | §9 | 포함 |
| 추천/매칭/What-if 일관성이 보호되는가 | §10 | 포함 |
| 수정 파일을 찾을 수 있는가 | §11 | 포함 |
| 단위/통합/API/성능 테스트가 있는가 | §12, §20 | 포함 |
| 관측/readiness가 있는가 | §13 | 포함 |
| migration 제약과 배포 순서가 있는가 | §14 | 포함 |
| 롤백이 기존 경로로 실제 가능한가 | §14.3 | 포함 |
| 커밋/MR 단위가 있는가 | §15 | 포함 |
| 예상 효과와 중단 기준이 구분되는가 | §16 | 포함 |
| 위험과 대응이 있는가 | §17 | 포함 |
| 완료 조건이 체크리스트인가 | §18 | 포함 |
| 미확정 값이 드러나 있는가 | §19 | 포함 |
| 공식 조사 근거가 기록됐는가 | §21 | 포함 |

구현 중 새 사실이 이 문서와 충돌하면 코드를 억지로 문서에 맞추지 않는다. 재현 근거와 영향
범위를 기록하고 이 문서를 먼저 갱신한 뒤 진행한다.

---

## 23. 구현자가 지켜야 할 최종 원칙

1. Preview 성능 문제를 해결하기 위해 개인 추천 계약까지 동시에 바꾸지 않는다.
2. 캐시는 Projection의 대체재가 아니라 Projection 위의 선택적 가속 계층이다.
3. 사용자 요청마다 파싱·직무 분류·요구사항 추출을 하지 않는다.
4. 검색 조합별 Snapshot을 저장하지 않는다.
5. CLOSED/deadline 정책과 월별 역사 정책을 섞지 않는다.
6. 새 결과가 완성되기 전에 기존 정상 head를 지우지 않는다.
7. 동등성은 count만이 아니라 공고 ID 집합으로 증명한다.
8. 성능 개선은 같은 데이터·조건의 before/after 측정으로 증명한다.
9. 구 Snapshot 삭제는 마지막 단계이며 참조 audit와 복구 rehearsal 전에는 실행하지 않는다.
10. 예상치가 아닌 인수 기준을 만족했을 때만 기능 플래그를 전환한다.

---

## 24. MR !270 독립 리뷰 보완 작업

2026-09-20 AI/데이터, BE/API, PostgreSQL/운영 독립 리뷰에서 확인된 결함을 다음 순서로
보완한다. 기존 005·006 migration은 checksum 호환을 위해 수정하지 않고 forward-only 007을
추가한다.

### 24.1 계약 및 저장 계층

- [x] BE의 정규화된 논리 `targetKey`를 `AnalysisCompleted`에 additive optional 필드로 전달한다.
- [x] 구 BE 요청은 기존 stream hash로 fallback하고 새 요청은 `(user_id, target_key)` head를 쓴다.
- [x] transport capability는 resolve 응답에만 광고하고 cohort/input identity hash에 포함하지 않는다.
- [x] 구 C 결과는 fallback contract로 구분하며, 복구 batch에서 미결과 사용자를 먼저 처리한다.
- [x] `user_result_head`에 원본 event 순서를 저장하고 역순 완료가 current/previous를 바꾸지 않게 한다.
- [x] Projection fact별 immutable matching source 테이블을 추가하고 신규 결과는 동일 fact만 복원한다.
- [x] legacy NULL fact 행은 기존 source 경로로 계속 읽는다.
- [x] 006의 non-null fact source를 007에서 backfill하고 신규 FK를 validate한다.
- [x] Projection head publish는 관측 시각 기준 단조 증가하고 동시 publish에서 역행하지 않는다.

### 24.2 읽기 및 교차 배포 호환

- [x] Projection stale 판정은 `C_JOB_MATCHING_ACTIVE_MODE=projection`일 때만 적용한다.
- [x] `c-*` 조회도 연결된 `user_result`를 먼저 찾아 READY/STALE과 재계산 계약을 보존한다.
- [x] compact result에 UI가 사용하는 최소 추천 explanation을 유지한다.
- [x] matching page/detail은 full Recommendation payload를 기본 조회하지 않고 legacy ID만 필요 시 보충한다.
- [x] legacy `current_job_ids`의 누락·null·잘못된 타입을 구분하고 손상 데이터를 제어된 무결성 오류로 처리한다.
- [x] migration 전 matching 결과는 active `current_count`를 0으로 덮어쓰지 않는다.
- [x] in-memory Projection cohort는 선택된 `projection.jobs`의 fact만 사용한다.

### 24.3 운영 안전성

- [x] 명시적 backfill은 HDFS source별 목록/다운로드 실패와 manifest 부재를 fail-closed 처리한다.
- [x] migration/publish Runbook은 data 서버 root, `.env.data`, base+cluster overlay와 `C_COMPUTE_DATABASE_URL`을 명시한다.
- [x] 환경 변수 변경은 `restart`가 아닌 container 재생성 절차로 반영한다.
- [x] 006 적용 전 행 수·relation size·lock 대기·maintenance window preflight를 문서화한다.
- [x] migration runner에 5초 lock timeout을 적용하고 007의 block/audit 이력을 immutable로 보존한다.
- [x] 일반 publish와 명시적 rollback 경로를 분리하고 rollback은 CAS·audit·blocked target 검증을 남긴다.

### 24.4 테스트와 완료 조건

- [x] target A→B→A와 같은 target의 Projection 변경에도 head key가 유지된다.
- [x] legacy/projection 모드별 NULL Projection stale 판정이 기대와 일치한다.
- [x] 같은 cohort/job의 Projection A→B→A가 각 계산 당시 fact를 복원한다.
- [x] 늦게 완료된 과거 event와 동시 Projection publish가 head를 역행시키지 않는다.
- [x] `c-*`/`ur-*` 양쪽에서 explanation과 stale 재계산 계약이 같다.
- [x] migration 전 matching 행의 count와 source fallback이 유지된다.
- [x] source partial/실패 backfill은 publish 전에 실패한다.
- [x] 001~006 legacy fact-linked 행을 seed한 후 007 backfill·FK validation을 실제 PostgreSQL에서 검증한다.
- [x] Windows/Linux에서 분석 파일 순서와 evidence 선택이 같다.
- [x] 변경 AI·BE 집중 테스트와 전체 회귀를 통과한다.
- [x] 서브 에이전트가 독립 테스트와 재리뷰를 수행하고 P1/P2 잔여가 없다.

최종 로컬 검증(2026-09-20): Python 3.12 Linux 전체 `3777 passed, 154 skipped`,
격리 PostgreSQL 16 집중 `291 passed, 7 skipped`, BE 전체 `623 tests, 1 skipped`,
FE Node 22 `241 passed` 및 production build 성공. skip은 선택 외부 서비스·별도 DB
환경 조건을 요구하는 기존 테스트이며, PostgreSQL 계약은 별도 격리 DB suite로
보완했다. Ruff 변경 파일 검사와 `git diff --check`도 통과했다.

### 24.5 커밋 경계

1. 계약·007 migration·head/source 원자성
2. stale/dual-read/payload/count/Projection cohort 회귀 수정
3. HDFS coverage gate·rollback CLI·Runbook
4. 회귀 테스트와 문서 완료 체크
