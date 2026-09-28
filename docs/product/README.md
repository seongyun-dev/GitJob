# 제품·요구사항 문서

> 상태: 현재 MVP 실행 범위
>
> 기준일: 2026-09-10
>
> 과거 Notion 기능 목록보다 [현재 구현 상태](../2026-09-10-current-status.md)와 이 문서의 MVP 범위를 우선한다.

## 1. 한 줄 정의

GitHub 개발 이력을 기술별 Evidence로 분석하고, 목표 직무의 채용시장 수요와 비교해 사용자가 다음 학습 행동을 결정하도록 돕는 서비스다.

## 2. 사용자 가치

| 사용자의 질문 | GitJob의 답변 |
|---|---|
| 내가 실제로 어떤 기술을 사용했나? | 저장소·파일·라인·Commit·Fact 유형이 연결된 Evidence |
| 단순 사용과 내 기여를 구분할 수 있나? | Repository Level과 Personal Level을 분리하고 기여 규칙을 표시 |
| 취업 목표에 무엇이 부족한가? | 목표 직무 수요 Snapshot과 개인 수준을 같은 `tech_id`로 조인 |
| 지금 무엇을 배워야 하나? | Gap·수요·추세·선행관계로 후보를 최대 3개 추천 |
| 결과를 믿을 수 있나? | Evidence·수요·추세의 출처, 기간, 분모와 미확정 상태 |

## 3. MVP 범위

### 필수 흐름

1. GitHub OAuth 로그인 및 권한 scope 확인
2. 접근 가능한 저장소 목록 조회
3. 분석 대상 저장소 선택
4. 비동기 GitHub 분석 요청·진행 상태·부분 결과·취소·재실행
5. 기술 프로필과 Evidence 상세 조회
6. 목표 직무 선택
7. 채용 수요·Skill Gap·학습 후보 추천 조회
8. What-if와 신규 부합 공고 목록·JOB/GITHUB Trend·근거 설명 조회

### 데이터 원칙

- PostgreSQL: 사용자, 분석 실행, Evidence, 기술 Registry, 정규화된 채용공고, 집계·추천 Snapshot
- HDFS/Parquet: raw payload, 장기 이력, Spark 처리·replay 대상
- Kafka: 수집·분석 이벤트와 재처리 흐름
- 공통 조인 키: `tech_id`, `registry_version`
- 데이터가 아직 없으면 임의의 더미 값을 반환하지 않고 `PREPARING`, `NO_DATA`, `INSUFFICIENT_DATA` 중 적합한 상태를 반환
- 분석 입력은 사용자가 GitHub OAuth로 접근 권한을 부여한 public/private 저장소다. 공개 집계 Trend에는 공개 데이터만 사용하고 private 원문은 포함하지 않는다.
- Stack Overflow/Pain/FAQ/RAG와 프로젝트 Template 추천은 현재 MVP 실행·수용 계약에서 제외한다.

## 4. 기능 영역

| 영역 | 주요 기능 ID | 설명 |
|---|---|---|
| 인증·계정 | `GH-AUTH-001`, `F-COL-06` | GitHub OAuth, scope, 별칭 이메일, 연결 해제·삭제 |
| 저장소 | `GH-REPO-001/002` | 저장소 조회, 분석 대상 선택·저장 |
| 분석 작업 | `AN-RUN-001~004` | 비동기 실행, 상태, 재실행, Snapshot, 취소 |
| 기술 분석 | `GH-EVD-001/002` | 기술별 레벨·Evidence·기여 근거 |
| 채용시장 | `JOB-ROLE-001`, `JOB-DMD-001` | 목표 직무와 기술 수요 Snapshot |
| Gap·추천 | `REC-GAP-001`, `REC-NEXT-001/002` | 보유/강화/부족, 다음 기술, What-if·신규 부합 공고 |
| 추세 | `TREND-*` | JOB/GITHUB 출처별 기술 추세 |
| 데이터 플랫폼 | `SYS-QUAL-001`, `TECH-REG-001` | Registry·품질·버전·DLQ·replay |

## 5. 범위와 기록 정책

Notion 요구사항·기능명세·와이어프레임은 초기 전체 후보를 보존한다. 현재 저장소의 실행 계약은 GitHub 분석, 채용 수요, Evidence, Skill Gap, 다음 기술 추천, What-if·신규 부합 공고와 JOB/GITHUB Trend를 중심으로 한다. 과거 문서의 SO/RAG·프로젝트 Template 및 다른 제품 아이디어와 API는 현재 GitJob의 실행 계약에 포함하지 않는다.

## 6. 화면 흐름

화면 번호는 Notion의 와이어프레임과 API 기능명세에서 일부 다르게 사용되므로, 문서·구현에서는 화면 번호보다 화면 이름을 기준으로 연결한다.

```text
GitHub 로그인
  → 저장소 목록·분석 대상 선택
  → 분석 요청·진행 상태
  → 기술 프로필·Evidence
  → 목표 직무 선택
  → Skill Gap·학습 후보 추천
  → 학습 기술 선택
  → What-if·신규 부합 공고·Trend·근거 설명
  → 분석 이력·Snapshot 비교·설정
```

와이어프레임의 공통 제약은 다음과 같다.

- 근거 없는 매칭 퍼센트, 기여 퍼센트, “학습자의 22%” 같은 표현을 사용하지 않는다.
- 별·게이지·트로피 등 숙련도를 오해하게 하는 장식을 사용하지 않는다.
- L0~L3와 Evidence 규칙, source·period·denominator를 함께 보여준다.
- 상태가 `PREPARING`/`NO_DATA`인 영역은 준비 중임을 표시하고 가짜 데이터를 그리지 않는다.

## 7. 비기능 요구사항

| 항목 | 기준 |
|---|---|
| 보안 | 승인된 GitHub scope만 사용, Token 암호화, 로그·응답에 비밀값 금지 |
| 일관성 | 동일 분석의 `analysisId`·Commit·Registry 버전 보존 |
| 복구성 | Kafka checkpoint, idempotent sink, DLQ, replay |
| 설명 가능성 | 모든 레벨·Gap·추천에 규칙/Fact/Evidence 또는 source 연결 |
| 외부 API | GitHub quota, backoff, retry-after, 부분 실패 처리 |
| 개인정보 | 권한 없는 저장소·데이터를 수집하지 않으며 삭제 요청을 처리 |

## 8. 미결정 사항

- 분석 상태 명칭을 요구사항의 `COLLECTING/ANALYZING/COMPLETED/PARTIAL/CANCELLED`로 할지 API 명세의 `RUNNING/RATE_LIMITED/SUCCEEDED/PARTIAL_SUCCEEDED/CANCELED`로 통일할지
- 목표 직무·직무 마스터 조회 API를 추가할지
- 추천 점수의 계산 주체와 정규화 범위
- 화면 번호와 API 기능 ID의 최종 매핑

## 9. 원문 출처

- [주요 기능](https://app.notion.com/p/1fa0dff912cf8349a0c70160b65eb3c2)
- [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d)
- [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c)
- [와이어프레임](https://app.notion.com/p/4590dff912cf8278b234819b7b0bd5d5)
- [아이디어](https://app.notion.com/p/9f50dff912cf838c8343015720cec682)
- [회의록](https://app.notion.com/p/5900dff912cf82f8ade6816778a1ec77)
