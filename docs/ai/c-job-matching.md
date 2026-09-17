# 공고별 부분 부합 — C 내부 계약

상태: S15P21E102-183/184/185 로컬 구현·단위/HTTP·격리 PostgreSQL 검증, 2026-09-09.

## 의미

필수·우대 각각의 요구 조건을 사용자 확인 기술로 평가한다. OR는 한 대안을
충족하면 조건 하나를 충족한다. 미보유와 분석 미확정은 구분한다. 필수 조건이
없으면 자동 100%가 아니며, 조건 해석 또는 사용자 근거가 미확정이면 전체 비율은 null이다.
기술 요건 충족 비율은 합격 가능성이나 개인 숙련도 점수가 아니다.

`job-requirements/v2` REQUIRED clause는 `required_level(L1~L3)`과 그
`level_evidence_refs`를 함께 가진다. `evidence-consumption-input/v3`에서는 B가
명시한 `personal_level(L0~L3)`만 이 수준과 비교한다. 과거 `evidence_level`은
repository 관측 축이므로 개인 수준의 fallback으로 쓰지 않는다. v3에서 accepted
proof가 뒷받침하는 positive personal level은 분석이 PARTIAL이어도 보존하지만,
관측되지 않았거나 level/proof/범위가 불완전한 기술은 수준이 아니라 Evidence 품질
unknown이다.

`evidence-consumption-input/v4`는 repository별 임시 personal level 대신 B가 전체
선택 저장소를 합산한 `personal_assessments[]`를 소비한다. 각 항목은 `tech_id`,
`personal_level`, `assessment_ceiling`, `attribution_status`, `missing_scope[]`를 가진다.
`assessment_ceiling`은 B의 현재 Rule Pack과 귀속 범위로 그 기술의 수준 부재를 판정할
수 있는 최고 단계다. `personal_level`보다 낮을 수 없으며, C는 repository
`evidence_level`을 둘 중 어느 값으로도 대체하지 않는다.

양성 판정은 보수적으로 지우지 않는다. 따라서 유효 proof의 personal level이 공고
요구 이상이면 다른 저장소가 PARTIAL이어도 `SATISFIED`다. 반대로 수준 부족은 모든
선택 저장소가 COMPLETE·coverage complete·해당 기술 평가 완료·사용자 참여 확인이고,
B 귀속 상태가 COMPLETE이며 `assessment_ceiling >= required_level`일 때만 확정한다.
상한이 요구보다 낮거나 coverage/귀속이 불완전하면 `LEVEL_BELOW_REQUIRED`가 아니라
`EVIDENCE_SCOPE_INCOMPLETE`다. 완전 범위에서 기술 evidence 자체가 없는 경우만 기존
`TECHNOLOGY_NOT_HELD`다.

수준 clause의 `verdict`는 다음 중 하나다: `SATISFIED`(ANY_OF 중 하나가
personal level 이상), `LEVEL_BELOW_REQUIRED`(완결적인 보유 evidence는 있으나
수준 부족), `TECHNOLOGY_NOT_HELD`(완결적인 부재),
`EVIDENCE_SCOPE_INCOMPLETE`(범위·proof·personal level 미확정). 공고 문장 자체가
미해석이면 기존 `unresolved`에 보존한다. 다만 같은 REQUIRED 문장에서 확인된 기술
clause를 사용자가 하나라도 충족하면 공고 전체를 UNKNOWN으로 숨기지 않고 outer
PARTIAL로 표시한다. 확인된 clause가 하나도 충족되지 않았고 `unresolved` 때문에
불충족도 확정할 수 없을 때만 outer UNKNOWN이다. PREFERRED는 같은 방식으로 보이되
REQUIRED eligibility를 탈락시키지 않는다.

v1/v2 Evidence 입력은 personal level 축이 없던 역사 입력이다. 이 경우 추천의 기존
held-only 의미와 일치하도록 proof-supported HELD 조건을 `LEGACY_HELD_MATCH`로
표시한다. 이는 사용자 수준이 공고 요구 이상이라는 판정이 아니며, 신규 v3/v4 입력에는
사용하지 않는다.

