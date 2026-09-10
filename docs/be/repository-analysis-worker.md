# 저장소 분석 Worker

Kafka로 들어온 분석 요청을 받아 요청된 commit을 로컬 디스크에 내려받는다.
앞단은 [저장소 선택·분석 요청](repository-analysis-request.md), 그 앞은
[Outbox·CDC 발행](analysis-outbox.md)이다. 이 문서는 그 뒤를 다룬다.

현재 범위는 **clone과 import 추출까지**다. 추출한 import를 기술로 매핑하고
Evidence로 저장하는 단계는 아직 없다.

## 위치

`AI/analysis/`. `AI/` 안의 다른 것들과 목적이 다르다.

| 모듈 | 무엇 |
| --- | --- |
| `AI/analysis/` | **이 문서.** 로그인 사용자의 저장소 하나를 특정 commit에서 내려받는다 |
| `AI/worker/` | C조 compute HTTP API (채용 수요·추천). 소스 첫 줄이 "Internal C compute API" |
| `AI/github/` | 공개 저장소를 대량 수집해 Registry를 만든다. GitHub REST API 기반 |
| `AI/collector/`, `AI/job/` | 채용공고 수집 |

같은 이미지를 `command`만 바꿔 쓰는 기존 방식(`collector` / `worker`)을 그대로 따라
`python -m analysis`로 뜬다. HTTP 서비스와 consumer는 실패·재시작·확장 특성이 달라
같은 프로세스에 넣지 않았다.

## 흐름

```
gitjob.repository-analysis.requests.v1
        |
   poll (max_poll_records=1)
        |
   파싱 --------------------------> 실패 시 DLQ + offset 커밋
        |
   선점(claim)
        |-- BUSY ----------------> consumer 종료, offset 커밋 안 함
        |-- CLONED/FAILED -------> offset 커밋하고 다음
        |
   git fetch --depth 1 <sha>
        |-- 일시 실패 -----------> 예산 남으면 선점 반납, offset 커밋 안 함 (재배달)
        |                          예산 소진이면 FAILED + DLQ + 커밋
        |-- 영구 실패 -----------> FAILED 기록 + DLQ + offset 커밋
        |
   tree-sitter 파싱 (import 추출)
        |
   CLONED 기록
        |
   작업 디렉터리 삭제 (finally)
        |
   offset 커밋
```

### 순서가 곧 정확성이다

세 가지가 이 파일의 correctness를 지탱한다.

**offset 커밋이 맨 마지막이다.** 작업 전에 커밋하면 처리 도중 죽은 메시지가 사라진다.

**재시도로 고쳐지지 않는 실패도 커밋한다.** 커밋하지 않으면 그 메시지 하나가 파티션을
영원히 막는다. DLQ로 보내 눈에 보이게 하는 편이 낫다.

**작업 디렉터리 삭제는 `finally`다.** 실패한 job이 clone을 남기면 디스크가 차고,
그 다음 실패는 원인과 무관한 얼굴로 나타난다.

## 중복 처리 방지

요청 토픽은 Debezium이 채우므로 at-least-once이고, 운영 문서는 이벤트를 손으로
재발행하라고 안내한다. **같은 `event_id`가 두 번 오는 것은 설계상 정상**이다.

`repo_analysis.event_claim` 테이블이 `event_id` 단위로 선점한다.

| 상황 | 결과 |
| --- | --- |
| 첫 도착 | 선점 성공, 진행 |
| 다른 worker의 lease가 유효한 같은 이벤트 | BUSY, 커밋하지 않고 consumer 종료 |
| 성공(`CLONED`) 후 재배달 | skip |
| 영구 실패(`FAILED`) 후 재배달 | skip (무한 재처리 방지) |
| 일시 실패로 반납한 뒤 | 행은 남고 lease만 만료된다. 다음 배달이 인수하면서 `attempt`가 1 늘어난다 |
| 재시도 예산(5회)을 다 쓴 뒤 | `FAILED` + DLQ + 커밋. 더는 재배달하지 않는다 |
| worker가 clone 중 죽은 뒤 | 유효기간이 지나면 다른 worker가 인수 |

BUSY에서 다음 메시지를 poll하면 나중 offset의 commit이 앞선 미완료 요청까지
건너뛸 수 있다. 따라서 BUSY는 정상 skip이 아니라 프로세스 종료 신호다. Compose의
`restart: unless-stopped`가 consumer를 다시 시작하고, 커밋되지 않은 offset을 같은
consumer group에서 재배달한다.

### 왜 `analysis_job.status`가 아닌가

