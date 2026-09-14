# Evidence 조회 API — FE 계약과 BE 구현의 차이

> 작성 2026-09-11 · BE(이 저장소 구현) ↔ FE 티켓 S15P21E102-208 계약
>
> FE가 `types.ts`·`parseEvidence.ts`로 계약을 먼저 고정했고, BE는 다른 모양으로
> 이미 구현돼 있다. **두 쪽 다 상대를 모르고 만들어졌다.** 이 문서는 무엇이
> 다른지와, 누가 무엇을 정해야 하는지를 적는다.

## 지금 상태

```
FE  evidenceApi.ts     GET /me/profile?analysisId=            ← BE에 없음
    parseEvidence.ts   GET /me/technologies/{techId}/evidence  ← 경로는 같고 모양이 다름

BE  TechnologyProfileController
                       GET /me/technologies                    ← FE가 안 부름
                       GET /me/technologies/{techId}/evidence
```

화면(`EvidenceOverviewPage`)은 아직 어느 쪽도 부르지 않는다. 자리표시자 상태다.

**부분 적합은 소용이 없다.** `parseEvidence.ts`가 필드 하나만 어긋나도 예외를
던지므로, 반만 맞추면 빈 화면이 아니라 오류 화면이 된다. 전부 맞추거나, 계약을
고치거나 둘 중 하나다.

---

## 1. 지금 바로 맞출 수 있는 것 — 이름만 다르다

| FE 계약 | BE 현재 | 조치 |
|---|---|---|
| `techName` | `displayName` | BE 개명 |
| `repoLevel` | `repositoryLevel` | BE 개명 |
| `matchedRule` | `ruleId` | BE 개명 |
| `detectedAt` | `matched_at` | BE 노출 |
| `evidenceId` | (미노출) | `analysis_evidence_id` 노출 |
| `repoFullName` | `repository` | BE 개명 |

BE만 고치면 되고 논쟁거리가 없다.

## 2. 만들 수 있지만 새 로직이 필요한 것

| FE 계약 | 무엇이 필요한가 |
|---|---|
| `partial` · `missingScope[]` | 선택한 저장소 중 실패한 것을 센다. `analysis_job.status='FAILED'`로 계산 가능 |
| `representativeRepo` | 근거가 가장 많은 저장소 |
| `unmetRules[]` | 그 기술의 상위 Level 규칙 중 충족되지 않은 것. Registry를 읽어 계산 |
| `nextActions[]` | 위에서 "무엇을 더 하면 다음 Level인가" 문장 생성 |
| `criteria.limits` | 워커 상수(`max_files=50,000`)를 응답에 싣기 |
| `judgementLimits[]` | 판정 한계 문장 목록. 내용은 제품이 정한다 |

## 3. 데이터가 없어서 못 맞추는 것 — **결정 필요**

### 3-1. `personalLevel`이 non-nullable이다

FE 타입:

```ts
repoLevel: EvidenceLevel
personalLevel: EvidenceLevel    // null 불가
```

**BE는 이 값을 만들 수 없다.** 본인 Commit 범위를 알려면 근거 라인마다 작성자를
봐야 하는데, 워커가 `--depth 1`로 클론해서 blame이 불가능하고
`analysis_evidence_commit`은 0행이다.

Repository Level을 복사해 넣으면 화면이 "본인이 썼다"고 말하게 된다. 그건 이
제품이 하지 않기로 한 것이다.

**정해야 할 것:** `personalLevel`을 nullable로 풀 것인가, 아니면 커밋 기여도
구현(아래 3-4)까지 이 API를 미룰 것인가.

### 3-2. `lastUsedAt` — 커밋 날짜가 필요하다

"이 기술을 마지막으로 쓴 시점"은 커밋 시각이다. `analysis_evidence.matched_at`은
**분석을 돌린 시각**이지 코드를 쓴 시각이 아니다. 그대로 넣으면 모든 기술의
`lastUsedAt`이 같아진다.

**정해야 할 것:** 3-4 전까지 이 필드를 뺄 것인가, 분석 시각으로 두고 의미를
바꿀 것인가(권장하지 않음).

### 3-3. `excludedCounts` · `excludedReason` · `inherited`

봇 커밋·merge·fork base·generated·format-only를 구분하려면 커밋을 분류해야 한다.
지금 워커는 커밋을 보지 않는다. `inherited`도 개념 자체가 BE에 없다.

**정해야 할 것:** 전부 0으로 보내는 것은 거짓이다(세어 보지 않았으므로). 필드를
빼거나 nullable로 두어야 한다.

### 3-4. 선행 작업이 하나로 묶인다

3-1·3-2·3-3이 **같은 선행 작업**을 공유한다.

```
히스토리 포함 클론
  ├─ git log   → 기술별 첫·마지막 근거 시점   → lastUsedAt
  ├─ git blame → 근거 줄의 작성자             → personalLevel
  └─ 커밋 분류 → 봇·merge·generated           → excludedCounts
```

설계는 [analysis-implementation.md 20장](../analysis-implementation.md)에 있다.
구현은 아직 안 됐다.

### 3-5. `registryChecksum`

Registry 버전의 체크섬 개념이 DB에 없다. 추가하려면 마이그레이션이 필요하다.

