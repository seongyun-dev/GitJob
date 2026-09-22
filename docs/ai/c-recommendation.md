# C Evidence 소비와 추천용 확인 기술

상태: C3/C4 로컬 구현·합성 계약 회귀 검증. 실제 B 출력 연결은 별도 인수 대상. 기준일: 2026-09-08. Jira: S15P21E102-33.

## 의미와 책임

C의 **추천용 확인 기술**은 공고의 기술명 조건과 비교할 집합이다. 개인 숙련도, 실력 점수, 채용 가능성이나 모든 기술의 본인 구현 여부를 뜻하지 않는다.

B는 직접 의존성·Rule 매칭·원천 제외·유효 참여·저자 귀속·L0–L3를 확정한다. C는 받은 사실과 근거의 범위·수용 상태·일관성을 검증하고, 관측/귀속 프로필과 추천 포함 사유를 보존한다. C에서 AST·blame·Rule 실행·언어별 레벨 계산을 재구현하지 않는다.

현재 보유 정책은 `c-confirmed/eligible-observation/v1`이다.

> 같은 저장소 snapshot의 **검증된 직접 의존성 또는 검증된 구현 근거**와 **검증된 유효 참여**가 있으면 추천 계산에 포함한다.

유효 참여는 같은 저장소의 accepted PARTICIPATION 또는 accepted SELF IMPLEMENTATION으로 확인한다. 기술마다 중복 참여 Fact를 요구하지 않으며 다른 기술의 참여 근거도 원 소속을 유지하여 재사용한다. 접근 권한, 저장소 이름/소유자, fork 생성만으로 참여를 추정하지 않는다. 서로 다른 저장소의 의존성·구현·참여를 조합하지 않는다.

## 입력: EvidenceAnalysis와 구조화된 Proof

호출은 `consume_evidence(analysis, user_id=..., analysis_id=..., tech_ids=...)`이다. `EvidenceAnalysis`는 `evidence-consumption-input/v1`/`v2`와 개인 수준 입력 `evidence-consumption-input/v3`를 받는다. 함수 시그니처는 유지한다.

공통 envelope:

- user_id, analysis_id, registry_version, level_policy_version, evidence_rule_version, status
- repositories와 선택 data_gaps
- 사용자·요청 분석 ID 또는 repository 사용자 불일치는 PermissionError

각 repository:

- repository_id, repository_analysis_id, commit_sha(40자리 SHA), status
- coverage_complete, evaluated_tech_ids, technologies, data_gaps
- COMPLETE만 coverage_complete=true 가능
- evaluated_tech_ids는 해당 버전의 Rule을 실제 완료 평가한 범위다. 누락은 미평가이며 임의 기술의 부재 증명이 아니다.
- 동일 repository snapshot 중복을 거절한다. 동일 repository/tech assessment의 정확한 중복은 멱등 처리하지만 서로 다른 assessment는 Fact ID와 무관하게 거절한다. 여러 근거는 한 assessment의 proofs에 넣는다.

각 TechnologyEvidence:

- tech_id, fact_ids, evidence_level(L0–L3 또는 null)
- v3에서는 명시적 personal_level(L0–L3 또는 null). 이는 repository evidence_level과
  다른 사용자 수준 축이며 C는 evidence_level을 personal_level의 fallback으로 쓰지 않는다.
- direct_dependency, implementation_present, user_participation(boolean 또는 null)
- implemented_by(SELF/OTHER/NONE/UNKNOWN), attribution_status(COMPLETE/PARTIAL/UNKNOWN)
- proofs와 선택 source_refs. 이전 source_refs 문자열만으로 긍정 근거를 만들지 않는다.

EvidenceProof의 실제 필드:

| 구분 | 필드 |
|---|---|
| Fact·Rule | evidence_id, fact_id, tech_id, rule_id, rule_version |
| 범위 | user_id, analysis_id, repository_id, repository_analysis_id, source_commit_sha |
| 역할 | kind: DIRECT_DEPENDENCY / IMPLEMENTATION / PARTICIPATION |
| 위치 | source_kind, path, line_start, line_end, source_ref |
| 수용·원천 | acceptance: ACCEPTED / EXCLUDED / UNCONFIRMED, exclusion_reason, origin, inherited |
| 귀속 | attribution: SELF / OTHER / NONE / UNKNOWN, attribution_commit_sha |
| 직접성 | direct_dependency: true / false / null |

source_kind는 MANIFEST/SBOM/SOURCE/CONFIG/TEST/README/LOCKFILE이다. origin은 PROJECT/GENERATED/VENDOR/COPIED/FORK_BASE/UNKNOWN이다. 긍정 근거는 B가 ACCEPTED로 제공한 PROJECT 원천이면서 inherited=false, exclusion_reason=null이어야 한다. 파일명만 보고 C가 원천 제외를 재판정하지 않는다.

직접 의존성 근거는 MANIFEST 또는 SBOM이며 직접성이 true여야 한다. README·lockfile-only·전이 의존성만으로 직접 의존성을 확인하지 않는다. 구현/참여는 SOURCE/CONFIG/TEST에 대한 accepted Rule 결과만 받는다. 상대 경로와 순서가 올바른 라인 범위를 검증하며 SOURCE/CONFIG/TEST는 라인이 필수다. MANIFEST/SBOM은 라인 대신 식별 가능한 path/source_ref를 사용할 수 있다.

proof의 사용자·전체 분석·저장소 분석·source commit·기술·Rule version·fact_id 소속이 enclosing assessment와 맞아야 한다. 불일치는 PROOF_SCOPE_MISMATCH로 보존하고 긍정 근거에서 제외한다. source_ref는 권한 있는 내부 근거 ID 또는 permalink를 지원하며 원문, 이메일, 토큰이 필요하지 않다. **source snapshot commit과 attribution commit은 역할이 다르므로 같을 필요가 없다.**

구 v1 입력도 parse하지만 구조화 근거 없는 긍정은 UNKNOWN + STRUCTURED_PROOF_REQUIRED다. 임의 문자열 Fact ID/URL에서 proof를 합성하거나 이전 personalLevel 숫자를 v2 레벨로 변환하지 않는다.

## 출력: 레벨·관측·귀속·추천 포함을 분리

`HeldTechnologySelection`은 schema `held-technology-selection/v2`를 반환한다. 각 기술의 profiles에는 repository별 `RepositoryTechnologyProfile`을 저장한다.

| 축 | 저장 내용 |
|---|---|
| 원본 B 결과 | reported 전체 assessment, reported evidence_level와 모든 boolean/귀속 상태 |
| B 레벨 검증 | verified_level, validation_status, validation_reasons |
| 사실 일관성 | observation_validation_status, observation_validation_reasons |
| 관측 | direct_dependency_status, implementation_status |
| 사용자 귀속 | participation_status, self_implementation_status |
| 근거 | proof_results(수용/거절 이유 포함), eligibility_proofs, supporting_proofs |
| 품질 | data_gaps, repository 상태와 사용자·분석·commit·정책/Rule lineage |

관측 축은 CONFIRMED / NOT_OBSERVED / UNKNOWN이다. NOT_OBSERVED는 해당 기술에 대한 완료 coverage와 명시적 false가 있는 경우에만 사용한다. 파일 수·Fact 수·커밋 수를 더해서 수준이나 숙련도를 올리지 않는다. SELF 구현 하나가 v2 L3에 해당하더라도 구현 난이도·테스트 깊이·운영 능력은 별도 근거 없이는 설명하지 않는다.

v2 레벨 검증은 B가 전달한 레벨의 조건만 확인한다. 조건이 맞으면 동일 레벨을 verified_level로 보존하고, 아니면 null과 이유를 보존한다. C가 상위/하위 대체 레벨을 산출하지 않는다.

