# 기술 후보 검토 (관리자 화면)

분석 워커가 매니페스트에서 본 의존성 중 레지스트리에 없는 것을 후보로 남긴다.
그 목록을 사람이 보고 등록 여부를 정하는 자리가 이 화면이다.

관련 문서: [기술 Registry와 Evidence 규칙](technology-registry.md) ·
[분석 Worker](repository-analysis-worker.md)

## 왜 자동 등록하지 않는가

좌표 하나가 곧 기술이 아니다. petclinic 한 저장소에서 나온 실제 후보 10건을
보면 이유가 그대로 드러난다.

```
com.github.ben-manes.caffeine:caffeine        캐시 라이브러리   → 등록
com.h2database:h2                             인메모리 DB       → 등록
com.puppycrawl.tools:checkstyle               빌드 도구         → 거절
io.spring.javaformat:spring-javaformat-...    빌드 도구         → 거절
io.spring.nohttp:nohttp-checkstyle            빌드 도구         → 거절
org.webjars.npm:bootstrap                     정적 자원 포장    → 판단 필요
```

세 건은 코드 품질 검사 플러그인이고, webjars 계열은 npm 패키지를 Maven으로
싸 놓은 것이라 "이 사람이 Bootstrap을 쓴다"는 근거로 쓸지가 갈린다. 규칙으로
거를 수 있는 모양이 아니어서 사람이 본다.

## 왜 후보를 지우지 않는가

거절해도 행은 남고 관찰 수는 계속 늘어난다. 세 명이 쓸 때 거절한 것이 삼백
명이 쓸 때는 다른 판단일 수 있고, 지워 버리면 그 변화가 보이지 않는다.
그래서 거절 사유를 필수로 받는다 — 사유가 없으면 다음 사람이 같은 판단을
처음부터 다시 한다.

목록은 `status <> 'REJECTED'` 로 걸러 보여주므로 평소에는 눈에 띄지 않는다.

## 순위는 사용자 수로만 매긴다

```sql
ORDER BY distinct_user_count DESC, distinct_repository_count DESC, coordinate
```

발생 횟수(`occurrence_count`)로 정렬하면 모노레포 하나가 순서를 정한다. 관리자가
답해야 하는 질문은 "몇 줄이 언급하는가"가 아니라 "몇 명에게 쓸모가 있는가"다.
화면은 세 수치를 모두 보여주되 사용자 수만 강조한다.

## 승격은 초안에 쌓인다

```
CURRENT (registry-20260910.2)      ← 지금 판정에 쓰인다. 절대 안 바뀐다.
   │  openDraft() = 통째로 복사
   ▼
DRAFT  (registry-20260910.3)       ← 승격이 여기에 쌓인다
   │  publish()
   ▼
CURRENT (registry-20260910.3)      ← 이후 요청되는 분석부터 이 버전
RETIRED (registry-20260910.2)      ← 행은 그대로 남는다
```

`registry_version` 이 모든 내용 테이블의 기본키에 들어 있어 발행된 버전은 바꿀
수 없다. 분석 이벤트가 자기가 판정에 쓴 버전을 들고 있기 때문이다 — 반년 뒤에
"이 근거는 어떤 규칙이 만들었나"를 되짚을 수 있어야 한다.

초안을 **빈 상태가 아니라 CURRENT 의 복사본으로** 여는 것이 중요하다. 새 기술만
담은 초안을 발행하면 지금 아는 기술 29개가 전부 사라진다. 그러면 모든 저장소가
"거의 아무것도 안 쓴다"로 나오는데, 그건 정상 결과처럼 보여서 눈에 띄지 않는다.

한 주치 결정이 버전 하나로 나가는 것도 같은 구조 덕분이다.

## 승격이 만드는 것

`RegistryDraftStore.addTechnology` 가 초안에 네 가지를 넣는다.

| 테이블 | 내용 |
|---|---|
| `technology` | 기술 자체 (`tech_id`, 표시명, ACTIVE) |
| `technology_category` | 고른 직무 도메인마다 한 행 |
| `technology_mapping` | `PACKAGE` · 후보의 생태계·좌표 · `EXACT` |
| `evidence_rule` 이하 | `{tech_id}.l0.dependency` 규칙 한 벌 (절·술어·기대값까지) |

