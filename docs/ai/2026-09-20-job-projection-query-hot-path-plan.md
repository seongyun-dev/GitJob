# 공고 Projection 조회 Hot Path 및 개인화 전환 보완 계획

- 작성일: 2026-09-20
- 기준 브랜치: `feat/S15P21E102-363-query-hot-path`
- 기준 commit: `11d58d5`
- 관련 Jira: `S15P21E102-360`, 후속 실행 Jira `S15P21E102-363`
- 관련 MR: 병합 완료된 `!270`
- 상태: 구현 진행, 로컬 검증 결과는 같은 문서의 완료 정의와 실행 기록으로 관리
- 목적: 이 문서를 후속 보완 작업의 단일 실행 기준(Source of Truth)으로 사용한다.

이 문서는 이미 병합된 Projection 구조를 폐기하거나 다시 설계하는 계획이 아니다. 현재
Projection 경로가 요청마다 전체 공고 payload를 읽고 Python 객체와 Cohort를 재구성하여 남긴
병목을 제거하고, 아직 운영에서 활성화되지 않은 현재 사용자 결과를 안전하게 전환하는 계획이다.

---

## 1. 결정 요약

1. 기존 MR `!270`의 Projection/fact/head/current-result 구조를 유지한다.
2. Preview와 개인화 계산의 조회 경계를 분리한다.
3. Preview는 typed Projection 열과 Current Market job/pair sidecar만 SQL로 집계한다.
4. Preview에서는 `job_fact.payload`, Pydantic 공고 객체, `JobCohort`를 만들지 않는다.
5. 개인화 계산은 고정된 Projection version에서 선택된 공고 fact만 복원한다.
6. `ACTIVE_MATCHING`과 `CURRENT_MARKET`의 서로 다른 데이터 의미를 SQL에 그대로 보존한다.
7. 월별 역사 Trend는 현재 시장 Projection으로 대체하지 않는다.
8. 새 SQL 경로는 기존 Projection flag와 별도인 query-engine flag로 전환한다.
9. 개인화 결과는 기존 Evidence를 우선 재사용하며 모든 사용자에게 재분석을 요구하지 않는다.
10. 기존 Snapshot 삭제와 compaction은 이번 작업 범위가 아니다.
11. 후속 Jira 1건, 작업 MR 1개를 사용하고 커밋과 feature flag로 단계만 나눈다.
12. 이미 공유·병합된 history를 rebase/force-push하지 않는다.
13. 모든 selector 조합을 사전 계산하지 않고, 공고별 typed projection과 필요한 최소 sidecar만
    게시한다.
14. Projection head가 바뀌면 C server cache는 version을 포함한 identity로 이전 응답을 재사용하지
    않는다. FE의 기존 bounded stale/poll window는 별도로 측정한다.
15. 개인화의 Projection 계산 생성과 사용자 조회 활성화를 서로 다른 flag로 분리한다.
16. terminal compute attempt는 삭제/무조건 재시도하지 않고 exact identity CAS와 감사 기록으로만
    재개한다.

---

## 2. 확인된 현재 상태

### 2.1 Git과 배포 상태

2026-09-20 확인 결과:

| 항목 | 확인 값 |
|---|---|
| 병합된 Projection commit | `6b5960c` |
| 최신 `origin/develop` | `11d58d5` |
| 서비스 서버 checkout | `6b5960c` |
| 데이터 서버 checkout | `6b5960c` |
| 기존 로컬 작업 tip | `2880bc2` |
| 기존 원격 작업 브랜치 | 삭제됨 |

`2880bc2`와 squash merge commit `6b5960c`의 tree diff는 없다. 따라서 기존 작업 내용은 모두
develop에 들어갔으며, 옛 브랜치에서 작업을 이어가면 안 된다. 최신 develop 이후 미배포 commit은
다음과 같다.

| commit | 내용 | 영향 |
|---|---|---|
| `d8cc297` | Current Market 마감·종료 공고 계약 테스트 | 새 SQL 경로의 필수 회귀 기준 |
| `e22e641` | repo fetch throughput metric 테스트 수정 | 이번 범위와 독립 |
| `11d58d5` | Recommendation explanation의 `matching_jobs` 조회 불일치 수정 | 개인화 전환 전 반드시 포함 |

위 commit은 C migration, BE, FE, Compose 계약을 변경하지 않는다. 최신 develop에서 Projection,
Current Market, 추천 explanation, matching 관련 집중 테스트는 `90 passed, 31 skipped`였다.

Windows local ref는 HEAD가 `refs/heads/feat/...`를 가리키지만 실제 저장 ref가 `refs/heads/Feat/...`인
case-only 불일치가 있다. 아직 원격 공유 전이므로 후속 Jira 번호 확정 때 임시 이름을 거쳐 최종
소문자 branch로 2단계 rename하고, 원격에 `Feat/...`와 `feat/...` 두 branch를 만들지 않는다.

### 2.2 운영 feature flag와 데이터 상태

확인된 운영 상태:

```text
C_JOB_DEMAND_PROJECTION_MODE=projection
C_JOB_MATCHING_ACTIVE_MODE=legacy
```

- Demand Preview는 Projection 응답을 사용한다.
- 개인화 matching은 아직 legacy 활성 정책을 사용한다.
- `c_compute.user_result`: 0행
- `c_compute.matching_source_fact`: 0행
- PUBLISHED Projection: 1개
- PUBLISHED Projection 관측 시각: 2026-09-19
- Projection 공고 수: 7,786
- `user_target`: 9명
- Evidence와 target이 모두 있는 backfill 후보: 최대 8명
- `user_c_compute_attempt`: 13건 모두 `FAILED`
  - `COMPUTE_RETRY_EXHAUSTED`: 12건
  - `COMPUTE_IDEMPOTENCY_CONFLICT`: 1건

따라서 Preview 구조는 배포됐지만 current-result 저장과 개인화 active 결합의 운영 효과는 아직
발생하지 않았다.

Backend 운영 로그에서 실패는 단일 원인이 아니었다. `/job-cohorts/resolve` 연결 실패·timeout,
`/analyses/completed`의 `COMPUTE_FAILED`, 배포 중 `C_DATABASE_UNAVAILABLE`가 확인됐다. 대상 수가
작아 backfill 부하 위험은 낮지만, 기존 attempt를 단순 재시도하면 성공한다고 가정할 수 없다.
개인화 전환은 각 실패 원인을 현재 SHA에서 재현·분류하고, 최소 1개의 실제 `ur-*` end-to-end 성공을
확인하기 전에는 시작하지 않는다.

현재 `user_result.recommendation_snapshot_id`는 `c_compute.snapshot`에 대한 `NOT NULL` FK다.
matching child도 legacy cohort/recommendation identity를 함께 가진다. 따라서 compact result를
backfill하면 조회 payload와 current pointer는 개선되지만, 기존 Snapshot 공간이 회수되거나 신규
Recommendation parent Snapshot write가 자동으로 사라지는 것은 아니다. Snapshot parent를 전혀
만들지 않는 완전한 Projection-native event와 result-only FK 전환은 별도 참조 migration과 restore
gate가 필요한 후속 단계다.

실시간 공고는 요청 시 parser를 다시 실행해서 제공하는 구조가 아니다. complete verified intake가
새 Projection을 게시하면 다음 head부터 보인다. 목표 publish lag는 기존 계획의 초기 기준인 수집
완료 후 5분 이내이며, partial/rate-limit 입력은 정상 공고를 사라지게 하지 않도록 게시를 보류하거나
이전 정상 source membership을 이어받는다. `input 완료→publish` 지연과 `현재 시각→observed_at`
head age는 다른 지표다. 이번 작업은 전자를 줄이지만 Collector 주기를 바꾸지 않으므로 후자를
실시간 수준으로 단축한다고 주장하지 않는다.

### 2.3 실제 화면·서버 성능 기준선

다음은 브라우저 조작과 Backend/C 로그를 함께 확인한 값이다. 추정치가 아니다.

| 화면/조건 | 실제 관측 |
|---|---:|
| Backend, 전체 지역·전체 경력, 556건 | BE 2,361ms, C 2,310.6ms |
| Backend, 서울, 389건 | BE 871ms |
| Backend, 부산, 35건 | BE 107ms |
| Backend, 경기, 129건 | BE 311ms |
| Infrastructure, 전체, 184건 | BE 437ms, C 404.6ms |
| Frontend, 전체, 301건 | BE 505ms, C 475.5ms |
| AI/Data, 전체, 428건 | BE 497ms, C 469.6ms |
| 현재 시장, 7,050건 | C 약 10.2~13.4초, 최근 11,786.8ms |
| Trend 월간 ranking | BE 약 414~736ms |
| 기술 상세/12개월 변경 | BE 약 176~201ms |
| Job Match 목록 | BE 약 70~97ms |
| Skill Gap | BE 약 2,027ms |
| 추천 | BE 약 2,143~2,335ms |
| GitHub repository 목록 | BE 약 384ms |

