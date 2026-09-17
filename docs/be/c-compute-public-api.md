# C 계산 결과 공개 API 계약 (B ↔ FE)

> 기준일: 2026-09-15 · 이슈: `S15P21E102-279` · 브랜치 `Feat/15P21E102-279-be-skill-gap-what-if-api`
>
> 상태: **제안**. 아래 §2의 결정 A~E는 B가 제안하고 FE조·C조 확인을 기다린다.
> 확인 전까지 B는 §2를 전제로 구현하고, 뒤집히면 이 문서와 구현을 함께 고친다.

C가 계산한 공고 매칭·Skill Gap·추천·What-if·Trend를 로그인 사용자에게 내려보내는
공개 API의 URI·DTO·상태·오류를 고정한다. 이 문서 하나로 FE와 B가 동시에 착수할 수
있게 하는 것이 목적이다.

원본 계약은 순서대로 [C 계산 실행·저장 계약](../ai/c-compute-runtime.md),
[B ↔ C Compute 연결 인수](../ai/c-compute-backend-integration.md)이고, 실제 계약의
원본은 문서가 아니라 운영 C의 `GET /internal/v1/c/contracts`가 생성하는 JSON Schema다.
이 문서가 그것과 어긋나면 C 구현이 옳다.

## 1. 경계 — B가 하는 일과 하지 않는 일

B가 하는 일은 넷뿐이다.

1. 로그인·소유권 확인 (`user_id`는 세션에서만 정한다)
2. 사용자별 최신 analysis/cohort/recommendation 선택
3. C 응답을 FE DTO로 변환
4. 페이징 변환과 C 오류 → 화면 상태 변환

B가 **하지 않는** 것:

- 추천 점수·순위 재계산
- 공고 부합 여부 판정
- Skill Gap 판정
- What-if 증가 건수 계산
- Trend 수치 계산이나 출처 합성

C가 주지 않는 수치는 만들지 않고 `null`로 내려보낸다. 비어 있는 자리를 0으로 채우면
화면이 "측정했더니 0이었다"로 읽는다. §6에 C가 현재 주지 않는 값을 모아 두었다.

## 2. 결정 A~E

### A. C에 보낼 `analysis_id`와 `event_id` — 사용자 Evidence 버전을 새로 만든다

문제: BE의 분석 단위는 **저장소 한 건**이다(`AnalysisJob` 하나에 `repository_id`
하나). 반면 C의 `POST /internal/v1/c/analyses/completed`는 사용자 전체 Evidence와
`personal_assessments`를 한 번에 받는다. 저장소 완료 이벤트마다 그대로 C를 부르면
저장소 3개를 분석한 사용자에게 C 호출 3번과 RECOMMENDATION Snapshot 3개가 생기고,
마지막 것만 맞다.

결정: 사용자 단위 **Evidence 버전**을 BE가 새로 정의한다.

```text
evidenceVersion = sha256(
  userId ␟ registryVersion ␟ levelPolicyVersion
  ( ␞ repositoryId ␟ repositoryAnalysisId ␟ commitSha )*   -- repositoryId 오름차순
)
```

근거 내용은 재료에 넣지 않는다. 같은 분석에서 나온 근거는 같은 내용이라 값이 달라지지
않고, 넣으면 해시 비용만 근거 수만큼 늘어난다. 시각과 난수도 넣지 않는다 — 넣는 순간
재시작할 때마다 event ID가 달라져 C가 같은 계산을 다시 한다.

- 대상은 해당 사용자의 **저장소별 최신 종료 분석**이다. 같은 저장소의 옛 분석은 들어가지 않는다.
- C에 보내는 `analysis_id`는 `u{userId}-{evidenceVersion 앞 32자}`로 만든다.
  C의 `Identifier`는 `^[A-Za-z0-9][A-Za-z0-9._:-]*$`, 128자 이하라 이 형식이 통과한다.
- `user_id`는 로그인 사용자 PK의 문자열 표현이다. 요청 파라미터에서 읽지 않는다.

`event_id`는 다음 네 가지로 만든다.

```text
event_id = "ev-" + sha256(userId, evidenceVersion, cohortSnapshotId, computeVersions)
```

`computeVersions`를 재료에 넣는 이유가 있다. C는 Registry나 알고리즘 버전이 바뀐 뒤
같은 `event_id`로 다시 계산하려 하면 409 `IDEMPOTENCY_CONFLICT`를 준다. 버전을 재료에
넣어 두면 배포로 버전이 바뀐 순간 event_id가 저절로 달라져 그 충돌을 만들지 않는다.
값은 바로 앞 `job-cohorts/resolve` 응답의 `compute_versions`를 그대로 쓴다.

재시작·재전달에도 같은 값이 나오므로 중복 계산이 생기지 않는다. 저장은 다음 표에
`event_id` UNIQUE로 한 번 더 막는다.

구현은 `V16__c_compute_sync.sql`이다.

```sql
CREATE TABLE user_c_snapshot (
    user_id                    BIGINT       NOT NULL REFERENCES "user"("user_id"),
    evidence_version           VARCHAR(64)  NOT NULL CHECK (evidence_version ~ '^[0-9a-f]{64}$'),
    cohort_snapshot_id         VARCHAR(80)  NOT NULL,
    demand_snapshot_id         VARCHAR(80)  NOT NULL,
    recommendation_snapshot_id VARCHAR(80)  NOT NULL,
    event_id                   VARCHAR(80)  NOT NULL,
    target_key                 VARCHAR(200) NOT NULL,
    computed_at                TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (user_id, evidence_version, cohort_snapshot_id),
    UNIQUE (event_id)
);
```

`demand_snapshot_id`를 함께 보관한다. COHORT와 DEMAND는 같은 회차의 쌍이고, 공개 API가
수요 집계를 읽을 때 그 쌍의 DEMAND를 써야 추천 수치와 분모가 맞는다.

`recommendation_snapshot_id`는 C 응답 `results`에서 `kind=RECOMMENDATION`인 것을 쓴다.
이 ID는 **응답에 내려보내지 않는다**(결정 C).

### B. 목표 직무는 서버에 저장한다 — `GET/PUT /api/v1/me/target` 신설

