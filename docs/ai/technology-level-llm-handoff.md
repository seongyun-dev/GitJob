# 기술 Evidence Level 평가·LLM 연동 설계안

> 상태: Backend 담당자 전달·협의안
>
> 기준일: 2026-09-02
>
> 관련 작업: `S15P21E102-77` / `infra/S15P21E102-77-ai-infra`

## 1. 문서 목적

Backend 담당자로부터 전달받은 기술 레벨 평가 payload를 분석하고, Registry·
Evidence Rule 기반 판정 결과를 로컬 LLM과 어떻게 연동할지 정의한다.

이 문서에서 말하는 기술 레벨은 개발자 개인의 실력이나 채용 가능성이 아니라,
저장소에서 특정 기술이 관측·사용된 Evidence의 수준을 의미한다.

## 2. 결론 요약

전달받은 payload는 원본 저장소를 LLM에 다시 분석시키는 입력이 아니라,
Registry와 Evidence Rule이 이미 처리한 **Fact Pack**에 가깝다.

```text
Registry / Evidence Rule DB
          ↓
matchedEvidence 생성
          ↓
기술 레벨 계산 또는 LLM 제안
          ↓
근거 기반 설명 생성
          ↓
Backend 검증·Snapshot 저장
```

권장 방식은 다음과 같다.

1. Registry와 Evidence Rule은 Backend/Worker가 기준 데이터로 사용한다.
2. `matchedEvidence`는 규칙 실행 결과이므로 LLM이 다시 판정하지 않는다.
3. 레벨의 최종 값은 Backend가 정책에 따라 계산하거나 LLM 제안값을 재검증한다.
4. LLM은 제공된 Evidence만 사용해 설명·요약·다음 확인 항목을 생성한다.
5. 원문, Evidence ID, Registry 버전, Rule 버전, Prompt/Model 버전을 함께 저장한다.

LLM에게 최종 레벨을 완전히 위임하는 것도 가능하지만, 그 경우에도 Backend가
동일 정책으로 결과를 재계산해 불일치 결과를 폐기해야 한다.

## 2.1 LLM 역할 범위 한눈에 보기

LLM은 원본 저장소나 DB를 처음부터 분석하는 주체가 아니다. Backend/Worker가
Registry와 Evidence Rule을 적용해 만든 구조화된 결과부터 LLM 작업이 시작된다.

```text
원본 저장소·SBOM
      ↓  Backend/Worker
Registry 조회·Evidence Rule 실행·저자 귀속
      ↓
matchedEvidence + 버전 + 품질 상태
      ↓  여기부터 LLM
레벨 설명·근거 요약·미확인 항목·다음 확인 항목
      ↓  다시 Backend
schema·Evidence ID·정책 일치 검증 및 저장
```

| 처리 단계 | 담당 | LLM 역할 |
|---|---|---|
| 저장소·SBOM 수집 | Collector/Worker | 담당하지 않음 |
| Registry·alias 조회 | Backend/Worker·DB | 담당하지 않음. 애매한 기술명 후보 제안은 예외적으로 가능 |
| Evidence Rule 실행 | Rule evaluator·DB | 담당하지 않음 |
| `matchedEvidence`·저자 귀속 생성 | Backend/Worker | 담당하지 않음 |
| L0~L3 최종 계산 | Backend 정책 계산기 | 권장하지 않음. 대안으로 제안값만 생성 가능 |
| Evidence 기반 설명·요약 | LLM | 주 담당 |
| Evidence ID·Registry ID·정책 검증 | Backend | 담당하지 않음 |
| 결과 Snapshot·검토 큐 저장 | Backend | 담당하지 않음 |

따라서 이번 연동에서 LLM에 넘기는 최소 시작점은 `matchedEvidence`,
`dependency`, `analysisQuality`, `levelPolicy` 또는 Backend가 계산한 평가 결과다.
LLM은 해당 입력을 벗어나 파일·라인·기술 수준을 새로 만들어서는 안 된다.

### 실무 적용 범위