- 직접 의존성 false가 우선인 v2 L0는 구현 관측과 양립할 수 있다. 예: Java source/SELF 근거가 있지만 SBOM 직접 의존성은 없음 → reported/verified L0, implementation CONFIRMED, 추천 포함 가능.
- L2/L3인데 직접 의존성이 false/null이면 레벨은 INCONSISTENT/UNCONFIRMED다. 독립적으로 유효한 accepted 구현이 있으면 그 사실을 지우지 않고 추천에 사용할 수 있다.
- accepted SELF 구현 한 건은 다른 근거의 귀속 PARTIAL/UNKNOWN 때문에 지우지 않는다.
- 알려지지 않은 레벨 정책의 숫자/문자열은 v2로 해석하지 않는다. 독립적으로 검증된 구조화 사실은 관측으로 보존하되 레벨은 미확정이다.
- implementation_present=false와 accepted 구현, direct_dependency=false와 accepted 직접 의존성, user_participation=false와 유효 SELF 참여 등 **관측 flags와 근거 자체의 모순**은 보수적으로 처리하여 해당 assessment로 추천 포함하지 않는다.

언어·인프라는 SBOM 직접 의존성이 본질적으로 없을 수 있다. 따라서 dependency gate만으로 미사용을 단정하지 않는다. accepted 구현 근거를 추천에 사용할 수 있지만 B의 언어 Rule이나 새 레벨을 C가 임의로 정의하지 않는다.

## 현행 추천 의미 (v8)

`c-recommendation/condition-impact/v8`부터 다음 학습 기술은 공고의 모든 필수 조건을
완전히 채우는 건수가 아니라, **후보 기술을 확인된 필수·우대 조건으로 언급한 서로
다른 공고 수**로 추천한다. `matching_jobs`의 조건부 공고와 일부 미해석 공고도
확인된 절은 센다. L2/L3 요구 공고도 기술 관련 수요로 세지만 L1 학습으로 해당
수준을 충족했다고 판정하지 않는다. OR의 다른 대안을 이미 보유한 공고도 해당 기술의
수요에는 포함한다. 미해석·일반 언급은 필수·우대로 승격하지 않는다.
`impact`에는 필수·우대·합집합 공고 ID와 건수가 저장되며,
화면과 상세 목록에는 같은 활성 공고 필터를 적용한다. 아래 v7 What-if 설명은 저장된
구 결과의 읽기 호환 계약이며 새 추천의 순위나 화면에 사용하지 않는다.

## 병합·Gap·설명

유효한 긍정은 PARTIAL 분석이나 실패한 peer repository가 있어도 유지한다. FAILED 전체 분석, FAILED/UNSUPPORTED/PERMISSION_DENIED repository의 proof는 수용하지 않는다. accepted observation이 없는 incomplete/unsupported 결과를 개인 미보유로 바꾸지 않는다.

eligible_repository_ids에는 accepted 참여가 확인된 repository만 들어간다. repository_coverage에는 repository/analysis/commit/status/coverage/evaluated tech/data_gaps를 저장한다. 모든 선택 저장소의 유효 참여와 해당 기술의 완료 coverage가 확인되어야 scoped NOT_HELD를 반환한다. 접근권한뿐이거나 참여 미확정인 repository가 있으면 음성 추론도 UNKNOWN이다. 이는 사용자 전체 지식의 부재가 아니다.

한 기술의 여러 repository profile은 그대로 보존하며 확인 기술 집합만 합집합한다. supporting_proofs는 실제 포함에 사용한 검증 근거다. 설명은 표현한 claim을 뒷받침하는 proof만 인용한다. 예를 들어 SELF 설명에는 해당 기술 SELF IMPLEMENTATION만 사용하고, FAILED peer나 다른 기술 참여 proof를 본인 기술 구현으로 인용하지 않는다.

`build_gap(selection, demanded_tech_ids=...)`은 `technology-gap/v2`로 held/missing/unknown을 나눈다. UNKNOWN은 missing 후보가 아니다. CURRENT·What-if·선행기술 확인 모두 같은 확인 기술 집합을 사용한다. What-if는 기술 하나만 추가하며 preferred를 필수 gate로 사용하지 않는다.