cohort resolve에는 `target_role`·`regions`·`career_levels`가 필요한데, 분석 완료 훅은
브라우저 없이 서버에서 돈다. 화면 쿼리 파라미터로만 받으면 완료 시점에 직무를 모른다.

구현은 `V16__c_compute_sync.sql`이다.

```sql
CREATE TABLE user_target (
    user_id       BIGINT       PRIMARY KEY REFERENCES "user"("user_id"),
    target_role   VARCHAR(60)  NOT NULL CHECK (length(trim(target_role)) > 0),
    regions       VARCHAR(200) NOT NULL DEFAULT '',   -- 쉼표 구분, 빈 값은 전체
    career_levels VARCHAR(200) NOT NULL DEFAULT '',
    updated_at    TIMESTAMPTZ  NOT NULL
);
```

계산을 트리거하는 지점은 둘이다.

1. 사용자 분석이 종료되어 Evidence 버전이 바뀌었을 때 (목표 직무가 이미 있는 경우)
2. `PUT /api/v1/me/target`으로 직무·필터가 바뀌었을 때

목표 직무가 없는 사용자의 공개 API는 오류가 아니라 `404 MATCH-404-1`이다. FE는 이
코드를 "목표 직무를 먼저 고르세요" CTA로 처리한다(`SHOW_EMPTY_WITH_CTA`).

지역·경력을 B에서 목록만 잘라내지 않는다. 필터가 바뀔 때마다 같은 조건으로 resolve를
다시 호출해 COHORT·DEMAND를 함께 받는다. 그렇게 하지 않으면 추천 수치의 분모와 공고
목록의 분모가 달라진다.

### C. FE는 어떤 식별자도 전달하지 않는다 — 캐시 키를 `targetKey`로 바꾼다

현재 [`queryKeys.ts`](../../FE/src/shared/api/queryKeys.ts)는
`matching(analysisId, target)` 형태로 `analysisId`를 키에 넣는다. 요구사항은 FE가
사용자 ID·Snapshot ID를 임의로 전달하지 않는 것이고, 최신 분석 선택도 B가 하므로 FE가
`analysisId`를 알아야 할 이유가 없다.

결정:

- 요청에 `analysisId`·`snapshotId`·`userId`를 **넣지 않는다**. 경로에도 쿼리에도 없다.
- 응답에도 C Snapshot ID를 **내려보내지 않는다**. 내려보내면 FE가 그것을 다시 보내는
  경로가 생기고, 그 경로는 곧 남의 Snapshot ID를 넣어 보는 시도가 된다.
- 캐시 무효화 단위는 서버가 정한 `targetKey`다. `GET /api/v1/me/target` 응답이 주는
  정규화 문자열이며(`BACKEND|서울|신입` 형태), 직무·필터가 바뀌면 값이 달라진다.

```ts
matching:        (targetKey: string) => ['matching', targetKey] as const,
matchingSkillGap:(targetKey: string) => ['matching', targetKey, 'skill-gap'] as const,
matchingPostings:(targetKey: string, params: PageParams) =>
  ['matching', targetKey, 'postings', params] as const,
matchingWhatIf:  (targetKey: string, techId: string) =>
  ['matching', targetKey, 'what-if', techId] as const,
```

증거 계열 키(`analysis`·`myTechnologies`)는 그대로 둔다. 그쪽은 `analysisId`가 계약의
일부이고 이미 구현된 API가 쓴다.

### D. 페이징은 BE 기존 규약을 따르고 C 쪽은 BE가 변환한다

| 층 | 형태 |
|---|---|
| 공개 API | `page`(1-base, 기본 1) · `perPage`(기본 20, 최대 50) · `hasNext` |
| C 내부 API | `page`(0-base) · `size`(1~50) |

변환은 `page - 1`, `size = min(perPage, 50)`. FE는
[`PageResponse`](../../FE/src/shared/types/api.ts)를 그대로 쓴다. 목록마다 다른 파서를
만들지 않기 위해 [열린 질문 2-6](../fe/cross-team-open-questions.md)을 여기서 닫는다.

`totalCount`는 C가 주는 목록(`matching-job-postings`, `job-postings`)에만 있으므로
`PageResponse`에 얹지 않고 각 응답의 `summary`에 둔다.

### E. 상태와 오류 — 200 + 상태값과 5xx를 분리한다

"계산 대기 / 미준비 / 일시 장애"를 구분하라는 요구를 다음으로 만족시킨다. 계산 계열
응답은 모두 `dataStatus`와 `statusReason`을 가진다. `dataStatus`는 FE에 이미 있는
[`DataStatus`](../../FE/src/shared/types/domain.ts) 7종을 그대로 쓰고, 값을 늘리지
않기 위해 사유는 별도 필드로 둔다.

```json
{
  "dataStatus": "PREPARING",
  "statusReason": "COHORT_NOT_PREPARED",
  "retryAfterSec": 2,
  "basis": { "targetRole": "BACKEND", "regions": [], "careerLevels": [],
             "asOf": "2026-09-15T22:30:04Z", "jobCount": 13,
             "inputJobCount": 1744, "matchingJobCount": 253,
             "duplicateJobCount": 0, "excludedJobCount": 1452,
             "reviewJobCount": 279 },
  "...": "기능별 payload"
}
```

`jobCount`는 요구 기술을 엄격히 해석할 수 있어 수요 비율의 분모가 된 공고 수다.
`inputJobCount`는 중복·품질·직무 필터 전 관측 입력이고, `matchingJobCount`는
직무·상태·지역·경력 필터를 통과해 상세 비교 후보로 남은 수다. 셋을 모두
"비교 대상 공고"라고 부르지 않는다. 과거 C snapshot에는 뒤의 다섯 필드가 없어
`null`일 수 있다.

`statusReason` 값: `NONE` `COMPUTING` `COMPUTE_PENDING` `COMPUTE_RETRYING`
`COMPUTE_INVALID_INPUT` `COMPUTE_IDEMPOTENCY_CONFLICT` `COMPUTE_RETRY_EXHAUSTED`
`COHORT_NOT_PREPARED` `MATCHING_NOT_PREPARED` `NO_CANDIDATES`
`INSUFFICIENT_JOB_SAMPLE` `INSUFFICIENT_EVIDENCE` `PARTIAL_ANALYSIS`
`RESULT_TOO_LARGE`. `COMPUTE_*` terminal 사유는 같은 Evidence·목표 조합에서 GET을
반복해도 유지되며, 새 Evidence나 목표 변경으로 identity가 바뀌어야 새 계산이 시작된다.

