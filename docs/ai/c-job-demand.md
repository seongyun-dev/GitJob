# 채용 코호트와 기술 수요

상태: 로컬 구현 및 검증. 기준일: 2026-09-08. 관련 Jira: S15P21E102-29.

`AI/job/cohort.py`의 기본 활성 `JobCohort`를 수요 집계와 추천/What-if에 전달한다.
`AI/job/demand.py`는 이 코호트의 공고 ID를 기준으로 집계한다. A의
`job-analysis-input/v1` 입력 필드와 기존 Registry/classifier 계약은 변경하지 않는다.
과거 월별 게시 수요는 `purpose=MONTHLY_DEMAND` 코호트로 별도 계산하며 추천에 섞지 않는다.

## 호출과 버전

```python
from job.cohort import CohortCriteria, build_cohort
from job.demand import aggregate_demand

criteria = CohortCriteria(
    target_role="BACKEND_ENGINEER",
    as_of="2026-09-08T00:00:00Z",
    posted_from="2026-09-01T00:00:00Z",
    posted_to="2026-09-09T00:00:00Z",
    min_jobs=10,
)
cohort = build_cohort(batch, criteria, mapper)
demand = aggregate_demand(cohort)
payload = demand.model_dump(mode="json")
```

`batch`는 검증된 `JobAnalysisInputBatch`, `mapper`는 선택한 Registry snapshot의
`RegistryMapper`이다. mapper를 생략하면 기존 `technology_registry_v1.json`을 사용한다.
운영 실행기는 사용할 Registry를 명시적으로 선택하고 결과 버전을 함께 저장한다.
두 함수는 네트워크 요청이나 파일/DB 변경 없이 계산한다.

| 결과 | schema_version | 계산 버전 |
|---|---|---|
| JobCohort | `job-cohort/v1` | `job-cohort-quality/v5` |
| DemandSnapshot | `job-demand-snapshot/v1` | `job-demand-aggregation/v3` |

DTO는 Pydantic의 `extra="forbid", frozen=True`와 tuple 필드를 사용한다.
`model_dump_json()` / `model_validate_json()`으로 저장·복원한다. 입력 snapshot/run,
collector, Registry, classifier/parser, quality, aggregation 버전을 전달한다.
classifier `job-requirement-rules/v5`는 `[우대 자격 요건]`뿐 아니라 실제 입력의
`📋 주요업무`, `2. 자격요건`, `3. 우대사항`처럼 장식·번호가 붙은 정확한 제목도
구분한다. 이전 필수 섹션이 뒤의 우대 기술까지 이어지지 않으며, 입력의 섹션명과
요구유형은 그대로 보존한다. 제목 단어가 들어간 일반 문장을 섹션으로 바꾸지 않는다.
`회사소개`/`기업소개`에서는 앞선 담당업무 필수 범위를 종료한다. 회사 설명의
MENTIONED 기술을 지원 조건으로 승격하지 않으며 A의 원본 섹션·요구유형은 남긴다.

`cohort_id`는 정규화된 criteria, 중복 제거 후 입력 내용, 선택된 수집 시각,
입력 lineage와 계산 버전의 SHA-256이다. 입력 순서와 동일 내용 재전달 횟수는
공고 집합 ID에 영향을 주지 않는다. criteria 또는 실제 입력이 달라지면 새 ID가 된다.
`input_count`와 `duplicate_count`는 해당 호출의 전달 통계이므로 재전달 횟수를 반영한다.

## 필터와 시간

`CohortCriteria`에는 `target_role`, 필수 `as_of`, 선택 `purpose`, `posted_from`, `posted_to`,
`sources`, `regions`, `career_levels`, `min_jobs`가 있다. 시각은 timezone이 필수이며
criteria에서 UTC로 정규화한다. 현재 시각을 함수 내부에서 읽지 않는다.

- 게시 기간은 `posted_from <= posted_at < posted_to`이다. 기간 필터를 요청했는데
  `posted_at`이 없으면 `POSTED_AT_UNKNOWN`으로 검토한다.
