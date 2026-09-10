# 기술 Registry와 Evidence 규칙

저장소 분석이 "이 사람은 Spring Boot를 L1 수준으로 쓴다"고 말할 때, 그 판단이
어디서 나오는지를 담은 테이블들이다. 구조를 기계가 읽을 수 있는 형태로는
[technology-registry-schema.json](technology-registry-schema.json)에 뽑아 두었다.
이 문서는 그것을 왜 그렇게 만들었는지 설명한다.

관련 문서: [분석 Worker](repository-analysis-worker.md) ·
[결과 계약](repository-analysis-result.md) ·
[기술 후보 검토](technology-candidate-review.md)

## 한 장 요약

```
technology_registry          버전 카탈로그 (DRAFT / CURRENT / RETIRED)
  └ technology               그 버전이 아는 기술 29개
      ├ technology_category  직무 도메인 (BACKEND, AI_DATA ...)
      ├ technology_mapping   "무슨 기술인가"  ← prefix·좌표 목록 117개
      └ evidence_rule        "어느 수준인가"  ← 규칙 60개
          └ evidence_rule_clause
              └ evidence_rule_predicate
                  └ evidence_rule_predicate_value
```

**핵심은 매핑과 규칙의 역할 분리다.**

```
fact ──매핑──▶ tech_id ──규칙──▶ L0..L3
```

## 왜 두 단계인가

처음에는 규칙이 직접 패턴을 들고 있었다. Kafka L1 규칙 안에
`org.apache.kafka`, `kafka`, `kafkajs` 같은 경로가 적혀 있었고, 그 목록은
`technology_mapping`에도 똑같이 있었다.

```
technology_mapping    org.apache.kafka  PREFIX(JAVA)  → apache-kafka
evidence_rule_clause  org.apache.kafka  PREFIX(.)     → apache-kafka.l1.import
```

Redis 클라이언트를 하나 추가하려면 두 곳을 고쳐야 했고, **한쪽을 빠뜨려도 아무
오류가 나지 않았다.** 매핑만 고치면 후보 목록에서는 사라지는데 L1이 안 붙고,
규칙만 고치면 그 반대가 된다.

그래서 나눴다. 이제 L1 절은 이렇게만 말한다.

```
fact_type = IMPORT,  fact_field = TECH_ID,  match_operator = EXACT,
expected_value = 'apache-kafka'
```

언어별 분기도 사라졌다. Java·Python·JS 구분은 이미 매핑이 하고 있다.

`TECH_ID`는 원문에 있는 필드가 아니라 **①단계가 붙여 주는 파생 필드**다. 매핑이
겹치면 한 fact가 여러 기술로 해석될 수 있고, 그때는 하나라도 같으면 성립한다.

### L3는 여전히 패턴을 쓴다

```
spring-boot.l3.actuator   MODULE PREFIX(.)  org.springframework.boot.actuate
```

`org.springframework.boot.actuate`는 매핑(`org.springframework.boot`)보다
세밀해서 매핑이 표현할 수 없다. **규칙은 매핑이 못 하는 것만 표현한다**는 것이
지금의 규칙이다.

## 버전은 불변이다

`registry_version`이 콘텐츠 4개 테이블의 **기본키에 들어 있다.**

```sql
PRIMARY KEY (tech_id, registry_version)
PRIMARY KEY (rule_id, registry_version)
```

한 버전의 내용은 바뀌지 않는다. 규칙을 고치려면 새 버전을 발행한다. 이유는
재현성이다 — 분석 요청 이벤트에 `registry_version`이 박혀 있어서, 반년 뒤에도
"이 Evidence는 어느 규칙으로 나왔나"를 되짚을 수 있어야 한다.

```
registry-20260908.1   RETIRED    ← 지난 버전. 행은 그대로 남는다
registry-20260910.1   CURRENT    ← 새 분석 요청이 쓴다. 항상 정확히 하나
(DRAFT)                          ← 관리자가 후보를 승격해 쌓는 중
```

`CURRENT`가 하나뿐인 것은 부분 유니크 인덱스가 강제한다. 둘이면 요청마다 다른
규칙으로 판정되는데, 그 차이는 결과를 비교하기 전까지 드러나지 않는다.

BE는 `technology_registry`에서 `CURRENT`를 읽어 요청 이벤트에 넣는다
(`CurrentRegistryVersion`). 예전에는 설정값이었고 기본값이 `schema_version`인
`technology-registry/v1`이었다 — 실재하지 않는 버전이라 그 값으로 규칙을
조회하면 0행이 나오고, **0행은 "매칭된 기술 없음"과 구분되지 않는다.**

