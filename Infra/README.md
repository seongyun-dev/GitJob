# GitJob Infrastructure

이 문서는 현재 인프라 구성이 어떻게 되어 있는지, 무엇이 실제로 검증됐는지,
무엇을 추가로 연결해야 하는지를 정리한 실행 문서다. 다음 문서와 함께
[인프라 준비도 점검 문서](../docs/infra/2026-08-27-infra-readiness.md)와 함께
확인한다.

## 1. 현재 구성 요약

Compose 파일 하나를 공통 진입점으로 사용하고, 프로파일로 무거운 서비스를
분리했다. WSL에서는 `compose.wsl.yaml`이 소스 기반 build와 loopback 포트를
추가하고, 현재 지급된 2대 EC2에서는 `compose.ec2.yaml`을 서비스 노드에,
`compose.ec2-data.yaml`을 데이터 노드에 적용한다. 두 EC2 override 모두
원격 checkout의 소스 기반 build를 제공하며, `compose.ec2.yaml`은 public Nginx
경계와 core의 private listener를 열고 `compose.ec2-data.yaml`은 HDFS/Spark와
원격 core를 사용하는 Collector/Worker를 구성한다. 향후 공유 상태 저장소가
준비되면 `compose.ec2-ha.yaml`을 각 app
노드에서 독립적으로 실행하고 AWS ALB가 두 Nginx를 분산한다.

```text
GitLab ── Poll SCM ──▶ Jenkins controller ──▶ restricted SSH deploy agent
                               │
Browser ── 127.0.0.1:8080 / EC2:80 ──▶ Nginx
                                        ├─▶ Frontend static
                                        └─▶ Backend ── PostgreSQL
                                                    ├─ Redis
                                                    └─ Kafka

Jenkins ── SSH ──▶ EC2 git pull/build/up (service → data)
Collector ── Kafka ── Worker ── HDFS/Parquet + Spark
```

2대 EC2의 목표 구조는 [EC2 고가용성 설계 문서](../docs/infra/2026-08-27-ec2-high-availability-design.md)에
별도로 정리했다. 핵심은 EC2를 무상태 app 노드로 이중화하고, PostgreSQL·Redis·Kafka
같은 상태 저장 계층은 RDS·ElastiCache·MSK 등 공유 HA endpoint로 분리하는 것이다.

현재 Git 저장소의 `BE/`, `FE/`, `AI/`는 빈 골격이므로 실제 애플리케이션을
기동한 상태는 아니다. 다만 소스가 들어온다는 전제의 build context, health
endpoint, 연결 환경변수, 서비스 의존관계는 미리 정의해 두었다.

## 2. 프로파일과 서비스

| 프로파일 | 서비스 | 역할 | 현재 상태 |
|---|---|---|---|
| `core` | `postgres` | 서비스 DB·분석 Snapshot | WSL 실제 기동/검증 완료 |
| `core` | `redis` | 캐시·세션·작업 보조 저장소 | WSL 실제 기동/검증 완료 |
| `core` | `kafka` | 수집·분석 이벤트, replay | WSL 실제 기동/송수신 검증 완료 |
| `app` | `backend` | Spring Boot API·분석 Job API | 소스 투입 후 build/연결 검증 필요 |
| `app` | `frontend` | React production static | 소스 투입 후 build 검증 필요 |
| `app` | `nginx` | 정적 파일·API·WebSocket reverse proxy | 설정 파일 작성, backend/frontend 연결 대기 |
| `data` | `collector` | 외부 소스 수집·Kafka producer | Python 모듈 계약 대기 |
| `data` | `worker` | Kafka consumer·분석 작업 | Python 모듈/이벤트 계약 대기 |
| `data` | `hdfs-namenode`, `hdfs-datanode` | 원본·장기 데이터/Parquet 저장 | XML env·volume 초기화·최초 format·put/get·재시작 영속성 검증 완료 |
| `data` | `spark-master`, `spark-worker` | 배치·스트리밍 처리 | 공식 Spark 3.5.3 image/foreground command와 1·2·4 worker Parquet smoke 검증 완료 |
| `ci` | `jenkins`, `jenkins-agent` | CI/CD controller와 제한 agent | controller 발급 secret bootstrap 및 credential 연결 대기 |
| `observability` | `kafka-ui`, `redis-insight` | WSL 디버깅/운영 보조 | 선택 프로파일, UI 실기동 대기 |

