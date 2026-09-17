# GitJob System Monitoring MVP

- Jira: `S15P21E102-205` (parent Story `S15P21E102-52`)
- 기준일: 2026-09-10
- 범위: Prometheus + Grafana 기반 운영 지표 대시보드의 Compose/config/provisioning
- 제외: Frontend Admin 연동, 기존 데이터 서비스 재시작, S15P21E102-194 monthly chain 중단

## 1. Audit 결과

현재 split 운영은 서비스 서버 `J15E102`와 데이터 서버 `J15E102A`로 구성된다.
기존 `observability` profile에는 Kafka UI와 Redis Insight만 있으며, audit 시점에
Prometheus, Grafana, node-exporter, Kafka exporter, JMX exporter 프로세스/컨테이너는
두 서버 모두에서 확인되지 않았다. 기존 운영 컨테이너와 `gitjob-service_default`,
`gitjob-data_default` 네트워크는 변경하지 않았다.

현재 확인된 관리자 주소는 다음과 같다.

| 대상 | 주소/포트 | 용도 |
|---|---|---|
| 서비스 서버 Tailscale | `100.71.215.74` | Grafana/Prometheus 및 서비스 node-exporter의 관리자망 바인드 주소 후보 |
| 데이터 서버 Tailscale | `100.70.66.38` | 데이터 node-exporter scrape target 및 HDFS/Spark 관리자 UI |
| Kafka | 서비스 서버 내부 `kafka:9092` | Kafka exporter bootstrap |

Prometheus/Grafana 주소는 overlay를 실제로 기동한 뒤에만 사용 가능하다. 방화벽과
Tailscale ACL은 기존 관리자망 정책을 따라야 하며, node-exporter 포트(9100)는
공개 인터넷에 노출하지 않는다.

## 2. 구성

`Infra/compose/compose.monitoring.yaml`은 기존 공통 Compose에 별도로 병합하는
monitoring overlay다. 새 서비스는 모두 기존 `observability` profile을 사용한다.

| 서비스 | 실행 호스트 | 수집/표시 범위 |
|---|---|---|
| `node-exporter` | 서비스·데이터 서버 각각 1개 | CPU, memory, filesystem, disk I/O, network I/O |
| `kafka-exporter` | 서비스 서버 1개 | broker/topic/partition/current offset/consumer lag |
| `prometheus` | 서비스 서버 1개 | 위 exporter 시계열 저장 및 scrape health |
| `grafana` | 서비스 서버 1개 | `GitJob System Monitoring` dashboard |

Prometheus는 `Infra/monitoring/prometheus/targets/node-exporter.yml`의 file-based
discovery를 통해 node-exporter를 스크랩한다. 현재 등록은 서비스 Compose DNS와
데이터 서버의 관리자망 주소이며, 각 항목에 `cluster=gitjob`, `role`, `node`,
`host`, `environment` 라벨을 부여한다. 새 서버는 이 target registry(또는 이후
동일 형식의 service-discovery 출력)에 node-exporter endpoint와 라벨만 추가하면
된다. Dashboard query는 hostname/IP를 포함하지 않고 `cluster`, `role`,
`instance`를 사용하므로 target 추가 후 기존 그래프에 자동으로 포함된다.

node-exporter는 host `/proc`·`/sys`·rootfs를 읽되 Compose 네트워크에 붙어 local
Prometheus가 DNS로 접근한다. 각 호스트의 9100 publish bind는 운영 env의
`NODE_EXPORTER_BIND_ADDRESS`로 관리자망 주소를 명시한다. target registry가
변경되면 Prometheus file-SD refresh(기본 30초) 또는 monitoring-only reload를
사용하며 기존 데이터 서비스는 재기동하지 않는다.

Grafana는 provisioning으로 `GitJob Prometheus` datasource와
`GitJob System Monitoring` dashboard를 자동 등록한다. dashboard UID는
`gitjob-system-monitoring`으로 고정한다.

## 3. 실제로 수집하는 metric

- Node Exporter: `node_cpu_seconds_total`, `node_memory_*`, `node_filesystem_*`,
  `node_disk_*_bytes_total`, `node_network_*_bytes_total`
- Kafka exporter: `kafka_brokers`, `kafka_topic_partitions`,
  `kafka_topic_partition_current_offset`, `kafka_consumergroup_lag_sum` 및
  exporter scrape `up`
