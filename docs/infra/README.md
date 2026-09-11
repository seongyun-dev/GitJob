# Infrastructure 문서 목차

> 상태: 2대 EC2 운영 배포 완료, S15P21E102-207 HDFS·Spark 2-host 분산 전환 진행 중
> (S15P21E102-207 Phase 0-10 완료, 후속 항목은 Phase 10 문서 9절 참조)
>
> 기준일: 2026-09-11

## 1. 문서 안내

| 문서 | 내용 |
|---|---|
| [HDFS·Spark 2-Host 분리 계획](2026-09-10-hdfs-spark-two-host-split-plan.md) | S15P21E102-207 Tailscale 기반 DataNode·Spark Worker 확장, 단계별 gate와 롤백 계획 |
| [HDFS·Spark Phase 0 사전점검](2026-09-10-hdfs-spark-two-host-phase0-preflight.md) | 양쪽 EC2의 Tailscale·자원·서비스·HDFS·Spark 기준선과 운영 checkout blocker |
| [HDFS·Spark Phase 1 구현·정적 검증](2026-09-10-hdfs-spark-two-host-phase1-static-implementation.md) | Tailscale cluster Compose, 독립 worker project, rack mapping, Spark 공통 설정과 회귀 검증 |
| [HDFS·Spark Phase 2 복구점 생성 차단](2026-09-10-hdfs-spark-two-host-phase2-recovery-point-blocked.md) | active WebHDFS writer와 EBS snapshot 권한 부재로 운영 변경 없이 중단한 기록 |
| [HDFS·Spark Phase 2 Linux off-host 복구점](2026-09-10-hdfs-spark-two-host-phase2-linux-recovery-point.md) | saveNamespace와 NameNode metadata archive를 service 서버에 복사·검증한 완료 기록 |
| [HDFS·Spark Phase 3 Data HDFS Tailscale 전환](2026-09-10-hdfs-spark-two-host-phase3-data-hdfs-tailscale.md) | NameNode와 기존 DataNode 3개의 롤링 Tailscale 전환, local bridge UFW 경계와 운영 검증 |
| [HDFS·Spark Phase 4 Service DataNode-4 가입](2026-09-10-hdfs-spark-two-host-phase4-service-datanode4.md) | service 서버 독립 project/volume의 DataNode-4 가입, Docker proxy 주소 보정과 `/rack-b` 생성 |
| [HDFS·Spark Phase 5 교차 host 복제 canary](2026-09-10-hdfs-spark-two-host-phase5-cross-host-replication.md) | canary 경로의 replication 2 교차 host 배치, 단일 DataNode 중지 read 검증과 재복제 미검증 한계 |
| [HDFS·Spark Phase 6 Spark Master·Worker-1 전환](2026-09-10-hdfs-spark-two-host-phase6-spark-master-tailscale.md) | host network·Tailscale 전환, hostname 해석·wildcard bind 결함 수정과 내용 기반 결과 동일성 검증 |
| [HDFS·Spark Phase 7 Service Spark Worker-2 가입](2026-09-11-hdfs-spark-two-host-phase7-service-spark-worker2.md) | 별도 project의 Worker-2 등록과 두 Tailscale IP ALIVE 확인, driver 주소 미고정으로 인한 executor 미참여 제약 |
| [HDFS·Spark Phase 8 driver·BlockManager 포트 고정](2026-09-11-hdfs-spark-two-host-phase8-driver-port-pinning.md) | Tailscale 주소·고정 포트 적용, 두 host executor 등록과 교차 host task 수행 확인, UFW 불필요 근거 |
| [DataNode 간 재복제 경로 수정](2026-09-11-hdfs-datanode-hostname-rereplication-fix.md) | rack-a→rack-b 전송 실패의 원인인 hostname 설정 누락 수정, 정체된 배치 위반 90건 자동 해소 |
| [HDFS·Spark Phase 9 분산 처리 검증](2026-09-11-hdfs-spark-two-host-phase9-distributed-verification.md) | shuffle canary·HDFS canary·1일치 GH Archive 실제 job, 단일 Worker 결과 일치와 노드 상실 자동 복구 재검증 |
| [HDFS·Spark Phase 10 안정화 관측](2026-09-11-hdfs-spark-two-host-phase10-stabilization.md) | 31분 연속 관측 결과, 미관측 항목(실사용자 E2E·Kafka lag)과 tailnet 노출 범위 실측 |
| [운영 상태 감시](health-monitoring.md) | 배포와 무관한 주기 감시, 설치 방법, 감시하지 않는 것 |
| [첫 운영 배포 기록](2026-09-09-first-production-deploy.md) | 배포 전후 상태, 배포 후 수동 단계, CDC 종단 검증, 이날 드러난 도구 결함 |
| [지급 서버 사양·네트워크 실측](2026-08-31-server-inspection.md) | J15E102/J15E102A 실제 사양, runtime, UFW, private network 점검 결과 |
| [MR !3 수정·검증 기록](2026-08-28-mr3-fix-validation.md) | 검토 항목별 수정 내용과 실제 검증 결과 |
| [인프라 준비도](2026-08-27-infra-readiness.md) | 현재 구현·검증·미완료 항목 |
| [배포 준비 계획](2026-08-27-infra-deployment-plan.md) | Compose profile, CI/CD, WSL→EC2 전환 |
| [J15E102 서비스 서버 문서](2026-08-31-ec2-service-node-runbook.md) | 서비스·core·Jenkins EC2 접속·기동·보안 |
| [J15E102A 데이터 서버 문서](2026-08-31-ec2-data-node-runbook.md) | Hadoop/HDFS·Spark·Collector/Worker EC2 접속·기동·점검 |
| [HDFS 3-DataNode 운영 검증](2026-09-09-hdfs-three-datanode-production-validation.md) | S15P21E102-175 merge 후 J15E102A 논리 3-DataNode 적용 및 무결성 검증 |
| [GitJob System Monitoring MVP](2026-09-10-gitjob-system-monitoring.md) | S15P21E102-205 Prometheus/Grafana 운영 지표 overlay·dashboard·검증 절차 |
| [2대 EC2 HA 설계](2026-08-27-ec2-high-availability-design.md) | ALB, 무상태 app node, 공유 상태 저장소, failover |
| [노트북 로컬 LLM GPU 런북](local-llm-runbook.md) | WSL2·Docker Desktop·NVIDIA GPU 기반 Ollama 실행·연동 준비 |
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
| `observability` | Kafka UI, Redis Insight, monitoring overlay의 Prometheus/Grafana/node-exporter/Kafka exporter | 내부 운영 확인 및 시계열 지표 |

