# 디자인 fixture

확정 디자인 `GitJob_FE_Final_v2_17screens.html`의 데모 데이터를 타입 있는 모듈로 옮긴 것.
**조회 API가 없어 화면이 비어 보이는 동안 레이아웃을 잡기 위한 값**이고, 제품 데이터가 아니다.

와이어프레임 스크립트 첫 줄이 이렇게 적는다.

```
// DESIGN MOCK DATA ONLY. DO NOT COPY THESE VALUES INTO PRODUCTION FRONTEND.
```

그래서 값을 화면에 직접 박지 않고 이 폴더에 모았다. 끄면 원래대로 상태 카드가 보인다.

## 켜는 법

`FE/.env.local`(gitignore 대상)에 한 줄.

```
VITE_DESIGN_FIXTURES=on
```

`'on'`과 정확히 같을 때만 켜진다. 환경 변수 정의는 인프라 소유라
(`docs/fe/shared-api-contract.md` 1-5) 루트 `.env.example`에는 넣지 않았다. 배포
파이프라인이 주입하는 값이 아니라 로컬 디자인 작업 전용이다.

## 쓰는 법

```tsx
import { withDesignFixture } from '@/mocks/designFixtures'
import { JOB_MATCH_ALL } from '@/mocks/fixtures/jobMatch'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'

const scenario = withDesignFixture(query.data, () => JOB_MATCH_ALL)
```

fixture를 직접 import해서 렌더하지 말고 반드시 `withDesignFixture`를 거친다. 그래야
플래그 하나로 전부 끌 수 있다.

`DesignMockBadge`는 fixture가 꺼져 있으면 아무것도 그리지 않으니 조건문으로 감싸지
않는다. 감싸는 순간 배지 없는 화면이 생기고, 그 스크린샷은 실제 결과로 읽힌다.

## 파일

| 파일 | 화면 | 타입 |
|---|---|---|
| `fixtures/technologyProfile.ts` | 08 My Evidence | 계약 (`features/evidence/api/types.ts`) |
| `fixtures/technologyEvidence.ts` | 09 Evidence Detail | 계약 (〃) |
| `fixtures/evidenceScreen.ts` | 08·09 | 계약에 **없는** 표시값 |
| `fixtures/targetRole.ts` | 16 Target Role | fixture 전용 |
| `fixtures/jobMatch.ts` | 02 Job Match | fixture 전용 |
| `fixtures/skillGap.ts` | 17 Skill Gap | fixture 전용 |
| `fixtures/nextSkill.ts` | 10 Recommendation · 03 What-if | fixture 전용 |
| `fixtures/technologyDetail.ts` | 11 Technology Detail | fixture 전용 |
| `fixtures/trend.ts` | 12 Trend Overview · 13 Trend Detail | fixture 전용 · 기술 10종 시계열 |
| `fixtures/growthStage.ts` | S6 성장 단계 (초안) | fixture 전용 |
| `fixtures/analysisFlow.ts` | 06 Repository · 07 Analysis · 14 My Page | fixture 전용 |

Evidence 계열 둘만 실제 계약 타입을 쓴다. 티켓 208이 명세를 근거로 이미 고정해 둔
계약이라 fixture도 그 타입을 만족해야 한다. 나머지는 조회 API가 없어 계약이 없으므로
`src/mocks/types.ts`에 화면용 타입을 따로 두었다 — **공용 타입 폴더에 두지 않는 것이
규칙이다.** 공용에 두면 다음 사람이 확정된 계약으로 읽는다.

## 와이어프레임과 일부러 다르게 둔 곳

값을 그대로 옮기지 않은 자리가 셋 있다. 데이터 계약과 어긋나서다.

1. **Stack Overflow 순위·시계열** (`trend.ts`) — 와이어프레임은 값과 함께 그리지만
   `docs/ai/c-public-trend.md` 10행이 "Stack Overflow는 현재 입력에 없다"고 적는다.
   `PREPARING` 상태로 두고 행을 비웠다.
2. **깃허브 star 증가율** (`growthStage.ts`) — 초안의 판정 축인데 star 지표는 수집
   대상이 아니다(docs·AI 코드 전체에 없다). GH Archive 활동 추이로 바꿨다.
3. **GitHub 출처의 `LANGUAGE ONLY` 배지** (`trend.ts`) — `DataStatus`에 없는 값이라
   상태는 `READY`로 두고 제한을 `scopeNote`로 옮겼다.

없는 데이터를 있는 것처럼 그려 두면 그 전제 위에 화면이 완성되고, 나중에 지우는 일이
디자인을 다시 하는 일이 된다.

