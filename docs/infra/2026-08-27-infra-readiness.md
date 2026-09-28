# 인프라 준비도 점검 보고서

- 작성일: 2026-08-27
- 최종 갱신일: 2026-08-28
- 프로젝트: S15P21E102 / GitJob
- 목적: 현재 인프라 준비 상태와 다음 작업을 기록하기 위한 문서
- 기준 문서: [`Infra/README.md`](../../Infra/README.md)
- MR !3 변경 상세: [`MR !3 수정 및 검증 기록`](2026-08-28-mr3-fix-validation.md)

## 1. 한 줄 요약

Docker Compose의 전체 서비스 구조와 WSL/EC2 전환 경계는 준비했다. PostgreSQL,
Redis, Kafka core는 WSL에서 실제 기동·healthcheck·송수신·재시작 영속성·백업/복원을
검증했다. HDFS/Spark data 골격은 별도 Compose project에서 최초 format, DataNode
등록, put/get, NameNode 재시작 영속성, Parquet smoke를 검증했다. Backend/Frontend/
Collector/Worker/Jenkins 전체 흐름은 소스와 운영 credential이 아직 저장소에
들어오지 않았으므로 Compose·Dockerfile·Nginx·JCasC·Jenkinsfile의 골격과 연결
계약까지 준비한 상태다. 현재 지급된 EC2 2대는 서비스/core와 Hadoop/Spark data로
분리할 수 있도록 `compose.ec2.yaml`, `compose.ec2-data.yaml`, split 배포 wrapper를
추가했으며, 향후 공유 상태 저장소가 준비되면 `compose.ec2-ha.yaml`과 ALB 기반
장애 조치로 전환한다.

## 2. 구현한 범위

### Compose

- `Infra/compose/compose.yaml`에 전체 프로파일을 정의했다.
  - `core`: PostgreSQL, Redis, Kafka KRaft
  - `app`: Spring Boot Backend, React Frontend, Nginx
  - `data`: Collector, Worker, HDFS NameNode/DataNode, Spark master/worker
  - `ci`: Jenkins controller와 제한된 build/deploy agent
  - `observability`: Kafka UI, Redis Insight
- `depends_on.condition: service_healthy`로 핵심 서비스 기동 순서를 표현했다.
- local WSL/단일 EC2의 cross-profile 의존성은 환경 override에 두고, HA app
  overlay는 외부 상태 저장소에 연결할 수 있도록 local `core` 의존성을 두지 않는다.
- PostgreSQL·Redis·Kafka·HDFS·Jenkins 데이터에 project-scoped named volume을 지정했다.
- HDFS는 `/data` volume 초기화와 `ENSURE_NAMENODE_DIR` 기반 최초 format 경계를 지정했다.
- Spark는 Python 포함 Apache image 변형과 foreground master/worker command를 사용하며, Worker UI host port를 publish하지 않는다.
- 로그는 기본 json-file rotation(`10m`, 3개)을 적용했다.

### 환경별 차이

- `compose.wsl.yaml`
  - Backend/Frontend/Worker/Jenkins image를 저장소에서 build하도록 build context를 추가
  - host 포트는 모두 `127.0.0.1`에만 바인딩
  - Kafka는 컨테이너 내부 `kafka:9092`, WSL host `localhost:9094`의 두 listener 사용
- `compose.ec2.yaml`
  - registry image를 사용하는 서비스/core EC2 구성을 제공
  - Nginx HTTP 80과 data EC2가 접근할 private core listener를 지정
  - DB/Redis/Kafka는 설정한 private IP에만 bind하고 Jenkins는 loopback/private IP에만 publish하며 관리 UI 포트는 publish하지 않음
- `compose.ec2-data.yaml`
  - Hadoop single-node와 Spark를 data EC2에 유지
  - Collector/Worker의 DB·Redis·Kafka 의존성을 서비스 EC2 endpoint로 분리
- `compose.ec2-ha.yaml`
  - EC2-A/B에서 `app` 프로파일만 실행하는 무상태 노드용 override
  - DB/Redis/Kafka는 양쪽 local volume이 아니라 RDS/ElastiCache/MSK 등 공유 endpoint 사용

### 실행·운영 파일

