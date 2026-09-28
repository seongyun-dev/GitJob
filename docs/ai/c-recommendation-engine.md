# C 후보 추천·What-if·공고 목록 계산

상태: 로컬 C1→C2→C3→C4 계산 구현 및 fixture 통합 검증. 실제 B 결과·실계정·서비스 연결은 통합 인수 대상. 기준일: 2026-09-08. Jira: S15P21E102-33.

## 실행 계약

### 현행 v9: 필수 공고 우선의 조건 영향 추천

`c-recommendation/condition-impact/v8` / `recommendation-snapshot/v4`부터 추천의
`필수 전체 충족 공고 증가` 순위와 후보 What-if는 폐기한다. 과거 v1~v7 Snapshot은
검증·조회 호환만 유지한다. 공고 매칭 화면의 `current_count`는 별도의 전체 충족 KPI라
계속 저장하지만 추천 후보를 고르거나 설명할 때 쓰지 않는다.

- ACTIVE_MATCHING `matching_jobs` 전체를 순회한다. ELIGIBLE/CONDITIONAL 모두 포함하되
  조건부를 지원 가능으로 승격하지 않는다. `requirements.required`와
  `requirements.preferred`의 **해석된 절에 후보 기술이 등장하는 공고**를 센다.
  `unresolved`나 일반 언급을 필수·우대로 승격하지 않는다. 다른 필수 절이 남아
  있거나 OR의 다른 대안을 이미 보유해도 후보 기술을 요구/우대하는 공고로 센다.
- 이 숫자는 개인의 현재 수준이나 공고의 L1~L3 요구 수준과 무관한 기술 관련 공고
  규모다. L2/L3 공고도 기술 수요로 포함하지만, L1 학습만으로 그 조건이나 공고
  전체를 충족했다고 주장하지 않는다. `current_count`의 엄격 부합 판정은 그대로다.
- 기술별 `impact.required_job_ids`, `preferred_job_ids`, `affected_job_ids`를
  중복 없는 정렬 ID로 저장한다. `affected`는 앞의 두 집합의 합집합이다. 추천 Top3는
  v8은 `affected_count`를 우선했다. v9는 `required_count` 내림차순,
  `preferred_count` 내림차순, 선행 준비 여부, 필수 수요, 불확실성, 전체 수요,
  `tech_id`로 Top3를 고른다. 필수·우대 영향이 모두 0인 일반 언급 후보는 추천하지
  않는다. Trend는 선출된 Top3 중 필수·우대 건수가 **둘 다 같은** 후보만 재정렬한다.
  두 건수는 공고가 겹칠 수 있으므로 합산하지 않는다.
- 후보에는 `impact`만 있고 구 `what_if`는 없다. 설명도 `IMPACT` Fact로 필수·우대·
  중복 제외 건수를 구분한다. Snapshot ID는 immutable content hash이며 검증 시
  저장된 impact를 동일 cohort/Evidence에서 재계산한다. C 계산 저장소의 스키마
  migration은 없다. BE는 V28로 계산 시도에 계약 버전을 추가한다.
- `GET .../snapshots/{id}`의 compact 사용자 결과는 현재 활성 공고 ID로 impact
  건수를 필터링한 조회 표현을 반환한다. 저장된 Snapshot은 변경하지 않는다. 상세
  `job-postings?mode=IMPACT&impact_kind=ALL|REQUIRED|PREFERRED`도 동일한 활성
  필터를 적용하고 건수·페이지 목록·공고별 영향 종류를 한 응답에서 보낸다.
- 추천 카드 전용 `GET .../recommendations/{id}/summary?user_id=...`는 같은 사용자
  소유권·결과 상태·활성 영향 건수를 유지하면서 held/gap 원본과 공고 ID 배열을 제외한다.
  BE 추천 조회만 이 경로를 쓰며 Skill Gap은 전체 Snapshot을 계속 읽는다. 목록은
  필수 영향이 있으면 `impact_kind=REQUIRED`, 없고 우대만 있으면 `PREFERRED`를 기본으로
  연다. 기존 v8 Snapshot은 원래 순위·ID대로 읽는다.
