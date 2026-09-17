# Prometheus mount drift remediation runbook

`S15P21E102-292` 의 Production 실행 절차. guard 계약은 `S15P21E102-304` 가
추가했고, 이 문서는 그것을 쓰는 정확한 명령이다.

**이 문서의 명령은 승인 후에만 실행한다.** 작성 시점에는 실행하지 않았다.

## 무엇이 잘못돼 있나

2026-09-17 서비스 호스트 실측:

```
gitjob-service-prometheus-1
  config_files:
    S15P21E102-monitoring/Infra/compose/compose.yaml
    S15P21E102-monitoring/Infra/compose/compose.ec2.yaml
    S15P21E102-monitoring/Infra/compose/compose.monitoring.yaml
  mounts:
    .../S15P21E102-monitoring/Infra/monitoring/prometheus/prometheus.yml -> /etc/prometheus/prometheus.yml
    .../S15P21E102-monitoring/Infra/monitoring/prometheus/targets        -> /etc/prometheus/targets

json-exporter : 존재하지 않음
```

Prometheus가 **stale checkout**의 config와 targets를 bind mount 중이다. 그
checkout에는 HDFS/Spark job이 없어 runtime에 해당 target이 없고, 그래서 화면의
HDFS·Spark 카드가 null이다.

bind mount 경로는 **컨테이너 생성 시점에 고정**된다. config reload로는 바뀌지
않는다. Codex 실증도 같다 — reload만으로는 불충분, json-exporter 생성만으로도
불충분, **Prometheus targeted recreate가 필요**하다.

## 실행 전 확인

```bash
ssh <SERVICE_HOST> 'cd ~/workspace/S15P21E102 \
  && git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD \
  && git status --porcelain | wc -l \
  && grep -c "job_name" Infra/monitoring/prometheus/prometheus.yml'
```

canonical checkout이 `develop` 이고 clean이며 HDFS/Spark job이 들어 있는지
확인한다. 아니면 중단한다.

## 1단계 — json-exporter 생성 (normal mode)

remediation이 아니다. `--no-recreate` 는 없는 컨테이너의 **생성을 막지 않는다.**

```bash
cd ~/workspace/S15P21E102

python3 Infra/scripts/deploy_guard.py observability \
  --compose-file Infra/compose/compose.yaml \
  --compose-file Infra/compose/compose.ec2.yaml \
  --compose-file Infra/compose/compose.monitoring.yaml \
  --profile=observability \
  --target-service=json-exporter \
  --flag=--no-deps --flag=--no-recreate

docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2.yaml \
  -f Infra/compose/compose.monitoring.yaml \
  --profile core --profile app --profile ci --profile observability \
  up -d --no-deps --no-recreate --no-build json-exporter
```

Prometheus가 json-exporter를 scrape하므로 **먼저** 만든다.

## 2단계 — Prometheus targeted recreate (remediation mode)

```bash
python3 Infra/scripts/deploy_guard.py observability \
  --compose-file Infra/compose/compose.yaml \
  --compose-file Infra/compose/compose.ec2.yaml \
  --compose-file Infra/compose/compose.monitoring.yaml \
  --profile=observability \
  --target-service=prometheus \
  --flag=--no-deps \
  --remediation \
  --deploy-path="$PWD" \
  --production-path=/home/ubuntu/workspace/S15P21E102

docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2.yaml \
  -f Infra/compose/compose.monitoring.yaml \
  --profile core --profile app --profile ci --profile observability \
  up -d --no-deps --force-recreate --no-build prometheus
```

`--no-deps` 가 의존 서비스를 끌어오지 않게 하고, 대상이 `prometheus` 하나라서
다른 컨테이너는 건드리지 않는다. guard가 exit 1이면 **compose를 실행하지 않는다.**

## 영향 범위

| 컨테이너 | 영향 |
|---|---|
| `gitjob-service-json-exporter-1` | **신규 생성** |
| `gitjob-service-prometheus-1` | **recreate** (mount 교체) |
| `gitjob-service-node-exporter-1` | 없음 |
| `gitjob-service-grafana-1` | 없음 |
| `gitjob-service-kafka-exporter-1` | 없음 |
| backend / nginx / postgres / redis / kafka | 없음 |
| 데이터 호스트 전체 (HDFS / Spark / C1 / collector) | 없음 |

## 예상 downtime

Prometheus recreate 동안 **수 초**. 그 사이의 영향:

- Admin Monitoring 화면이 잠시 빈 값을 보일 수 있다
- 시계열 데이터는 named volume `gitjob-service_prometheus-data` 에 있어
  **보존된다** (recreate는 volume을 지우지 않는다)
- scrape 공백이 수 초 생긴다

backend / nginx / 사용자 API에는 downtime이 없다.

## 검증

```bash
# mount가 canonical로 바뀌었는가
docker inspect -f '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' \
  gitjob-service-prometheus-1 | grep prometheus

# config_files 라벨이 canonical checkout인가
docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' \
  gitjob-service-prometheus-1

# HDFS/Spark job이 runtime에 올라왔는가
curl -s localhost:9090/api/v1/targets | grep -oE '"job":"[^"]+"' | sort -u

# json-exporter 기동
docker ps --filter name=json-exporter --format '{{.Names}} {{.Status}}'

# 건드리지 않아야 할 것들의 restart count가 그대로인가
docker inspect -f '{{.Name}} restarts={{.RestartCount}}' \
  gitjob-service-node-exporter-1 gitjob-service-grafana-1 \
  gitjob-service-kafka-exporter-1 gitjob-service-backend-1
```

## Rollback

Prometheus를 되돌려야 하면 같은 형태로 다시 recreate한다.

```bash
cd ~/workspace/S15P21E102
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2.yaml \
  -f Infra/compose/compose.monitoring.yaml \
  --profile core --profile app --profile ci --profile observability \
  up -d --no-deps --force-recreate --no-build prometheus
```

시계열은 named volume에 있어 recreate로 사라지지 않으므로 데이터 손실 rollback은
해당 사항이 없다.

json-exporter를 되돌리려면 그 컨테이너만 제거한다.

```bash
docker rm -f gitjob-service-json-exporter-1
```

stale checkout의 config로 돌아가는 rollback은 **하지 않는다.** 그것이 애초에
고치려는 상태다.

## 하지 않는 것

- 다른 monitoring 서비스 recreate (`node-exporter` / `grafana` / `kafka-exporter`)
  — guard의 `REMEDIATION_SERVICES` 가 거부한다
- full observability project reconcile
- 데이터 호스트 / HDFS / Spark / Kafka / backend 변경
- stale worktree 복원

## 참고

- `S15P21E102-292` — 2호스트 모니터링 실지표 연결 (이 실행의 소유자)
- `S15P21E102-304` — observability remediation mode (이 실행을 가능하게 한 guard 계약)
- `S15P21E102-300` — deploy fail-closed guard
- `docs/infra/2026-09-17-deploy-topology-guard.md` — guard 계약 전문
