# 인프라 배포 준비 계획서

- 작성일: 2026-08-27
- 프로젝트: S15P21E102 / GitJob
- 상태: 전체 Compose/Dockerfile 및 2-EC2 app HA 골격 구현 / 애플리케이션 통합·AWS 운영 검증 대기
- 범위: WSL에서 검증 가능한 Docker Compose·Jenkins 기반 실행 환경을 준비하고, 이후 EC2에 동일한 방식으로 이관
- 이번 단계: core/app/data/ci/observability Compose 프로파일, WSL·단일 EC2·2-EC2 HA override, Dockerfile·Nginx·Jenkins 골격과 준비도 문서를 구현함. 실제 애플리케이션 소스·credential·EC2가 준비되면 통합 검증함

## 1. 목적

EC2 서버가 발급되기 전에 WSL에서 개발·통합 환경을 재현하고, 서버가 발급되면 환경 변수와 배포 대상만 바꾸어 EC2에 배포할 수 있는 기반을 만든다.

최종적으로는 다음 흐름을 목표로 한다.

```text
GitLab(develop/main)
        │ Webhook
        ▼
     Jenkins ── build/test ── image publish
        │                         │
        └──── deploy ─────────────┘
                  ▼
       Docker Compose on WSL / EC2
```

## 2. 확인된 기준

### 2.1 저장소 현황

- 현재 저장소는 `BE/`, `FE/`, `AI/`, `Infra/`, `docs/` 초기 골격으로 구성되어 있다.
- 애플리케이션 소스는 아직 없지만, Dockerfile·Compose·Nginx·Jenkinsfile/JCasC 및 2-EC2 app HA overlay 골격은 이번 단계에서 추가했다.
- 기본 브랜치는 `develop`이며 원격 저장소는 SSAFY GitLab이다.
- 인프라 문서는 `docs/infra/`, 실제 인프라 관련 파일은 기존 `Infra/` 아래에 배치한다.

### 2.2 Notion 기준

| 영역 | 확정 또는 제안된 기준 |
|---|---|
| Backend | Spring Boot, JPA, Java 21 |
| Frontend | React |
| 서비스 DB | PostgreSQL로 확정 |
| 캐시/보조 저장소 | Redis |
| 메시징 | Kafka, 소스별 토픽 분리, 비동기 분석 처리 |
| 대용량 처리 | Spark, Hadoop/HDFS, Python, Parquet |
| 인프라 | Docker, AWS, Nginx, Jenkins, Tailscale |
| 서비스 데이터 | PostgreSQL에 사용자·분석 실행·정규화·집계·추천 Snapshot 저장 |
| 원본/장기 데이터 | HDFS/Parquet에 저장하고 PostgreSQL에는 위치·버전·체크섬 기록 |
| 공통 키 | `tech_id`와 `registry_version` |
| 운영 요구 | Consumer Lag, DLQ, 분석 시간, GitHub quota 확인 |

### 2.3 현재 환경 변수에서 확인된 사항

- PostgreSQL 기본 DB명은 `gitjob`이다.
- Compose 내부에서 Spring Boot가 실행될 때 DB 호스트는 `localhost`가 아니라 PostgreSQL 서비스명으로 설정해야 한다. 계획상 서비스명은 `postgres`로 통일한다.
- Redis 기본 포트는 `6379`, Redis Insight 포트는 `8001`이다.
- `JPA_DDL_AUTO=update`는 로컬 개발 기본값으로만 사용하고, EC2 운영 환경에서는 마이그레이션 도입 후 `validate` 또는 명시적인 마이그레이션 전략으로 전환한다.
- 현재 백엔드·프론트엔드 전용 환경 변수와 실제 빌드 명령은 아직 확정되지 않았다.

## 3. 목표와 비목표

### 목표

