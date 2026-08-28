# GitJob

S15P21E102 특화 프로젝트 저장소입니다.

GitJob은 GitHub 저장소를 분석해 사용자의 기술 사용 근거(Evidence)를 만들고, 목표 직무의 채용 수요와 비교해 Skill Gap과 다음 학습 기술을 제안하는 서비스입니다.

GitJob은 사용자가 접근 권한을 부여한 GitHub public/private 저장소의 개발 활동을 기술별 Evidence로 변환합니다. GitHub 전체 Trend에는 공개 집계 데이터만 사용하며, 사용자의 private 저장소 원문은 시장 Trend에 사용하지 않습니다.

## 프로젝트 흐름

```text
GitHub OAuth
    ↓
저장소 조회·선택
    ↓
비동기 분석 요청
    ↓
GitHub 수집 → 기술 Registry 판정 → Evidence Snapshot
    ↓
기술 Profile → 목표 직무 수요 → Skill Gap·추천
    ↓
Trend · Pain Topic · FAQ · 근거 기반 RAG Q&A
```

분석 실행은 Kafka 기반 비동기 Job으로 처리합니다. 원본·장기 이력은 HDFS/Parquet에 저장하고, 서비스 조회 데이터와 Snapshot은 PostgreSQL에 저장합니다. Redis는 세션·캐시·작업 보조 상태에 사용합니다.

## 주요 기능

- GitHub OAuth 로그인과 public/private 저장소 권한 관리
- 접근 가능한 저장소 목록 조회와 분석 대상 선택
- 저장소별 Commit 기준 비동기 분석·진행률·부분 결과·취소·재실행
- 기술별 Repository Level / Personal Level 및 Evidence 조회
- 파일 경로·라인·Commit permalink·판정 규칙 기반의 근거 제공
- 목표 직무별 채용공고 기술 수요와 Skill Gap 분석
- 다음 학습 기술 후보, 선행관계, 필요한 Evidence 규칙 추천
- GitHub 활동·채용·Stack Overflow 출처별 Trend 비교
- Stack Overflow 반복 문제·FAQ·인용 가능한 기술 Q&A를 제공

기술 레벨은 숙련도나 채용 가능성의 확률이 아니라, 등록된 Evidence 규칙에 의해 판정된 상태입니다. 서로 다른 출처의 지표를 임의의 종합 점수로 합치지 않습니다.

## 시스템 구성

```text
                         Browser
                           │ HTTPS
                           ▼
                 ┌────────────────────┐
                 │ Nginx              │
                 │ SPA · /api · /ws   │
                 └─────────┬──────────┘
                           ▼
                 ┌────────────────────┐
                 │ Spring Boot Backend│
                 └───┬──────┬──────┬───┘
                     │      │      │
                     ▼      ▼      ▼
                PostgreSQL Redis  Kafka
                                    │
                         ┌──────────┴──────────┐
                         ▼                     ▼
                    Collector              Worker
                         │                     │
                         └──────► HDFS/Parquet ◄── Spark/Hadoop
```

운영에서는 EC2를 무상태 app 노드로 사용하고, 2대 구성 시 AWS ALB가 Nginx 앞단에서 트래픽을 분산합니다. PostgreSQL·Redis·Kafka 같은 상태 저장 계층은 양쪽 EC2의 local volume을 공유하지 않고 별도 HA endpoint를 사용합니다.

## 기술 스택

| 영역 | 기술 |
|---|---|
| Backend | Java 21, Spring Boot, Spring Data JPA |
| Frontend | React, Vite 기반 빌드 계약 |
| AI/Data | Python, Kafka, Spark, Hadoop/HDFS, Parquet |
| Database | PostgreSQL, Redis |
| Edge | Nginx |
| Infrastructure | Docker Compose, AWS EC2, Tailscale |
| CI/CD | Jenkins, GitLab Webhook |

## 저장소 구조

```text
.
├── BE/                 # Spring Boot Backend
├── FE/                 # React Frontend
├── AI/                 # Collector·Worker·AI/RAG 처리
├── Infra/              # Compose·Dockerfile·Nginx·Jenkins·운영 스크립트
├── docs/               # 요구사항·아키텍처·파트별 설계·운영 문서
├── Jenkinsfile         # CI/CD pipeline
└── README.md
```

현재 `BE/`, `FE/`, `AI/`에는 애플리케이션 소스가 아직 들어오지 않았습니다. 따라서 인프라 구성은 실행 골격과 연결 계약을 기준으로 하고, 실제 앱 통합 상태는 각 문서의 현재 상태 항목에 따로 기록합니다.

## 로컬 실행

### 사전 조건

- WSL2
- Docker Desktop의 WSL integration 또는 WSL 내부 Docker Engine
- Docker Compose plugin

### 기본 실행

```bash
# .env.wsl 생성. 이미 있으면 기존 설정을 보존하고 종료합니다.
./Infra/scripts/init-wsl.sh

# PostgreSQL·Redis·Kafka 실행
PROFILES=core ./Infra/scripts/up.sh

# 컨테이너 health 상태 확인
./Infra/scripts/healthcheck.sh

# Kafka topic 생성·producer·consumer smoke test
./Infra/scripts/kafka-smoke.sh
```