- `Infra/scripts/init-wsl.sh`: `.env.wsl` 생성 및 로컬 임시 secret 생성
- `up.sh`, `down.sh`, `healthcheck.sh`: profile 기반 기동/종료/상태 확인
- `bootstrap-jenkins-agent.sh`: controller가 발급한 inbound agent secret 조회·주입·online 확인
- `deploy.sh`: commit-tag image를 서비스 EC2와 data EC2에 각각 배포
- `spark-smoke.sh`: 고정 입력의 Parquet job과 Spark version/worker 수 기록
- `spark-benchmark.sh`: Worker 1/2/4·dataset 1x/2x/4x 반복 실행과 p50/p95/throughput TSV 기록
- `kafka-smoke.sh`: Kafka topic 생성과 producer/consumer 확인
- `backup-postgres.sh`, `restore-postgres.sh`: custom-format 백업과 명시적 복원
- `replay.sh`: newline-delimited payload의 Kafka 재생
- `ha-preflight.sh`: 2-EC2 app-only profile과 외부 상태 endpoint 사전 확인
- `Infra/nginx/`: SPA, `/api`, `/ws` reverse proxy와 `/health` readiness, `/nginx-health` liveness
- `Infra/jenkins/`: JCasC, plugin 목록, job 연결 안내
- 루트 `Jenkinsfile`: validate → test → image build → 조건부 push/deploy 골격

## 3. 실제로 확인한 결과

검증 환경은 Docker Engine 29.6.2, Docker Compose v5.3.1이며, 호스트의 PostgreSQL
`5432` 사용으로 현재 `.env.wsl`에서는 host 포트를 `15432`로 변경했다.

| 검증 | 결과 |
|---|---|
| WSL core Compose config | 통과 |
| PostgreSQL healthcheck | 통과 |
| Redis healthcheck | 통과 |
| Kafka KRaft healthcheck | 통과 |
| Kafka topic 생성/발행/소비 | 통과 |
| core 컨테이너 재시작 후 PostgreSQL/Redis 데이터 | 통과 |
| 재시작 후 Kafka smoke topic 유지 | 통과 |
| PostgreSQL custom dump 생성 | 통과 |
| PostgreSQL backup/restore smoke | 통과 |
| WSL override loopback 포트 경계 | 통과 |
| EC2 override 관리 포트 비공개 | 통과 |
| 전체 profile Compose YAML 병합 | 통과 |
| 2-EC2 HA app-only Compose 병합 | 통과 |
| Nginx `/health` readiness 라우팅 | 설정 작성, 실제 Backend 전으로 미검증 |
| AWS ALB target failover | ALB 미생성으로 미검증 |
| 상태 저장소 failover | RDS/ElastiCache/MSK 미선택으로 미검증 |
| 실제 Backend/Frontend/AI build | 소스 없음으로 미실행 |
| HDFS NameNode/DataNode smoke | 새 volume 최초 format, live DataNode, put/get, NameNode 재시작 후 metadata 보존 통과 |
| Spark Parquet smoke | Spark 3.5.3, Worker 1/2/4 모두 동일 입력 job과 Parquet 결과 생성 통과 |
| Jenkins agent image toolchain | Java 21, Node 22/npm, Docker CLI/Compose, Git, SSH 실행 확인 |
| 실제 Jenkins webhook/push/deploy | GitLab/registry/EC2 credential 전으로 미실행 |

## 4. `.env.example` 구성

`.env.example`에는 현재 Compose가 참조하는 항목을 영역별로 정리했다.

- image reference와 Compose project
- WSL/EC2 host port
- PostgreSQL·Redis credentials
- Spring datasource/Redis/Kafka 연결값
- GitHub OAuth/API/JWT/CORS/cookie 값
- Kafka topic·consumer group
- HDFS/Spark 자원과 URI
- Jenkins admin와 GitLab registry/EC2 deploy 값. inbound agent secret은 controller에서 발급
- 2-EC2 node 이름·private IP·ALB health path·rolling deploy target
- Compose project 이름(개발/CI volume 격리)

실제 secret은 `.env.wsl`, `.env.ec2`, Jenkins Credentials, AWS SSM/Secrets Manager에
두고 Git에는 넣지 않는다. `.env.wsl`과 `.local/`은 `.gitignore`로 제외했다.

