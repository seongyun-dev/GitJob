package com.example.git_job.monitoring.controller.dto;

import java.time.Instant;
import java.util.List;

/**
 * Admin Monitoring 화면의 현재값 한 묶음 (S15P21E102-209).
 *
 * <p>엔드포인트를 {@code /servers}·{@code /targets}로 쪼개지 않았다. 화면이 한 번에 다
 * 그리는 값이라 나누면 요청만 늘고, 화면 어느 부분은 갱신됐고 어느 부분은 아닌 상태가
 * 생긴다. Server Detail 표와 Infrastructure Map의 상태 점은 모두 {@link #servers()}에서 나온다.</p>
 *
 * <p>수치가 {@code null}인 것과 0인 것은 다르다. {@code null}은 그 값을 아직 얻지 못했다는
 * 뜻이고, 화면은 숫자 대신 값 없음으로 그려야 한다. 0으로 채우면 "측정했더니 0"이라는
 * 거짓이 된다.</p>
 */
public record MonitoringOverviewResponse(
        Instant updatedAt,
        PrometheusStatus prometheus,
        List<ServerMetrics> servers,
        KafkaStatus kafka,
        Coverage coverage,
        Links links
) {

    /**
     * Prometheus 자체의 상태.
     *
     * <p>실패도 200으로 내린다. 모니터링이 끊긴 것은 요청 실패가 아니라 운영자가 봐야 하는
     * 사실이고, 500으로 던지면 화면은 "모니터링이 끊겼다"와 "서버가 죽었다"를 구분할 수
     * 없다.</p>
     *
     * <p>{@code reachable} 하나로 끝내지 않고 {@link #state}를 함께 싣는다. 주소가 없는
     * 것과 닿지 않는 것과 응답이 이상한 것은 고칠 사람이 다르다.</p>
     *
     * <p>연결되지 않았으면 {@code targetsUp}·{@code targetsTotal}은 {@code null}이다.
     * 0으로 채우면 "target이 하나도 없다"는 다른 사실이 된다.</p>
     */
    public record PrometheusStatus(
            boolean reachable,
            PrometheusState state,
            Integer targetsUp,
            Integer targetsTotal,
            Integer scrapeIntervalSeconds
    ) {
        public static PrometheusStatus connected(int up, int total, int scrapeIntervalSeconds) {
            return new PrometheusStatus(
                    true, PrometheusState.CONNECTED, up, total, scrapeIntervalSeconds);
        }

        /** {@code state}는 CONNECTED가 아닌 값이어야 한다. */
        public static PrometheusStatus disconnected(PrometheusState state) {
            return new PrometheusStatus(false, state, null, null, null);
        }
    }

    /**
     * 서버 한 대의 현재 지표.
     *
     * <p>{@code instance}가 식별자다. {@code role}·{@code node}·{@code host}는 Prometheus
     * target 라벨에서 그대로 온다. 이 목록의 길이가 곧 서버 대수이며, 서버가 늘면 라벨만
     * 추가되고 이 계약은 바뀌지 않는다.</p>
     */
    public record ServerMetrics(
            String instance,
            String role,
            String node,
            String host,
            boolean up,
            Double cpuPercent,
            /** 확정 디자인 Server Detail의 "4 vCPU". */
            Integer cpuCores,
            Double memoryPercent,
            /** "6.6 / 16 GB"를 그리려면 비율만으로는 부족하다. */
            Long memoryUsedBytes,
            Long memoryTotalBytes,
            Double diskPercent,
            Long diskUsedBytes,
            Long diskTotalBytes,
            Double networkReceiveBytesPerSecond,
            Double networkTransmitBytesPerSecond
    ) {
    }

    /**
     * Kafka exporter 도달 여부만 본다. topic 처리량·consumer lag은 이 화면의 범위가 아니라
     * 대시보드가 담당하고, 비즈니스 지표는 {@link Coverage}에서 미수집으로 표시된다.
     */
    public record KafkaStatus(Boolean up) {
        public static KafkaStatus unknown() {
            return new KafkaStatus(null);
        }
    }

    /**
     * 어떤 범위가 실제로 수집되고 있는지.
     *
     * <p>이 필드가 있는 이유는 화면이 "값이 0"과 "아직 수집하지 않음"을 구분해야 하기
     * 때문이다. HDFS logical capacity, Spark application/executor, Collector business
     * counter, Kafka topic business 지표는 Prometheus exposition endpoint나 exporter가
     * 아직 없다(S15P21E102-205 문서 3장). 값을 만들지 않고 상태만 내린다.</p>
     */
    public record Coverage(
            CoverageState hdfs,
            CoverageState spark,
            CoverageState collector,
            CoverageState kafkaBusiness
    ) {
        /** 현재 상태. exporter가 붙으면 해당 필드만 COLLECTED로 바뀐다. */
        public static Coverage current() {
            return new Coverage(
                    CoverageState.NOT_COLLECTED,
                    CoverageState.NOT_COLLECTED,
                    CoverageState.NOT_COLLECTED,
                    CoverageState.NOT_COLLECTED);
        }
    }

    /**
     * Grafana·Prometheus 상세 화면 링크.
     *
     * <p>서버 설정에서만 온다. 관리자망 주소를 FE 번들에 넣지 않기 위해서이고,
     * 미설정이면 {@code null}이라 화면은 눌러도 아무 일 없는 링크를 그리지 않는다.</p>
     */
    public record Links(String grafanaUrl, String prometheusUrl) {
    }
}
