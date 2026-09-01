# J15E102 서비스 EC2 운영 문서

- 상태: 2-EC2 분리 구성용 실행 문서
- 대상: J15E102 / j15e102.p.ssafy.io
- 역할: 서비스·core·CI 서버
- 기준일: 2026-08-31
- 기준 브랜치: develop

이 서버는 사용자 트래픽을 받는 서비스 노드다. Nginx, Frontend, Backend,
PostgreSQL, Redis, Kafka를 실행하고 Jenkins는 private network에서만 운영한다.
J15E102A는 별도의 data 서버이며 이 문서의 Compose 명령으로 Hadoop/Spark를
실행하지 않는다.

현재 구성은 고가용 구성이 아니다. PostgreSQL, Redis, Kafka는 이 서버의 local
volume을 사용하고 Kafka는 single broker다. 장애 조치는 백업·수동 복구를
기준으로 하며, ALB/RDS/ElastiCache/MSK를 도입할 때에만 HA 구성으로 전환한다.

## 1. 서버 구성과 네트워크 경계

| 대상 | Compose profile | 주소/포트 | 용도 |
|---|---|---|---|
| Nginx | app | public 80/443 | HTTP→HTTPS redirect, Frontend, /api, /ws 진입점 |
| Backend | app | Compose 내부 backend:8080 | API 및 분석 Job API |
| PostgreSQL | core | 서비스 private IP:5432 | Backend·Worker DB |
| Redis | core | 서비스 private IP:6379 | Backend·Worker cache/session |
| Kafka | core | 서비스 private IP:9094 | data 서버용 external listener |
| Jenkins | ci | public 공개 금지 | CI/CD controller |
| Kafka UI | observability | Tailscale 100.71.215.74:8082 | Kafka 운영 확인 |
| Redis Insight | observability | Tailscale 100.71.215.74:8001 | Redis 운영 확인 |

서비스 EC2의 core 포트는 EC2_CORE_BIND_ADDRESS에 지정한 private IP에만
bind한다. J15E102A의 private IP에서만 5432, 6379, 9094로 접근하도록 제공된
네트워크 경계를 확인한다. 서비스 서버의 UFW/Security Group은 public 80/443을
허용한다. HTTP는 ACME challenge와 health endpoint를 제외하고 HTTPS로 redirect하며,
데이터 서버에는 80/443을 열지 않는다.

## 2. 먼저 확정할 값

| 값 | 예시 |
|---|---|
| SERVICE_PUBLIC_HOST | j15e102.p.ssafy.io |
| SERVICE_PRIVATE_IP | <J15E102-private-ip> |
| DATA_PRIVATE_IP | <J15E102A-private-ip> |
| DEPLOY_PATH | /home/ubuntu/workspace/S15P21E102 |
| DEPLOY_REF | develop |
| Jenkins trigger | Poll SCM (5분 주기) |
| 관리자 CIDR | <admin-cidr> |

추가 EC2 안내에는 PEM 파일이 기본 EC2와 같다고 되어 있다. 실제 발급 파일명을
확인하고, 별도 키가 없다면 두 서버 모두 J15E102T.pem을 사용한다. PEM은
저장소·Jenkins workspace·서버의 Git 디렉터리에 복사하지 않는다.

## 3. SSH 접속

로컬에서 PEM 권한을 제한한다.

~~~bash
chmod 400 J15E102T.pem
ssh -i J15E102T.pem ubuntu@j15e102.p.ssafy.io
~~~

## 4. 최초 서버 준비

Docker Engine, Docker Compose plugin, Git이 설치되어 있어야 한다. 설치 후 다음
조건을 확인한다.

~~~bash
sudo apt-get update
sudo apt-get install --yes ca-certificates curl git
sudo systemctl enable --now docker
docker --version
docker compose version
git --version
~~~

docker 명령에 매번 sudo가 필요하면 운영 방식에 맞춰 deploy user를 Docker
group에 추가하고 새 SSH 세션에서 다시 확인한다.

~~~bash
sudo usermod -aG docker ubuntu
~~~

배포 디렉터리를 만들고 저장소를 받을 때는 `develop` 브랜치를 사용한다.

~~~bash
sudo mkdir -p /home/ubuntu/workspace/S15P21E102
sudo chown ubuntu:ubuntu /home/ubuntu/workspace/S15P21E102
git clone --branch develop https://lab.ssafy.com/s15-bigdata-dist-sub1/S15P21E102.git /home/ubuntu/workspace/S15P21E102
cd /home/ubuntu/workspace/S15P21E102
~~~