- Prometheus 자체와 각 target의 scrape health: `up`

HDFS logical capacity/live DataNode/block health, Spark application/executor/stage/
shuffle/spill, Collector business counters는 현재 Prometheus exposition endpoint나
exporter가 없다. 이 MVP는 해당 값을 임의로 만들지 않고 dashboard의 coverage note에
미수집 상태를 표시한다. HDFS `dfsadmin -report`/`fsck`, Spark UI, 기존 Collector
로그는 각각의 운영 검증 수단으로 유지한다. HDFS JMX/Spark metrics exporter 및
Collector instrumentation은 후속 Task다.

확장 라벨 계약은 다음과 같다. HDFS exporter는 `cluster=gitjob`,
`role=hdfs-namenode|hdfs-datanode`, `instance`, `datanode_uuid`를 제공하고,
Spark exporter는 `role=spark-master|spark-worker|spark-executor`, `instance`,
`application_id`, `executor_id`, `worker`를 제공한다. 그러면 cluster 전체와
개별 DataNode, Spark Worker/Executor 및 application 분포를 같은 dashboard에서
조회할 수 있다. 현재 metric이 없는 항목은 N/A로 남기며 fake/mock series를 만들지
않는다. Grafana에는 `Instance`, `Worker / executor`, `Spark application` 변수를
미리 두어 metric이 추가될 때 선택 범위를 좁힐 수 있게 했다.

새 서버 추가 절차는 `node-exporter 배포 → Prometheus file-SD target/서비스
디스커버리 등록 → cluster/role/node/instance 라벨 지정 → Prometheus refresh →
Grafana 기존 그래프 확인`이다. Worker 수를 1→2→3으로 늘리는 benchmark에서는
node별 CPU/memory/disk/network 시계열과 Spark application duration을 동일한
시간 범위로 비교한다.

## 4. 안전한 검증·기동 절차

모든 명령은 해당 호스트의 clean checkout과 운영 env 파일에서 실행한다. 기존
service/data Compose를 내리거나 전체 profile을 올리지 않는다.

### 서비스 서버: config/dry-run

```bash
NODE_EXPORTER_BIND_ADDRESS=100.71.215.74 \
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2.yaml \
  -f Infra/compose/compose.monitoring.yaml \
  --profile core --profile app --profile ci --profile observability config --quiet

NODE_EXPORTER_BIND_ADDRESS=100.71.215.74 \
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2.yaml \
  -f Infra/compose/compose.monitoring.yaml \
  --profile core --profile app --profile ci --profile observability --dry-run up -d --no-deps --no-recreate --no-build \
  node-exporter kafka-exporter prometheus grafana
```

서비스 서버에서 Grafana를 대상으로 지정하기 전에는 `.env.service`(mode 600)
또는 조직의 secret provider에서 `GRAFANA_ADMIN_PASSWORD`가 비어 있지 않은지
확인한다. Compose overlay는 데이터 서버의 `config --quiet`가 Grafana 비밀값을
요구하지 않도록 빈 interpolation을 허용하지만, 비밀값 없이 Grafana를 기동하는
것은 금지한다.

### 서비스 서버: 신규 monitoring 서비스만 targeted up

```bash
NODE_EXPORTER_BIND_ADDRESS=100.71.215.74 \
docker compose --project-directory . --env-file .env.service \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2.yaml \
  -f Infra/compose/compose.monitoring.yaml \
  --profile core --profile app --profile ci --profile observability up -d --no-deps --no-recreate --no-build \
  node-exporter kafka-exporter prometheus grafana
```

### 데이터 서버: node-exporter만 targeted up

> **2026-09-17 정정 (S15P21E102-300).** 아래 명령의 base override가 이전에는
> `compose.ec2-data.yaml`이었다. 데이터 서버의 운영 topology는
> `compose.ec2-data-cluster.yaml`이며, 그쪽에만 `hdfs-bootstrap` ·
> `spark-c1-archiver` · `weekly-trend-consumer`가 있다. 두 파일 모두
> `.env.data`의 `COMPOSE_PROJECT_NAME=gitjob-data`를 읽으므로 **같은 compose
> 프로젝트**로 인식되고, 잘못된 base로 전체를 reconcile하면 그 세 서비스가
> 사라진다.
>
> 이날 05:16 outage의 직접 원인은 **이 monitoring 절차가 아니라 stale checkout
> (`~/workspace/S15P21E102-monitoring`, HEAD `2f62651`)에서 실행된 `deploy.sh`의
> full Data reconcile**이었다. 아래 절차는 `--no-deps --no-recreate` + 대상
> 서비스 1개 지정이라 기존 컨테이너를 건드리지 않는다. 그 원칙은 그대로 두고
> base override만 바로잡는다.