전체 Compose에는 모든 서비스가 들어 있지만, 기본 실행은 자원과 소스 상태를
고려해 `core`만 활성화한다.

## 3. 파일별 구성

```text
Infra/
├── compose/
│   ├── compose.yaml          # 서비스, profiles, 내부 DNS, healthcheck, volumes
│   ├── compose.wsl.yaml      # WSL build와 127.0.0.1 포트
│   ├── compose.ec2.yaml      # 서비스/core EC2 + 단일 EC2 fallback
│   ├── compose.ec2-data.yaml # 분리된 Hadoop/Spark data EC2
│   └── compose.ec2-ha.yaml   # 2대 EC2 app 노드용 override
├── docker/
│   ├── backend/Dockerfile    # Java 21 + Gradle + Spring Boot 가정
│   ├── frontend/Dockerfile   # Node/npm + React dist 가정
│   ├── worker/Dockerfile     # Python requirements.txt + collector/worker 가정
│   ├── spark/Dockerfile      # 공식 Spark + Python job runtime
│   └── jenkins/              # controller/agent 이미지 가정
├── nginx/                    # edge Nginx와 SPA reverse proxy 설정
├── jenkins/                  # JCasC, plugin 목록, job 안내
└── scripts/                  # 기동, 종료, health, smoke, backup/restore, replay
```

루트의 `Jenkinsfile`은 아래 흐름을 위한 골격이다.

```text
validate Compose → backend test → frontend test
→ split EC2 SSH deploy (각 EC2 git pull/build/up)
→ service core health → data up → service app health
```

## 4. WSL 실행

### 사전 조건

- WSL2
- Docker Desktop WSL integration 또는 WSL 내부 Docker Engine
- Docker Compose v2
- Docker daemon 실행

저장소는 WSL 파일시스템 안에 두는 것을 권장한다. 먼저 환경변수 파일을 만들고
core를 실행한다.

```bash
./Infra/scripts/init-wsl.sh
./Infra/scripts/up.sh
./Infra/scripts/healthcheck.sh
./Infra/scripts/kafka-smoke.sh
```

처음 생성되는 `.env.wsl`은 Git에 포함되지 않으며, 초기화 스크립트가 PostgreSQL,
Redis, JWT, Jenkins, webhook용 임시 secret을 생성한다. OAuth client secret과
GitHub token은 직접 입력하지 말고 로컬 secret 또는 Jenkins Credentials에 둔다.

### 실행 범위 선택

```bash
# 기본: PostgreSQL + Redis + Kafka
PROFILES=core ./Infra/scripts/up.sh

# 앱 연결 환경
PROFILES=core,app ./Infra/scripts/up.sh

# 데이터 파이프라인까지 (HDFS/Spark와 최소 worker 1개)
PROFILES=core,app,data ./Infra/scripts/up.sh

# Spark worker 수를 바꾸어 같은 smoke job을 반복
docker compose --project-directory . --env-file .env.wsl \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.wsl.yaml \
  --profile core --profile app --profile data \
  up -d --scale spark-worker=2 spark-worker
./Infra/scripts/spark-smoke.sh

# 전체 구조(소스/image/자원이 준비된 경우). ci는 controller-first bootstrap을 사용
PROFILES=core,app,data,ci,observability ./Infra/scripts/up.sh
```

단일 호스트의 `app`, `data`는 WSL 또는 `compose.ec2.yaml`의 health 기반
`depends_on`으로 local `core`를 기다린다. 반면 2대 HA app 노드는 `core`를
실행하지 않고 외부 HA endpoint에 연결하므로 `compose.ec2-ha.yaml`과
`PROFILES=app`만 사용한다. 현재 저장소에서 전체 실행을 하면 BE/FE/AI 소스와
build image가 없어 실패한다. 이것은 Compose 누락이 아니라 아래 7장의 선행
계약이 아직 없는 상태다.

### Compose 최종 설정 확인