- 기본 `purpose=ACTIVE_MATCHING`에서는 CLOSED와 `deadline <= as_of` 공고를 제외한다. ACTIVE이고 deadline이 없는 공고는
  열린 상태로 사용할 수 있다. UNKNOWN 상태는 `POSTING_STATUS_UNKNOWN`으로 검토한다.
- 미래 게시 또는 미래 수집 공고는 제외한다.
- 출처는 trim/대문자/중복 제거/정렬 후 정확하게 비교한다. 지역과 경력은 trim 후
  입력 문자열과 정확하게 비교한다. 값이 없으면 `REGION_UNKNOWN` 또는
  `CAREER_LEVEL_UNKNOWN`이다. 지역 계층이나 경력 연수를 임의로 추정하지 않는다.
- 역할은 BACKEND, FRONTEND, AI_DATA, INFRASTRUCTURE, MOBILE을 지원한다.
  `BACKEND_ENGINEER`는 BACKEND의 명시적 alias이다. 콤마 등으로 분리된 원문 직무의
  정확한 alias 또는 제목의 독립된 직무 표현을 사용한다. 본문 기술 언급만으로 직무를
  바꾸지 않는다. `AI Agent 개발자`, `AI 개발 엔지니어`는 AI_DATA에 포함하지만 `AI 서비스 UX기획자`는
  그 표현만으로 AI_DATA에 포함하지 않는다. 전체 alias 목록은 `_ROLE_ALIASES`와
  `_TITLE_ROLES`에 있다.

### 월별 게시 관측 수요

v5의 `purpose=MONTHLY_DEMAND`는 서울 기준 완료된 한 달 전체의 게시 공고를 집계한다.
예를 들어 `posted_from=2026-08-01T00:00:00+09:00`,
`posted_to=2026-09-01T00:00:00+09:00`, `as_of=2026-09-01T00:00:00+09:00`를 지정한다.
이는 호출 형식 예시이지 실제 8월 전체 표본을 확보했다는 뜻은 아니다.

월별 용도에서는 CLOSED/마감 경과만으로 제외하지 않는다. UNKNOWN 상태·본문/게시일/조건
불확실성은 여전히 검토하고, 수집 기준 시각 이후 관측을 과거 계산에 섞지 않는다.
입력 합집합은 기존처럼 최신 관측을 먼저 선택한다. 최신 본문이 없거나 상충하면 과거
정상 본문으로 되돌리지 않는다. 따라서 단순 마감 경과와 새 입력의 품질 문제는 구분한다.
월별 포함 공고의 `posting_status`를 보존하며 같은 공고 ID는 한 번만 센다.

기본 ACTIVE_MATCHING과 선택 posting_status의 빈 기본값은 JSON에서 생략해 구 추천
Snapshot의 해시·목록 형식을 유지한다. MONTHLY_DEMAND는 criteria/공고 집합 ID/저장 stream에
명시된다. 월별 코호트는 추천·What-if에서 거부하며, 기존 활성 DemandSnapshot도 월별 Trend로
재해석하지 않는다. 월별 지표의 분모·누락·0 처리와 호출은 [Trend 계약](c-public-trend.md)을 따른다.

### 현재 시장 기술 수요

`purpose=CURRENT_MARKET`은 지금 확보한 유효 공고 전체의 기술 수요다. 시계열이 아니라
한 시점의 Snapshot이므로 `target_role`과 `posted_from`/`posted_to`를 모두 거부한다.
역할을 받으면 직무 코호트가 되어 저장된 lineage가 실제 모집단과 어긋나고, 기간을 받으면
게시일 의미를 약속하게 된다. `sources`·`regions`·`career_levels`는 기존과 동일하게 쓴다.

모집단은 `jobs + exclusions`의 서로 다른 `source_site:source_posting_id`다. 직무·품질
게이트에서 빠진 공고도 같은 기술을 놓고 경쟁하므로 분모에 남긴다. 분모를 좁혀 비율을
올리지 않는다.