### 추천 후보 자격 (S15P21E102-354, v7부터)

Gap 의 의미는 그대로 두고 **추천 후보 자격만** 개인 Level 로 판정한다. 이 추천은 "이미
가진 기술의 Level 을 올리자"가 아니라 "아직 직접 써 본 적 없는 새 기술 하나"이기
때문이다.

- `personal_level` 이 L1·L2·L3 이면 후보에서 제외한다. 공고가 더 높은 Level 을 요구해도
  제외한다 -- 보유 기술 Level-up 은 이 계산의 답이 아니다.
- `personal_level` 이 L0 이거나, 개인 판정이 없거나, Evidence 가 UNKNOWN 이면 후보다.
  저장소에서 관측됐지만 개인 귀속이 없는 기술도 여기에 들어간다.

Evidence 층은 바뀌지 않는다. UNKNOWN 은 계속 UNKNOWN 이고 `missing_tech_ids` 로
옮기지 않는다 -- 후보 자격에서만 UNKNOWN 을 허용한다. 후보의 `evidence_status` 가
`PERSONAL_LEVEL_UNKNOWN` 인 경우가 그것이며, 미보유로 단정한 `NOT_HELD` 와 다르다.

후보가 존재하면 coverage 가 불완전해도 후보를 숨기지 않는다. 그때 결과는
`INSUFFICIENT_EVIDENCE` 가 아니라 `PARTIAL` 이고, 근거가 부족하다는 사실은 data gap 으로
함께 전달한다. 후보가 하나도 없을 때에만 기존 `INSUFFICIENT_EVIDENCE`/`NO_CANDIDATES`
판정을 유지한다.

Top3 는 `increased_count` 내림차순으로 고른다. 증가 건수 정의와 What-if 가정 Level(L1)
은 바꾸지 않고 그대로 재사용한다.

`consume_personal_levels()`는 v3에서 accepted supporting proof가 있는 repository
profile의 personal_level만 취한다. 따라서 PARTIAL analysis라도 유효 positive proof는
보유 수준으로 남고, proof/귀속/coverage가 미확정인 범위는 level을 만들어 내지 않는다.
이는 개인 전체 능력의 부재가 아니라 품질 unknown이다.

v4 입력은 B가 사용자 전체 저장소를 합산해 다음 aggregate를 전달한다. 같은 입력의
repository proof와 C의 held/coverage 검증을 통과한 기술만 소비한다.

```json
{
  "schema_version": "evidence-consumption-input/v4",
  "personal_assessments": [
    {
      "tech_id": "java",
      "personal_level": "L2",
      "assessment_ceiling": "L2",
      "attribution_status": "COMPLETE",
      "missing_scope": ["L3_RULE_NOT_SUPPORTED"]
    }
  ]
}
```

`personal_level`은 L0~L3 값이고 `UNKNOWN`은 수준 값이 아니다. `assessment_ceiling`은
사용자 최고 수준이 아니라 B가 현재 Rule Pack과 수집·귀속 범위로 부재까지 판정 가능한
최고 수준이다. aggregate personal level이 repository 증거와 연결되지 않으면 입력을
거절한다. 누락/부분 귀속은 기술 미보유나 L0으로 축소하지 않는다.

## 버전과 저장 조회 호환

- 현재 confirmed 정책: c-confirmed/eligible-observation/v1
- 현재 추천 결과 schema: recommendation-snapshot/v3; 실제 비교 후보 전체를 쓰는 계산은
  c-recommendation/lexicographic/v7이다. 후보 자격이 바뀐 새 계산이므로 새 버전이며,
  같은 입력에 다른 후보를 내는 계산을 v6이라는 한 이름으로 부르지 않는다. 이전 후보
  자격을 쓰는 v6과 v3 personal 입력 계산 v4, v4 aggregate ceiling 입력 계산 v5는
  저장된 결과 조회용으로 유지한다. 저장된 snapshot은 자기 버전의 자격 규칙으로
  재검증하므로 v6 이하 결과는 그대로 읽힌다.
