import type { CoverageState, PrometheusState } from '@/features/admin/monitoring/model/monitoringState'
import { get } from '@/shared/api/client'

/**
 * Admin Monitoring API 호출 · 티켓 S15P21E102-210.
 *
 * 계약은 티켓 S15P21E102-209의 `docs/be/admin-monitoring-api.md`다. 브라우저가
 * Prometheus를 직접 부르지 않고 Backend를 거치는 이유는 Prometheus·Grafana가 관리자망에만
 * 열려 있고, 사설 주소를 공개 번들에 넣을 수 없기 때문이다. **이 파일에도, 이 화면
 * 어디에도 Prometheus/Grafana 주소가 없다.** Quick Access가 여는 주소는
 * {@link MonitoringOverview.links}로 서버가 준다.
 *
 * 수치 필드가 `null`인 것과 `0`인 것은 다르다. `null`은 값을 얻지 못했다는 뜻이고 화면은
 * 숫자 대신 값 없음으로 그려야 한다. 그래서 타입에서 `null`을 지우거나 `?? 0`으로 채우지
 * 않는다 — 그 한 줄이 "측정했더니 0이었다"는 거짓을 만든다.
 */

/** 서버 한 대의 현재 지표. `instance`가 식별자, `role`이 topology config와 잇는 열쇠다. */
export interface ServerMetrics {
  instance: string
  role: string | null
  node: string | null
  host: string | null
  up: boolean
  cpuPercent: number | null
  cpuCores: number | null
  memoryPercent: number | null
  memoryUsedBytes: number | null
  memoryTotalBytes: number | null
  diskPercent: number | null
  diskUsedBytes: number | null
  diskTotalBytes: number | null
  networkReceiveBytesPerSecond: number | null
  networkTransmitBytesPerSecond: number | null
}

export interface MonitoringOverview {
  updatedAt: string
  prometheus: {
    reachable: boolean
    state: PrometheusState
    /** 미연결이면 `null`. `0`이 아니다 — 0은 "target이 하나도 없다"는 다른 사실이다. */
    targetsUp: number | null
    targetsTotal: number | null
    scrapeIntervalSeconds: number | null
  }
  servers: readonly ServerMetrics[]
  /**
   * Kafka 처리 현황 · 티켓 S15P21E102-261 Phase 1.
   *
   * `up`은 kafka-exporter 도달 여부. 붙어 있으면 topic 수·초당 유입 메시지·consumer lag
   * 합계가 실값으로 온다. exporter 시계열이 없으면 `up`이 `null`이고("아직 재보지 않았다"),
   * 값 필드도 `null`이다. `0`(실제로 0)과 구분해야 하므로 `?? 0`으로 채우지 않는다.
   */
  kafka: {
    up: boolean | null
    topicCount: number | null
    messagesInPerSecond: number | null
    consumerLagTotal: number | null
  }
  /**
   * HDFS 현황 · 티켓 S15P21E102-261 Phase 2.
   *
   * `up`은 NameNode /jmx 를 옮기는 json-exporter 도달 여부. 붙어 있으면 용량(사용/전체/
   * 잔여 바이트)·전체 Block·Under-replicated Block·DataNode Live/Dead 수가 실값으로 온다.
   * 미도달이면 `up`이 `null`이고 값 필드도 `null`이다(`0`과 구분).
   */
  hdfs: {
    up: boolean | null
    capacityUsedBytes: number | null
    capacityTotalBytes: number | null
    blocksTotal: number | null
    liveDataNodes: number | null
    deadDataNodes: number | null
    capacityRemainingBytes: number | null
    underReplicatedBlocks: number | null
  }
  /**
   * Spark 현황 · 티켓 S15P21E102-261 Phase 3.
   *
   * `up`은 Spark Master /json/ 을 옮기는 json-exporter 도달 여부. 붙어 있으면 살아 있는
   * Worker 수·Core(사용/전체)·Memory(사용/전체, MB)가 실값으로 온다. 미도달이면 `up`이
   * `null`이고 값 필드도 `null`이다.
   */
  spark: {
    up: boolean | null
    aliveWorkers: number | null
    coresTotal: number | null
    coresUsed: number | null
    memoryTotalMb: number | null
    memoryUsedMb: number | null
  }
  /**
   * DB 적재 현황 · 티켓 S15P21E102-261 Phase 4.
   *
   * 수집 파이프라인이 Postgres에 쌓은 것(기술 목록·기술 후보·분석 요청 건수). HDFS/Spark/
   * Kafka와 달리 Prometheus가 아니라 BE가 자기 DB를 직접 세어 준다(배치 산출물이라 scrape할
   * 장기 exporter가 없다). 개별 count가 `null`이면 세지 못한 것(`0`과 구분).
   */
  dataStore: {
    technologyCount: number | null
    technologyCandidateCount: number | null
    analysisJobCount: number | null
  }
  coverage: {
    hdfs: CoverageState
    spark: CoverageState
    collector: CoverageState
    kafkaBusiness: CoverageState
  }
  /** 서버 설정에서만 온다. 미설정이면 `null`이라 화면은 링크를 그리지 않는다. */
  links: { grafanaUrl: string | null; prometheusUrl: string | null }
}

/** 시계열로 조회할 수 있는 지표. BE가 허용하는 값만 있다. */
export type TimeseriesMetric = 'cpu' | 'memory' | 'network'

export interface MonitoringTimeseries {
  metric: TimeseriesMetric
  range: string
  stepSeconds: number
  unit: 'PERCENT' | 'BYTES_PER_SECOND'
  reachable: boolean
  state: PrometheusState
  series: readonly {
    instance: string
    role: string | null
    /** network의 `receive`/`transmit`. cpu·memory에서는 `null`. */
    direction: string | null
    points: readonly { at: string; value: number }[]
  }[]
}

const BASE = '/admin/monitoring'

export function fetchMonitoringOverview(): Promise<MonitoringOverview> {
  return get<MonitoringOverview>(`${BASE}/overview`)
}

/**
 * `range`를 보내지 않는다. BE 기본값이 확정 디자인의 "최근 60분 · 5분 간격"이고, 화면에
 * 범위 선택 컨트롤이 없다. 컨트롤이 생기면 그때 인자로 받는다.
 */
export function fetchMonitoringTimeseries(
  metric: TimeseriesMetric,
): Promise<MonitoringTimeseries> {
  return get<MonitoringTimeseries>(`${BASE}/timeseries?metric=${metric}`)
}