단 호출자가 선언한 범위 밖은 애초에 시장이 아니다. `MARKET_SCOPE_EXCLUSIONS`
(`SOURCE_NOT_MATCHED`, `REGION_NOT_MATCHED`, `CAREER_LEVEL_NOT_MATCHED`,
`COLLECTED_AFTER_AS_OF`, `POSTED_AFTER_AS_OF`)에 해당하는 공고는 모집단에서 뺀다.
공식 출처를 JOBKOREA·SARAMIN으로 지정하면 WORKNET·GAMEJOB·CAREER는 분모에도
기술 건수에도 들어가지 않는다. 기준 시각 이후에 관측된 공고도 지금의 Snapshot이 아니다.
반면 본문 미확보·상태 미상·요구 미해석은 시장 안에 있으나 해석하지 못한 것이므로 남는다.
따라서 `strict_count <= denominator <= input_count - duplicate_count`이다.

같은 공고가 JOBKOREA와 SARAMIN에 동시에 올라와도 현재는 각각 독립 공고로 센다.
cross-source 병합은 `canonical_job_id` 생산자가 생긴 뒤 ACTIVE_MATCHING과
CURRENT_MARKET에 **동일하게** 적용할 별도 작업이다. 두 purpose가 서로 다른 identity
정책을 쓰지 않는다.

집계 대상은 Registry가 해석한 관측뿐이다. `match_status=MATCHED`이고
`requirement_class`가 REQUIRED 또는 PREFERRED인 기술만 센다. 매핑되지 않은 언급은
순위를 매길 안정된 ID가 없고, SKILL(입력의 MENTIONED)은 요구가 아니라 목격이므로
`general_count`는 항상 0이다. 한 공고에서 같은 기술이 여러 번 나와도 공고 1건이다.

역할별 `matching_jobs`를 합쳐 시장 Snapshot을 만들지 않는다. 5개 직무 결과의 합집합은
같은 공고를 여러 번 세고, 어떤 직무에도 매칭되지 않은 공고를 통째로 잃는다.
CURRENT_MARKET은 추천·What-if와 월별 Trend에서 모두 거부된다.
회귀: `tests/test_current_market_demand.py`.

#### 어떻게 요청하는가

`job-cohort-resolve-selector/v1`의 `purpose`로 지정한다. 생략하면 `ACTIVE_MATCHING`이라
기존 요청은 형식도 결과도 그대로다. `CURRENT_MARKET`에는 `target_role`을 넣지 않으며
넣으면 422다. 판정은 selector가 따로 갖지 않고 위의 `CohortCriteria`가 내린다.

```json
{
  "schema_version": "job-cohort-resolve-selector/v1",
  "purpose": "CURRENT_MARKET",
  "sources": ["JOBKOREA", "SARAMIN"]
}
```

공식 모집단은 이렇게 criteria로 명시하며 코드에 고정하지 않는다. 고정하면 모집단이 바뀔
때 계약이 아니라 배포를 고쳐야 하고, 저장된 criteria만으로는 무엇을 셌는지 알 수 없다.
자동 intake 설정에 같은 criteria를 두면 poll이 최신 관측 시각에 바인딩해 미리 계산한다.
이때 지정한 source 범위만 준비하므로 조회 쪽도 같은 source를 보내야 한다.
실행 경로와 precompute 규칙은 [런타임](c-compute-runtime.md)을 따른다.
회귀: `tests/test_current_market_resolve.py`.

## 품질과 조건

본문이 TEXT_AVAILABLE이어야 한다. 입력의 필수 제목/회사명/URL 등은 기존 -90
Pydantic 입력 검증으로 보장한다. 각 비포함 공고는 `CohortExclusion`에 원본 ID,
canonical 후보 ID, 출처/URL/content hash, 판정, 모든 사유와 기술 분류 근거를 남긴다.
제외 항목에도 제목/회사, 직무·지역·경력, 본문/공고 상태, 게시·마감·수집 시각과
원본 artifact URI를 보존하여 저장된 결과에서 필터 판단을 추적할 수 있다.
필터 제외 사유가 있으면 EXCLUDED, 필터는 통과했지만 품질/조건을 확정할 수 없으면
REVIEW_REQUIRED이다. 한 공고에 여러 사유가 있어도 판정 건수는 한 번만 센다.