### 프로파일별 실행

```bash
# 상태 저장·메시징
PROFILES=core ./Infra/scripts/up.sh

# Backend·Frontend·Nginx 포함
PROFILES=core,app ./Infra/scripts/up.sh

# Collector·Worker·HDFS·Spark 포함
PROFILES=core,app,data ./Infra/scripts/up.sh

# CI·운영 UI까지 포함
PROFILES=core,app,data,ci,observability ./Infra/scripts/up.sh
```

현재 애플리케이션 소스가 없는 상태에서는 `core` 프로파일을 먼저 사용합니다. 전체 프로파일의 Compose 설정 병합만 확인하려면 다음 명령을 실행합니다.

```bash
docker compose --env-file .env.wsl --project-directory . \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.wsl.yaml \
  --profile core --profile app --profile data \
  --profile ci --profile observability config --quiet
```

컨테이너 간 연결은 `localhost`가 아닌 service name을 사용합니다.

| 서비스 | 컨테이너 주소 | WSL host 기본 주소 |
|---|---|---|
| PostgreSQL | `postgres:5432` | `127.0.0.1:5432` |
| Redis | `redis:6379` | `127.0.0.1:6379` |
| Kafka | `kafka:9092` | `127.0.0.1:9094` |
| Nginx | `nginx:80` | `127.0.0.1:8080` |
| Jenkins | `jenkins:8080` | `127.0.0.1:8081` |

호스트에서 PostgreSQL `5432`가 이미 사용 중이면 `.env.wsl`의 host port만 변경하고, 컨테이너 내부 `DB_PORT=5432`는 유지합니다.

## 환경 변수와 보안

`.env.example`은 변수명과 기본 구조만 제공합니다. `init-wsl.sh`는 `.env.wsl`을 만들고 로컬용 임시 secret을 생성합니다.

- 실제 `.env`, GitHub OAuth secret, GitHub Token, JWT secret, DB password를 커밋하지 않습니다.
- PEM key와 GitLab webhook/registry credential은 Git에서 제외하고 Jenkins Credentials 또는 AWS SSM/Secrets Manager에 보관합니다.
- WSL에서는 DB·Redis·Kafka·관리 UI를 loopback에만 노출합니다.
- 운영에서는 외부 진입점을 ALB/Nginx 80·443으로 제한하고 관리 경로는 Tailscale/private network 또는 SSM을 사용합니다.
- 운영 DB schema는 `JPA_DDL_AUTO=update` 대신 명시적 migration과 `validate`를 사용합니다.

자세한 포트, 백업·복구, EC2 전환, 2대 HA 절차는 [Infra 문서](Infra/README.md)를 참고합니다.

## 문서

| 문서 | 내용 |
|---|---|
| [문서 목차](docs/README.md) | 전체 문서와 파트별 링크 |
| [시스템 아키텍처](docs/architecture.md) | 컴포넌트·데이터 흐름·설계 원칙 |
| [제품·요구사항](docs/product/README.md) | MVP·정책·범위·미결정 사항 |
| [Backend](docs/be/README.md) | 도메인·분석 Job·API·보안 |
| [Frontend](docs/fe/README.md) | 화면 흐름·상태·통신·UX |
| [AI](docs/ai/README.md) | Fact 기반 설명·RAG·AI 안전장치 |
| [Data](docs/data/README.md) | 수집·Kafka·Parquet·Registry·품질 |
| [Infrastructure](docs/infra/README.md) | Compose·배포·HA·운영 |
| [QA](docs/qa/README.md) | 기능·통합·성능·복원력 검증 |
| [공통 컨벤션](docs/shared/README.md) | Git/Jira·코드·리뷰 규칙 |

## 현재 상태

- PostgreSQL·Redis·Kafka core Compose 설정과 healthcheck 구성
- 현재 환경에서 core 컨테이너 healthcheck와 Kafka 송수신 smoke test 확인
- PostgreSQL backup/restore와 Kafka replay 스크립트 파일 제공
- Backend·Frontend·Worker Dockerfile 및 Nginx reverse proxy 골격 구성
- HDFS/Spark는 최소 Parquet smoke까지 검증했으며, Jenkins·Collector/Worker 전체 흐름과 2대 EC2 HA는 실행 계약·전환 문서 수준
- 실제 Backend·Frontend·AI 소스, 외부 credential, AWS 리소스 연결은 미완료

재시작 영속성·backup/restore의 상세 통과 결과는 [인프라 준비도 문서](docs/infra/2026-08-27-infra-readiness.md)에 별도로 기록되어 있다. 이 README의 현재 상태는 이번 문서 작성에서 직접 확인한 범위와 파일 존재 여부를 우선한다.

## 원문 기획 문서

자세한 요구사항과 원문 결정 사항은 [Notion 프로젝트 페이지](https://app.notion.com/p/6fe0dff912cf83f1a2850101b8643bdf)에서 확인할 수 있습니다.
