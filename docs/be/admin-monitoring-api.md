# Admin Monitoring API

- Jira: `S15P21E102-209` (parent Story `S15P21E102-52`)
- 소비자: `S15P21E102-210` [FE] Admin System Monitoring 화면
- 선행: `S15P21E102-205` [INFRA] Prometheus/Grafana 운영 모니터링 MVP
- 기준일: 2026-09-10
- 상태: **구현됨 · Unit/Controller Test 검증됨 · `Runtime verification pending`**

> `Runtime verification pending` — 실제 Prometheus 응답과 실제 BE proxy 응답은 아직
> 확인하지 않았다. 개발 PC가 관리자망에 접근할 수 없어서다. 무엇이 미검증인지와 확인
> 절차는 8장에 있다. 테스트 통과를 Runtime 검증으로 표기하지 않는다.

## 1. 문제

Admin System Monitoring 화면은 서버 상태와 자원 지표를 보여줘야 한다. 값은
Prometheus에 이미 있다(`S15P21E102-205`). 그러나 Prometheus와 Grafana는 관리자망
(Tailscale)에만 바인드되어 있고 공개 nginx 경로가 없어 **브라우저가 직접 조회할 수 없다.**

사설 주소를 FE 번들에 넣는 것은 두 가지 이유로 불가능하다. 번들은 공개 배포물이므로
관리자망 주소가 그대로 노출되고, 브라우저가 그 주소에 닿지도 못한다.

## 2. 결정

Backend가 Prometheus HTTP API를 호출해 화면이 쓰는 모양으로 바꿔 반환하는 **thin
proxy/adapter**를 둔다. 엔드포인트는 두 개다.

```
GET /api/v1/admin/monitoring/overview
GET /api/v1/admin/monitoring/timeseries?metric={cpu|memory|network}&range=60m
```

`/api/v1/admin/**`는 `SecurityConfig`가 이미 `hasRole("ADMIN")`으로 제한하므로 별도
보안 설정을 추가하지 않았다.

## 3. 선택 이유와 검토한 대안

**엔드포인트를 2개로 둔 이유.** 초안은 `/overview`, `/servers`, `/targets`,
`/timeseries` 4개였다. 화면이 그 값을 한 번에 다 그리기 때문에 나누면 요청만 늘고,
화면 어느 부분은 갱신됐고 어느 부분은 아닌 상태가 생긴다. Server Detail 표와
Infrastructure Map의 상태 점, Disk 용량, Quick Access 링크는 모두 `overview` 하나에서
나온다.

**PromQL을 파라미터로 받지 않는 이유.** 받으면 이 엔드포인트가 관리자망 Prometheus에
대한 임의 질의 창구가 된다. 화면이 고를 수 있는 것은 닫힌 enum(`MetricKind`,
`TimeRange`)뿐이고 질의는 서버가 만든다.

**Prometheus 미도달 시 502가 아닌 이유.** 모니터링이 끊긴 것은 요청 실패가 아니라
운영자가 봐야 하는 사실이다. 5xx로 던지면 화면은 "모니터링이 끊겼다"와 "서버가 죽었다"를
구분할 수 없다. 대신 실패를 성공으로 바꾸지도 않는다 — `reachable=false`와 상태 enum이
실패를 명시하고, 값 자리는 0이 아니라 `null`로 비운다.

**`/api/v1/ops/metrics`와의 관계.** README 7장 API 카탈로그에 `GET /api/v1/ops/metrics`
(운영 지표·lag·DLQ·quota)가 있다. 아직 구현체가 없고, 그쪽은 파이프라인/quota 지표이며
`/admin/**` 밖이라 ADMIN 제한을 받지 않는다. 이번 API는 node 인프라 지표이고 관리자
화면 전용이므로 별 경로로 두었다. 둘을 합칠지는 `ops/metrics`를 실제로 구현하는 티켓에서
결정한다.

## 4. 현재 구현 범위

`BE/src/main/java/com/example/git_job/monitoring/`