1. WSL에서 핵심 서비스와 애플리케이션을 명령 한 번으로 기동한다.
2. Compose 내부 서비스 간 통신이 EC2에서도 동일하게 동작하도록 서비스명 기반으로 구성한다.
3. Jenkins가 GitLab 변경을 감지해 테스트·이미지 빌드·배포·헬스체크까지 수행한다.
4. PostgreSQL, Redis, Kafka, HDFS의 데이터가 컨테이너 재시작 뒤에도 보존되도록 한다.
5. Kafka·Spark·HDFS 기반 데이터 파이프라인은 무거운 구성과 핵심 구성으로 나누어 WSL 자원에 맞게 실행한다.
6. 비밀값·토큰·SSH 키가 Git에 들어가지 않도록 한다.
7. WSL 검증 결과를 바탕으로 EC2 인스턴스 사양과 단일/2-노드 운영 형태를 판단한다.

### 비목표

- 이번 단계에서 EC2 리소스를 생성하거나 외부 DNS·인증서를 발급하지 않는다.
- 이번 단계에서 애플리케이션 기능, DB 스키마, Kafka 이벤트 payload 자체를 구현하지 않는다.
- EC2 한 대에 모든 대용량 처리 컴포넌트를 반드시 고정하지 않는다. 벤치마크 결과에 따라 분리 배포를 결정한다.
- Jenkins를 인터넷에 공개하는 것을 목표로 하지 않는다.

## 4. 제안 아키텍처

```text
                         ┌──────────────┐
                         │ GitLab       │
                         └──────┬───────┘
                                │ Webhook
                         ┌──────▼───────┐
                         │ Jenkins      │  ci profile
                         └──────┬───────┘
                                │ Compose deploy
  User ── 80/443 ──▶ ┌─────────▼─────────┐
                     │ Nginx              │
                     │ SPA / API / WS     │
                     └──┬──────────────┬──┘
                        │              │
                 ┌──────▼──────┐ ┌─────▼──────┐
                 │ React       │ │ Spring Boot│ app profile
                 │ static      │ │ API        │
                 └─────────────┘ └──┬────┬────┘
                                    │    │
                         ┌──────────▼┐ ┌─▼────────┐
                         │ PostgreSQL│ │ Redis    │ core profile
                         └───────────┘ └──────────┘
                                    │
                             ┌──────▼──────┐
                             │ Kafka       │ core profile
                             └──┬──────┬───┘
                                │      │
                    ┌───────────▼┐  ┌─▼────────────┐
                    │ Collectors  │  │ Analysis    │ data profile
                    │ / Producers │  │ Workers     │
                    └──────┬──────┘  └──────┬──────┘
                           │                │
                     ┌─────▼────────────────▼─────┐
                     │ HDFS / Parquet / Spark      │ data profile
                     └────────────────────────────┘

  운영자 ── Tailscale/private access ──▶ Jenkins·Kafka UI·운영 지표
```

### 4.1 2대 EC2 목표 구조

EC2가 2대이면 각 서버에 동일한 commit SHA의 `Backend`, `Frontend`, `Nginx`를
올리고 AWS ALB target group이 `/health` 결과를 기준으로 분산한다.
`compose.ec2-ha.yaml`은 각 서버에서 `PROFILES=app`만 실행하는 overlay다.
두 서버의 local Compose network/volume은 공유되지 않으므로 PostgreSQL·Redis·Kafka는
RDS·ElastiCache·MSK 같은 공유 HA endpoint를 사용한다.

상세 구성, ALB, 장애 테스트와 rolling deploy는
[2대 EC2 고가용성 설계 문서](2026-08-27-ec2-high-availability-design.md)에 기록한다.

### 서비스 구성 원칙

| 서비스 | 역할 | 외부 공개 | 초기 실행 범위 |
|---|---|---:|---|
| `nginx` | React 정적 파일 제공, `/api` reverse proxy, WebSocket/Stomp 전달 | 80/443만 | app |
| `backend` | Spring Boot API 및 분석 Job 조회·등록 | 직접 공개하지 않음 | app |
| `postgres` | 서비스 조회 데이터와 분석 Snapshot 저장 | 공개하지 않음 | core |
| `redis` | 캐시·세션·작업 보조 저장소 | 공개하지 않음 | core |
| `kafka` | 수집·분석 이벤트 전달과 replay | 공개하지 않음 | core |
| `jenkins` | CI/CD 컨트롤러 | 공개하지 않음 | ci |
| `collector/worker` | 수집·소비·분석 작업 실행 | 공개하지 않음 | data |
| `hdfs` | 원본·장기 이력·Parquet 저장 | 공개하지 않음 | data |
| `spark` | 배치·스트리밍 분산 처리 | 공개하지 않음 | data |
| `redis-insight` 또는 Kafka 관리 UI | WSL 디버깅·운영 보조 | Tailscale 또는 localhost만 | optional |