`CohortJob.required_clauses`는 AND로 묶인 OR 조건이다.

```text
(("java", "python"), ("spring-boot",))
=> (Java 또는 Python) 그리고 Spring Boot
```

필수 원문을 source 위치의 전체 행과 대조한다. 각각의 technology mention이 단어만
evidence_text로 제공해도 같은 행의 OR 연산자를 확인한다. 명시적 `또는`, `혹은`,
`아니면`, `or`, `중 하나`/`one of` 형태를 지원한다. 서로 다른 필수 행은 AND이다.
일반 기술 열거 및 명시적 AND는 각 필수 기술 조건으로 남긴다. slash, 혼합된 AND/OR,
누락된 대안, 미확정 열거, 부정/선택 표현, 여러 줄 증거 등은
`REQUIREMENT_LOGIC_UNRESOLVED`로 검토한다. 지원하는 제한 문법을 벗어난 문장을
일반 NLP처럼 해석하지 않는다. A의 추출 자체가 놓친 모든 기술을 복원하는 기능도 아니다.
`개발 및 운영`, `구축 및 운용`, `설계 및 구현`은 실공고에서 확인한 작업 연결 표현으로
기술 간 AND와 구분한다. 이 제한된 세 구문 밖의 미등록 AND 피연산자는 계속 검토하며,
`Java 개발 및 Cobol 운영`에서 Cobol을 조용히 버리는 식으로 완화하지 않는다.
v3는 `등을`, `등의`도 미확정 열거로 처리하고, `Java 개발 및 운영, Python 개발 경험`의
작업 연결 표현을 후속 기술 간 연산자 검사에서도 일관되게 제외한다. 원문 근거는 보존하며
진짜 기술 AND/OR·미등록 피연산자 검사는 유지한다. 변경된 품질 버전은 cohort/계산 identity에
포함되므로 v2의 판정 결과를 새 계산으로 재사용하지 않는다. 과거 불변 Snapshot 조회는 유지한다.

v4는 `Java 경험은 필수가 아닙니다`와 `Java, Python, Docker 중 2가지 이상`도
필수 AND로 확정하지 않는다. `필수는 아닙니다`, `2개 이상`, `두 가지 이상` 등의
조사·수량 표현은 검토 대상으로 남긴다. A가 기술 단어만 evidence_text로 전달하는 경우도
원본 행에서 같은 불확실성을 확인한다. 전체 근거 문장이 전달되면 classifier가
REVIEW_REQUIRED로, 단어 근거만 있으면 cohort 원문행 검사로 검토 사유를 보존한다.

필수 기술이 없으면 `NO_REQUIRED_TECHNOLOGY`, 미확정 Registry/분류가 하나라도
있으면 `TECHNOLOGY_REVIEW_REQUIRED`, 필수 원문 위치를 찾을 수 없으면
`EVIDENCE_NOT_LOCATED`로 검토한다. 빈 필수 조건을 모든 공고에 부합하는 조건으로
사용하지 않는다. 미확정 우대/일반 기술도 집계 품질을 위해 동일 코호트에서 검토한다.

`preferred_tech_ids`는 우대 기술이며 필수 매칭 gate가 아니다.
`general_tech_ids`는 기존 classifier `SKILL`을 명시적으로 GENERAL로 변환한 필드다.
원본 분류와 A의 `MENTIONED` 필드는 `technologies` provenance에 남는다.

## 입력 경로: 단일 배치와 여러 출처 통합

앞의 `build_cohort(batch, criteria, mapper)` 예제는 **명시적으로 전달한 단일 배치**를
계산한다. 자동 입력은 `AI/job/input_union.py`의
`build_input_union(outputs, criteria, mapper)`가 검증된 완료 배치를 통합한 뒤
같은 품질·수요 계산을 적용한다. 두 경로의 범위를 혼동하지 않는다.