- 활성 필터는 저장된 Top3를 새 후보로 교체하지 않는다. 새 공고 Projection 게시로
  결과가 STALE이 되면 BE가 재계산을 요청하며, 완료 전까지 순위는 이전 계산 기준일 수 있다.
- 배포 순서는 C Worker/API → BE V28 migration 및 서버 → FE다. C가 먼저 `IMPACT` 조회를 받을 수 있어야
  BE가 구 `WHAT_IF`를 호출하지 않고 전환할 수 있다. BE 계약 버전을
  `active-matching/job-demand-v4+recommendation-v8`로 올려 기존 사용자를 새 결과로
  재계산한다. 구 FAILED/RETRYING 시도는 `legacy` 계약으로 남고 현재 계약의 재계산을
  막지 않는다. 구 결과가 아직 최신인 사용자의 새 상세 조회는 IMPACT를 보내지 않고
  `COMPUTE_PENDING`으로 대기한다. 구 결과는 호환 조회 대상으로 보존한다. 배포 후에는 재계산 완료 여부,
  추천 카드와 상세의 활성 공고 건수 일치, 필수·우대 탭 합집합, CONDITIONAL 표시를
  확인한다. **구 BE/C 바이너리만 단순 재배포하는 롤백은 안전하지 않다.** 구 BE의
  `findLatest`는 계약 버전 없이 최신 행을 고르므로 저장된 v8 결과를 구 `WHAT_IF`
  경로에 전달할 수 있고, 구 C는 v8 Snapshot을 읽지 못한다. 운영 배포 전에는 구 계약
  행을 선택하는 호환 롤백 빌드 또는 복구 가능한 DB 체크포인트를 별도로 준비하고
  실제 롤백 리허설을 통과해야 한다. v8 저장 결과를 무조건 삭제하지 않는다.

2026-09-22 추가: v9 계산 반영 시에는 C API/Worker가 v8·v9를 모두 읽을 수 있는 상태로
먼저 배포하고, 그 다음 BE 계약을 `active-matching/job-demand-v4+recommendation-v9`로
올린다. 현재 계약이 v9인 BE 화면은 기존 v8만 있는 사용자에게 재계산 완료 전까지
대기 상태를 표시한다. 운영 적용 전 재계산 큐·건수·시간을 확인해야 하며, 단순한 FE 캐시
갱신으로 v8 결과가 v9로 바뀌지는 않는다.

아래의 `current/projected/increased` What-if 설명은 **v1~v7 구 결과 계약**이다.

`AI/recommendation/engine.py`의 `build_recommendations(cohort, analysis, user_id=..., analysis_id=..., prerequisites=None)`가 `RecommendationSnapshot`을 반환한다. 입력은 [C 채용 cohort](c-job-demand.md)의 `JobCohort`와 [B Evidence 소비 입력](c-recommendation.md)의 `EvidenceAnalysis`다. 요청 user/analysis 소유권이 맞아야 하며 두 Registry 버전이 다르면 거절한다.

수요는 전달한 cohort에서 다시 집계한다. 결과에 `demand`의 직무·기간·필터·분모·원본 run·Registry·parser·quality·집계 버전, `held`의 B Rule·레벨 정책·보유 정책 버전과 근거, `gap`의 missing/unknown 구분, 전체 `prerequisite_snapshot`, `algorithm_version`, `tie_break_rule`을 함께 저장한다. 결과는 `model_dump_json()` / `RecommendationSnapshot.model_validate_json()`으로 왕복한다.

## 후보 집합과 순서

legacy 알고리즘은 `c-recommendation/lexicographic/v1~v3`으로 그대로 읽는다. v3 B
personal level과 levelled v2 REQUIRED clause를 함께 가진 새 계산은
`c-recommendation/lexicographic/v4`를 사용한다. v4는 `personal_level >= required_level`
으로 CURRENT를 계산하며 repo/evidence level을 개인 수준 fallback으로 쓰지 않는다.
새 B aggregate 계약 `evidence-consumption-input/v4`는
`c-recommendation/lexicographic/v5`로 분리한다. v5의 CURRENT와 L0→L1 What-if 숫자는
동일한 personal level 비교를 쓰되, `assessment_ceiling`과 전체 저장소 coverage를
snapshot에 고정한다. 요구 수준이 analyzer 상한보다 높으면
`ASSESSMENT_CEILING_BELOW_REQUIREMENT:{tech_id}:{level}`, 귀속·coverage가 불완전하면
`PERSONAL_LEVEL_SCOPE_INCOMPLETE:{tech_id}`를 품질 gap으로 남긴다. 이를 사용자 수준
부족이나 기술 미보유로 바꾸지 않는다.