### Compose 프로파일

자원 사용량과 검증 목적을 분리하기 위해 하나의 Compose 진입점에서 프로파일을 제공한다.

- `core`: PostgreSQL, Redis, Kafka 및 공통 네트워크·볼륨
- `app`: Backend, React build/runtime, Nginx
- `data`: Collector, Worker, HDFS, Spark, replay·DLQ 처리 도구
- `ci`: Jenkins controller와 제한된 권한의 build/deploy agent
- `observability`: Kafka 관리 화면, 애플리케이션 지표 수집 등 선택 구성

WSL에서는 먼저 `core` → `app` 순서로 검증하고, 대용량 파이프라인은 `data`를 별도로 실행한다. 단일 EC2 fallback은 `core + app`을 사용하고, 2대 HA에서는 두 노드에 `app`만 실행한 뒤 data/CI와 상태 저장소를 별도로 배치한다.

## 5. 파일 구조 계획

실제 구현 시 다음 구조를 기준으로 작성한다. 파일명은 구현 단계에서 팀 컨벤션과 애플리케이션 빌드 구조를 확인해 확정한다.

```text
Infra/
├── compose/
│   ├── compose.yaml          # 공통 서비스·네트워크·볼륨·healthcheck
│   ├── compose.wsl.yaml      # WSL 개발용 override
│   ├── compose.ec2.yaml      # 단일 EC2 fallback override
│   └── compose.ec2-ha.yaml   # 2대 EC2 app 노드 override
├── docker/
│   ├── backend/Dockerfile    # Java multi-stage build
│   ├── frontend/Dockerfile   # React build stage
│   ├── worker/Dockerfile
│   ├── spark/Dockerfile       # 공식 Spark + Python smoke/job runtime
│   └── jenkins/Dockerfile
├── nginx/
│   ├── nginx.conf
│   └── conf.d/default.conf
├── jenkins/
│   ├── casc/                 # Jenkins Configuration as Code
│   ├── jobs/                 # pipeline seed 또는 job 설정
│   └── plugins.txt
├── scripts/
│   ├── up.sh
│   ├── down.sh
│   ├── healthcheck.sh
│   ├── backup-postgres.sh
│   ├── restore-postgres.sh
│   ├── replay.sh
│   ├── spark-smoke.sh
│   ├── spark-benchmark.sh
│   └── ha-preflight.sh
└── README.md                 # 실행·운영·장애 대응 안내

Jenkinsfile                   # 저장소 루트에 배치 예정
.env.example                  # 커밋 가능한 샘플만 제공
```

`docs/infra/`에는 설계·운영 문서를 두고, 실제 실행 파일은 기존 대문자 디렉터리인 `Infra/`에 둔다. 경로 대소문자 혼동을 막기 위해 문서와 스크립트에서 이를 명시한다.

## 6. 환경 변수와 비밀값 전략

### 공통 환경 변수 초안

```dotenv
# PostgreSQL
POSTGRES_PORT=5432
POSTGRES_DB=gitjob
POSTGRES_USER=change-me
POSTGRES_PASSWORD=change-me
DB_HOST=postgres
DB_PORT=5432

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# Kafka
KAFKA_BOOTSTRAP_SERVERS=kafka:9092

# Application
JPA_DDL_AUTO=validate
JPA_SHOW_SQL=false

# 2-EC2 HA app node
DEPLOYMENT_MODE=ha
EC2_NODE_NAME=node-a
ALB_HEALTHCHECK_URL=https://<service-domain>/health
# Replace local DB/Redis/Kafka hosts with shared HA endpoints on EC2.
```

위 값은 구조 확인용 초안이며 실제 `.env.example`에는 동작 가능한 기본 비밀번호를 넣지 않는다.

### 환경 분리