```bash
docker compose \
  --env-file .env.wsl \
  --project-directory . \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.wsl.yaml \
  --profile core --profile app --profile data --profile ci \
  --profile observability config
```

Compose는 여러 `-f` 파일을 순서대로 병합한다. 공통 파일을 먼저, 환경 override를
나중에 지정해야 한다.

## 5. 포트·내부 DNS·영속성

| 대상 | WSL 기본 host | Compose 내부 주소 | 공개 범위 |
|---|---:|---|---|
| PostgreSQL | `127.0.0.1:5432` | `postgres:5432` | WSL loopback only |
| Redis | `127.0.0.1:6379` | `redis:6379` | WSL loopback only |
| Kafka host listener | `127.0.0.1:9094` | `kafka:9092` | WSL loopback only |
| Nginx | `127.0.0.1:8080` | `nginx:80` | WSL loopback / EC2 public HTTP |
| Jenkins | `127.0.0.1:8081` | `jenkins:8080` | WSL loopback; EC2 Tailscale 예정 |
| Kafka UI | `127.0.0.1:8082` | `kafka-ui:8080` | WSL loopback; EC2 Tailscale 예정 |
| Spark master UI | `127.0.0.1:8083` | `spark-master:8080` | WSL loopback |
| Redis Insight | `127.0.0.1:8001` | `redis-insight:5540` | WSL loopback |

컨테이너 간 연결에 `localhost`를 쓰지 않는다. Backend는 `postgres`, `redis`,
`kafka:9092`를 사용한다. WSL host 도구만 `localhost:9094`를 사용한다.

PostgreSQL, Redis, Kafka, HDFS, Jenkins home은 Compose project-scoped named
volume에 저장한다. 따라서 `gitjob`과 `gitjob-ci-<build>`은 서로 다른 volume을 사용한다.
`./Infra/scripts/down.sh`는 volume을 보존하며, volume 삭제는 다음처럼 명시한다.

```bash
CONFIRM=yes ./Infra/scripts/down.sh --volumes
```

호스트의 PostgreSQL이 이미 `5432`를 사용하면 `.env.wsl`의 `POSTGRES_PORT`만
`15432`로 바꾸고 내부 `DB_PORT=5432`는 유지한다.

## 6. 백업·복구·Kafka 검증

```bash
./Infra/scripts/backup-postgres.sh
CONFIRM_RESTORE=yes ./Infra/scripts/restore-postgres.sh \
  .local/backups/<database>-<timestamp>.dump
./Infra/scripts/replay.sh <topic> ./path/to/payloads.ndjson
```

백업은 `.local/backups/`에 생성되며 Git에서 무시된다. `restore`는 현재 DB 객체를
덮어쓰므로 개발 데이터가 필요하지 않을 때만 실행한다.

## 7. 현재 가정한 애플리케이션 계약

실제 코드가 들어오면 아래 항목을 먼저 확인하고 Dockerfile/Compose를 조정한다.

| 영역 | 현재 가정 | 실제 투입 후 확인할 것 |
|---|---|---|
| Backend | `BE/gradlew`, Java 21, `bootJar` | Gradle task, jar 경로, actuator health 경로 |
| Frontend | `FE/package-lock.json`, `npm ci`, `npm run build`, `dist/` | package manager, output directory, runtime env 방식 |
| Worker | `AI/requirements.txt`, `python -m collector/worker` | 실제 module/entrypoint, CPU·메모리, health endpoint |
| Backend health | `GET /actuator/health` | 보안 설정과 실제 endpoint |
| Worker health | `GET /health` | HTTP health server 존재 여부 |
| Kafka | 4개 provisional topic, auto-create off | topic명, partition, retention, envelope/schema, DLQ policy |
| HDFS | `apache/hadoop:3.4.1`, `hdfs://hdfs-namenode:8020`, replication 1 | `CORE-SITE.XML_*`/`HDFS-SITE.XML_*`, `/data` volume 권한, 최초 format |
| Spark | `apache/spark:3.5.3-scala2.12-java11-python3-ubuntu` 계열, `spark://spark-master:7077` | foreground master/worker command, `spark-submit`, worker 1/2/4와 executor 자원 |
| Nginx | `/api/`, `/ws/`, `/` upstream, `/health` readiness, `/nginx-health` liveness | 실제 API prefix, actuator path, STOMP/SSE path, CORS/cookie 정책 |