## 어떤 fixture가 어느 화면의 무엇이 되는가

fixture는 화면에 그대로 꽂히지 않는다. 대부분 한 번 **다시 묶거나 골라진다.** 그 변환이
어디서 일어나는지 알아야 BE 응답으로 갈아끼울 때 무엇을 서버가 줘야 하는지 판단할 수 있다.

### 공통 관문

모든 화면이 같은 모양으로 fixture를 받는다.

```ts
const data = withDesignFixture<T | null>(null, () => FIXTURE)
```

첫 인수가 **실제 값의 자리**이고 지금은 `null`이다. 화면은 `data === null`이면 기존
`StateCard`를, 아니면 채워진 본문을 그린다. 조회 API가 붙으면 첫 인수를
`useQuery(...).data`로 바꾸고 fixture 인수만 지운다 — 본문 코드는 건드리지 않는다.

예외가 하나 있다. `RepositorySelectionPage`는 `DESIGN_FIXTURES_ENABLED`로 직접 분기한다.
그 화면은 대체 대상이 값 하나가 아니라 조회 상태 전체(로딩·오류·페이지네이션)여서다.

### 화면별 흐름

| fixture | 들어가는 곳 | 중간에 일어나는 변환 |
|---|---|---|
| `TECHNOLOGY_PROFILE` | 08 표 본문 | `EvidenceRows`가 **카테고리 경계를 지우고 Personal Level로 다시 묶는다** (`LEVEL_STEPS >= 2 / == 1 / == 0`). 응답은 카테고리별로 오지만 v2의 묶음 기준은 Level이다 |
| `REPRESENTATIVE_EVIDENCE` | 08 `대표 EVIDENCE` 열 | `techId`로 프로필 행과 join. **계약에 없는 값이라** 프로필 fixture와 섞지 않았다 |
| `EVIDENCE_SUMMARY` | 08 상단 KPI 4칸 | 프로필에서 세지 않고 그대로 쓴다. "근거 보강 필요"의 기준(Repository > Personal? 몇 단계 차이부터?)이 아직 제품 정의라 화면이 세면 규칙을 발명하게 된다 |
| `PARTIAL_TECHNOLOGY_PROFILE` | 08 부분결과 배너 | `partial === true`일 때만 `StateCard kind="PARTIAL"`. `missingScope`를 문장으로 잇는다 |
| `KAFKA_EVIDENCE` | 09 근거 표 | `EvidenceProofRows`가 **`scopeType`으로 두 그룹으로 쪼갠다**(PERSONAL / REPOSITORY). `factType` 5종 → `DEP`·`IMP`·`CFG`·`IMPL` 배지로 매핑, `commitSha`는 앞 7자만 |
| `KAFKA_LEVEL_LADDER` | 09 `L2가 되려면?` | 계약의 `unmetRules`·`nextActions`가 같은 내용을 다른 모양으로 주는데 어느 쪽으로 화면을 만들지 정하기 전이라 별도로 둔다 |
| `TARGET_ROLES` | 16 직무 카드 3장 | 막대 분모가 **그 직무의 공고 수**다(87 / 34 / 29). 전체 공고를 분모로 쓰면 직무 간 비교가 되어 버린다 |
| `JOB_MATCH_ALL/FILTERED/EMPTY` | 02 전체 본문 | `pickScenario(region, career)`가 셋 중 하나를 고른다. 전체·전체 → ALL, 부산·1~3년 → EMPTY, 나머지 → FILTERED. **실제 필터링을 화면이 계산하지 않는다** |
| 〃 `gaps` | 02 우측 Gap 카드 | 막대 분모가 `gaps[0].requiredCount`다. 1위 대비 상대 길이 |
| `JobPostingFixture` | 02 공고 카드 · 드로어 | `SegmentBar`가 요구 기술 수만큼 칸을 나눈다. 퍼센트 하나로 합치지 않는 이유는 4개 중 3개와 8개 중 6개가 같은 75%라도 다른 상황이기 때문 |
| `SKILL_GAP_GROUPS` | 17 표 본문 | 판정 4묶음을 그대로 렌더. `fillDelta`가 `null`(미판정) / `0`(채워도 안 늘어남) / 양수로 갈린다 — 셋을 같게 그리면 사실이 뭉개진다 |
| `SKILL_GAP_SUMMARY` | 17 KPI 4칸 | `요구 기술 = 충족 + 부족 + 판단 근거 부족`이 성립해야 한다. 화면이 합을 만들지 않는 이유는 서버 값과 어긋났을 때 그 사실이 감춰지기 때문 |
| `NEXT_SKILLS` | 10 · 03 · 17 하단 · 11 상단 | **네 화면이 같은 배열을 본다.** 따로 두면 화면마다 숫자가 어긋난다. 10은 `[0]`을 크게 + 나머지를 작게, 03은 `?tech=`로 하나를 고르고, 17은 상위 3개만, 11은 `find(techId)`로 축 3개를 채운다 |
| 〃 증가분 | 10 · 03 · 11 | `projectedFullMatch - currentFullMatch`를 **화면에서 뺀다.** 원칙 위반이고(서버가 줘야 하는 값) 레이아웃에 `+15` 자리를 확인하려는 임시 수단이다. API가 붙으면 지운다 |
| `CURRENT_STATE` 외 5개 | 11 탭 4개 | `skill?.techId === 'kafka'`일 때만 탭을 그린다. 내용이 없으면 전환할 것이 없어 탭이 빈 컨트롤이 된다. 탭 선택은 `?tab=`에 실린다 |
| `TREND_SOURCES` | 12 출처 카드 3장 | 막대 분모가 **그 출처의 1위 값**이다. 출처 간 길이를 비교할 수 있게 만들면 "합치지 않는다"는 규칙을 화면이 깬다. 상세 링크는 행의 `techId`를 쓴다(표시 이름에서 만들지 않는다) |
| `TECH_TRENDS` | 13 시계열 + 보조 패널 | `findTechTrend(techId)` → `[primary, ...others]`로 쪼갠다. 첫 계열만 막대로 그리고 나머지는 상태 카드다. 막대 높이 분모는 그 계열의 최대값 — 출처끼리 한 축에 겹치지 않는다. **라이브러리는 Innovation Graph가 `NOT_SUPPORTED`, 언어는 월별이 아닌 분기별**이다 |
| `GROWTH_STAGES` | 13 최상단 S6 카드 | `findGrowthStage(techId)`로 하나를 고른다. stepper는 **현재 단계만** 칠한다 — 단계는 달성도가 아니라 분류다. 초안의 `쇠퇴기`는 값 목록에서 뺐다(기술을 쇠퇴한다고 단정하지 않는다) |
| `ANALYSIS_STEPS` | 07 단계 4칸 | `AnalysisStepList`가 자기 단계 이름과 fixture를 index로 짝짓는다. fixture가 없으면 이름만 남는다 |
| `ANALYSIS_RUNNING` / `_RATE_LIMITED` | 07 진행률 블록 | 화면의 토글이 둘 중 하나를 고른다. **같은 타입을 붙인 이유**는 추론에 맡기면 `status`가 리터럴로 좁혀져 전환이 타입 오류가 되기 때문 |
| `ACCOUNT_CONNECTIONS` | 14 계정 · 연결 | `CONNECTIONS` 배열의 index 0·1을 `ssafy`·`github`에 짝짓는다. `SIGNED IN`·`CONNECTED`는 사실을 주장하는 값이라 fixture가 없으면 배지를 그리지 않는다 |
| `ANALYSIS_HISTORY` | 14 이력 표 | 상태 3종을 서로 다른 톤으로. `JobStatus` 컴포넌트를 쓰지 않는 이유는 `PARTIAL`이 그 enum에 없어서다 |
| `REPOSITORY_LIST` | 06 저장소 목록 | 조회 상태 전체를 대체한다(위 "공통 관문" 예외). 페이지네이션은 fixture에 다음 페이지가 없어 숨긴다 |

### 화면이 계산하는 것 / 계산하지 않는 것

화면에 남아 있는 계산은 셋뿐이고 전부 **표시 환산**이다.

- `MeterBar`가 `value / total`로 폭을 구한다. 비율을 호출부가 넘기지 않게 분모를 필수로 받는다
- `LEVEL_STEPS`로 Level을 묶음에 배정한다(정책이 아니라 `EVIDENCE_LEVELS` 순서에서 나오는 값)
- `projectedFullMatch - currentFullMatch` — 위 표에 적은 임시 수단

순위·비중·증감·판정·단계는 하나도 화면에서 만들지 않는다. fixture가 이미 계산된 값을
갖고 있고, 그 자리에 서버 응답이 들어오면 된다.

## 지울 때

각 화면의 조회 API가 붙으면 해당 fixture 파일을 지운다. 마지막 fixture가 사라지면
`designFixtures.ts` · `types.ts` · `DesignMockBadge.tsx`와 이 폴더도 함께 지운다.