- `.env.example`: 변수명, 설명, 예시 형식만 저장
- `.env.wsl`: 개인 WSL 실행용. Git ignore 대상
- `.env.ec2`: EC2 운영용. Git ignore 대상이며 서버에서만 관리
- Jenkins Credentials: GitLab webhook secret, GitLab token, registry credential, EC2 SSH key, GitHub OAuth secret 등을 저장
- EC2 운영 단계에서는 가능하면 AWS SSM Parameter Store 또는 Secrets Manager를 검토한다.
- 로그에 환경 변수 전체를 출력하지 않으며, 토큰·비밀번호·쿠키는 마스킹한다.
- 2대 HA에서는 `EC2_NODE_NAME`만 노드별로 다르게 두고, DB/Redis/Kafka endpoint와
  JWT/OAuth/topic 설정은 두 노드에서 동일하게 유지한다.

### 반드시 확인할 환경 차이

| 항목 | WSL 외부에서 앱 실행 | Compose 내부에서 앱 실행 |
|---|---|---|
| PostgreSQL host | `localhost` | `postgres` |
| Redis host | `localhost` | `redis` |
| Kafka bootstrap | `localhost:<published-port>` | `kafka:9092` |
| Frontend API URL | Nginx/localhost 기준 | 브라우저가 접근 가능한 Nginx URL 기준 |
| GitHub OAuth callback | WSL callback URL | EC2 도메인 callback URL |

## 7. Jenkins CI/CD 계획

### 파이프라인 흐름

1. GitLab `develop` 변경 또는 Merge Request 이벤트 수신
2. `.env.ci.example`을 깨끗한 workspace에 복사하고 Java·Node·npm·Docker·Compose·Git 버전을 확인
3. 브랜치명·커밋 메시지·Jira 키 형식 검증
4. Backend 단위 테스트·정적 검사
5. Frontend lint·test·production build
6. Compose 문법과 환경 변수 템플릿 검증
7. Backend·Frontend·Worker·Spark 처리 이미지 빌드
8. Git commit SHA 또는 release tag로 이미지 태깅
9. 사용할 이미지 저장소(GitLab Container Registry 등)에 push
10. WSL 검증 환경 또는 EC2 대상에 `pull` 후 Compose rolling/recreate 배포
11. Nginx·Backend·DB·Redis·Kafka healthcheck와 핵심 API smoke test 수행
12. 실패 시 이전 이미지 태그로 rollback하고 Jenkins 결과·로그 링크를 남김

### Jenkins 구성 원칙

- Jenkins controller와 실제 Docker build/deploy 작업을 수행하는 agent를 분리한다.
- 초기 WSL에서는 전용 agent를 사용하고, Docker daemon 접근 권한은 해당 agent에만 부여한다.
- JCasC가 만든 permanent node의 inbound secret은 controller 기동 후 API에서 조회해 agent에 주입한다. 임의 secret을 `.env`에 생성하지 않는다.
- `.env.ci.example`은 깨끗한 workspace에서 `.env.ci`로 복사하고, 실제 registry·deploy credential은 Jenkins Credentials로만 주입한다.
- Docker socket을 마운트하는 방식은 초기 검증에서 허용할 수 있으나, 소켓 탈취 시 호스트 전체 권한으로 이어질 수 있으므로 EC2 운영 전 대체 방식 또는 전용 배포 agent를 검토한다.
- Jenkins 포트는 인터넷에 공개하지 않고 localhost 또는 Tailscale/private network로 제한한다.
- GitLab webhook secret과 registry credential은 Jenkins Credentials에서 참조한다.
- 배포 단계에서 `docker compose config`를 먼저 수행하고, healthcheck가 통과하기 전 기존 컨테이너를 제거하지 않는다.
- 이미지에는 `latest`만 사용하지 않고 commit SHA/tag를 사용해 재현성과 rollback을 보장한다.
- Push/Deploy는 기본적으로 skip이며, branch/tag 조건과 명시적 Pipeline parameter가 모두 켜진 경우에만 실행한다.

### GitLab·Jira 컨벤션 반영