FE의 직무 조건 변경 debounce는 400ms다. 작은 지역 조건은 이미 C가 100~300ms이므로 최종 체감은
debounce 비중이 크다. 전체 직무와 현재 시장은 C cold path가 지배한다.

### 2.4 DB와 프로파일링 기준선

운영 DB 읽기 전용 확인 결과:

| 관계/종류 | 크기 또는 행 수 |
|---|---:|
| `c_compute.snapshot` 전체 | 약 1,534MB |
| COHORT Snapshot | 166행, 약 1,260MB |
| RECOMMENDATION Snapshot | 112행, 약 70MB |
| PUBLIC_GITHUB Snapshot | 13행, 약 135MB |
| TREND Snapshot | 1,013행, 약 6.8MB |
| `job_fact` | 약 23MB |
| `job_projection_job` | 약 5.5MB |

현재 Projection demand 프로파일:

- Backend 전체: 총 약 1.25초의 로컬 재현 중 `aggregate_projection_demand` 약 660ms,
  `build_projection_cohort` 약 640ms, Pydantic 검증 누적 약 461ms
- Current Market: 총 약 8.36초의 로컬 재현 중 집계 약 4.16초, Cohort 재구성 약 3.71초,
  Pydantic 검증 약 2.76초, JSON load 약 1.49초, payload hash 약 1.26초
- 선택 7,155건이 canonical cross-site 병합 후 denominator 7,050건이 되어 105건이 병합됨

SQL 가능성 확인:

- Backend 활성 조건의 raw row filter: 약 8.4ms
- Backend 기술 배열 집계 proof-of-concept: 약 9.3ms
- Current Market JSONB 직접 집계: 약 459.7ms, canonical dedupe 미포함
- Current Market 저장 배열 집계: 약 57.4ms, 기존 market 의미·canonical dedupe와 완전 동등하지 않음

위 SQL 수치는 최종 구현의 성능을 보장하지 않는다. 정확한 의미와 canonical dedupe를 포함한
동일 쿼리로 다시 측정해야 한다.

### 2.5 예상 효과와 불확실성

| 경로 | 개선 확신 | 판단 |
|---|---|---|
| 직무/지역/경력 Preview | 높음 | raw filter와 배열 집계가 8~10ms 수준이고 현재 병목이 payload/Pydantic/Cohort 재구성이라 구조적으로 제거 가능 |
| Current Market | 중간 | 10초대 Python 병목은 제거 가능하지만 filtered candidate fan-out까지 포함한 exact SQL은 아직 실측 전 |
| Skill Gap/추천 | 중간 | `ur-*`면 full Snapshot hydration을 피할 수 있으나 현재 운영 result가 0이고 compute 실패 원인을 먼저 해결해야 함 |
| Job Match | 낮음(성능) | 이미 70~97ms라 속도 개선 가치는 작고 동일 result identity/정확성 보장이 주목적 |
| Monthly Trend/기술 상세 | 없음 | 역사 aggregate 경로를 의도적으로 유지하므로 이번 DB 변경의 성능 효과를 주장하지 않음 |
| GitHub repository | 없음 | 별도 API 경로라 이번 변경으로 빨라지지 않음 |

FE debounce 400ms는 그대로이므로 부산처럼 C가 이미 100ms 안팎인 작은 결과에서는 체감 개선이
희박할 수 있다. 반대로 전체 직무와 Current Market은 서버 병목이 커서 개선 가치가 높다. 이
작업의 성공을 모든 화면이 빨라졌다는 한 문장으로 판단하지 않고 경로별 before/after로 판단한다.

---

## 3. 근본 원인

현재 `JobProjectionStore.demand()`는 selector로 행을 줄인 뒤에도 다음을 수행한다.

1. 모든 선택 행을 `job_fact`와 join하여 전체 `payload`를 가져온다.
2. 요청마다 모든 payload의 canonical hash를 다시 계산한다.
3. `JobFact`, `ProjectionJob`, record/classification/requirements Pydantic 객체를 만든다.
4. Python set으로 기술 count와 canonical market identity를 계산한다.
5. Preview에도 필요 없는 `build_projection_cohort()`를 항상 호출한다.

따라서 “원본 HDFS/공고 재파싱”은 제거됐지만, “선택 공고 전체 객체 그래프 재구성”이 hot path에
남아 있다. 저장 구조가 잘못된 것이 아니라 읽기 경계가 Preview와 개인화 계산을 구분하지 않은
것이 문제다.

---

## 4. 변경하지 않아야 하는 의미

### 4.1 공통

- C가 파싱·분류·요구사항·수요·추천 의미의 소유자다.
- BE는 C API를 사용하고 C 테이블을 직접 읽지 않는다.
- `source_site:source_posting_id` identity를 유지한다.
- Registry/parser/quality/requirements/aggregation version을 결과 identity에 포함한다.
- incomplete 수집을 공고 종료로 해석하지 않는다.
- Projection version과 head는 불변/원자 게시한다.
- 계산 시작 시 Projection version을 고정한다.
- 최신 공고 내용과 과거 개인 평가를 섞지 않는다.

### 4.2 `ACTIVE_MATCHING`

- target role은 반드시 일치해야 한다.
- 명시적 CLOSED, `deadline <= as_of`, 미래 수집/게시, 확정 region/career 불일치는 제외한다.
- BODY_UNAVAILABLE과 SOURCE_RECORD_CONFLICT는 matching 모집단에서 제외한다.
- region/career UNKNOWN은 확정 불일치가 아니라 CONDITIONAL이다.
- 복수 지역은 요청 지역 중 하나와 overlap하면 일치한다.
- OR requirement와 required level을 보존한다.
- required/preferred/general은 겹칠 수 있다.
- total은 category 합이 아니라 공고 ID 합집합이다.
- general 기술은 strict 공고만 집계한다.

### 4.3 `CURRENT_MARKET`

- 공식 source 범위를 유지한다.
- CLOSED와 `deadline <= as_of`를 제외한다.
- 상태 UNKNOWN과 deadline 미상은 분모에 남긴다.
- body/requirement 해석 실패도 범위·시간 조건이 맞으면 분모에 남긴다.
- 해석 가능한 MATCHED 기술만 required/preferred count에 반영한다.
- cross-site canonical identity 기준으로 공고를 distinct 처리한다.
- 같은 사이트의 ID가 다른 유사 공고는 이번 작업에서 자동 병합하지 않는다.

### 4.4 `MONTHLY_DEMAND`

- 당시 관측 수요이므로 현재 CLOSED/마감 경과 공고도 포함한다.
- 현재 시장 active 정책을 소급 적용하지 않는다.
- 완료된 서울 달력 월과 posting-date 정책을 유지한다.
- 한 개뿐인 현재 Projection version으로 과거 월을 재구성했다고 주장하지 않는다.

### 4.5 개인화 결과

한 result identity 안에서 다음은 같은 공고 집합을 사용한다.

- demand denominator
- Skill Gap
- 추천 후보와 순위
- current matching IDs/count
- What-if projected/new IDs/count
- 설명 문구의 수치와 source
- Job Match 평가와 목록

마감 공고를 목록에서만 제거하고 저장 count를 그대로 반환하지 않는다.

---

## 5. 범위와 비범위

### 5.1 이번 작업 범위

- Preview demand-only SQL 경로
- Preview와 개인화 Cohort 복원 API 분리
- Current Market canonical/기술 sidecar schema
- forward-only migration(현재 develop 기준 예정 번호 008)
- materializer/publish/readiness coverage 확장
- query-engine `python|shadow|sql` feature flag
- matching compute `legacy|projection`와 matching active `legacy|projection` flag 분리
- SQL/Python 결과 shadow와 운영 지표
- 선택 fact만 복원하는 개인화 계산 경로
- 기존 Evidence 기반 current-result backfill
- matching projection 활성화 전 검증
- 브라우저·서버·DB before/after 측정
- 배포·롤백·보존 문서 갱신

### 5.2 이번 작업 비범위

- 월별 Trend 의미 또는 보존 정책 변경
- 과거 누락 Trend 데이터 복원
- 같은 사이트의 유사 공고 자동 병합
- Collector 수집 주기 변경
- 원본 parser 전면 재작성
- Kafka/Spark/HDFS 처리량 튜닝
- GitHub API 및 repository/branch 조회 최적화
- LLM 기술 요약 지연 개선
- FE debounce 변경
- 직무·지역·경력의 모든 가능한 조합 사전 계산
- 기존 Snapshot 삭제, `VACUUM FULL`, OS 디스크 반환 작업
- Projection-native resolve로 legacy cohort/recommendation FK를 완전히 제거하는 작업
- Registry review의 cohort fan-out 제거

---

## 6. 목표 구조