신규 `c-recommendation/lexicographic/v6`는 ACTIVE_MATCHING의 `matching_jobs` 전체를
CURRENT·What-if·수요 분모에 사용한다. 요구 기술이 없는 공고는 목록에는 남지만
자동 충족으로 세지 않으며, REQUIRED 일부가 미해석인 공고도 CURRENT나 증가분으로
승격하지 않는다. 지역·경력 조건이 미확정인 CONDITIONAL 공고도 목록과 분모에는
남지만 현재 충족·What-if 증가분으로 세지 않는다. 저장된 v1~v5 결과의 계산식과
Snapshot ID는 유지한다.
동일 cohort의 필수·우대·일반 수요 중 `NOT_HELD`, 또는 명시적 personal L0 기술만 후보가
될 수 있고 후보 최대 수는 3개다. `UNKNOWN`은 Gap의 `unknown_tech_ids`와 `data_gaps`로
전달하며 학습 부족으로 표현하지 않는다.

v3 cohort에 levelled v2 clause와 legacy clause가 섞여 있으면 전체 계산을 held-only
legacy로 내리지 않는다. levelled 공고만 personal level로 평가하고 level 없는 REQUIRED
공고는 `REQUIRED_LEVEL_UNCONFIRMED:{job_id}` 품질 gap으로 남겨 CURRENT/What-if 증가에
보수적으로 포함하지 않는다.

2026-09-10 사용자 결정 / S15P21E102-202: 채용 중심으로 증가 공고 수를 최우선에 둔다.
선행기술은 안내·동률 기준이며 학습 완료나 기술 보유를 대신 확정하지 않는다.
v1/v2로 저장한 결과는 원래 공식과 순위를 그대로 읽으며, 새 공식으로 다시 계산한 결과는 새 Snapshot이다.

임의 합산 점수 없이 아래 값을 차례대로 비교한다.

1. 기술 하나를 추가했을 때 직접 증가한 distinct 공고 수 내림차순.
2. 증가 공고 수가 같으면 명시된 선행 기술이 모두 보유 확인된 후보 우선. 해당 정책이 선행 기술을 지정하지 않은 후보도 같은 그룹이다.
3. 해당 기술의 필수 요구 distinct 공고 수 내림차순. OR 대안도 해당 필수 수요의 관찰로 집계된다.
4. 미확정 선행 기술 수 + 후보 Evidence `data_gaps` 수 오름차순.
5. 필수·우대·일반의 합집합 distinct 공고 수 내림차순.
6. Registry `tech_id` 오름차순.

증가 공고가 0인 후보도 수요가 있으면 출력할 수 있다. `NO_IMMEDIATE_JOB_INCREASE`와 0건을 그대로 반환한다. 선행 기술이 미보유/미확정이면 각각 `missing_prerequisite_tech_ids`/`unknown_prerequisite_tech_ids`와 사유를 표시한다. 이들은 What-if에 자동 추가하지 않는다.

기본 `c-learning-prerequisites/v1`은 C가 적용하는 학습 순서 정책이다. Java→Spring Boot, Spring Boot→Spring Data JPA·Actuator, JavaScript→Node.js·React·Vue.js, React→Next.js, Python→FastAPI를 지정한다. 실제 언어 생태계 전체 의존 그래프나 사용자 숙련도를 주장하는 자료가 아니다. 목록 밖 기술은 이 정책 버전이 선행 조건을 부과하지 않는다는 뜻이다. 각 rule의 Fact ID와 전체 규칙을 결과에 저장하므로 정책 변경을 재현할 수 있다. 호출자가 다른 명시적 `PrerequisiteSnapshot`을 주면 그 정책을 그대로 저장·사용한다.

Trend는 이 순위에 가중치로 합산하지 않는다. 임의 종합 점수는 여전히 만들지 않는다.