| 위치 | 책임 |
|---|---|
| `config/MonitoringProperties` | Prometheus 주소·타임아웃·scrape 간격·cluster 라벨·화면 링크 |
| `client/PrometheusClient` | `query`·`query_range`·`targets` 읽기 전용 호출과 파싱 |
| `client/PrometheusUnavailableException` | 실패 종류(`UNREACHABLE`/`INVALID_RESPONSE`/`NOT_CONFIGURED`) |
| `service/MonitoringQueries` | 화면이 쓰는 PromQL 전부 |
| `service/MonitoringService` | 라벨로 묶어 서버 단위 레코드로 변환 |
| `service/MetricKind`·`TimeRange`·`MetricUnit` | 요청 어휘(닫힌 목록) |
| `controller/AdminMonitoringController` | 두 엔드포인트 |
| `controller/dto/*` | 응답 계약 |

지표를 계산하지 않는다. 비율과 rate는 Prometheus가 계산하고 여기서는 옮긴다. 같은 값을
두 곳에서 계산하면 Grafana 대시보드와 화면의 숫자가 갈라지고, 그때 어느 쪽이 맞는지 알
방법이 없다.

## 5. 계약

### 5.1 `GET /overview`

성공·실패 모두 200이며 공용 `ApiResponse` 봉투(`{message, data}`)를 쓴다. 봉투는 이번
Jira에서 바꾸지 않았다(6장 참고).

```json
{
  "message": "요청이 성공적으로 처리되었습니다.",
  "data": {
    "updatedAt": "2026-09-10T05:32:05Z",
    "prometheus": {
      "reachable": true,
      "state": "CONNECTED",
      "targetsUp": 6,
      "targetsTotal": 6,
      "scrapeIntervalSeconds": 15
    },
    "servers": [
      {
        "instance": "10.0.0.1:9100",
        "role": "service",
        "node": "service-1",
        "host": "service-server",
        "up": true,
        "cpuPercent": 23.4,
        "cpuCores": 4,
        "memoryPercent": 41.0,
        "memoryUsedBytes": 6600000000,
        "memoryTotalBytes": 16000000000,
        "diskPercent": 54.0,
        "diskUsedBytes": 216000000000,
        "diskTotalBytes": 400000000000,
        "networkReceiveBytesPerSecond": 4100000.0,
        "networkTransmitBytesPerSecond": 2100000.0
      }
    ],
    "kafka": { "up": true },
    "hdfs": {
      "up": true,
      "capacityUsedBytes": 86016,
      "capacityTotalBytes": 3243303530496,
      "blocksTotal": 0,
      "liveDataNodes": 3,
      "deadDataNodes": 0,
      "capacityRemainingBytes": 3243303444480,
      "underReplicatedBlocks": 2
    },
    "spark": {
      "up": true,
      "aliveWorkers": 1,
      "coresTotal": 2,
      "coresUsed": 0,
      "memoryTotalMb": 2048,
      "memoryUsedMb": 0
    },
    "coverage": {
      "hdfs": "COLLECTED",
      "spark": "COLLECTED",
      "collector": "NOT_COLLECTED",
      "kafkaBusiness": "NOT_COLLECTED"
    },
    "links": { "grafanaUrl": null, "prometheusUrl": null }
  }
}
```

`prometheus.state`

| 값 | 뜻 | 고칠 사람 |
|---|---|---|
| `CONNECTED` | 정상 | — |
| `NOT_CONFIGURED` | 이 배포에 Prometheus 주소가 없다 | 배포 담당자 |
| `UNREACHABLE` | 주소는 있는데 닿지 않는다 | 운영자 |
| `INVALID_RESPONSE` | 닿았는데 응답을 해석할 수 없다 | 운영자 (버전·주소 확인) |

`CONNECTED`가 아니면 `targetsUp`·`targetsTotal`은 `null`이고 `servers`는 빈 배열이다. 0으로
채우지 않는다 — `0`은 "target이 하나도 없다"는 다른 사실이다.

`servers[]`의 수치가 `null`인 것과 0인 것은 다르다. `null`은 그 값을 얻지 못했다는 뜻이고
화면은 숫자 대신 값 없음으로 그려야 한다.

`kafka.up`은 exporter 시계열이 없으면 `false`가 아니라 `null`이다. "브로커가 죽었다"와
"아직 재보지 않았다"는 다른 사실이다.