```text
complete verified collector input
  -> materialize immutable job_fact
  -> materialize versioned job_projection_job
  -> materialize versioned job_projection_market_job/candidate
  -> validate counts/hash/coverage
  -> atomically publish Projection head

Preview
  -> pin published head
  -> normalize selector
  -> SQL filter/classify/aggregate typed rows
  -> Demand DTO only

Personalized recompute
  -> pin Projection version
  -> SQL-select matching job keys/fact IDs
  -> load and validate only selected immutable facts
  -> rebuild Cohort once
  -> calculate recommendation/gap/matching/what-if
  -> atomically publish current user result

Historical monthly Trend
  -> keep existing immutable monthly aggregate path
```

---

## 7. 구현 단계

### Phase 0. 기준선과 작업 준비

1. 후속 Jira 1건을 만들고 `S15P21E102-360`, MR `!270`을 연결한다.
2. 현재 브랜치가 최신 `origin/develop`에서 시작했는지 확인한다.
3. 기존 공유 history를 rebase/force-push하지 않는다.
4. 운영 before 측정 입력/selector/as-of/Projection ID를 기록한다.
5. 최신 develop 집중 테스트를 다시 실행한다.
6. 구현 직전 최신 develop의 C migration과 BE Flyway migration 최종 번호를 다시 확인한다. 다른
   MR이 008/V26을 선점했으면 충돌하는 파일명을 유지하지 않고 다음 번호로 문서·패키징·테스트를
   함께 변경한다.
7. 첫 push 전 Windows case-only local branch ref를 임시 이름→최종 Jira 소문자 이름으로
   정상화하고 `git show-ref --heads`로 단일 ref만 확인한다.

완료 조건:

- 기준 commit과 배포 SHA를 문서에 기록
- working tree clean
- 최신 develop 집중 테스트 실패 0

### Phase 1. 정확성 fixture와 benchmark 고정

다음 selector/입력을 fixture와 PostgreSQL integration test로 고정한다.

- 5개 지원 직무
- region 없음/단일/복수/전국/UNKNOWN
- career 신입/경력/복수/무관/AMBIGUOUS/UNKNOWN
- ACTIVE/CLOSED/UNKNOWN
- deadline 과거/정확히 as_of/미래/null
- body unavailable
- source record conflict
- multi-role/multi-region
- required/preferred 중복
- OR requirement
- 빈 결과/min_jobs 미달
- CURRENT_MARKET 공식 source
- cross-site duplicate
- filter 적용 전 many-to-one이지만 적용 후 one-to-one이 되는 cross-site 후보
- 같은 사이트의 유사하지만 다른 posting ID

비교 대상:

- normalized criteria
- selected job IDs
- denominator/matching/input/duplicate/excluded/review
- required/preferred/general/total count와 ratio
- 전체/category rank와 tie-break
- cross-site merged count
- status/as_of/basis versions

### Phase 2. Preview와 Cohort 복원 경계 분리

기존의 항상-Cohort 결과를 다음 두 경계로 분리한다.

```text
query_projection_demand_summary(criteria, version=None)
query_projection_cohort(criteria, version)
```

`query_projection_demand_summary` 계약:

- Preview 전용
- `job_fact.payload`를 읽지 않음
- `JobFact`/`ProjectionJob` Pydantic 객체를 만들지 않음
- `build_projection_cohort()`를 호출하지 않음
- Snapshot을 INSERT하지 않음
- 사용자 응답에 selected ID 전체 배열을 노출하지 않음
- Projection version, version에 결합된 `as_of`, normalized selector를 cache/metric identity에 포함

`query_projection_cohort` 계약:

- 개인화 계산 전용
- 반드시 명시 Projection version을 사용
- SQL이 선택한 job key/fact ID만 로드
- 선택 fact의 payload hash와 version을 검증
- 계산 때 사용한 `job_fact_id`를 matching assessment/source에 고정
- personalized resolve에서만 기존 BE 계약용 COHORT/DEMAND Snapshot pair를 결정론적으로 1회 저장할
  수 있으며 Preview에서는 이 저장 함수를 호출할 수 없음

### Phase 3. 다음 forward migration과 Current Market sidecar

이 문서 작성 시 최신 번호는 007이므로 아래에서는 예정 번호를 008로 쓴다. 번호는 구현 시작
preflight에서 다시 배정하며, 한번 공유된 migration 파일은 rename/rebase하지 않고 새 forward
migration으로 수정한다.

기존 immutable `job_projection_job` 행을 UPDATE하지 않는다. Current Market 기술과 cross-site
후보 관계는 별도 sidecar로 저장한다. 최종 canonical key는 selector에 따라 달라질 수 있으므로
게시 시 고정해 저장하지 않는다.

초기 schema:

```text
c_compute.job_projection_market_job
  projection_version_id varchar(80)
  job_key varchar(256)
  normalized_company text
  normalized_title text
  market_region_identity text
  raw_region_identity text
  raw_career_identity text
  market_required_tech_ids text[]
  market_preferred_tech_ids text[]
  PRIMARY KEY (projection_version_id, job_key)
  FK (projection_version_id, job_key)
    -> job_projection_job(projection_version_id, job_key)

c_compute.job_projection_market_candidate
  projection_version_id varchar(80)
  left_job_key varchar(256)
  right_job_key varchar(256)
  PRIMARY KEY (projection_version_id, left_job_key, right_job_key)
  FK left/right -> job_projection_job(projection_version_id, job_key)
```

제약과 원칙:

- 배열은 sorted distinct, null 대신 빈 배열
- sidecar 행은 immutable
- canonical key 정책 version은 Projection aggregation identity에 포함
- aggregation/canonical policy version을 bump해 같은 input union이라도 sidecar 없는 기존 PUBLISHED
  version ID를 재사용하지 않음; 이미 게시된 version에 sidecar를 사후 보충하지 않음
- candidate는 기존 `canonical_identities()`와 같은 company/title/deadline/region guard를 통과한
  JOBKOREA-SARAMIN 조합을 저장하되 fan-out 때문에 탈락한 후보도 보존
- query는 먼저 selector/scope/시간 필터를 적용하고, 남은 candidate의 left/right fan-out이 각각
  1인 pair만 canonical identity로 확정
- canonical identity는 확정된 pair의 source key hash로 요청 중 결정하며 저장된 전역 대표 key를
  사용하지 않음
- 기존 Projection version은 sidecar 0행이어도 유효하지만 SQL market-ready는 아님
- 새 version publish 시 Projection 공고마다 `market_job` sidecar가 정확히 1행인지 검증
- candidate는 coverage 비율이 아니라 동일 입력 재생성 count/hash와 FK·중복 없음으로 완전성 검증
- CURRENT_MARKET 공식 source 밖의 행도 sidecar를 만들 수 있으나 query scope는 기존 계약 유지
- candidate count, full-set one-to-one count, ambiguous fan-out count를 build stats에 기록
- 동일 normalized company/title 군의 row 수와 candidate 수 상한을 계측한다. 보수적 초기 gate는
  전체 candidate `<= max(10,000, job_count * 4)`, 단일 company/title 군의 cross product
  `<= 1,000`으로 둔다. 초과 시 임의 truncate하지 않고 해당 Projection publish를 실패시키며
  이전 head를 유지한다. 운영 분포로 조정할 때는 수치와 근거를 runbook에 기록한다.

필수 패키징:

- `008_*.sql` 추가
- Worker Dockerfile `/app/migrations` COPY 추가
- migration version/checksum/readiness 테스트 갱신
- 001→008 fresh migration 검증
- 001→007 seeded DB의 008 upgrade 검증

### Phase 4. SQL Demand 집계

공통 CTE는 전체 Projection 행에 대해 selector 판정 결과를 명시적으로 만든다.

```text
scoped
  -> flags(excluded reasons, review reasons, strict, matching)
  -> matching rows
  -> technology category rows
  -> distinct posting identity/category
  -> counts/ratios/ranks
```

SQL은 단순 WHERE prefilter만으로 끝내지 않는다. `excluded_count`, `review_count`, UNKNOWN과
conditional 의미를 재현할 수 있도록 판정 상태를 계산한다.

`ACTIVE_MATCHING`:

- identity는 `job_key`
- strict/general 규칙 유지
- BODY_UNAVAILABLE/SOURCE_RECORD_CONFLICT 제외

`CURRENT_MARKET`:

- identity는 filtered one-to-one pair hash, pair가 없으면 `job_key`
- sidecar market arrays 사용
- quality/review 행을 분모에 유지
- CLOSED/deadline/scope/future만 제외
- filtered candidate fan-out을 다시 계산해 one-to-one pair만 shared identity 사용
- `cross_site_merged_count`는 전체 분모의 merge 수가 아니라 기존 validator 계약대로 strict
  `cohort.jobs` 집합 내부의 merge 수만 계산

rank는 count 내림차순, `tech_id` 오름차순 tie-break를 유지한다.

속성을 저장한 목적은 모든 조합의 최종 JSON을 미리 만드는 것이 아니라 작은 typed row를 SQL로
필터·집계하기 위한 것이다. 그 위에 Worker별 bounded summary cache만 둔다.