`job-requirements/v2`의 levelled clause assessment는 personal level이 비어도
`EVIDENCE_SCOPE_INCOMPLETE` verdict를 반드시 저장한다. verdict가 없는 historical
assessment는 level field 자체가 없던 requirements v1만 legacy read로 허용한다.

기존 CURRENT/WHAT_IF의 엄격한 전체 필수 충족 기준은 유지한다. 부분 부합 결과는
해당 목록이나 증가 수에 합산하지 않는다. 확정된 마감/필터 불일치, 본문 미확보,
원본 충돌은 부분 부합 목록에도 포함하지 않는다. 필터 또는 공고 상태 자체가
불명확한 경우 CONDITIONAL로 분리하고 확정 조건을 통과했다고 표시하지 않는다.
`eligibility`는 직무·공고 상태·설정한 지역/경력 필터에 관한 값이며 기술 조건의
전체 충족을 뜻하지 않는다. `strict_match_eligible=false`의 이유는
`strict_review_reasons`에 별도로 보존한다. 일반 기술스택의 미등록 기술 때문에
엄격 코호트에서 빠진 공고도 이유를 잃지 않는다.

## 저장 및 자동 실행

새 COHORT payload의 선택적 matching_jobs는 동일 관측에서 생성한 요구절과 원문
근거를 보존한다. 옛 COHORT의 필드 누락은 준비 안 됨이며 빈 모집단과 다르다.
사용자 분석 완료 API는 기존 추천 계산과 함께 부분 부합을 계산한다.

`job-matching/v3`는 사용자 부합을 parser 완결성보다 먼저 보이도록 상태와 정렬 의미를
명시한다. 중복 요구절과 원문 근거는 사용자 RECOMMENDATION마다 복제하지 않는다.
`002_job_matching_projection.sql`의 `matching_source`가
`(cohort_snapshot_id, job_id)`별 불변 `MatchingJobInput`을 한 번 보존하고,
`matching_calculation`은 계산 ID·작은 metadata·전체/적격/조건부 count를,
`matching_job`은 안정 position과 사용자별 held/missing/unknown 판정만 보존한다.
추천 payload에는 전체 결과 대신 `job_matching_ref(job-matching-storage/v2)`만 둔다.
compact 사용자 assessment 행은 바깥 `evidence_input_version`을 필수로 저장하고 각
수준 clause의 ceiling-aware mode와 대조한다. 따라서 v4 저장 행에서 ceiling 필드를
삭제해 legacy 수준 부족 판정으로 바꾸는 입력은 조회 시 무결성 오류다.
세 저장은 기존 추천 snapshot/head/event 완료와 같은 transaction에서 게시한다.
같은 cohort 원본을 다른 사용자가 평가해도 요구절/evidence는 공유 원본을 참조한다.
게시된 shared source와 assessment 행의 UPDATE/DELETE는 DB trigger가 거절한다. 런타임
role에도 이 두 권한을 부여하지 않는다. 초기 행 수·hash·참조 검증이 끝나기 전에는 같은
transaction이 완료되지 않으므로 child 유실을 축약된 정상 결과로 게시하지 않는다.
게시 transaction은 부모 `job_matching_ref`와 calculation ID·cohort snapshot·job count,
부모 recommendation의 analysis/cohort scope를 대조한 뒤 작은 전용 열에 결박한다. 이후
compact 조회는 이 불변 header를 기준으로 하며 부모 payload를 매번 재검증하지 않는다.
trigger와 runtime 최소 권한은 정상 애플리케이션 경로의 불변 계약이지, table owner/DB
관리자가 trigger를 비활성화하거나 직접 schema를 바꾸는 행위까지 막는 보안 경계는 아니다.

`calculation_snapshot_id`는 생성 시 전체 논리 결과를 canonical JSON으로 한 번 hash한
불변 값이다. 이 필드 자신은 hash 입력에서 제외하고, 사용자·분석·cohort·정책·정렬된
전체 평가를 포함한다. 추천 snapshot ID는 이 계산 ID를 가진 reference를 포함하므로
sidecar와 결박된다. 조회에서는 이 값을 다시 계산하지 않는다. 설명/추천 정책만 달라져
RECOMMENDATION snapshot이 달라져도 같은 matching 계산 ID를 재사용할 수 있으므로 계산 ID는
DB 전역 unique key가 아니다.