## 8. Jenkins와 보안 구성

Jenkins controller는 `Infra/jenkins/casc/jenkins.yaml`을 JCasC로 읽고, agent만
Docker socket을 받는다. `PROFILES=...,ci ./Infra/scripts/up.sh`는 controller를 먼저
기동하고 `docker-agent` node의 JNLP secret을 Jenkins API에서 조회한 뒤 agent를
연결한다. secret은 `.local/jenkins/` 아래의 0600 파일에서 agent 프로세스에만
읽히며 Compose의 `Config.Env`나 `.env.example`에는 넣지 않는다. 이 방식은 WSL 검증용이며 socket을 가진
agent가 침해되면 호스트 권한으로 이어질 수 있다.

현재 split EC2 전환은 다음 원칙으로 보완한다.

1. GitLab pull token을 각 EC2의 Git credential store에 별도로 등록
2. `gitjob-gitlab-scm`과 `gitjob-ec2-ssh` Credential을 Jenkins에 등록
3. Jenkins Job을 `develop` Pipeline from SCM + Poll SCM으로 설정
4. Jenkins는 public inbound에서 제외하고 SSH로 EC2에 접근
5. 배포 전 `docker compose config`, 배포 후 healthcheck를 실행
6. HDFS volume을 삭제하지 않고 실패 시 이전 checkout/이미지로 수동 복구

`.env.example`에는 변수명과 형식만 두며 실제 credential을 넣지 않는다.

## 9. EC2 전환 절차

EC2가 발급되면 다음 순서로 이관한다.

1. WSL `core`, `app`, `data`의 health·자원 사용량을 기록
2. EC2 instance type, EBS 크기, data 분리 여부 결정
3. Docker Engine/Compose plugin/Git/Tailscale 설치
4. `/opt/gitjob` 배포 경로와 deploy user 생성
5. `develop`을 각 EC2의 배포 checkout으로 지정하고 로컬 build를 사용
6. Security Group은 80/443과 제한 SSH만 허용(현재 UFW는 변경하지 않음)
7. `compose.ec2.yaml`로 Nginx HTTP만 publish하고 DB/Redis/Kafka/Jenkins는 비공개 유지
8. TLS 인증서와 443 Nginx server block 추가
9. GitHub OAuth callback, domain, cookie secure, CORS를 운영값으로 변경
10. PostgreSQL dump·Parquet·EBS backup과 디스크/log rotation 설정
11. Jenkins deploy 후 smoke test와 rollback을 실행

EC2 실행 형태는 다음과 같다.

```bash
ENV_FILE=.env.ec2 \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml \
PROFILES=core,app \
./Infra/scripts/up.sh
```

현재 EC2 override는 Nginx HTTP 80과 split 배포에 필요한 core의 private
binding을 제공한다. HTTPS 443, DNS, 인증서, SSM/Secrets Manager,
systemd 자동기동은 서버 발급 후 운영 정보가 확정되면 추가한다.

## 10. EC2 서비스/data 분리 구성

현재 지급된 두 EC2는 고가용 app 노드로 사용하지 않고, 서비스 계층과 데이터
처리 계층을 분리한다. `J15E102`에는 `core + app`을, `J15E102A`에는 `data`를
실행한다. `data` 프로파일은 Collector·Worker·HDFS·Spark를 함께 포함한다.

```text
J15E102
  Nginx → Frontend → Backend → PostgreSQL/Redis/Kafka
                                      ▲
                                      │ private endpoint
J15E102A
  Collector/Worker ───────────────────┘
  HDFS NameNode/DataNode + Spark master/worker (local)
```

### 서비스 서버

`.env.service`는 다음 값을 기준으로 만든다.

```dotenv
COMPOSE_PROJECT_NAME=gitjob-service
COMPOSE_PROFILES=core,app,ci
DEPLOYMENT_MODE=split
EC2_CORE_BIND_ADDRESS=<J15E102-private-ip>
EC2_KAFKA_ADVERTISED_HOST=<J15E102-private-ip>
EC2_KAFKA_EXTERNAL_PORT=9094
DB_HOST=postgres
REDIS_HOST=redis
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
```