```bash
NODE_EXPORTER_BIND_ADDRESS=100.70.66.38 \
docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2-data-cluster.yaml \
  -f Infra/compose/compose.monitoring.yaml \
  --profile core --profile data --profile observability config --quiet

NODE_EXPORTER_BIND_ADDRESS=100.70.66.38 \
docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2-data-cluster.yaml \
  -f Infra/compose/compose.monitoring.yaml \
  --profile core --profile data --profile observability --dry-run up -d --no-deps --no-recreate --no-build node-exporter

NODE_EXPORTER_BIND_ADDRESS=100.70.66.38 \
docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml \
  -f Infra/compose/compose.ec2-data-cluster.yaml \
  -f Infra/compose/compose.monitoring.yaml \
  --profile core --profile data --profile observability up -d --no-deps --no-recreate --no-build node-exporter
```

`--no-deps`는 Kafka/HDFS/Spark/194 chain을 dependency로 끌어오지 않게 하고,
`--no-recreate`는 이미 실행 중인 기존 컨테이너를 건드리지 않게 한다. 새 monitoring
컨테이너가 없는 경우에만 생성된다. 설정 변경을 적용하기 위한 recreate는 별도 승인과
점검 없이 수행하지 않는다. `--dry-run` 결과에 기존 서비스가 포함되면 명령을 중단하고
target 목록을 다시 확인한다.

`config` 단계에서 기존 profile 간 dependency를 해석할 수 있도록 core/app/data/ci
profile을 함께 열지만, 실제 `up`과 `--dry-run`의 target은 위에 적은 monitoring
서비스뿐이다. 따라서 profile 해석이 기존 컨테이너를 시작하거나 재생성하지 않는다.

서비스 서버에서만 Prometheus/Grafana/Kafka exporter를 실행한다. 데이터 서버에는
node-exporter만 실행하므로 Prometheus/Grafana가 중복되지 않는다. Jenkins,
Jenkins-agent, Kafka, HDFS, Spark, Collector, Worker 및 S15P21E102-194 실행은
재시작하지 않는다.

## 5. Dashboard layout

`GitJob System Monitoring`은 한 화면에서 다음을 볼 수 있게 배치한다.

1. 서비스 서버·데이터 서버·Kafka scrape status
2. CPU와 memory time series
3. root disk 사용률, disk I/O, network I/O
4. `github.events`, `so.raw`, `jobs.collected` Kafka throughput/consumer lag
5. HDFS/Spark/Collector 미수집 범위 및 후속 계측 안내

Prometheus retention 기본값은 30일이며 `PROMETHEUS_RETENTION`으로 조정한다. 향후
1.00x → 1.30x → 1.69x → 2.20x benchmark를 같은 시간축에서 비교할 수 있도록
대시보드 time range와 영속 volume을 사용한다.

## 6. 검증 checklist

- `docker compose ... config --quiet` 성공
- `docker compose ... --dry-run up ...`에 신규 monitoring 서비스만 표시
- Prometheus `/api/v1/targets`에서 service/data node-exporter와 Kafka exporter `up`
- Prometheus query API에서 CPU/memory/disk/network/Kafka lag·throughput 응답
- Grafana datasource가 `gitjob-prometheus`로 provision되고 dashboard UID가 로드됨
- 서비스·데이터 기존 컨테이너의 ID/상태가 변하지 않음
- S15P21E102-194 monthly chain의 tmux/process/checkpoint/log가 변하지 않음

실제 HDFS/Spark logical metric이 필요하면 exporter 또는 Prometheus endpoint를 별도
Task로 추가한 뒤 dashboard query를 확장한다. 이번 MVP에서 미수집 항목을 정상값으로
표시하지 않는다.

## 7. 2026-09-10 server validation

구성 검증은 `infra/S15P21E102-205-prometheus-grafana-monitoring` clean worktree
`2f62651`에서 수행했다. 기본 운영 checkout은 변경하지 않았다.

### Prometheus/exporter 결과

