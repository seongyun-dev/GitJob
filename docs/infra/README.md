# Infrastructure 문서 목차

> 상태: WSL 실행 골격 구현, EC2 운영 전환 준비
>
> 기준일: 2026-08-28

## 1. 문서 안내

| 문서 | 내용 |
|---|---|
| [MR !3 수정·검증 기록](2026-08-28-mr3-fix-validation.md) | 검토 항목별 수정 내용과 실제 검증 결과 |
| [인프라 준비도](2026-08-27-infra-readiness.md) | 현재 구현·검증·미완료 항목 |
| [배포 준비 계획](2026-08-27-infra-deployment-plan.md) | Compose profile, CI/CD, WSL→EC2 전환 |
| [2대 EC2 HA 설계](2026-08-27-ec2-high-availability-design.md) | ALB, 무상태 app node, 공유 상태 저장소, failover |
| [실제 Infra 실행 안내](../../Infra/README.md) | 명령어와 운영 스크립트 사용법 |

## 2. 논리 구성

```text
사용자 → ALB(운영) / Nginx(로컬)
                    ├─ React static
                    ├─ /api → Spring Boot
                    └─ /ws  → Spring Boot WebSocket

Spring Boot → PostgreSQL / Redis / Kafka
Kafka → Collector·Worker → HDFS/Parquet·Spark
운영자(Tailscale/private network) → Jenkins·Kafka UI·Redis Insight
```

## 3. Compose profile

| Profile | 서비스 | 목적 |
|---|---|---|
| `core` | PostgreSQL, Redis, Kafka KRaft | 기본 상태 저장·메시징 |
| `app` | Backend, Frontend, Nginx | 사용자 서비스 |
| `data` | Collector, Worker, HDFS NameNode/DataNode, Spark master/worker | 수집·분석·대용량 처리 |
| `ci` | Jenkins controller/agent | 빌드·테스트·배포 |
| `observability` | Kafka UI, Redis Insight | 내부 운영 확인 |

환경별 override는 목적이 다르다.

| 파일 | 특징 |
|---|---|
| `Infra/compose/compose.wsl.yaml` | 저장소에서 image build, 모든 host binding loopback |
| `Infra/compose/compose.ec2.yaml` | EC2 single-host, Nginx HTTP 80만 publish |
| `Infra/compose/compose.ec2-ha.yaml` | EC2-A/B에서 `app`만 실행, 외부 HA state 사용 |

2대 구성에서는 각 EC2의 local named volume이 공유되지 않는다. 양쪽에서 PostgreSQL·Redis·Kafka를 동시에 실행하지 않고 RDS Multi-AZ, ElastiCache failover, MSK/동등한 외부 HA endpoint를 사용한다.

## 4. 로컬 실행

```bash
# .env.wsl 생성
./Infra/scripts/init-wsl.sh

# 기본 상태 계층
PROFILES=core ./Infra/scripts/up.sh

# 상태 확인 및 Kafka 송수신 확인
./Infra/scripts/healthcheck.sh
./Infra/scripts/kafka-smoke.sh

# 앱까지 연결
PROFILES=core,app ./Infra/scripts/up.sh

# 데이터 profile: HDFS/Spark 최소 cluster와 Parquet smoke 검증 완료
PROFILES=core,app,data ./Infra/scripts/up.sh
./Infra/scripts/spark-smoke.sh

# 같은 입력으로 Worker 1/2/4 비교를 수행한다. Worker UI host port는 충돌을
# 피하기 위해 publish하지 않고 Spark master UI에서 등록 수를 확인한다.
docker compose --project-directory . --env-file .env.wsl \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.wsl.yaml \
  --profile core --profile app --profile data \
  up -d --scale spark-worker=4 spark-worker
```

Compose 내부에서는 `localhost`가 아니라 service name을 사용한다.

| 대상 | 컨테이너 주소 | WSL host 주소 |
|---|---|---|
| PostgreSQL | `postgres:5432` | `127.0.0.1:${POSTGRES_PORT}` |
| Redis | `redis:6379` | `127.0.0.1:${REDIS_PORT}` |
| Kafka | `kafka:9092` | `127.0.0.1:${KAFKA_EXTERNAL_PORT}` |
| Nginx | `nginx:80` | `127.0.0.1:${NGINX_HTTP_PORT}` |
| Jenkins | `jenkins:8080` | `127.0.0.1:${JENKINS_HTTP_PORT}` |