C 응답 → 공개 응답 변환표. **C 장애를 전부 500으로 뭉개지 않는다.**

| C | 뜻 | 공개 API | FE 처리 |
|---|---|---|---|
| resolve `202 PREPARING` | 같은 selector 계산 중 | `200` `PREPARING`/`COMPUTING` + `retryAfterSec` | 계산 중 안내, Retry-After 간격 폴링 |
| resolve `404 COHORT_NOT_PREPARED` | Worker 첫 poll 전이거나 입력 차단 | `200` `PREPARING`/`COHORT_NOT_PREPARED` | 준비 중 안내, 폴링 간격 길게 |
| matching `409 JOB_MATCHING_NOT_PREPARED` | 구 결과에 매칭이 없음 | `200` `PREPARING`/`MATCHING_NOT_PREPARED` | 준비 중 안내 |
| recommendation `status=NO_CANDIDATES` | 정상 결과, 후보 0 | `200` `READY`/`NO_CANDIDATES`, 목록 빈 배열 | 빈 상태 문구 |
| recommendation `status=PARTIAL` | 일부 저장소 미분석 | `200` `PARTIAL`/`PARTIAL_ANALYSIS` | 부분 분석 배지 + 값 표시 |
| recommendation `status=INSUFFICIENT_DATA` | 공고 표본 부족 | `200` `INSUFFICIENT_DATA`/`INSUFFICIENT_JOB_SAMPLE` | 표본 부족 안내 |
| recommendation `status=INSUFFICIENT_EVIDENCE` | Evidence 부족 | `200` `INSUFFICIENT_DATA`/`INSUFFICIENT_EVIDENCE` | 분석 추가 CTA |
| trends `404 TREND_NOT_PREPARED` | 그 출처에 완료 head 없음 | `200` `NO_DATA` (해당 출처 카드만) | 출처 카드에 "데이터 없음" |
| `422 INVALID_INPUT` | 지원하지 않는 직무·필터·비활성 기술 | `400 MATCH-400-1` / `TREND-400-1` | 인라인 오류 |
| snapshot `404` (없음·타인) | 존재 여부를 노출하지 않음 | `404 MATCH-404-2` | 404 화면 |
| `413 INPUT_TOO_LARGE` / `RESULT_TOO_LARGE` | 예산 초과 | `200` `FAILED`/`RESULT_TOO_LARGE` | 표시 불가 안내 |
| `403 EVIDENCE_SCOPE_MISMATCH` | B가 잘못 만든 요청 = B 버그 | `500 G-500` + ERROR 로그 | 일반 오류 |
| `409 IDEMPOTENCY_CONFLICT` | 같은 event로 내용이 바뀜 | 내부 처리(§3.3) | — |
| `500 COMPUTE_FAILED` | 같은 event 재시도 가능 | `503 MATCH-503-1` | 재시도 버튼 |
| `500 STORED_MATCHING_INTEGRITY_FAILED` | 저장 결과 무결성 실패 | `500 G-500` + ERROR 로그 | 일반 오류 |
| `503 C_*_UNAVAILABLE` / 연결 실패 / 타임아웃 | C 일시 장애 | `503 MATCH-503-1` | 재시도 버튼 |
| `401` (토큰 불일치) · C 미설정 | 배포 설정 오류 | `503 MATCH-503-1` + ERROR 로그 | 재시도 버튼 |

`ErrorCode`에 추가할 값:

```java
TARGET_ROLE_NOT_SELECTED (404, "MATCH-404-1", "목표 직무를 먼저 선택해 주세요.")
MATCHING_RESULT_NOT_FOUND(404, "MATCH-404-2", "매칭 결과를 찾을 수 없습니다.")
MATCHING_CRITERIA_INVALID(400, "MATCH-400-1", "지원하지 않는 직무 또는 필터입니다.")
COMPUTE_UNAVAILABLE      (503, "MATCH-503-1", "분석 계산 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
TREND_CRITERIA_INVALID   (400, "TREND-400-1", "지원하지 않는 기술 또는 기간입니다.")
```

FE [`errorCodes.ts`](../../FE/src/shared/api/errorCodes.ts)에 붙일 매핑:

| 코드 | action |
|---|---|
| `MATCH-404-1` | `SHOW_EMPTY_WITH_CTA` |
| `MATCH-404-2` | `SHOW_NOT_FOUND` |
| `MATCH-400-1` · `TREND-400-1` | `SHOW_INLINE_ERROR` |
| `MATCH-503-1` | `SHOW_RETRY` |

## 3. BE 내부 흐름

> 구현됨(2026-09-15). `compute` 패키지의 `UserEvidenceAssembler`(조립),
> `CComputeSyncService`(호출·저장), `UserEvidenceStore`·`UserTargetStore`·
> `ComputeSnapshotStore`(질의)와 `RepositoryAnalysisResultConsumer`의 훅이다.

### 3.1 트리거

```text
저장소 분석 종료(SUCCEEDED 또는 허용된 부분 성공)
  → 기여 판정(EvidenceAuthorshipService) 시도 종료
  → analysis_job.compute_ready_at 기록
  → 사용자 Evidence 버전 재계산
  → 목표 직무가 있으면 C 동기화 큐에 적재
```

기여 판정 **뒤에** 부르는 이유는 `personal_assessments` 때문이다. 기여 판정은 GitHub를
호출하므로 결과 저장 트랜잭션 밖에서 돈다(`AnalysisResultService`의 주석). 그전에 C를
부르면 개인 판정이 비어 있는 Evidence로 추천이 계산된다.