이미 디렉터리가 있으면 삭제하지 말고 다음처럼 fast-forward만 사용한다.

~~~bash
cd /home/ubuntu/workspace/S15P21E102
git fetch origin
git switch develop
git pull --ff-only origin develop
~~~

## 5. .env.service 작성

저장소의 샘플을 복사하되 실제 secret은 직접 입력한다.

~~~bash
cd /home/ubuntu/workspace/S15P21E102
cp .env.example .env.service
chmod 600 .env.service
~~~

.env.service에서 최소한 다음 값을 운영값으로 바꾼다.

~~~dotenv
COMPOSE_PROJECT_NAME=gitjob-service
COMPOSE_PROFILES=core,app,ci,observability
DEPLOYMENT_MODE=split
JENKINS_EC2_BIND=100.71.215.74
JENKINS_EC2_HTTP_PORT=8081
JENKINS_URL=http://100.71.215.74:8081

BACKEND_IMAGE=gitjob/backend:local
FRONTEND_IMAGE=gitjob/frontend:local

NGINX_EC2_BIND=0.0.0.0
NGINX_EC2_HTTP_PORT=80
NGINX_EC2_HTTPS_PORT=443
LETSENCRYPT_DIR=/etc/letsencrypt
CERTBOT_WEBROOT_HOST_PATH=.local/certbot/www
SERVICE_ADMIN_BIND_ADDRESS=100.71.215.74
KAFKA_UI_EC2_PORT=8082
REDIS_INSIGHT_EC2_PORT=8001
EC2_CORE_BIND_ADDRESS=<J15E102-private-ip>
EC2_POSTGRES_PORT=5432
EC2_REDIS_PORT=6379
EC2_KAFKA_EXTERNAL_PORT=9094
EC2_KAFKA_ADVERTISED_HOST=<J15E102-private-ip>

DB_HOST=postgres
DB_PORT=5432
REDIS_HOST=redis
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
JPA_DDL_AUTO=validate

POSTGRES_PASSWORD=<long-random-password>
REDIS_PASSWORD=<long-random-password>
JWT_SECRET=<long-random-secret>
GITHUB_CLIENT_ID=<github-client-id>
GITHUB_CLIENT_SECRET=<github-client-secret>
GITHUB_API_TOKEN=<github-token-if-needed>
GITHUB_REDIRECT_URI=https://<service-domain>/api/v1/auth/github/callback
COOKIE_SECURE=true
CORS_ALLOWED_ORIGINS=https://<service-domain>
~~~

POSTGRES_USER, POSTGRES_DB, Kafka cluster/topic 값은 data 서버와 애플리케이션
계약에 맞춰 동일하게 유지한다. JPA_DDL_AUTO=update는 초기 개발용이며 운영
schema migration이 정해지면 validate 또는 팀이 합의한 migration 설정을 사용한다.

## 6. UFW와 Security Group

서비스 서버에는 public 80/443과 SSH만 허용한다. 데이터 서버에는 80/443을
열지 않는다. AWS Security Group은 사용자가 콘솔에서 변경할 수 없으므로 현재
확인 가능한 Ubuntu UFW 정책만 관리한다.

~~~text
서비스 서버 UFW: 22/tcp, 80/tcp, 443/tcp 허용
데이터 서버 UFW: public 80/443 미허용
~~~

Security Group에서도 같은 경계를 적용한다.

- 80/tcp: ACME challenge, health endpoint, HTTPS redirect
- 443/tcp: public HTTPS 서비스
- 22/tcp: 관리자 IP, SSM 또는 Tailscale 경로만
- 5432, 6379, 9094: J15E102A private IP만
- Jenkins·HDFS·Spark 관리 포트: public inbound 금지

## 7. 서비스 기동

Registry를 사용하지 않는다. `develop`을 pull한 뒤 EC2에서 Backend와 Frontend
이미지를 직접 build한다. core가 먼저 healthy가 된 뒤 app을 기동한다.

~~~bash
cd /home/ubuntu/workspace/S15P21E102
git pull --ff-only origin develop
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2.yaml \
  --profile core --profile app config --quiet
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2.yaml \
  --profile core --profile app build backend frontend
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2.yaml \
  --profile core up -d --no-build
ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml PROFILES=core \
  ./Infra/scripts/healthcheck.sh
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2.yaml \
  --profile app up -d --no-build backend frontend nginx
ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml PROFILES=app \
  ./Infra/scripts/healthcheck.sh
~~~

확인한다.

~~~bash
ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml PROFILES=core,app ./Infra/scripts/healthcheck.sh
curl --fail http://127.0.0.1/health
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
~~~