2026-09-20 / S15P21E102-355: 다만 **이미 정해진 Top3 안에서 증가 공고 수가 사실상
같을 때**는 순서를 GitHub 주간 관측으로 가른다. 계산이 아니라 순서 규칙이므로
`algorithm_version`이 아니라 `tie_break_rule`이 갈리고, 새 규칙은
`gain-desc,top3-near-tie-weekly-active-repo-v1,prerequisites-ready,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc`
다. 후보 자격·`increased_count`·What-if는 그대로다(S15P21E102-354의 v7 계산 유지).

- **Top3 집합은 바뀌지 않는다.** 위 1~6번 비교로 Top3를 고른 **뒤에** 그 세 후보만
  재정렬한다. 4위 후보는 Trend가 아무리 높아도 이 비교에 참여하지 않는다.
- **near-tie 기준**은 더 큰 `increased_count` 대비 10% 이내다(경계 포함). 둘 다 0이면
  정확히 같으므로 near-tie이고, `0`과 `1`은 100% 차이라 아니다. 비교는 정수 연산이다.
- **무리 짓기는 leader 기준**이다. `31~29`, `29~27`이 각각 10% 안이어도 `31~27`은
  12.9%이므로 셋이 한 무리가 되지 않는다. 인접 쌍을 이어 붙이면 1위와 10% 넘게
  벌어진 후보가 Trend만으로 1위에 올라간다.
- **무리 안 비교**는 `active_repo_count` 내림차순이고, 그 다음은 위 2~6번 그대로다.
- **값이 하나라도 없는 무리는 손대지 않는다.** 측정하지 않은 것은 0이 아니다.
- 출처는 payload source `GITHUB_GH_ARCHIVE` + `granularity=WEEK`이며 기간은 그 출처가
  실제로 게시한 최신 주차다. 같은 point의 `event_count`는 쓰지 않는다 — 기술마다
  중복 합산되는 값이라 순위가 "많이 쓰이는 기술"이 아니라 "바쁜 저장소에 같이 들어
  있는 기술"이 된다.
- 근거는 결과의 `trend_tiebreak`에 `{source, granularity, period, metric, values}`로
  고정한다. 값이 있는 후보만 들어가며 최대 3개다. 근거가 있는데 `tie_break_rule`이
  예전 것이면 저장을 거절한다 — 저장된 순서를 그 근거로 재현할 수 없기 때문이다.
- Trend를 구하지 못하면 순서도 규칙도 예전 그대로이고 payload는 바이트까지 같다.
  Trend는 순서 보정이지 추천 생성의 전제가 아니다.

## What-if와 목록

legacy `simulate_what_if(cohort, selection, tech_id)`는 held set과 `{tech_id}` 하나를
비교한다. v4의 신규 기술 What-if는 후보 personal level을 **L0에서 L1로만** 투영하며
L2/L3를 가정하지 않는다. 동일 cohort에서 각 REQUIRED clause는 바깥 AND, 안쪽 ANY_OF다.
한 대안의 personal level이 required level 이상이면 충족하며 PREFERRED는 eligibility
gate가 아니다. 비어 있거나 미확정인 필수 조건은 검토로 남는다.

각 결과는 `current_count`, `projected_count`, `increased_count`와 각각의 `current_job_ids`, `projected_job_ids`, `newly_matched_job_ids`를 반환한다. ID는 중복 없이 정렬한다.

`increased_count = len(newly_matched_job_ids) = projected_count - current_count`

`list_related_jobs(snapshot, user_id=..., view=..., tech_id=None, offset=0, limit=20)`는 저장된 snapshot의 ID를 조회한다. 목록 순서는 job ID 오름차순이며 `limit` 범위는 1~100이다.

| view | tech_id | total_count와 items 의미 |
|---|---|---|
| CURRENT | 사용하지 않음 | 현재 held set으로 부합한 공고 |
| WHAT_IF | 그 snapshot의 추천 후보 | 해당 기술 하나를 추가해서 **신규로 부합한 공고만** |