- 브랜치: `<label>/<JIRA-KEY>-브랜치명`
- 커밋: `<type>: <JIRA-KEY> <message>`
- 인프라 변경 예시: `infra: S15P21E102-xxx Compose 실행 환경 추가`
- MR 라벨: `infra` 성격의 담당 라벨과 필요한 경우 `review` 라벨 적용
- 실제 Jenkins 정책은 GitLab 프로젝트의 보호 브랜치·필수 리뷰 수와 함께 맞춘다.

## 8. WSL 검증 계획

### 사전 조건

- WSL2와 Docker Desktop WSL integration 또는 WSL 내부 Docker Engine
- Docker Compose v2
- GitLab 접근 권한과 필요한 OAuth·API 테스트용 환경 변수
- 전체 `data` 프로파일 실행 전 WSL CPU·메모리·디스크 한도 확인

초기 예상 자원은 측정 전 가정이다. `core + app`은 약 4 vCPU·8GB RAM 수준부터 검증하고, HDFS·Spark·Worker를 포함한 `data`는 약 8 vCPU·16GB RAM 이상을 시작점으로 삼아 실제 사용량을 기록한다. 최종 EC2 사양은 이 측정 결과로 정한다.

### 검증 순서

1. `.env.wsl` 생성 및 값 검증
2. `docker compose config`로 변수 치환·서비스 의존성·포트 충돌 확인
3. `core` 기동 후 PostgreSQL·Redis·Kafka healthcheck 확인
4. Kafka 토픽 생성 정책과 producer/consumer 송수신 확인
5. `app` 기동 후 Nginx → Backend → PostgreSQL/Redis 연결 확인
6. GitHub OAuth callback과 세션 쿠키의 reverse proxy 동작 확인
7. `data` 기동 후 HDFS 저장·Spark 작업·Kafka 소비·DLQ 흐름 확인
8. Jenkins에서 동일 Compose 검증 파이프라인 실행
9. 컨테이너 재시작·호스트 재부팅 후 데이터 보존 확인
10. 실패 이미지 배포 후 이전 태그 rollback 확인

### 주요 테스트 시나리오

| ID | 시나리오 | 통과 조건 |
|---|---|---|
| WSL-01 | 빈 환경에서 전체 core 기동 | 지정된 healthcheck가 모두 통과 |
| WSL-02 | Backend DB 연결 | Spring Boot가 `postgres`로 연결되고 기본 API 응답 |
| WSL-03 | Redis 연결 | 캐시/세션 확인 및 재시작 후 연결 |
| WSL-04 | Kafka 송수신 | 소스별 토픽에 메시지가 발행·소비되고 offset 확인 |
| WSL-05 | Nginx reverse proxy | `/`, `/api`, WebSocket 경로가 의도한 upstream으로 전달 |
| WSL-06 | 분석 Job 상태 | `QUEUED` → `RUNNING` → 성공/부분성공/실패 상태가 조회됨 |
| WSL-07 | DLQ·재시도 | 재시도 후 실패 데이터가 원본과 함께 격리·재처리됨 |
| WSL-08 | 영속성 | 컨테이너 재생성 후 PostgreSQL·Kafka·HDFS 데이터가 보존됨 |
| WSL-09 | Jenkins 배포 | build/test/deploy/healthcheck 결과가 파이프라인에 남음 |
| WSL-10 | Rollback | 직전 이미지 태그로 서비스 복구 가능 |

## 9. EC2 이관 계획

### 1차 배포 형태

- EC2가 1대면 `compose.ec2.yaml`로 `core + app`을 운영하는 fallback을 사용한다.
- EC2가 2대면 `compose.ec2-ha.yaml`로 각 노드에 `app`만 실행하고, ALB가 두 Nginx를 분산한다.
- HA target은 서로 다른 AZ에 배치하고, 상태 저장소는 RDS·ElastiCache·MSK 등 managed HA를 우선한다.
- Jenkins는 같은 EC2에 둘 수도 있지만, 자원 경합과 보안 위험 때문에 별도 관리 호스트 또는 최소한 별도 Compose 프로파일로 분리한다.
- `data` 프로파일은 WSL 벤치마크 이후 EC2에 함께 배치할지, 별도 인스턴스로 분리할지 결정한다.
- 단일 fallback의 Docker named volume은 EBS에 두고 PostgreSQL dump·Parquet·중요 설정을 별도 백업한다. HA app 노드에는 상태 데이터를 local volume으로 두지 않는다.

