# GitJob 기술 문서

> 기준일: 2026-08-28
>
> 이 문서는 현재 레포의 구현 골격과 Notion에 정리된 GitJob 기획·설계를 한 곳에서 확인하기 위한 기술 문서 진입점이다.

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
기술 프로필·근거 ── 목표 직무 ── Skill Gap·추천·Trend·FAQ/Q&A
```

## 2. 파트별 문서

| 파트 | 문서 | 주요 내용 |
|---|---|---|
| 전체 구조 | [아키텍처](architecture.md) | 서비스 목적, 컴포넌트, 데이터 흐름, 설계 원칙 |
| 기획 | [제품·요구사항](product/README.md) | MVP, 기능 범위, 정책, 범위 충돌 |
| Backend | [BE 설계](be/README.md) | 도메인, 분석 Job, 인증, API, 오류·멱등성 |
| Frontend | [FE 설계](fe/README.md) | 화면 흐름, 상태 관리, API/WebSocket, UX 제약 |
| AI | [AI 설계](ai/README.md) | AI 적용 범위, RAG, 설명 생성, 안전장치 |
| Data | [데이터 파이프라인](data/README.md) | 수집, Kafka, HDFS/Parquet, Registry, 품질·재처리 |
| Infra | [인프라 문서 목차](infra/README.md) | Compose, 배포, EC2 HA, 보안, 운영 상태 |
| QA/운영 | [검증 계획](qa/README.md) | 기능·통합·부하·장애 검증 |
| 공통 | [개발 컨벤션](shared/README.md) | Git/Jira, 브랜치, 커밋, 응답·코드 규칙 |

## 3. 현재 구현 상태

현재 레포는 인프라 실행 골격을 중심으로 준비되어 있다.

| 영역 | 현재 레포 상태 | 문서에서의 표현 |
|---|---|---|
| `Infra/` | Compose, Dockerfile, Nginx, Jenkins, 운영 스크립트 존재 | 구현·검증 범위와 미검증 범위를 분리 |
| `BE/` | `.gitkeep`만 존재 | Notion 기준의 구현 계약·목표 설계 |
| `FE/` | `.gitkeep`만 존재 | 와이어프레임과 화면/API 계약 |
| `AI/` | `.gitkeep`만 존재 | 수집·분석 Worker 및 AI/RAG 설계 |
| `docs/` | 본 문서와 기존 Infra 보고서 | 프로젝트 기술·인수인계 문서 |

따라서 “구현됨”은 현재 코드·설정으로 확인된 항목, “설계”는 Notion의 요구사항과 기능명세를 기준으로 작성한 목표 계약, “미결”은 팀 결정이 필요한 항목을 뜻한다.

## 4. 기준 문서와 범위 판단

현재 상세 요구사항의 중심은 GitHub 분석 서비스인 GitJob이다. [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d), [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c), [와이어프레임](https://app.notion.com/p/4590dff912cf8278b234819b7b0bd5d5), [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)의 최신 상세 항목을 현재 서비스 기준으로 삼았다.

현재 구현 계약과 문서의 기준은 GitJob이다. 과거 회의록의 다른 제품 아이디어나 API 표는 현재 GitJob의 실행 계약에 포함하지 않는다.

## 5. 빠른 실행·검증

인프라 기본 검증은 다음 순서로 진행한다. 전체 앱 소스가 추가되기 전에는 `core` 프로파일 검증을 기준으로 한다.

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