- **정규화**: Registry에 없는 기술명이나 애매한 표현의 대표 기술 후보 제안
- **레벨 설명**: 확정된 L0~L3와 사용 Evidence를 한국어로 설명
- **보조 판정**: 선택적으로 `proposedLevel`을 반환하되 Backend가 재계산
- **검토 지원**: 부족한 Evidence, 정책 충돌, 추가로 확인할 파일·규칙 제안
- **최종 책임 제외**: Registry 확정, 저자 귀속, L0~L3 확정, DB 저장, 사용자 숙련도·채용 가능성 판단

## 3. 전달받은 payload 분석

### 3.1 필드별 의미

| 필드 | 의미 | 검토 의견 |
|---|---|---|
| `task` | 수행할 평가 작업 | `ASSESS_TECHNOLOGY_LEVEL`보다 `ASSESS_EVIDENCE_LEVEL`이 의미상 명확함 |
| `technology` | Registry 기준 기술 | `registryVersion`을 추가해야 재현 가능 |
| `dependency` | 직접 의존성 확인 결과 | package·version·manifest·commit 근거가 필요함 |
| `matchedEvidence` | Evidence Rule에 매칭된 사실 | LLM 입력으로 적합. Rule·Fact·Source·Attribution을 포함함 |
| `analysisQuality` | 파싱·저자 귀속 품질 | 불완전한 분석 결과를 구분하는 데 필요함 |
| `levelPolicy` | L0~L3 정책 | 현재 프로젝트 문서의 정책과 충돌함 |
| `outputRules` | LLM 또는 평가기의 안전 제약 | `useOnlyProvidedEvidence`와 추론 금지 규칙은 적절함 |

### 3.2 전달 payload 기준의 판정

전달받은 데이터에는 다음 근거가 있다.

- `hasDirectDependency=true`
- `evidence-001`: `KafkaTemplate.send()` 호출, `USER_AUTHORED`
- `evidence-002`: `KafkaListener` annotation, `OTHER_AUTHORED`
- `parseStatus=COMPLETE`
- `attributionStatus=COMPLETE`

전달받은 `levelPolicy`를 그대로 적용하면 결과는 다음과 같다.

```text
직접 의존성 있음
  → L1 이상

구현 Evidence 있음
  → L2 이상

USER_AUTHORED 구현 Evidence 있음
  → L3
```

따라서 **전달 payload의 정책 기준 결과는 L3**다. `evidence-002`는 Repository
Evidence로는 유효하지만 `OTHER_AUTHORED`이므로 개인 기여 근거로는 사용하지
않는다.

### 3.3 기존 프로젝트 문서와의 정책 충돌

현재 [Backend 설계 문서](../be/README.md)의 레벨 정책은 다음과 같다.

| 레벨 | 현재 프로젝트 문서의 의미 |
|---|---|
| L0 | 기술 발견. 직접 의존성·build plugin·container image 등 |
| L1 | 설정·import·annotation |
| L2 | 핵심 API 호출과 본인 기여 |
| L3 | 테스트·retry/backoff·DLQ·metric/tracing·timeout/circuit breaker 등 심화 사용 |

또한 Repository Level과 Personal Level을 분리한다고 정의한다.

이 정책을 적용하면 전달 payload는 다음에 가깝다.

```text
Repository Level: L2
Personal Level:   L2
```

`KafkaTemplate.send()`라는 핵심 API 호출과 사용자 작성 근거는 있지만, 테스트·
retry·DLQ·metric 등의 L3 운영 Evidence는 payload에 없기 때문이다.

따라서 Backend 팀과 아래 중 하나를 먼저 결정해야 한다.

1. 전달받은 새 정책을 공식 정책으로 채택한다.
2. 기존 정책을 유지하고 `repositoryLevel`과 `personalLevel`을 분리한다.
3. 전달받은 L0~L3를 기술 레벨이 아닌 `personalEvidenceLevel`로 이름을 바꾼다.

현재 프로젝트 전체 문서와 일관적인 권장안은 **Repository Level과 Personal Level을
분리하는 2번**이다. [AI 설계 문서](README.md)도 기술 레벨은 AI가 결정하지 않고
L0~L3 Rule과 Evidence로 판정한다고 명시한다.