실행 명령은 다음과 같다. Jenkins가 아직 필요하지 않으면 `ci`를 빼고 먼저
`core,app`만 기동한다.

```bash
ENV_FILE=.env.service \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml \
PROFILES=core,app,ci \
./Infra/scripts/up.sh
```

`EC2_CORE_BIND_ADDRESS`는 public IP가 아니라 서비스 EC2의 private IP로 두고,
SSAFY 제공 네트워크 경계에서 `J15E102A`의 private IP만 5432·6379·9094에 접근할 수
있도록 확인한다. 현재 작업에서는 UFW를 변경하지 않는다. Kafka는 컨테이너 내부
Backend용 `kafka:9092`와 데이터 서버용
private listener를 분리한다.

서비스 EC2의 UFW/보안 경계 변경은 현재 작업 범위가 아니다. 관리자 CIDR과 private
IP가 확정되고 별도 승인을 받은 뒤에만 방화벽 정책을 검토한다.

```text
현재는 UFW 명령을 실행하지 않는다.
```

데이터 EC2는 외부에 Hadoop/Spark 포트를 열지 않고 SSH 관리망만 허용한다.
`J15E102A`의 주소를 서비스 EC2에서 접근해야 하는 별도 운영 요구가 있을 때만
그 목적의 private rule을 추가한다.

### 데이터 서버

`.env.data`는 서비스 서버의 private endpoint와 데이터 서버의 local endpoint를
함께 사용한다.

```dotenv
COMPOSE_PROJECT_NAME=gitjob-data
COMPOSE_PROFILES=data
DEPLOYMENT_MODE=split
DB_HOST=<J15E102-private-ip>
REDIS_HOST=<J15E102-private-ip>
KAFKA_BOOTSTRAP_SERVERS=<J15E102-private-ip>:9094
HDFS_URI=hdfs://hdfs-namenode:8020
PARQUET_ROOT=hdfs:///gitjob/parquet
SPARK_MASTER_URL=spark://spark-master:7077
HDFS_REPLICATION_FACTOR=1
```

`J15E102A`에서는 반드시 `compose.ec2-data.yaml`을 사용한다. `compose.ec2.yaml`
은 local core 의존성을 추가하므로 data 프로파일만 실행할 때 사용할 수 없다.

```bash
ENV_FILE=.env.data \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml \
PROFILES=data \
./Infra/scripts/up.sh
```

초기에는 HDFS/Spark를 먼저 확인하고, AI 소스와 이미지가 준비된 뒤 Collector와
Worker를 실행한다. 일반 애플리케이션 배포에서는 HDFS volume을 삭제하거나
재생성하지 않는다.

### split Jenkins 배포

루트 `Jenkinsfile`은 `DEPLOYMENT_MODE=split`과 `develop` 기준으로 동작한다.
Jenkins는 Registry push를 수행하지 않고 `gitjob-ec2-ssh` Credential로 각 EC2에
SSH하여 `git pull --ff-only origin develop` 후 로컬 Docker build와 Compose 실행을
순서대로 수행한다. 각 서버에는 secret을 포함한 `.env.service` 또는 `.env.data`를
미리 배치하고, Jenkins는 secret env 파일·GitLab token·PEM을 서버 간에 복사하지
않는다. GitLab Integration webhook은 사용하지 않고 Poll SCM을 사용한다.

현재 구성은 서비스와 데이터의 역할 분리이며 HA가 아니다. Kafka single broker,
HDFS replication 1, local named volume은 각각 단일 장애점이다. PostgreSQL dump와
HDFS/중요 설정은 별도 EBS 또는 S3로 백업한다.

## 11. EC2 2대 고가용성 구성

### 실행 원칙

- 두 EC2에 동일한 commit SHA의 Backend·Frontend image를 배포한다.
- 각 노드에서는 `compose.ec2-ha.yaml`의 `app` 프로파일만 실행한다.
- AWS ALB target group에 두 EC2를 등록하고 `/health`를 health path로 사용한다.
- ALB가 80/443 외부 진입점이 되고, EC2의 80은 ALB Security Group에서만 허용한다.
- 두 EC2의 local named volume은 서로 공유되지 않으므로 DB/Redis/Kafka를 양쪽에서
  동시에 실행하지 않는다.