`analysis_job`은 Spring 서비스의 것이다. 매핑된 JPA 엔티티이고 배포가
`ddl-auto=validate`로 뜨며 상태 어휘의 주인도 B다. 다른 언어의 두 번째 writer가
생기면 컬럼 변경이 매번 두 저장소 마이그레이션이 된다.

C조가 `c_compute` 스키마를 갖는 것과 같은 방식으로 worker도 자기 스키마를 갖는다.
Job 상태는 나중에 결과 토픽으로 되돌려 **B가 자기 테이블의 유일한 writer로 남는다.**

### 왜 선점을 인수할 수 있어야 하나

clone 도중 죽은 worker는 `CLONING` 행을 남기고, 그걸 끝낼 사람은 없다. 인수 규칙이
없으면 그 이벤트는 영원히 멈춘다. 그래서 선점은 사실이 아니라 **유효기간(lease)** 이다.
`ANALYSIS_CLAIM_LEASE_SECONDS`가 지난 `CLONING` 행은 다른 worker가 가져간다.

`attempt`는 lease를 인수할 때마다 증가하는 fencing token이다. `release`와 terminal
`finish`는 자신이 받은 attempt가 현재 행과 일치할 때만 상태를 바꾼다. 만료 후 이전
worker가 늦게 돌아와도 새 owner의 lease를 반납하거나 완료로 덮어쓸 수 없다. 체크아웃
디렉터리도 analysis ID, event ID digest, attempt를 조합해 owner별로 분리한다.
생성·정리 직전에는 해석된 경로가 작업 루트의 실제 하위인지 다시 확인하고,
symbolic link와 Windows junction을 거쳐 다른 작업 디렉터리로 가는 경로도 거절한다.

**이 값은 가장 느린 clone보다 커야 한다.** 작으면 두 worker가 같은 저장소를 동시에
내려받는다.

## clone은 브랜치가 아니라 SHA로

```bash
git init
git remote add origin https://github.com/<owner>/<repo>.git
git fetch --depth 1 origin <commit_sha>
git checkout FETCH_HEAD
```

계약이 *"the worker must still analyze `commitSha`"* 라고 못박고 있고, 요청과 이 시점
사이에 브랜치는 대개 이미 움직였다. 브랜치를 clone하고 SHA가 아직 닿기를 바라는 것은
경합이다. SHA를 직접 fetch하면 GitHub이 주거나 없거나 둘 중 하나다.

`--depth 1`은 그 커밋의 트리만 받는다. 기여 분석에는 히스토리가 필요해지는데, 그건
다른 방식이 아니라 더 큰 `--depth`다.

## 파싱 — tree-sitter

clone이 끝나면 같은 선점 안에서 바로 파싱한다. 체크아웃은 아래 `finally`까지만
존재하므로 나중에 이어서 할 자리가 없다.

### 왜 tree-sitter인가

`github/public_analysis.py`가 이미 정규식으로 import를 뽑고 있고 동작한다. 다만
그 대가로 JavaScript의 문자열·주석·템플릿 리터럴을 손으로 마스킹하고, Java text
block 전용 스캐너를 따로 두고 있다. 전부 문법 규칙을 정규식으로 재구현한 것이다.
파서는 주석이 어디서 끝나는지 이미 알기 때문에 그런 코드가 필요 없다.

두 번째 이유는 위치다. Evidence는 파일과 라인을 지목해야 하는데
(`docs/be/README.md` 8절) 파스 트리는 그걸 공짜로 준다.

### 대상 언어

| 언어 | 확장자 | ecosystem |
| --- | --- | --- |
| Python | `.py` `.pyi` | `PYTHON` |
| Java | `.java` | `JAVA` |
| JavaScript | `.js` `.jsx` `.mjs` `.cjs` | `JAVASCRIPT` |
| TypeScript | `.ts` `.mts` `.cts` `.tsx` | `JAVASCRIPT` |
| C# | `.cs` | `DOTNET` |

`ecosystem`은 technology-registry 계약의 `ImportEcosystem`과 같은 값이라, 추출한
import를 registry의 `IMPORT_PATH` 매핑에 바로 넘길 수 있다. TypeScript는 문법은
다르지만 패키지 생태계가 npm으로 같아 `JAVASCRIPT`로 묶었다.

### 무엇을 세지 않는가

- **상대 import** — `from .models import X`, `import './styles.css'`는 분석 대상
  저장소 안을 가리킨다. 기술 신호가 아니다
- **의존성·빌드 산출물 디렉터리** — `node_modules`, `target`, `build`, `dist`,
  `.venv`, `vendor`, `obj` 등. 남의 코드의 import를 세면 전이 의존성 전부가
  "이 사람이 쓴 기술"이 된다