## 내부 조회

- GET /internal/v1/c/recommendations/{snapshot_id}/matching-job-postings
  - user_id 필수, page는 기존 C API처럼 0-base, size 1~50.
  - include_conditional 기본 false. true인 경우에도 각 공고의 조건부 상태를 유지.
  - 이미 저장된 결과만 읽고 조회 시 재분석하지 않는다.
- GET /internal/v1/c/recommendations/{snapshot_id}/matching-job-posting
  - user_id와 job_id 필수. 같은 저장 결과의 공고 상세를 반환한다.

새 v2 결과의 두 경로는 snapshot PK/kind/owner와 작은 계산 metadata 열만 읽고 부모
RECOMMENDATION payload에는 접근하지 않는다. 필요한 `LIMIT/OFFSET` 행 또는
단일 `job_id`만 읽고 shared source를 PK join한다. 전체 RECOMMENDATION/COHORT JSONB를
전송·TOAST 해제하거나 전체 `JobMatchingResult`를 model_validate/sort/hash하지 않는다. MR 보완 전
`job_matching/v1`을 본문에 포함해 저장한 snapshot은 호환 조회하되 해당 옛 결과에만
전체 payload fallback 비용이 남는다.
legacy embedded payload도 50,000공고/64 MiB 상한을 적용하며 초과 결과를 일부만
반환하지 않고 413 `LEGACY_MATCHING_RESULT_TOO_LARGE`로 명시한다.

3,000건의 짧고 반복적인 합성 공고 1사용자 측정에서는 논리 JSON 합계가
23,123,470 bytes에서 20,996,724 bytes로 9.2% 감소했다. 반면 행·인덱스 overhead를
제외한 PostgreSQL column 크기는 기존 parent 2,683,282 bytes에서 새 parent
2,514,031 + shared source 4,992,000 + assessment 2,031,000 + metadata 636 =
9,537,667 bytes로 증가했다. 큰 반복 JSONB의 TOAST 압축이 작은 분리 행보다 유리한
합성 입력 특성 때문이다. 따라서 절반 저장 감소나 1사용자 물리 저장 절감을 주장하지
않는다. 이번 projection의 확인된 이점은 bounded 조회와 cohort 원본의 사용자 간 재사용이며,
실제 공고 길이·사용자 수에 따른 운영 저장량은 별도 용량 측정이 필요하다.

같은 3,000건 합성 입력의 loopback PostgreSQL/in-process ASGI 진단에서 전체 실행은
8.92초(cohort 2,457.84ms, 개인 계산·저장 4,576.04ms), 20건 페이지 5회 중앙값은
40.1ms(38.7~45.21ms), 마지막 페이지는 42.5ms였다. 4동시 8요청은
39.09~155.85ms, 별도 단일 조회 Python tracemalloc peak는 582,966 bytes였다.
보완 전 같은 3,000건 페이지 중앙값 2,458.28ms와 달리 마지막 페이지도 source 20건만
PK join한다. DB I/O·네트워크·운영 동시성을 대표하는 보장은 아니며, 단일 로컬 합성 진단이다.

두 경로 모두 기존 내부 Bearer 인증을 요구한다. B는 로그인 사용자 식별자를
연결하고 사용자 권한을 검증한다. FE에 C 토큰을 전달하지 않는다.
다른 사용자/없는 결과는 404, 옛 결과의 부분 부합 미생성은 409로 구분한다.
owner 확인 후 저장 reference의 user/analysis/cohort나 shared source가 불일치하면 입력
오류가 아니라 서버 저장 무결성 실패다. 이 경우 내부 값을 노출하지 않고 500
`STORED_MATCHING_INTEGRITY_FAILED`를 반환하고 진단 로그를 남긴다. 보완 전 같은
scope mismatch가 전역 ValueError handler에서 422 `INVALID_INPUT`으로 잘못 분류되던
동작을 변경한 것이다.
옛 추천 Snapshot 및 CURRENT/WHAT_IF 조회는 계속 가능하며 조회 시 새 필드를 만들지 않는다.

### 응답 해석 예시

목록은 `data.items[]`, 상세는 `data.item`에 **동일한 JobAssessment**를 반환한다.
아래는 합성 Java 보유 사용자에 대한 주요 필드 발췌이며 전체 JSON은 아니다.