```text
Route53/DNS → ALB(ACM TLS) → EC2-A Nginx:80 → Backend/Frontend
                         └→ EC2-B Nginx:80 → Backend/Frontend
                              │
                         shared HA state
                    RDS / ElastiCache / MSK / S3
```

노드별 환경 파일은 `.env.example`을 복사해 만들고 다음 값을 설정한다.

```dotenv
DEPLOYMENT_MODE=ha
EC2_NODE_NAME=node-a             # node-b on the second server
COMPOSE_PROFILES=app
DB_HOST=<RDS-Multi-AZ-endpoint>
REDIS_HOST=<ElastiCache-endpoint>
KAFKA_BOOTSTRAP_SERVERS=<MSK-brokers>
ALB_HEALTHCHECK_URL=https://<service-domain>/health
PUBLIC_BASE_URL=https://<service-domain>
COOKIE_SECURE=true
```

두 노드에서 `JWT_SECRET`, OAuth, topic, DB 사용자와 같은 애플리케이션 설정은
동일해야 한다. 실제 secret은 SSM/Secrets Manager 또는 Jenkins Credentials에서
주입한다.

공유 endpoint와 ALB health URL을 입력한 뒤에는 다음 preflight로 HA 설정을
확인한다.

```bash
ENV_FILE=.env.ec2-node-a \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-ha.yaml \
PROFILES=app \
./Infra/scripts/ha-preflight.sh
```

```bash
# EC2-A와 EC2-B에서 각각 실행
ENV_FILE=.env.ec2-node-a \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-ha.yaml \
PROFILES=app \
./Infra/scripts/up.sh
```

EC2-B에서는 환경 파일명과 `EC2_NODE_NAME`만 `node-b`에 맞춘다. `/health`는
Backend `/actuator/health`를 프록시하므로 Backend·DB·Redis·Kafka가 준비되지 않은
노드는 ALB에서 제외된다. Nginx 프로세스만 확인하려면 `/nginx-health`를 사용한다.

두 EC2만으로 local PostgreSQL primary/standby, Redis Sentinel, Kafka quorum,
HDFS NameNode HA를 모두 완성할 수는 없다. managed HA 서비스를 사용할 수 없다면
앱 계층만 HA로 표시하고, 상태 계층은 백업·수동 failover가 필요한 단일 장애점이라고
운영 문서에 명시한다. 상세 장애 테스트와 롤링 배포 순서는 [EC2 고가용성 설계 문서](../docs/infra/2026-08-27-ec2-high-availability-design.md)를 따른다.

## 12. 준비도 판단

| 항목 | 준비도 | 근거 |
|---|---|---|
| 인프라 구조 설명 | 준비됨 | profiles·서비스·경계·파일구조 문서화 |
| 핵심 저장소 기동 | 검증됨 | WSL에서 core health/smoke/영속성 통과 |
| 앱 Compose 연결 | 골격 준비 | Dockerfile·env·Nginx·health 계약 작성, 실제 소스 대기 |
| 데이터 파이프라인 | 부분 검증 | HDFS/Spark 최소 cluster·Parquet smoke와 Worker 1/2/4 확장 검증, Collector/Worker 통합·benchmark 대기 |
| Jenkins CI/CD | 실행 골격 준비 | JCasC·controller-first agent bootstrap·direct-build Jenkinsfile 작성, Jenkins Credentials/job 설정 대기 |
| EC2 운영 | 단일 노드 골격 / HA 설계 준비 | 서버·ALB·상태 저장소·도메인·TLS·보안그룹·백업 정책 필요 |

현재 “무엇이 동작하는가”는 `core` 실행 결과로 확인하고, 2대 구성은
`compose.ec2-ha.yaml`과 ALB/상태 저장소 전환 계획으로 구분한다. 소스가 들어오면
먼저 실제 build contract를 맞춘 뒤 app 노드 2대의 failover를 검증한다.
