# GitJob 빌드 및 배포 가이드

기준 브랜치: `develop`

기준일: 2026-09-28

운영 URL: `https://j15e102.p.ssafy.io`

## 1. 시스템 구성

| 구분 | 제품/런타임 | 버전 또는 이미지 | 주요 설정 |
|---|---|---|---|
| OS | Ubuntu Server | 24.04 LTS | 서비스 EC2와 데이터 EC2 공통 |
| 컨테이너 | Docker Engine / Compose | 29.7.2 / 5.5.0 | 모든 애플리케이션과 인프라를 컨테이너로 실행 |
| JVM | Eclipse Temurin JDK/JRE | Java 21 LTS | 빌드 JDK, 실행 JRE 분리 |
| Backend | Spring Boot / Gradle | 4.1.1 / 9.7.1 | Java toolchain 21, 실행 포트 8080 |
| WAS | Embedded Apache Tomcat | Spring Boot 4.1.1 BOM 관리 버전 | 별도 WAS 설치 없이 실행 JAR에 포함 |
| Frontend | React / Vite / TypeScript | 19.2.8 / 8.2.2 / 7.0.2 | Node 22.12 빌드, 정적 산출물 생성 |
| Web server | Nginx | 1.27.1-alpine | 80/443, TLS 종료, 정적 파일 및 `/api`, `/ws` 프록시 |
| Database | PostgreSQL | 16.4-alpine | 서비스 EC2, Flyway 마이그레이션 |
| Cache | Redis | 7.4.0-alpine | 서비스 EC2 |
| Message broker | Apache Kafka | 4.0.0 | KRaft, 서비스 EC2 |
| CDC | Debezium Connect | 3.4.3 | PostgreSQL 변경을 Kafka로 발행 |
| Data lake | Apache Hadoop HDFS | 3.4.1 | 데이터 EC2의 NameNode + 2 DataNode 컨테이너 |
| Distributed processing | Apache Spark | 3.5.3, Scala 2.12, Java 11, Python 3 | 데이터 EC2의 master/worker |
| Python services | CPython | 3.12 | collector, worker, analysis-worker |
| CI/CD | Jenkins | 2.568.2, JDK 21 | 5분 Poll SCM, Docker agent 사용 |
| Private network | Tailscale | 1.102.3 | 관리자 UI 및 서버 간 비공개 통신 |
| IDE(선택) | VS Code / IntelliJ IDEA | 1.138.0 / 2026.1.4 | 개발 PC 확인 버전이며 빌드 의존성은 아님 |

주요 소스 버전의 기준 파일은 `BE/build.gradle`, `BE/gradle/wrapper/gradle-wrapper.properties`, `FE/package.json`, 각 Dockerfile과 `Infra/compose/*.yaml`이다.

## 2. 저장소 받기

GitLab 저장소는 비공개이므로 먼저 개인 액세스 토큰 또는 Project Access Token을 발급한다. 소스 조회만 필요한 토큰의 최소 권한은 `read_repository`다.

```bash
mkdir -p /home/ubuntu/workspace
git clone --branch develop \
  https://lab.ssafy.com/s15-bigdata-dist-sub1/S15P21E102.git \
  /home/ubuntu/workspace/S15P21E102
cd /home/ubuntu/workspace/S15P21E102
```

이미 clone한 저장소를 갱신할 때는 다음 명령을 사용한다.

```bash
git fetch origin
git switch develop
git pull --ff-only origin develop
```

토큰을 원격 URL이나 셸 기록에 직접 넣지 않는다. Jenkins에서는 Username with password 형식의 Credential `gitjob-gitlab-scm`을 사용한다.

## 3. 환경 파일

전체 변수와 설명의 단일 기준은 저장소 루트의 `.env.example`이다. 운영에서는 템플릿을 복사한 뒤 서버 역할별 값만 보관한다.

| 파일 | 위치 | 용도 |
|---|---|---|
| `.env.service` | 서비스 EC2 저장소 루트 | core/app/ci/observability |
| `.env.data` | 데이터 EC2 저장소 루트 | collector/worker/HDFS/Spark |
| `.env.ci` | Jenkins workspace | 테스트 및 배포 대상 설정; `.env.ci.example`에서 생성 |

```bash
cp .env.example .env.service   # 서비스 EC2에서만
cp .env.example .env.data      # 데이터 EC2에서만
chmod 600 .env.service .env.data
```

