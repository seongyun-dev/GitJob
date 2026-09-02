# 기술명 정규화·대표 기술 집계 설계안

> 상태: 담당자 협의안
>
> 기준일: 2026-09-02
>
> 관련 작업: `S15P21E102-77` / `infra/S15P21E102-77-ai-infra`

## 1. 문서 목적

GitJob에서 채용공고와 저장소에 나타나는 다양한 기술 표현을 하나의 대표
기술로 연결하고, 동시에 원문 표현과 세부 변형을 보존하기 위한 설계안이다.

예를 들어 다음 표현은 기술 수요를 집계할 때 `kafka`로 합칠 수 있다.

| 원문 표현 | 대표 기술 | 세부 변형·관계 |
|---|---|---|
| `Apache Kafka` | `kafka` | core |
| `Kafka` | `kafka` | core |
| `Spring Kafka` | `kafka` | Spring integration |
| `Kafka Streams` | `kafka` | stream processing |
| `kafka-clients` | `kafka` | client library |
| `kafka-python` | `kafka` | Python client |
| `Confluent Kafka` | `kafka` | vendor/client |
| `Redpanda` | `redpanda` | Kafka-compatible, 별도 집계 |
| `RabbitMQ` | `rabbitmq` | 별도 메시징 기술 |

이 문서에서 말하는 정규화는 단순 대소문자·공백 정리가 아니라, 원문 기술명을
기준 taxonomy의 대표 기술과 연결하는 canonical mapping을 의미한다.

## 2. 배경과 목표

기술명은 채용공고·README·의존성 파일·코드에서 서로 다른 형태로 표현된다.
정규화하지 않으면 같은 기술이 여러 기술로 분리되어 수요 집계와 레포 분석이
왜곡될 수 있다.

목표는 다음과 같다.

- `Spring Kafka`와 `Kafka Streams`를 Kafka 생태계 수요로 함께 집계한다.
- 원문 기술명과 세부 구현 방식은 삭제하지 않는다.
- 기술 Registry를 코드에 하드코딩하지 않고 데이터로 관리한다.
- 알려진 표현은 빠르게 처리하고, 새로운 표현·애매한 표현만 LLM의 도움을 받는다.
- 모델이 존재하지 않는 대표 기술 ID를 임의로 만들지 못하게 한다.
- 정규화 결과의 근거·버전·판정 주체를 재현 가능하게 보존한다.

## 3. 제안 결론

정규화 전체를 LLM에 맡기거나, 모든 변형을 백엔드 코드의 조건문으로 구현하지
않는다. 다음과 같이 Registry를 중심으로 얇은 백엔드와 LLM을 결합한다.

```text
원문 기술명·Evidence
        ↓
문자열 기본 정리 및 Registry alias 조회
        ├─ 확정 매칭 → 즉시 정규화
        └─ 미등록·애매한 표현
                ↓
        관련 Registry 후보만 LLM에 전달
                ↓
        결과 schema·Registry ID 검증
                ↓
        정규화 결과·근거·버전 저장
                ↓
        집계는 aggregation_key 사용
```

이 구조에서는 새로운 변형을 추가할 때마다 백엔드 코드를 수정하지 않고 Registry
데이터만 갱신할 수 있다. LLM은 Registry에 없는 표현을 제안하거나 문맥을
판단하는 보조 역할을 맡는다.

## 4. 역할 분리

### 4.1 Technology Registry

대표 기술, alias, 부모 기술, 집계 정책을 관리하는 기준 데이터다.

Registry는 다음 정보를 가질 수 있다.

| 필드 | 의미 |
|---|---|
| `canonical_id` | 내부 대표 기술 ID. 예: `kafka` |
| `canonical_name` | 화면 표시명. 예: `Apache Kafka` |
| `aliases` | 원문에서 허용할 표현 목록 |
| `parent_id` | 상위 생태계 또는 대표 기술 |
| `aggregation_key` | 수요 집계에 사용할 ID |
| `relation` | core, integration, client 등의 관계 |
| `provider` | AWS, Confluent 등 공급자 |
| `status` | 활성·폐기 여부 |
| `registry_version` | taxonomy 버전 |

### 4.2 백엔드

백엔드는 복잡한 정규화 규칙을 모두 코드로 구현하지 않고 다음만 담당한다.