- **번들·최소화 파일** — `*.min.js`, `*.bundle.js`, `*.d.ts`
- **주석·문자열 안의 import** — 파서가 알아서 구분한다

`require()`는 한 개의 문자열 인자를 받는 다른 모든 호출(`t('key')`,
`describe('x')`)과 형태가 같다. 그래서 호출 대상 이름을 함께 캡처해 비교한다.
쿼리 `matches()`를 쓰는 이유가 이것이다. `captures()`는 그 짝을 잃어버린다.

### 한계를 두는 것들

분석 대상은 인터넷에서 받아온 임의의 내용이다. 생성된 파일 하나가 수십 MB일 수
있고, `.gitignore` 실수로 살아남은 `node_modules`가 십만 개 파일을 담을 수 있다.

| 항목 | 기본값 | 환경변수 |
| --- | --- | --- |
| 파일 하나 크기 | 1 MiB | `ANALYSIS_MAX_FILE_BYTES` |
| 파일 개수 | 50,000 | `ANALYSIS_MAX_FILES` |
| import 개수 | 200,000 | (고정) |

한계에 걸린 파일은 예외가 아니라 기록으로 남는다. 일부를 못 읽는 저장소도 나머지
에서는 쓸 만한 증거가 나오기 때문이다. 이유별 건수는 로그의 `skipped=`에 찍힌다.

바이너리(널 바이트), 심볼릭 링크, 읽기 실패도 같은 방식으로 건너뛴다. 한 파일의
문법 오류가 저장소 전체를 실패시키지 않는다 — tree-sitter는 오류에서 복구하고
읽을 수 있는 부분을 돌려준다.

`occurrence_limit`에 걸린 파일은 `files_skipped`에 세지 않는다. 파싱에는 성공했으므로
한 파일이 parsed와 skipped 양쪽에 잡히면 숫자가 거짓말이 된다.

문법 로딩은 파일별이 아니라 **기동 시 한 번** 검증한다. 파일별로 잡으면 wheel이 빠졌을 때
모든 파일이 `parse_error`가 되고 "import 0건"으로 끝나는데, 그건 파싱할 것이 없는
저장소와 구분되지 않는다.

### 경로가 되는 값

`analysis_id`는 작업 디렉터리 이름이 된다. `Path("/tmp/work") / "/etc"`는 `/etc`라서,
값 하나가 `mkdir`과 `rmtree`를 작업 루트 밖으로 보낸다. 두 겹으로 막는다.

- 이벤트 계약이 모든 식별자를 `^[A-Za-z0-9_-]{1,80}$`로 좁힌다. `trace_id`도 같은 규칙이라
  로그에 개행을 심을 수 없다
- `RepositoryCloner`가 체크아웃 경로를 만들 때마다 상대경로·심볼릭 링크·junction을 거치지
  않는지 확인하고 `resolve()` 후 작업 루트 안인지 다시 본다. `fetch()`와 `cleanup()`이
  같은 검사를 공유해, 쓰는 경로와 지우는 경로가 갈라지지 않는다

발행자를 믿지 않는 것이 이 계약의 존재 이유인데, 하필 경로가 되는 필드에만 형식 검증이
없었다.

## 의존성 — 매니페스트

파싱이 **코드가 무엇을 건드리는지**를 말한다면, 매니페스트는 **프로젝트가 무엇에
의존하기로 했는지**를 말한다. 둘 다 fact가 되지만 답하는 질문이 다르다.

### 왜 후보 발굴은 import가 아니라 여기인가

매칭되지 않은 import는 기술이 아니라 클래스 경로다. `org.junit.jupiter.api.Test`를
후보로 등록하는 것은 쓸모가 없고, 패키지로 자르려면 존재하지 않는 깊이가 필요하다.

```
org.springframework.web          3세그먼트
org.springframework.data.redis   4세그먼트   ← 고정 깊이로는 못 가른다
jakarta.persistence              2세그먼트
```

매니페스트 항목은 이미 관리자가 승격할 단위다. 게다가 **소스가 절대 언급하지 않는
것**을 본다. spring-petclinic에서 `postgresql`, `h2`, `caffeine`,
`mysql-connector-j`는 드라이버·캐시 구현이라 런타임에만 쓰이고 import에 등장하지
않는다. 매니페스트가 아니면 영영 못 찾는다.

### 버전은 버린다

`jjwt-api:0.12.6`과 `0.12.7`은 하나의 의존성이다. 버전을 남기면 릴리스마다 카운트가
갈라진다.

버리기로 하면 Gradle 읽기의 제일 성가신 부분도 같이 사라진다.

```gradle
runtimeOnly "org.webjars:webjars-locator-lite:${webjarsLocatorLiteVersion}"
             └──────── 리터럴로 그대로 읽힌다 ────────┘ └─ 어차피 버림 ─┘
```