## 4. JSON 형식 보완 사항

### 4.1 현재 붙여넣기 상태의 JSON 오류

전달된 내용이 화면 표시가 아니라 실제 request body라면 다음은 유효한 JSON이
아니다.

- `ASSESS\_TECHNOLOGY\_LEVEL`처럼 underscore 앞에 `\\`가 들어간 값
- `GITHUB\_SBOM`처럼 underscore 앞에 `\\`가 들어간 값
- `matchedEvidence` 내부에 삽입된 `\`\`\`css`와 `\`\`\` 코드 펜스

정상 JSON에서는 다음처럼 작성해야 한다.

```json
{
  "task": "ASSESS_TECHNOLOGY_LEVEL",
  "source": "GITHUB_SBOM"
}
```

화면 복사 과정에서 생긴 Markdown escape라면 무시해도 되지만, API 전송 전에
JSON parser로 반드시 확인한다.

### 4.2 버전과 lineage 필드

다음 필드는 request에 포함하거나 Backend가 서버 측에서 주입해야 한다.

```json
{
  "analysisId": "analysis-001",
  "repository": "org/gitjob-api",
  "commitSha": "9c1e2f0",
  "registryVersion": "technology-registry/v1",
  "evidenceRuleVersion": "evidence-rule/v1",
  "levelPolicyVersion": "level-policy/v2"
}
```

`levelPolicy`, `outputRules`를 클라이언트가 임의로 보내게 하면 평가 기준을
바꿀 수 있으므로, 운영 요청에서는 Backend가 버전으로 조회하고 immutable한
snapshot을 LLM 입력에 포함하는 방식이 안전하다.

### 4.3 Dependency Evidence 보강

`hasDirectDependency`만으로는 어떤 의존성이 확인됐는지 재현하기 어렵다.

```json
{
  "hasDirectDependency": true,
  "source": "GITHUB_SBOM",
  "packageName": "org.springframework.kafka:spring-kafka",
  "version": "3.2.0",
  "scope": "runtime",
  "manifestPath": "build.gradle",
  "commitSha": "9c1e2f0",
  "evidenceId": "dependency-001"
}
```

SBOM에 직접 의존성이 있다는 사실은 `CONFIGURED` 또는 L1 근거로 사용할 수
있지만, 실제 실행 코드 사용을 의미하지는 않는다.

### 4.4 Source와 Attribution 보강

Evidence에는 최소한 다음 정보가 있으면 좋다.

- `repository` 또는 `repoFullName`
- `commitSha`
- `filePath`
- `lineStart`, `lineEnd`
- GitHub permalink
- `scopeType`: `REPOSITORY`, `PERSONAL`, `ALL`
- `excludedReason`, `inherited` 여부
- `attribution` 판정에 사용한 commit/author 근거

LLM은 `USER_AUTHORED` 여부를 검증할 수 없다. 저자 귀속은 GitHub commit과
Backend/Worker의 attribution 로직이 확정한 값을 전달해야 한다.

## 5. Registry·Evidence DB와의 연결

전달받은 ERD의 역할은 다음과 같이 연결된다.

```text
technology_registry
        ↓ registry_version
technology
   ├─ technology_mapping      기술명·package·tag 매핑
   ├─ technology_category     직무 도메인 분류
   └─ evidence_rule           기술별 Evidence 규칙
          ↓
   evidence_rule_clause
          ↓
   evidence_rule_predicate
          ↓
   evidence_rule_predicate_value