서비스 서버에서 monitoring 신규 컨테이너만 targeted 기동한 뒤 Prometheus
`/-/ready`와 `/api/v1/targets`를 확인했다.

| target | cluster / role / instance | result |
|---|---|---|
| `node-exporter:9100` | `gitjob / service / node-exporter:9100` | `up` |
| `100.70.66.38:9100` | `gitjob / data / 100.70.66.38:9100` | `up` |
| `kafka-exporter:9308` | `gitjob / core / kafka-exporter:9308` | `up` |
| `prometheus:9090` | `gitjob / monitoring / prometheus:9090` | `up` |

실제 query 응답은 `count(node_cpu_seconds_total)=64`,
`count(node_memory_MemTotal_bytes)=2`, `count(node_filesystem_size_bytes)=12`,
`kafka_brokers=1`이었다. 현재 broker에서 `github.events`, `so.raw`,
`jobs.collected` topic label에 대한 partition/consumer-lag series는 조회되지
않았다. 토픽을 새로 만들거나 기존 Kafka 설정을 바꾸지는 않는다.

실행에 사용한 image digest는 다음과 같다.

| image | digest |
|---|---|
| `prom/prometheus:v2.54.1` | `sha256:f6639335d34a77d9d9db382b92eeb7fc00934be8eae81dbc03b31cfe90411a94` |
| `prom/node-exporter:v1.8.2` | `sha256:4032c6d5bfd752342c3e631c2f1de93ba6b86c41db6b167b9a35372c139e7706` |
| `danielqsj/kafka-exporter:v1.8.0` | `sha256:9b67b273d1e54052e7ce77c46ecd1c6619fdee7e2ed26717e6272806fbc94150` |
| `grafana/grafana:11.2.0` | `sha256:408afb9726de5122b00a2576763a8a57a3c86d5b0eff5305bc994ceb3eb96c3f` |

`GRAFANA_ADMIN_PASSWORD`는 저장소에 기록하지 않고 서비스 서버
`/home/ubuntu/workspace/S15P21E102/.env.service`에 mode 600, `ubuntu:ubuntu`로
등록했다. 값 자체는 로그나 문서에 출력하지 않았다. Grafana만
`--no-deps --no-recreate --no-build`로 targeted 기동했고 readiness는
`database=ok`, version `11.2.0`이었다. `gitjob-prometheus` datasource는
`http://prometheus:9090`, proxy access로 연결되었고, dashboard API는
`GitJob System Monitoring`, UID `gitjob-system-monitoring`, 13 panels와 3
variables(`instance`, `worker`, `application`)을 반환했다.

Prometheus dashboard 주요 query는 CPU/memory/root filesystem/disk/network에서
각 2 series로 응답했다. 현재 exporter에 해당 topic series가 없어
`github.events`, `so.raw`, `jobs.collected` throughput/lag는 0 series이며,
HDFS/Spark metric name도 0 series다. 이 항목은 N/A로 표시하고 fake 값을 만들지
않는다. Prometheus `/api/v1/targets`의 4 targets는 모두 `up`이었다.

### Host capacity and impact

검증 시점 `df -h /`는 서비스 서버 `/dev/root` 309G 중 24G used/286G available
(8%), 데이터 서버 309G 중 237G used/73G available(77%)였다. 이 값은 host
물리 용량 기준이며 HDFS logical capacity를 대신하지 않는다.

기존 서비스·데이터 컨테이너는 healthy/up 상태로 관찰됐고, 이번 compose 명령의
대상은 신규 `node-exporter`, `kafka-exporter`, `prometheus`뿐이었다. Kafka,
HDFS, Spark, Collector, Worker, Jenkins/Jenkins-agent를 재기동하거나 volume을
변경하지 않았다. 이후 Grafana도 별도 monitoring 컨테이너로만 기동했다.
S15P21E102-194 chain에는 명령을 보내지 않았으며, 데이터 서버의 확인 시점에는
`s15p21e102-194-monthly-top10k` 세션/프로세스가 관찰되지 않아 상태를 추정하지
않고 별도 조치도 하지 않았다.

## 8. 후속 작업

- HDFS NameNode/DataNode JMX 또는 Prometheus exporter 연동
- Spark master/worker 및 application metrics servlet/exporter 연동
- Collector/Worker success/failure/processed/last-successful-run 계측
- Prometheus alert rules와 외부 알림 채널
- Frontend Admin 모니터링 화면 연동(별도 Jira)