변수 보간은 **버전 자리에만** 나타나므로, group:artifact는 정적 읽기로 온전히 나온다.

### 빌드를 실행하지 않는다

`gradle dependencies`, `npm install`, `mvn dependency:list`는 전부 원격 코드
실행이다. 인터넷에서 받아온 임의 저장소의 파일이고, `build.gradle`은 선언이 아니라
프로그램이다. Gradle 버전 카탈로그를 Gradle로 해석하지 않고 TOML을 직접 읽는 이유도
같다.

### 대상

| 파일 | 생태계 | 비고 |
| --- | --- | --- |
| `package.json` | `NPM` | dependencies·dev·peer·optional |
| `build.gradle`, `build.gradle.kts` | `MAVEN` | 문자열 리터럴 + `libs.*` 카탈로그 참조 |
| `gradle/libs.versions.toml` | — | 별칭 → 좌표. 카탈로그 항목만으로는 의존성이 아니다 |
| `pom.xml` | `MAVEN` | `dependencyManagement`는 제외 |
| `requirements*.txt`, `pyproject.toml` | `PYPI` | PEP 503 정규화 |
| `*.csproj`, `Directory.Packages.props` | `NUGET` | 소문자 |

`node_modules`를 비롯한 제외 디렉터리는 파싱과 같은 목록을 쓴다. 커밋된
`node_modules` 하나가 수천 개의 남의 의존성을 만들어낸다.

### 자기 자신은 뺀다

모노레포에서는 매니페스트에도 자기 코드가 들어간다. import 쪽과 달리 **명시적
신호**가 있어 추측이 필요 없다.

```
package.json    "workspace:*"  "file:../core"  "link:"  "portal:"
build.gradle    project(':core')
requirements    -e .   -r other.txt   ./libs/internal
pom.xml         ${project.groupId}    ← 유효 POM이 필요하다. Maven 실행은 금지
```

### scope를 지금 담는 이유

`testImplementation`인지 `implementation`인지는 나중에 "프로덕션에서 쓴다"와
"테스트에서만 쓴다"를 가를 때 필요하다. 그때 담기 시작하면 이미 분석한 저장소를
전부 다시 clone해야 한다.

### 줄 번호

L0 판정은 `build.gradle:16`을 가리켜야 하지, 사실만 주장해서는 안 된다. 그런데
`json`·`tomllib`·`ElementTree`는 전부 위치를 버린다. 그래서 구조적으로 파싱한 뒤
원문에서 값을 다시 찾는다.

**섹션 안에서 찾아야 한다.** 이 저장소의 `FE/package.json`이 그 예다.

```json
"scripts":         { "lint": "oxlint" },      ← 파일 전체 검색은 여기를 잡는다
"devDependencies": { "oxlint": "^1.79.0" }    ← 실제 선언
```


## 판정 모델 — 매핑과 규칙

`analysis/rules.py`가 레지스트리 한 버전을 읽고, `analysis/judge.py`가 fact를
해석해 규칙을 평가한다.
반영한 것이다.

```
매핑   technology_mapping   "무슨 기술인가"   prefix·좌표 목록의 유일한 원천
규칙   evidence_rule        "어느 수준인가"   해석된 tech_id 위의 조건
```

판정은 두 단계다.

```
① 해석   fact ──매핑──▶ tech_id
           IMPORT     → IMPORT_PATH 매핑 (생태계별 구분자 경계에서 PREFIX)
           DEPENDENCY → PACKAGE 매핑

② 평가   해석된 fact ──규칙──▶ L0..L3
```

### 왜 나눴나

V3의 L1 규칙은 IMPORT_PATH 매핑을 그대로 옮겨 적은 것이었다.

```
technology_mapping    org.apache.kafka  PREFIX(JAVA)  → apache-kafka
evidence_rule_clause  org.apache.kafka  PREFIX(.)     → apache-kafka.l1.import
```

Redis 클라이언트를 하나 추가하려면 두 곳을 고쳐야 했고, 한쪽을 빠뜨려도 아무
오류가 나지 않았다. 매핑만 고치면 후보에서는 사라지는데 L1은 안 붙고, 규칙만
고치면 그 반대가 된다.

이제 L1 절은 이렇게 말한다.

```
fact_type = IMPORT,  fact_field = TECH_ID,  match_operator = EXACT,
expected_value = 'apache-kafka'
```

언어별 `group_no`도 사라졌다. Java·Python·JS 분기는 이미 매핑이 하고 있다.

