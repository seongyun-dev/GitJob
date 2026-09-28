/**
 * Infrastructure Map의 데이터 모델 · 티켓 S15P21E102-210.
 *
 * 이 파일이 존재하는 이유는 화면이 현재 인프라 구조를 **모르게** 하려는 것이다.
 * 서버가 두 대인지 세 대인지, Kafka가 어느 서버에 있는지, DataNode가 몇 개인지는
 * 컴포넌트가 아니라 config가 안다(`topology.config.ts`). 그래서 EC2가 늘거나 서비스가
 * 옮겨가도 컴포넌트를 뜯지 않고 config만 고친다. S15P21E102-207에서 HDFS·Spark 2호스트
 * 확장이 진행 중이라 이 요구는 가정이 아니라 예정된 일이다.
 *
 * 좌표가 없는 것도 의도다. 확정 디자인은 1174x372 박스에 픽셀로 카드를 놓지만, 그 값은
 * 서버가 두 대일 때만 맞는다. 여기서는 `column`이라는 논리 순서만 주고 실제 배치는
 * 컴포넌트가 계산한다.
 *
 * 서버와 지표를 잇는 열쇠는 `role`이다. Prometheus target 라벨이며
 * `Infra/monitoring/prometheus/targets/node-exporter.yml`이 정한다. 호스트명이나 IP를
 * 열쇠로 쓰지 않는 이유는 그것들이 바뀌기 때문이다.
 */

/**
 * 한 서버에 올라가 있는 서비스.
 *
 * 상태 점을 갖지만 그 상태는 이 서비스 자신의 것이 아니라 **호스트 서버의 target
 * UP/DOWN**이다. 컨테이너 단위 UP/DOWN을 주는 exporter가 아직 없다
 * (`Infra/monitoring/prometheus/prometheus.yml`의 job은 prometheus·node-exporter·
 * kafka-exporter 셋뿐이고 cAdvisor는 없다). 확정 디자인의 각주도 같은 말을 한다 —
 * "노드 상태는 Prometheus target UP/DOWN 기준".
 *
 * 그래서 서비스별로 다른 상태를 만들지 않는다. 만들면 그 점은 근거 없는 초록불이 된다.
 */
export interface ServiceNode {
  id: string
  /** 화면에 보이는 이름. 예: `Backend` */
  label: string
  /** 짧은 종류 표기. 예: `spring`, `broker`, `hdfs` */
  tag: string
}

/** 서버 한 대. `metrics`는 여기 없다 — API가 주고 adapter가 붙인다. */
export interface ServerNode {
  id: string
  /**
   * 서버의 역할 이름. 예: `Service Server`
   *
   * 대문자 표기는 CSS가 한다(Infrastructure Map의 `SERVICE SERVER`). 같은 문자열을
   * 대소문자만 달리해 두 번 적어 두면 한쪽만 고쳐지는 일이 생긴다.
   */
  name: string
  /** 카드에 크게 보이는 호스트 이름. 예: `J15E102` */
  displayName: string
  /**
   * Prometheus target의 `role` 라벨. 지표를 이 값으로 붙인다.
   * 같은 role의 서버가 여러 대면 `instance`까지 쓴다({@link ServerNode.instance}).
   */
  role: string
  /**
   * 같은 role에 서버가 둘 이상일 때 어느 것인지 특정한다. 비워 두면 role의 첫 서버를
   * 쓴다. role 하나에 서버 하나인 현재 구성에서는 필요하지 않다.
   */
  instance?: string
  /** 배치 순서. 픽셀이 아니라 논리 순서다. 컴포넌트가 열로 바꾼다. */
  column: number
  services: readonly ServiceNode[]
}

/**
 * 연결의 종류.
 *
 * `PROMETHEUS_SCRAPE`만 다르게 그려진다(점선, 아래쪽 수집 바). 나머지는 서버 사이를
 * 흐르는 실선이다. 종류를 늘릴 때 컴포넌트에 분기를 더하지 않아도 되게 두 갈래로만
 * 나눈다.
 */
export type ConnectionType =
  | 'KAFKA_STREAM'
  | 'PROMETHEUS_SCRAPE'
  | 'HDFS_REPLICATION'
  | 'SPARK_CONTROL'

/**
 * 두 노드 사이의 연결.
 *
 * `from`·`to`는 {@link ServerNode.id} 또는 {@link TopologyConfig.monitoring}의 id다.
 * 존재하지 않는 id를 가리키면 adapter가 그 연결을 버린다 — 없는 서버로 향하는 화살표를
 * 그리는 것보다 안 그리는 것이 낫다.
 */
export interface Connection {
  id: string
  from: string
  to: string
  type: ConnectionType
  /** 연결 위에 붙는 이름. 예: `Kafka Streaming` */
  label?: string
  /**
   * 보조 설명. 예: `Producer → Consumer`
   *
   * 여기에 런타임 수치를 적지 않는다. 확정 디자인의 `job-postings · 3 partitions`는
   * mock이며(실제 토픽 이름은 `gitjob.*`이고 partition 수를 주는 API도 없다) 그대로
   * 옮기면 화면이 없는 사실을 주장한다.
   */
  caption?: string
}

/** 수집 주체. 서버 카드가 아니라 아래쪽 바로 그려진다. */
export interface MonitoringNode {
  id: string
  label: string
  /** 예: `Grafana`. 없으면 표시하지 않는다. */
  dashboardLabel?: string
}

/**
 * 현재 topology 선언.
 *
 * 이 객체가 인프라 구조에 대한 화면의 유일한 지식이다. `replicationFactor`처럼 값을
 * 확인하지 못한 항목은 `null`로 두고 화면이 그 줄을 그리지 않게 한다. 임의의 숫자를
 * 넣으면 그것이 곧 화면의 주장이 된다.
 */
export interface TopologyConfig {
  servers: readonly ServerNode[]
  connections: readonly Connection[]
  monitoring: MonitoringNode
  /** HDFS 복제 계수. 근거 있는 설정값이 없으면 `null`. */
  replicationFactor: number | null
}
