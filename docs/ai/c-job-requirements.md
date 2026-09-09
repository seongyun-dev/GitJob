# 공고 요구절 보존 계약

상태: S15P21E102-184 로컬 구현 및 합성 회귀 검증. 기준일: 2026-09-09.

`AI/job/requirements.py`는 A의 `JobPostingInput`과 동일 공고에 대한 현재
`JobClassificationRecord`에서 공고별 필수·우대 요구절을 만든다. 기존 classifier와
Registry를 다시 실행하지 않는 순수 계산이며 네트워크·파일·DB를 변경하지 않는다.
기존 `cohort._required_clauses`와 엄격 코호트 계산 API도 변경하지 않는다.

## 호출과 결과

```python
from job.requirements import extract_job_requirements

requirements = extract_job_requirements(record, classification)
payload = requirements.model_dump(mode="json")
```

두 입력의 `source_record_id`, `content_hash`, mention 개수·순서·원문 기술명이 다르면
계산을 거부한다. 출력은 `job-requirements/v1`이며 모든 모델은
`extra="forbid", frozen=True`와 tuple 기반이다.

| 모델 | 주요 필드 | 의미 |
|---|---|---|
| `JobRequirements` | `required`, `preferred`, `unresolved` | 같은 원문에서 분리한 필수·우대 확정절과 미해석 구간 |
| `RequirementClause` | `operator=ANY_OF`, `tech_ids`, `evidence_refs` | 하나의 OR 요구절. 여러 clause는 AND 관계 |
| `RequirementEvidence` | `source_surface`, `char_start`, `char_end`, `text`, `mention_indices` | 원문 surface의 정확한 범위와 이 범위를 지지한 classifier mention |
| `UnresolvedRequirement` | `requirement_kind`, `reason`, `known_tech_ids`, `raw_operands`, `evidence` | 필수/우대 구분을 유지한 미지원 또는 미등록 표현 |

`required_count`와 `preferred_count`는 각각 확정 clause 개수다.
`unresolved_for(RequirementKind.REQUIRED)`처럼 필수/우대 미해석 항목을 분리할 수 있다.
빈 필수 조건은 모든 조건을 충족했다는 뜻이 아니며, 추출기는 비율이나 합격 확률을
계산하지 않는다.

## 제한 문법과 근거 보존

- 서로 다른 독립 문장·행과 명시적 AND는 각각의 clause로 보존한다.
- `Java 또는 Python`은 `ANY_OF(java, python)` 한 clause다. 우대 OR도 같은 방식이다.
- 동일 논리 clause가 반복되면 분모는 한 번만 세고, 서로 다른 원문 범위는
  `evidence_refs`에 모두 남긴다. 동일 source mention 재전달은 같은 범위의
  `mention_indices`로 합친다.
- 원문 근거는 title/body surface와 Python 문자열 기준 `[char_start, char_end)`를 쓴다.
  찾지 못한 근거에는 가짜 offset을 넣지 않고 두 값을 `null`로 두며
  `EVIDENCE_NOT_LOCATED`로 보존한다.
- 미등록 피연산자가 OR에 있으면 알려진 기술만으로 clause를 확정하지 않는다.
  알려진 ID는 `known_tech_ids`, 미등록 원문 피연산자는 `raw_operands`, 전체 문장은
  evidence에 남는다. 같은 공고의 다른 독립 clause는 계속 반환한다.
- 부정은 `NEGATION_UNSUPPORTED`, `2가지 이상` 같은 최소 수량은
  `CARDINALITY_UNSUPPORTED`, slash·AND/OR 혼합·`등`·여러 줄 one-of는
  `LOGIC_UNSUPPORTED`다. 이를 임의의 전체 AND로 완화하지 않는다.
- `기술스택`, `사용기술`, 복리후생·근무조건·채용절차와 회사/기업 소개 구간은
  필수·우대 요구절 및 미해석 분모에서 제외한다.

collector가 같은 기술을 한 번만 emit해도, 이미 정상 위치·분류가 확인된 기술 표면형은
명시적 필수/우대 섹션에서만 다시 찾아 반복 원문 범위를 보존한다. 이 재탐색은 새 기술을
Registry에 매핑하지 않는다. 알려진 기술과 OR로 연결된 미등록 원문은 전체 식을
미해석으로 남기지만, 알려진 기술이 전혀 없는 별도 행을 임의 기술 후보로 발굴하지 않는다.

## 검증 범위와 한계

`tests/test_job_requirements.py`는 실제 `JobPostingInput → classify_job_batch →
extract_job_requirements` 경로와 저장소의 A→C fixture를 사용한다. 필수/우대 AND·OR,
부분 미해석 보존, 반복 문장 dedup/evidence, 부정·수량·혼합식, 회사소개 제외,
미위치 근거와 frozen JSON round-trip을 검증한다.

이는 저장된 합성 입력과 계약 fixture 검증이다. 실제 채용 사이트 최신 배치의 표본 정확도,
운영 intake, DB 저장, B 조회 API 및 FE 화면 연결을 검증한 결과가 아니다. 문장 경계는
개행과 제한된 문장 부호만 지원하며 괄호 중첩, `N개 중 M개`, 부정 요구, 여러 줄 선택 목록은
원문 미해석으로 유지한다.