```

### Registry

`technology_mapping`은 다음과 같은 정규화에 사용할 수 있다.

```text
value: Spring Kafka
tech_id: kafka 또는 spring-kafka
mapping_type: ALIAS
ecosystem: JVM
match_mode: EXACT
status: ACTIVE
registry_version: technology-registry/v1
```

상세 변형을 보존하면서 상위 기술로 집계하려면 `canonical_id`와
`aggregation_key`를 분리하거나, `parent_tech_id`/관계 필드를 명시해야 한다.

### Evidence Rule

`evidence_rule`부터 predicate value까지는 저장소 Fact가 특정 기술의 Evidence인지
판정하는 규칙 계층이다. 이 규칙을 통과한 결과가 `matchedEvidence`다.

따라서 LLM은 DB를 직접 조회하거나 원본 전체를 다시 검색하지 않고, Backend가
DB에서 만든 `matchedEvidence`와 버전 정보를 입력으로 받는다.

## 6. 권장 LLM 설계

### 6.1 권장 모드: Backend 판정 + LLM 설명

프로젝트의 기존 Rule-first 원칙과 가장 잘 맞는 구조다.

```text
Evidence Rule 실행
  → matchedEvidence
  → Backend가 repository/personal level 계산
  → LLM이 확정 결과의 설명 생성
  → usedEvidenceIds 검증
  → Explanation Snapshot 저장
```

이 모드에서 LLM은 다음을 수행한다.

- 확정된 레벨이 의미하는 내용을 한국어로 설명
- 사용된 Evidence를 요약
- 확인된 것과 확인되지 않은 것을 구분
- 다음에 확인할 Evidence 후보 제안
- 경고·분석 범위 제한을 사용자에게 설명

LLM은 다음을 수행하지 않는다.

- Registry에 없는 기술 ID 생성
- 제공되지 않은 파일·라인·Commit 생성
- `USER_AUTHORED` 여부 재판정
- Evidence가 없는 L3 판정
- 개발자 숙련도·채용 가능성·연봉 추론

### 6.2 대안 모드: LLM 제안 + Backend 재검증

Backend 개발량을 줄이기 위해 LLM이 레벨 후보를 제안하도록 할 수 있다.

```text
Fact Pack + levelPolicy
  → LLM proposedLevel
  → Backend가 동일 정책으로 재계산
  ├─ 일치 → 결과 저장
  └─ 불일치 → proposedLevel 폐기·REVIEW_REQUIRED
```

이 경우 LLM 응답에는 반드시 `usedEvidenceIds`가 포함되어야 하고, Backend는
해당 ID가 입력 Evidence의 부분집합인지 확인해야 한다. LLM의 레벨을 그대로
신뢰하면 안 된다.

## 7. 권장 LLM 요청·응답 계약

### 7.1 설명 생성 요청

실제 API 경로와 envelope은 Backend 컨벤션에 맞춰 결정한다. 아래는 내부 LLM
adapter에 전달할 논리 payload다.

```json
{
  "task": "EXPLAIN_TECHNOLOGY_LEVEL",
  "schemaVersion": "technology-level-explanation/v1",
  "analysisId": "analysis-001",
  "repository": "org/gitjob-api",
  "commitSha": "9c1e2f0",
  "technology": {
    "techId": "kafka",
    "displayName": "Apache Kafka"
  },
  "versions": {
    "registryVersion": "technology-registry/v1",
    "evidenceRuleVersion": "evidence-rule/v1",
    "levelPolicyVersion": "level-policy/v2"
  },
  "evaluation": {
    "repositoryLevel": "L2",
    "personalLevel": "L2",
    "status": "COMPLETE"
  },
  "matchedEvidence": [
    {
      "evidenceId": "evidence-001",
      "fact": {
        "factType": "METHOD_CALL",
        "value": "send",
        "receiver": "kafkaTemplate",
        "resolvedType": "KafkaTemplate"
      },
      "source": {
        "repository": "org/gitjob-api",
        "commitSha": "9c1e2f0",
        "filePath": "src/main/java/KafkaProducer.java",
        "lineStart": 24,
        "lineEnd": 24
      },
      "attribution": {
        "status": "USER_AUTHORED"
      }
    }
  ],
  "constraints": {
    "useOnlyProvidedEvidence": true,
    "doNotInferProficiency": true,
    "doNotInferEmployability": true,
    "outputJsonOnly": true
  }
}
```

### 7.2 설명 생성 응답

```json
{
  "schemaVersion": "technology-level-explanation/v1",
  "techId": "kafka",
  "repositoryLevel": "L2",
  "personalLevel": "L2",
  "usedEvidenceIds": [
    "evidence-001"
  ],
  "summary": "KafkaTemplate.send 호출이 확인되었고 해당 코드에 사용자 작성 근거가 있습니다.",
  "confirmedFacts": [
    "KafkaTemplate의 send 메서드 호출이 확인됨",
    "해당 Evidence가 USER_AUTHORED로 귀속됨"
  ],
  "notProven": [
    "테스트, retry/backoff, DLQ, metric/tracing 구성은 제공된 Evidence에서 확인되지 않음"
  ],
  "nextEvidence": [
    "Kafka producer 테스트 확인",
    "재시도·실패 메시지·모니터링 설정 확인"
  ],
  "warnings": []
}
```

`summary`, `confirmedFacts`, `notProven`, `nextEvidence`는 모두 입력 Evidence에서
확인 가능한 범위로 제한한다. Backend는 `usedEvidenceIds`와 최종 level 필드를
검증하고, LLM이 반환한 임의의 파일 경로·수치를 그대로 노출하지 않는다.

## 8. LLM Prompt 구성 원칙

매번 사용자가 전체 Registry를 수동으로 프롬프트에 넣지 않는다. Backend/Worker가
다음 순서로 내부 prompt를 조립한다.

1. Server-side에서 Registry·Rule·Policy version을 조회한다.
2. 해당 기술의 `technology`, `matchedEvidence`, 평가 결과만 선택한다.
3. 코드·문서의 원문은 지시문이 아닌 데이터로 취급하도록 경계를 표시한다.
4. JSON output schema와 `usedEvidenceIds` 제약을 추가한다.
5. Qwen에 요청한다.
6. 응답을 JSON parse하고 schema·Evidence ID·Registry ID를 검증한다.

동일한 원문과 version 조합은 cache한다.

```text
cache key = analysisId + techId + commitSha + registryVersion
            + evidenceRuleVersion + levelPolicyVersion + promptVersion
