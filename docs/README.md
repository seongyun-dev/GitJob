# GitJob 기술 문서

> 기준일: 2026-09-08 (C 구현 진입점 갱신, 타 파트 전체 인수 상태는 별도)
>
> 기술 문서 진입점이다. 현재 C 구현은 [C조 구현 안내](ai/README.md), 검증 근거와 잔여는 [C 검증·인수 기록](ai/c-mvp-verification.md)부터 읽는다. 이전 설계 문서의 전체 기능 목록을 현재 구현 완료 목록으로 해석하지 않는다.

## 1. 5분 요약

GitJob은 GitHub 저장소를 분석해 사용자의 기술 사용 근거(Evidence)를 만들고, 목표 직무의 채용 수요와 비교해 Skill Gap과 다음 학습 기술을 제안하는 서비스다. 분석은 비동기로 실행하며, 원본·장기 데이터는 HDFS/Parquet에 보관하고 서비스 조회 데이터와 Snapshot은 PostgreSQL에 저장한다.

```text
GitHub OAuth
    ↓
저장소 조회·선택
    ↓
비동기 분석 요청 ── Kafka ── Collector / Worker ── HDFS·Parquet
    ↓                                      ↓
분석 상태·Snapshot                     PostgreSQL Evidence
    ↓                                      ↓
기술 프로필·근거 ── 목표 직무 ── Skill Gap·추천·What-if·Trend
```

위는 서비스 목표 흐름이며 Kafka부터 실제 화면까지 연결 완료를 뜻하지 않는다.
현재 C는 완료 입력 감시/내부 HTTP 호출로 계산한다. SO·FAQ/Q&A·프로젝트 추천은
이번 C MVP 범위에서 제외하며, 정확한 실행 경계는 [C 안내](ai/README.md)를 따른다.

## 2. 파트별 문서

| 파트 | 문서 | 주요 내용 |
|---|---|---|
| 전체 구조 | [아키텍처](architecture.md) | 서비스 목적, 컴포넌트, 데이터 흐름, 설계 원칙 |
| 기획 | [제품·요구사항](product/README.md) | MVP, 기능 범위, 정책, 범위 충돌 |
| Backend | [BE 설계](be/README.md) | 도메인, 분석 Job, 인증, API, 오류·멱등성 |
| Frontend | [FE 설계](fe/README.md) | 화면 흐름, 상태 관리, API/WebSocket, UX 제약 |
| AI/C | [C조 구현 안내](ai/README.md) | 기능·코드 지도, Evidence 판단, 수요·추천·자동 실행, 검증·남은 인수 |
| Data | [데이터 파이프라인](data/README.md) | 수집, Kafka, HDFS/Parquet, Registry, 품질·재처리 |
| Infra | [인프라 문서 목차](infra/README.md) | Compose, 배포, EC2 HA, 보안, 운영 상태 |
| QA/운영 | [검증 계획](qa/README.md) | 기능·통합·부하·장애 검증 |
| 공통 | [개발 컨벤션](shared/README.md) | Git/Jira, 브랜치, 커밋, 응답·코드 규칙 |

## 3. 현재 구현 상태

아래는 이 checkout에서 확인한 파일 존재·구현 범위다. 배포나 타 파트 기능 완성을 판정한 표가 아니다.

| 영역 | 현재 레포 상태 | 문서에서의 표현 |
|---|---|---|
| `Infra/` | Compose, Dockerfile, Nginx, Jenkins, 운영 스크립트 존재 | 구현·검증 범위와 미검증 범위를 분리 |
| `BE/` | Spring Boot 진입점·공통 응답/오류 처리·init.sql·C migration 존재 | B 실제 분석·인증 API 통합은 별도 인수 |
| `FE/` | Vite/React 소스·package-lock 존재 | C 결과 화면의 실제 연결은 별도 인수 |
| `AI/` | Collector·Registry·공고 분석·추천·공개 분석·Trend·C Worker 구현 | [기능 지도](ai/README.md)와 [검증 경계](ai/c-mvp-verification.md)로 확인 |
| `docs/` | 본 문서와 기존 Infra 보고서 | 프로젝트 기술·인수인계 문서 |

따라서 “구현됨”은 현재 코드·설정으로 확인된 항목, “설계”는 Notion의 요구사항과 기능명세를 기준으로 작성한 목표 계약, “미결”은 팀 결정이 필요한 항목을 뜻한다.

## 4. 기준 문서와 범위 판단

GitJob의 기획 원문은 [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d), [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c), [와이어프레임](https://app.notion.com/p/4590dff912cf8278b234819b7b0bd5d5), [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)다. 이 절의 기존 링크를 이번 갱신에서 최신 원문으로 재검증한 것은 아니다. C의 확정 제외 범위·Evidence 정책·실행 API는 9/8 C 문서와 각 문서가 연결한 정책 원문을 따른다.

현재 구현 계약과 문서의 기준은 GitJob이다. 과거 회의록의 다른 제품 아이디어나 API 표는 현재 GitJob의 실행 계약에 포함하지 않는다.

## 5. 빠른 실행·검증

인프라 기본 검증 명령은 다음과 같다. C 계산을 실행하려면 이것만으로는 부족하며
[C 런타임](ai/c-compute-runtime.md)의 migration·token·입력 mount가 필요하다.

```bash
./Infra/scripts/init-wsl.sh
PROFILES=core ./Infra/scripts/up.sh
./Infra/scripts/healthcheck.sh
./Infra/scripts/kafka-smoke.sh
```

Compose 병합과 전체 구조 확인은 [인프라 문서](infra/README.md)를 참조한다.

## 6. 원문 출처

- [2학기 특화 PJT 루트](https://app.notion.com/p/6fe0dff912cf83f1a2850101b8643bdf)
- [주요 기능](https://app.notion.com/p/1fa0dff912cf8349a0c70160b65eb3c2)
- [개발 환경](https://app.notion.com/p/77f0dff912cf8305a10b017245b40a78)
- [환경 변수](https://app.notion.com/p/0b60dff912cf836084ee01fb375e5cbd)
- [깃랩/지라 컨벤션 가이드](https://app.notion.com/p/e2a0dff912cf824a85340178601b1997)
- [회의록](https://app.notion.com/p/5900dff912cf82f8ade6816778a1ec77)
- [WBS](https://app.notion.com/p/b0b0dff912cf827781ee8119fc1a7cbd)
