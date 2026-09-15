# C조 구현 안내 — 여기서 시작

> 2026-09-12 후속 -221: [공통 44개 Registry·Rule Pack](common-rule-pack.md)은 새 immutable
> 버전, 필요한 Fact와 repository 판정, B v2/v4 인수 fixture를 제공한다. B의 개인 귀속·API/FE와
> 운영 activation은 별도 인수 대상이다. 아래의 과거 완료 기록과 구분한다.

> 상태: C 기능 로컬 구현·검증 완료, 실제 B/FE·운영 서비스 인수는 남음
>
> 기준일: 2026-09-08 · 구현 기준: `ce4c24f` · 관련 Jira: S15P21E102-29/31/33/36/88/160

> 2026-09-10 계약 정합성 후속: Registry 운영 기본을 DB로 전환(-199), 공고 미해결
> 검토 항목을 계산 결과와 함께 DB에 저장(-88), Career/GameJob 완료 checksum 보완(-200),
> GH Archive 기간별 기술 활동 계산(-201), 증가 공고 수 우선 추천(-202)을 추가했다.
> 아래 링크의 최신 계약이 기준이며, 이번 변경은 로컬 구현·검증으로 운영 배포는 하지 않았다.

> 2026-09-09 후속 -183/-184/-185: 채용공고 정규화·필수/우대 조건 보존·공고별 부분 부합을
> 추가했다. [부분 부합 계약과 검증 한계](c-job-matching.md), [요구절 모델](c-job-requirements.md)을
> 참고한다. 최신 로컬 PostgreSQL 검증과 아직 남은 B/FE·운영 인수는
> [검증 기록 10절](c-mvp-verification.md#10-2026-09-10-계약-정합성-후속)을 구분해서 읽는다.

## 1. 3분 요약

C는 **사용자가 사용한 것으로 확인된 기술과 공고의 기술 조건을 비교해, 다음에 배울 기술과 늘어나는 부합 공고를 계산**한다. 여기서 부합은 수집·분류한 기술 조건에 대한 부합이지 학력·경력 등 전체 채용 자격 충족이나 합격 확률이 아니다.

이번 구현은 공고 정규화·분류·여러 출처 통합·수요 집계, Evidence 소비·Gap, 학습 기술 추천·What-if·공고 목록, 근거 설명, 공개 Repo 관측·Trend, 자동 계산·DB 저장·내부 API다. Stack Overflow/Pain/FAQ/RAG와 프로젝트 추천은 현재 범위에서 제외한다. GPU/LLM 없이도 Rule 설명이 동작한다.

**처음 읽을 때는 이 문서 → 필요한 기능 계약 → [검증 결과와 남은 인수](c-mvp-verification.md) 순서면 된다.** 실행하거나 B에서 연결하려면 [실행·저장 계약](c-compute-runtime.md), [완료 이벤트 전송기](c-compute-client.md)를 읽는다.

용어:

- **코호트(cohort):** 같은 직무·기준 시각·필터·품질 규칙으로 선정한 공고 집합. 수요·추천·What-if가 같은 집합을 사용한다.
- **Evidence:** 파일/path/commit/Fact/Rule로 확인 가능한 기술 관측과 사용자 참여·귀속 근거.
- **Snapshot:** 입력·정책 버전·근거와 계산 결과를 함께 고정한 불변 결과. 조회할 때 새로 계산하지 않는다.
- **What-if:** 기술 하나를 추가로 보유한다고 가정했을 때 새로 부합하는 공고 수와 목록.

## 2. 기능 지도: 무엇을 만들었고 어디를 보면 되나

아래는 현재 구현 기능이다. 로컬 검증과 실제 서비스 인수의 차이는 6절을 따른다.

| 기능 / Jira | 제공하는 결과·핵심 동작 | 상세 계약 / 주요 코드 |
|---|---|---|
| 공통 44개 Rule Pack / -221 | source별 기술 매핑, 실제 Fact 기반 Rule, 판정 상한과 PARTIAL, 버전별 DB 발행 및 B 인수 계약 | [공통 Rule Pack](common-rule-pack.md) · [Rule 데이터](../../AI/analysis/data/rule_pack_20260911_2.json), [DB 발행](../../AI/registry/rulepack_db.py) |
| 정규화·요구유형·검수 / -81·-82·-88 | 기술 alias를 Registry ID로 통일, 필수/우대/일반과 미확정 분리, 근거·검토 이력 보존 | [Registry](../data/2026-09-08-technology-registry-mvp.md), [분류·품질](c-job-demand.md) · [classifier.py](../../AI/job/classifier.py), [review.py](../../AI/registry/review.py) |
| DB Registry·검토 실행 / -199·-88 | B의 기본 선택값을 불변 DB 버전으로 해석, UNKNOWN/AMBIGUOUS 원문·결정 이력의 원자적 저장과 API | [DB 운영 계약](../data/technology-registry-db.md), [검토 큐](c-registry-review.md) |
| 공고별 부분 부합 / -183·-184·-185 | 필수/우대별 충족·부족·미확정과 원문 근거, 고정 목록/상세. 기존 What-if와 별도 | [부분 부합](c-job-matching.md), [요구절](c-job-requirements.md) · [matching.py](../../AI/job/matching.py) |
| 공고 통합·수요 / -29 | 출처별 최신 관측을 합쳐 유효 공고 집합 확정, 기술별 distinct 공고 수·분모·비율 | [코호트·수요](c-job-demand.md) · [input_union.py](../../AI/job/input_union.py), [cohort.py](../../AI/job/cohort.py), [demand.py](../../AI/job/demand.py) |
| Evidence 소비·Gap / -33 | 확인 보유/범위 내 미보유/미확정 구분, 레벨·관측·참여·귀속 프로필 보존 | [Evidence 정책](c-recommendation.md) · [evidence.py](../../AI/recommendation/evidence.py) |
| 추천·What-if·목록 / -33 | 후보 최대 3개, 기술 하나 추가 시 증가 공고 수와 해당 공고 ID | [추천 엔진](c-recommendation-engine.md) · [engine.py](../../AI/recommendation/engine.py) |
| 근거 설명 / -36 | 같은 Snapshot의 수요·Evidence·증가 공고를 한국어 Rule 문장으로 설명 | [설명 계약](c-recommendation-explanation.md) · [explanation.py](../../AI/recommendation/explanation.py) |
| 공개 Repo 분석 / -160 | Artifact 크기/hash 확인 후 기술 관측, 분할 실행·재개·전체 결과 게시 | [관측 의미](c-public-analysis.md), [파이프라인](c-public-pipeline.md) · [public_analysis.py](../../AI/github/public_analysis.py), [public_pipeline.py](../../AI/github/public_pipeline.py) |
| 출처별 Trend / -31 | JOB 월별 수요와 Innovation Graph KR 언어별 분기 지표를 각각 반환 | [Trend 계약](c-public-trend.md) · [job.py](../../AI/trend/job.py), [github.py](../../AI/trend/github.py) |
| GH Archive 기술 활동 / -201 | 기간별 이벤트와 공개 기술 관측을 repo_id로 결합, 표본·coverage·입력 계보와 함께 저장 | [Archive 계약](c-archive-trend.md) · [archive.py](../../AI/trend/archive.py) |
| 자동 실행·저장·조회 / -33 | 완료 manifest 감지/완료 API 호출, 재시도·멱등성·사용자 격리·DB 불변 저장 | [런타임](c-compute-runtime.md), [클라이언트](c-compute-client.md) · [intake.py](../../AI/worker/intake.py), [api.py](../../AI/worker/api.py), [store.py](../../AI/worker/store.py) |

기능별 예외·DTO·계산 버전은 표의 상세 계약이 기준이다. HTTP의 실제 JSON Schema는 인증된 `GET /internal/v1/c/contracts`에서 확인한다. Python 함수의 인자명과 HTTP DTO 필드가 같다고 가정하지 않는다.

## 3. 입력에서 화면까지: C가 맡는 경계

### 공고와 시장 결과

A 수집기가 완료 배치와 manifest를 발행한다. C Worker는 설정한 입력 디렉터리를 감시하고 완료 여부·hash·품질을 확인한다. 여러 출처의 검증된 관측을 합친 뒤 공고를 정규화·분류하고 같은 코호트의 수요를 계산해 DB에 저장한다. A가 별도의 통합 배치를 새로 만들 필요는 없다.

공개 Repo는 A의 고정 Snapshot을 읽어 파일 근거를 분석한다. 큰 입력은 분할·재개하며 전체 완료 후에만 최종 결과를 게시한다. 공개 Repo 기술 관측과 Innovation Graph 언어 Trend는 서로 다른 지표다.

### 개인 추천

B가 사용자 저장소 Facts/Rule/참여·귀속을 분석한다. B는 준비된 공고 코호트를 조회하고, 해당 ID와 실제 Evidence를 C 분석 완료 API에 전달한다. C는 즉시 보유·Gap·추천·What-if·설명을 계산해 DB에 저장한다. B의 인증 API가 저장 결과를 조회해 FE에 전달한다.

- A: 원재료 수집·발행. C: 의미 판정·집계·추천 계산. B: 개인 분석 엔진·사용자 인증·서비스 조회.
- C는 공통 Rule Pack과 필요한 Fact 추출기를 소유하고 B가 이를 저장소 분석에 실행한다. B는 개인 귀속·여러 저장소 종합을 담당한다. 공개 저장소 관측으로 사용자의 L3를 만들지 않는다.
- C 내부 API의 `user_id`는 B가 인증한 값이다. 브라우저가 C 서비스 토큰을 가지고 직접 호출하는 구조가 아니다.
- Registry 실행 기본은 DB이며 기존 파일 `ReviewStore`는 로컬 도구로 남긴다. 운영 실행 코드는
  공고 완료 시 DB 검토 큐를 함께 저장한다. B 관리자 인증·Registry 신규 기술/alias 승인 UI는 별도 경계다.

## 4. 중요한 판단과 이유

### 보유 기술과 수준은 다르다

추천 포함 조건은 **검증된 직접 의존성 또는 구현 관측 + 같은 저장소의 유효 사용자 참여**다. `L3` 숫자만 있거나 접근 권한만 있는 입력은 보유 근거가 아니다. 반대로 Java처럼 SBOM 직접 의존성이 없어도 소스 구현과 참여가 확인되면 추천용 보유로 사용할 수 있다.

B 레벨, 검증 상태, 기술 관측, 참여, SELF 귀속을 따로 보존한다. 파일 수·커밋 수를 숙련도 점수로 바꾸거나 C가 B 레벨을 임의 승격하지 않는다. 자세한 조건과 18개 사례는 [Evidence 정책](c-recommendation.md)에 있다.

- `HELD`: 검증된 긍정 근거로 추천에 포함.
- `NOT_HELD`: 선택한 저장소의 유효 참여와 해당 기술의 완료 평가 범위 안에서 미관측. 사용자 전체 지식의 부재라는 뜻이 아님.
- `UNKNOWN`: 부족·실패·모순·미평가. 미보유 후보로 강제 추천하지 않음.

### 수요와 What-if의 숫자는 같은 공고 집합에서 계산한다

필수 조건은 AND/OR를 유지하며 우대를 필수로 바꾸지 않는다. 모호한 조건을 추측해서 통과시키지 않고 검토 대상으로 남긴다. What-if에는 기술 하나만 추가하고 선행 기술까지 자동 보유 처리하지 않는다.

예를 들어 현재 12개, 추가 후 27개라면 증가 공고는 15개다. `WHAT_IF` 목록도 **신규 15개**이며 27개 전체가 아니다. 추천 v3은 증가 공고 수를 먼저 비교하고, 동률일 때 선행기술 준비 여부·수요 등을 비교한다. 근거 없는 종합 점수는 만들지 않는다.

### 모르는 것과 0을 구분한다

공고 입력 미완료와 정상 집합의 0건, 공개 실행 완료와 원천 품질 부족, 기술 미관측과 개인 미보유를 구분한다. NOT_FOUND/FAILED/파일 없음은 기술 미사용이 아니다. 이전 결과는 보존하지만 잘못된 새 입력을 성공 결과로 바꾸지는 않는다.

## 5. 실행·연결을 시작하는 순서

1. [AI 개발 환경](../../AI/README.md)으로 Python 3.12와 저장소의 requirements를 준비한다.
2. [런타임](c-compute-runtime.md)에 따라 public Flyway V3, C migration 003까지와 내부 token을 준비하고, [Registry를 DB에 import·활성화](../data/technology-registry-db.md)한다. `/health`는 생존 확인이고 인증된 `/ready`는 실행 Registry와 DB migration 준비 확인이다.
3. 공고 자동화는 `C_INTAKE_CONFIG`와 보존된 완료 입력 디렉터리를 설정한다. 공개 분석은 허용한 고정 HDFS root와 별도 checkpoint를 사용한다.
4. `GET /internal/v1/c/intake/status`로 처리 상태를 보고, `POST /internal/v1/c/job-cohorts/resolve`로 검증된 입력 합집합에서 화면 조건에 맞는 코호트·수요 ID를 얻는다. 처음 보는 조건은 C가 멱등 계산·저장하고 같은 입력과 조건은 기존 결과를 재사용한다.
5. B에서 `POST /internal/v1/c/analyses/completed`로 실제 Evidence와 코호트 ID를 보낸다. 반환된 저장 Snapshot ID로 결과와 공고 목록을 조회한다. 실패 재전달은 [클라이언트 규칙](c-compute-client.md)을 따른다.

운영 준비 현황과 B 연동에 남은 일은 [B ↔ C compute 연동](c-compute-backend-integration.md)에 있다. 그 문서의 2026-09-09 스키마·token 기록은 이전 배포 기준이며, 새 V3/003·DB Registry를 적용했다는 뜻은 아니다.

배포 대상 주소·비밀값은 문서 예제를 그대로 쓰지 않는다. 자동 입력의 `as_of`는 명시한 기준 시각이며 저절로 현재 시각으로 이동하지 않는다. 기준 변경과 운영 입력 보존은 실행 설정에서 관리한다.

## 6. 어디까지 검증했고 무엇이 남았나

`ce4c24f` 기준 전체 AI 테스트 973개, 로컬 Docker/HTTP/PostgreSQL 왕복과 재시작, 실제 A Top20k 전체 입력 소비를 검증했다. 공고·개인 Evidence의 통합 입력은 합성이므로 실제 B 분석이나 운영 서비스 완료와 구분한다. 공개 데이터는 처리 완료여도 품질이 `INSUFFICIENT_DATA`다.

서비스 인수에는 충분한 유효 실공고, A tree 메타데이터/소스 범위 확인, 실제 B Evidence·callback·인증 조회·FE, 승인된 운영 배포가 남는다. 검수한 14개 공고를 시장 모집단으로 일반화하지 않는다.

정확한 수치·검증 조건·재실행 방법·코드 커밋 경계는 [검증 및 인수 기록](c-mvp-verification.md)을 본다.

## 7. 기존 설계와 원문을 읽을 때

아래는 이전 설계/별도 운영 자료다. 현재 Evidence 정책·SO 제외·Rule 설명 구현과 충돌하는 과거 내용을 새 실행 계약으로 적용하지 않는다.

- [기술명 정규화 초기 설계](technology-normalization-design.md)
- [Evidence/LLM 초기 설계와 정책 충돌 기록](technology-level-llm-handoff.md)
- [외부 조사 도구 초기 설계](external-research-tools.md)
- [노트북 LLM 별도 런북](../infra/local-llm-runbook.md)
- [이전 Registry·분류 작업 기록](2026-09-07-registry-job-review-implementation.md)

Notion 출처와 정확한 정책/기능 ID는 각 상세 계약에 연결되어 있다. 이 문서는 C 구현 안내이며 다른 조의 미게시 로컬 코드나 전체 서비스 완료를 확인한 보고서가 아니다.
