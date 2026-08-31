# J15E102A 데이터 EC2 운영 문서

- 상태: 2-EC2 분리 구성용 실행 문서
- 대상: J15E102A / j15e102a.p.ssafy.io
- 역할: Hadoop/HDFS single-node·Spark·Collector·Worker 서버
- 기준일: 2026-08-31
- 기준 브랜치: develop

이 서버는 사용자 요청을 직접 받지 않는다. HDFS와 Spark를 local volume에 두고,
Collector와 Worker가 J15E102의 private PostgreSQL·Redis·Kafka endpoint를
사용한다. 서비스 서버의 Compose 파일이나 local core profile을 이 서버에서
실행하지 않는다.

이 구성의 HDFS는 single-node이며 replication factor는 1이다. 따라서 이 서버의
EBS/volume과 NameNode가 단일 장애점이다. 중요한 원본과 Parquet는 별도 EBS
snapshot 또는 S3 backup 정책을 추가해야 한다.

## 1. 서버 구성과 네트워크 경계

| 대상 | Compose profile | 주소/포트 | 용도 |
|---|---|---|---|
| Collector | data | Compose 내부 collector:8080 | GitHub event producer |
| Worker | data | Compose 내부 worker:8080 | Kafka consumer·분석 작업 |
| HDFS NameNode | data | hdfs-namenode:8020 | HDFS metadata/RPC |
| HDFS DataNode | data | local volume | HDFS block 저장 |
| Spark master | data | spark-master:7077 | Spark job scheduler |
| Spark worker | data | spark-worker:8081 | Spark executor |

Hadoop/Spark 관리 포트와 Collector/Worker health port는 public에 publish하지
않는다. 필요한 운영 점검은 SSH, Tailscale 또는 별도 private tunnel로 수행한다.
이 서버가 서비스 core에 접근하는 outbound 연결은 다음 세 포트다.

- J15E102-private-ip:5432 PostgreSQL
- J15E102-private-ip:6379 Redis
- J15E102-private-ip:9094 Kafka external listener

## 2. 먼저 확정할 값

| 값 | 예시 |
|---|---|
| SERVICE_PRIVATE_IP | <J15E102-private-ip> |
| DATA_PRIVATE_IP | <J15E102A-private-ip> |
| DEPLOY_PATH | /opt/gitjob |
| DEPLOY_REF | develop |
| 관리자 CIDR | <admin-cidr> |

추가 EC2 안내에는 PEM 파일이 기본 EC2와 같다고 되어 있다. 실제 발급 파일명을
확인하고, 별도 키가 없다면 J15E102T.pem으로 접속한다.

## 3. SSH 접속

~~~bash
chmod 400 J15E102T.pem
ssh -i J15E102T.pem ubuntu@j15e102a.p.ssafy.io
~~~

## 4. 최초 서버 준비

Docker Engine, Docker Compose plugin, Git이 설치되어 있어야 한다.

~~~bash
sudo apt-get update
sudo apt-get install --yes ca-certificates curl git netcat-openbsd
sudo systemctl enable --now docker
docker --version
docker compose version
git --version
~~~

Docker를 ubuntu 사용자가 실행해야 하면 group 권한을 추가한 뒤 새 SSH 세션에서
확인한다.

~~~bash
sudo usermod -aG docker ubuntu
~~~

배포 디렉터리를 만들고 `develop` 브랜치를 받는다.

~~~bash
sudo mkdir -p /opt/gitjob
sudo chown ubuntu:ubuntu /opt/gitjob
git clone --branch develop https://lab.ssafy.com/s15-bigdata-dist-sub1/S15P21E102.git /opt/gitjob
cd /opt/gitjob
~~~

이미 checkout되어 있으면 삭제하지 말고 fast-forward만 사용한다.

~~~bash
cd /opt/gitjob
git fetch origin
git switch develop
git pull --ff-only origin develop
~~~

## 5. .env.data 작성

~~~bash
cd /opt/gitjob
cp .env.example .env.data
chmod 600 .env.data
~~~