- key: Projection version + bound `as_of` + normalized purpose/source/role/region/career/min_jobs
- value: Demand DTO만 저장하며 selected ID 배열, fact payload, Cohort는 저장하지 않음
- 최대 256개 LRU, key별 single-flight, process-local
- Redis 추가와 모든 조합 precompute는 하지 않음
- head가 바뀌면 새 version key만 사용하고 구 항목은 LRU로 자연 퇴출
- cold 성능 gate는 cache를 비우고 통과해야 하며 cache hit으로 느린 SQL을 숨기지 않음

인덱스는 계획만으로 늘리지 않는다. 실제 데이터 분포에서 `EXPLAIN (ANALYZE, BUFFERS)`로 seq
scan, bitmap scan, array unnest, sort/hash aggregate, temp spill을 확인한다. 현재 C DB adapter는
pool이 아니라 요청마다 새 psycopg connection을 여므로 존재하지 않는 pool wait를 계측했다고
쓰지 않는다. connect 시간, query 시간, 동시 open connection/PostgreSQL `numbackends`, statement
timeout을 분리해 기록한다. SQL foreground/shadow 동시 실행에는 보수적 concurrency/queue 상한을
두고, connect가 전체 latency의 30% 이상이면 그때 bounded pool 도입을 별도 benchmark로 판단한다.
한 요청이 대량 메모리나 temp 파일을 쓰면서 다른 API를 느리게 만들면 p95가 맞더라도 완료로 보지
않는다.

### Phase 5. query-engine flag와 shadow

운영 demand가 이미 Projection mode이므로 기존 flag를 재사용해 즉시 SQL을 켜지 않는다.

신규 설정:

```text
C_JOB_DEMAND_QUERY_ENGINE=python|shadow|sql
C_JOB_DEMAND_QUERY_FALLBACK=false|true
```

- `python`: 기존 Projection Python 집계
- `shadow`: 사용자 응답은 Python, SQL 비교는 bounded background 실행
- `sql`: SQL 응답
- SQL error fallback은 별도 boolean으로 제어
- 기본값은 engine `python`, fallback `false`
- old head/no-sidecar는 query 시작 전 readiness로 감지해 Python을 선택하고 metric을 남김
- 임의 SQL error는 기본적으로 빠르게 실패하며, canary에서 fallback을 켠 경우에도 semaphore 안에서
  한 번만 Python으로 재시도

지표:

- query count/error/fallback/duration
- summary cache hit/miss/eviction/single-flight wait
- shadow compared/mismatch/skipped
- selected ID/count mismatch
- category/rank mismatch
- market-job sidecar missing/coverage와 candidate count/hash/integrity
- Projection version/input-to-publish lag/head age
- canonical merged count
- DB connect/query/active connection/timeout/temp spill

기존 Python 경로가 Current Market에서 10초 이상 걸리므로 운영 shadow를 동기 100%로 실행하지
않는다. 배포 전 offline 100 selector를 먼저 수행하고 운영 shadow는 bounded 1%로 제한한다.
fallback은 임시 안전장치이며 정상 성공처럼 숨기지 않는다. fallback rate와 원인을 경보하고,
반복 fallback이 DB connection을 폭증시키지 않도록 bounded 실행과 timeout을 둔다.

offline 100 selector는 실행 때 seed와 JSON 목록을 저장한다. 최소 구성은 5개 직무의
지역/경력 조합 80개와 Current Market의 전체/지역/경력 조합 20개이며, deadline·UNKNOWN·빈 결과
fixture는 별도 고정 테스트로 보충한다. staging/복제본에서 concurrency 최대 2, selector별 checkpoint로
실행해 중단 후 이어갈 수 있게 하고 운영 트래픽에서 100개 비교를 돌리지 않는다.

Current Market exact SQL은 sidecar 배열만 쓴 57.4ms POC와 동일한 쿼리가 아니다. filtered
candidate fan-out과 strict merge metric을 포함한 쿼리가 DB p95 gate를 넘으면 canonical 정책을
단순화하거나 중복 병합을 빼서 통과시키지 않는다. 먼저 실행계획·index·CTE materialization을
조정하고, 그래도 실패하면 query engine을 `python`에 둔 채 Current Market no-filter 기본 selector의
version별 summary만 별도 사전 계산하는 후속 설계를 선택한다. 정확성 gate를 성능 gate와 맞바꾸지
않는다.

### Phase 6. 개인화 선택 fact 경량화

현재 `C_JOB_MATCHING_ACTIVE_MODE`는 `/job-cohorts/resolve` 응답에 Projection version을 넣는 계산
선택과, 목록/detail에서 active Projection 필터를 적용하는 읽기 선택을 함께 제어한다. 이 결합을
유지하면 canary result를 만들기 위해 전체 사용자의 읽기 의미부터 바꿔야 한다. 다음 두 flag로
분리한다.

```text
C_JOB_MATCHING_COMPUTE_MODE=legacy|projection
C_JOB_MATCHING_ACTIVE_MODE=legacy|projection
```

- 둘의 기본값은 `legacy`
- compute mode만 `projection`이면 새 계산 event에 pinned Projection version을 포함하지만 기존
  사용자 조회는 legacy 의미를 유지
- active mode는 projection-backed `ur-*` canary와 dual-read 검증 후에만 `projection`
- rolling deploy 중 구 Worker가 새 compute flag를 몰라도 active 기본값은 바뀌지 않음

`job-cohorts/resolve`의 projection compute 경로와 `analysis_completed`가 Preview용 summary에서 Cohort를
우연히 받거나 같은 Cohort를 두 번 만들지 않도록 호출을 분리한다.

1. compute resolve가 normalized selector와 PUBLISHED Projection version을 원자적으로 pin
2. ACTIVE_MATCHING SQL로 정확한 선택 key/fact ID 계산
3. 선택된 fact payload만 조회하고 hash/version 검증
4. parser를 다시 실행하지 않고 저장된 record/classification/requirements로 Cohort를 1회 복원
5. 기존 BE rolling 계약을 위해 projection version이 identity에 포함된 immutable COHORT/DEMAND
   compatibility Snapshot pair를 개인화 selector에 한해 저장·반환. `JobCohort`에는 기존 row와
   호환되는 nullable `projection_version_id`를 additive하게 넣고 새 pair에서는 필수로 채움
6. `analysis_completed`는 event의 cohort Snapshot과 pinned Projection version 일치를 검증하고
   Projection을 다시 조회하거나 Cohort를 다시 만들지 않음
7. recommendation/gap/matching/what-if를 한 번 계산
8. compact result와 모든 child를 같은 transaction에 저장
9. `(user_id, target_key)` head를 마지막에 교체

새 head 게시 실패 시 이전 결과를 유지한다.

이 compatibility Snapshot write는 기존 FK와 BE DTO를 이번 MR에서 안전하게 유지하기 위한 것이다.
Preview write 제거와 모순되지 않으며, Snapshot parent를 완전히 없애는 후속 작업으로 오인하지 않는다.
resolve cold latency도 별도로 측정해 BE client timeout보다 충분히 낮아야 backfill을 시작한다.

### Phase 7. 기존 사용자 result backfill

기존 사용자의 GitHub 분석을 일괄 재실행하지 않는다. BE의 현재 target과 기존 ready Evidence를
사용해 current result를 만든다.

dry-run 분류:

- 재사용 가능: target과 단일 호환 Evidence lineage 존재
- 재분석 필요: lineage 없음, Rule Pack 혼재, 무결성 실패
- 보류: target 없음, 성공한 분석 없음

운영 preflight에서 기존 `user_c_compute_attempt`의 상태와 실제 Backend/C 로그를 함께 분류한다.
현재 확인된 13건은 모두 실패 상태이므로 다음을 선행한다.

1. resolve 연결 실패/timeout이 SQL Preview 전환 후 사라졌는지 확인
2. `C_DATABASE_UNAVAILABLE`가 배포 window의 일시 장애인지 현재 설정 오류인지 확인
3. `COMPUTE_FAILED`의 C stack/error code를 동일 SHA에서 재현
4. idempotency conflict는 event payload/compute version 차이를 비교하고 기존 event를 삭제하지 않음
5. compute mode만 `projection`, active mode는 `legacy`로 유지
6. 한 명을 canary로 synchronize하여 C 응답 `result_id=ur-*`를 확인
7. BE `user_c_snapshot.recommendation_snapshot_id`가 해당 `ur-*`를 저장했는지 확인

1번은 Preview API가 빨라졌다는 사실로 대신 판정하지 않는다. compute mode projection의
`/job-cohorts/resolve`를 실제 8개 target selector로 cold 측정하고, compatibility pair가 이미 있을
때와 없을 때를 나눠 기록한다.

