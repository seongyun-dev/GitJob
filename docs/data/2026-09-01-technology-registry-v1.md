# Technology Registry v1 계약

> Jira: `S15P21E102-80`
>
> 상태: 초기 계약·Seed
>
> Registry version: `registry-20260901.1`

## 1. 목적과 책임 경계

Technology Registry는 GitJob 분석 결과가 공통으로 조인할 승인된 canonical 기술과 출처별 표현을 제공한다. 분석 결과에는 표시명 대신 `tech_id`와 판정에 사용한 `registry_version`을 저장한다.

이 계약은 승인된 Registry만 다룬다.

- `S15P21E102-80`: canonical technology, mapping, 정규화, 버전 계약
- `S15P21E102-81`: 입력 후보를 Registry에 조회해 `MATCHED`, `AMBIGUOUS`, `UNKNOWN`으로 판정
- `S15P21E102-82`: 채용공고 후보를 `REQUIRED`, `PREFERRED`, `SKILL`, `REVIEW_REQUIRED`로 분류
- `S15P21E102-88`: 미등록·모호 후보와 원문 Evidence를 별도 review storage에 보존
- `S15P21E102-143`: Registry 배포 승인과 Dataset Replay 운영 정책

따라서 Registry Seed에는 `REVIEW_REQUIRED`나 미승인 후보를 넣지 않는다. `display_name`은 화면 표시 전용이며 조회 입력이나 조인 key로 사용하지 않는다.

## 2. 구현 Artifact

- [Pydantic 계약](../../AI/registry/contracts.py)
- [정규화 규칙](../../AI/registry/normalization.py)
- [초기 Seed](../../AI/registry/data/technology_registry_v1.json)
- [JSON Schema](contracts/technology-registry-v1.schema.json)

Schema는 `TechnologyRegistry.model_json_schema()`의 결과와 테스트에서 JSON 구조가 완전히 일치해야 한다. JSON Schema는 필드·enum·형식 같은 구조 검증용이며, ACTIVE mapping 보유와 정규화 충돌 같은 배열 간 규칙은 Pydantic `TechnologyRegistry` 로딩을 최종 기준으로 검증한다.

## 3. 최상위 계약

```json
{
  "schema_version": "technology-registry/v1",
  "registry_version": "registry-20260901.1",
  "technologies": [],
  "mappings": []
}
```

| 필드 | 규칙 |
|---|---|
| `schema_version` | 구조 버전. v1은 `technology-registry/v1` 고정 |
| `registry_version` | 내용 Snapshot 버전. ASCII 실제 달력 날짜를 사용한 `registry-YYYYMMDD.N` 형식이며 발행 후 불변 |
| `technologies` | 승인된 canonical technology 배열 |
| `mappings` | 특정 입력 surface에 한정된 승인 mapping 배열 |

같은 Registry 내용을 수정해서 과거 결과를 덮어쓰지 않는다. mapping/category/status가 바뀌면 새 `registry_version`을 발행하고 각 소비 결과에 사용한 버전을 기록한다. 배포 승인과 Dataset Replay 여부·범위는 `S15P21E102-143`의 운영 정책에서 결정한다.

## 4. Canonical technology

| 필드 | 규칙 |
|---|---|
| `tech_id` | 영구 canonical key. 소문자 kebab-case, 최대 80자 |
| `display_name` | 표시 전용 이름. 조회하지 않음 |
| `categories` | 직무 도메인 다중값 |
| `status` | `ACTIVE` 또는 `DEPRECATED` |
| `provenance_refs` | mapping·canonical 판단에 사용한 저장소 상대 파일 또는 절대 HTTPS 원문 1개 이상 |

직무 도메인은 `BACKEND`, `FRONTEND`, `AI_DATA`, `INFRASTRUCTURE`, `MOBILE`이다. `DATABASE`는 직무 도메인이 아니므로 별도 category로 두지 않는다. ACTIVE 기술은 category가 하나 이상이어야 하고 DEPRECATED 기술은 빈 배열을 허용한다.

초기 다중 분류의 기준 예시는 다음과 같다.

- Python: `BACKEND`, `AI_DATA`
- PostgreSQL: `BACKEND`, `AI_DATA`, `INFRASTRUCTURE`
- React: `FRONTEND`
- .NET MAUI: `MOBILE`

## 5. Source-qualified mapping

| `mapping_type` | `ecosystem` | 허용 match mode | 용도 |
|---|---|---|---|
| `ALIAS` | `null` | `EXACT` | 검토·승인된 일반 텍스트 표현 |
| `PACKAGE` | `NPM`, `PYPI`, `MAVEN`, `NUGET` | `EXACT` | package registry 식별자 |
| `IMPORT_PATH` | `JAVASCRIPT`, `PYTHON`, `JAVA`, `DOTNET` | `EXACT`, `PREFIX` | import/module namespace |
| `STACKOVERFLOW_TAG` | `null` | `EXACT` | Stack Overflow tag |
| `GITHUB_LANGUAGE` | `null` | `EXACT` | GitHub Linguist language name |