### EC2 준비 항목

1. OS·인스턴스 타입·EBS 크기를 WSL 측정 결과로 결정
2. Docker Engine·Compose plugin·Git·Tailscale 설치
3. `/opt/gitjob` 등 배포 경로와 권한 분리
4. Security Group은 80/443과 제한된 SSH만 허용
5. Jenkins·PostgreSQL·Redis·Kafka·HDFS 관리 포트는 public inbound에서 제외
6. Tailscale을 통해 Jenkins와 내부 관리 화면 접근
7. Nginx TLS·도메인·GitHub OAuth callback URL 설정
8. EC2 운영용 `.env` 또는 SSM/Secrets Manager 연결
9. systemd 또는 부팅 시 Compose 자동 기동 정책 구성
10. Docker log rotation, 디스크 사용량 알림, PostgreSQL backup/restore 점검
11. 2대인 경우 ALB target group·`/health`·80→443 listener·Route53 alias 구성
12. ALB SG만 EC2 80에 접근하도록 제한하고, 서로 다른 AZ의 target 등록 확인

### EC2 배포 smoke test

- Nginx에서 Frontend가 정상 제공된다.
- `/api` 요청이 Backend로 전달되고 Backend가 PostgreSQL·Redis에 연결된다.
- GitLab에서 push 또는 수동 승인으로 Jenkins 배포가 실행된다.
- 분석 요청 API가 `202 Accepted`와 `analysisId`, `pollAfterSec`를 반환한다.
- 분석 상태 조회와 운영 지표 조회가 동작한다.
- Kafka consumer lag·DLQ·GitHub quota 지표의 미도착 상태가 임의의 정상값으로 위장되지 않는다.
- 컨테이너 재기동 후 핵심 데이터와 이전 배포 태그가 유지된다.
- 2대인 경우 한 EC2의 Backend/인스턴스를 중지해도 ALB가 다른 노드로 요청을 전달한다.
- 한 노드에서 로그인한 뒤 다른 노드로 요청해도 JWT/공유 session이 유지된다.

## 10. 단계별 작업 계획

| 단계 | 목표 | 주요 산출물 | 예상 소요 | 선행 조건 |
|---|---|---|---:|---|
| P0 | 배포 계약 확정 | 서비스 목록, 포트, 환경 변수, 이미지·토픽·볼륨 표 | 0.5~1일 | 현재 계획 검토 |
| P1 | 핵심 Compose | PostgreSQL·Redis·Kafka, healthcheck, named volume | 1~2일 | P0 |
| P2 | 앱 연결 | Backend·Frontend Dockerfile, Nginx, API/WS proxy | 1~2일 | 앱 빌드 구조 확정 |
| P3 | 데이터 프로파일 | Collector·Worker·HDFS·Spark·replay·DLQ | 2~3일 | Kafka 이벤트 계약·Worker 코드 |
| P4 | Jenkins CI/CD | Jenkinsfile, agent, credential, build/test/deploy/rollback | 1~2일 | P1~P2 |
| P5 | WSL 통합 검증 | smoke test, 장애·재시작·성능 결과 | 1일 | P1~P4 |
| P6 | EC2 이관 | 서버 bootstrap, TLS, backup, 운영 배포 | 1~2일 | EC2 발급 및 P5 결과 |
| P7 | 2-EC2 HA 검증 | ALB target, shared state, 장애 조치, rolling deploy | 1~2일 | EC2 2대·ALB·상태 endpoint |

### 단계별 완료 기준