- 현재 설명: c-fact-explanation/v2
- 구 결과의 c-held/project-participation/v1 정책은 신규 계산에 사용하지 않는다.
- LegacyHeldTechnologySelection / LegacyGapSnapshot은 기존 출력 모양 그대로 분리해 읽는다. RecommendationSnapshot은 schema discriminator로 구/신 결과를 구분한다.
- 기존 snapshot에 새 default 필드를 끼워 넣거나 조회 시 재계산하지 않으므로 구 JSON payload/hash와 CURRENT/WHAT_IF 목록이 유지된다.
- 신규 profile 저장 조회에서도 consumed flags, proof 검증 결과, 지원 근거와 범위를 재검증한다.
- matching/recommendation v6는 v3 personal_level 또는 v4 aggregate와 ceiling을
  실제 비교 후보 전체에 적용하지만, v1~v3 envelope과 기존 recommendation v1~v5 snapshot은 historical 결과를 재계산하거나 새 필드로
  보정하지 않는다.

## Calibration과 검증 범위

`tests/test_evidence_calibration.py`의 18행은 합성 B Fact로 정책 전후를 비교한다. 역사 열은 검토한 구 정책 결과를 기록한 것이며 구 정책을 새 계산 옵션으로 노출하지 않는다.

| 사례 | 구 정책 | 새 확인 정책 |
|---|---|---|
| 유효 참여 + L1 직접 의존성 | NOT_HELD | HELD |
| L2 타인 구현 + 참여 | HELD | HELD, SELF 아님 |
| L3 본인 구현 | HELD | HELD |
| accepted SELF + 다른 귀속 PARTIAL | UNKNOWN | HELD |
| L1 의존성 + 구현 parse 실패 | UNKNOWN | HELD, 구현 UNKNOWN |
| proof 없는 구 L3 | HELD | UNKNOWN |
| SBOM 없는 언어 구현 + v2 L0 | UNKNOWN | HELD, 레벨 L0 유지 |
| v2 레벨 불일치 + 독립적 유효 source | HELD | HELD + 레벨 불일치 |
| flags와 accepted 관측 자체 모순 | HELD | UNKNOWN |
| 접근권한뿐인 L1 | NOT_HELD | UNKNOWN |
| inherited dependency | NOT_HELD | UNKNOWN |
| FAILED repository | UNKNOWN | UNKNOWN |
| UNSUPPORTED repository | UNKNOWN | UNKNOWN |
| PARTIAL에서 미관측 | UNKNOWN | UNKNOWN |
| 유효 참여·완료 평가에서 미관측 | NOT_HELD | scoped NOT_HELD |
| 모든 proof 미확정 | HELD | UNKNOWN |
| 구현 proof 범위 오류 + 유효 직접 의존성/참여 | HELD | HELD, SELF 근거로 인용 불가 |
| SBOM 없는 인프라 타인 구현 + 참여 | UNKNOWN | HELD, SELF 아님 |

회귀는 사용자·분석 격리, Proof scope/origin/accepted, 같은 repo 참여 재사용, repo 간 짜깁기 금지, 모순·중복·순서 불변, 레벨/관측 분리, 실패 근거 인용 제외, JSON 왕복, 구 snapshot hash/목록, API/PostgreSQL 저장 조회를 다룬다. 합성 fixture가 실제 저장소 코드나 B의 운영 귀속 정확도를 증명하지는 않는다.

출처: [Evidence 정책 v2](https://app.notion.com/p/78215fc50ec7823d81e481e5ce71e50e), [추천·What-if](https://app.notion.com/p/15615fc50ec78365b73401c62b4fab33), [관련 공고](https://app.notion.com/p/06f15fc50ec783e198ba01dfd32dce7d). [과거 정책 충돌 기록](technology-level-llm-handoff.md)의 9/2 운영·테스트 L3 정의는 현재 v2에 적용하지 않는다.
