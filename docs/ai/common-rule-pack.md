# 공통 44개 Registry와 Rule Pack

Jira: [S15P21E102-221](https://ssafy.atlassian.net/browse/S15P21E102-221)

C가 고정 기술 44개의 정규화, Rule 의미, 필요한 Fact 추출기와 회귀 fixture를 제공한다.
B는 이 버전을 저장소 분석에 실행하고 개인 귀속 및 여러 저장소 종합을 거쳐
`evidence-consumption-input/v4`를 C에 전달한다. 저장소 수준을 개인 수준으로 복사하지 않는다.

## 버전과 입력

- 현재 callable 범위 Registry: `AI/registry/data/technology_registry_20260911_4.json`, `registry-20260911.4`
- 현재 Rule Pack: `AI/analysis/data/rule_pack_20260911_4.json`, `rule-pack-20260911.4`
- 앞선 공통 44 `.2`와 깊이 확장 `.3` Registry/Rule Pack은 원본 그대로 보존한다. 모든 version pair를 섞지 않는다.
- 기존 `registry-20260911.1`의 47개와 B `registry-20260910.2`의 29개는 수정하지 않는다.
- 새 Registry의 ACTIVE 집합은 44개다. 기존 ID를 삭제하거나 이전 분석 행을 재작성하지 않는다.
- Registry hash는 검증 모델의 canonical JSON SHA-256이다. Rule Pack hash는 최상위
  `content_sha256`만 제외한 원본 JSON을 key 정렬, 공백 없는 UTF-8 JSON으로 직렬화한 SHA-256이다.
  파일 byte hash와 서로 다른 값일 수 있다.

각 기술 profile은 `evaluation_scope`, `required_fact_types`, `max_supported_level`,
`coverage`, `limitations`와 실행 규칙을 함께 갖는다. `max_supported_level`은 구현한
판정의 상한이다. 저장소에서 그 기술을 발견했다는 의미나 개인 귀속의 완료를 뜻하지 않는다.
상한보다 높은 요구 수준은 부족으로 단정할 수 없다. 파일 누락, parser 제한, 불완전한 귀속은
PARTIAL/UNKNOWN으로 전달한다.

Rule은 기존 `analysis.rules.RuleSet`으로 컴파일되어 `analysis.judge.Judge`가 실행한다.
기술 식별은 source-specific Registry mapping이 담당한다. 공통 method 이름을 사용하는
규칙은 필요한 import와 API Fact의 `FILE_PATH`를 결합해 다른 파일의 근거를 빌리지 않는다.
`.3`의 `SYNTAX_NODE`는 지원 grammar의 실제 구조를 기록한다. API/타입/annotation의
`RESOLVED_MODULE`은 import 및 보수적인 정적 바인딩으로 결정하며 변수 이름으로 추정하지 않는다.
`COMPONENT`를 사용하는 규칙은 파일 내 클래스·함수·타입 선언 또는 설정 리소스 범위까지 묶는다.
`.4`의 `FUNCTION`은 호출·구문·annotation을 가장 가까운 callable에 묶는다. Kafka L3는
같은 파일의 서로 다른 method가 신호를 빌려주지 않도록 `FILE_PATH`와 `FUNCTION`을 함께 요구한다.
module-level 호출에는 `FUNCTION`을 만들지 않으므로 callable 범위 Rule의 근거가 되지 않는다.
분석할 수 없는 alias, 동적 생성, 여러 파일에 흩어진 관계는 양성 근거로 합치지 않는다.

## DB 발행과 이전 버전

새 migration `V11_1__common_rule_pack.sql`은 develop의 V11 다음에 적용한다.
깊이 확장에는 이어서 `V11_2__rule_pack_structural_evidence.sql`을 적용한다.
11.2는 구조 Fact 및 binding/predicate 허용 범위만 확장하며 기존 규칙 행을 재작성하지 않는다.
`.4` 발행 전에는 `V11_3__rule_pack_function_scope.sql`을 적용한다. 11.3은 `FUNCTION`
binding을 추가하며 기존 `.2/.3` 규칙 행과 원본 artifact를 변경하지 않는다.
B의 미병합 V12/V13과 번호가 겹치지 않는다. 기존 V7/V9는 그대로 유지한다.
11.1은 Flyway의 [숫자 부분 버전](https://documentation.red-gate.com/fd/versioned-migrations-273973333.html)이다.
이미 V12 이상이 적용된 환경은 적용 순서를 별도 검토해야 한다. 이 작업은 운영 DB에
`outOfOrder`, repair 또는 자동 activation을 수행하지 않는다.

발행은 환경 변수 `REGISTRY_DATABASE_URL`을 설정한 운영자의 명시적 작업이다.
AI 디렉터리에서 실행한다. DSN을 명령행이나 로그에 넣지 않는다.

```powershell
python -m registry.rulepack_db `
  --registry registry/data/technology_registry_20260911_4.json `
  --rule-pack analysis/data/rule_pack_20260911_4.json `
  --repository-root .. `
  --source-ref <reviewed-commit-or-artifact-reference>
```

Registry, Rule Pack 원본, 기술별 지원 범위, 실행용 normalized rule 행을 하나의 트랜잭션에
저장한다. 동일 version/hash/source 재시도는 멱등이고 다른 내용으로 덮어쓰면 실패한다.
규칙 삽입 실패는 Registry 삽입도 rollback한다. 발행만으로 B의 `CURRENT`나 C family alias를
변경하지 않는다. B 요청은 검증한 구체 버전을 명시해야 한다.

`analysis.rules.RegistryStore`가 새 버전을 읽으면 Registry hash, Rule Pack hash,
기술별 지원 범위 및 실제 predicate 행까지 대조한 뒤 같은 Judge 실행 모델을 반환한다.
알 수 없는 버전이나 손상된 발행 데이터는 빈 verdict나 이전 버전으로 대체하지 않고 실패한다.
기존 버전은 기존 DB 규칙 경로로 읽는다.

## B 인수와 결과 계약

`.2`의 SOURCE_FILE/지원 범위는 `repository-analysis-result/v2`,
`.3`과 `.4`의 SYNTAX_NODE/구조 통계는 `repository-analysis-result/v3`로 전달한다.
v3 reader는 정확한 `.3/.3` 또는 `.4/.4` 쌍만 허용하며 교차 조합과 알 수 없는 버전은 거절한다.
각 결과 schema는 엄격하게 검증하며 기존 v1/v2 읽기 경로를 보존한다.
B 서비스의 실제 v3 수신, OAuth와 개인 귀속,
다중 저장소 종합, C 호출 및 사용자 API/FE 연결은 별도 인수 대상이다.

기본 worker는 v1을 유지한다. 새 결과를 활성화하려면
`ANALYSIS_RESULT_SCHEMA_VERSION=repository-analysis-result/v3`와
`KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V3`를 함께 지정한다.
`.2` 요청도 처리할 worker는 `KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V2`를 추가한다.
기존 `KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS`는 v1 대상으로 유지된다.
혼재 요청은 Rule Pack lineage에 따라 v1/v2/v3 publisher로 나눠 보내며 목적지는 서로 달라야 한다.
해당 목적지가 없는 요청은 `UNSUPPORTED_RESULT_SCHEMA` 실패 결과와 DLQ로 마무리한다.
결과 전송이 실패하면 claim을 terminal로 완료하지 않으며 재전달 시 결과를 다시 발행한다.

`AI/tests/fixtures/common44-b-evidence-v4.json`의 두 저장소는 React L2를 보이지만,
fixture 사용자의 수락된 파일은 L1 근거만 가진다. 테스트는 실제 parser/Judge로 두 축을
별도 검증하고 B가 전달한 개인 L1과 상한 L2, PARTIAL 상태를 C가 보존하는지 확인한다.
`AI/tests/fixtures/repository-analysis-result-v1-base-3a4c57c.json`은 clean develop
`3a4c57c`의 기존 모델에서 생성한 고정 v1 결과다.
`common44-depth-b-evidence-v4.json`은 `.3` 실제 Python 구조/호출로 저장소 L3를 얻지만,
수락된 사용자 파일은 L1인 두 저장소 fixture다. 결과 v3 직렬화, 개인 L1/상한 L3/PARTIAL,
C 매칭·추천까지 연결해 확인한다.

Synthetic contract fixture의 개인 귀속은 fixture에 명시된 정답이다.
실제 사용자 검증은 본인의 file/commit/rule/permalink와 personal_level을 사람이 대조해야 한다.
fixture 통과가 실제 개인 귀속이나 운영 E2E 완료를 의미하지 않는다.

## 검증 범위

- 고정 44개 및 C47/B29 diff, source mapping, 이전 immutable snapshot 보존.
- 파일 → Fact → Rule positive/negative/near-miss, 기술 간 오탐, 제외 파일 및 PARTIAL 범위.
- 격리 PostgreSQL에서 원본 V1~V11 → 11.1 → 11.2 → 11.3, 원자적 import/read-back, legacy/unknown version.
- 같은 Registry/Rule version의 repository verdict → synthetic B v4 → C 소비 계약.

Archive `S15P21E102-214`의 HDFS intake/canary와 운영 배포는 이 변경의 검증과 따로 기록한다.
배포한 image, migration, Registry, 실제 B/API/FE 및 실사용자 E2E 확인 전에는 운영 완료로 표시하지 않는다.

## 검출 기준과 trade-off

L3는 각 rule에 명시한 정적 구현 패턴을 확인했다는 뜻이다. 실행 성공, 성능, 운영 경험이나
사용자 개인 숙련도를 입증하지 않는다. 같은 파일의 무관한 API 호출을 합산하는 규칙은
scope/참조 관계를 강화하거나 낮은 수준으로 남긴다. 각 profile의 `limitations`가 인수 범위다.

- 정밀도: 실제 grammar 구조와 import 귀속, 명시적인 scope/리소스 관계, 필요한 조건의 동시 충족을 요구한다.
  주석·문자열·shadowing·generated/vendor/test-only·서로 무관한 선언은 별도 회귀로 배제한다.
- 재현율: wrapper, 동적 dependency injection, 다른 파일의 추상화, 조건부/재할당 alias는 놓칠 수 있다.
  근거가 없을 때 개인 미보유나 수준 부족으로 단정하지 않고 PARTIAL/UNKNOWN을 유지한다.
- 설정: Docker 유효 final stage, Kubernetes 같은 container, Terraform 실제 참조와 활성 리소스를 구분한다.
  복잡한 동적 표현은 정적으로 연결을 확인할 수 있을 때만 높은 수준의 근거로 사용한다.
- 검증 수치: synthetic positive/negative/near-miss의 통과율은 회귀 검증이다.
  다양한 실제 저장소에 대한 모집단 precision/recall 측정으로 제시하지 않는다.

`AI/tests/test_analysis_depth_rule_coverage.py`는 `.2` 대비 변경/추가한 모든 실행 규칙마다
실제 파일에서 발생하는 positive와 전용 near-miss가 있는지 검사한다. 기존 `.2` fixture는
그대로 재실행해 이전 판정을 보존한다. 기술별 최고 수준은 팩의 profile에서 읽어야 하며,
L1/L2/L3별 지원 기술 수는 중복 집계, 최고 수준별 기술 수는 서로 배타적인 집계다.

언어/설정 문법은 공식 문서를 참고하고, L0~L3 수준 판정은 GitJob의 별도 정책으로 정의한다.
Docker의 전역 ARG와 stage 범위는 [Docker 변수 범위 문서](https://docs.docker.com/build/building/variables/#scoping),
Terraform 문자열과 실제 interpolation의 구분은 [Terraform 문자열 문서](https://developer.hashicorp.com/terraform/language/expressions/strings)를 따른다.
Python task 정리 패턴은 [asyncio task 문서](https://docs.python.org/3/library/asyncio-task.html),
TypeScript 조건부/매핑 타입은 [조건부 타입](https://www.typescriptlang.org/docs/handbook/2/conditional-types.html)과
[매핑 타입](https://www.typescriptlang.org/docs/handbook/2/mapped-types.html)을 참고한다.

<!-- DEPTH-COVERAGE-BEGIN -->

## 현재 .3 구현 범위

실행 규칙 145개. 레벨별 지원 기술 수는 L1 44 / L2 36 / L3 27, 최고 수준별로는 L1 8 / L2 9 / L3 27이다.
상한 L1인 C, C++, Go, Kotlin, PHP, SQL, HTML, CSS는 정규화·소스 존재를 지원하며 검증된 구조 깊이 추출기가 남아 있다.
Django와 Redis는 트랜잭션/클라이언트 실행 관계를 증명하는 Fact가 부족해 L3를 발행하지 않았다. 다른 L2 기술도 일반 구현을 넘어서는 강한 패턴의 추가 추출·검증이 필요하다.

| tech_id | L1 | L2 | L3 | 최고 판정 수준 |
|---|:---:|:---:|:---:|:---:|
| c | 지원 | — | — | L1 |
| cpp | 지원 | — | — | L1 |
| csharp | 지원 | 지원 | 지원 | L3 |
| go | 지원 | — | — | L1 |
| java | 지원 | 지원 | 지원 | L3 |
| kotlin | 지원 | — | — | L1 |
| python | 지원 | 지원 | 지원 | L3 |
| javascript | 지원 | 지원 | 지원 | L3 |
| typescript | 지원 | 지원 | 지원 | L3 |
| php | 지원 | — | — | L1 |
| sql | 지원 | — | — | L1 |
| html | 지원 | — | — | L1 |
| css | 지원 | — | — | L1 |
| spring-framework | 지원 | 지원 | — | L2 |
| spring-boot | 지원 | 지원 | 지원 | L3 |
| jpa | 지원 | 지원 | 지원 | L3 |
| mybatis | 지원 | 지원 | — | L2 |
| dotnet | 지원 | 지원 | 지원 | L3 |
| nestjs | 지원 | 지원 | 지원 | L3 |
| django | 지원 | 지원 | — | L2 |
| fastapi | 지원 | 지원 | 지원 | L3 |
| react | 지원 | 지원 | 지원 | L3 |
| nextjs | 지원 | 지원 | 지원 | L3 |
| vuejs | 지원 | 지원 | — | L2 |
| unity | 지원 | 지원 | 지원 | L3 |
| numpy | 지원 | 지원 | — | L2 |
| pandas | 지원 | 지원 | — | L2 |
| scikit-learn | 지원 | 지원 | 지원 | L3 |
| pytorch | 지원 | 지원 | 지원 | L3 |
| tensorflow | 지원 | 지원 | 지원 | L3 |
| apache-spark | 지원 | 지원 | 지원 | L3 |
| hadoop | 지원 | 지원 | 지원 | L3 |
| apache-kafka | 지원 | 지원 | 지원 | L3 |
| mysql | 지원 | 지원 | — | L2 |
| postgresql | 지원 | 지원 | — | L2 |
| mongodb | 지원 | 지원 | 지원 | L3 |
| redis | 지원 | 지원 | — | L2 |
| nodejs | 지원 | 지원 | 지원 | L3 |
| docker | 지원 | 지원 | 지원 | L3 |
| kubernetes | 지원 | 지원 | 지원 | L3 |
| aws | 지원 | 지원 | 지원 | L3 |
| azure | 지원 | 지원 | 지원 | L3 |
| gcp | 지원 | 지원 | 지원 | L3 |
| jenkins | 지원 | 지원 | 지원 | L3 |

Rule Pack canonical hash: `757aca8ce4302dec62b008e4901a97c87ccdb3f4e342283c70f69001c7f15253`.
Registry canonical hash: `eb371d723c3ca12dadcfa2fc7b1ed89e07700ab756b745f88d40da0a7455778d`.

## .4 callable 범위 보정

`.4`는 `.3`의 고정 44개 기술과 실행 규칙 145개, 레벨별 지원 기술 수
L1 44 / L2 36 / L3 27을 그대로 유지한다. 변경된 실행 규칙은
`apache-kafka.l3.transactional-consumer` 하나이며, 같은 파일의 서로 다른 method에서
발생한 신호를 합치지 않도록 binding을 `FILE_PATH` + `FUNCTION`으로 좁혔다.

Registry canonical hash: `da5ae094c58c613c28ffbe8017c0630a1097430584cf700c21672e9525fdee66`.
Rule Pack canonical hash: `832e427affc6c29929e62d5cc77eecb6aae962d3a7a91c8006cdbb99ddac5886`.

이전 `.2`/`.3` artifact는 Git LF blob byte hash로 고정 검증하고, `.3` writer가 만든
고정 result fixture를 `.4` reader에서 읽어 하위 호환성을 확인한다. 격리 PostgreSQL에서는
V11.3 적용 후 `.4` 원자적 import/read-back과 실패 rollback, 기존 `.2`/`.3` row 보존을 확인한다.