`TECH_ID`는 원문에 있는 필드가 아니라 ①이 붙여 주는 파생 필드다. 매핑이 겹치면
한 fact가 여러 기술로 해석될 수 있고, 그때는 **하나라도 같으면** 성립한다.

### L3는 그대로다

`org.springframework.boot.actuate`와
`org.springframework.kafka.listener.DeadLetterPublishingRecoverer`는 매핑보다
세밀해서 어디에도 중복되지 않는다. 이런 것은 계속 `MODULE` + `PREFIX`로 쓴다.
**규칙은 매핑이 표현할 수 없는 것만 표현한다.**

### 규칙 평가의 네 겹

```
predicate_value  ──OR──▶  predicate  ──AND──▶  clause  ──AND──▶  group  ──OR──▶  rule
   기대값 여러 개            필드 여러 개      min_match_count       대안
```

- **술어** — fact의 `fact_field` 값이 기대값 중 **하나라도** `match_operator`로 맞으면 참
- **절** — 그 절의 **모든** 술어를 만족하는 fact가 `min_match_count`개 이상
- **그룹** — 같은 `group_no`의 `REQUIRED` 절을 **전부** 만족
- **규칙** — 그룹이 **하나라도** 성립

한 기술이 여러 규칙을 만족하면 최종 레벨은 **가장 높은 `rule_type`**이고, 동률은
`priority`로 가른다.

`evaluation_scope = PERSONAL`은 지금 평가할 수 없다. 본인 기여 판정에는 commit
author와 라인 대조가 필요한데 `--depth 1`에는 히스토리가 없다. 조용히 건너뛰지
말고 명시적으로 skip해야 한다.

### 어휘는 이제 제약이다

`rule_type`·`evaluation_scope`·`role`·`fact_type`·`fact_field`·`match_operator`가
V6부터 CHECK로 강제된다. 그 전에는 varchar에 주석뿐이어서, 오타가 INSERT를
통과한 뒤 "매칭되지 않는 규칙"으로만 나타났다 — 기술을 쓰지 않는 저장소와
구분되지 않는 실패 방식이다.

`segment_delimiter`는 `PREFIX`·`SUFFIX`에서만 허용한다. `EXACT`에 붙어 있으면
경계 검사를 하는 것처럼 읽히지만 아무 효과가 없다.

### 생태계마다 PREFIX의 뜻이 다르다

`PACKAGE` 매핑이 `EXACT`뿐이던 것을 V7에서 고쳤다. 그런데 단순히 `PREFIX`로
바꾸면 안 된다 — **좌표 구조가 생태계마다 다르다.**

| 생태계 | 구조 | 경계 | PREFIX |
| --- | --- | --- | --- |
| `MAVEN` | `group:artifact` 계층적 | `.` `:` `-` | 사용 |
| `NUGET` | dotted id 계층적 | `.` | 사용 |
| `NPM` | 스코프만 계층 | `/` | 스코프에만 |
| `PYPI` | 평평 | (없음) | **금지** |

npm과 PyPI에서 `-`를 경계로 삼으면 `react`가 `react-dom`·`react-router`를,
`kafka`가 `kafka-python`을 삼킨다. 전부 별개 패키지이고 레지스트리에서도 별개
기술이다. **평평한 이름 공간에서는 `EXACT`가 맞고**, `package_has_prefix`는
PyPI에 PREFIX를 쓰면 조용히 False를 주는 대신 예외를 던진다 — 매칭되지 않는
매핑은 "아무도 안 쓰는 기술"과 구분되지 않기 때문이다.

효과는 spring-petclinic으로 재보면 이렇다.

```
MAVEN 의존성 31개 중 spring-boot 로 해석되는 것
  EXACT  (구)   1개   spring-boot-starter-webmvc
  PREFIX (신)  14개   -actuator -cache -data-jpa -restclient -thymeleaf
                      -validation -webmvc 와 각 -test
```

L0 판정 자체는 1개로도 서지만 Evidence는 `build.gradle` 한 줄뿐이고, webmvc를
쓰지 않는 저장소는 0개가 된다.

### 한 fact가 여러 기술로 해석될 수 있다

```
org.springframework.boot:spring-boot-starter-data-jpa
  → spring-boot       (PREFIX)
  → spring-data-jpa   (EXACT)
```

우선순위를 두지 않는다. **둘 다 참이기 때문이다** — 그 의존성은 Spring Boot를
쓴다는 증거이자 Spring Data JPA를 쓴다는 증거다. 더 구체적인 것 하나만 남기면
맞는 사실 하나를 버리게 된다.

위험은 지나치게 넓은 prefix가 조용히 모든 곳에 기술을 붙이는 것인데, 이것은
스키마가 아니라 레지스트리 리뷰로 막을 문제다.


