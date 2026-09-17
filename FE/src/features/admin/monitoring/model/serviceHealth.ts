import type { PrometheusState } from './monitoringState'

export interface ServiceHealthEvidence {
  prometheusState: PrometheusState
  kafkaUp: boolean | null
  hdfsUp: boolean | null
  sparkUp: boolean | null
}

/**
 * Returns a service-specific state only when the current overview has a real source for it.
 * Host node-exporter state is intentionally not used as a proxy for every service on that host.
 */
export function serviceUpState(
  serviceId: string,
  evidence: ServiceHealthEvidence,
): boolean | null {
  switch (serviceId) {
    case 'prometheus':
      return evidence.prometheusState === 'CONNECTED'
        ? true
        : evidence.prometheusState === 'NOT_CONFIGURED'
          ? null
          : false
    case 'kafka':
      return evidence.kafkaUp
    case 'hdfs-namenode':
      return evidence.hdfsUp
    case 'spark-master':
      return evidence.sparkUp
    default:
      // Backend, Redis, Grafana, DataNode, Worker, and Collector have no individual health source
      // in the current API. Do not infer their state from the host or an aggregate metric.
      return null
  }
}
