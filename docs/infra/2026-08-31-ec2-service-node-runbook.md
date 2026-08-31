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
| Nginx | app | public 80 | Frontend, /api, /ws 진입점 |
| Backend | app | Compose 내부 backend:8080 | API 및 분석 Job API |
| PostgreSQL | core | 서비스 private IP:5432 | Backend·Worker DB |
| Redis | core | 서비스 private IP:6379 | Backend·Worker cache/session |
| Kafka | core | 서비스 private IP:9094 | data 서버용 external listener |
| Jenkins | ci | public 공개 금지 | CI/CD controller |

서비스 EC2의 core 포트는 EC2_CORE_BIND_ADDRESS에 지정한 private IP에만
bind한다. J15E102A의 private IP에서만 5432, 6379, 9094로 접근하도록 제공된
네트워크 경계를 확인한다. 현재 작업에서는 UFW를 변경하지 않는다. Nginx의 80은 초기에는 public HTTP로
사용하고, TLS/ALB 도입 후 inbound 범위를 ALB 또는 private 운영망으로 줄인다.

## 2. 먼저 확정할 값

| 값 | 예시 |
|---|---|
| SERVICE_PUBLIC_HOST | j15e102.p.ssafy.io |
| SERVICE_PRIVATE_IP | <J15E102-private-ip> |
| DATA_PRIVATE_IP | <J15E102A-private-ip> |
| DEPLOY_PATH | /opt/gitjob |
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
sudo mkdir -p /opt/gitjob
sudo chown ubuntu:ubuntu /opt/gitjob
git clone --branch develop https://lab.ssafy.com/s15-bigdata-dist-sub1/S15P21E102.git /opt/gitjob
cd /opt/gitjob
~~~

이미 디렉터리가 있으면 삭제하지 말고 다음처럼 fast-forward만 사용한다.

~~~bash
cd /opt/gitjob
git fetch origin
git switch develop
git pull --ff-only origin develop
~~~

## 5. .env.service 작성

저장소의 샘플을 복사하되 실제 secret은 직접 입력한다.

~~~bash
cd /opt/gitjob
cp .env.example .env.service
chmod 600 .env.service
~~~

.env.service에서 최소한 다음 값을 운영값으로 바꾼다.

~~~dotenv
COMPOSE_PROJECT_NAME=gitjob-service
COMPOSE_PROFILES=core,app
DEPLOYMENT_MODE=split
JENKINS_EC2_BIND=127.0.0.1
JENKINS_EC2_HTTP_PORT=8081
JENKINS_URL=http://127.0.0.1:8081

BACKEND_IMAGE=gitjob/backend:local
FRONTEND_IMAGE=gitjob/frontend:local

NGINX_EC2_BIND=0.0.0.0
NGINX_EC2_HTTP_PORT=80
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

## 6. UFW와 Security Group (현재 미실행)

현재 작업에서는 UFW를 변경하지 않는다. 이 서버는 SSAFY가 제공한 EC2이며,
AWS 콘솔·Security Group을 직접 변경할 권한도 없으므로 아래 방화벽 명령은 실행하지
않는다. 실제 운영 전 네트워크 경계가 확인되고 별도 승인이 있을 때만 작성된
정책을 검토한다.

~~~text
현재는 UFW 명령을 실행하지 않는다.
~~~

Security Group에서도 같은 경계를 적용한다.

- 80/tcp: 초기 public HTTP 또는 지정한 ALB 경로
- 22/tcp: 관리자 IP, SSM 또는 Tailscale 경로만
- 5432, 6379, 9094: J15E102A private IP만
- Jenkins·HDFS·Spark 관리 포트: public inbound 금지

## 7. 서비스 기동

Registry를 사용하지 않는다. `develop`을 pull한 뒤 EC2에서 Backend와 Frontend
이미지를 직접 build한다. core가 먼저 healthy가 된 뒤 app을 기동한다.

~~~bash
cd /opt/gitjob
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

Jenkins는 이 서버에만 배치하고 public port로 열지 않는다. compose.ec2.yaml은
Jenkins를 기본 loopback 8081에 publish하므로 서버 내부 bootstrap과 SSH tunnel에
사용할 수 있다. Tailscale/private network에서 직접 접근해야 하면
JENKINS_EC2_BIND를 해당 private IP로 바꾼다.

- Tailscale/private IP에 Jenkins 포트를 bind하고 JENKINS_URL을 그 주소로 설정
- private reverse proxy를 두고 Jenkins URL을 내부 DNS로 제공
- 초기 bootstrap 동안 관리자 SSH tunnel을 사용

JENKINS_EC2_BIND와 JENKINS_URL을 확정한 뒤 JENKINS_ADMIN_PASSWORD를 secret으로 넣고
Jenkins 이미지를 이 서버에서 직접 build한다. Jenkins는 public port로 열지 않는다.

~~~bash
cd /opt/gitjob
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