- P1: `core` 프로파일을 깨끗한 WSL에서 반복 기동할 수 있다.
- P2: 브라우저에서 Nginx를 통해 Frontend와 Backend API를 함께 확인할 수 있다.
- P3: 원본 저장·Kafka 소비·Spark/HDFS 처리·실패 격리 흐름을 최소 데이터로 재현할 수 있다.
- P4: GitLab push에서 이미지 생성과 대상 환경 배포까지 자동화된다.
- P5: 테스트 결과와 WSL 자원 사용량이 문서로 남는다.
- P6: 환경 변수·도메인·인증서만 교체해 EC2에서 재배포할 수 있다.
- P7: 한 app 노드 장애 중에도 ALB를 통한 핵심 API가 유지되고, 한 노드씩 rolling deploy할 수 있다.

## 11. 의존성 및 미결정 사항

### 외부/팀 의존성

- EC2 인스턴스 타입, EBS 용량, 리전, public/private 네트워크 구조
- 2대 EC2 여부, 각 인스턴스의 AZ/private subnet, ALB 사용 여부
- RDS·ElastiCache·MSK 등 shared HA state 사용 여부와 비용/접근 정책
- 도메인·TLS 인증서·GitHub OAuth callback 주소
- GitLab Container Registry 사용 가능 여부
- Jenkins 실행 위치와 Docker build 권한 정책
- 애플리케이션별 실제 빌드·테스트 명령과 health endpoint
- Kafka 3개 토픽의 이름, partition 수, retention, 공통 envelope schema
- HDFS/Spark를 EC2 한 대에 포함할지 별도 인스턴스/managed 저장소로 분리할지

### 현재 확인이 필요한 항목

- Notion의 `운영 지표 조회` API는 관리자 권한 모델이 아직 정의되지 않았다. 초기에는 Tailscale/private network와 Jenkins 운영 계정으로 접근을 제한하고, 최종 권한 모델을 별도로 확정한다.
- 분석 상태 전달은 현재 server-directed polling(`pollAfterSec`)을 기준으로 하며, SSE/WebSocket 전환 여부는 API·프론트 구현 전에 결정한다.
- `JPA_DDL_AUTO=update`를 EC2에서 계속 사용할지 여부가 아니라, 운영에서는 마이그레이션을 도입할지 확정해야 한다.
- 자기 신고 기술을 지원 가능 공고 수에 포함할지는 인프라와 직접 연동되지는 않지만, 결과 smoke test 기준에 영향을 준다.
- Redis 비밀번호·세션 저장 방식·Kafka 인증(TLS/SASL) 수준은 EC2 노출 범위가 확정된 뒤 결정한다.

## 12. 위험 요소와 대응

| 위험 | 가능성/영향 | 대응 |
|---|---|---|
| HDFS·Spark·Kafka·Jenkins 동시 실행으로 WSL 자원 부족 | 높음/높음 | Compose profile 분리, 자원 제한, core/app 우선 검증, 사용량 측정 |
| Compose 내부에서 `localhost` 사용 | 높음/높음 | 모든 서비스 연결을 Compose DNS 서비스명으로 통일하고 smoke test에 포함 |
| Jenkins Docker 권한으로 호스트 장악 가능 | 중간/높음 | 전용 agent, private 접근, 최소 credential, EC2 운영 전 방식 재검토 |
| 운영 DB가 `ddl-auto=update`에 의존 | 중간/높음 | Flyway/Liquibase 등 마이그레이션을 P2/P6 전에 확정 |
| 단일 EC2 장애 시 서비스·데이터 동시 중단 | 중간/높음 | 2대면 ALB + shared state로 분리하고, 1대면 EBS backup·dump·S3 백업을 적용 |
| 두 EC2에서 local core를 동시에 실행해 데이터가 갈라짐 | 높음/높음 | HA overlay는 `app`만 실행하고 RDS·ElastiCache·MSK endpoint를 양쪽에 동일하게 주입 |
| ALB health가 실제 Backend 장애를 감지하지 못함 | 중간/높음 | Nginx `/health`를 Backend actuator에 연결하고 target failover 테스트 수행 |
| Kafka/HDFS 데이터 디스크 급증 | 중간/높음 | retention·파티션·로그 rotation·디스크 알림·Parquet 보관 정책 정의 |
| GitHub API quota 소진으로 분석이 멈춤 | 높음/중간 | 중앙 quota 관리, retry/backoff, `RATE_LIMITED` 상태와 재개 시각 노출 |
| 소스 코드가 초기 골격이라 CI 빌드가 즉시 불가능 | 현재 높음/중간 | P0에서 실제 모듈·빌드 명령 확인 후 Dockerfile/Jenkinsfile 작성 |

