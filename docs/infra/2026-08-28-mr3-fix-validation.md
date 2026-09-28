# MR !3 수정 및 검증 기록

> 상태: 수정 반영, 핵심 인프라 smoke 검증 완료
>
> 작성일: 2026-08-28
>
> 검토 대상 기준 HEAD: `cfb7b24b6de4cf1d2cda959466f8d66602e7ef5c`

## 1. 문서 목적

MR !3 검토에서 확인된 실행 불가 구성, 데이터 삭제 위험, 환경 간 계약 불일치,
GitJob 요구사항과 충돌하는 문서를 수정한 결과를 기록한다. 이 문서는 실제로
검증한 범위와 아직 외부 환경 또는 애플리케이션 소스가 필요한 범위를 분리해
재검토 근거로 사용한다.

상세 운영 절차는 [Infra 실행 안내](../../Infra/README.md), 전체 준비도는
[인프라 준비도](2026-08-27-infra-readiness.md)를 기준으로 한다.

## 2. 검토 항목별 반영 내용

| 영역 | 반영 내용 | 주요 위치 |
|---|---|---|
| Compose volume | 명시적 고정 `name`을 제거해 Compose project별 volume을 사용하고, CI cleanup은 `gitjob-ci-*` project만 허용 | `Infra/compose/compose.yaml`, `Jenkinsfile` |
| HDFS | 공식 Hadoop 환경변수 형식, `/data` 권한 초기화, NameNode 최초 format 경계, HDFS bootstrap 추가 | `Infra/compose/compose.yaml` |
| Spark | Python 포함 Apache Spark 3.5.3 기반 이미지, foreground master/worker command, Worker UI host port 제거 | `Infra/docker/spark/`, `Infra/compose/compose*.yaml` |
| 분산처리 | Worker 1/2/4 확장과 dataset 1x/2x/4x 반복 실행을 위한 smoke·benchmark 스크립트 추가 | `Infra/scripts/spark-smoke.sh`, `Infra/scripts/spark-benchmark.sh` |
| Jenkins label | 다중 label을 `docker && linux` 표현식으로 수정 | `Jenkinsfile` |
| Jenkins agent secret | 임의 secret 생성을 제거하고 controller가 발급한 JNLP secret을 bootstrap 후 0600 파일로 주입 | `Infra/scripts/bootstrap-jenkins-agent.sh`, `Infra/docker/jenkins/agent-entrypoint.sh` |
| Jenkins toolchain | Java 21, Node/npm, Docker CLI/Compose v2, Git, SSH가 포함된 agent image 구성 | `Infra/docker/jenkins/agent.Dockerfile` |
| CI 환경 | 비밀값 없는 `.env.ci.example`을 추가하고 Pipeline에서 깨끗한 workspace에 `.env.ci`를 준비 | `.env.ci.example`, `Jenkinsfile` |
| Push/Deploy gate | 기본값은 실패가 아닌 `SKIPPED`, 명시적인 Pipeline parameter와 credential이 있을 때만 실행 | `Jenkinsfile` |
| API 계약 | GitHub OAuth callback을 `/api/v1/auth/github/callback`으로 통일 | `.env.example`, Compose, BE 문서 |
| 제품 범위 | RAG Q&A를 필수 기능으로 복구하고 검색 구현 방식은 별도 결정으로 분리 | `README.md`, `docs/product/`, `docs/ai/` |
| 문서 정합성 | 현재 제품 범위와 맞지 않는 잔여 내용·이전 환경명·예시를 실행 문서에서 제거하고 public/private 저장소 정책을 통일 | `README.md`, `docs/`, `Infra/` |

## 3. 주요 실행 계약

### 3.1 Volume 격리

Compose volume에는 명시적인 Docker volume `name`을 두지 않는다. 따라서
`COMPOSE_PROJECT_NAME`이 volume 이름에 반영된다.

```text
gitjob-local_postgres-data
gitjob-ci-99_postgres-data
```

Jenkins의 post cleanup은 project 이름이 `gitjob-ci-*`인지 확인한 뒤에만
`down --volumes`를 수행한다. 로컬 개발 project의 volume은 CI job 종료로
삭제되지 않는다.

### 3.2 HDFS와 Spark

`data` profile은 다음 순서로 기동한다.

1. init service가 새 `/data` volume의 소유권을 `hadoop:hadoop`으로 맞춘다.
2. NameNode가 비어 있는 name directory에서 한 번만 format하고 기동한다.
3. DataNode가 NameNode에 등록된다.
4. HDFS bootstrap이 smoke/Parquet 경로를 만든다.
5. Spark master와 Worker가 `spark://spark-master:7077`로 연결된다.

Spark smoke job은 고정된 dataset id와 배수 값을 받아 Parquet를 생성하고,
dataset id·row count·Spark version·Worker 수를 JSON으로 남긴다. Worker UI는
host port를 고정하지 않고 master UI에서 등록된 Worker 수를 확인한다.

### 3.3 Jenkins

