# 2대 EC2 고가용성 설계 및 전환 계획

- 작성일: 2026-08-27
- 상태: 애플리케이션 이중화 골격 구현 / AWS 리소스 발급 전
- 대상: EC2를 2대 받을 가능성에 대비한 GitJob 운영 구성

## 1. 결론

2대의 EC2에 같은 Backend·Frontend·Nginx를 각각 실행하고, 앞단에 AWS
Application Load Balancer(ALB)를 둔다. 두 EC2는 active-active 애플리케이션
노드가 되고, 한 노드가 내려가면 ALB가 healthcheck에 실패한 노드를 트래픽에서
제외한다.

단, EC2 두 대의 로컬 Docker volume을 서로 복제하는 방식은 고가용성이 아니다.
PostgreSQL·Redis·Kafka·HDFS 같은 상태 저장 계층은 별도 HA 서비스 또는 별도의
복제·failover 구성이 필요하다.

현재 구현한 `compose.ec2-ha.yaml`은 **무상태 app 노드 이중화**를 위한 파일이다.
ALB와 HA 상태 저장소가 준비되기 전까지는 실제 HA가 완료된 것으로 표시하지 않는다.

## 2. 목표 구조

```text
                         Route53 / public DNS
                                  │
                   ALB (2개 AZ, 80→443 redirect, ACM TLS)
                         ┌────────┴────────┐
                 target healthy       target healthy
                         │                    │
             EC2-A private IP        EC2-B private IP
              Nginx:80                 Nginx:80
                 │                         │
          Frontend + Backend        Frontend + Backend
                 └──────────┬──────────────┘
                            │ private VPC endpoints
              ┌─────────────┼──────────────┐
              │             │              │
       RDS PostgreSQL   ElastiCache     MSK/3-broker Kafka
          Multi-AZ      failover        quorum 구성
              │
       S3/EFS 등 공유 파일·백업 저장소
```

가능하면 EC2-A와 EC2-B를 서로 다른 Availability Zone과 private subnet에 둔다.
EC2를 같은 AZ에 두면 인스턴스 장애에는 대응하지만 AZ 장애까지 대응하는 HA는
아니다.

## 3. 저장소에 구현한 범위

| 항목 | 구현 내용 | 상태 |
|---|---|---|
| 앱 노드 Compose | `compose.ec2-ha.yaml`에서 `app` 프로파일만 실행 | 구현 |
| 노드별 Nginx | 각 노드의 Backend·Frontend만 연결 | 구현 |
| readiness | `/health`가 Backend `/actuator/health`를 프록시 | 구현 |
| Nginx liveness | `/nginx-health`는 Nginx 자체만 확인 | 구현 |
| 로컬 의존성 분리 | WSL/단일 EC2 override에만 local `depends_on` 적용 | 구현 |
| 노드 설정 | `.env.example`에 node/ALB/rolling 배포 변수 추가 | 구현 |
| AWS ALB | target group, listener, DNS, SG | EC2 발급 후 |
| 상태 저장소 HA | RDS·ElastiCache·MSK 또는 동등한 구성 | 선택·구축 전 |
| 실제 failover | Backend/EC2 장애 후 ALB 전환 테스트 | 미검증 |

Docker Compose의 네트워크와 named volume은 호스트별 리소스다. 따라서 두 서버가
같은 Compose project name을 사용해도 컨테이너 네트워크나 volume이 공유되지 않는다.
두 노드 간 연결은 ALB와 VPC endpoint/DNS를 사용한다.

## 4. EC2에서 실행하는 방법

### 공통 환경 원칙

두 노드의 `.env`는 다음 값을 동일하게 유지한다.

- `BACKEND_IMAGE`, `FRONTEND_IMAGE`: 동일한 commit SHA 이미지
- `DB_HOST`, `DB_PORT`, `POSTGRES_DB`, `POSTGRES_USER`
- `REDIS_HOST`, `REDIS_PASSWORD`
- `KAFKA_BOOTSTRAP_SERVERS`와 Kafka topic명
- `JWT_SECRET`, OAuth client 설정, webhook secret
- `PUBLIC_BASE_URL`, `CORS_ALLOWED_ORIGINS`, `COOKIE_SECURE`

노드별로 달라지는 값은 `EC2_NODE_NAME`, 관리용 host, Compose project name 정도다.
실제 secret은 `.env`에 커밋하지 않고 SSM/Secrets Manager 또는 Jenkins Credentials에서
주입한다.