실제 운영 파일을 Git 또는 다른 서버에서 복사해 공유하지 않는다. 서비스 서버 값과 데이터 서버 값을 각각 해당 서버에서 입력한다.

### 3.1 서비스 EC2 필수 그룹

| 그룹 | 주요 변수 | 설명 |
|---|---|---|
| Compose | `COMPOSE_PROJECT_NAME`, `COMPOSE_PROFILES`, `DEPLOYMENT_MODE` | `gitjob-service`, `core,app,ci,observability`, `split` |
| 이미지 | `BACKEND_IMAGE`, `FRONTEND_IMAGE`, `WORKER_IMAGE` | Jenkins가 서버에서 직접 빌드할 로컬 이미지명 |
| 공개 진입점 | `PUBLIC_BASE_URL`, `NGINX_HTTP_PORT`, `NGINX_HTTPS_PORT`, `LETSENCRYPT_*` | 현재 공개 URL은 `https://j15e102.p.ssafy.io` |
| DB | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL 접속 정보 |
| Redis | `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | 캐시 접속 정보 |
| Kafka/CDC | `KAFKA_CLUSTER_ID`, `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_EXTERNAL_*`, `CDC_DATABASE_PASSWORD` | 내부/데이터 서버용 브로커와 CDC |
| 인증 | `JWT_SECRET`, `AES_SYMMETRIC_KEY`, `AES_SALT` | 충분히 긴 난수. 기존 운영값을 임의 교체하면 기존 토큰/암호문을 사용할 수 없음 |
| GitHub | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_API_TOKEN`, `GITHUB_REDIRECT_URI` | OAuth 및 API 수집 |
| 브라우저 | `FRONTEND_CALLBACK_URL`, `CORS_ALLOWED_ORIGINS`, `COOKIE_SECURE` | 운영 URL과 정확히 일치, HTTPS에서는 `true` |
| 비공개 분석 | `INTERNAL_ANALYSIS_SERVICE_TOKEN`, broker URL 관련 변수 | BE와 worker가 같은 토큰을 사용 |
| 관리망 | `ADMIN_BIND_ADDRESS`, 모니터링 bind 변수 | 공인 주소가 아닌 Tailscale 주소에만 바인딩 |

현재 GitHub OAuth callback은 다음 값과 GitHub OAuth App 설정이 정확히 같아야 한다.

```text
https://j15e102.p.ssafy.io/api/v1/auth/github/callback
```

### 3.2 데이터 EC2 필수 그룹

| 그룹 | 주요 변수 | 설명 |
|---|---|---|
| Compose | `COMPOSE_PROJECT_NAME`, `COMPOSE_PROFILES`, `DEPLOYMENT_MODE` | `gitjob-data`, `data`, `split` |
| 서비스 EC2 연결 | `DB_HOST`, `REDIS_HOST`, `KAFKA_BOOTSTRAP_SERVERS` | 서비스 EC2 private/Tailscale 주소 사용 |
| 인증/수집 | `POSTGRES_*`, `REDIS_PASSWORD`, `GITHUB_API_TOKEN`, `INTERNAL_ANALYSIS_SERVICE_TOKEN` | 서비스 EC2와 필요한 값 일치 |
| HDFS | `HADOOP_CLUSTER_NAME`, `HDFS_URI`, `HDFS_REPLICATION_FACTOR`, `WEBHDFS_*`, `PARQUET_ROOT` | 단일 호스트 다중 컨테이너 분산 구성 |
| Spark | `SPARK_MASTER_URL`, `SPARK_WORKER_CORES`, `SPARK_WORKER_MEMORY`, executor 관련 변수 | EC2 자원에 맞춰 제한 |
| 관리망 | `DATA_ADMIN_BIND_ADDRESS` | Tailscale 주소에만 UI/관리 포트 노출 |

현재 자동 배포의 데이터 서버에서는 반드시 `Infra/compose/compose.ec2-data-cluster.yaml`을 사용한다. `compose.ec2-data.yaml`은 과거 단일 데이터 서버용이며, 현재 구성에 적용하면 서비스 EC2의 DataNode/Spark worker 연결이 끊길 수 있다. `compose.ec2.yaml`은 서비스 서버용이다.