### 실제로 돌린 결과

V7 레지스트리(기술 29개, 매핑 117개, 규칙 60개)로 두 저장소를 판정했다.

```
spring-petclinic   기술 7개 · Evidence 97건 · 후보 10개
  spring-boot L1 · spring-data-jpa L1 · testcontainers L1
  junit L1 · mockito L1 · postgresql L0 · mysql L0

이 저장소            기술 17개 · Evidence 243건 · 후보 27개
```

`postgresql`·`mysql`이 petclinic에서 **L0만**인 것이 두 fact 종류를 나눈 이유다.
JDBC 드라이버라 매니페스트에만 있고 소스 import에는 없다. 반대로 `junit`·
`mockito`는 **L1만**인데, `starter-test`로 딸려 와서 직접 선언하지 않았기
때문이다.

`spring-boot`가 L3가 아닌 것도 맞다. petclinic은 `spring-boot-starter-actuator`를
선언만 하고 `org.springframework.boot.actuate`를 import하지 않는다. L3 규칙이
요구하는 것은 선언이 아니라 사용이다.

### 레지스트리 버전은 통째로 읽고 캐시한다

`registry_version`이 모든 콘텐츠 테이블의 PK에 들어 있어 **한 버전의 내용은
변하지 않는다.** 그래서 캐시 무효화 문제가 없다 — 한 번 읽어 인덱스를 만들고
들고 있으면 된다. 배포 중 구·신 버전 이벤트가 섞이므로 2개까지 보관한다.

fact마다 조회하는 방식은 모양이 틀렸다. 저장소 하나가 수백 개의 fact를 내는데
레지스트리 전체는 수천 행이다.

### 없는 버전은 영구 실패다

없는 버전으로 규칙을 조회하면 0행이고, 0행은 "매칭된 기술 없음"으로 평가된다.
**그건 아무 기술도 안 쓰는 저장소와 똑같이 생겼다.** 재시도해도 버전이 생기지
않으므로 `REGISTRY_VERSION_UNKNOWN`으로 `FAILED` + DLQ + 커밋한다.

`UnknownRegistryVersion`은 `RuleSet` 생성자가 던진다. 빈 RuleSet을 만들 수
있게 두면 그 판정이 어디까지 흘러갈지 알 수 없다.


## 실패 분류

| 종류 | 예 | 처리 |
| --- | --- | --- |
| 일시 (예산 남음) | DNS, 연결 끊김, 5xx, rate limit, early EOF, timeout | 선점 반납, **커밋 안 함**. 예외가 `run()`을 관통해 프로세스가 죽고 컨테이너가 재시작하며, 그 재배달이 재시도다 |
| 일시 (예산 소진) | 위와 같은 오류가 `ANALYSIS_MAX_ATTEMPTS`번째로 난 경우 | 영구로 전환한다. `FAILED` + DLQ + **커밋** |
| 영구 | 404, 없는 SHA, 인증 필요, 크기 초과, 알 수 없는 git 오류 | `FAILED` + DLQ + **커밋** |
| 예기치 못한 예외 | claim 저장 실패, 디스크 오류 | 선점 반납 후 그대로 전파. 아래 설명 |

**예기치 못한 예외도 선점을 반납한다.** 반납하지 않으면 프로세스가 죽을 때 선점이
`CLONING`으로 남고 offset은 커밋되지 않는다. 재배달된 메시지는 그 선점을 lease가 풀릴
때까지 가져갈 수 없어 `skipped`가 되고, 그대로 커밋된다 — **요청이 사라진다.**

반납 자체가 실패하면(대개 같은 장애) 로그만 남기고 원래 예외를 그대로 던진다. offset이
커밋되지 않으므로 lease 만료가 마지막 회복 수단이다.

**DLQ 발행이 실패하면 그 메시지는 로그에만 남고 사라진다.** DLQ가 주 토픽을 막지 않는
쪽을 택한 결과이고, 의도된 트레이드오프다.

**분류되지 않은 오류는 영구로 본다.** 알 수 없는 git 오류가 저절로 낫는 경우는 드물고,
무한 재처리보다 DLQ에 한 건 남기는 편이 낫다. 일시로 볼 패턴만 명시적으로 나열했다.

### 재시도 예산이 필요한 이유

일시 실패는 커밋하지 않는다. 그런데 **매번 timeout이 나는 저장소는 매 배달마다 일시**다.
예산이 없으면 그 하나가 파티션 offset을 붙잡고, 뒤에 줄 선 요청은 하나도 분석되지 않는다.
"재시도로 고쳐지지 않는 실패도 커밋한다"는 규칙이 있는 이유와 같은 상황인데, 분류만으로는
이쪽을 잡지 못한다.