## `technology_mapping` — 무슨 기술인가

| mapping_type | 쓰는 쪽 | ecosystem |
| --- | --- | --- |
| `IMPORT_PATH` | 저장소 분석 (소스 import) | `JAVA` `PYTHON` `JAVASCRIPT` `DOTNET` |
| `PACKAGE` | 저장소 분석 (매니페스트) | `MAVEN` `NPM` `PYPI` `NUGET` |
| `ALIAS` `STACKOVERFLOW_TAG` `GITHUB_LANGUAGE` | C조 채용 수요·트렌드 | NULL |

### PREFIX의 경계는 생태계마다 다르다

이게 가장 자주 틀리는 부분이다.

| 생태계 | 구조 | 경계 | PREFIX |
| --- | --- | --- | --- |
| `MAVEN` | `group:artifact` 계층적 | `.` `:` `-` | 쓴다 |
| `NUGET` | dotted id 계층적 | `.` | 쓴다 |
| `JAVA` `PYTHON` `DOTNET` (import) | dotted | `.` | 쓴다 |
| `JAVASCRIPT` (import) | 경로 | `/` | 쓴다 |
| `NPM` | 스코프만 계층 | `/` | 스코프에만 |
| `PYPI` | 평평 | (없음) | **못 쓴다** |

경계가 필요한 이유는 `org.springframework`가 `org.springframeworkfoo`에 걸리면
안 되기 때문이다.

npm과 PyPI에서 `-`를 경계로 삼으면 안 된다. `react`가 `react-dom`·`react-router`를,
`kafka`가 `kafka-python`을 삼킨다. **전부 별개 패키지이고 이 레지스트리에서도
별개 기술이다.** PyPI에는 경계가 아예 없으므로 PREFIX를 쓸 수 없고,
`package_has_prefix`가 조용히 `False`를 주는 대신 **예외를 던진다** — 매칭되지
않는 매핑은 "아무도 안 쓰는 기술"과 구분되지 않기 때문이다.

효과는 실측된다. spring-petclinic의 MAVEN 의존성 31개 중 `spring-boot`로
해석되는 것이 `EXACT` 한 줄로는 1개, `PREFIX`로는 14개다.

### 한 fact가 여러 기술로 해석될 수 있다

```
org.springframework.boot:spring-boot-starter-data-jpa
  → spring-boot       (PREFIX)
  → spring-data-jpa   (EXACT)
```

**우선순위를 두지 않는다.** 둘 다 참이기 때문이다 — 그 의존성은 Spring Boot를
쓴다는 증거이자 Spring Data JPA를 쓴다는 증거다. 더 구체적인 것 하나만 남기면
성립하는 사실 하나를 버리게 된다.

## `evidence_rule` — 어느 수준인가

```
predicate_value  ──OR──▶  predicate  ──AND──▶  clause  ──AND──▶  group  ──OR──▶  rule
   기대값 여러 개            필드 여러 개      min_match_count      대안
```

- **술어** — fact의 `fact_field` 값이 기대값 중 **하나라도** `match_operator`로 맞으면 참
- **절** — 그 절의 **모든** 술어를 만족하는 fact가 `min_match_count`개 이상
- **그룹** — 같은 `group_no`의 `REQUIRED` 절을 **전부** 만족
- **규칙** — 그룹이 **하나라도** 성립

`group_no`가 대안을 가른다. 같은 번호끼리 AND, 다른 번호끼리 OR다.

한 기술이 여러 규칙을 만족하면 최종 레벨은 **가장 높은 `rule_type`**이고, 동률은
`priority`로 가른다.

### 레벨의 뜻

| | |
| --- | --- |
| `L0` | 발견 — 의존성 선언 |
| `L1` | 적용 — import·설정·annotation |
| `L2` | 활용 — 핵심 API 호출·본인 기여 |
| `L3` | 심화 — 운영 성숙도 |

`L0`과 `L1`을 가르는 것은 `fact_type`뿐이다. `DEPENDENCY`면 선언, `IMPORT`면
사용. spring-petclinic에서 `postgresql`·`mysql`이 **L0만** 나오는 것이 그
예다 — JDBC 드라이버라 매니페스트에만 있고 소스 import에는 전혀 없다.

### 지금 만들 수 없는 규칙

**`evaluation_scope = PERSONAL`** — 본인 기여 판정에는 commit author와 라인
대조가 필요한데, worker가 `--depth 1`로 clone하므로 히스토리가 없다. 평가하지
않고 `skipped_rule_ids`로 보고한다. 조용히 빠지면 구현 안 된 레벨과 충족 안 된
레벨이 같아 보인다.