`SUCCEEDED`는 Evidence 저장 완료이고 기여 판정 완료가 아니다. 둘은 서로 다른
트랜잭션이므로 V23부터 `compute_ready_at`을 별도 marker로 저장한다. 복구 스케줄러는
최신 성공 분석 모두에 이 값과 Rule Pack 계보가 있을 때만 사용자를 선택한다. consumer가
두 단계 사이에서 종료되면 미커밋 Kafka event가 재배달되고, 이미 `SUCCEEDED`인 잡이라도
`compute_ready_at IS NULL`이면 기여 판정부터 재개한다. GitHub 장애로 판정이 실패한 경우도
시도 종료를 기록한 뒤 미확인 근거로 계산한다.

부분 성공 판정: `RepositoryEvidence.status`가 `COMPLETE`인 저장소가 하나 이상 있으면
`EvidenceAnalysis.status = PARTIAL`로 보낸다. 하나도 없으면 C를 부르지 않는다. BE에는
아직 `PARTIAL_SUCCEEDED` 잡 상태가 없으므로(열린 질문 2-3) 저장소별 상태에서 만든다.

### 3.1-a 결과 계약 — v1과 v3를 함께 받는다

워커는 Registry 버전에 따라 발행 계약을 **바꾼다**. v1을 함께 보내지 않으므로
(`AI/analysis/consumer.py`의 publisher 선택), `registry-20260911.3/.4` 환경에서 v1만
구독하면 결과가 통째로 도달하지 않고 분석이 QUEUED에 남는다. 그러면 이 문서의 나머지도
전부 동작하지 않는다.

| 계약 | 추가로 싣는 것 | BE 저장 위치 |
|---|---|---|
| v1 | — | 기존 |
| v2 | `rule_pack_version`·`rule_pack_content_sha256`·`technology_support`·`stats.skipped_reasons` | `analysis_job`, `analysis_technology_support` |
| v3 | v2 + `SYNTAX_NODE` fact type, `syntax_node_count` | 같음 (`analysis_evidence.fact_type`은 제약이 없어 그대로 들어간다) |

v4는 열지 않았다. 개인 귀속(`personal_assessments`)이 붙는 계약이고 저장할 자리가
없다. 열려면 저장 경로를 먼저 만든다 — 반쯤 해석한 결과를 저장하면 그 사실이 어디에도
남지 않는다.

구독 토픽은 `gitjob.kafka.topics.repository-analysis.results-v3`이며 워커와 같은 환경
변수(`KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V3`)를 쓴다. 비어 있으면 구독하지 않는다.

### 3.1-b Rule Pack 계보를 보존한다

C가 근거의 범위를 검사할 때 보는 값은 Registry 버전이 아니라 **Rule Pack** 버전이다
(`evidence_rule_version`, 각 proof의 `rule_version`). 그 자리에 Registry 버전을 넣으면
C가 모든 근거를 범위 불일치로 버리는데, **오류가 나지 않는다** — 화면에는 "근거는 있는데
전부 미판정"으로만 보인다.

| 값 | 어디서 오는가 | 하지 말아야 할 것 |
|---|---|---|
| `evidence_rule_version` | `analysis_job.rule_pack_version` | Registry 버전으로 대체 |
| `coverage_complete` | `status=SUCCEEDED` **그리고** `skipped_reasons`가 보고됐고 비어 있음 | 성공만으로 참 |
| `evaluated_tech_ids` | 그 분석의 `technology_support` 중 `coverage != UNSUPPORTED` | Registry 전체 |
| `assessment_ceiling` | `max_supported_level`, 귀속이 불완전하면 L1로 하향, 개인 판정 아래로는 내리지 않음 | 관측된 최고 Level |

`skipped_reasons`는 NULL과 `{}`를 구분한다. v1에는 필드가 없어 NULL이고, 그것은 "건너뛴
것이 없다"가 아니라 "모른다"이다. 같게 다루면 저장소 일부만 본 분석이 완전 판정으로
나간다.

### 3.1-c 보낼 수 없는 이유를 구분한다

Evidence가 0건이어도 보낸다. "분석했지만 등록 기술이 관측되지 않았다"와 "분석하지
않았다"는 다른 사실이고, 앞은 Skill Gap과 추천을 받을 자격이 있다. 판정 기준을 근거
행이 아니라 분석에 붙인 것이 그것을 가능하게 한다.

보내지 못하는 경우는 셋이며, 화면 상태가 다르다.

| 이유 | 뜻 | 화면 |
|---|---|---|
| `NO_ANALYSIS` | 성공한 분석이 없다 | `NO_DATA` · 분석 시작 CTA |
| `NO_RULE_PACK_LINEAGE` | v1 결과만 있어 Rule Pack을 모른다 | `FAILED`/`REANALYSIS_REQUIRED_NO_RULE_PACK` |
| `MIXED_RULE_PACK` | 저장소마다 다른 Rule Pack | `FAILED`/`REANALYSIS_REQUIRED_MIXED_RULE_PACK` |

아래 둘은 기다려서 풀리지 않는다. 무기한 `PREPARING`으로 두면 화면이 영원히 기다리고
사용자는 무엇을 해야 하는지 알 수 없다.

### 3.2 호출 순서

```text
POST /internal/v1/c/job-cohorts/resolve     (job-cohort-resolve-selector/v1)
  → cohort_snapshot_id, demand_snapshot_id, criteria, compute_versions
POST /internal/v1/c/analyses/completed      (c-compute-event/v1 + evidence-consumption-input/v4)
  → results[kind=RECOMMENDATION].snapshot_id
→ user_c_snapshot upsert
```

`evidence-consumption-input/v4`에서 지킬 것:

- 개인 종합은 top-level `personal_assessments`에만 둔다. v4는 repository 기술의
  `personal_level`이 하나라도 있으면 검증에서 거부한다.
- `assessment_ceiling`, `attribution_status`, `missing_scope`를 보존한다.
  `attribution_status != COMPLETE`면 `missing_scope`가 비어 있으면 안 된다.
- `personal_level`은 `assessment_ceiling`을 넘을 수 없다.
- `commit_sha`는 40자 소문자 hex여야 한다.
- `coverage_complete=true`는 `status=COMPLETE`일 때만 허용된다.

### 3.3 재시도와 충돌