그래서 `attempt`를 센다. 예전에는 반납이 행을 지워서 재배달마다 1로 돌아갔고, 그러면
아무리 세도 상한에 닿지 않는다. 지금은 행을 남기고 lease만 즉시 만료시킨다.

| | |
| --- | --- |
| 세는 곳 | `claim()` 한 곳뿐. 그래서 "작업을 시작한 횟수"로 읽힌다 |
| 기본값 | 5회 (`ANALYSIS_MAX_ATTEMPTS`). 첫 배달이 1회를 쓴다 |
| 소진되면 | `finish(FAILED)` + DLQ + 커밋. 영구 실패와 같은 처리다 |
| 운영자 판별 | `CLONING` 행의 `claimed_at`이 `-infinity`면 반납된 것(재배달 대기), 실제 시각이면 진행 중이거나 죽은 worker가 남긴 것 |

`GIT_TERMINAL_PROMPT=0`을 준다. 비공개 저장소에서 git이 사용자명을 물으며 멈추면
브로커가 파티션을 회수할 때까지 매달려 있게 된다. 즉시 실패하는 편이 낫다.

## 비공개 저장소는 아직 안 된다

이벤트에 토큰이 없다. 의도된 것이고, payload 주석이 이유를 적어 두었다.

> The worker exchanges `analysis_repository_id` for a short-lived credential
> through an authenticated internal API when it starts the job.

**그 내부 API가 아직 없다.** 지금은 공개 저장소만 받는다. 비공개는
`REPOSITORY_NOT_ACCESSIBLE`로 끝난다.

## 설정

| 환경변수 | 기본값 | 비고 |
| --- | --- | --- |
| `KAFKA_TOPIC_REPOSITORY_ANALYSIS_REQUESTS` | `gitjob.repository-analysis.requests.v1` | B가 발행하는 토픽. C조 worker의 `KAFKA_TOPIC_ANALYSIS_REQUESTS`와 **다른 토픽이다** |
| `ANALYSIS_CONSUMER_GROUP` | `gitjob-repository-analysis` | |
| `KAFKA_TOPIC_REPOSITORY_ANALYSIS_DLQ` | `gitjob.repository-analysis.dlq.v1` | 전용 DLQ. C조 worker의 `KAFKA_TOPIC_ANALYSIS_DLQ`와 payload 형태가 달라 섞지 않는다 |
| `KAFKA_MAX_POLL_INTERVAL_MS` | `900000` | **clone 최대 소요보다 커야 한다.** 작으면 브로커가 파티션을 회수해 다른 worker가 같은 저장소를 또 내려받는다. compose는 `ANALYSIS_MAX_POLL_INTERVAL_MS`를 이 이름에 매핑한다 |
| `ANALYSIS_CLAIM_LEASE_SECONDS` | `900` | 위와 같은 이유로 clone 최대 소요보다 커야 한다 |
| `ANALYSIS_MAX_ATTEMPTS` | `5` | 일시 실패를 몇 번까지 재시도할지. 소진되면 영구 실패로 전환한다 |
| `ANALYSIS_CLONE_TIMEOUT_SECONDS` | `600` | |
| `ANALYSIS_MAX_REPOSITORY_BYTES` | `2147483648` | clone 후 검사. git에 미리 물을 방법이 없다 |
| `ANALYSIS_WORK_ROOT` | `/tmp/gitjob-analysis` | 볼륨이 없어 재시작하면 사라진다. 재시도하면 다시 받으므로 의도된 것 |
| `ANALYSIS_MAX_FILE_BYTES` | `1048576` | 파싱할 파일 하나의 상한 |
| `ANALYSIS_MAX_FILES` | `50000` | 순회할 파일 개수 상한 |

## 배포 전

```bash
# 1) 저장소 checkout에서 claim 테이블을 수동 적용한다.
psql -v ON_ERROR_STOP=1 -f BE/src/main/resources/db/migrations/002_repo_analysis.sql

# 2) 기동
PROFILES=core,data ./Infra/scripts/up.sh
```

이 SQL은 Flyway의 `migration/`이나 C조 러너의 `c-compute/` 대상이 아니다. Worker
이미지에도 자동으로 포함되지 않으므로 위 명령은 배포에 사용할 저장소 checkout에서
analysis-worker 기동 전에 실행한다. `python -m worker.migrate`도 이 테이블을 만들지 않는다.

Kafka·DB·claim 테이블·tree-sitter 문법 중 하나라도 없으면 **프로세스가 뜨기를 거부한다.** 환경변수 하나가
빠져 조용히 놀고 있는 consumer는 조용한 토픽과 구분되지 않고, 그건 며칠 뒤에 발견된다.