/health는 Backend의 /actuator/health를 확인한다. Nginx만 확인하려면
/nginx-health를 사용한다. Backend가 /actuator/health를 제공하려면
spring-boot-starter-actuator와 application 설정이 함께 배포되어야 한다.

## 8. Jenkins 운영

Jenkins는 이 서버에만 배치하고 public port로 열지 않는다. JENKINS_EC2_BIND를
이 서버의 Tailscale IPv4 100.71.215.74로 지정하면 다음 주소로 접속한다.

http://100.71.215.74:8081

Kafka UI와 Redis Insight는 observability profile을 켰을 때만 실행되며 각각
http://100.71.215.74:8082, http://100.71.215.74:8001로 접속한다. 이 주소들은
Tailscale에 연결된 기기에서만 사용한다.

- Tailscale/private IP에 Jenkins 포트를 bind하고 JENKINS_URL을 그 주소로 설정
- private reverse proxy를 두고 Jenkins URL을 내부 DNS로 제공
- 초기 bootstrap 동안 관리자 SSH tunnel을 사용

JENKINS_EC2_BIND와 JENKINS_URL을 확정한 뒤 JENKINS_ADMIN_PASSWORD를 secret으로 넣고
Jenkins 이미지를 이 서버에서 직접 build한다. Jenkins는 public port로 열지 않는다.

~~~bash
cd /home/ubuntu/workspace/S15P21E102
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2.yaml \
  --profile ci build jenkins jenkins-agent
ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml PROFILES=core,app,ci ./Infra/scripts/up.sh
~~~

Jenkins controller와 agent는 같은 서버에 두되 Docker socket을 받는 agent는
신뢰된 job만 실행한다. Jenkins를 인터넷에 직접 노출하지 않는다.

## 9. Jenkins split 배포 연결

Jenkins의 .env.ci에는 다음 값을 넣는다. 실제 secret env 파일은 이 파일에
넣지 않고 각 EC2에 별도로 둔다.

~~~dotenv
DEPLOYMENT_MODE=split
EC2_DEPLOY_REF=develop
EC2_SERVICE_HOST=j15e102.p.ssafy.io
EC2_SERVICE_USER=ubuntu
EC2_SERVICE_PATH=/home/ubuntu/workspace/S15P21E102
EC2_SERVICE_ENV_FILE=.env.service
EC2_DATA_HOST=j15e102a.p.ssafy.io
EC2_DATA_USER=ubuntu
EC2_DATA_PATH=/home/ubuntu/workspace/S15P21E102
EC2_DATA_ENV_FILE=.env.data
EC2_SSH_PORT=22
EC2_SSH_CREDENTIAL_ID=gitjob-ec2-ssh
GITLAB_SCM_CREDENTIAL_ID=gitjob-gitlab-scm
~~~

Jenkins Credentials에는 다음 ID를 사용한다.

- gitjob-ec2-ssh: EC2 SSH private key와 username
- gitjob-gitlab-scm: GitLab repository read token을 Username with password로 등록

`Jenkinsfile`은 `develop`에서만 `DEPLOY_ENABLED=true`일 때 배포한다. Jenkins Job은
Pipeline from SCM, branch `*/develop`, script path `Jenkinsfile`, Poll SCM
(`H/5 * * * *`)으로 설정한다. GitLab Integrations의 Jenkins webhook은 사용하지
않는다.

배포 단계는 Jenkins가 PEM을 임시 Credential로 주입해 두 EC2에 SSH하고, 각 서버에서
`git pull --ff-only origin develop`과 로컬 Docker build를 실행한다. secret env 파일,
GitLab token, PEM은 서버 간에 복사하지 않는다. 서비스 core health 확인 후 data 서버를
기동하고, data 확인이 끝난 뒤 서비스 app을 기동한다.

## 10. 운영 점검과 복구

~~~bash
docker compose --project-directory . --env-file .env.service -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2.yaml --profile core --profile app logs --tail=100 backend nginx
ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml ./Infra/scripts/backup-postgres.sh
# 복구는 기존 DB 객체를 덮어쓰므로 승인 후에만 실행
CONFIRM_RESTORE=yes ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml ./Infra/scripts/restore-postgres.sh /path/to/backup.dump
~~~

down.sh --volumes, docker volume rm, docker system prune --volumes는 운영
서버에서 실행하지 않는다. image tag를 이전 정상 commit SHA로 바꾸는 수동
rollback 절차와 PostgreSQL dump 복구 절차를 별도로 기록하고 테스트한다.