- 같은 event 재전달: C가 저장된 결과를 그대로 준다. 그대로 저장한다.
- `409 IDEMPOTENCY_CONFLICT`: 이미 `user_c_snapshot` 행이 있으면 그것을 쓰고 끝낸다.
  없으면 resolve부터 다시 해서 `compute_versions`를 새로 받고, 그래도 409면 WARN 로그를
  남기고 중단한다. 같은 event를 무한히 다시 만들지 않는다.
- `202 PREPARING`: `Retry-After`를 따르고 같은 event로 재시도한다. 공개 API는 그동안
  `PREPARING`을 내려보낸다.
- **조회는 재시도하지 않는다.** 계산 시작점은 분석 완료와 목표 직무 변경뿐이다.
  `ComputeResultReader`는 Snapshot과 `user_c_compute_attempt` 상태를 읽기만 하므로 화면
  새로고침이 C outbound 요청이나 event attempt를 늘리지 않는다.
- 일시 오류만 최대 3회까지 다시 claim할 수 있다. 실행 중 lease와 `Retry-After` 또는
  지수 backoff 전에는 같은 Evidence·목표 조합을 다시 보내지 않는다. 상한에 도달하면
  `FAILED/COMPUTE_RETRY_EXHAUSTED`로 고정한다.
- 각 실행은 `run_token`을 새로 발급한다. 상태 변경과 정리는 이 token이 같은 행에만
  적용하므로, 행이 삭제·재생성된 뒤 돌아온 이전 worker가 새 실행을 덮어쓰지 못한다.
  목표나 Evidence가 바뀐 경우에도 사용자 전체 행을 지우지 않고 스케줄러가 읽었던
  정확한 이전 token만 정리한다.
- `422 INVALID_INPUT`, 두 번째 `409 IDEMPOTENCY_CONFLICT`, 범위·무결성 오류는 즉시
  terminal 상태로 저장한다. 공개 GET은 각각의 안정적인 `COMPUTE_*` 사유를 200 응답의
  `FAILED` 상태로 노출하고 자동 계산을 시작하지 않는다.

### V22/V23 기존 미완료 사용자 복구

V22 attempt가 없더라도, V23 복구 스케줄러는 목표와 성공 분석은 있지만 Snapshot과
attempt가 없는 사용자를 제한된 배치로 시작한다. 단 최신 성공 분석이 모두
`compute_ready_at IS NOT NULL`이고 Registry/Rule Pack 계보가 있어야 한다. 계보 없는 v1
사용자는 재분석이 필요하므로 LIMIT 후보에서 제외되어 뒤의 정상 사용자를 막지 않는다.
아래 진단은 배포 전후 대상 확인용이다.

```sql
WITH latest_analysis AS (
    SELECT DISTINCT ON (a.user_id, a.repository_id)
           a.user_id, a.repository_id, a.completed_at, a.compute_ready_at,
           a.registry_version, a.rule_pack_version
    FROM analysis_job a
    WHERE a.status = 'SUCCEEDED'
    ORDER BY a.user_id, a.repository_id, a.completed_at DESC NULLS LAST
), ready_user AS (
    SELECT user_id, max(completed_at) AS completed_at
    FROM latest_analysis
    GROUP BY user_id
    HAVING bool_and(compute_ready_at IS NOT NULL)
       AND bool_and(nullif(btrim(registry_version), '') IS NOT NULL)
       AND bool_and(nullif(btrim(rule_pack_version), '') IS NOT NULL)
), latest_input AS (
    SELECT t.user_id,
           t.target_role || '|' || t.regions || '|' || t.career_levels AS target_key,
           greatest(t.updated_at, r.completed_at) AS input_at
    FROM user_target t
    JOIN ready_user r ON r.user_id = t.user_id
)
SELECT i.user_id, i.target_key, i.input_at
FROM latest_input i
WHERE NOT EXISTS (
          SELECT 1 FROM user_c_snapshot s
          WHERE s.user_id = i.user_id AND s.target_key = i.target_key
            AND s.computed_at >= i.input_at
      )
  AND NOT EXISTS (
          SELECT 1 FROM user_c_compute_attempt a WHERE a.user_id = i.user_id
      )
ORDER BY i.user_id;
```

결과가 있으면 먼저 최신 분석의 `compute_ready_at`, `registry_version`,
`rule_pack_version`을 함께 확인한다. 준비된 사용자는 스케줄러가 시작하고, 계보 없는
사용자는 재분석 대상으로 남긴다. GET 호출로 복구하지 않는다. 운영 DB에서 이 목록이
비어 있는지는 배포 승인 전에 별도로 확인한다.

## 4. 공개 API

> 구현됨(2026-09-15). `compute.controller`의 `MeMatchingController`(개인 계열)와
> `MarketController`(공용 계열)이며, C 호출은 `CComputeApi`, 상태 변환은
> `ComputeResultReader`가 한다. 아래와 다른 점은 §6에 적었다.

모든 응답은 기존 봉투 `{message, data}`이고, 실패는 `{code, message}`다.
`/api/v1/me/**`는 로그인 필수, `user_id`는 세션에서만 온다. `SecurityConfig`의
`anyRequest().authenticated()`가 적용되므로 별도 규칙을 추가하지 않았다.

### 4.1 `GET /api/v1/me/target` · `PUT /api/v1/me/target`

```json
{ "targetRole": "BACKEND", "regions": ["서울"], "careerLevels": ["신입"],
  "targetKey": "BACKEND|서울|신입", "updatedAt": "2026-09-15T01:30:00Z" }
```

PUT 본문은 `targetRole`·`regions`·`careerLevels`. 저장 후 C 동기화를 트리거하고
`202`가 아니라 `200`으로 저장 결과를 돌려준다. 계산 진행은 조회 API의 `dataStatus`로
드러난다.

### 4.2 `GET /api/v1/me/job-matches` — 공고 매칭 목록 (화면 02)

쿼리: `page`, `perPage`, `includeConditional`(기본 `false`)

C 원천: `GET /internal/v1/c/recommendations/{snapshotId}/matching-job-postings`