단순히 `user_result`를 old `c-*`에 연결해 INSERT하는 것은 backfill 완료가 아니다. 정상 경로는
`Store.finish()`가 compact `user_result`와 child를 원자 저장하고, 완료 응답의 `result_id`를
`AnalysisCompleted.Result.recommendationSnapshotId()`가 선택해 BE current pointer를 `ur-*`로
교체하는 것이다. 그래야 Skill Gap/추천 조회가 `resolved_user_result()`에서 legacy full Snapshot을
강제 hydrate하지 않는다.

backfill은 사용자별 idempotent identity를 사용하고 retry budget을 지킨다. 1명 canary 성공 후
나머지 최대 7명을 작은 batch로 실행한다. 완료 후 확인:

- `user_result`와 `user_result_head` 생성
- BE current snapshot의 recommendation reference가 `ur-*`
- 일반 조회에서 legacy `c_compute.snapshot.payload` full hydration 0회
- matching child/result/fact source 연결
- `c-*`와 `ur-*` dual-read 동일성
- target A→B→A
- stale result에서 비동기 recompute

현재 FAILED attempt는 `tryStartAttempt()`가 의도적으로 다시 열지 않으므로 재배포나 scheduler
대기로는 backfill되지 않는다. BE에 operator-only rearm 경계를 추가한다.

- 입력: `user_id`, exact `target_key`, exact `evidence_version`, expected `run_token`, actor, reason
- 조건: 현재 status가 `FAILED`이고 target/Evidence가 여전히 현재 값일 때만 CAS 성공
- 동작: attempt count를 0으로 초기화한 새 retry identity를 만들고 즉시가 아닌 scheduler가 claim
- 감사: before reason/count/token, actor, reason, timestamp를 별도 append-only 행/로그에 남김
- 실행 경계: 기존 ADMIN role로 보호되는 `/api/v1/admin/**` 아래 dry-run/rearm API와 service를
  사용하고 public/me API에서는 노출하지 않음
- dry-run은 후보만 출력하고 상태를 바꾸지 않음
- canary 1건 성공 전 bulk rearm 금지
- 실패 행의 무조건 DELETE, 전체 UPDATE, 운영 DB 수동 ad-hoc SQL은 금지

### Phase 8. 화면·운영 검증

브라우저와 Backend/C 로그를 함께 사용한다.

직무 화면:

- 직무 5개와 전체/서울/부산/경기/대구
- 경력 전체/신입/경력/복수
- cold와 exact cache hit 분리
- 빠른 연속 조건 변경의 최종 응답 일치

Trend:

- 현재 시장 7천여 공고 카드
- 주간/월간 ranking
- 기술 상세의 12개월 series
- 월별 역사 Trend 불변

개인화:

- Job Match 목록/상세
- Skill Gap
- 추천
- 추천 후보가 있는 사용자의 What-if
- stale 표시와 재계산
- 마감 공고 list/detail/count/ID 동시 제외

별도 확인:

- GitHub repository 화면은 회귀만 확인하고 개선 수치에 포함하지 않음
- 유사 공고 후보가 자동 오병합되지 않았는지 표본 확인

---

## 8. 테스트 계획

### 8.1 AI unit/contract

- Python/SQL selector parity
- category 합집합과 rank
- UNKNOWN/AMBIGUOUS/UNRESTRICTED
- Current Market expiry
- Monthly Demand historical expiry 보존
- cross-site canonical dedupe
- filter 전 many-to-one, filter 후 one-to-one canonical dedupe
- strict/review가 섞인 pair의 `cross_site_merged_count`
- candidate 폭증 gate와 이전 head 유지
- recommendation explanation `matching_jobs` 회귀
- payload hash/integrity audit
- query-engine mode/fallback/metric
- bounded summary cache key/LRU/single-flight/head 변경

### 8.2 PostgreSQL integration

- 001→008 fresh apply
- 001→007 data seed 후 008 upgrade
- sidecar FK/check/immutable trigger
- publish 중 실패 시 이전 head 유지
- 같은 input union에서도 aggregation version bump로 새 Projection ID/sidecar 생성
- head 동시 publish와 관측 시각 역행 방지
- old head/no-sidecar Python fallback
- selected-fact cohort 복원
- projection compute resolve의 deterministic compatibility pair 재사용
- compatibility COHORT/DEMAND/event의 Projection ID 3자 일치와 legacy nullable 호환
- `analysis_completed`에서 같은 Projection Cohort를 다시 복원하지 않음
- current-result atomic publish와 previous 유지
- active matching pagination/count/detail

### 8.3 BE

- demand DTO/basis/cache key
- stale recompute scheduling
- `c-*`/`ur-*` dual read
- 완료 응답이 `result_id`를 반환하면 BE가 snapshot ID 대신 `ur-*`를 저장
- `ur-*` Skill Gap/추천 일반 조회에서 full legacy Snapshot 미조회
- Skill Gap/추천/매칭/What-if 상태
- current count와 pagination 일치
- 기존 Evidence 기반 synchronize
- terminal attempt exact-CAS rearm/dry-run/audit와 stale target/evidence 거절

### 8.4 FE

- 전체 unit test
- lint/build/typecheck
- query key와 stale time 회귀
- 새 server refetch가 새 Projection basis를 반영하는지와 기존 FE stale/poll window 확인
- 직무 조건 변경과 마지막 응답 표시
- 데이터 없음/부분/재계산 상태

### 8.5 성능

같은 input union, Projection ID, selector, `as_of`로 비교한다.

- Worker restart 직후 첫 요청
- exact selector 10회
- 고정 100 selector
- DB `EXPLAIN (ANALYZE, BUFFERS)`
- connection acquire/query timeout과 temp read/write
- connect handshake와 PostgreSQL active connection 수
- C p50/p95/max
- BE p50/p95/max
- RSS peak
- Snapshot INSERT rows/bytes
- error/fallback/mismatch
- 개인화 API별 DB query 수와 읽은 JSON/TOAST bytes
- projection compute resolve cold/warm latency와 Cohort 복원 횟수

운영 DB에 부하 테스트나 시험 migration을 실행하지 않는다. staging/복제본 또는 승인된 bounded
read-only 측정만 사용한다.

---

## 9. 성능 및 정확성 gate

다음을 모두 만족해야 SQL 응답을 활성화한다. 경량 직무 selector와 전체 시장 selector는 데이터
크기가 다르므로 같은 DB 숫자를 억지로 적용하지 않는다.

- 비의도 selected job ID mismatch 0
- 비의도 denominator/count/rank mismatch 0
- 고정 fixture 100% 통과
- 운영 최신 Projection offline 100 selector 통과
- 직무/지역/경력 DB query p95 <= 100ms
- 직무/지역/경력 C cold p95 <= 300ms
- 직무/지역/경력 BE cold p95 <= 500ms
- Current Market exact DB query p95 <= 250ms
- Current Market C cold p95 <= 500ms, BE cold p95 <= 800ms
- Current Market은 운영 기준선 대비 C latency 90% 이상 감소
- C cold max <= 1s
- Worker restart 후 별도 warm-up 없이 동일 기준
- Preview COHORT/DEMAND Snapshot INSERT 0
- `market_job` sidecar coverage 100%, candidate count/hash integrity 일치
- build 실패 시 이전 head 정상 조회
- publish lag <= 5분 또는 승인된 운영 기준
- Projection head 변경 후 새 C/BE 요청은 즉시 새 version을 사용
- FE는 직무 stale 60초·현재 시장 poll 최대 10분이라는 기존 bounded freshness를 넘지 않음

개인화 mode 전환 gate:

- 기존 failed attempt 원인 분류와 canary 1명 `ur-*` 성공
- projection compute resolve cold max <= 5초(BE write timeout 기본 30초의 1/6 이하)
- backfill 가능한 대상 성공률과 실패 분류 확인
- current-result/child atomicity 확인
- Job Match/Skill Gap/추천/What-if 동일 result identity
- list/detail/count/pagination active set 일치
- `11d58d5` recommendation explanation 회귀 통과
- legacy dual-read와 rollback 확인
- Skill Gap C/BE p95 <= 800ms 또는 기존 대비 50% 이상 개선
- 추천 C/BE p95 <= 500ms 또는 기존 대비 50% 이상 개선
- Job Match는 기존 p95 회귀 없음

개인화 기준은 Preview SQL 활성 gate와 독립이다. 운영 후보가 최대 8명이라 표본이 작으므로 p95만
단독으로 해석하지 않고 같은 사용자·result의 cold 10회 median/max, DB query 수, full Snapshot
read 여부를 함께 기록한다. 이 gate를 못 맞춰도 Preview SQL을 롤백할 이유는 아니지만 matching
projection mode는 켜지 않는다.

---

## 10. 배포 순서