`links`는 서버 설정에서만 온다. 미설정이면 `null`이라 화면이 눌러도 아무 일 없는 링크를
그리지 않는다.

### 5.2 `GET /timeseries`

```json
{
  "message": "요청이 성공적으로 처리되었습니다.",
  "data": {
    "metric": "network",
    "range": "60m",
    "stepSeconds": 300,
    "unit": "BYTES_PER_SECOND",
    "reachable": true,
    "state": "CONNECTED",
    "series": [
      {
        "instance": "10.0.0.1:9100",
        "role": "service",
        "direction": "receive",
        "points": [{ "at": "2026-09-10T05:30:00Z", "value": 4100000.0 }]
      }
    ]
  }
}
```

`metric`은 `cpu`·`memory`·`network`, `range`는 `60m`(생략 시 기본값). 목록에 없는 값은
`400 G-400-2`이며 조용히 기본값으로 바꾸지 않는다. `direction`은 network에만 있고
cpu·memory에서는 `null`이다.

`reachable=false`면 `series`는 빈 배열이다. 0으로 채운 점을 만들지 않는다 — 평평한 0
그래프는 장애가 아니라 한가한 서버로 읽힌다.

### 5.3 설정

| 키 | 환경변수 | 기본값 | 비고 |
|---|---|---|---|
| `gitjob.monitoring.prometheus.base-url` | `PROMETHEUS_BASE_URL` | 없음(빈 값) | 비면 호출하지 않고 `NOT_CONFIGURED` |
| `gitjob.monitoring.prometheus.timeout` | `PROMETHEUS_TIMEOUT` | `3s` | connect·read 공통 |
| `gitjob.monitoring.prometheus.scrape-interval` | `PROMETHEUS_SCRAPE_INTERVAL` | `15s` | `prometheus.yml`의 `global.scrape_interval`과 같아야 함 |
| `gitjob.monitoring.prometheus.cluster` | `PROMETHEUS_CLUSTER` | `gitjob` | target 라벨 값 |
| `gitjob.monitoring.links.grafana-url` | `GRAFANA_ADMIN_URL` | 없음 | 화면 Quick Access |
| `gitjob.monitoring.links.prometheus-url` | `PROMETHEUS_ADMIN_URL` | 없음 | 화면 Quick Access |

기본값에 사설 IP를 넣지 않았다. 코드에 박힌 주소는 환경이 바뀌면 조용히 틀린 곳을
가리킨다.

## 6. PromQL

`MonitoringQueries`의 질의는 새로 만든 것이 아니라 `S15P21E102-205`가 서버에서 검증해
커밋한 `Infra/monitoring/grafana/dashboards/gitjob-system-monitoring.json`의 식이다.

| 용도 | PromQL |
|---|---|
| target UP/DOWN·서버 목록 | `up{job="node-exporter",cluster="gitjob"}` |
| Kafka exporter | `max(up{job="kafka-exporter",cluster="gitjob"})` |
| CPU 사용률 | `100 - (avg by (cluster, role, instance) (rate(node_cpu_seconds_total{cluster="gitjob",mode="idle"}[5m])) * 100)` |
| Memory 사용률 | `100 * (1 - (node_memory_MemAvailable_bytes{...} / node_memory_MemTotal_bytes{...}))` |
| Disk 사용률 | `100 * (1 - (node_filesystem_avail_bytes{...,mountpoint="/",fstype!~"tmpfs\|overlay"} / node_filesystem_size_bytes{...}))` |
| Network | `sum by (cluster, role, instance) (rate(node_network_{receive,transmit}_bytes_total{cluster="gitjob",device!~"lo"}[5m]))` |

대시보드에 없고 추가한 것은 셋이다. 확정 디자인 Server Detail이 "4 vCPU", "6.6 / 16 GB"를
표시하는데 비율만으로는 그릴 수 없어서다. 셋 다 205 문서 3장이 수집 대상으로 확인한
metric family만 쓴다.