```json
{
  "dataStatus": "READY", "statusReason": "NONE", "retryAfterSec": null,
  "basis": { "targetRole": "BACKEND", "regions": [], "careerLevels": [],
             "asOf": "2026-09-15T22:30:04Z", "jobCount": 13,
             "inputJobCount": 1744, "matchingJobCount": 253,
             "duplicateJobCount": 0, "excludedJobCount": 1452,
             "reviewJobCount": 279 },
  "summary": {
    "totalCount": 253,
    "fullMatchCount": 12,
    "nearMatchCount": null,
    "lowMatchCount": null,
    "conditionalCount": 5,
    "excludedConditionalCount": 5
  },
  "dataGaps": ["JOB_LEVEL_REQUIREMENT_UNRESOLVED"],
  "page": 1, "perPage": 20, "hasNext": true,
  "items": [{
    "jobId": "...", "title": "...", "companyName": "...",
    "sourceSite": "saramin", "sourceUrl": "https://...",
    "region": "서울", "careerLevel": "신입", "deadline": "2026-09-26T14:59:59Z",
    "eligibility": "ELIGIBLE",
    "requiredStatus": "PARTIAL",
    "fulfillmentRatio": 0.75,
    "required": { "satisfiedCount": 3, "unsatisfiedCount": 1, "unknownCount": 0,
                  "clauses": [{ "mark": "HAVE", "techIds": ["spring"],
                                "heldTechIds": ["spring"], "missingTechIds": [],
                                "unknownTechIds": [] }] },
    "preferred": { "...": "required와 같은 모양" }
  }]
}
```

- `fullMatchCount`는 RECOMMENDATION Snapshot의 `current_count`다.
- `nearMatchCount`·`lowMatchCount`는 **C가 주지 않는다**(§6-1). `null`로 내려보내고
  FE는 그 칸을 그리지 않는다. 비율로 직접 세지 않는다 — 그게 부합 판정 재계산이다.
- `mark`는 clause의 `status`를 그대로 옮긴 것이다.
  `SATISFIED→HAVE`, `UNSATISFIED→NONE`, `UNKNOWN→UNKNOWN`.
  **`UNKNOWN`을 `NONE`으로 접지 않는다.** FE `RequirementMark`에 `UNKNOWN`을 추가해야
  한다(현재 `HAVE|WEAK|NONE` 3종). `WEAK`는 요구 Level 미달을 뜻하며 clause의
  `verdict`에 레벨 미달이 담긴 경우에만 쓴다.
- `includeConditional=false`면 `totalCount`는 `eligible_count`다. 제외된 건수를
  `excludedConditionalCount`로 함께 준다 — 목록에서 사라진 공고가 몇 건인지 화면이
  말할 수 있어야 한다.

### 4.3 `GET /api/v1/me/job-matches/{jobId}` — 공고 매칭 상세 (화면 16 drawer)

C 원천: `.../matching-job-posting?job_id=`. 항목 모양은 4.2의 `items[]`와 같고
`unresolved`(요구 해석 실패 절) 배열이 추가된다. 없는 `jobId`는 `404 MATCH-404-2`.

### 4.4 `GET /api/v1/job-demands` — 직무별 기술 수요

쿼리: `targetRole`(필수), `regions`, `careerLevels`, `limit`(기본 20, 최대 50)

C 원천: `job-cohorts/resolve` → `GET /internal/v1/c/snapshots/{demandSnapshotId}`

```json
{
  "dataStatus": "READY", "statusReason": "NONE",
  "basis": { "targetRole": "BACKEND", "asOf": "2026-09-15T22:30:04Z",
             "jobCount": 13, "inputJobCount": 1744, "matchingJobCount": 253,
             "duplicateJobCount": 0, "excludedJobCount": 1452,
             "reviewJobCount": 279 },
  "technologies": [{
    "techId": "spring", "rank": 1,
    "requiredCount": 54, "preferredCount": 12, "generalCount": 3, "totalCount": 69,
    "requiredRatio": 0.62, "preferredRatio": 0.13, "generalRatio": 0.03, "totalRatio": 0.79
  }]
}
```

개인 결과가 아니므로 로그인만 확인하고 소유권 검사는 없다. 비율은 C가 준 값을 그대로
옮긴다.

### 4.5 `GET /api/v1/me/skill-gap` — Skill Gap (화면 17)

C 원천: RECOMMENDATION Snapshot의 `gap`(`technology-gap/v2`) + `demand` + `personal_levels`

```json
{
  "dataStatus": "READY", "statusReason": "NONE",
  "basis": { "targetRole": "BACKEND", "denominator": 87 },
  "summary": { "requiredTechCount": 18, "metCount": 9,
               "noEvidenceCount": 6, "levelShortCount": 3, "undeterminedCount": 4 },
  "rows": [{
    "techId": "kafka",
    "verdict": "NO_EVIDENCE",
    "requiredCount": 21, "preferredCount": 4,
    "personalLevel": null,
    "assessmentCeiling": "L1",
    "attributionStatus": "PARTIAL",
    "reasonCodes": ["TECHNOLOGY_NOT_EVALUATED"],
    "fillDelta": 7
  }]
}
```

- `verdict`는 C의 `HeldStatus`에서 온다. `HELD→MET`, `UNKNOWN→UNDETERMINED`,
  `NOT_HELD`는 `reasonCodes`에 레벨 미달 사유가 있으면 `LEVEL_SHORT`, 아니면
  `NO_EVIDENCE`. **`UNKNOWN`을 부족으로 세지 않는다** — `summary`의 부족 집계에
  `undeterminedCount`는 들어가지 않는다.
- `fillDelta`는 `candidates[].what_if.increased_count`다. C는 What-if를 **상위 3개
  후보에만** 계산하므로 나머지 행은 `null`이다(§6-2). 행끼리 더하지 않는다.
- `personalLevel`이 `null`인 것은 "미보유"가 아니라 "판정되지 않음"이다.
  `assessmentCeiling`·`attributionStatus`를 함께 내려 화면이 구분할 수 있게 한다.

### 4.6 `GET /api/v1/me/recommendations` — 다음 학습 기술 (화면 10)

C 원천: RECOMMENDATION Snapshot의 `candidates` + `explanation.facts`