환경별 override는 목적이 다르다.

| 파일 | 특징 |
|---|---|
| `Infra/compose/compose.wsl.yaml` | 저장소에서 image build, 모든 host binding loopback |
| `Infra/compose/compose.ec2.yaml` | 서비스/core EC2, 저장소 image build, Nginx HTTP 80과 private core listener |
| `Infra/compose/compose.ec2-data.yaml` | Hadoop/Spark data EC2, 저장소 image build, remote core endpoint |
| `Infra/compose/compose.ec2-data-cluster.yaml` | 기존 data volume을 유지한 Tailscale HDFS/Spark 전환 overlay |
| `Infra/compose/compose.ec2-cluster-worker.yaml` | service EC2의 독립 DataNode-4·Spark Worker-2 project |
| `Infra/compose/compose.ec2-ha.yaml` | EC2-A/B에서 `app`만 실행, 외부 HA state 사용 |

현재 2대 구성에서는 `J15E102`에 `core + app`과 Jenkins를, `J15E102A`에
`data`와 Hadoop single-node를 배치한다. 각 EC2의 local named volume이 공유되지
않으므로 데이터 서버는 서비스 서버의 private PostgreSQL·Redis·Kafka endpoint를
사용한다. 향후 HA로 전환할 때는 양쪽에서 PostgreSQL·Redis·Kafka를 동시에 실행하지
않고 RDS Multi-AZ, ElastiCache failover, MSK/동등한 외부 HA endpoint를 사용한다.

Prometheus/Grafana 운영 모니터링 MVP의 overlay와 안전한 targeted 기동·검증 절차는
[GitJob System Monitoring MVP](2026-09-10-gitjob-system-monitoring.md)에 기록한다.

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
Jenkins Poll SCM (develop)
  → Jenkins Validate
  → Backend test
  → Frontend test
  → split EC2 SSH deploy (각 EC2 git pull/build/up)
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
- Jenkins Poll SCM job·EC2 credential 기반 실제 split 배포
- Jenkins controller 실제 기동·agent online·Pipeline 실행
- AWS ALB·TLS·Route53·RDS/ElastiCache/MSK
- 실제 장애 주입, failover, rolling rollback

## 9. 원문 출처

- [개발 환경](https://app.notion.com/p/77f0dff912cf8305a10b017245b40a78)
- [환경 변수](https://app.notion.com/p/0b60dff912cf836084ee01fb375e5cbd)
- [깃랩/지라 컨벤션 가이드](https://app.notion.com/p/e2a0dff912cf824a85340178601b1997)
- [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d)
- [WBS](https://app.notion.com/p/b0b0dff912cf827781ee8119fc1a7cbd)