**매핑은 `EXACT` 다.** `PREFIX` 로 넓히면 아무도 쓰는 것을 본 적 없는 아티팩트까지
그 기술로 판정된다. 관찰한 것보다 넓은 근거는 만들지 않는다. npm 과 PyPI 는
애초에 접두 경계가 없기도 하다.

**규칙은 L0 뿐이다.** 승격된 후보는 의존성 좌표이므로 "선언했다"까지가 관찰된
사실이다. 코드가 import 하는지(L1), 실제로 호출하는지(L2)는 이 승격이 갖고 있지
않은 매핑이 있어야 답할 수 있다.

기술 식별자를 안 넘기면 좌표에서 만든다 (`io.jsonwebtoken:jjwt-api` →
`io-jsonwebtoken-jjwt-api`). 좌표는 그대로 id 가 될 수 없다 — 생태계마다 콜론,
슬래시, 점, `@` 가 섞인다. 화면은 그 결과를 미리 채워 보여주고 고칠 수 있게 한다.

## API

`/api/v1/admin/**` 는 `SecurityConfig` 가 `hasRole("ADMIN")` 으로 제한한다.
역할은 `user.role` 컬럼(V10)에 있고 JWT 필터가 `ROLE_` 를 붙여 권한으로 만든다.

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| GET | `/api/v1/admin/technology-candidates?limit=50` | 후보 목록 (1~200) |
| GET | `/api/v1/admin/technology-candidates/registry` | `{current, draft}` |
| POST | `/api/v1/admin/technology-candidates/{id}/promote` | 초안에 등록 |
| POST | `/api/v1/admin/technology-candidates/{id}/reject` | 거절 |
| POST | `/api/v1/admin/technology-candidates/registry/publish` | 초안 발행 |

승격 본문은 전부 선택이다.

```json
{ "techId": "caffeine", "displayName": "Caffeine",
  "jobDomains": ["BACKEND"], "note": "캐시 라이브러리" }
```

응답은 `{ "techId": "caffeine", "registry": { "current": "...", "draft": "..." } }`.
레지스트리 상태를 같이 실어 보내 화면이 대기 중인 초안을 한 번 더 묻지 않아도
되게 한다.

### 오류

전부 공통 실패 봉투다.

| 코드 | 상태 | 뜻 |
|---|---|---|
| `ADMIN-400-1` | 400 | 기술 식별자 형식이 아니다 |
| `ADMIN-404-1` | 404 | 후보가 없다 |
| `ADMIN-409-1` | 409 | 이미 처리된 후보다 |
| `ADMIN-409-2` | 409 | 발행할 초안이 없다 |

`ADMIN-409-1` 은 오류가 아니라 정상 상황이다. 관리자 둘이 같은 목록을 보고 같은
행을 누르는 일이 있고, 뒤에 누른 쪽은 목록을 새로 읽으면 무엇이 어떻게 처리됐는지
그대로 보인다. 화면은 이 넷을 모두 해당 행 옆에 붙인다 — 화면 전체를 오류로 덮으면
다른 후보를 계속 처리할 수 없는데, 실제로 막힌 것은 그 한 행이다.

## 경합에서 부분 적용이 없어야 하는 이유

승격은 초안 편집과 후보 상태 변경을 한 트랜잭션에서 한다. 상태 변경은
`WHERE status IN ('NEW','REVIEWING')` 라서 다른 사람이 먼저 처리했으면 0행이
갱신되고, 그때 예외를 던져 초안 편집까지 되돌린다.

되돌리지 않으면 기술은 레지스트리에 들어갔는데 후보는 다른 사람의 결정을 달고
남는다. 그 후보가 다시 승격되면 같은 기술이 두 번 등록된다.

## 화면

`FE/src/features/admin/pages/TechnologyCandidatePage.tsx`,
경로는 `/admin/technology-candidates`.

라우트를 숨기지 않는다. 숨겨도 보호가 되지 않고, 실제 접근 제어는 BE 가 한다.
관리자가 아닌 사용자는 API 에서 401·403 을 받는다.

낙관적 업데이트는 하지 않는다. 미리 지워 둔 행을 409 를 받고 되살리는 것보다
서버가 실제로 무엇을 받아들였는지 다시 읽는 편이 정확하다.
