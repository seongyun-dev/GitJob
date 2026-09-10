# 2026-09-10 구현 상태와 실행 계약

> 상태: 중간 통합 기준점
>
> 기준일: 2026-09-10
>
> Jira: `S15P21E102-203`

이 문서는 오래된 설계 문서의 기능 목록을 현재 완료 상태로 오해하지 않도록 만든
진입점이다. 코드 존재, 로컬 테스트, 운영 배포, 실제 사용자 흐름 인수는 서로 다른
증거로 취급한다.

## 1. 코드 기준점

| 구분 | 기준 | 포함 내용 |
|---|---|---|
| `develop` 기준 | `0da1756` | !46 분석 Worker·Registry 수명 주기, C1 Archiver/후속 문서 및 Final v2 FE 디자인 포함 |
| 이번 통합 브랜치 | `refactor/S15P21E102-203-branch` | 아래 로컬 기능 커밋과 문서 정리 |

이번 통합 브랜치는 다른 작업자의 깨끗한 로컬 커밋을 원래 Jira 키와 함께 보존한다.

| Jira | 로컬 구현 경계 | 현재 증거 |
|---|---|---|
| `S15P21E102-200` | Career/GameJob 완료 입력 checksum | 코드·회귀 테스트 포함 |
| `S15P21E102-127` | Evidence v2와 과거 설계 구분 | 계약 문서 포함 |
| `S15P21E102-202` | 증가 공고 수 우선 추천 정렬 | 코드·회귀 테스트 포함 |
| `S15P21E102-199` | C DB Registry import·조회와 B CURRENT 수명 주기 공존 | V11 호환 확장, 연결 인수는 별도 |
| `S15P21E102-88` | Registry 검토 원문·결정 이력·검토 API | 코드·migration·테스트 포함 |
| `S15P21E102-201` | GH Archive 기간별 기술 활동 계산 | 코드·fixture/DB 경계 테스트 포함 |
| `S15P21E102-143` | Registry 운영 전환·재처리 경계 | 후속 문서 포함 |

위 항목은 이 브랜치에 포함됐다는 뜻이며, `develop` 반영이나 운영 배포 완료를 뜻하지
않는다. 기능별 상세 계약과 검증 한계는 [C 구현 안내](ai/README.md)와
[C 검증 기록](ai/c-mvp-verification.md)을 따른다.

## 2. 현재 서비스 경계

| 영역 | 현재 상태 | 완료로 보지 않는 항목 |
|---|---|---|
| FE | Vite/React 앱, 저장소 선택·분석 진행·Evidence·추천·Trend 등 주요 화면 초안 존재 | 실계정 로그인부터 C 결과까지 E2E |
| BE | OAuth/저장소/분석 요청·Outbox·Worker 결과 수신 코드 존재 | 실제 결과 소비부터 인증 사용자 조회·C 계산까지 전체 경로 인수 |
| AI/C | Registry·공고·Evidence 소비·Gap·추천·Trend·DB 저장·내부 API의 로컬 구현 존재 | 새 migration/이미지 운영 배포, 실제 B callback·FE 연결 |
| Data | 수집기·계약·GH Archive 결과와 후속 계산 입력 존재 | 모든 월별 운영 모집단과 서비스 소비 경로 검증 |
| Infra | Compose/배포 스크립트와 과거 운영 검증 기록 존재 | 이번 브랜치 이미지·migration의 운영 적용 |

현재 핵심 인수 경로는 `B 분석 완료 → C 인증 내부 호출 → C Snapshot 저장/조회 → B 사용자
API → FE 표시`다. 로컬 fixture, 합성 입력, 정적 Compose 검증만으로 이 경로를 완료로
판정하지 않는다.

## 3. 현재 MVP 범위

현재 MVP는 GitHub Evidence, 목표 직무 채용 수요, Skill Gap, 다음 기술 추천, What-if,
신규 부합 공고 목록, JOB/GITHUB 기반 Trend와 근거 설명이다.

Stack Overflow/Pain/FAQ/RAG와 프로젝트 Template 추천은 과거 설계 또는 후속 후보이며
현재 실행·수용 계약에서 제외한다. 과거 문서에 해당 표현이 남아 있으면 그 문서의
기준일 당시 설계 기록으로 읽고, 현재 범위 판단은 이 문서와
[제품 문서](product/README.md)를 우선한다.

## 4. 이번 정리에서 포함하지 않은 로컬 상태

- 저장소 밖 Evidence POC 작업 트리
- 이미 통합된 `S15P21E102-103`의 오래된 로컬 변경
- 운영 배포, 실데이터 재실행, Jira 기능 티켓 완료 처리, MR merge

## 5. 다음 인수 확인

1. 이 MR의 기능별 단위·DB 경계 테스트와 FE lint/typecheck/build를 다시 확인한다.
2. Flyway V1~V11과 C Compute 001~004 migration을 승인된 환경에 적용하고 이미지 identity를 기록한다.
   C 승인 import와 B CURRENT는 별도이므로 연결 결과의 버전 호환 및 새 코호트 재계산까지 확인한다.
3. 실제 B 분석 완료 payload와 인증된 사용자로 C 저장·조회 경로를 검증한다.
4. 같은 결과를 FE에서 표시하고 재전달·부분 실패·사용자 격리를 E2E로 확인한다.
5. 실제 월별 Archive 모집단과 충분한 실공고를 별도 데이터 인수로 확인한다.