## 5. 현재 구성되지 않은 것과 구성 방법

| 미완료 항목 | 현재 이유 | 구성 방법 |
|---|---|---|
| Backend image build | `BE/`가 `.gitkeep`만 보유 | Gradle wrapper/task와 actuator 경로 확인 후 Dockerfile build/test 수정 |
| Frontend image build | `FE/`가 `.gitkeep`만 보유 | package manager, build output, API/WS runtime env 확정 후 build |
| Collector/Worker 실행 | `AI/`가 `.gitkeep`만 보유 | requirements, module entrypoint, `/health`, CPU/RAM 확정 |
| Kafka 운영 계약 | topic envelope와 partition 미확정 | BE/AI가 topic명·schema·retry·DLQ·retention 합의 후 초기화 script 추가 |
| Jenkins 자동화 | GitLab/registry/EC2 정보 미확정 | Credentials 등록, webhook 연결, SHA tag push, deploy/rollback 구현 |
| TLS/도메인 | EC2와 도메인 미발급 | 인증서 mount, Nginx 443 server block, OAuth callback/cookie 변경 |
| ALB 기반 앱 이중화 | EC2/ALB 미발급 | 서로 다른 AZ에 두 target 등록, `/health` healthcheck, 80→443 listener 구성 |
| 공유 상태 저장소 | 두 EC2 local volume은 독립적 | RDS Multi-AZ·ElastiCache failover·MSK/3 broker 중 하나로 endpoint 통일 |
| HA rolling deploy | 두 노드 배포 절차 미연결 | node-a 배포·health 확인 후 node-b 배포, 실패 시 이전 SHA rollback |
| EC2 운영 자동기동 | 서버 OS/경로 미확정 | `/opt/gitjob`, deploy user, systemd, log rotation, backup timer 작성 |
| 운영 secret 관리 | SSM/Secrets Manager 선택 전 | EC2 운영값을 secret store에서 주입하고 로그 마스킹 |
| 모니터링 | 지표 API·권한 미확정 | consumer lag, DLQ, 분석시간, GitHub quota metric과 private 접근 추가 |

## 6. 향후 우선순위

1. BE/FE/AI 소스가 들어오면 Dockerfile의 가정을 실제 build/test 명령과 맞춘다.
2. `PROFILES=core,app`으로 Nginx → Backend → PostgreSQL/Redis 연결을 검증한다.
3. Kafka topic envelope와 상태 전이(`QUEUED → RUNNING → ...`)를 고정한다.
4. `PROFILES=core,app,data`로 Collector/Worker를 포함한 최소 수집·분석 흐름을 실행한다.
5. Jenkins Credentials와 GitLab webhook을 연결하고 SHA image tag pipeline을 실행한다.
6. EC2 2대의 private IP와 UFW/보안그룹을 확정하고 서비스/data split 구성을 기동한다.
7. Jenkins Credentials·Registry와 remote `.env.service`/`.env.data`를 연결해 split deploy를 검증한다.
8. HDFS/Parquet·PostgreSQL backup과 systemd/log rotation을 EC2 운영 정책에 맞춘다.
9. 향후 HA가 필요해지면 RDS·ElastiCache·MSK·ALB와 `compose.ec2-ha.yaml` 전환을 검증한다.

## 7. 검증 명령

```bash
# 핵심 실행
./Infra/scripts/init-wsl.sh
PROFILES=core ./Infra/scripts/up.sh
./Infra/scripts/healthcheck.sh
./Infra/scripts/kafka-smoke.sh
PROFILES=core,app,data ./Infra/scripts/up.sh
./Infra/scripts/spark-smoke.sh
./Infra/scripts/spark-benchmark.sh

# 전체 구조의 Compose 병합 검증
docker compose --env-file .env.wsl --project-directory . \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.wsl.yaml \
  --profile core --profile app --profile data --profile ci \
  --profile observability config
```

전체 profile 기동은 소스/image와 WSL 자원이 준비된 후 수행한다. 현재 문서에서는
core 실제 결과, 2-EC2 split/HA Compose config 결과, AWS 리소스가 아직 미생성인 사실을
구분해서 기록한다. 상세 절차는
[2대 EC2 고가용성 설계 문서](2026-08-27-ec2-high-availability-design.md)에 있다.