| 공고 조건 | required_status | 충족 / 미충족 / 사용자 미확정 | fulfillment_ratio |
|---|---|---|---|
| Java 필수 | FULL | 1 / 0 / 0 | 1.0 |
| Java, Docker 필수 · Docker 평가 완료/미관측 | PARTIAL | 1 / 1 / 0 | 0.5 |
| Java 필수 + 별도 `Python, Docker 등을 활용` | PARTIAL | 1 / 0 / 0 + 미해석 1개 | null |
| Java 또는 Python · 두 기술 모두 미평가 | UNKNOWN | 0 / 0 / 1 | null |
| 기술 필수 조건 추출 없음 | NOT_APPLICABLE | 0 / 0 / 0 | null |

`required`와 `preferred`는 별개다. 각 조건의 `clause.tech_ids`는 OR 대안이며,
`missing_tech_ids` 전체를 반드시 배워야 할 기술 목록처럼 표시하면 안 된다.
`unknown_count`는 사용자 Evidence 미확정이고 `unresolved`는 공고 문장 해석 미확정이다.
회사 조건 전체·경력 연차 충족·자격증·합격 가능성은 이 비율에 포함하지 않는다.

```json
{
  "required_status": "PARTIAL",
  "required": {
    "satisfied_count": 1,
    "unsatisfied_count": 1,
    "unknown_count": 0,
    "fulfillment_ratio": 0.5,
    "unresolved": []
  }
}
```

목록 상위 필드는 저장 `snapshot_id`, 별도 계산 `calculation_snapshot_id`,
`cohort_id`, `analysis_id`, `criteria`, Registry/Evidence 정책 버전,
`total_count`, `conditional_count`, `excluded_conditional_count`, `page`, `size`,
`has_next`, `data_gaps`다. `conditional_count`는 mode와 무관한 저장 결과 전체의 조건부
공고 수다. `total_count`는 현재 mode의 반환 대상 수이고,
`excluded_conditional_count`는 기본 false에서 `conditional_count`, true에서 0이다.
예를 들어 적격 2·조건부 1이면 false는 total=2/conditional=1/excluded=1,
true는 total=3/conditional=1/excluded=0이다. 페이지 경계는 이 반환 집합의 안정 position을
따른다. 새 `job-matching/v3` 정렬은 적격 여부 →
FULL/PARTIAL/UNKNOWN/NONE/NOT_APPLICABLE → 확정 미충족 수가 적은 순 → 확정 충족
수가 많은 순 → 사용자 미확정과 원문 미해석 수가 적은 순 → 우대 충족 수 → job_id
순으로 고정한다. 따라서 FULL이 20건보다 적으면 첫 페이지의 남는 자리를 사용자에게
확인된 기술이 있는 PARTIAL이 채우며, 완전 해석됐지만 전부 미충족인 NONE이 앞서지 않는다.
기존 v1/v2 저장 결과는 저장 당시 상태와 정렬을 그대로 읽는다.
과거 Snapshot에는 새 결과를 덧붙이지 않으며 새 정책 계산은 새 완료 event ID를 사용한다.

비율의 정본은 `satisfied_count`, `unsatisfied_count`, `unknown_count` 정수다. 확정 조건은
정수에서 비율을 다시 만들고, JSON 경계에서 소수 6자리 반올림은 절대 오차 5e-7 이내만
받은 뒤 정본 비율로 canonicalize한다. 그 밖의 오차, NaN/Infinity는 거절한다.
UNKNOWN 또는 미해석 조건은 오차 범위와 무관하게 반드시 null이다. compact 행에는
float 비율을 저장하지 않고 조회 시 정수 count에서 파생한다.

입력 HTTP body는 기존 8 MiB 제한을 유지한다. matching 결과는 최대 50,000공고,
shared source 1행 512 KiB, 사용자 assessment 1행 64 KiB, 논리 결과 전체 source+assessment
64 MiB를 한도로 한다. 초과 시 일부 top-N을 정상 결과로 게시하지 않고 전체 계산을
실패 처리하여 413 `RESULT_TOO_LARGE`를 반환한다. 자동 intake의 원본 50,000건/128 MiB
예산은 별도 입력 검증이며, ACTIVE_MATCHING에서는 최신 complete active snapshot 선택 후
계산 대상에 적용한다. 과거 회차의 manifest·hash 무결성 검증은 생략하지 않는다.
둘 중 하나를 통과했다고 다른 예산 통과를 뜻하지 않는다.