1. 최신 develop 기반 새 MR 병합
2. 서비스·데이터 서버 preflight와 dirty checkout 확인
3. 새 Worker image 빌드
4. migration 008 lock/size/dry-run 확인
5. 새 runtime 활성화 전 migration 008 적용
6. 서비스·데이터 서버 동일 SHA로 배포
7. `C_JOB_DEMAND_QUERY_ENGINE=python` 확인
8. 새 Projection dry-run
9. market-job coverage와 candidate count/hash/build stats 확인
10. 새 Projection publish
11. offline 100 selector shadow
12. query engine `shadow`, bounded 1%
13. mismatch/error/latency 관측
14. query engine `sql`
15. 24시간 관측
16. 기존 failed compute attempt 원인 재확인과 개인화 backfill dry-run
17. `C_JOB_MATCHING_COMPUTE_MODE=projection`, active mode `legacy`로 Worker 재생성
18. exact identity CAS로 1명 rearm 후 canary `ur-*` publish와 BE pointer/full Snapshot read 검증
19. 나머지 대상 bounded rearm/backfill
20. 개인화 네 화면 검증
21. 개인화 성능·정확성 gate를 만족할 때만 `C_JOB_MATCHING_ACTIVE_MODE=projection`
22. 추가 24시간 관측

Preview SQL 전환과 개인화 matching 전환은 한 MR 안에 있어도 서로 다른 운영 단계다. 15번까지
성공했다고 21번을 자동 진행하지 않는다. 반대로 개인화 실패가 Preview SQL의 정확성·성능을
무효화하지는 않으며, matching은 legacy에 둔 채 실패 원인을 수정한다.

`Infra/scripts/deploy.sh`는 새 Worker image build와 runtime recreate 사이에
`c-compute-migrate.sh`를 `run` mode로 자동 실행한다. 스크립트는 선택한 env/Compose project의
다섯 `POSTGRES_*` 값을 container 내부 `psycopg.make_conninfo`로 escape하며, Python runner의
명시적 `--from-postgres-env` 선택으로만 이를 허용한다. migration 실패 시 Worker recreate를
시작하지 않는다.

환경변수 변경 후 `docker compose restart`만 사용하면 기존 container 환경이
유지되므로 `up -d --no-deps --force-recreate`로 Worker를 재생성하고 container 내부 실제 flag와
`/ready`를 다시 확인한다.

서비스 서버가 먼저, 데이터 서버가 나중에 교체되는 동안 서로 다른 image가 공존할 수 있다.
migration과 응답 필드는 additive해야 하고, 구 Worker가 새 테이블을 무시하며 새 Worker가 old
head를 Python으로 읽을 수 있어야 한다.

---

## 11. 롤백

SQL 조회 장애 또는 mismatch:

1. `C_JOB_DEMAND_QUERY_ENGINE=python`
2. Worker 강제 재생성
3. 대표 selector와 `/ready` 확인

Projection 자체 장애:

1. `C_JOB_DEMAND_PROJECTION_MODE=legacy`
2. matching이 켜졌다면 `C_JOB_MATCHING_ACTIVE_MODE=legacy`
3. matching compute mode도 `legacy`
4. Worker 재생성
5. 기존 Snapshot preview와 개인화 화면 확인
6. 필요할 때만 CAS/audit rollback 명령으로 이전 PUBLISHED head 복구

개인화 장애:

1. matching active mode `legacy`
2. 새 계산도 중단해야 하면 matching compute mode `legacy`
3. current result와 실패 version/행은 삭제하지 않음
4. legacy `c-*` 조회 확인

신규 테이블과 실패 Projection을 즉시 DROP/DELETE하지 않는다. 005~008 migration을 역수정하지
않으며 수정은 새 forward migration으로만 수행한다.

---

## 12. 보존과 Snapshot 정책

- 이번 작업에서 기존 COHORT/RECOMMENDATION Snapshot을 삭제하지 않는다.
- Preview는 새 대형 Snapshot을 만들지 않는다.
- current-result backfill은 읽기 경량화이며 그 자체를 Snapshot 저장량 감소로 보고하지 않는다.
- 신규 개인화 계산은 교차 배포 호환을 위해 당분간 legacy parent Snapshot을 계속 만들 수 있다.
- current-result가 안정화되어도 legacy 참조 audit, restore rehearsal 전에는 정리하지 않는다.
- Projection version은 현재 head, 직전 정상 head, 진행 중 result가 참조하는 version을 보존한다.
- FAILED metadata의 감사 이력을 보존한다.
- 장기간 version membership 누적을 방치하지 않되 자동 GC는 참조 관계 구현 전 켜지 않는다.
- 대량 DELETE와 disk compaction을 분리한다.
- Snapshot을 정리해도 과거 월별 Trend aggregate는 유지한다.

Snapshot write를 실제로 중단하는 후속 작업은 다음 순서를 요구한다.

1. projection-native resolve/event 계약을 additive하게 도입
2. matching/review/BE 참조를 `result_id` 또는 `job_fact_id`로 이전
3. 신규 결과가 legacy COHORT/RECOMMENDATION parent 없이 저장·조회되는지 검증
4. 7일 이상 legacy fallback과 신규 parent write를 관측
5. 참조 audit 0과 별도 DB restore rehearsal
6. 삭제 후보 dry-run 후 승인된 maintenance 작업으로 GC/compaction

---

## 13. 위험 등록부

| 위험 | 영향 | 방지/탐지 |
|---|---|---|
| Python/SQL 의미 drift | 잘못된 수요·추천 | ID/count/rank shadow 100% 비교 |
| Current Market 배열 재사용 오류 | required/preferred 순위 변경 | market 전용 sidecar와 fixture |
| canonical false merge | 서로 다른 채용 합침 | 정책 version, 표본 review, same-site 자동 병합 금지 |
| 전역 canonical key 고정 | selector 후 1:1이 되는 후보를 놓침 | candidate pair 저장, 필터 후 fan-out 재계산 |
| candidate O(n²) 폭증 | publish 지연/DB 증가 | 전체·group 상한, 통계, 초과 publish 실패 |
| strict 밖 merge를 metric에 포함 | `cross_site_merged_count` invariant 왜곡 | strict pair 전용 회귀 fixture |
| incomplete 수집을 CLOSED로 오인 | 정상 공고 대량 소멸 | complete source만 부재 확정 |
| deadline timezone/off-by-one | 당일 공고 조기 제외 | UTC/서울/동일 as_of 경계 테스트 |
| old head에 sidecar 없음 | SQL 500/누락 | coverage readiness와 Python fallback |
| 동일 Projection ID 재사용 | publish가 early-return해 sidecar 0행 | aggregation version bump, 새 version ID 테스트 |
| migration 008 미패키징 | 배포 후 schema mismatch | Dockerfile/migration package 테스트 |
| 다른 MR이 migration 008 선점 | checksum/적용 순서 충돌 | 구현 직전 번호 재확인, 공유 후 forward-only |
| Windows branch 대소문자 alias | 원격에 유사 branch 두 개 생성 | 첫 push 전 2단계 rename, 단일 ref 확인 |
| deploy가 migration을 자동 적용하지 않음 | runtime readiness 실패 | 명시적 선적용 단계 |
| 서비스/데이터 SHA 불일치 | 교차 API 오류 | 양쪽 checkout/image SHA 검증 |
| 순차 배포 중 old/new Worker 공존 | 일시적 404/500 | additive schema/API, old-head fallback |
| 이미 projection mode라 새 SQL 즉시 활성 | 전체 트래픽 장애 | 별도 query-engine 기본 python |
| matching 계산/읽기 flag 결합 | canary 전에 전체 읽기 의미 변경 | compute/active flag 분리, compute만 먼저 전환 |
| head 변경 직후 cache stampede | DB connection 폭증 | version key, single-flight/bounded cache fill |
| process-local cache를 전역 진실로 오인 | Worker별 hit 차이/old memory | DTO 가속만 사용, version key, 256 LRU, DB가 진실 |
| 새 connection handshake가 지배 | SQL 자체만 빨라도 C 지연 | connect/query 분리 계측, 필요할 때만 bounded pool 검증 |
| SQL sort/hash temp spill | 다른 API까지 지연 | BUFFERS/temp/connection wait 계측과 timeout |
| fallback이 오류를 숨김 | 느린 Python 경로 상시 사용 | fallback rate 경보와 전환 중단 gate |
| publish lag 증가 | 새 공고 노출 지연 | intake 완료→head 5분 gate와 lag metric |
| intake 중단 중 deadline 경과 | old head의 마감 공고가 더 오래 보임 | head age 경보/표시, 수집 정상화 전 새 head 위조 금지 |
| 요청 hash 검증 제거로 corruption 은폐 | 잘못된 fact 사용 | publish 검증, audit, 개인화 선택 fact 검증 |
| compute 중 head 변경 | 혼합 입력 | Projection ID pinning |
| 최신 상세와 과거 평가 혼합 | 설명/매칭 오류 | assessment `job_fact_id` 고정 |
| count만 stale | KPI/What-if 불일치 | 같은 active set으로 ID/count/page/detail 계산 |
| user_result backfill 폭주 | DB/C 부하 | dry-run, bounded batch, retry/idempotency |
| 기존 compute 실패를 무시하고 backfill | result 0행/화면 stale 유지 | 실패 원인 분류, 1명 canary `ur-*`, BE pointer 확인 |
| FAILED attempt가 terminal인데 scheduler만 대기 | backfill 영구 미실행 | exact identity CAS rearm와 append-only 감사 |
| `user_result`만 INSERT | BE가 계속 `c-*`를 읽어 성능 무효 | 정상 완료 응답으로 `ur-*` pointer 교체 검증 |
| 모든 사용자 재분석 요구 | 사용자 경험 악화 | 기존 compatible Evidence 우선 재사용 |
| Snapshot 즉시 삭제 | rollback/감사 불가 | 이번 범위 제외, 참조 audit/restore gate |
| compact result를 저장량 감소로 오인 | Snapshot TOAST가 계속 증가 | parent FK/write를 별도 계측하고 후속 전환 |
| Projection version 무제한 누적 | 디스크 재증가 | current/previous/in-flight retention |
| 361 미포함 배포 | explanation KeyError | 최신 develop 기준, 회귀 테스트 |
| 월별 Trend에 current active 적용 | 과거 수요 소실 | 별도 historical path 회귀 테스트 |
| 근접 중복을 성능 작업에 혼입 | 데이터 의미 변경 | 후속 별도 정책 작업 |