---

## 4. 구조가 충돌하는 것 — **여기가 핵심**

### 4-1. 집계 단위: analysisId인가 사용자인가

FE 계약은 **분석 한 건**이 단위다.

```
GET /me/profile?analysisId=...      응답에 analysisId, analyzedAt 단수
```

BE는 **사용자**가 단위다. 저장소별 최신 성공 분석을 모아 기술별 최고 Level을
채택한다.

이건 이름 차이가 아니다. 확정된 제품 정책이 *"저장소마다 별도 analysisId, 기술별
최고 Level 채택"*인데, 그러면 **프로필 하나에 analysisId가 여러 개**가 된다.
단수 필드에 담을 수 없다.

FE의 `EvidenceOverviewPage` 주석이 이 구멍을 이미 지적해 두었다 —
*"여러 analysisId를 가로지르는 집계 단위가 계약에 없다."*

**정해야 할 것:** 셋 중 하나다.

| 안 | 내용 | 대가 |
|---|---|---|
| **A** | `analysisId`를 빼고 사용자 단위로 간다 | 명세 B-FN-010과 달라진다 |
| **B** | 분석 한 건만 보여준다 | 저장소를 여러 개 분석해도 하나만 보인다 |
| **C** | `analysisIds[]` 복수로 바꾼다 | 계약 수정 + 화면이 여러 건을 표현해야 한다 |

BE 구현과 제품 정책은 **A**를 가리킨다. 다만 명세를 벗어나므로 FE·기획과 합의가
필요하다.

### 4-2. 카테고리 값 집합이 다르다

FE 계약(명세 B-FN-010):

```
BACKEND · DATABASE · INFRASTRUCTURE · TESTING · OBSERVABILITY · OTHER
```

DB(`technology_category.job_domain`, registry-20260910.2):

```
BACKEND(21) · AI_DATA(12) · FRONTEND(6) · INFRASTRUCTURE(5)
```

겹치는 것은 `BACKEND`·`INFRASTRUCTURE` 둘뿐이다. 그리고 **성격이 다르다** — DB
쪽은 *직무 도메인*(이 기술이 어느 직무에 속하나)이고, 명세 쪽은 *기술 분류*(이게
DB인가 테스트 도구인가)다. `junit`이 DB에서는 `BACKEND`인데 명세로는 `TESTING`이다.

한 기술이 여러 도메인에 속하는 것도 다르다 — `apache-kafka`는 지금
`AI_DATA`·`BACKEND`·`INFRASTRUCTURE` 셋에 들어 있다. 명세의 `categories[]`는
기술을 한 카테고리에만 넣는 구조다.

**정해야 할 것:** 두 축을 둘 다 둘 것인가(`job_domain`은 직무 매칭용, 새
`category_code`는 화면 분류용), 아니면 하나로 합칠 것인가. 합치면 직무 매칭
기능이 영향을 받는다.

### 4-3. 근거 목록의 모양

FE 계약은 **평평한 배열**이다.

```ts
evidences: EvidenceItem[]     // 한 줄 = 파일 한 곳
```

BE는 **Level → 파일 → 라인**으로 접는다. 평평하면 Spring Security 하나가 82행이
되고 같은 파일의 연속된 import 세 줄이 세 행을 차지해서, 화면이 "왜 L2인가"가
아니라 로그가 되기 때문이다.

**정해야 할 것:** 접는 일을 BE가 할 것인가 FE가 할 것인가. 평평하게 내려보내고
FE가 묶어도 된다 — 다만 그때는 Level마다 따로 자르는 상한 처리도 FE로 간다.
(전체에 하나의 상한을 걸면 L2가 채우는 순간 L0·L1이 통째로 사라진다.)

---

## 5. 권고

**단계를 나누자.**

**1단계 — 지금 화면을 살린다.** 1·2번 항목만 맞추고, 3번(데이터 없는 필드)은
계약에서 optional로 풀거나 뺀다. 4-1은 A안(사용자 단위), 4-3은 BE가 접는 현행
유지. 이렇게 하면 오늘 화면에 651건의 근거가 뜬다.

**2단계 — 커밋 기여도 구현 후.** `personalLevel`·`lastUsedAt`·`excludedCounts`를
채우고 계약을 원래 모양으로 되돌린다.

**4-2(카테고리)는 1단계에서 건드리지 않는 것을 권한다.** 직무 매칭 기능과 얽혀
있어 여기서 정할 문제가 아니다. 1단계에서는 카테고리 하나(`OTHER`)에 전부 넣거나
`categories`를 빼고 평평한 목록으로 둔다.

## 6. 결정이 필요한 목록

| # | 항목 | 누가 |
|---|---|---|
| 1 | `personalLevel` nullable 허용 여부 | FE + 기획 |
| 2 | `lastUsedAt`·`excludedCounts`·`inherited` — 1단계에서 뺄 것인가 | FE + 기획 |
| 3 | 집계 단위 A/B/C | FE + 기획 + BE |
| 4 | 카테고리 축을 둘 둘 것인가 | 기획 |
| 5 | 근거 접기를 BE가 할 것인가 | FE + BE |

1~3이 정해지면 BE 조정은 하루 안에 끝난다. 4는 1단계에서 미룰 수 있다.