ALB와 공유 endpoint 값을 넣은 뒤에는 `ha-preflight.sh`로 local core를 잘못
참조하지 않는지 먼저 확인한다.

```bash
ENV_FILE=.env.ec2-node-a \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-ha.yaml \
PROFILES=app \
./Infra/scripts/ha-preflight.sh
```

### EC2-A

```bash
cp .env.example .env.ec2-node-a
# .env.ec2-node-a에 DEPLOYMENT_MODE=ha,
# EC2_NODE_NAME=node-a, DB/Redis/Kafka의 공유 endpoint를 입력

ENV_FILE=.env.ec2-node-a \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-ha.yaml \
PROFILES=app \
./Infra/scripts/up.sh
```

### EC2-B

```bash
cp .env.example .env.ec2-node-b
# .env.ec2-node-b에 DEPLOYMENT_MODE=ha,
# EC2_NODE_NAME=node-b와 같은 공유 endpoint를 입력

ENV_FILE=.env.ec2-node-b \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-ha.yaml \
PROFILES=app \
./Infra/scripts/up.sh
```

HA app 노드에서는 `PROFILES=app`만 사용한다. `core`를 두 노드에서 함께 켜면
각 EC2의 local PostgreSQL·Redis·Kafka가 별도로 생성되어 데이터가 갈라진다.
`data` 프로파일도 HDFS/Spark endpoint와 저장 정책을 확정한 뒤 별도 노드에 배치한다.

배포 전에는 다음 명령으로 app-only 구성을 확인한다.

```bash
ENV_FILE=.env.ec2-node-a \
COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-ha.yaml \
PROFILES=app \
./Infra/scripts/healthcheck.sh

docker compose --project-directory . \
  --env-file .env.ec2-node-a \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2-ha.yaml \
  --profile app config --quiet
```

## 5. ALB 구성 순서

1. 서로 다른 AZ의 subnet을 사용해 internet-facing ALB를 생성한다.
2. EC2-A와 EC2-B를 private IP 또는 instance target으로 target group에 등록한다.
3. Target group protocol은 HTTP, port는 `80`, health path는 `/health`로 둔다.
4. ALB listener `80`은 `443`으로 redirect하고, `443`은 ACM 인증서를 사용한다.
5. ALB default action은 위 target group으로 forward한다.
6. Route53에서 서비스 도메인을 ALB alias로 연결한다.

초기 운영은 ALB에서 TLS를 종료하고 EC2는 Nginx HTTP 80을 받는 형태로 단순화한다.
Nginx는 ALB가 보낸 `X-Forwarded-Proto`를 Backend에 전달하도록 구성되어 있어
HTTPS OAuth redirect와 secure cookie 판단이 내부 HTTP 때문에 바뀌지 않는다.

Security Group은 다음 경계로 설정한다.

| 대상 | inbound 허용 |
|---|---|
| ALB | 인터넷에서 TCP 80/443 |
| EC2-A/B | ALB Security Group에서 TCP 80 |
| EC2-A/B SSH | 관리자 IP 또는 SSM/Tailscale 경로만 |
| DB/Redis/Kafka/관리 UI | public inbound 금지, 필요한 private SG만 허용 |

`compose.ec2-ha.yaml`은 컨테이너의 80 포트를 호스트에 bind하지만, EC2 Security
Group이 ALB SG만 허용하도록 해야 한다. EC2 public IP를 사용자 트래픽의 고정
진입점으로 사용하지 않는다.

### health 의미

- `/health`: ALB target-group용 readiness. Backend actuator 결과를 그대로 반환한다.
- `/nginx-health`: Nginx 프로세스만 확인하는 운영자용 liveness.
- Backend actuator health에는 DB·Redis·Kafka 연결 상태를 포함하고, 인증 없이
  health path를 조회할 수 있도록 보안 설정을 확인한다.
- 실제 actuator 경로가 다르면 Nginx와 ALB health path를 함께 바꾼다.

## 6. 상태 저장 계층 판단