- `outputs`는 완료 manifest의 byte hash·source/run/count를 검증한 `JobOutput` tuple이다.
  임의 JSON을 이 객체로 감싸 검증을 생략하지 않는다. 검증·발행은 [런타임](c-compute-runtime.md)의
  `load_job_output`/자동 intake 경로를 사용한다.
- 출처/공고 ID별 `as_of` 이전 최신 관측을 먼저 고르고 직무·품질 필터를 적용한다.
  최신 CLOSED/본문 미확보/직무 변경을 과거의 정상 공고로 대체하지 않는다.
  동일 최신 시각의 서로 다른 내용은 검토 대상으로 남긴다.
- 새 배치에서 안 보이는 공고는 삭제·마감으로 추론하지 않는다. 서로 다른 검색/기간 배치를
  출처별 최신 배치 하나로 덮지 않으며, 기준 시각 이후 관측은 과거 계산에 넣지 않는다.
- 통합 경로의 `job_id`는 `SOURCE_SITE:source_posting_id`이고 원래 `source_record_id`는
  별도 보존한다. 기존 단일 배치의 기본 `job_id=source_record_id` 동작은 유지한다.
- `JobCohort.input_union`은 입력 배치/run/hash와 각 원본 행의 SELECTED/DUPLICATE/
  SUPERSEDED/AFTER_AS_OF/CONFLICT 이력을 보존한다. 정책은 `c-job-input-union/v1`이다.
  수요 결과는 같은 `cohort_id`로 연결하며 큰 원본 통합 이력을 중복 저장하지 않는다.
- 통합 코호트의 `input_count`는 최신 선택/충돌 행에 대한 기존 집계 통계다. 전체 원본 관측 수는
  `input_union.input_record_count`다. 미래·대체된 행을 포함한 원본 수와 공고 분모를 혼동하지 않는다.
- 함수 입력은 최대 50,000개 원본 record/128MiB batch bytes다. 부분 수집·수정일 혼재와
  게시일 필터·검증 실패는 정상 전체 모집단으로 승격하지 않는다. 감지/보존/재시도 한계는
  런타임 문서를 따른다. 통합은 확보한 관측의 합집합이지 전체 시장의 완전한 목록이 아니다.

회귀: `tests/test_job_input_union.py`, `tests/test_job_union_intake.py`.

## 단일 배치 재전달, 충돌, Review

`collected_at`을 제외한 전체 입력 내용이 같은 경우에만 재전달로 제거하고, 수집 시각은
가장 이른 동일 내용 관측을 사용한다. 내용 해시 하나만 같다고 제거하지 않는다.
같은 출처+공고 ID 또는 같은 source_record_id에 서로 다른 내용이 있으면
`SOURCE_RECORD_CONFLICT`로 검토하여 임의 덮어쓰기를 막는다.

`canonical_job_id`는 의미 중복 후보이며 공고 삭제나 병합 근거가 아니다. 서로 다른
출처의 후보는 그대로 남는다. 기본 단일 배치는 `job_id=source_record_id`로 정렬하며,
여러 배치의 시각별 갱신 및 ID 구분은 앞 절의 통합 경로가 담당한다.

Review 저장은 실행기의 책임이다. 기존 `classify_job_batch(batch, mapper)` 결과를
`ReviewStore.ingest(classified)`에 전달하면 기존 수동 검토/재처리 경로를 재사용한다.
코호트의 제외/검토 항목도 raw technology, evidence text/section/location,
mapping attempts/evidence/candidates를 모두 보존한다. 다만 mapping context는
코호트 payload에 싣지 않는다(티켓 S15P21E102-333). 이 값은 title·evidence section·
evidence text·본문을 이어 붙인 문자열이라 기술 언급 하나마다 본문이 한 벌씩 붙고,
2026-09-18 실측에서 COHORT payload의 66.4%를 차지했다. 서빙은 읽지 않으며, 필요한
두 소비자는 코호트를 보지 않는다 — Registry mapper는 분류 도중 메모리 값을 쓰고,
사람이 검토하는 근거는 `registry_review.record.context`에 그대로 남는다. 본문은
HDFS `analysis_input`에 불변으로 있어 `classify_job_batch`를 다시 돌리면 같은 문맥이
재생성된다. 필드 자체는 과거 snapshot 호환을 위해 남겨 두고 빈 값일 때만 직렬화에서
빠진다. Registry 매핑이
수동 승인되어도 논리 미확정 조건까지 자동 승인되는 것은 아니다. 승인된 Registry와
동일 원본 입력으로 코호트와 수요를 다시 계산한다.