Compose는 profile 필터링보다 먼저 전체 YAML의 변수를 치환하므로 데이터 서버에서도 `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `KAFKA_CLUSTER_ID`, `CDC_DATABASE_PASSWORD`, `AES_SYMMETRIC_KEY`, `AES_SALT`가 비어 있으면 `config` 단계에서 실패한다.

### 3.3 Jenkins CI/CD 변수와 Credential

`Jenkinsfile`은 `.env.ci.example`을 `.env.ci`로 복사한다. 다음 값은 실제 인프라에 맞아야 한다.

- `DEPLOYMENT_MODE=split`
- `EC2_DEPLOY_REF=develop`
- `EC2_SERVICE_HOST`, `EC2_SERVICE_USER`, `EC2_SERVICE_PATH`, `EC2_SERVICE_ENV_FILE`
- `EC2_DATA_HOST`, `EC2_DATA_USER`, `EC2_DATA_PATH`, `EC2_DATA_ENV_FILE`
- `EC2_SSH_CREDENTIAL_ID=gitjob-ec2-ssh`
- `GITLAB_SCM_CREDENTIAL_ID=gitjob-gitlab-scm`

Jenkins Credentials에는 다음 두 항목을 별도로 만든다.

1. `gitjob-gitlab-scm`: GitLab 사용자명 + 토큰
2. `gitjob-ec2-ssh`: Ubuntu 사용자 + 서비스/데이터 서버 접속에 사용하는 SSH 개인키

## 4. 로컬 빌드 및 검증

### Backend

```bash
cd BE
./gradlew --no-daemon clean test bootJar
```

### Frontend

```bash
cd FE
npm ci
npm run lint
npm test
npm run build
```

### Python 분석 모듈

기본 Jenkins 배포 대상은 BE/FE이며 GPU LLM 서버는 별도 운영한다. Python 코드를 직접 검증하려면 Python 3.12 환경에서 실행한다.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r AI/requirements.txt
bash AI/scripts/ci-regression.sh
```

JobKorea OCR collector는 기본 requirements 외에 PaddleOCR 3.x와 PaddlePaddle 3.2.0을 사용한다.

### Compose 구문 검증

```bash
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2.yaml \
  --profile core --profile app config --quiet
```

## 5. 운영 배포

### 5.1 권장: Jenkins

1. Pipeline from SCM 저장소를 GitLab 프로젝트로 지정한다.
2. Branch Specifier를 `*/develop`, Script Path를 `Jenkinsfile`로 지정한다.
3. Poll SCM은 `H/5 * * * *`로 5분마다 변경을 확인한다.
4. 자동 배포가 필요하면 빌드 파라미터 `DEPLOY_ENABLED=true`로 실행한다.
5. Jenkins는 현재 checkout이 `origin/develop`에 포함된 커밋인지 확인한 후에만 배포한다.

배포 순서는 다음과 같다.

1. 서비스 EC2의 core(PostgreSQL, Redis, Kafka/CDC) 준비
2. 데이터 EC2의 data(collector, worker, HDFS, Spark) 배포
3. 서비스 EC2의 app(BE, FE, Nginx) 배포
4. health check 및 공개 URL 검증

Docker Registry에 push/pull하지 않는다. Jenkins가 각 EC2에서 `develop`을 pull하고 해당 서버에서 이미지를 직접 빌드한다.

### 5.2 수동 복구용 명령

서비스 EC2:

```bash
cd /home/ubuntu/workspace/S15P21E102
git pull --ff-only origin develop
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2.yaml \
  --profile core --profile app up -d --build
```

서비스 core가 healthy인 것을 확인한 뒤 데이터 EC2에서 실행한다.

```bash
cd /home/ubuntu/workspace/S15P21E102
git pull --ff-only origin develop
docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2-data-cluster.yaml \
  --profile data up -d --build
```

상세 초기 설치·점검 절차는 다음 운영 지시서를 참고한다.

- `docs/infra/2026-08-31-ec2-service-node-runbook.md`
- `docs/infra/2026-08-31-ec2-data-node-runbook.md`

단, 데이터 runbook의 `compose.ec2-data.yaml` 명령은 단일 노드 시점의 기록이다. 현재 Jenkins 배포의 기준은 `Infra/scripts/deploy.sh`와 `compose.ec2-data-cluster.yaml`이다. 가능하면 수동 Compose 명령 대신 Jenkins 또는 `Infra/scripts/deploy.sh`를 사용한다.