```json
{
  "dataStatus": "READY", "statusReason": "NONE",
  "candidates": [{
    "techId": "kafka", "rank": 1,
    "personalLevel": null,
    "evidenceStatus": "NOT_HELD",
    "demand": { "requiredCount": 21, "requiredRatio": 0.24, "rank": 4 },
    "whatIf": { "denominator": 87, "currentCount": 12, "projectedCount": 19,
                "increasedCount": 7 },
    "prerequisiteTechIds": ["java"],
    "missingPrerequisiteTechIds": [],
    "unknownPrerequisiteTechIds": ["docker"],
    "reasonCodes": ["DEMAND_TOP_QUARTILE"],
    "reasons": ["서울 신입 백엔드 공고 87건 중 21건이 Kafka를 필수로 요구합니다."],
    "dataGaps": []
  }]
}
```

`reasons`는 `explanation.facts`에서 해당 `tech_id`의 `text`를 순서대로 옮긴 문장이다.
점수를 노출하지 않는다. `targetLevel`은 C가 주지 않으므로 필드를 두지 않는다(§6-3).

### 4.7 `GET /api/v1/me/recommendations/{techId}/what-if` — What-if와 신규 부합 공고 (화면 03)

쿼리: `page`, `perPage`

C 원천: `GET /internal/v1/c/recommendations/{snapshotId}/job-postings?mode=WHAT_IF&recommended_tech_id={techId}`

```json
{
  "dataStatus": "READY", "statusReason": "NONE",
  "techId": "kafka",
  "counts": { "denominator": 87, "currentCount": 12, "projectedCount": 19,
              "increasedCount": 7 },
  "page": 1, "perPage": 20, "hasNext": false,
  "totalCount": 7,
  "items": [{ "jobId": "...", "title": "...", "companyName": "...",
              "region": "서울", "careerLevel": "신입", "deadline": "...",
              "sourceUrl": "https://..." }],
  "dataGaps": []
}
```

증가 건수와 목록이 **한 응답, 한 호출**에서 나온다. C의 `WHAT_IF` 모드는 신규 증가
공고만 준다. 화면 10의 `increasedCount`와 이 화면의 목록 길이가 어긋나면 그건 표시
버그가 아니라 서로 다른 Snapshot을 읽은 것이다.

### 4.8 `GET /api/v1/technologies/{techId}/trends` — 출처별 Trend (화면 13)

쿼리: `periods`(선택, `2026-06,2026-07,2026-08` 형태), `targetRole`,
`regions`, `careerLevels`. JOB 출처는 `periods`와 `targetRole`이 모두 있어야 조회한다.

C 원천: `POST /internal/v1/c/trends/resolve`를 출처별로 각각 부른 뒤 각 `snapshot_id`로
`GET /internal/v1/c/snapshots/{id}`.

```json
{
  "techId": "kafka",
  "sources": [
    { "sourceId": "GITHUB_WEEKLY", "cSource": "WEEKLY_REPO_ACTIVITY",
      "dataStatus": "READY", "unit": "주간 활동 저장소 수",
      "basis": "공개 저장소 주간 증분", "points": [{"period":"2026-W36","value":128}] },
    { "sourceId": "GITHUB_ARCHIVE", "cSource": "GH_ARCHIVE_HISTORICAL",
      "dataStatus": "PARTIAL", "unit": "월별 commit 관측 수",
      "basis": "2026-06~2026-08", "points": [] },
    { "sourceId": "JOB", "cSource": "JOB_MONTHLY_DEMAND",
      "dataStatus": "READY", "statusReason": "NONE",
      "unit": "월별 공고 요구 건수", "points": [{"period":"2026-08","value":54}] }
  ]
}
```

- 출처는 **배열로 분리해서** 내려보낸다. 합성 점수 필드를 만들지 않는다.
  `WEEKLY_REPO_ACTIVITY`·`GH_ARCHIVE`·`GH_ARCHIVE_HISTORICAL`은 서로 다른 series이고
  JOB은 또 다른 축이다.
- 미완료 기간을 0으로 채우지 않는다. 값이 없으면 `points`가 비고 `dataStatus`가
  `NO_DATA`·`PARTIAL`이 된다.
- 한 출처가 404여도 나머지는 정상 응답한다. 출처 하나의 미준비는 요청 실패가 아니다.
- JOB Trend는 월별 `MONTHLY_DEMAND` cohort를 쓴다. 활성 추천용 DEMAND를 JOB Trend로
  쓰지 않는다(§6-4).
- C의 `JOB` resolve는 기술·월·목표 직무·지역·경력·수집원·최소 표본을 포함한 정확한
  stream identity로 저장 결과를 찾는다. BE는 로그인 사용자의 목표 조건을 그대로 넘기고
  다른 직무의 월별 수요를 대신 고르지 않는다.
- `periods`를 주지 않으면 Archive와 JOB 출처를 부르지 않는다. 서버가 최근 몇 달을 임의로
  고르면 화면에 적힌 기간과 실제 계산 기간이 달라진다.

### 4.9 `GET /api/v1/trends/compare` — 기술 교차 비교 (화면 12)

쿼리: `techIds`(쉼표 구분, 최대 10), `source`(단일 출처 필수), `periods`,
`targetRole`, `regions`, `careerLevels`. `source=JOB`이면 월별 기간과 목표 직무가 필수다.

한 응답에 **한 출처만** 담는다. 여러 출처를 한 표에 섞으면 분모가 다른 값이 한 축에
들어간다. 화면 12는 출처 카드마다 이 API를 따로 호출한다.

```json
{ "sourceId": "JOB", "unit": "월별 공고 요구 건수", "dataStatus": "READY",
  "basis": "서울 · 2026-08",
  "rows": [{ "techId": "spring", "rank": 1, "value": 54, "share": 0.62,
             "previousValue": 50, "direction": "UP" }] }
```

`share`·`direction`은 C 값에서 온다. BE가 두 기간을 빼서 만들지 않는다.

## 5. FE가 지킬 것

- 운영 빌드에서 `withDesignFixture` 결과가 화면에 남지 않는다. `features/`에서
  `@/mocks`를 import하지 않는 것이 최종 상태다.
- `dataStatus`별로 화면을 구분한다: 로딩 / 분석 전(`MATCH-404-1`) / 계산 중(`PREPARING`)
  / 데이터 부족(`INSUFFICIENT_DATA`) / 부분 분석(`PARTIAL`) / 오류(4xx·5xx).