`down.sh`는 기본적으로 named volume을 보존한다. volume까지 삭제하거나 PostgreSQL dump를 restore할 때는 스크립트가 요구하는 확인 변수를 명시한다.

```bash
CONFIRM=yes ./Infra/scripts/down.sh --volumes
./Infra/scripts/backup-postgres.sh
CONFIRM_RESTORE=yes ./Infra/scripts/restore-postgres.sh .local/backups/<dump>
./Infra/scripts/replay.sh <topic> <payload.ndjson>
```

## 5. Edge·Healthcheck

Nginx는 다음 경로를 제공한다.

| 경로 | 의미 |
|---|---|
| `/` | Frontend SPA |
| `/api`, `/api/` | Backend reverse proxy |
| `/ws/` | WebSocket upgrade proxy |
| `/health` | Backend Actuator를 확인하는 readiness; ALB target용 |
| `/nginx-health` | Nginx process만 확인하는 liveness |

ALB가 TLS를 종료하는 경우 `X-Forwarded-Proto`를 Backend에 전달해 OAuth redirect와 secure cookie 판단이 원래 요청 scheme을 유지하도록 한다.

## 6. 비밀값·네트워크 보안

- `.env.example`에는 이름과 placeholder만 넣고 실제 secret은 커밋하지 않는다.
- 로컬 secret은 `.env.wsl`, 운영 secret은 Jenkins Credentials 또는 AWS SSM/Secrets Manager에 둔다.
- GitHub OAuth client secret, Token, JWT secret, DB password, webhook secret, PEM key를 로그·이미지·Git에 넣지 않는다.
- WSL의 DB/Redis/Kafka/관리 UI는 loopback에만 bind한다.
- EC2의 외부 진입점은 Nginx/ALB 80·443으로 제한하고 관리 UI·SSH는 private network/Tailscale 또는 SSM을 사용한다.
- Jenkins Docker socket agent는 로컬 편의를 위한 구성이다. 운영에서는 isolated/rootless builder를 검토한다.

## 7. CI/CD 흐름

```text
GitLab webhook
  → Jenkins Validate
  → Backend test
  → Frontend test/build
  → image build
  → (승인된 branch/tag) image push
  → EC2 deploy
  → healthcheck / rollback
```

이미지는 `latest`가 아니라 commit SHA 또는 release tag로 고정한다. 2대 HA rolling deploy는 node-a 배포 → ALB healthy 확인 → node-b 배포 → 재확인 순서다.

## 8. 상태 및 완료 기준

현재 확인된 범위:

- PostgreSQL·Redis·Kafka core의 Compose config와 healthcheck
- 현재 환경에서 실행한 Kafka smoke test
- WSL loopback 경계, EC2 override, HA app-only Compose 병합
- HDFS 최초 format·DataNode 등록·put/get·NameNode 재시작 영속성
- Spark 3.5.3 Parquet smoke와 Worker 1/2/4 확장
- Jenkins agent image의 Java/Node/npm/Docker/Compose/Git/SSH toolchain
- Nginx API/WS/readiness 설정과 Jenkinsfile/JCasC 골격

재시작 영속성·PostgreSQL backup/restore의 상세 결과는 [인프라 준비도 문서](2026-08-27-infra-readiness.md)에 기록되어 있으나, 위 목록에는 이번 문서 작성에서 직접 재확인한 항목만 적었다.

아직 외부 상태로 남은 범위:

- Backend·Frontend·AI source가 추가된 뒤 실제 image build와 통합 연결
- Collector/Worker를 포함한 전체 data pipeline과 full benchmark/resource 측정
- GitLab webhook·registry push·EC2 credential 기반 배포
- Jenkins controller 실제 기동·agent online·Pipeline 실행
- AWS ALB·TLS·Route53·RDS/ElastiCache/MSK
- 실제 장애 주입, failover, rolling rollback

## 9. 원문 출처

- [개발 환경](https://app.notion.com/p/77f0dff912cf8305a10b017245b40a78)
- [환경 변수](https://app.notion.com/p/0b60dff912cf836084ee01fb375e5cbd)
- [깃랩/지라 컨벤션 가이드](https://app.notion.com/p/e2a0dff912cf824a85340178601b1997)
- [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d)
- [WBS](https://app.notion.com/p/b0b0dff912cf827781ee8119fc1a7cbd)