```

## 9. 로컬 LLM 실행 계약

현재 노트북 검증 환경은 다음과 같다.

| 항목 | 값 |
|---|---|
| Model | `qwen3.5:4b` |
| Runtime | WSL2 + Docker Desktop + Ollama |
| Context | 기본 8192 tokens |
| Timeout | 300초 |
| Output limit | 최대 5500 tokens |
| Docker에서의 Ollama 주소 | `http://host.docker.internal:11434` |

Backend 컨테이너에서 `localhost:11434`를 사용하면 Backend 컨테이너 자신을
가리키므로 안 된다. 운영 연결 주소는 배포 환경에 맞는 환경 변수로 분리한다.

권장 환경 변수:

```dotenv
LLM_PROVIDER=ollama
LLM_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=qwen3.5:4b
LLM_TIMEOUT_SECONDS=300
LLM_MAX_OUTPUT_TOKENS=3000
LLM_MAX_RETRIES=2
```

기술 레벨 설명은 일반적으로 3000 tokens 이내로 제한하고, 긴 Evidence 원문을
그대로 보내지 않고 필요한 근거만 발췌한다.

## 10. 실패·품질·보안 정책

### 입력 상태

다음 상태를 구분한다.

| 상태 | 처리 |
|---|---|
| `COMPLETE` | 평가 또는 설명 생성 진행 |
| `INSUFFICIENT_EVIDENCE` | 확정 레벨 없이 부족한 근거 안내 |
| `REVIEW_REQUIRED` | 정책 충돌·저자 귀속 충돌·LLM/Backend 불일치 |
| `FAILED` | 재시도 후 실패. 원인과 trace ID 저장 |

`parseStatus=COMPLETE`라도 dependency scan이 실제로 수행되지 않았다면 직접
의존성 없음과 미확인을 구분해야 한다. 이를 위해 `dependencyScanStatus`를 별도로
두는 것을 권장한다.

### LLM 출력 검증

