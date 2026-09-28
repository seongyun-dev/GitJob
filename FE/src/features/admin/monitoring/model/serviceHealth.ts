import type { PrometheusState } from './monitoringState'

/**
 * 서비스 칩 하나의 상태를 판정할 때 쓸 수 있는 근거 · 티켓 S15P21E102-210, 확장 -319.
 *
 * 여기 있는 것이 곧 "지금 수집되고 있는 것"이다. 없는 필드는 만들지 않는다 — 판정할
 * 근거가 없는 서비스는 화면에서 회색으로 남는 것이 정확하다.
 */
export interface ServiceHealthEvidence {
  prometheusState: PrometheusState
  /** kafka-exporter 도달 여부. */
  kafkaUp: boolean | null
  /** NameNode `/jmx` 를 옮기는 json-exporter 도달 여부. */
  hdfsUp: boolean | null
  /** Spark Master `/json/` 을 옮기는 json-exporter 도달 여부. */
  sparkUp: boolean | null
  /** 살아 있는 DataNode 수. 아직 재보지 않았으면 `null` (`0` 과 다르다). */
  liveDataNodes: number | null
  /** 살아 있는 Spark Worker 수. 아직 재보지 않았으면 `null` (`0` 과 다르다). */
  aliveWorkers: number | null
  /** BE 프로세스 자신의 Actuator 집계(DB·디스크 contributor 포함) · 티켓 -321. */
  backendUp: boolean | null
  /** Grafana 가 스스로 내는 `/metrics` 의 scrape 도달 여부 · 티켓 -321. */
  grafanaUp: boolean | null
}

/**
 * 살아 있는 개수를 칩 상태로 옮긴다 · 티켓 S15P21E102-319.
 *
 * `null` 은 exporter 가 아직 답하지 않은 것이라 모른다. `0` 은 다르다 — 재봤는데 살아
 * 있는 것이 없다는 뜻이고, 운영 화면이 가장 먼저 말해야 하는 사실이다. 둘을 같은
 * 회색으로 접으면 전멸을 "수집 전"으로 감춘다.
 *
 * 하나만 살아 있어도 정상으로 본다. 그 계층이 동작 중인지가 이 칩의 질문이고, 몇 개가
 * 빠졌는지는 Data Platform 카드의 `DataNode N개 · M down` 이 이미 말한다.
 */
function liveCountState(count: number | null): boolean | null {
  return count === null ? null : count > 0
}

/**
 * 서비스별 상태 · 티켓 S15P21E102-210, 확장 -319.
 *
 * <h2>왜 여기 한 곳인가</h2>
 *
 * `service id → monitoring source → status` 를 한 표로 둔다. 칩 컴포넌트마다
 * `if (metric > 0)` 을 흩뿌리면 어떤 서비스가 무슨 근거로 초록인지 화면을 다 열어 봐야
 * 알 수 있고, 근거 없는 초록불이 슬며시 생긴다.
 *
 * <h2>호스트 상태를 프로세스 상태로 쓰지 않는다</h2>
 *
 * node-exporter 두 개가 UP 이라는 것은 두 **호스트**가 살아 있다는 뜻이다. 그 안의 Redis ·
 * Grafana · Collector · C1 Archiver 가 각각 살아 있다는 뜻이 아니다. 호스트 UP 을 자식
 * 서비스에 물려주면 죽은 컨테이너가 초록으로 보이고, 그것은 운영 화면에서 가장 나쁜
 * 거짓이다.
 *
 * <h2>Backend 와 Grafana · 티켓 -321</h2>
 *
 * 남아 있던 다섯 칩 중 둘에 근거가 생겼다. `overview.services` 가 준다 — Backend 는 BE
 * 프로세스 자신의 Actuator 집계(DB·디스크 contributor 가 실제로 포함된다), Grafana 는
 * Grafana 가 스스로 내는 `/metrics` 의 scrape 도달 여부다. 둘은 같은 점으로 그려지지만
 * 근거가 같지 않다.
 *
 * <h2>아직 근거가 없는 것들</h2>
 *
 * Redis · Collector · C1 Archiver 는 여전히 `null` 이고 회색으로 남는다. 각각 exporter
 * 추가 · 수집 컨테이너 재기동 · json-exporter 규칙 실행 검증이 남아 후속 작업으로
 * 분리했다. 붙이지 않은 것을 죽은 것으로 바꿔 말하지 않는다.
 *
 * `coverage.collector` 는 여전히 쓰지 않는다. 그것은 Data Platform 의 DB 집계 상태이지
 * Collector 컨테이너의 health 가 아니다.
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
    case 'hdfs-datanode':
      return liveCountState(evidence.liveDataNodes)
    case 'spark-worker':
      return liveCountState(evidence.aliveWorkers)
    case 'backend':
      return evidence.backendUp
    case 'grafana':
      return evidence.grafanaUp
    default:
      // Redis · Collector · C1 Archiver 는 아직 개별 source 가 없다. 호스트나 집계 지표로
      // 대신 칠하지 않는다.
      return null
  }
}