**`fact_type` 중 `ANNOTATION`·`CONFIG_KEY`·`API_CALL`** — 추출기가 아직 없다.
그 fact_type을 쓰는 규칙을 넣으면 영원히 매칭되지 않는다.

## 어휘는 CHECK로 강제된다

`rule_type`·`evaluation_scope`·`role`·`fact_type`·`fact_field`·`match_operator`가
V6부터 CHECK 제약이다. 그 전에는 varchar에 주석뿐이라 오타가 INSERT를 통과한 뒤
**"매칭되지 않는 규칙"으로만 나타났는데, 그건 기술을 쓰지 않는 저장소와
구분되지 않는다.**

아직 CHECK가 없는 것: `mapping_type`, `ecosystem`, `match_mode`, `job_domain`,
각 테이블의 `status`. 앞의 셋은 공유 계약
(`docs/data/contracts/technology-registry-v1.schema.json`)의 enum과 같은 어휘라
그쪽과 함께 정해야 한다.

## 규칙을 손으로 다 적지 않는다

기술 29개에 L0·L1이 각각 있으면 규칙 58개다. **V6가 규칙에서 패턴을 걷어낸
뒤로 모든 기술의 L0·L1은 모양이 같다** — "이 fact가 이 기술로 해석되면 성립".
그래서 V7은 매핑에서 SQL로 생성한다.

```sql
INSERT INTO evidence_rule (...)
SELECT DISTINCT m.tech_id || '.l1.import', m.tech_id, ..., 'L1', ...
FROM technology_mapping m
JOIN technology t ON ...
WHERE m.registry_version = '...' AND m.mapping_type = 'IMPORT_PATH';
```

손으로 적으면 오타가 나고, 매핑을 추가할 때 규칙을 빠뜨린다. **매핑이 없는
종류의 규칙은 만들지 않는다** — 없는 fact를 기다리는 규칙은 영원히 매칭되지
않으면서 "이 기술을 안 쓴다"처럼 보인다.

L3 둘만 손으로 쓴다. 그것들만 매핑이 표현할 수 없는 것을 표현하기 때문이다.

## 새 버전을 발행하는 법

마이그레이션 한 파일이 버전 하나를 발행한다. V7이 그 예다.

```
1. technology_registry 에 DRAFT 로 INSERT
2. technology / technology_category / technology_mapping 채우기
3. L0·L1 규칙을 매핑에서 생성, L3 는 손으로
4. 이전 CURRENT → RETIRED,  DRAFT → CURRENT + published_at
5. 발행 결과가 비어 있지 않은지 확인 (RAISE)
```

5번이 필요한 이유는, 빈 버전을 `CURRENT`로 올리면 **모든 저장소가 "아무 기술도
안 쓴다"로 나오기** 때문이다. 정상 결과와 구분되지 않는다.

기존 버전을 고치는 것은 원칙 위반이다. V6가 한 번 그렇게 했는데, 그 버전으로
판정된 분석이 하나도 없다는 전제가 있었고 마이그레이션 첫 블록이
`analysis_evidence`를 확인해 그 전제를 스스로 강제한다.

## 코드 어디를 보면 되나

| | |
| --- | --- |
| 레지스트리 로딩 | `AI/analysis/rules.py` |
| 해석·평가 | `AI/analysis/judge.py` |
| PREFIX 경계 | `AI/registry/normalization.py` |
| 평가 의미론 테스트 | `AI/tests/test_analysis_judge.py` |
| 현재 버전 조회 (BE) | `BE/.../analysis/service/CurrentRegistryVersion.java` |
| 스키마 | `BE/src/main/resources/db/migration/V1,V3~V8` |

`test_analysis_judge.py`가 규칙 집합을 값으로 직접 지어 평가 의미론을 고정한다.
group·role·min_match_count·경계 규칙이 그동안 마이그레이션 주석에만 있었는데,
거기서 처음으로 실행 가능한 명세가 됐다.

## 지금 들어 있는 것

```
registry-20260910.1  (CURRENT)
  기술 29개    직무 도메인별(중복 포함): BACKEND 21 · AI_DATA 12 · FRONTEND 6 · INFRASTRUCTURE 5
  매핑 117개   IMPORT_PATH 51 · PACKAGE 66
  규칙 60개    L0 29 · L1 29 · L3 2
```

spring-petclinic을 판정하면 기술 7개(`spring-boot` L1, `spring-data-jpa` L1,
`testcontainers` L1, `junit` L1, `mockito` L1, `postgresql` L0, `mysql` L0)와
Evidence 97건, 후보 10개가 나온다.