`PROFILES=...,ci ./Infra/scripts/up.sh`는 controller를 먼저 기동한다.
`bootstrap-jenkins-agent.sh`가 `docker-agent` node의 controller 발급 secret을
조회해 `.local/jenkins/` 아래 0600 파일로 저장하고, agent는 그 파일을 읽어
연결한다. secret은 `.env.example`, Compose `Config.Env`, build log에 넣지 않는다.

Pipeline은 다음 단계로 구성한다.

```text
Prepare CI environment → Validate → Backend test → Frontend test/build
→ (조건부) Deploy
```

`DEPLOY_ENABLED=false`가 기본값이며, Deploy는 develop 브랜치에서 명시적으로
활성화했을 때만 실행된다.

## 4. 검증 결과

검증 환경은 Docker Engine 29.6.2, Docker Compose v5.3.1이다. HDFS/Spark는
기존 `gitjob` project와 분리한 임시 Compose project에서 실행한 뒤 해당
project와 volume을 정리했다.

| 검증 | 결과 | 비고 |
|---|---|---|
| `git diff --check` | 통과 | whitespace 오류 없음 |
| Shell syntax check | 통과 | `Infra/scripts/*.sh`, agent entrypoint |
| Markdown 상대 링크 검사 | 통과 | 대상 파일 존재 확인 |
| WSL 전체 profile Compose 병합 | 통과 | `core/app/data/ci/observability` |
| EC2 single Compose 병합 | 통과 | `core/app` |
| EC2 HA app-only Compose 병합 | 통과 | `app` |
| CI template Compose 병합 | 통과 | `.env.ci.example` 사용 |
| Volume project 격리 | 통과 | local/CI project의 volume 이름이 다름 |
| Spark image manifest | 통과 | `apache/spark:3.5.3-scala2.12-java11-python3-ubuntu` |
| HDFS cluster smoke | 통과 | 최초 format, live DataNode, put/get, NameNode 재시작 후 metadata 보존 |
| Spark Parquet smoke | 통과 | Worker 1/2/4에서 동일 job 성공 |
| Benchmark harness smoke | 통과 | Worker 1 × dataset 1x × 1회 실행; TSV summary 생성 |
| Jenkins agent toolchain | 통과 | Java 21, Node 22/npm, Docker CLI/Compose, Git, SSH |
| Jenkins controller·webhook·registry·deploy 전체 흐름 | 미검증 | controller plugin mirror와 외부 credential 필요 |

검증 결과 파일은 `.local/` 아래에 생성되며 Git에는 포함하지 않는다. 전체
benchmark 조합의 성능 표와 CPU/RAM 측정값은 실제 데이터 pipeline과 고정
dataset이 준비된 뒤 기록한다.

## 5. 재현 명령

```bash
# Compose 병합
docker compose --project-directory . --env-file .env.ci.example \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.wsl.yaml \
  --profile core --profile app --profile data --profile ci \
  --profile observability config --quiet

# HDFS/Spark 최소 검증
PROFILES=core,app,data ./Infra/scripts/up.sh
./Infra/scripts/spark-smoke.sh

# Worker 1/2/4 × dataset 1x/2x/4x benchmark
./Infra/scripts/spark-benchmark.sh

# Jenkins controller-first bootstrap
PROFILES=core,app,data,ci ./Infra/scripts/up.sh
```

실제 CI에서는 `.env.ci.example`을 그대로 운영 secret으로 사용하지 않는다.
Registry 인증, GitLab webhook, EC2 SSH key와 같은 값은 Jenkins Credentials로
주입한다.

## 6. 남은 검증과 다음 조건

- `BE/`, `FE/`, `AI/`에 애플리케이션 소스가 추가되기 전에는 Backend API,
  Frontend build, Collector/Worker end-to-end를 통과한 것으로 표시하지 않는다.
- Jenkins controller image는 plugin mirror 네트워크 상태 때문에 이 검증에서
  실제 online node와 Pipeline 실행까지 완료하지 못했다. mirror가 정상화되면
  `docker-agent` online, Validate/Test/Build, 기본 Push/Deploy skipped를
  순서대로 확인한다.
- Registry push와 EC2 deploy는 실제 credential과 배포 wrapper가 연결된 뒤
  검증한다. 현재 Deploy stage는 wrapper가 없으면 명확히 실패하도록 되어 있다.
- 전체 benchmark는 동일한 실제 입력 dataset, parser/Registry version,
  partition 설정을 고정한 뒤 Worker 1/2/4와 dataset 1x/2x/4x를 반복하고,
  throughput·p50/p95·실패 수·CPU/RAM을 같은 형식으로 기록한다.
- 이미 생성된 로컬 `.env.wsl`은 Git에서 무시되므로 이 변경으로 자동 덮어쓰지
  않는다. 기존 환경을 계속 사용할 때는 `.env.example`의 최신 변수와 비교해
  필요한 값을 수동 반영한다.

## 7. 관련 문서

- [인프라 문서 목차](README.md)
- [인프라 준비도](2026-08-27-infra-readiness.md)
- [배포 준비 계획](2026-08-27-infra-deployment-plan.md)
- [QA·검증 계획](../qa/README.md)