## 13. 산출물 체크리스트

### 문서

- [x] 날짜 포함 인프라 배포 준비 계획서
- [x] 2-EC2 HA 설계·장애 조치 계획서
- [x] Compose 서비스·포트·볼륨·healthcheck 표
- [x] WSL 실행 안내서 (`Infra/README.md`)
- [ ] EC2 bootstrap 및 운영 배포 안내서
- [x] backup/restore 실행 안내 (`Infra/README.md`)
- [ ] 장애 대응·rollback 안내서

### 구현 예정 파일

- [x] `Infra/compose/compose.yaml` (P1 core)
- [x] `Infra/compose/compose.wsl.yaml`
- [x] `Infra/compose/compose.ec2.yaml` (P1 core boundary)
- [x] `Infra/compose/compose.ec2-ha.yaml` (app-only HA overlay)
- [x] Backend·Frontend·Worker Dockerfile (가정한 build contract 기반)
- [x] Nginx 설정
- [x] Jenkinsfile 및 Jenkins agent/JCasC 설정 (credential 연결 전)
- [x] `.env.example`
- [x] healthcheck·backup·restore·replay·HA preflight 스크립트

## 14. 완료 정의

- 현재 단계에서 완료한 범위는 [인프라 준비도 점검 보고서](2026-08-27-infra-readiness.md)와 [2-EC2 HA 설계 문서](2026-08-27-ec2-high-availability-design.md)에 기록했다. 전체 서비스와 AWS HA의 실제 기동 완료를 의미하지 않으며, core/HA config 검증 결과와 실제 운영 검증을 구분한다.

- [ ] 새 WSL 환경에서 문서의 명령만으로 `core + app`을 재현할 수 있다.
- [ ] Compose 내부 DNS로 Backend·PostgreSQL·Redis·Kafka 연결이 검증된다.
- [ ] 데이터 프로파일을 별도로 실행·중지할 수 있고, named volume과 retention 정책이 확인된다.
- [ ] GitLab 변경을 Jenkins가 받아 테스트·이미지 빌드·배포·healthcheck를 수행한다.
- [ ] 실패 배포를 이전 이미지 태그로 rollback할 수 있다.
- [ ] 비밀값이 저장소와 빌드 로그에 노출되지 않는다.
- [ ] WSL 자원 사용량을 바탕으로 EC2 사양과 단일/분리 배포 결정을 기록한다.
- [ ] EC2에서는 80/443 외 관리 포트가 외부에 노출되지 않는다.
- [ ] 2대 EC2가 서로 다른 AZ의 ALB target으로 healthy 상태를 유지한다.
- [ ] 한 app 노드 장애 시 다른 노드로 API/Frontend/WebSocket 요청이 전환된다.
- [ ] DB/Redis/Kafka가 local volume이 아닌 HA endpoint로 양 노드에 연결된다.

## 15. 참고 문서

- [인프라 준비도 점검 보고서](2026-08-27-infra-readiness.md)
- [2대 EC2 고가용성 설계](2026-08-27-ec2-high-availability-design.md)
- [Infra 실행·구성 안내](../../Infra/README.md)

- [Notion 프로젝트 상위 페이지](https://app.notion.com/p/2-PJT-6fe0dff912cf83f1a2850101b8643bdf)
- [Notion 개발 환경](https://app.notion.com/p/ef50dff912cf83d4804b81de828c845a)
- [Notion 환경 변수](https://app.notion.com/p/33a0dff912cf8346b35b813737fdb1dd)
- [Notion 요구사항 명세서](https://app.notion.com/p/2780dff912cf83c7875001aed60d4d3f)
- [Notion 기능 명세서](https://app.notion.com/p/6a90dff912cf8295998f815878ab7a88)
- [Notion 와이어 프레임](https://app.notion.com/p/bdd0dff912cf82beaccd01dde091efc8)
- [Notion API 명세서](https://app.notion.com/p/e350dff912cf82759fb0017315b2823c)