## 수집·정규화 변경과 기존 입력

- SpringBoot/Postgres 추출과 원문 위치를 보존한다.
- 날짜만 있는 마감은 다음날 서울 00:00의 종료 제외 경계로 저장한다. 시각이 있는
  timestamp는 그대로 보존한다. 기존 저장값의 00:00만 보고 날짜형으로 재해석하지 않는다.
- 시/도 별칭·복수 지역, 신입/경력무관/혼합 경력을 해석하되 미확정은 확정 불일치와 구분한다.
- Worknet 상세의 경력·근무지는 표 설명이나 기업 주소가 아니라 해당 항목 값을 읽는다.
  `직무내용`은 기존 담당업무와 동일하게 해석한다. 원문 본문은 유지한다.
- `담당업무`, `주요업무`, `직무내용`, `responsibilities`의 기술 업무 문장은 현재
  `job-requirements/v2`에서 지원자 REQUIRED clause로 만들지 않는다. 회사소개·기업소개와
  일반 기술스택 나열도 마찬가지로 요구절이 아니다. 지원자격/자격요건 등 명시적 requirement
  surface의 근거만 levelled REQUIRED clause가 될 수 있다.
- `ACTIVE_MATCHING`의 strict 공고도 같은 `job-requirements/v2` REQUIRED clause를
  사용한다. 우대 조건의 미해석은 strict 판정을 막지 않지만, REQUIRED 일부가 미해석이면
  확인된 기술을 보존하더라도 공고 전체를 확정 부합으로 올리지 않는다.
- JobKorea의 `스킬`은 일반 기술 영역이며, 그 아래 `ㆍ필수`, `ㆍ우대`처럼 명시된 행만
  각각 REQUIRED/PREFERRED로 해석한다. C 공고 추출기가 인식하는 표기 변형
  (`SpringBoot`, `React.js`, `HTML5` 등)은 Registry 44의 정식 표시명으로 재확인하며
  원문과 위치는 그대로 보존한다.
- 새 입력 버전은 `worknet-collector/v2`, `saramin-collector/v2`,
  `gamejob-collector/v2`, 기간 수집 `jobkorea-crawler/v2`, 전체 활성 스냅샷
  `jobkorea-crawler/v3`다. 기존 v1/v2 데이터는 변경하지 않는다. v3의 16개 duty token은
  쉼표·세미콜론·파이프로 분리한 exact category 단위에서만 다섯 서비스 직무로 매핑한다.
- C 분류 `job-requirement-rules/v8`, 품질 `job-cohort-quality/v7`,
  요구절 `job-requirements/v2`(v1 read 호환), 부분 평가 `job-matching/v3`, 저장 표현
  `job-matching-storage/v2`를 새 계산에 기록한다.

## 동일 표본 필터 영향 비교

보존 텍스트 50건, 같은 기준 시각 `2026-09-09T00:00:00+09:00`, Worker Registry
`registry-20260908.1`에서 MR 기준 `d136c1a`와 보완 전 HEAD `e08060a`를 같은 조건으로
비교했다. 수치는 `포함/제외/검토`다.

| 조건 | d136c1a | e08060a | 확인한 변화 |
|---|---:|---:|---|
| BACKEND 무필터 | 0/49/1 | 1/49/0 | 같은 FDE 공고 1건이 확정 포함으로 이동 |
| FRONTEND 무필터 | 0/48/2 | 1/48/1 | 위와 같은 1건이며 별도 증가가 아님 |
| INFRA 무필터 | 0/49/1 | 0/48/2 | 검토 1건 증가, 포함 증가는 없음 |
| BACKEND + 서울 | 지역 불일치 30 | 지역 불일치 24 | 지역 필드 재해석 영향, strict 포함 증가는 0 |
| BACKEND + 신입 | 경력 불일치 50 | 경력 불일치 49 | 경력 필드 재해석 영향, strict 포함 증가는 0 |

