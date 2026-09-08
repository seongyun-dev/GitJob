# C 후보 추천·What-if·공고 목록 계산

상태: 로컬 C1→C2→C3→C4 계산 구현 및 fixture 통합 검증. 실제 B 결과·실계정·서비스 연결은 통합 인수 대상. 기준일: 2026-09-08. Jira: S15P21E102-33.

## 실행 계약

`AI/recommendation/engine.py`의 `build_recommendations(cohort, analysis, user_id=..., analysis_id=..., prerequisites=None)`가 `RecommendationSnapshot`을 반환한다. 입력은 [C 채용 cohort](c-job-demand.md)의 `JobCohort`와 [B Evidence 소비 입력](c-recommendation.md)의 `EvidenceAnalysis`다. 요청 user/analysis 소유권이 맞아야 하며 두 Registry 버전이 다르면 거절한다.

수요는 전달한 cohort에서 다시 집계한다. 결과에 `demand`의 직무·기간·필터·분모·원본 run·Registry·parser·quality·집계 버전, `held`의 B Rule·레벨 정책·보유 정책 버전과 근거, `gap`의 missing/unknown 구분, 전체 `prerequisite_snapshot`, `algorithm_version`, `tie_break_rule`을 함께 저장한다. 결과는 `model_dump_json()` / `RecommendationSnapshot.model_validate_json()`으로 왕복한다.

## 후보 집합과 순서

현재 알고리즘 버전은 `c-recommendation/lexicographic/v2`이다. 동일 cohort의 필수·우대·일반 수요에 관찰된 기술 중 C 정책에서 `NOT_HELD`인 기술만 후보에 넣는다. `HELD`와 `UNKNOWN`은 제외한다. 후보 최대 수는 3개다. `UNKNOWN`은 Gap의 `unknown_tech_ids`와 `data_gaps`로 전달하며 학습 부족으로 표현하지 않는다.

임의 합산 점수 없이 아래 값을 차례대로 비교한다.

1. 명시된 선행 기술이 모두 보유 확인된 후보 우선. 해당 정책이 선행 기술을 지정하지 않은 후보도 같은 그룹이다.
2. 기술 하나를 추가했을 때 직접 증가한 distinct 공고 수 내림차순.
3. 해당 기술의 필수 요구 distinct 공고 수 내림차순. OR 대안도 해당 필수 수요의 관찰로 집계된다.
4. 미확정 선행 기술 수 + 후보 Evidence `data_gaps` 수 오름차순.
5. 필수·우대·일반의 합집합 distinct 공고 수 내림차순.
6. Registry `tech_id` 오름차순.

증가 공고가 0인 후보도 수요가 있으면 출력할 수 있다. `NO_IMMEDIATE_JOB_INCREASE`와 0건을 그대로 반환한다. 선행 기술이 미보유/미확정이면 각각 `missing_prerequisite_tech_ids`/`unknown_prerequisite_tech_ids`와 사유를 표시한다. 이들은 What-if에 자동 추가하지 않는다.

기본 `c-learning-prerequisites/v1`은 C가 적용하는 학습 순서 정책이다. Java→Spring Boot, Spring Boot→Spring Data JPA·Actuator, JavaScript→Node.js·React·Vue.js, React→Next.js, Python→FastAPI를 지정한다. 실제 언어 생태계 전체 의존 그래프나 사용자 숙련도를 주장하는 자료가 아니다. 목록 밖 기술은 이 정책 버전이 선행 조건을 부과하지 않는다는 뜻이다. 각 rule의 Fact ID와 전체 규칙을 결과에 저장하므로 정책 변경을 재현할 수 있다. 호출자가 다른 명시적 `PrerequisiteSnapshot`을 주면 그 정책을 그대로 저장·사용한다.

Trend는 출처별 관측으로 별도 제공하며 이 순위에 가중치로 합산하지 않는다.

## What-if와 목록

`simulate_what_if(cohort, selection, tech_id)`는 현재 held set과 `{tech_id}` 하나만 추가한 set을 비교한다. 이미 보유한 기술과 분석 범위 미확정 기술을 명시적으로 거절한다. 동일 cohort에서 각 `required_clauses`는 바깥 AND, 안쪽 OR로 평가한다. 예를 들어 `((java, python), (docker,))`는 `(Java 또는 Python) 및 Docker`다. 우대 기술은 필수 매칭에 쓰지 않는다. 비어 있거나 미확정인 필수 조건은 C1에서 검토로 보내며, 매칭 함수도 빈 조건을 false로 처리한다.

각 결과는 `current_count`, `projected_count`, `increased_count`와 각각의 `current_job_ids`, `projected_job_ids`, `newly_matched_job_ids`를 반환한다. ID는 중복 없이 정렬한다.

`increased_count = len(newly_matched_job_ids) = projected_count - current_count`

`list_related_jobs(snapshot, user_id=..., view=..., tech_id=None, offset=0, limit=20)`는 저장된 snapshot의 ID를 조회한다. 목록 순서는 job ID 오름차순이며 `limit` 범위는 1~100이다.

| view | tech_id | total_count와 items 의미 |
|---|---|---|
| CURRENT | 사용하지 않음 | 현재 held set으로 부합한 공고 |
| WHAT_IF | 그 snapshot의 추천 후보 | 해당 기술 하나를 추가해서 **신규로 부합한 공고만** |

따라서 예시 `current=12`, `projected=27`이면 WHAT_IF `total_count=15`다. 27개 전체 예상 공고는 `projected_job_ids`에 별도로 남는다. 페이지 바깥 offset은 빈 items와 동일 total_count를 반환한다. 공고 원본 URL, 원문 기술 Evidence, 회사·제목·필수 조건은 snapshot에 남아 숫자와 출처를 같은 결과에서 조회할 수 있다. 다른 사용자의 snapshot은 `PermissionError`로 거절한다.

## 상태·품질·설명 Fact

공고가 없거나 최소 표본 기준보다 작으면 `INSUFFICIENT_DATA`와 실제 분모를 반환하고 추천을 내지 않는다. 미보유 후보가 없고 미확정 기술이 있으면 `INSUFFICIENT_EVIDENCE`, 모두 평가됐고 후보가 없으면 `NO_CANDIDATES`다. 후보가 있고 품질/분석 누락이 있으면 `PARTIAL`, 그렇지 않으면 `READY`다. 의도한 기간·직무 필터 제외는 집계 제외 수에 남으며, 미확정 조건의 검토 수는 `data_gaps`에도 기록된다.

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
