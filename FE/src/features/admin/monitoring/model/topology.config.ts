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
        /*
         * 두 컴포넌트를 나눠 적는다 · 티켓 S15P21E102-313.
         *
         * 한 칩에 `Collector / kafka→hdfs` 로 묶여 있었는데, 실제로는 서로 다른 서비스이고
         * Kafka 를 읽는 쪽은 Collector 가 아니다.
         *
         *   collector          외부 소스 수집기. GitHub API · GH Archive 를 읽어 WebHDFS 로
         *                      RAW 를 적재한다(`RAW_ROOT=hdfs:///gitjob/raw`). 상시 프로세스는
         *                      health 서버이고 수집은 `AI/collector/gharchive` 배치가 한다.
         *   spark-c1-archiver  C1 Archiver(티켓 112·228). Spark Structured Streaming 으로
         *                      `github.events`·`so.raw` 를 읽어 HDFS 에 적재한다. 이쪽이
         *                      말 그대로 Kafka → HDFS 다.
         *
         * `id` 는 compose 서비스명을 그대로 쓴다. 화면에 보이는 이름만 사람이 읽기 좋게
         * 줄인다 — 운영 명칭을 화면이 새로 만들지 않는다.
         */
        { id: 'collector', label: 'Collector', tag: 'gh-archive→hdfs' },
        { id: 'spark-c1-archiver', label: 'C1 Archiver', tag: 'kafka→hdfs' },
      ],
    },
  ],
  connections: [
    {
      id: 'kafka-stream',
      from: 'service',
      to: 'data',
      type: 'KAFKA_STREAM',
      /*
       * `Kafka Streaming` 이 아니라 `Kafka` 다 · 티켓 S15P21E102-313.
       *
       * 이 값 하나를 제목(`Service Server → ? → Data Server`)과 가운데 필이 함께 쓴다.
       * 길게 적으면 두 서버 사이에 세 번째 서버가 있는 것처럼 읽히는데, broker 는
       * 서비스 서버(J15E102) 한 곳에만 있다 — 데이터 호스트는 broker 를 돌리지 않는다
       * (`Infra/compose/compose.ec2.yaml`, `compose.yaml` 의 kafka 주석).
       *
       * broker 라는 사실은 서비스 서버 카드의 `Kafka / broker` 칩과 아래 caption 이 말한다.
       */
      label: 'Kafka',
      // 토픽 이름과 partition 수는 적지 않는다. 확정 디자인의 `job-postings · 3 partitions`는
      // mock이고, 실제 토픽은 `gitjob.*`(루트 `.env.example`)이며 partition 수를 주는 API가
      // 없다. 확인된 뒤에 이 caption에 넣는다.
      //
      // Producer 를 적지 않는 이유는 위치가 하나로 특정되지 않기 때문이다 — Backend 도
      // 배치 수집기도 produce 한다. 대신 broker 가 어디 있고 누가 받아 적재하는지를 적는다.
      caption: 'Kafka Broker → C1 Archiver · HDFS 적재',
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