따라서 예시 `current=12`, `projected=27`이면 WHAT_IF `total_count=15`다. 27개 전체 예상 공고는 `projected_job_ids`에 별도로 남는다. 페이지 바깥 offset은 빈 items와 동일 total_count를 반환한다. 공고 원본 URL, 원문 기술 Evidence, 회사·제목·필수 조건은 snapshot에 남아 숫자와 출처를 같은 결과에서 조회할 수 있다. 다른 사용자의 snapshot은 `PermissionError`로 거절한다.

## 상태·품질·설명 Fact

공고가 없거나 최소 표본 기준보다 작으면 `INSUFFICIENT_DATA`와 실제 분모를 반환하고 추천을 내지 않는다. 미보유 후보가 없고 미확정 기술이 있으면 `INSUFFICIENT_EVIDENCE`, 모두 평가됐고 후보가 없으면 `NO_CANDIDATES`다. v4에서 HELD인데 personal_level이 없으면 후보를 새로 만들지 않고 `PERSONAL_LEVEL_UNCONFIRMED:{tech_id}` data gap을 남기며, 후보가 없을 때 `INSUFFICIENT_EVIDENCE`가 된다. 후보가 있고 품질/분석 누락이 있으면 `PARTIAL`, 그렇지 않으면 `READY`다. 의도한 기간·직무 필터 제외는 집계 제외 수에 남으며, 미확정 조건의 검토 수는 `data_gaps`에도 기록된다.

v4 결과에는 `personal_levels`와 level-aware CURRENT/What-if IDs가 함께 snapshot에
고정된다. v5에는 `assessment_ceilings`와
`level_assessment_complete_tech_ids`도 함께 고정한다. 과거 recommendation v1~v4는
기존 matcher와 hash를 그대로 유지한다.
부분 matching projection은 기존 `matching_source`/`matching_job` JSONB를 재사용하므로
이 수준 계약 추가에 DB migration은 없다.

부분 분석에서 유효하게 관찰한 held 기술로 현재 부합을 계산할 수 있다. 이 숫자는 선택한 분석과 정책에서 확인된 기술 조건 부합 수이며 개인 전체 기술의 부재나 채용 합격 가능성을 뜻하지 않는다.

각 후보의 `fact_ids`는 다음 계산 사실을 식별한다. 설명 계층은 해당 structured value와 원문 참조를 사용한다.

- `demand:{cohort_id}:{tech_id}`: 같은 결과의 `demand.technologies` 행.
- `evidence:{analysis_id}:{tech_id}`: `held.technologies`의 판정과 B Fact·repository·commit provenance.
- `what-if:{cohort_id}:{tech_id}`: 후보의 `what_if` 숫자와 ID 집합.
- `job:{cohort_id}:{job_id}`: 실제 신규 공고의 `jobs` 항목과 원문 URL.
- 선행 정책의 `fact_ids`: `prerequisite_snapshot.rules`의 해당 규칙.

`snapshot_id`는 정렬·직렬화한 결과 전체의 SHA-256이다. 출력 순서, held set, 새 공고 목록, counts, 소유권을 검증하며 JSON 왕복 중 수치·목록이나 내용이 바뀌면 검증 실패한다. 같은 입력·동일 버전의 재실행은 같은 snapshot과 목록을 만든다.

## 검증과 원문

`test_recommendation_engine.py`는 AND/OR/우대, 보유 후보 제외, 분석 미확정, 선행 기술, 다중 부족 기술, 0 증가, 최대 3개·동률·순서 결정성, 빈/부족 표본, 사용자 격리, pagination, 중복 공고 ID, JSON 변조를 검증한다. 합성 원문 공고를 실제 Mapper/classifier→cohort→demand→B Evidence 소비→추천→JSON 저장/조회 경로로 실행해 분모·현재 수·신규 ID도 비교한다. 이는 로컬 fixture 통합 검증이며 실제 B API·DB·FE·운영 서버 검증을 대신하지 않는다.

- [학습 기술 후보·What-if 조회](https://app.notion.com/p/15615fc50ec78365b73401c62b4fab33)
- [관련 채용공고 목록 조회](https://app.notion.com/p/06f15fc50ec783e198ba01dfd32dce7d)
- [Evidence 정책 v2](https://app.notion.com/p/78215fc50ec7823d81e481e5ce71e50e)