| 계층 | 권장 HA 구성 | 현재 Compose의 의미 |
|---|---|---|
| PostgreSQL | RDS Multi-AZ writer endpoint | WSL/단일 EC2 개발용 local DB |
| Redis | ElastiCache replication group + automatic failover | local cache/session 확인용 |
| Kafka | MSK 또는 3개 이상 broker/controller quorum | WSL 단일 KRaft broker |
| HDFS/Parquet | S3/EFS 또는 별도 HA HDFS | local NameNode/DataNode 실험용 |
| Spark | managed/dedicated cluster 또는 별도 HA 구성 | local master/worker 실험용 |
| Jenkins | controller 1대 + agent 분리 | 사용자 요청 경로와 분리되는 CI 서비스 |
| 파일 업로드/산출물 | S3 또는 EFS | 컨테이너 local filesystem 금지 |

두 EC2만으로 DB primary/standby, Redis Sentinel, Kafka quorum, HDFS NameNode HA를
모두 구성하려고 하면 quorum·witness·백업 노드가 부족하다. 따라서 다음 두 경우를
구분한다.

- **권장**: EC2는 app 노드로 사용하고 상태 저장소는 managed HA 서비스로 둔다.
- **단일 호스트 임시안**: EC2-A에 local core를 두고 EC2-B에 app을 추가한다. 이때
  앱 계층만 HA이며 EC2-A 장애 시 데이터 계층은 중단된다고 명시한다.

## 7. 장애 조치 테스트

실제 소스와 AWS 리소스가 준비된 뒤 아래 순서로 확인한다.

1. 두 target이 ALB에서 healthy인지 확인한다.
2. ALB 도메인으로 `/`, `/api`, WebSocket 연결을 반복 호출한다.
3. EC2-A에서 Backend를 중지한다.
4. `/health` 실패 후 EC2-A target이 unhealthy가 되고, 요청이 EC2-B에서 계속
   성공하는지 확인한다.
5. EC2-A를 복구하고 healthy로 돌아온 뒤 EC2-B에서도 같은 테스트를 반복한다.
6. 한 인스턴스 전체를 중지해도 서비스가 유지되는지 확인한다.
7. A에서 로그인한 뒤 B로 라우팅되어도 JWT/Redis session이 유지되는지 확인한다.
8. Worker를 두 노드에 배치할 경우 같은 consumer group의 offset과 중복 처리
   idempotency를 확인한다.

장애 테스트 통과 전에는 “2대 구성”이라고만 표현하고 “완전한 HA”라고 표시하지
않는다. ALB healthcheck interval과 deregistration delay도 실제 장애 감지 시간으로
기록한다.

## 8. 롤링 배포

두 노드를 동시에 내리지 않고 다음 순서를 지킨다.

1. commit SHA 이미지 빌드·push 및 Compose config 검증
2. EC2-A를 배포하고 ALB health가 healthy가 될 때까지 대기
3. 핵심 API·WebSocket smoke test
4. EC2-B를 같은 SHA로 배포하고 healthy 대기
5. 두 target과 오류율을 확인한 뒤 배포 완료
6. 실패하면 새 노드부터 이전 SHA로 rollback

DB migration은 앱 두 대가 동시에 실행하지 않게 별도 단계로 처리한다. 운영
`JPA_DDL_AUTO`는 `update`가 아니라 `validate`와 Flyway/Liquibase 같은 명시적인
migration 전략을 사용한다.

## 9. 아직 구성하지 않은 것

- AWS ALB, target group, listener, Route53 alias, ACM certificate
- 두 EC2의 AZ/private subnet/Security Group
- RDS·ElastiCache·MSK의 선택과 실제 endpoint
- SSM/Secrets Manager secret 주입
- 실제 Backend readiness와 graceful shutdown
- rolling deploy Jenkins 단계와 ALB 기반 smoke/rollback
- HDFS/Spark를 managed 서비스 또는 별도 데이터 노드로 둘지에 대한 결정
- 실제 장애 주입 및 복구 결과

따라서 현재 문서에서 확인 가능한 준비 상태는 “두 app 노드를 배포할 Compose
골격과 Nginx readiness까지 준비됨”이며, AWS 리소스 생성 이후 위 목록을 검증해
완료 처리한다.

## 10. 참고 문서

- [Infra 실행·구성 안내](../../Infra/README.md)
- [인프라 준비도 점검 보고서](2026-08-27-infra-readiness.md)
- [인프라 배포 계획](2026-08-27-infra-deployment-plan.md)
- [AWS EC2 resiliency guidance](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-recover.html)
- [Docker Compose documentation](https://docs.docker.com/compose/)
- [NGINX upstream module](https://nginx.org/en/docs/http/ngx_http_upstream_module.html)