---

## 14. 파일별 예상 변경 지도

| 파일/영역 | 변경 |
|---|---|
| `BE/src/main/resources/db/c-compute/<next>_*.sql` | market sidecar와 제약/index(현재 예정 008) |
| `Infra/docker/worker/Dockerfile` | 새 migration 패키징 |
| `AI/job/projection.py` | Preview summary와 Cohort 복원 책임 분리 |
| `AI/worker/job_projection_store.py` | SQL 집계, selected-fact load, coverage |
| `AI/worker/store.py` | DB adapter와 current-result 경로 |
| `AI/worker/api.py` | query-engine flag, shadow, metric, 명시적 호출 경계 |
| `AI/worker/intake.py` | sidecar materialize/publish 통계 |
| `AI/worker/job_projection_backfill.py` | 새 Projection dry-run/publish coverage |
| `AI/worker/projection_shadow.py` | Python/SQL 비교 |
| AI tests | parity, migration, publish, matching, performance contract |
| BE compute tests | result identity/stale/current count |
| `BE/src/main/resources/db/migration/V<next>__*.sql` | failed-attempt rearm 감사(현재 예정 V26) |
| BE admin compute recovery controller/service/store | dry-run, exact CAS rearm, canary 상태 |
| `docs/ai/job-search-projection-runbook.md` | 새 migration·query-engine·backfill·rollback |
| 이 문서 | 실제 결과와 체크리스트 갱신 |

FE 계약을 바꾸지 않는 것이 기본값이다. 구현 중 응답 DTO 변경이 필요한 사실이 발견되면 additive
필드로만 추가하고 기존 화면/구 C 호환을 보존한다.

---

## 15. Jira, MR, 커밋 경계

후속 Jira 1건과 MR 1개를 사용한다. Jira가 확정되기 전 임시 작업 브랜치는
`feat/S15P21E102-360-query-hot-path`이며, 공유 전에 Jira 기준 이름을 확정한다. 공유 후에는
history를 바꾸지 않는다.

권장 Jira 제목:

```text
[AI/BE] Projection SQL 조회 및 개인화 결과 전환 보완
```

커밋 경계와 한국어 제목:

1. `[Jira] test: Projection SQL 집계 계약과 성능 기준 고정`
2. `[Jira] refactor: 수요 조회와 개인화 Cohort 복원 경로 분리`
3. `[Jira] feat: Current Market 집계 sidecar 스키마 추가`
4. `[Jira] feat: Projection SQL 수요 집계 구현`
5. `[Jira] feat: SQL shadow 계측과 기능 플래그 추가`
6. `[Jira] feat: 기존 Evidence 기반 개인화 결과 backfill 지원`
7. `[Jira] test: 매칭·추천·Trend 통합 회귀 검증`
8. `[Jira] docs: 배포·롤백·성능 검증 절차 갱신`

MR 설명에는 실제 before/after, 의도적 Current Market 정책 차이, migration 순서, query-engine과
matching compute/active feature flag,
개인화 전환 gate, 미완료 운영 관측을 포함한다.

---

## 16. 이전 대화 요구 추적 감사

아래 표는 이번 문서를 작성한 뒤 이전 대화에서 제기된 요구와 의문을 역순으로 다시 대조한
결과다.

| 이전 요구/문제 | 문서 반영 위치 | 판정 |
|---|---|---|
| develop의 미배포 변경과 함께 진행 가능한가 | §2.1, §7 Phase 0, §10 | 포함 |
| 기존 브랜치 SHA/rebase/force-push 위험 | §2.1, §7 Phase 0, §15 | 포함 |
| MR 하나 안에서 연관 작업과 커밋 분리 | §1, §15 | 포함 |
| 영어 commit이 아닌 기존 한국어 관례 | §15 | 포함 |
| 직무 변경이 실제로 느림 | §2.3, §3, §7 Phase 8 | 포함 |
| 모바일 재조회가 빠른 것은 cache 때문 | §2.3, 성능에서 cold/cache hit 분리 | 포함 |
| 지역 변경별 시간을 실제 화면/로그로 확인 | §2.3, §7 Phase 8 | 포함 |
| 직무·지역·경력을 저장 후 필터링 | §6, §7 Phase 4 | 포함 |
| 매번 계산한다면 기존 개선이 무엇인가 | §3 | 포함 |
| DB 변경 시 parser 재작성/실시간 공고 영향 | §4.1, §6, §7 Phase 3 | 포함 |
| 실시간 공고를 계속 볼 수 있는가 | complete input→새 Projection 게시 구조 §6, §10 | 포함 |
| DB 변경 파급과 연결 화면 | §4.5, §7 Phase 8, §14 | 포함 |
| 전체 로딩도 개선 가능한가 | §2.3, §5 범위/비범위 | 포함 |
| Snapshot이 과거 기술/공고를 기억하는가 | §4.4, §12 | 포함 |
| 마감 공고가 현재 화면에서 보이면 안 됨 | §4.2~4.5, §7 Phase 8 | 포함 |
| Snapshot 폐기 가치와 위험 | §12, §13 | 포함 |
| compact result만으로 Snapshot 저장이 끝나는가 | §2.2, §12 | 끝나지 않음을 명시 |
| 9월 1일 과거 공고 재구성 불가 | §4.4 | 포함 |
| 기존 추천/매칭 기능이 깨질 가능성 | §4.5, §8, §9 | 포함 |
| 검색·조사 후 서비스에 맞는 구조와 가치 판단 | §2~§6 | 포함 |
| 배포 실패와 migration/flag 순서 | §10, §11, §13 | 포함 |
| shadow가 1%라 검증이 느림 | §7 Phase 5: offline 100 + bounded 1% | 포함 |
| 두 경로를 동시에 계산하거나 바로 테스트 | offline 100 selector 선검증, 운영 shadow는 비동기 | 포함 |
| Projection인데 여전히 느린 원인 | §2.4, §3 | 포함 |
| 다른 화면에서도 개선할 부분 탐색 | §2.3, §5, §7 Phase 8 | 포함 |
| 기술 Trend/다른 화면 직접 확인 | §2.3, §7 Phase 8 | 포함 |
| EC2 실제 데이터와 시간 기반 판단 | §2.2~2.4 | 포함 |
| Current Market cross-site 중복 | §2.4, §4.3, §7 Phase 3 | 포함 |
| 화면에서 보인 같은 사이트 유사 공고 | §4.3, §5.2, §13 | 포함하되 자동 병합은 제외 |
| Skill Gap/추천 약 2초 | §2.3, §7 Phase 6~8 | 포함 |
| 기존 개인화 compute가 실제 성공 가능한가 | §2.2, §7 Phase 7, §9 | 전 attempt 실패를 반영해 canary gate 추가 |
| Job Match는 이미 빠름 | §2.3, 범위는 성능보다 일관성 | 포함 |
| What-if 후보 없어 운영 측정 못 함 | §7 Phase 8에서 후보 있는 사용자 필요 | 포함 |
| GitHub 화면도 같은 DB 수정으로 빨라지는가 | §5.2, §7 Phase 8 | 비범위 명시 |
| 사용자 재분석이 필요한가 | §7 Phase 7 | 포함 |
| 이전 Snapshot/legacy 호환 | §4.5, §11, §12 | 포함 |
| 운영 수치를 만들어내지 말 것 | §2.3/2.4 실제와 목표 구분, §8.5 | 포함 |
| 이번 수정으로 개선이 희박한 화면 | §2.5, §5.2 | 경로별 가치/비범위 명시 |

감사 결과, 이전 대화에서 제기된 구현·성능·데이터 의미·배포·운영·호환 요구는 모두 본문 또는
명시적 비범위로 분류됐다. 단, 다음은 실행 전 외부 상태로 확정해야 하며 문서 누락이 아니다.