## 6. 배포 특이사항과 금지 사항

- 서비스 EC2 core를 먼저 기동한 후 데이터 EC2를 기동한다.
- 현재 2-host HDFS/Spark 토폴로지에서 데이터 배포 override를 `compose.ec2-data.yaml`로 되돌리지 않는다.
- 데이터 EC2에서 `docker compose down --volumes`, `docker volume prune`, HDFS 볼륨 삭제 명령을 실행하지 않는다.
- PostgreSQL/Redis/Kafka/HDFS 볼륨은 운영 데이터이므로 재배포 시 보존한다.
- `.env` 파일, PEM, 토큰은 서버별로 별도 관리하며 저장소에 커밋하지 않는다.
- Nginx는 호스트 설치가 아니라 Docker 컨테이너다.
- 공개 포트는 서비스 EC2의 80/443만 사용한다. Jenkins, Kafka UI, RedisInsight, Prometheus, Grafana, HDFS, Spark UI는 Tailscale을 통해서만 접속한다.
- `gitjob.shop` Host는 차단되어 있으며 현재 공식 진입점은 `j15e102.p.ssafy.io`다.
- TLS 인증서는 Nginx가 `/etc/letsencrypt`를 read-only mount하여 사용한다. 갱신 후 Nginx reload/recreate가 필요하다.
- GPU LLM/Ollama 서버는 Jenkins 기본 배포에 포함되지 않는 독립 서버다.
- 단순 `compose up -d`만으로 Nginx 배포를 대체하지 않는다. 배포 스크립트는 설정 검증 후 Nginx를 강제 재생성하여 bind mount 변경을 반영한다.
- 컨테이너 health만으로 성공을 판단하지 않는다. `Infra/scripts/verify-deployment.sh`가 Flyway/분석 스키마, CDC, Kafka topic, Nginx upstream까지 통과해야 한다.
- 방화벽/UFW, 운영 배포, 데이터 삭제 가능 명령은 현재 상태와 대상을 확인한 뒤 수행한다.

## 7. 운영 확인 주소

Tailscale 연결 상태에서만 관리자 UI에 접근한다.

| 기능 | 주소 |
|---|---|
| Jenkins | `http://100.71.215.74:8081` |
| Kafka UI | `http://100.71.215.74:8082` |
| RedisInsight | `http://100.71.215.74:8001` |
| Prometheus | `http://100.71.215.74:9090` |
| Grafana | `http://100.71.215.74:3000` |
| HDFS NameNode | `http://100.70.66.38:9870` |
| Spark Master | `http://100.70.66.38:8083` |
| Spark Worker | `http://100.70.66.38:8084` |

## 8. DB 접속 정보와 스키마 정의 파일

실제 계정과 비밀번호는 문서가 아니라 서버 환경 파일에 있다.

| 목적 | 파일/경로 |
|---|---|
| 환경 변수 전체 템플릿 | `.env.example` |
| 서비스 DB 실제 접속값 | 서비스 EC2의 `.env.service` |
| 데이터 작업자 DB 접속값 | 데이터 EC2의 `.env.data` |
| Spring datasource/Flyway/JPA 설정 | `BE/src/main/resources/application.yaml` |
| PostgreSQL 컨테이너와 볼륨 | `Infra/compose/compose.yaml`, `Infra/compose/compose.ec2.yaml` |
| 데이터 서버 연결 override | `Infra/compose/compose.ec2-data-cluster.yaml` (현재 2-host 운영) |
| 주 애플리케이션 스키마 | `BE/src/main/resources/db/migration/V*.sql` |
| 계산/분석 스키마 | `BE/src/main/resources/db/c-compute/*.sql` |
| 분석 보조 마이그레이션 | `BE/src/main/resources/db/migrations/*.sql` |
| Python worker DB 환경 매핑 | `AI/worker/postgres_env.py` |
| Debezium connector 설정 | `Infra/cdc/connector.json` |
| 백업/복구 스크립트 | `Infra/scripts/backup-postgres.sh`, `Infra/scripts/restore-postgres.sh` |

Flyway가 Backend 시작 시 DB 마이그레이션을 적용한다. 운영 DB에서 수동으로 DDL을 먼저 적용하지 말고 migration 파일을 추가해 배포한다.
