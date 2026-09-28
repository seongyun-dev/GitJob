# 추천 근거 설명

상태: C5 로컬 구현·회귀 검증 완료, 외부 LLM 미연결. 기준일: 2026-09-08. Jira: S15P21E102-36.

`recommendation.explanation.explain_recommendations(snapshot)`은 계산이 완료된
`RecommendationSnapshot`에서 수요 분자/분모, What-if 전후/증가 공고,
Evidence Fact, 선행 학습 조건 및 분석 부족 사실을 추출해 한국어로 설명한다.
설명과 실제 공고 목록은 같은 불변 Snapshot을 참조한다. 원본 채용 본문이나
외부 생성 텍스트를 지시로 실행하거나 수치의 근거로 사용하지 않는다.

각 사실은 `fact_id`, `kind`, `tech_id`, `text`, 구조화된 `values`, `source_refs`를
포함한다. 현재 설명 버전은 `c-fact-explanation/v2`다. 직접 의존성 또는 구현과
같은 저장소의 유효 참여가 확인되면 추천 계산에 포함한다. 저장소 관측·개인 귀속·
B 레벨 검증은 분리해서 설명하고 `UNKNOWN`을 미보유로 바꾸지 않는다.

각 Evidence 설명의 `values.profiles`에는 reported/verified level, 관측·참여·
SELF 상태, 레벨과 사실 각각의 검증 상태·이유가 들어간다. `used_evidence_ids`,
`fact_ids`, `supporting_scope`는 그 문장을 뒷받침하는 검증 Proof만 가리킨다.
SELF 문장은 해당 기술의 accepted SELF IMPLEMENTATION만 인용한다. FAILED peer,
거절된 source, 다른 기술의 프로젝트 참여를 그 기술의 본인 구현으로 인용하지 않는다.

L1은 직접 의존성 확인에 따른 추천 포함으로 표현하고 구현·숙련도를 주장하지 않는다.
SBOM 직접 의존성이 없는 언어/인프라의 유효 구현은 B의 L0와 양립할 수 있다.
이 경우 구현 사실은 보존하지만 L3나 능력 점수로 승격하지 않는다. 구현의 깊이,
테스트·운영 능력은 파일 수나 레벨 숫자로 추정하지 않는다.

기본 동작은 `mode=RULE`이며 GPU나 LLM 연결이 없어도 모든 설명을 제공한다.
선택적인 `narrative_plan`은 외부 모델이 생성할 수 있는 **Fact 표시 순서** 계약이다.
현재 Snapshot ID와 정확히 동일한 Fact ID 집합만 허용하며 자유 텍스트·숫자·새
사실은 받지 않는다. 잘못된 ID, 누락, 중복, 다른 Snapshot, 추가 필드는 모두
규칙 기반 원래 설명으로 fallback한다. 따라서 단순히 숫자가 같은지 검사하고
근거 없는 자연어를 통과시키지 않는다. 이번 구현은 외부 LLM을 호출하지 않는다.

반환 `snapshot_id`는 추천 계산 자체의 ID이고 DB HTTP 응답의 `snapshot_id`는
설명까지 포함한 저장 Snapshot ID다. C API가 저장 ID를 외부 조회 기준으로 전달한다.

검증: 모든 표시 수치와 원천 필드 일치, 증가 ID의 source URL 연결, 타인 구현
과대 해석 방지, 실패 근거의 긍정 인용 제외, L1과 proof 없는 구 입력 설명,
데이터 부족 상태, 잘못된 외부 plan fallback, 결정적 JSON 왕복. 기존 저장 Snapshot은
조회 시 설명을 재생성하지 않으며 구 정책과 hash를 유지한다. 원본 B의 실제 귀속
정확도나 실사용자 Evidence 깊이는 합성 fixture 검증과 별도의 인수 대상이다.

출처: [추천·What-if API](https://app.notion.com/p/15615fc50ec78365b73401c62b4fab33),
[Evidence 정책 v2](https://app.notion.com/p/78215fc50ec7823d81e481e5ce71e50e).
