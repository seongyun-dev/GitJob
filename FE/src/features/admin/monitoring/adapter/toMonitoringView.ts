import type { MonitoringOverview, ServerMetrics } from '@/features/admin/monitoring/api/monitoringApi'
import type { CoverageState, PrometheusState } from '@/features/admin/monitoring/model/monitoringState'
import type {
  Connection,
  MonitoringNode,
  ServerNode,
  TopologyConfig,
} from '@/features/admin/monitoring/model/topology'

/**
 * topology config와 API 응답을 화면이 그릴 모양으로 합친다 · 티켓 S15P21E102-210.
 *
 * 이 파일이 따로 있는 이유는 두 가지가 서로 다른 속도로 바뀌기 때문이다. config는 인프라
 * 구성이고 응답은 매 30초 갱신되는 관측값이다. 컴포넌트 안에서 둘을 합치면 서버가 한 대
 * 늘 때마다 컴포넌트를 열어야 한다.
 *
 * 순수 함수다. 여기서 fetch하거나 시각을 읽지 않는다.
 */

/**
 * 화면에 그릴 서버 한 대.
 *
 * `metrics`가 `null`이면 config에는 있는데 Prometheus 결과에 그 서버가 없다는 뜻이다.
 * 없는 값을 0으로 채우지 않고 그대로 비운다.
 */
export interface ServerView {
  node: ServerNode
  metrics: ServerMetrics | null
}

export interface MonitoringView {
  state: PrometheusState
  reachable: boolean
  updatedAt: string
  /** 미연결이면 `null`. */
  targets: { up: number; total: number } | null
  scrapeIntervalSeconds: number | null
  /** config의 `column` 순서. */
  servers: readonly ServerView[]
  /**
   * Prometheus는 알고 있는데 topology config에는 없는 서버.
   *
   * 조용히 버리지 않는다. 인프라에 서버가 추가됐는데 config를 갱신하지 않은 상황이
   * 정확히 이 목록으로 드러나야 한다. 감추면 운영자는 화면에 보이는 두 대가 전부라고
   * 믿는다.
   */
  unmappedServers: readonly ServerMetrics[]
  /** 양 끝이 모두 실재하는 연결만. */
  connections: readonly Connection[]
  monitoring: MonitoringNode
  replicationFactor: number | null
  kafkaUp: boolean | null
  coverage: MonitoringOverview['coverage']
  links: MonitoringOverview['links']
}

/**
 * config의 서버와 응답의 서버를 잇는다.
 *
 * 열쇠는 `role`이고, 같은 role에 서버가 둘 이상일 때만 `instance`까지 본다. 호스트명이나
 * IP를 열쇠로 쓰지 않는 이유는 그것들이 바뀌기 때문이다.
 */
function findMetrics(
  node: ServerNode,
  servers: readonly ServerMetrics[],
): ServerMetrics | null {
  if (node.instance !== undefined) {
    return servers.find((server) => server.instance === node.instance) ?? null
  }
  return servers.find((server) => server.role === node.role) ?? null
}

/**
 * 연결의 양 끝이 실재하는지 확인한다. 없는 서버로 향하는 화살표는 그리지 않는다 —
 * 지운 서버로 이어진 선이 남아 있으면 화면이 없는 구조를 주장한다.
 */
function isResolvable(connection: Connection, knownIds: ReadonlySet<string>): boolean {
  return knownIds.has(connection.from) && knownIds.has(connection.to)
}

export function toMonitoringView(
  topology: TopologyConfig,
  overview: MonitoringOverview,
): MonitoringView {
  const servers = [...topology.servers]
    .sort((left, right) => left.column - right.column)
    .map((node) => ({ node, metrics: findMetrics(node, overview.servers) }))

  const mappedInstances = new Set(
    servers
      .map((server) => server.metrics?.instance)
      .filter((instance): instance is string => instance !== undefined),
  )

  const knownIds = new Set<string>([
    ...topology.servers.map((node) => node.id),
    topology.monitoring.id,
  ])

  return {
    state: overview.prometheus.state,
    reachable: overview.prometheus.reachable,
    updatedAt: overview.updatedAt,
    targets:
      overview.prometheus.targetsUp === null || overview.prometheus.targetsTotal === null
        ? null
        : { up: overview.prometheus.targetsUp, total: overview.prometheus.targetsTotal },
    scrapeIntervalSeconds: overview.prometheus.scrapeIntervalSeconds,
    servers,
    unmappedServers: overview.servers.filter(
      (server) => !mappedInstances.has(server.instance),
    ),
    connections: topology.connections.filter((connection) =>
      isResolvable(connection, knownIds),
    ),
    monitoring: topology.monitoring,
    replicationFactor: topology.replicationFactor,
    kafkaUp: overview.kafka.up,
    coverage: overview.coverage,
    links: overview.links,
  }
}

/**
 * 서버 카드의 상태 점이 무엇을 근거로 하는가.
 *
 * Prometheus에 닿지 못하면 서버가 살았는지 죽었는지 알 수 없다. 그때 `false`(=DOWN)를
 * 주면 화면은 서버 두 대가 죽었다고 주장하게 된다. 그래서 `null`을 둔다.
 */
export function serverUpState(view: MonitoringView, server: ServerView): boolean | null {
  if (!view.reachable || server.metrics === null) {
    return null
  }
  return server.metrics.up
}

/** 미수집 범위가 하나라도 있는지. Data Platform 섹션의 안내 문구가 쓴다. */
export function hasUncollectedCoverage(coverage: MonitoringOverview['coverage']): boolean {
  return Object.values(coverage).some((state: CoverageState) => state === 'NOT_COLLECTED')
}