- Registry 로드·버전 관리·캐시
- 원문 기술명과 Evidence를 LLM에 전달
- LLM 출력 JSON과 대표 ID 검증
- 원문·정규화 결과·판정 버전 저장
- 중복 호출 방지와 재시도
- 미확정 결과의 검토 큐 등록
- `aggregation_key` 기준 집계

### 4.3 로컬 LLM

Qwen은 다음 작업에 사용한다.

- Registry alias에 없는 새로운 표현의 후보 연결
- 공고 문맥에서 기술명이 의미하는 대상 파악
- `Spring Kafka`가 Kafka core인지 integration framework인지 구분
- 코드·의존성·설정에서 기술 사용 맥락 추출
- 새로운 alias를 Registry에 추가할지 검토할 후보 제안

LLM은 자유롭게 대표 기술 ID를 만들지 않고, 백엔드가 전달한 Registry 후보 중
하나를 선택해야 한다.

### 4.4 사람 검토

다음 결과는 자동 확정하지 않고 검토 대상으로 둔다.

- Registry에 없는 기술명
- 후보가 여러 개이고 confidence가 낮은 경우
- Kafka-compatible 제품처럼 통합 여부가 정책에 따라 달라지는 경우
- 하나의 표현이 여러 기술을 동시에 의미할 수 있는 경우

## 5. Registry 보관 방식

### 5.1 초기 단계: Git 관리 YAML 또는 JSON

기술 종류가 많지 않고 담당자 협의·코드 리뷰를 중심으로 운영하는 초기에는
저장소의 versioned YAML/JSON이 적합하다.

예시:

```yaml
version: technology-taxonomy/v1

technologies:
  - canonical_id: kafka
    canonical_name: Apache Kafka
    aliases:
      - kafka
      - apache kafka
    aggregation_key: kafka
    relation: CORE

  - canonical_id: spring-kafka
    canonical_name: Spring for Apache Kafka
    aliases:
      - spring kafka
      - spring-kafka
    parent_id: kafka
    aggregation_key: kafka
    relation: INTEGRATION_FRAMEWORK

  - canonical_id: kafka-streams
    canonical_name: Kafka Streams
    aliases:
      - kafka streams
      - kafka-streams
    parent_id: kafka
    aggregation_key: kafka
    relation: STREAM_PROCESSING

  - canonical_id: redpanda
    canonical_name: Redpanda
    aliases:
      - redpanda
    aggregation_key: redpanda
    relation: COMPATIBLE_NOT_SAME
```

장점은 변경 이력이 Git에 남고, 담당자 리뷰와 Registry 버전 고정이 쉽다는 점이다.

### 5.2 운영 단계: DB 테이블

관리 화면에서 alias를 추가하거나 담당자가 즉시 승인해야 하는 단계가 되면
PostgreSQL로 옮길 수 있다. 이때도 변경된 Registry snapshot 또는 version을
분석 결과에 함께 저장해야 재현성이 유지된다.

권장 논리 테이블은 다음과 같다.

```text
technology_taxonomy
  canonical_id, canonical_name, parent_id, aggregation_key,
  relation, provider, status, registry_version

technology_alias
  alias_normalized, canonical_id, variant, relation,
  priority, source, registry_version

technology_normalization_decision
  raw_technology, source_technology_id, canonical_id,
  aggregation_key, decision_source, confidence, evidence,
  taxonomy_version, review_status, created_at
```

초기에는 YAML/JSON을 source of truth로 두고 애플리케이션 시작 시 메모리의
alias map으로 읽는 구성이 가장 단순하다. 수요 집계·관리자 승인·감사 이력이
필요해지면 DB를 source of truth로 전환한다.

## 6. 정규화 결과 계약

원천값을 대표 기술명으로 덮어쓰지 않는다. 다음 세 값을 분리해서 보존한다.

```json
{
  "raw_technology": "Spring Kafka",
  "source_technology_id": "spring-kafka",
  "canonical_technology_id": "spring-kafka",
  "canonical_name": "Spring for Apache Kafka",
  "aggregation_key": "kafka",
  "variant": "spring-kafka",
  "relation": "INTEGRATION_FRAMEWORK",
  "related_canonical_ids": ["spring"],
  "decision_source": "rule",
  "confidence": 0.99,
  "needs_registry_review": false,
  "taxonomy_version": "technology-taxonomy/v1"
}
```