비교 cohort는 collector v1 저장 `region`/`career_level`을 그대로 사용했고, 변화는 그
기존 저장 필드에 대한 지역 별칭과 경력 3값 필터 해석 변경이다. 경력 텍스트 21건·지역
텍스트 17건의 별도 재파싱 건수는 이 비교 입력도, cohort 증가 건수도 아니다.
이 비교는 보존 텍스트 기반이며 원본 HTML 재수집·collector v2 운영 재발행 증거가 아니다.

## 검증 기준

AND/OR·우대 OR·UNKNOWN·미해석·조건 없음·중복 근거·원본 범위 단위 테스트,
새 공고→분석 완료→저장→목록/상세, 재전달/재시작/사용자 격리와 과거 결과 조회를
검증한다. 실제 공고 검수와 합성 사용자 입력, 운영 배포/FE 연결 증거는 구분한다.

2026-09-09 최초 MR 로컬 검증: AI 전체 **1,267 passed / 47 skipped**,
변경 Python 22개 Ruff check/format 통과. 부분 부합 HTTP는 메모리 저장소를 사용한
계산→직렬화→목록/상세·재전달·앱 재구성·타 사용자/옛 결과 접근을 검증했다.
당시 같은 5개 시나리오의 PostgreSQL 실행은 `C_COMPUTE_TEST_DATABASE_URL` 미설정으로
건너뛰었다. 이번 보완에서는 loopback 전용 격리 EDB PostgreSQL 16.15에 001→002를
명시 적용하고 같은 HTTP/저장 회귀를 실행했다. 이는 운영 컨테이너 PostgreSQL 16.4-alpine,
B/FE 또는 운영 데이터 인수가 아니다.
PG 프로세스를 실제 stop/start한 뒤에도 새 projection 결과와 embedded v1 결과의 페이지
JSON SHA-256 및 목록/상세가 각각 재시작 전과 같음을 확인했다.
최종 보완 코드 기준 전체 AI 테스트는 **1,350 passed / 2 skipped**였고, 두 skip은
메모리 전용 검사가 PostgreSQL 매개 실행을 건너뛰는 경우와 PostgreSQL trigger 검사가
메모리 매개 실행을 건너뛰는 경우다. PostgreSQL 경로 자체는 실행됐다. 변경 Python 9개는
Ruff check/format을 통과했으며, 의존 라이브러리의 기존 deprecation warning 2개가 남는다.

재현 환경은 Python 3.12.14, Pydantic 2.13.5, FastAPI 0.141.1, psycopg 3.3.3,
pytest 9.1.1이며 저장소 의존성 파일은 변경하지 않았다. `AI` 디렉터리에서 다음처럼
실행한다. 두 DB 환경 변수는 다른 서비스와 공유하지 않는 격리 테스트 DB를 명시해야 한다.

```powershell
python -m pip install -r requirements-dev.txt
$env:C_COMPUTE_DATABASE_URL = '<isolated-postgresql-dsn>'
python -m worker.migrate
$env:C_COMPUTE_TEST_DATABASE_URL = $env:C_COMPUTE_DATABASE_URL
python -m pytest tests/test_compute_matching.py tests/test_compute_store.py tests/test_compute_api.py tests/test_job_matching.py tests/test_job_requirements.py -q
python -m pytest -q
```

DB 환경 변수가 없으면 PostgreSQL 매개 테스트는 명시적으로 skip되며 메모리 통과를
내구성·FK·trigger·재연결 증거로 바꾸어 쓰지 않는다.

별도 보존한 Worknet 실공고 50건에 대해 현재 Worker 기본 Registry
`registry-20260908.1`로 원문 범위와 요구절을 점검했다. 상세 텍스트를 최소 HTML로
재구성한 필터 비교에서는 기존 `경력` 중 21건에 신입 허용/경력무관 값이 있었고,
지역 누락 17건에서 항목 값을 찾았다. 이는 원본 HTML 재수집·운영 입력 재발행이 아니다.
원본에서 지역이 모순되거나 기술 요건 본문이 부족한 경우는 여전히 확정하지 않는다.
기존 저장 배치를 자동 덮어쓰지 않으므로 운영 반영 후 **새 버전 입력 재생성**이 필요하다.