package ecosystem과 import ecosystem은 의미가 다르다. 예를 들어 NuGet package `Microsoft.Maui.Controls`와 .NET namespace `Microsoft.Maui`는 각각 `PACKAGE/NUGET`, `IMPORT_PATH/DOTNET`으로 저장한다.

모든 mapping은 존재하는 `tech_id`를 참조한다. ACTIVE mapping은 ACTIVE technology만 참조할 수 있고, 모든 ACTIVE technology에는 ACTIVE mapping이 하나 이상 있어야 한다.

로컬 provenance는 `AI/`, `BE/`, `FE/`, `Infra/`, `docs/` 아래의 repository-relative 파일이어야 하며 `..`, 역슬래시, 빈 fragment를 허용하지 않는다. 외부 provenance는 hostname과 source path가 있는 절대 HTTPS URL이어야 한다. Seed 검증·CI에서는 `load_registry(..., repository_root=...)`로 로컬 파일 존재와 fragment의 실제 관측값을 모두 검증한다. 이 source 검증은 Registry 배포 승인을 뜻하지 않으며, 승인 manifest·artifact hash·배포 및 Replay 정책은 `S15P21E102-143`이 담당한다. 원본 source가 없는 런타임은 승인된 artifact를 `TechnologyRegistry.model_validate_json()`으로 구조 검증할 수 있지만, 그 호출 자체가 승인 상태를 만들지는 않는다.

## 6. 정규화와 충돌

모든 값은 Unicode NFKC와 앞뒤 공백 제거를 먼저 적용한다.

| Surface | 비교값 정규화 |
|---|---|
| Alias | 내부 공백 축약, Unicode casefold, 문장부호 보존 |
| Stack Overflow tag | lowercase, 문장부호 보존 |
| GitHub language | Unicode casefold |
| npm package | lowercase |
| PyPI package | lowercase 후 `-`, `_`, `.` 연속 구분자를 `-`로 축약 |
| Maven package | `group:artifact` 구조 검증, 대소문자 보존 |
| NuGet package | Unicode casefold |
| Import path | NFKC/trim, namespace 대소문자 보존 |

Registry 안의 유일성 key는 다음 세 값이다.

```text
(mapping_type, ecosystem, normalized_value)
```

`match_mode`는 충돌 key가 아니다. 같은 normalized value를 `EXACT`와 `PREFIX`로 나눠 서로 다른 technology에 배정할 수 없다.

## 7. Import prefix 경계

PREFIX는 `IMPORT_PATH`에서만 허용하며 문자열 시작 일치가 아니라 segment 경계를 사용한다.

저장된 import path에는 선행·후행 delimiter나 비어 있거나 공백뿐인 segment를 허용하지 않는다. 따라서 `react/`, `/react`, `org.foo.`, `org..foo`, `org. .foo`는 Registry 로딩 단계에서 거부한다.

| Ecosystem | delimiter | 일치 | 불일치 |
|---|---|---|---|
| JavaScript | `/` | `react` → `react/jsx-runtime` | `react` → `react-dom` |
| Python | `.` | `pydantic` → `pydantic.fields` | `pydantic` → `pydantic_core` |
| Java | `.` | `org.foo` → `org.foo.bar` | `org.foo` → `org.foobar` |
| .NET | `.` | `Microsoft.Maui` → `Microsoft.Maui.Controls` | `Microsoft.Maui` → `Microsoft.MauiX` |

## 8. 짧고 모호한 기술명

`C`, `R`, `Go` canonical technology는 Registry에 존재하지만 정규화 결과가 `c`, `r`, `go`인 `ALIAS`는 계약 validator가 거부한다. 대신 `GITHUB_LANGUAGE`처럼 입력 source가 확정된 mapping만 둔다. 채용공고 자유 텍스트에서 이 문자열을 기술로 확정할지는 `S15P21E102-81`의 문맥 판정과 `S15P21E102-88` review queue가 담당한다.

## 9. 로딩 예시

저장소의 `AI` 디렉터리에서 실행한다. JSON snapshot은 strict 계약의 `model_validate_json()` 경로로 로딩하며, Python 객체를 직접 검증할 때도 bytes 같은 암묵 변환을 허용하지 않는다.

```python
from pathlib import Path

from registry.contracts import load_registry

registry = load_registry(
    Path("registry/data/technology_registry_v1.json"),
    repository_root=Path(".."),
)
print(registry.registry_version)
```

계약·Seed 검증 명령:

```powershell
python -m pytest tests/test_registry_contracts.py tests/test_registry_seed.py -q
python -m ruff check registry tests/test_registry_contracts.py tests/test_registry_seed.py
python -m ruff format --check registry tests/test_registry_contracts.py tests/test_registry_seed.py
```