1. JSON parser로 응답을 파싱한다.
2. 출력 schema와 enum을 검증한다.
3. `usedEvidenceIds`가 입력 Evidence의 부분집합인지 확인한다.
4. `techId`가 해당 Registry version에 존재하는지 확인한다.
5. 파일 경로·라인·Commit이 입력에 있는 값인지 확인한다.
6. `repositoryLevel`·`personalLevel`이 정책 계산값과 일치하는지 확인한다.
7. 검증 실패 시 LLM 응답을 폐기하고 Rule Template 또는 `REVIEW_REQUIRED`를 반환한다.

### 개인정보·원문 보호

- private repository의 원문과 GitHub token을 외부 검색 서비스나 외부 LLM으로 보내지 않는다.
- 사용자의 이름·이메일보다 `USER_AUTHORED` 같은 판정 결과를 우선 전달한다.
- 저장소 전체 코드를 보내지 않고 필요한 Evidence만 전달한다.
- prompt·응답 로그에는 token, secret, 전체 코드 본문을 저장하지 않는다.
- 모델은 코드·README 안에 포함된 지시문을 실행하지 않고 분석 데이터로만 취급한다.

## 11. 저장 모델 제안

기존 `fact`·`evidence`·Snapshot 구조가 있으면 최종 레벨은 해당 구조에 저장하고,
LLM 결과는 설명 이력으로 분리하는 구성이 좋다.

```text
technology_assessment
  assessment_id
  analysis_id
  tech_id
  repository_level
  personal_level
  level_policy_version
  evidence_rule_version
  status

technology_explanation
  explanation_id
  assessment_id
  model_name
  prompt_version
  used_evidence_ids
  summary
  confirmed_facts
  not_proven
  next_evidence
  validation_status
  generated_at
```

최소한 다음 lineage는 결과와 함께 남긴다.

- `analysisId`
- `repository`와 `commitSha`
- `techId`
- `registryVersion`
- `evidenceRuleVersion`
- `levelPolicyVersion`
- `modelName`
- `promptVersion`
- `usedEvidenceIds`

## 12. Backend 구현 순서

1. L0~L3 정책을 기존 문서와 새 payload 중 어느 것으로 할지 확정한다.
2. Repository Level과 Personal Level의 분리 여부를 확정한다.
3. `registryVersion`, `evidenceRuleVersion`, `levelPolicyVersion`을 추가한다.
4. Backend가 DB Rule 결과를 Fact Pack DTO로 변환한다.
5. 최소한의 deterministic level reducer를 구현하거나 기존 평가 결과를 연결한다.
6. 내부 LLM client와 timeout·retry·cache를 구현한다.
7. 설명 생성 prompt와 response schema를 고정한다.
8. `usedEvidenceIds`·Registry ID·level 일치 여부를 검증한다.
9. LLM 실패 시 Rule Template/`REVIEW_REQUIRED` fallback을 구현한다.
10. synthetic Evidence fixture로 L0~L3·저자 귀속·불완전 분석·정책 충돌을 테스트한다.

## 13. 담당자 협의 사항

1. 전달받은 `levelPolicy`와 기존 Backend 문서 중 어느 것이 최신 기준인가?
2. L3를 `USER_AUTHORED 구현 1건`으로 볼 것인가, 운영·테스트 Evidence까지 요구할 것인가?
3. Repository Level과 Personal Level을 분리할 것인가?
4. LLM은 최종 레벨을 결정할 것인가, 설명만 생성할 것인가?
5. `technology_mapping`에서 상세 variant와 `aggregation_key`를 어떻게 표현할 것인가?
6. `matchedEvidence`와 LLM 설명 결과를 어느 Snapshot/테이블에 저장할 것인가?
7. private repository Evidence를 LLM에 전달하는 범위와 보존 기간은 무엇인가?
8. LLM 결과가 Backend 정책과 다를 때 `FAILED`와 `REVIEW_REQUIRED` 중 어떤 상태를 사용할 것인가?

## 14. 관련 문서

- [AI·분석 설계 문서](README.md)
- [Backend 설계 문서](../be/README.md)
- [데이터 플랫폼·파이프라인 문서](../data/README.md)
- [A→C job-analysis input contract](../data/2026-09-01-a-to-c-job-analysis-input-contract.md)
- [기술명 정규화·대표 기술 집계 설계안](technology-normalization-design.md)