## 집계와 상태

각 tech_id의 REQUIRED/PREFERRED/GENERAL/전체 distinct 공고 수와 비율을 반환한다.
ACTIVE_MATCHING의 분모는 사용자가 실제 비교하는 `len(cohort.matching_jobs)`이고,
MONTHLY_DEMAND와 과거 결과는 기존 `len(cohort.jobs)` 의미를 유지한다. 한 공고에서 같은 기술이 필수와 우대에 모두
등장할 수 있으므로 전체 수는 세 수의 합이 아닌 공고 ID의 합집합이다. OR 대안은
필수 기술로 언급된 공고에 포함하며, 해당 기술 하나만의 절대 필수 여부로 해석하지 않는다.

각 범주의 순위는 공고 수 내림차순, tech_id 오름차순이다. `rank`와 `total_rank`는
전체 순위이고 `required_rank`, `preferred_rank`, `general_rank`는 범주별 순위다.
해당 범주의 관측 수가 0이면 그 범주 순위는 null이다. 비율은 0..1 값이다.
DTO 복원 시에도 분모, 합집합 수 경계, 비율과 중복 기술 ID를 검증한다.

| 상태 | 의미 |
|---|---|
| READY | 포함 공고 수가 criteria.min_jobs 이상 |
| INSUFFICIENT_DATA | 포함 공고가 있지만 min_jobs 미만. 관측값은 함께 제공 |
| EMPTY | 포함 공고 없음. 분모 0, technologies 빈 배열 |

`min_jobs` 기본값 1은 계산 가능 여부의 기본 경계이며 시장 대표성을 보장하는
통계 기준이 아니다. 표본 품질 기준은 호출자가 입력과 함께 고정한다. 준비중/실패는
실행기 상태이며 이 집계 함수가 EMPTY나 수요 0으로 변환하지 않는다.
관측된 비어 있지 않은 코호트에서 특정 기술이 없을 때의 관측 0과 코호트 EMPTY는
별개다. v2와 MONTHLY_DEMAND는
`input_count = denominator + duplicate_count + excluded_count + review_count`를 유지한다.
v3 ACTIVE_MATCHING은 `denominator = matching_count`이며 직무·상태·지역·경력 필터를
통과해 상세 비교에 남은 공고를 모두 센다. 요구 기술이 없거나 일부 미해석인 공고도
분모에는 남지만 확인되지 않은 기술을 REQUIRED/PREFERRED 건수로 만들지 않는다.
과거 Snapshot과 `MONTHLY_DEMAND`에는 `matching_count`가 없을 수 있다.

## 검증과 출처

`tests/test_job_cohort.py`, `tests/test_job_demand.py`는 AND/OR, 누락된 대안,
필수 기술 없음, 미등록, 중복 언급·재전달·source 충돌, 기간·직무·지역·경력 필터,
순서와 해시 재현성, 원문 근거 보존, 수기 distinct 기대값 및 JSON 왕복을 검증한다.
실데이터 배포·반복 수집·B 사용자 Evidence 연동의 완료 근거는 별도 서비스 통합 검증이 필요하다.

### 실제 입력 품질 인수 범위 (2026-09-08)