- 후속 Jira 번호와 최종 공유 브랜치 이름
- 운영과 같은 데이터 분포에서 exact SQL `EXPLAIN ANALYZE`
- What-if 후보가 있는 검증 사용자
- 배포 window와 24시간 관측 종료 시점
- Snapshot GC의 별도 후속 Jira

---

## 17. 최종 완료 정의

### 구현

- [x] Preview와 개인화 Cohort 조회 경계가 분리됐다.
- [x] Preview가 `job_fact.payload`를 읽지 않는다.
- [x] Preview가 Pydantic 공고 객체와 Cohort를 만들지 않는다.
- [x] migration 008과 Worker packaging이 완료됐다.
- [x] Current Market sidecar가 새 Projection과 원자적으로 게시된다.
- [x] 기존 PUBLISHED version을 수정하지 않고 새 aggregation identity로 게시된다.
- [x] candidate 폭증 시 truncate 없이 publish가 실패하고 이전 head가 유지된다.
- [x] ACTIVE_MATCHING/CURRENT_MARKET SQL 의미가 기존 계약과 일치한다.
- [x] query-engine/fallback 기본값이 `python/false`다.
- [x] matching compute/active flag 기본값이 각각 `legacy`이고 독립 동작한다.
- [x] old head/no-sidecar가 안전하게 fallback한다.
- [x] 개인화는 선택 fact만 복원한다.
- [x] 기존 Evidence 기반 result backfill이 idempotent하다.
- [x] backfill 완료 응답의 `ur-*`가 BE current pointer에 저장된다.
- [x] FAILED attempt rearm이 exact CAS·ADMIN 경계·append-only 감사를 사용한다.

### 테스트

- [ ] 고정 fixture와 운영 100 selector mismatch 0이다.
- [x] Current Market expiry와 Monthly Demand history가 모두 통과한다.
- [x] migration fresh/upgrade/PostgreSQL integration이 통과한다.
- [x] AI 전체 회귀가 통과한다.
- [x] BE 전체 회귀가 통과한다(환경 의존 context test를 DB 설정 실행으로 분리).
- [x] FE test/lint/build가 통과한다.
- [x] recommendation explanation 361 회귀가 통과한다.
- [x] filter 후 fan-out 및 strict merge metric 회귀가 통과한다.

### 성능

- [ ] 직무 selector가 DB/C/BE `100/300/500ms` p95를 만족한다.
- [ ] Current Market이 DB/C/BE `250/500/800ms` p95와 C 90% 개선을 만족한다.
- [ ] C cold max <= 1s다.
- [ ] restart 후 warm-up 없이 동일 기준을 만족한다.
- [x] Preview Snapshot INSERT가 0이다.
- [ ] 개인화 cold 성능과 DB query/full Snapshot read가 §9 gate를 만족한다.

### 운영

- [ ] migration 008이 runtime보다 먼저 적용됐다.
- [ ] 서비스·데이터 서버가 같은 SHA다.
- [ ] 새 Projection `market_job` coverage 100%와 candidate count/hash가 일치한다.
- [ ] query-engine shadow 후 SQL 전환이 완료됐다.
- [ ] 기존 failed compute attempt 원인과 처리 결과가 기록됐다.
- [ ] canary `ur-*` end-to-end가 성공했다.
- [ ] current-result backfill 결과와 실패 분류가 기록됐다.
- [ ] matching projection 전환 후 네 화면이 같은 result identity를 쓴다.
- [ ] Python/legacy rollback을 실제로 실행해 검증했다.
- [ ] 기존 Snapshot을 삭제하지 않았다.
- [ ] 월별 Trend 의미가 바뀌지 않았다.

### 종료 판단

체크되지 않은 항목이 있으면 완료로 보고하지 않는다. 외부 권한·운영 window 때문에 수행할 수
없는 항목은 수행 가능한 나머지 작업을 끝낸 뒤 정확한 사유와 재현 명령을 남긴다. 성능 수치는
실제 같은 입력의 before/after 측정만 기록한다.

---

## 18. 구현 실행 기록

### 18.1 로컬에서 완료한 검증

- AI 전체 회귀: `3814 passed, 160 skipped`.
- 변경 파일 Ruff와 Python compileall: 통과. 저장소 전체 Ruff는 이번 변경 밖의 기존 위반
  201건 때문에 기준선 자체가 실패하므로 변경 파일을 별도 gate로 사용했다.
- 격리 PostgreSQL에서 migration 001→008, 007→008 upgrade, sidecar publish/readiness,
  SQL/Python parity, selected-fact 복원: 최종 집중 실행 `19 passed`.
- 고정 100 selector는 Python 집계와 SQL summary뿐 아니라 selected job ID도 mismatch 0을
  확인했다. 게시된 exact Projection ID를 고정한 persisted CLI도 100건 mismatch 0,
  checkpoint 완료 100건과 재시작 resume를 확인했다. 이는 소형 고정 fixture 결과이며
  운영 7천여 공고 결과로 대체 기록하지 않는다.
- BE는 전체 실행에서 DB 미설정 context 1건을 제외한 625건이 통과했고, 해당 context와 신규
  rearm service/store integration을 격리 PostgreSQL 환경에서 분리 실행해 모두 통과했다. DB 설정
  전체 단일 실행은 로컬 JVM native-memory 부족으로 완료하지 못했지만, 누락된 test class는 없다.
- 최초 구현 기준 FE 241 tests가 통과했고, MR 생성 직후 추가된 develop `caef5b6`
  (`S15P21E102-364`)을 merge한 최종 상태에서 249 tests, lint, production build가 통과했다.
  lint의 `CountUp.tsx` warning과 build의
  chunk-size warning은 기존 경고이며 실패는 아니다.
- `bash -n`으로 deploy/migration script 문법을 확인했고 `git diff --check`를 통과했다.
- 최종 리뷰 보완 후 rearm service/store/controller 집중 테스트를 재실행해
  `BUILD SUCCESSFUL`을 확인했고, SQL 오류→query fallback과 Projection 오류→legacy
  fallback의 request/error/fallback/reason metric 계약을 별도 테스트로 고정했다.
- persisted gate는 100 selector 실행 전·후에 exact head를 두 번 검증하고, 긴급 head
  rollback과 migration one-shot 확인은 모두 새 Worker image의 `POSTGRES_*`를 safe DSN helper로
  변환하는 명령으로 고정했다.

### 18.2 운영 환경이 필요해 미완료인 gate

다음 항목은 코드·테스트로 성공을 가정하지 않고 체크하지 않았다.

- 운영과 같은 7,786건 분포의 저장 selector JSON/seed를 사용한 offline 100 selector mismatch 0
- staging/복제본 `EXPLAIN (ANALYZE, BUFFERS)`, cold 10회와 DB/C/BE p50/p95/max,
  connect/query/temp/RSS 측정 및 §9 성능 gate
- EC2 migration 선적용, 양 서버 동일 SHA 배포, 새 Projection publish와 coverage/count/hash 확인
- bounded 1% shadow→SQL 전환과 24시간 관측
- 실제 FAILED attempt 원인 재분류, 관리자 dry-run/exact-CAS rearm, 1명 `ur-*` canary와 나머지
  bounded backfill
- 네 개인화 화면의 동일 result identity, 실제 Python/legacy rollback rehearsal, 추가 24시간 관측

이 항목들은 운영 자격 증명, 배포 window, 검증 사용자와 승인된 staging/복제본이 필요하다.
로컬 격리 DB 결과나 기존 기준선 수치를 운영 after 수치로 사용하지 않는다.

### 18.3 2026-09-21 최초 운영 gate 결과

- Jenkins #271이 `develop` `a13d7e4`를 배포했고, 양 호스트 SHA가 일치했다.
- Projection `jp-6f4261...`은 7,786건, missing fact 0, market sidecar READY였다.
- 배포 직후 Worker는 projection mode였지만 query engine은 `python`이었다. C 내부
  실측은 Current Market 11,769.5ms, 백엔드+서울 1,420.1ms, 백엔드+부산
  101.8ms, 프론트엔드+경기+신입 105.6ms였다.
- pinned persisted 100 selector gate는 100건을 모두 완료했지만 18 selector에서 mismatch가
  발견돼 SQL 전환을 중단했다. 원인 분포는 review count 7, technology category 16,
  technology rank 13이었다.
- 운영 레코드 대조로 마감일을 원본 `+09:00`과 PostgreSQL UTC에서 다르게 비교한
  cross-site fan-out과, unknown 경력 필터에서 `UNRESTRICTED`를 SQL만 strict match로 판정한
  경계가 원인임을 확인했다.
- 두 계약을 수정하고 운영 재현 fixture를 추가한 후 로컬 전체 AI `3815 passed,
  160 skipped`, 격리 PostgreSQL 집중 `19 passed`를 통과했다. 수정 SHA를 재배포한
  뒤 동일 Projection ID로 운영 100 selector mismatch 0을 재확인하기 전에는 SQL flag를
  켜지 않는다.
