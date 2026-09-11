# 공고 요구절 보존 계약

상태: S15P21E102-184 요구절 추출과 S15P21E102-217 필수 기술 수준 산정 로컬 구현.
기준일: 2026-09-11.

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
계산을 거부한다. 새 출력은 `job-requirements/v2`이며 모든 모델은
`extra="forbid", frozen=True`와 tuple 기반이다.

| 모델 | 주요 필드 | 의미 |
|---|---|---|
| `JobRequirements` | `level_policy_version`, `required`, `preferred`, `unresolved` | 같은 원문에서 분리한 필수·우대 확정절과 미해석 구간 |
| `RequirementClause` | `operator=ANY_OF`, `tech_ids`, `evidence_refs`, `required_level`, `level_evidence_refs` | 하나의 OR 요구절. 여러 clause는 AND 관계. 수준 필드는 필수 clause에만 존재 |
| `RequirementEvidence` | `source_surface`, `char_start`, `char_end`, `text`, `mention_indices` | 원문 surface의 정확한 범위와 이 범위를 지지한 classifier mention |
| `RequirementLevelEvidence` | `source`, `level`, `text`, 원문 위치, `mention_indices` | 수준 신호의 출처와 원문/구조화 필드 lineage |
| `UnresolvedRequirement` | `requirement_kind`, `reason`, `known_tech_ids`, `raw_operands`, `evidence` | 필수/우대 구분을 유지한 미지원 또는 미등록 표현 |

`required_count`와 `preferred_count`는 각각 확정 clause 개수다.
`unresolved_for(RequirementKind.REQUIRED)`처럼 필수/우대 미해석 항목을 분리할 수 있다.
빈 필수 조건은 모든 조건을 충족했다는 뜻이 아니며, 추출기는 비율이나 합격 확률을
계산하지 않는다.

기존 저장 `job-requirements/v1` payload는 수준 필드 없이 같은 `JobRequirements`로
읽을 수 있다. v2는 `level_policy_version=job-required-level-policy/v1`과 모든 필수
clause의 `required_level`, 비어 있지 않은 `level_evidence_refs`를 강제한다. 우대와
unresolved에는 요구 수준을 만들지 않으며 `UNKNOWN`은 수준 enum이 아니다.

## 필수 기술 요구 수준 정책

수준은 기술 ID별 하드코딩이 아니라 다음 원문 신호를 순서대로 적용한다. 더 직접적인
출처에서 신호가 확인되면 덜 직접적인 출처로 수준을 올리지 않는다. 공고 전역의
`career_level`과 직급은 기술별 경력으로 자동 전파하지 않는다.

1. 기술이 있는 동일 clause의 표현과 기술에 직접 결속된 최소 연차·직급
2. 위 신호가 없을 때 보수적인 L1

| 수준 | 판정 신호 |
|---|---|
| L1 | 기술명·단순 목록, 지식·기초 이해, 사용/활용/개발 가능, 교육·자격 |
| L2 | 해당 기술의 경험·실무·개발·운영·배포·구축·설계, 직접 결속된 최소 1~4년 |
| L3 | 해당 기술에 직접 결속된 최소 5년·고직급 또는 아키텍처·리딩·최적화·운영 책임 |

직접 결속된 연차 범위는 최소 요구치를 쓴다. 예를 들어 `Java 경력 3~7년`은 L2다.
직급 범위는 논리 미확정으로 보존한다. 같은 clause에 `기초 이해`가 명시되면 공고 전체
경력이 5년 이상이어도 L1이며, `경험`이 명시되면 L2다. 일반 `설계`는 L2이고,
아키텍처·리딩·최적화·운영 책임처럼 기술에 직접 붙은 고책임 표현만 L3다.
`지원자격\n경력 5년 이상\nJava 필수`와 `자격요건: 경력 5년 이상\nJava 필수`처럼
기술 없는 독립 section 경력은 표기 방식과 무관하게 Java에 전파하지 않는다.

담당업무의 개발·설계·운영 문구, 회사소개, 제목, 구조화 스킬만으로는 REQUIRED
clause나 L3를 만들지 않는다. 복리후생·일반 기술 소개도 요구절 산정에서 제외한다.

`level_evidence_refs.source`는 `DIRECT_CLAUSE`, `CONSERVATIVE_DEFAULT` 중 하나다.
직접 clause 출처는 원문 surface와 `[char_start, char_end)`를 필수로 가지며,
모든 출처는 해당 clause의
classifier `mention_indices`를 보존한다. 직렬화 전 evidence는 출처·위치·본문·mention
순으로 정규화된다.

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
  `CARDINALITY_UNSUPPORTED`, slash·AND/OR 혼합·`등`·`외`·직급 범위·여러 줄 one-of는
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
미위치 근거와 frozen JSON round-trip을 검증한다. 수준 회귀는 L1~L3 직접 표현,
1년/5년 경계, 직접 연차 범위의 최소값, 직급 범위 보류, 독립 section 경력 비전파,
담당업무/회사소개 게이트, v1 read 호환, v2 policy/evidence 검증과 결정적 JSON
직렬화를 포함한다. 저장소의 기존 A→C fixture
`jobkorea:fixture-1001`은 `C# 실무 경험`, `경력 3년 이상`에서 L2로 검증한다.

정책 보정에는 WorkNet 원본 42절과 JobKorea·Career·GameJob·Work24 저장 결과 8절,
총 50개의 실제 요구절을 사람이 판독한 표본을 사용했다. 제안 분포는 L1 14, L2 22,
L3 2, 미확정 12였다. 저장소 테스트는 이 표본에서 확인된 가능/경험/설계/최적화,
공고 전역 경력 비전파, 담당업무와 열린 목록의 대표 경계를 고정하지만, 50절 정답표
전체를 자동 replay하는 fixture는 아니다. 별도로 수행한 WorkNet 원본 50레코드 smoke도
파싱 예외 확인이며 수동 50절과 분모·사이트·판정 단위가 달라 정확도 검증으로 보지 않는다.

다른 세 사이트의 이번 snapshot은 본문·직급 coverage가 제한적이므로 전체 사이트의
수준 정확도나 운영 intake, DB 저장, B 조회 API 및 FE 화면 연결을 검증한 결과는 아니다. 문장 경계는
개행과 제한된 문장 부호만 지원하며 괄호 중첩, `N개 중 M개`, 부정 요구, 여러 줄 선택 목록은
원문 미해석으로 유지한다.
