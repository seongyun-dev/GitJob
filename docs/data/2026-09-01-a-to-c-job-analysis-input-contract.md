# A→C 채용공고 분석 입력 계약

> 상태: 구현 계약 문서화 완료 / 실제 A조 Dataset 연동 전
>
> 기준일: 2026-09-01
>
> Jira: [S15P21E102-90](https://ssafy.atlassian.net/browse/S15P21E102-90)
>
> 기준 계약 버전: `job-analysis-input/v1`
>
> Authoritative source: [`AI/job/contracts.py`](../../AI/job/contracts.py)
>
> 기준 작업트리: `origin/develop@cae22101e57e2228fc96a94963e94769165ac957`
>
> 계약 코드 마지막 변경: `60185336d38f9f8cf4fc35ccdf540f6a4d60640a`

## 1. 목적과 적용 범위

이 문서는 A조가 수집·파싱한 채용공고를 C조 분석 경계로 전달할 때 사용하는
`JobAnalysisInputBatch` JSON 계약을 설명한다. 사람이 필드 의미와 책임 경계를
검토할 수 있게 하면서, A조가 [기계 검증용 JSON Schema](contracts/job-analysis-input-v1.schema.json)와
[고정 Fixture](../../AI/job/fixtures/job_analysis_input_v1.json)로 자신의 출력을
검증할 수 있게 하는 것이 목적이다.

적용 범위는 채용공고 source 필드, 본문 가용 상태, 원천에서 이미 구조화되어
관측된 경우의 upstream 기술 후보와 Evidence, Dataset·Pipeline lineage metadata,
그리고 C조 입력 adapter까지다. Technology
Registry의 최종 `MATCHED`·`AMBIGUOUS`·`UNKNOWN` 판정, 직무별 수요 집계와 추천
결과는 이 입력 계약의 범위가 아니다.

이 문서는 계약을 새로 정의하지 않는다. 필드, enum, 기본값과 검증 규칙이
문서와 다르면 [`AI/job/contracts.py`](../../AI/job/contracts.py)가 단일 기준이다.

## 2. A조와 C조의 책임 경계

| 구분 | 책임 |
|---|---|
| A조 | source record 식별자·원천 공고 ID/URL·원문 기반 필드·본문 상태·수집 시각·content hash·Dataset/Pipeline/collector version을 계약 형태로 전달하고, 원천에서 구조화된 기술 후보와 Evidence가 관측된 경우 함께 보존 |
| A조 | JSON Schema로 구조·타입·enum을 확인하고, Pydantic runtime 검증으로 cross-field 규칙까지 확인 |
| C조 입력 경계 | strict validation으로 알 수 없는 필드와 잘못된 타입을 거부하고, 원문 표기·Evidence·미확정 후보를 보존 |
| C조 adapter | 명시된 source `technology_id`만 안전한 내부 `tech_id`로 변환하고, Registry 판정 없이 레코드를 내부 모델로 옮김 |
| C조 후속 분석 | 별도 Registry/rule version에 따라 최종 기술 판정·요구유형 분류·semantic duplicate 검토·수요 집계를 수행 |

`registry_version`과 requirement rule version은 A조 수집 입력 metadata가 아니다.
후속 C조 결과가 실제 사용한 버전을 기록해야 한다. 기대 Fixture의 synthetic
version은 후속 Mapper·분류 테스트용이며 production input 필드가 아니다.

## 3. 전달 흐름과 authoritative source

```text
A조 source 수집·파싱
  → JobAnalysisInputBatch JSON 생성
  → JSON Schema 구조 검증
  → Pydantic runtime 의미 검증
  → C조 adapt_job_analysis_input
  → Registry Mapper·요구유형 rule·수요 분석
```

계약 자료의 우선순위와 역할은 다음과 같다.

1. [`AI/job/contracts.py`](../../AI/job/contracts.py): 필드·enum·validator·adapter의
   authoritative source
2. [JSON Schema](contracts/job-analysis-input-v1.schema.json):
   `JobAnalysisInputBatch.model_json_schema(by_alias=True)`에서 생성한 구조 계약
3. 이 문서: 사람을 위한 의미·책임·검증 안내
4. 정상·오류·기대 Fixture: 고정 사례와 회귀 테스트 입력

JSON Schema는 `additionalProperties`, 필수 필드, 타입, enum, pattern과
`date-time` format을 표현한다. 비공백 문자열, timezone 포함 여부,
`TEXT_AVAILABLE`과 `description_text`의 관계 같은 custom validator는 모두
표현하지 못하므로 Schema 통과만으로 runtime 계약 통과를 단정하지 않는다.

## 4. 필드 계약

모든 객체는 정의되지 않은 추가 필드를 거부한다. `필수`는 JSON property가 반드시
존재해야 한다는 뜻이고, `null 허용`은 존재하는 property의 값으로 JSON `null`을
쓸 수 있다는 뜻이다. 필수가 아닌 필드는 생략하면 표의 기본값을 사용한다.

### 4.1 Batch 필드

| 필드 | JSON 타입 | 필수 | null 허용 | 규칙·의미 |
|---|---|---:|---:|---|
| `schema_version` | string | 예 | 아니요 | 정확히 `job-analysis-input/v1` |
| `dataset_snapshot_id` | string | 예 | 아니요 | 비공백 Dataset snapshot 식별자 |
| `pipeline_run_id` | string | 예 | 아니요 | 비공백 Pipeline 실행 식별자 |
| `collector_version` | string | 예 | 아니요 | 비공백 수집기/파서 버전 |
| `records` | array | 예 | 아니요 | `JobPostingInput` 배열, 현재 계약은 빈 배열도 허용 |

### 4.2 채용공고 필드

| 필드 | JSON 타입 | 필수 | null 허용 | 기본값 | 규칙·의미 |
|---|---|---:|---:|---|---|
| `source_record_id` | string | 예 | 아니요 | - | 비공백 source record 식별자 |
| `canonical_job_id` | string | 아니요 | 예 | `null` | upstream이 제공한 semantic duplicate 후보 키. 값이 있으면 비공백 |
| `source_site` | string | 예 | 아니요 | - | 비공백 원천 사이트 식별자 |
| `source_posting_id` | string | 예 | 아니요 | - | 비공백 원천 공고 ID. 숫자 자동 변환 없음 |
| `source_url` | string/URI | 예 | 아니요 | - | HTTP(S) URL로 검증 |
| `company_name` | string | 예 | 아니요 | - | 비공백 원문 회사명 |
| `title` | string | 예 | 아니요 | - | 비공백 원문 공고 제목 |
| `raw_job_category` | string | 아니요 | 예 | `null` | 원천 직무/카테고리 값 |
| `career_level` | string | 아니요 | 예 | `null` | 원천 경력 조건 |
| `region` | string | 아니요 | 예 | `null` | 원천 지역 값 |
| `description_text` | string | 아니요 | 예 | `null` | 사용 가능한 정제 본문. `TEXT_AVAILABLE`이면 비공백 필수 |
| `raw_artifact_uri` | string | 아니요 | 예 | `null` | 원본 artifact 위치. `IMAGE_ONLY`이면 비공백 필수 |
| `body_status` | string/enum | 예 | 아니요 | - | 본문 상태, 5절 규칙 적용 |
| `posting_status` | string/enum | 아니요 | 아니요 | `UNKNOWN` | `ACTIVE`, `CLOSED`, `UNKNOWN` |
| `posted_at` | string/date-time | 아니요 | 예 | `null` | 있으면 ISO 8601 `T` 구분자와 timezone 필수 |
| `deadline` | string/date-time | 아니요 | 예 | `null` | 있으면 ISO 8601 `T` 구분자와 timezone 필수 |
| `collected_at` | string/date-time | 예 | 아니요 | - | ISO 8601 `T` 구분자와 timezone 필수 |
| `content_hash` | string | 예 | 아니요 | - | 소문자 16진수 64자리 SHA-256 형태 |
| `technology_mentions` | array | 아니요 | 아니요 | `[]` | `TechnologyMentionInput` 배열 |

외부 JSON timestamp는 ISO 8601 date-time 문자열이어야 한다. `0`, `0.0`, `"0"`,
boolean 같은 epoch 유사 값은 자동 변환하지 않고 거부한다.

### 4.3 기술 후보 필드

| 필드 | JSON 타입 | 필수 | null 허용 | 기본값 | 규칙·의미 |
|---|---|---:|---:|---|---|
| `raw_technology` | string | 예 | 아니요 | - | 비공백 원문 기술 표기 |
| `technology_id` | string | 예 | 예 | - | source ID. 미확정 후보는 property를 유지하고 `null` 사용 |
| `requirement_type` | string/enum | 예 | 아니요 | - | upstream 입력값 `REQUIRED`, `PREFERRED`, `MENTIONED` |
| `source_surface` | string/enum | 예 | 아니요 | - | 후보가 관측된 `TITLE` 또는 `BODY` |
| `evidence_section` | string | 아니요 | 예 | `null` | 원문 section 정보 |
| `evidence_text` | string | 예 | 아니요 | - | 비공백 근거 텍스트 |
| `extraction_method` | string | 예 | 아니요 | - | 비공백 추출 방식 식별자 |

외부 property 이름은 반드시 `technology_id`다. 내부 Python 이름인
`source_technology_id`를 JSON에 보내면 추가 필드로 거부된다.

## 5. 본문 상태 처리 규칙

| 상태 | 필수 조건 | 현재 계약의 해석 |
|---|---|---|
| `TEXT_AVAILABLE` | `description_text`가 존재하고 비공백 | 분석에 사용할 수 있는 텍스트 본문 |
| `IMAGE_ONLY` | `raw_artifact_uri`가 존재하고 비공백 | 텍스트 본문 없이 원본 artifact만 관측됨 |
| `BLOCKED` | 추가 cross-field 필수 조건 없음 | 접근 제한 등으로 본문을 확보하지 못한 관측 상태 |
| `MISSING` | 추가 cross-field 필수 조건 없음 | 원천에서 본문을 관측하지 못한 상태 |
| `PARSE_FAILED` | 추가 cross-field 필수 조건 없음 | 수집물은 있으나 본문 파싱이 실패한 상태 |

`BLOCKED`, `MISSING`, `PARSE_FAILED`에 별도 사유 field를 임의로 추가하면 strict
contract에서 거부된다. 사유 전달이 필요해지면 먼저 계약 버전과 모델을 명시적으로
변경해야 한다. 이 계약은 권한 없는 OCR 수행이나 누락 본문 생성을 지시하지 않는다.

## 6. source 기술 후보와 C조 Registry 판정 경계

`technology_mentions`를 제공하는 경우 A조 입력은 source `technology_id`,
`raw_technology`, `requirement_type`, 관측 위치와 Evidence를 함께 보존한다.
이 배열은 선택 필드이며, A조가 원천에 없는 기술 후보를 새로 판정해야 한다는 뜻이
아니다. `technology_id=null`인 미확정 후보도 버리지 않는다.

입력 adapter가 수행하는 변환은 다음 명시적 alias와 안전한 slug 통과뿐이다.

| source `technology_id` | 내부 `tech_id` |
|---|---|
| `c#` | `csharp` |
| `c++` | `cpp` |
| `.net` | `dotnet` |
| `.net-maui` | `dotnet-maui` |
| `node.js` | `nodejs` |
| `next.js` | `nextjs` |
| `vue.js` | `vuejs` |
| `[a-z0-9]+(-[a-z0-9]+)*` 형태 | 동일 값 |

이 adapter는 Registry 조회나 `MATCHED`·`AMBIGUOUS`·`UNKNOWN` 판정을 수행하지
않는다. 안전한 형식이 아니고 명시 mapping도 없는 ID는 추측해서 정규화하지 않고
실패한다. 최종 Registry 판정과 rule version 기록은 C조 후속 결과의 책임이다.

## 7. semantic duplicate와 기술적 멱등성 경계

`find_semantic_duplicate_groups`는 같은 비공백 `canonical_job_id` 아래에 서로 다른
`source_record_id`가 둘 이상 있을 때 source record ID 목록을 노출한다. record를
삭제하거나 대표 공고를 확정하지 않는다. 동일 `source_record_id`가 재전달된 경우는
하나의 semantic duplicate group으로 만들지 않는다.

Kafka 재전달, Consumer 재시작, Spark Retry와 Replay의 중복 방지는 A조의 기술적
멱등성 경계다. 이 JSON 계약에는 Kafka offset이나 `event_id`가 없으며,
`canonical_job_id`를 transport delivery key로 사용하지 않는다.
`dataset_snapshot_id`, `pipeline_run_id`, `source_record_id`, `canonical_job_id`는
각각 Snapshot, 실행, source record, 업무 중복 후보라는 서로 다른 목적을 가진다.

## 8. 고정 Fixture의 역할

| Fixture | 역할 |
|---|---|
| [정상 입력](../../AI/job/fixtures/job_analysis_input_v1.json) | 10개 공고, 12개 기술 후보, 5개 본문 상태, alias·미확정 후보·semantic duplicate 후보를 포함한 유효 입력 |
| [오류 입력](../../AI/job/fixtures/invalid_job_analysis_input_v1.json) | 잘못된 schema version, 필수 metadata 누락, 숫자 source ID/timestamp, 본문 상태 조건 위반, 잘못된 enum/ID/property를 포함한 8개 거부 사례 |
| [기대 결과](../../AI/job/fixtures/job_analysis_expected_v1.json) | 12개 후보에 대한 후속 Mapper·요구유형 분류 기대값. `fixture_only=true`이며 A조 입력 Schema 대상이 아님 |

정상 Fixture는 실제 A조 Dataset의 대표 표본이 아니라 계약 개발용 synthetic data다.
기대 결과의 `registry_version`과 `requirement_rule_version`도 production version이
아니다.

## 9. A조 출력 검증 방법

아래 명령은 저장소 root의 Python 환경에
[`AI/requirements-dev.txt`](../../AI/requirements-dev.txt)가 설치됐다는 전제다.

### 9.1 저장된 Schema와 현재 모델의 일치 확인

```powershell
Set-Location AI
python -c "import json; from pathlib import Path; from job.contracts import JobAnalysisInputBatch; expected=json.loads(Path('../docs/data/contracts/job-analysis-input-v1.schema.json').read_text(encoding='utf-8')); actual=JobAnalysisInputBatch.model_json_schema(by_alias=True); assert actual == expected"
```

### 9.2 정상 Fixture runtime 검증

```powershell
Set-Location AI
python -c "from pathlib import Path; from job.contracts import JobAnalysisInputBatch; JobAnalysisInputBatch.model_validate_json(Path('job/fixtures/job_analysis_input_v1.json').read_text(encoding='utf-8')); print('valid fixture: PASS')"
```

### 9.3 실제 A조 JSON 검증

`date-time` format 검사를 활성화한 Schema 호환 validator로 먼저
[JSON Schema](contracts/job-analysis-input-v1.schema.json)를 검사한 뒤, C조 인계 전에는
custom validator까지 실행되는 Pydantic model로 최종 확인한다.

다음 Python 코드는 저장소의 `AI` 디렉터리에서 실행한다.

```python
from pathlib import Path

from job.contracts import JobAnalysisInputBatch

input_path = Path("path/to/a-team-output.json")
batch = JobAnalysisInputBatch.model_validate_json(
    input_path.read_text(encoding="utf-8")
)
print(f"validated records={len(batch.records)}")
```

검증 실패 payload는 값을 자동 보정해서 통과시키지 않는다. 원문 payload와
`schema_version`, `dataset_snapshot_id`, `pipeline_run_id`를 유지한 채 오류 원인을
기록하고 A조 재처리/DLQ 절차로 돌려보낸다.

## 10. 검증 범위와 미검증 범위

### 현재 저장소에서 검증한 범위

- Pydantic 2.13.5에서 `by_alias=True` Schema 생성 결과와 저장 파일의 구조적 일치
- 정상 Fixture의 runtime validation
- 오류 Fixture 8건의 deterministic rejection
- source `technology_id` alias와 내부 `tech_id` 변환
- unknown 후보 보존, semantic duplicate 후보와 동일 source 재전달의 구분
- [`AI/tests/test_job_contracts.py`](../../AI/tests/test_job_contracts.py)의 전체 회귀 테스트

### 아직 실제 A조 Dataset으로 확인하지 못한 범위

- 실제 A조 Parquet/JSON field type, null 분포와 partition-to-batch 변환
- production `dataset_snapshot_id`, `pipeline_run_id`, `collector_version` 형식과 수명주기
- 실제 source의 `canonical_job_id`, `technology_mentions`, `requirement_type` 제공 여부
- `raw_artifact_uri`의 실제 위치·권한·checksum 연계
- 대량 Dataset의 batch 크기, 메모리 사용량과 처리 성능
- Kafka/Spark 재전달·Retry·Replay 환경에서의 end-to-end 기술적 멱등성
- 실제 Registry/rule version을 사용한 최종 판정과 수요 집계
- Jenkins에서의 AI contract test 자동 실행

## 11. 관련 자료

- 계약 코드: [`AI/job/contracts.py`](../../AI/job/contracts.py)
- JSON Schema: [`job-analysis-input-v1.schema.json`](contracts/job-analysis-input-v1.schema.json)
- 정상 Fixture: [`job_analysis_input_v1.json`](../../AI/job/fixtures/job_analysis_input_v1.json)
- 오류 Fixture: [`invalid_job_analysis_input_v1.json`](../../AI/job/fixtures/invalid_job_analysis_input_v1.json)
- 기대 Fixture: [`job_analysis_expected_v1.json`](../../AI/job/fixtures/job_analysis_expected_v1.json)
- 회귀 테스트: [`AI/tests/test_job_contracts.py`](../../AI/tests/test_job_contracts.py)
- 데이터 파이프라인 배경: [`docs/data/README.md`](README.md)
- Jira: [S15P21E102-90](https://ssafy.atlassian.net/browse/S15P21E102-90)