.env.data는 다음 핵심값을 사용한다.

~~~dotenv
COMPOSE_PROJECT_NAME=gitjob-data
COMPOSE_PROFILES=data
DEPLOYMENT_MODE=split

COLLECTOR_IMAGE=gitjob/collector:local
WORKER_IMAGE=gitjob/worker:local
SPARK_IMAGE=gitjob/spark:local
HDFS_IMAGE=apache/hadoop:3.4.1
SPARK_BASE_IMAGE=apache/spark:3.5.3-scala2.12-java11-python3-ubuntu

DB_HOST=<J15E102-private-ip>
DB_PORT=5432
POSTGRES_DB=gitjob
POSTGRES_USER=gitjob
POSTGRES_PASSWORD=<same-service-db-password>
REDIS_HOST=<J15E102-private-ip>
REDIS_PASSWORD=<same-service-redis-password>
KAFKA_BOOTSTRAP_SERVERS=<J15E102-private-ip>:9094

HADOOP_CLUSTER_NAME=gitjob
HDFS_URI=hdfs://hdfs-namenode:8020
HDFS_REPLICATION_FACTOR=1
PARQUET_ROOT=hdfs:///gitjob/parquet
SPARK_MASTER_URL=spark://spark-master:7077
SPARK_WORKER_CORES=2
SPARK_WORKER_MEMORY=2G
~~~

DB_HOST, REDIS_HOST, KAFKA_BOOTSTRAP_SERVERS에 postgres, redis, kafka:9092,
localhost를 넣지 않는다. data 서버에는 local core container가 없으므로 해당
값은 서비스 EC2의 private endpoint여야 한다.

Collector가 GitHub를 호출한다면 GITHUB_API_TOKEN과 rate-limit 설정도 운영
secret store에서 주입한다. Token은 .env.data 외의 파일·로그·Git에 넣지 않는다.

## 6. UFW와 Security Group (현재 미실행)

현재 작업에서는 UFW를 변경하지 않는다. 데이터 서버는 외부에 Hadoop/Spark 포트를
열지 않는 구성을 유지하되, SSAFY 제공 EC2의 네트워크 경계는 별도 확인 대상으로
남긴다. 아래 방화벽 명령은 실행하지 않는다.

~~~text
현재는 UFW 명령을 실행하지 않는다.
~~~

Security Group은 다음만 허용한다.

- 22/tcp: 관리자 IP, SSM 또는 Tailscale 경로
- public 80, 8020, 8080, 8081, 9870, 9864: 허용하지 않음
- 서비스 core port inbound: 필요하지 않음. data 서버는 서비스 서버로 outbound 연결만 수행

## 7. 서비스 서버 연결 확인

서비스 서버가 먼저 core를 기동한 뒤 data 서버에서 private endpoint 연결을
확인한다.

~~~bash
nc -vz <J15E102-private-ip> 5432
nc -vz <J15E102-private-ip> 6379
nc -vz <J15E102-private-ip> 9094
~~~

연결이 실패하면 data 컨테이너를 재시작하기 전에 서비스 EC2의 다음 항목을
확인한다.

1. EC2_CORE_BIND_ADDRESS가 서비스 EC2가 실제로 가진 private IP인지
2. Kafka KAFKA_ADVERTISED_LISTENERS의 external 주소가 같은 private IP인지
3. 제공된 EC2 네트워크 경계가 DATA_PRIVATE_IP의 연결을 허용하는지
4. data .env.data의 포트와 endpoint에 공백·따옴표·localhost가 없는지

## 8. 데이터 profile 기동

이 서버에서는 반드시 compose.ec2-data.yaml을 사용한다. compose.ec2.yaml은
local PostgreSQL·Redis·Kafka 의존성을 추가하므로 data-only profile과 함께 쓰지
않는다.