필드 의미는 다음과 같다.

- `raw_technology`: 공고·코드에서 관측한 원문
- `source_technology_id`: A팀 또는 원천 시스템이 보낸 ID
- `canonical_technology_id`: 상세 기술 분석용 대표 ID
- `aggregation_key`: 상위 기술 수요 집계용 ID
- `variant`: 구현체·라이브러리·프레임워크 변형
- `related_canonical_ids`: 함께 사용된 관련 기술
- `decision_source`: `rule`, `llm`, `human`
- `taxonomy_version`: 당시 사용한 Registry 버전

현재 `AI/job/contracts.py`의 `map_source_technology_id()`는 안전한 source ID를
검증·alias 변환하는 경계 adapter다. `Spring Kafka → Kafka`처럼 의미 기반으로
상위 기술을 정하는 기능은 이 함수에 섞지 않고 별도의 normalization 단계로
두는 것이 안전하다.

## 7. Kafka 정규화 정책 예시

| 표현 | `canonical_id` | `aggregation_key` | 관계 | 비고 |
|---|---|---|---|---|
| `Kafka` | `kafka` | `kafka` | `CORE` | Kafka 자체 |
| `Spring Kafka` | `spring-kafka` | `kafka` | `INTEGRATION_FRAMEWORK` | Spring 관련 기술도 보존 가능 |
| `Kafka Streams` | `kafka-streams` | `kafka` | `STREAM_PROCESSING` | 스트림 처리 API |
| `kafka-clients` | `kafka-clients` | `kafka` | `CLIENT_LIBRARY` | 클라이언트 라이브러리 |
| `confluent-kafka` | `confluent-kafka` | `kafka` | `CLIENT_LIBRARY` | Confluent provider 보존 권장 |
| `Redpanda` | `redpanda` | `redpanda` | `COMPATIBLE_NOT_SAME` | 기본적으로 Kafka와 별도 |
| `RabbitMQ` | `rabbitmq` | `rabbitmq` | `UNRELATED` | Kafka로 합치지 않음 |

`Spring Kafka`를 Kafka 집계에 포함할지는 가능하지만, Spring 기술 수요에도
포함할지 여부는 별도 정책으로 결정해야 한다. 집계 기준을 하나로 고정하지
않으면 동일 공고가 Kafka와 Spring 수요에 동시에 포함될 수 있다.

## 8. LLM 호출 정책

### 8.1 Registry 전체를 매번 수동으로 넣지 않음

사용자가 프롬프트에 Registry를 직접 붙여 넣는 방식은 사용하지 않는다. 백엔드가
Registry를 읽고, 원문과 관련된 후보만 자동으로 프롬프트에 추가한다.

```text
전체 Registry
  → alias·문자열 검색 또는 후보 검색
  → 관련 후보 5~20개
  → 원문·Evidence와 함께 LLM 전달
```

초기 Registry가 작으면 전체 Registry를 자동으로 넣어도 되지만, 사용자가 매번
프롬프트를 조립하지 않도록 호출부에서 처리한다.

### 8.2 호출하지 않아도 되는 경우

정확한 alias가 하나로 매칭되는 경우에는 LLM을 호출하지 않는다. 이 결과는
빠르고 결정적이며, 모델 응답 변동도 없다.

### 8.3 LLM 호출이 필요한 경우

- Registry에 없는 표현
- 오타 또는 여러 표기가 섞인 표현
- 기술의 역할·관계를 문맥으로 판단해야 하는 경우
- 공고 본문이나 코드에서 기술 언급을 추출하는 경우
- 새 alias 후보를 제안하는 경우

## 9. 실패·품질 관리

LLM을 사용하더라도 다음 검증은 백엔드에서 수행한다.