| 용도 | PromQL |
|---|---|
| vCPU 수 | `count by (cluster, role, instance) (node_cpu_seconds_total{cluster="gitjob",mode="idle"})` |
| Memory 총량 | `node_memory_MemTotal_bytes{cluster="gitjob"}` |
| Memory 잔여 | `node_memory_MemAvailable_bytes{cluster="gitjob"}` |

호스트명과 IP는 질의에 없다. 셀렉터는 `cluster`·`role`·`instance` 라벨만 쓴다. 서버를 늘릴
때 `Infra/monitoring/prometheus/targets/node-exporter.yml`에 target과 라벨만 추가하면 이
질의들이 그대로 새 서버를 포함한다(`S15P21E102-207`의 2호스트 확장이 이 경로를 쓴다).

## 7. 제공하지 않는 것

**수집 중이지만 이번 API에 없는 것.** disk I/O(`node_disk_*_bytes_total`)는 205가 수집하고
있으나 확정 디자인 v2에 그 값을 쓰는 자리가 없다(Server Detail 4열은 CPU·Memory·Disk
용량·Network). 수집 가능한 것과 이번 API가 제공할 것은 다른 문제다. 쓰는 화면이 생기면
추가한다. 같은 이유로 `TimeRange`는 `60m` 하나이고 `MetricKind`는 셋이다 — 화면에 범위
선택 컨트롤이 없고 시계열 그래프가 셋이다.

**아직 수집하지 않는 것.** Spark application/executor/stage, Collector business counter,
Kafka topic business 지표는 현재 Prometheus exposition endpoint나 exporter가 없다.
HDFS/Spark 기본 exporter가 연결되지 않은 runtime에서는 `coverage`가 `NOT_COLLECTED`로
알리고 값을 만들지 않는다.

**추정으로 넣지 않은 것.** 확정 디자인의 "load 0.9"에 해당하는 `node_load1`은 205 문서의
수집 확인 목록에 없어 넣지 않았다. node-exporter 기본 collector에 있을 가능성이 높지만,
있을 것 같다는 추정으로 질의를 만들면 빈 결과가 "부하 0"으로 읽힌다. Runtime 검증에서
존재를 확인한 뒤 별도로 추가한다.

**Grafana API.** 디자인의 Grafana 카드는 "Dashboards 4 · Datasource OK"를 보여주지만 그
값은 Grafana API를 호출해야 얻는다. 이번 범위는 Prometheus proxy이므로 넣지 않았고,
화면은 링크만 노출한다.

## 8. 검증 방법과 결과

### 로컬에서 검증됨

- `./gradlew compileJava` 성공
- `./gradlew test --tests 'com.example.git_job.monitoring.*'` — 23개 통과, 실패 0

| 테스트 | 확인하는 것 |
|---|---|
| `PrometheusClientTest` | 루프백 stub 서버로 URL 인코딩(PromQL 중괄호가 URI 템플릿으로 삼켜지지 않음), vector·matrix 파싱, `NaN`/`+Inf`/비숫자 샘플 폐기, DOWN target이 분모에 포함, `status!=success` → `INVALID_RESPONSE`, 연결 거부 → `UNREACHABLE`, 메시지에 주소 미포함, 주소 없음 → `NOT_CONFIGURED` |
| `MonitoringServiceTest` | 서버별 값 매핑과 정렬, 빈 결과가 0이 아니라 `null`, 총량/잔여 한쪽만 있으면 사용량 미생성, `instance` 라벨 없는 샘플 폐기, 미설정 시 호출하지 않음, 실패 종류 구분, `coverage` 상태, network 2방향, 시계열 실패 시 빈 배열 |
| `AdminMonitoringControllerTest` | 공용 봉투 형태, 미연결이 200 본문으로 옴, `null` 필드가 0이 되지 않음, 모르는 metric·range가 `400 G-400-2` |

Prometheus를 부르지 않는다. stub 서버는 루프백이며 실제 외부 호출은 단위 테스트에서
하지 않는다(PROJECT_GUIDE 10.9).

### 미검증 — `Runtime verification pending`

아래는 **하지 않았다.** 개발 PC에 Tailscale이 없어 관리자망
Prometheus(`:9090`)에 도달하지 않는다(`curl` 종료 코드 000).