Registry를 사용하지 않는다. 서비스 core가 먼저 healthy가 된 것을 확인한 뒤,
`develop`을 pull하고 이 서버에서 Collector·Worker·Spark 이미지를 직접 build한다.
이 서버에서는 반드시 `compose.ec2-data.yaml`을 사용한다.

~~~bash
cd /opt/gitjob
git pull --ff-only origin develop
docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2-data.yaml \
  --profile data config --quiet
docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2-data.yaml \
  --profile data pull hdfs-namenode hdfs-datanode hdfs-bootstrap
docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2-data.yaml \
  --profile data build collector worker spark-master spark-worker
docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2-data.yaml \
  --profile data up -d --no-build \
  hdfs-namenode hdfs-datanode hdfs-bootstrap spark-master spark-worker collector worker
~~~

up.sh는 HDFS NameNode/DataNode, HDFS bootstrap, Spark master/worker, Collector,
Worker를 dependency 순서에 맞춰 기동한다. HDFS volume은 컨테이너 재생성으로
삭제되지 않지만, down --volumes나 volume prune은 운영 데이터 삭제로 이어진다.

## 9. 데이터 점검

~~~bash
ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml PROFILES=data ./Infra/scripts/healthcheck.sh
docker compose --project-directory . --env-file .env.data -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2-data.yaml --profile data ps
~~~

HDFS와 Spark를 개별적으로 확인한다.

~~~bash
docker compose --project-directory . --env-file .env.data -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2-data.yaml --profile data exec hdfs-namenode hdfs dfsadmin -report
ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data.yaml PROFILES=data ./Infra/scripts/spark-smoke.sh
~~~

현재 `develop`의 Collector/Worker 또는 `/health` 계약이 완성되지 않은 상태에서는
전체 healthcheck가 실패할 수 있다. 이 경우 HDFS/Spark를 먼저 확인하되, Registry를
기다리지 않고 소스 코드와 Dockerfile이 준비된 뒤 로컬 build를 다시 수행한다.

## 10. Jenkins 배포와 운영 주의사항

Jenkins는 J15E102에서만 실행한다. data 서버에는 Jenkins controller나 Docker
socket agent를 설치하지 않는다.

Jenkins split deploy에 필요한 .env.ci 예시는 다음과 같다.

~~~dotenv
DEPLOYMENT_MODE=split
EC2_DEPLOY_REF=develop
EC2_SERVICE_HOST=j15e102.p.ssafy.io
EC2_SERVICE_USER=ubuntu
EC2_SERVICE_PATH=/opt/gitjob
EC2_SERVICE_ENV_FILE=.env.service
EC2_DATA_HOST=j15e102a.p.ssafy.io
EC2_DATA_USER=ubuntu
EC2_DATA_PATH=/opt/gitjob
EC2_DATA_ENV_FILE=.env.data
EC2_SSH_PORT=22
EC2_SSH_CREDENTIAL_ID=gitjob-ec2-ssh
GITLAB_SCM_CREDENTIAL_ID=gitjob-gitlab-scm
~~~

Jenkins는 Registry push를 수행하지 않는다. Jenkins가 SSH로 data 서버에 접속해
`develop`을 pull하고 `compose.ec2-data.yaml`로 직접 build/up을 실행한다. `.env.data`,
PEM, GitHub token은 동기화하지 않는다.

운영 중 data 컨테이너를 갱신할 때는 HDFS volume을 건드리지 않고 image tag만
변경한다. Worker가 처리 중인 상태에서 강제 재시작하기 전에 Kafka consumer
재처리와 DLQ 정책을 확인한다.

## 11. 장애 시 확인 순서

1. 서비스 EC2의 5432/6379/9094 private 연결 상태 확인
2. docker compose logs --tail=100 worker collector로 인증·Kafka 오류 확인
3. NameNode/DataNode health와 hdfs dfsadmin -report 확인
4. Spark master/worker health와 worker 등록 상태 확인
5. Kafka consumer lag과 DLQ를 확인한 뒤 Worker만 재시작
6. HDFS volume 삭제·재format은 백업과 팀 승인 없이 실행하지 않음