1. 출력이 정해진 JSON schema인지 확인한다.
2. `canonical_technology_id`가 현재 Registry에 존재하는지 확인한다.
3. 원문 기술명과 Evidence가 보존됐는지 확인한다.
4. Registry에 없는 ID나 근거 없는 매핑은 `needs_registry_review=true`로 바꾼다.
5. LLM이 실패하면 원문을 버리지 않고 미정 상태로 저장한다.
6. 같은 원문·taxonomy version 조합은 cache한다.
7. 결과에 모델 버전, prompt 버전, taxonomy version을 남긴다.
8. LLM이 자동으로 Registry를 수정하지 못하게 한다. 승인된 결과만 alias로 반영한다.

## 10. 레포 분석과의 연결

레포 분석에서 의존성 파일만 확인되면 해당 기술을 사용한다고 확정하지 않고,
증거 유형을 구분해야 한다.

| 증거 | 해석 예시 |
|---|---|
| `requirements.txt`, `package.json` | 설정·직접 의존성 확인 |
| import 또는 client 생성 | 코드 통합 확인 |
| producer/consumer 호출 | 실행 경로 사용 확인 |
| 테스트 코드 | 테스트 근거 확인 |
| Docker·배포·모니터링 설정 | 운영 근거 확인 |

예를 들어 `confluent-kafka`가 requirements에만 있으면 기술 정규화 결과의
`aggregation_key`는 `kafka`로 만들 수 있지만, 레포 사용 수준은 `CONFIGURED`로
보는 것이 적절하다. 실제 import·호출까지 확인된 경우에만 `INTEGRATED` 이상으로
올린다.

기술 레벨 L0~L3, Skill Gap, 추천 순위는 기존 Rule-first 정책을 유지하며
정규화 LLM이 결정하지 않는다.

## 11. 기대 효과와 한계

### 기대 효과

- 기술 alias를 추가할 때 백엔드 조건문을 수정할 필요가 줄어든다.
- 공고·코드·의존성의 서로 다른 표현을 같은 집계 기준으로 통합할 수 있다.
- 새로운 기술 표현을 사람이 처음부터 모두 예상하지 않아도 된다.
- 원문과 변형을 보존하므로 상세 분석과 상위 집계를 동시에 지원할 수 있다.

### 한계

- LLM은 같은 입력에도 모델 버전·프롬프트에 따라 다른 결과를 낼 수 있다.
- Registry에 없는 기술을 잘못된 대표 기술로 연결할 가능성이 있다.
- 모든 호환 제품을 같은 기술로 합칠지는 기술적 사실보다 비즈니스 정책에 가깝다.
- LLM 호출은 백엔드 alias 조회보다 느리므로 cache와 batch 처리가 필요하다.
- 최종 결과의 신뢰성을 위해 최소한의 schema·Registry 검증 코드는 필요하다.

## 12. 협의가 필요한 결정 사항

담당자와 다음 항목을 먼저 확정해야 한다.

1. `Spring Kafka`를 Kafka 집계에 포함하면서 Spring 집계에도 포함할 것인가?
2. `Kafka Streams`, `Kafka Connect`, `Confluent Platform`, `MSK`의 집계 정책은 무엇인가?
3. Redpanda·WarpStream 등 Kafka-compatible 제품을 Kafka와 통합할 것인가?
4. `canonical_id`와 `aggregation_key`를 분리할 것인가?
5. Registry의 1차 source of truth를 Git YAML/JSON으로 할 것인가, DB로 할 것인가?
6. LLM confidence 기준과 사람 검토 기준을 어디에 둘 것인가?
7. 승인된 LLM 결과를 alias Registry에 자동 반영할 것인가, 수동 승인할 것인가?
8. 원문·Evidence·정규화 결과를 어느 저장소와 보존 기간으로 관리할 것인가?

## 13. 제안 MVP

1. Kafka·Spring Kafka·Kafka Streams·Confluent·Redpanda 등 대표 사례의 taxonomy를 합의한다.
2. `technology-taxonomy/v1` YAML Registry를 Git에 추가한다.
3. 기술명 정규화 요청·응답 schema를 고정한다.
4. Registry alias 매칭과 LLM fallback을 수행하는 얇은 normalizer를 만든다.
5. 원문·canonical ID·aggregation key·근거·버전을 저장한다.
6. 미확정 결과를 검토할 수 있는 목록을 만든다.
7. 승인된 alias를 Registry에 반영하고 재처리한다.
8. 정규화 결과를 공고 수요 집계와 레포 기술 분석에서 공통으로 사용한다.