- `UNKNOWN`·`UNDETERMINED`·`personalLevel: null`을 "미보유"로 표시하지 않는다.
- JOB Trend와 GitHub Trend를 한 축·한 점수로 합치지 않는다.
- What-if 증가 건수와 신규 부합 공고 목록은 4.7 한 응답에서 읽는다.
- 기존 Evidence·기술 프로필 화면 연결은 그대로 둔다.

## 6. C가 현재 주지 않는 값 — C조 확인 요청

1. **공고 매칭 KPI 분포.** `matching-job-postings`는 `total_count`·`eligible_count`·
   `conditional_count`만 준다. 화면 02의 "필수 100% / 75~99% / 75% 미만" 3분할을 만들려면
   `required_status`별 집계가 필요하다. B가 페이지를 모아 세면 그게 부합 판정 재계산이라
   하지 않는다. 그때까지 `nearMatchCount`·`lowMatchCount`는 `null`이다.
2. **Skill Gap의 `fillDelta`.** C는 What-if를 상위 3개 후보에만 계산한다. 화면 17은 부족
   기술 전체에 증가 건수를 붙이는 디자인이다. 전체 계산이 예산상 불가능하면 화면에서
   그 열을 3행에만 두는 것으로 디자인을 확정해야 한다.
3. **추천의 `targetLevel`.** "L0 → L2" 표기에 필요한 목표 Level을 C가 주지 않는다.
   요구 Level이 `levelled_required_clauses`에 있으나 후보별 단일 목표값은 아니다.
4. **JOB Trend 입력.** 월별 `MONTHLY_DEMAND` COHORT/DEMAND가 실제로 준비돼 있는지,
   어떤 기간이 사용 가능한지.
5. **Trend Snapshot payload 스키마.** `trends/resolve`는 `snapshot_id`만 주고 수치는
   `GET /snapshots/{id}`에 있다. 그 payload의 필드 이름·기간 표기 형식이 필요하다.
6. **`HeldTechnology.reason_codes` 목록.** 4.5의 `LEVEL_SHORT` 판정이 어느 코드로
   구분되는지 확정해야 한다. 지금은 `TECHNOLOGY_NOT_EVALUATED` 하나만 확인했다.
7. **운영 접속값.** `C_COMPUTE_URL`과 `C_COMPUTE_TOKEN` 전달 경로. 값은 문서·로그·커밋에
   남기지 않는다.
8. **`GET /internal/v1/c/contracts` 출력.** 이 문서의 요청 필드는 구현 소스에서 읽은
   것이고, 계약 원본은 그 schema다.
9. **JOB Trend의 실제 월별 산출물.** 조회 경로는 준비됐지만, 화면에 표시하려면 A 입력으로
   생성한 `MONTHLY_DEMAND` cohort와 같은 조건의 JOB Trend Snapshot이 기간별로 있어야 한다.
   없는 기간을 0으로 만들거나 다른 직무의 Snapshot으로 대체하지 않는다.
10. **Evidence 근거 행의 실제 수용 여부.** B가 `analysis_evidence` 한 행을 C의
    `EvidenceProof` 하나로 옮기는데(`UserEvidenceAssembler`), C가 그 근거를 실제로
    받아들이는지는 운영 C와 한 번 돌려 봐야 안다. C는 근거가 하나도 수용되지 않으면
    오류 없이 모든 기술을 `UNKNOWN`으로 만든다 — 화면에는 "Skill Gap 전부 미판정"으로만
    보이므로, 첫 E2E에서 가장 먼저 확인할 항목이다.

## 7. FE 연결 상태

> 구현됨(2026-09-15). 아래는 §2의 결정을 FE가 어떻게 반영했는지다.

| 결정 | FE 반영 |
|---|---|
| §2-C 캐시 키 | `queryKeys`의 매칭 계열이 `targetKey` 기반으로 바뀌었다. `analysisId`를 키에서 뺐다 |
| 4.2 `RequirementMark` | `UNKNOWN`을 추가했다. 칩·분절 막대·상세 드로어가 미보유와 다른 색·문구로 그린다 |
| §6-1 KPI 3분할 | 화면 02의 세 번째 칸을 "조건부 제외"로 바꿨다. 셀 수 없는 구간 대신 셀 수 있는 것을 보여준다 |
| §6-2 `fillDelta` | 표의 열은 그대로 두고 계산되지 않은 행을 `—`로 둔다. 0으로 채우지 않는다 |
| §2-B 목표 직무 미선택 | `MATCH-404-1` → `SHOW_EMPTY_WITH_CTA`. 화면 16이 직무를 입력·저장하는 폼이 됐다 |

연결된 화면: `02 Job Match`, `03 What-if`, `10 Recommendation`, `12·13 Trend`,
`16 Target Role`, `17 Skill Gap`.

`16 Target Role`은 직무 카드 3열을 쓰지 않는다. v2 아트보드 자신이 그 영역에
`DESIGN MOCK ROLE TAXONOMY`라고 적었고 확정 목록도 조회 API도 없다. 직무를 입력받고
그 조건의 실제 수요(`/api/v1/job-demands`)를 미리 보여 주는 형태로 바꿨다 — 지원 직무
목록을 화면이 복제하면 C가 직무를 늘릴 때마다 FE가 뒤처진다.

`S6 성장 단계` 카드는 화면에서 뺐다. 세 축을 묶어 단계를 정하는 계산이 어디에도 없고,
만드는 순간 "출처를 합쳐 종합 점수를 만들지 않는다"는 규칙과 부딪힌다.

운영 빌드 보호는 두 겹이다. fixture 스위치는 기본이 꺼짐이고, 그 위에
`npm run check:fixtures`가 `features/matching`·`features/trend`의 `@/mocks` import를
막는다(`npm run build`가 먼저 실행한다). 연결된 화면의 fixture 파일은 지웠다 — 남겨
두면 다음 사람이 되살려 실제 값 위에 덮는다.

아직 fixture로 도는 화면은 `11 Technology Detail`과 `14 My Page`다. 기술 단건 상세와
분석 이력을 돌려주는 API가 없어 연결할 대상이 없고, 두 화면은 `DesignMockBadge`를
그대로 달고 있다.
