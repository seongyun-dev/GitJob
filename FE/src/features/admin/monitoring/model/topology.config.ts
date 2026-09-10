import type { TopologyConfig } from '@/features/admin/monitoring/model/topology'

/**
 * 현재 운영 topology · 티켓 S15P21E102-210.
 *
 * **인프라가 바뀌면 고치는 파일은 여기 하나다.** 컴포넌트에는 서버 이름도, 서비스 위치도,
 * 개수도 없다.
 *
 * 값의 출처는 확정 디자인 `GitJob Admin Monitoring v2`와
 * `Infra/monitoring/prometheus/targets/node-exporter.yml`의 `role` 라벨이다. 디자인의
 * Infrastructure Map은 파일 주석 스스로가 `DESIGN MOCK / FUTURE STATE`라고 적어 두었으므로
 * 여기 적힌 서비스 배치도 운영 사실의 증명이 아니다. 실제 배치가 다르면 이 파일을 고친다.
 *
 * 서버를 늘리는 절차:
 *   1. `Infra/monitoring/prometheus/targets/node-exporter.yml`에 node-exporter target과
 *      `cluster`/`role`/`node`/`host` 라벨 추가
 *   2. 이 파일 `servers`에 항목 추가 (`role`이 1번의 라벨과 같아야 한다)
 *   3. 필요하면 `connections`에 연결 추가
 *
 * 컴포넌트와 BE 계약은 건드리지 않는다.
 */
export const GITJOB_TOPOLOGY: TopologyConfig = {
  servers: [
    {
      id: 'service',
      name: 'Service Server',
      displayName: 'J15E102',
      role: 'service',
      column: 0,
      services: [
        { id: 'backend', label: 'Backend', tag: 'spring' },
        { id: 'kafka', label: 'Kafka', tag: 'broker' },
        { id: 'redis', label: 'Redis', tag: 'cache' },
        { id: 'prometheus', label: 'Prometheus', tag: 'server' },
        { id: 'grafana', label: 'Grafana', tag: 'ui' },
      ],
    },
    {
      id: 'data',
      name: 'Data Server',
      displayName: 'J15E102A',
      role: 'data',
      column: 1,
      services: [
        { id: 'hdfs-namenode', label: 'HDFS NameNode', tag: 'hdfs' },
        { id: 'hdfs-datanode', label: 'HDFS DataNode', tag: 'hdfs' },
        { id: 'spark-master', label: 'Spark Master', tag: 'spark' },
        { id: 'spark-worker', label: 'Spark Worker', tag: 'spark' },
        { id: 'collector', label: 'Collector', tag: 'kafka→hdfs' },
      ],
    },
  ],
  connections: [
    {
      id: 'kafka-stream',
      from: 'service',
      to: 'data',
      type: 'KAFKA_STREAM',
      label: 'Kafka Streaming',
      // 토픽 이름과 partition 수는 적지 않는다. 확정 디자인의 `job-postings · 3 partitions`는
      // mock이고, 실제 토픽은 `gitjob.*`(루트 `.env.example`)이며 partition 수를 주는 API가
      // 없다. 확인된 뒤에 이 caption에 넣는다.
      caption: 'Producer → Consumer · Collector 적재',
    },
    {
      id: 'scrape-service',
      from: 'monitoring',
      to: 'service',
      type: 'PROMETHEUS_SCRAPE',
    },
    {
      id: 'scrape-data',
      from: 'monitoring',
      to: 'data',
      type: 'PROMETHEUS_SCRAPE',
    },
  ],
  monitoring: {
    id: 'monitoring',
    label: 'Prometheus',
    dashboardLabel: 'Grafana',
  },
  // 근거 있는 설정값을 찾지 못했다. `Infra/`의 replication 설정은 Kafka·Postgres 것이고
  // HDFS `dfs.replication`은 어디에도 없다. 확인되면 숫자를 넣고, 그때까지는 화면이 이
  // 줄을 그리지 않는다.
  replicationFactor: null,
}