- 실제 Prometheus `/api/v1/query`·`/api/v1/query_range`·`/api/v1/targets` 응답
- 실제 라벨 값(`role`, `node`, `host`, `instance`)이 예상과 일치하는지
- `node_filesystem_*`의 `mountpoint="/"`가 두 서버에서 각각 한 건인지
- `count by (...) (node_cpu_seconds_total{mode="idle"})`가 실제 vCPU 수와 같은지
- `BE /api/v1/admin/monitoring/overview`·`/timeseries` 실제 응답
- ADMIN 권한 실제 차단

전체 테스트를 돌리면 `GitJobApplicationTests.contextLoads()`가 실패한다. 개발 PC에
PostgreSQL이 없어 Flyway가 연결하지 못하는 것이고(`5432` 미개방, Docker 없음) 이번 변경과
무관하다. 나머지 194개는 통과한다.

서버 접근이 가능한 환경에서 아래를 확인한 뒤 이 절을 갱신한다. 테스트 통과를 Runtime
검증으로 표기하지 않는다.

```bash
# 1. Prometheus에 질의가 실제로 응답하는지 (관리자망에서, READ-ONLY)
curl -sG "$PROMETHEUS_BASE_URL/api/v1/query" \
  --data-urlencode 'query=up{job="node-exporter",cluster="gitjob"}' | jq '.data.result[].metric'

curl -sG "$PROMETHEUS_BASE_URL/api/v1/query" \
  --data-urlencode 'query=count by (cluster, role, instance) (node_cpu_seconds_total{cluster="gitjob",mode="idle"})' \
  | jq '.data.result[] | {instance:.metric.instance, cores:.value[1]}'

curl -sG "$PROMETHEUS_BASE_URL/api/v1/query" \
  --data-urlencode 'query=node_filesystem_size_bytes{cluster="gitjob",mountpoint="/",fstype!~"tmpfs|overlay"}' \
  | jq '.data.result | length'

# 2. Backend proxy 응답 (ADMIN 세션 쿠키 필요)
curl -s -b "$ADMIN_COOKIE" "$BE_ORIGIN/api/v1/admin/monitoring/overview" | jq '.data.prometheus, .data.servers'
curl -s -b "$ADMIN_COOKIE" "$BE_ORIGIN/api/v1/admin/monitoring/timeseries?metric=cpu" | jq '.data.series[0].points | length'

# 3. 권한 차단 (쿠키 없이 401/403이어야 한다)
curl -s -o /dev/null -w '%{http_code}\n' "$BE_ORIGIN/api/v1/admin/monitoring/overview"
```

첫 번째 명령의 `role`·`node`·`host` 라벨이 응답에 실려 오는지, 세 번째 명령이 서버 대수와
같은 건수(현재 2)를 주는지가 핵심 확인 항목이다. 라벨이 없거나 파일시스템이 여러 건이면
`MonitoringService`가 첫 값만 쓰므로 결과가 달라진다.

## 9. 후속 작업

- `S15P21E102-210` FE 화면 연결
- Runtime 검증 수행 및 이 문서 8장 갱신
- `node_load1` 존재 확인 후 CPU 보조 표기 추가
- Production observability overlay 배포 후 HDFS/Spark `coverage`와 실제 값 read-back 검증
- Alertmanager 도입 시 Recent Events 공급원 결정(현재 화면은 PREPARING)
- `/api/v1/ops/metrics` 구현 시 경로 통합 여부 결정
- 공용 `ApiResponse`에 `meta` 블록이 없는 것과 PROJECT_GUIDE 14장 예시의 차이 — 이번
  Jira 범위 밖이며 기존 컨트롤러 전체에 걸친 계약 문제다

## 10. 관련

- Jira: `S15P21E102-52`, `S15P21E102-205`, `S15P21E102-207`, `S15P21E102-209`, `S15P21E102-210`
- 문서: [Prometheus/Grafana 운영 모니터링 MVP](../infra/2026-09-10-gitjob-system-monitoring.md)
- 설정: `Infra/monitoring/prometheus/prometheus.yml`,
  `Infra/monitoring/prometheus/targets/node-exporter.yml`,
  `Infra/monitoring/grafana/dashboards/gitjob-system-monitoring.json`