저장된 Worknet 5건·Saramin 5건과 승인된 제한적 Saramin 백엔드 직무 수집 4건을
`registry-20260908.1`, parser v4, quality v2로 검수했다. 새 수집은 robots 확인과
목록 응답 크기 조정 재요청을 포함해 총 7 GET으로 종료했다. 새 4건은 원본 HTML
SHA-256, 상세 본문 재파싱, 목록의 직무·제목·URL을 입력과 대조했다. 이전 10건은
저장된 -90 본문·manifest까지만 대조했으며 당시 HTML은 보존되어 있지 않았다.

아래 결과는 `as_of=2026-09-08T02:00:00Z`, `min_jobs=2`, 게시 기간 필터 없이 계산한
각 배치의 결과다. 수집 범위가 달라 행 사이 분모를 합치거나 시장 수요로 일반화하지 않는다.

| 실제 입력 배치 | BACKEND 포함/제외/검토 | AI_DATA 포함/제외/검토 |
|---|---|---|
| Worknet 9/7, dev 직종 5건 | 0 / 5 / 0 | 0 / 5 / 0 |
| Saramin 9/7, dev 직무 5건 | 0 / 4 / 1 | 1 / 4 / 0 |
| Saramin 9/8, 백엔드 직무 4건 | 0 / 0 / 4 | 0 / 3 / 1 |

AI_DATA의 1건은 Python 필수 관측이며 `INSUFFICIENT_DATA`다. 새 백엔드 4건은
필수 기술 미기재 2건, `등`을 포함한 조건 미확정 1건, 미등록 MariaDB 포함 1건이므로
`EMPTY`를 유지한다. MariaDB를 MySQL로 합치거나 태그의 Java를 필수 기술로 승격하지 않는다.
모든 배치의 재실행·입력 순서 불변성, 동일 레코드 재전달 시 코호트/공고 ID 불변성,
DTO JSON 왕복을 별도로 확인했다. 원본 데이터와 개별 검수표는 제품 저장소에 넣지 않는다.

### 수집 품질과 게시일의 한계

- `job-analysis-input/v1`은 완료 manifest의 중단·누락 통계를 직접 포함하지 않는다.
  실행기는 manifest의 `stopped_reason`, 상세 실패, invalid record 등을 검증해야 한다.
  문제가 있는 배치를 정상 부분 표본으로 자동 게시하려면 먼저 별도의 부분 수집 정책과
  품질 전달 계약이 필요하다. C 계산 함수의 정상 종료만으로 수집 완료를 판정하지 않는다.
- Saramin 9/7 manifest는 등록일 4/수정일 1, 새 9/8 manifest는 등록일 2/수정일 2였다.
  현재 A 입력의 `posted_at`에는 행별 등록일/수정일 구분이 없으므로 이 값으로 실제
  게시일 기준 월별 JOB Trend를 검증했다고 주장할 수 없다. 날짜 필터를 쓰는 실행기는
  수정일이 섞인 manifest를 차단하며, 게시일 근거가 확인된 별도 배치가 필요하다.
- Worknet 5건은 `raw_job_category`가 모두 비어 있고, 일부 제목도 잘려 있다.
  `ROLE_NOT_MATCHED`는 현재 입력에서 명시적 직무를 확인하지 못했다는 뜻이지,
  원문 직무가 기술 직무가 아님을 증명하지 않는다. 본문 키워드로 직무를 임의 확장하지 않는다.
- 한국어 `파이썬`·`리눅스`, `springframework`, `eGovFramework`, 일부 AI 도구 등은
  A의 기술 언급 목록에서 누락된 사례가 있다. 현재 결과는 전달된 기술 언급과 고정 Registry의
  관측이며 모든 자격요건을 복원한 결과가 아니다. 예컨대 Python 한 기술의 부합을 해당
  AI 공고 전체 자격 충족으로 설명하지 않는다. 원문 링크와 이 제한을 함께 제공해야 한다.

- [기술 수요 집계 원문](https://app.notion.com/p/32a15fc50ec782deaf61814349d717c3)
- [What-if와 학습 기술 후보 원문](https://app.notion.com/p/15615fc50ec78365b73401c62b4fab33)
- [기존 A-to-C 입력 계약](../data/2026-09-01-a-to-c-job-analysis-input-contract.md)