Compose healthcheck는 두지 않았다. 포트를 열지 않는 프로세스이고, 기동 자체가 이미
의존성을 증명한다. `Infra/scripts/healthcheck.sh`의 점검 대상에도 넣지 않았다.

## 검증

```bash
cd AI && python -m pytest tests/test_analysis_consumer.py tests/test_analysis_clone.py tests/test_analysis_parse.py -q
```

- `test_analysis_consumer.py` — 브로커도 DB도 없이 fake를 주입해 **순서 규칙**을 검증한다.
  잘못된 메시지는 선점하지 않고 DLQ로, 일시 실패는 반납 후 예외(커밋 안 함), 영구 실패는
  기록 후 커밋, 작업 디렉터리는 실패해도 삭제. 재시도 예산은 token을 받았을 때의 행동만
  본다 — 예산 안이면 반납, 마지막이면 영구 실패, 그 사이에 선점을 빼았기면 `ClaimLostError`.
  token이 실제로 누적되는지는 `test_analysis_claim.py`가 실 DB로 확인한다.
- `test_analysis_parse.py` — tree-sitter를 **실제로** 쓴다. Java text block 안의
  `import`, JavaScript 문자열·템플릿 안의 `import`, 주석 처리된 `import`,
  `require`가 아닌 한 인자 호출이 모두 걸러지는지 확인한다. 정규식 대신 파서를
  택한 이유가 그것이라 mock으로는 아무것도 증명되지 않는다.
- `test_analysis_judge.py` — 규칙 집합을 값으로 직접 직어 평가 의미론을 고정한다.
  그동안 마이그레이션 주석에만 있던 group·role·min_match_count·경계 규칙이
  여기서 처음으로 실행 가능한 명세가 된다. DB를 쓰지 않는다.
- `test_analysis_manifests.py` — 실제 파일로 읽는다. 보간된 Gradle 버전, 버전 카탈로그,
  모노레포의 자기 패키지, `dependencyManagement`, PEP 503 표기 — 순진한 리더가 틀리는
  모양만 모았다. mock으로는 아무것도 증명되지 않는다.
- `test_analysis_clone.py` — git을 **실제로** 쓴다. remote는 디스크 위의 저장소라 네트워크가
  없다. 브랜치가 움직인 뒤에도 요청한 commit이 체크아웃되는지, 오래된 커밋에는 이후 파일이
  없는지까지 확인한다.

격리된 로컬 PostgreSQL/Kafka가 있을 때 lease와 강제 종료 재배달을 추가로 검증한다.

```bash
ANALYSIS_TEST_POSTGRES_DSN=postgresql://... \
ANALYSIS_TEST_KAFKA_BOOTSTRAP=127.0.0.1:9092 \
python -m pytest tests/test_analysis_claim.py tests/test_analysis_kafka_integration.py -q
```

두 환경변수를 모두 명시하지 않으면 통합 테스트는 skip한다. 비-loopback endpoint는
거절한다. Kafka 테스트는 고유한 `mr46-review-<uuid>` topic/group만 만들며, topic
삭제는 `ANALYSIS_TEST_KAFKA_DELETE_TOPIC=1`일 때만 수행한다.

`test_analysis_claim.py`는 실제 PostgreSQL에서 첫 선점·BUSY·반납 후 재시도·만료
인수와 stale token의 release/finish 차단을 확인한다. Kafka 통합 테스트는 별도
프로세스를 첫 poll+claim 직후 강제 종료하고, lease 만료 전 재배달은 commit하지 않으며
만료 후 원본·후속 offset·terminal duplicate가 순서대로 처리되는지 확인한다. 로컬 Git과
tree-sitter도 이 경로에서 실제로 실행하지만, Windows native Kafka 검증은 Linux/Docker
이미지 기동 검증을 대신하지 않는다.

## 다음

1. **분석 상태 되돌리기** — 결과 토픽으로 `COLLECTING`/`FAILED`를 B에 전달. 지금은
   `analysis_job`이 `QUEUED`에 머문다
2. **자격 증명 내부 API** — 비공개 저장소
3. ~~기술 판정~~ — 완료. `analysis/judge.py`가 매핑으로 해석하고 규칙을 평가한다
4. **기술 후보 집계** — worker는 관찰만 낸다. 사용자 수 집계와 관리자 화면은 B
5. **Evidence 저장** — 결과 토픽으로 보내고 B가 `analysis_evidence`에 쓴다
6. **본인 기여 판정(L2)** — 커밋 author와 라인을 대조해야 한다. `--depth 1`로는
   히스토리가 없으므로 더 큰 depth가 필요하다
