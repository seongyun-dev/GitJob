package com.example.git_job.monitoring.service;

import com.example.git_job.monitoring.client.PrometheusClient;
import com.example.git_job.monitoring.client.PrometheusUnavailableException;
import com.example.git_job.monitoring.config.MonitoringProperties;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.Coverage;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.KafkaStatus;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.Links;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.PrometheusStatus;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.ServerMetrics;
import com.example.git_job.monitoring.controller.dto.MonitoringTimeseriesResponse;
import com.example.git_job.monitoring.controller.dto.PrometheusState;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Admin Monitoring 화면이 쓰는 값을 Prometheus에서 읽어 화면 모양으로 바꾼다
 * (S15P21E102-209).
 *
 * <p>이 클래스는 지표를 계산하지 않는다. 비율과 rate는 Prometheus가 계산하고 여기서는
 * 라벨로 묶어 서버 단위 레코드로 옮긴다. 같은 값을 두 곳에서 계산하면 대시보드와 화면의
 * 숫자가 갈라지고, 그때 어느 쪽이 맞는지 알 방법이 없다.</p>
 *
 * <p>Prometheus에서 값을 얻지 못하면 예외를 올리지 않고 상태를 내린다. 모니터링이 끊긴
 * 것은 요청 실패가 아니라 운영자가 봐야 하는 사실이고, 500을 던지면 화면은 그것을
 * "서버가 죽었다"와 구분할 수 없다. 대신 실패를 성공으로 바꾸지도 않는다 —
 * {@code reachable=false}와 {@link PrometheusState}가 실패를 명시적으로 남기고, 값 자리는
 * 0이 아니라 {@code null}로 비워 둔다.</p>
 *
 * <p>서버 목록은 {@code up} 질의 결과에서 나온다. 이 코드는 서버가 몇 대인지, 어떤 role이
 * 있는지 알지 않는다. 그래서 EC2가 2대에서 3대가 되어도(S15P21E102-207) 여기는 바뀌지 않고
 * Prometheus target 등록만 바뀐다.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MonitoringService {

    private static final String INSTANCE = "instance";
    private static final String ROLE = "role";
    private static final String NODE = "node";
    private static final String HOST = "host";

    private final PrometheusClient prometheus;
    private final MonitoringQueries queries;
    private final MonitoringProperties properties;

    public MonitoringOverviewResponse overview() {
        if (!properties.isPrometheusConfigured()) {
            log.debug("Prometheus 주소가 설정되지 않아 overview를 NOT_CONFIGURED로 반환한다");
            return disconnectedOverview(PrometheusState.NOT_CONFIGURED);
        }

        try {
            return collectOverview();
        } catch (PrometheusUnavailableException e) {
            // 주소는 로그에 남기지 않는다. 필요한 것은 실패 사실과 종류다.
            log.warn("Prometheus overview 수집 실패 (state={}): {}", e.getState(), e.getMessage());
            return disconnectedOverview(e.getState());
        }
    }

    public MonitoringTimeseriesResponse timeseries(MetricKind metric, TimeRange range) {
        int stepSeconds = (int) range.step().toSeconds();

        if (!properties.isPrometheusConfigured()) {
            return MonitoringTimeseriesResponse.disconnected(
                    metric.wireName(), range.wireName(), stepSeconds, metric.unit(),
                    PrometheusState.NOT_CONFIGURED);
        }

        try {
            return collectTimeseries(metric, range, stepSeconds);
        } catch (PrometheusUnavailableException e) {
            log.warn("Prometheus timeseries 수집 실패 (metric={}, state={}): {}",
                    metric.wireName(), e.getState(), e.getMessage());
            return MonitoringTimeseriesResponse.disconnected(
                    metric.wireName(), range.wireName(), stepSeconds, metric.unit(), e.getState());
        }
    }

    private MonitoringOverviewResponse collectOverview() {
        PrometheusClient.TargetHealth health = prometheus.targets();

        List<PrometheusClient.Sample> nodes = prometheus.instant(queries.nodeUp());
        Map<String, Double> cpu = byInstance(prometheus.instant(queries.cpuPercent()));
        Map<String, Double> cores = byInstance(prometheus.instant(queries.cpuCores()));
        Map<String, Double> memory = byInstance(prometheus.instant(queries.memoryPercent()));
        Map<String, Double> memoryTotal = byInstance(prometheus.instant(queries.memoryTotalBytes()));
        Map<String, Double> memoryAvailable =
                byInstance(prometheus.instant(queries.memoryAvailableBytes()));
        Map<String, Double> diskPercent = byInstance(prometheus.instant(queries.diskPercent()));
        Map<String, Double> diskTotal = byInstance(prometheus.instant(queries.diskTotalBytes()));
        Map<String, Double> diskAvailable =
                byInstance(prometheus.instant(queries.diskAvailableBytes()));
        Map<String, Double> netReceive =
                byInstance(prometheus.instant(queries.networkReceiveBytesPerSecond()));
        Map<String, Double> netTransmit =
                byInstance(prometheus.instant(queries.networkTransmitBytesPerSecond()));

        List<ServerMetrics> servers = new ArrayList<>();
        for (PrometheusClient.Sample node : nodes) {
            String instance = node.label(INSTANCE);
            servers.add(new ServerMetrics(
                    instance,
                    emptyToNull(node.label(ROLE)),
                    emptyToNull(node.label(NODE)),
                    emptyToNull(node.label(HOST)),
                    node.value() > 0,
                    cpu.get(instance),
                    toInteger(cores.get(instance)),
                    memory.get(instance),
                    usedBytes(memoryTotal.get(instance), memoryAvailable.get(instance)),
                    toLong(memoryTotal.get(instance)),
                    diskPercent.get(instance),
                    usedBytes(diskTotal.get(instance), diskAvailable.get(instance)),
                    toLong(diskTotal.get(instance)),
                    netReceive.get(instance),
                    netTransmit.get(instance)));
        }
        // 표의 행 순서가 새로고침마다 바뀌면 값을 눈으로 비교할 수 없다.
        servers.sort(Comparator
                .comparing((ServerMetrics server) -> server.role() == null ? "" : server.role())
                .thenComparing(ServerMetrics::instance));

        return new MonitoringOverviewResponse(
                Instant.now(),
                PrometheusStatus.connected(
                        health.up(),
                        health.total(),
                        (int) properties.getPrometheusScrapeInterval().toSeconds()),
                List.copyOf(servers),
                kafkaStatus(),
                Coverage.current(),
                links());
    }

    private MonitoringTimeseriesResponse collectTimeseries(
            MetricKind metric, TimeRange range, int stepSeconds
    ) {
        Instant end = Instant.now();
        Instant start = end.minus(range.window());

        List<MonitoringTimeseriesResponse.Series> out = new ArrayList<>();
        for (DirectedQuery directed : directedQueries(metric)) {
            for (PrometheusClient.Series series : prometheus.range(
                    directed.query(), start, end, range.step())) {
                out.add(new MonitoringTimeseriesResponse.Series(
                        series.label(INSTANCE),
                        emptyToNull(series.label(ROLE)),
                        directed.direction(),
                        series.points().stream()
                                .map(point -> new MonitoringTimeseriesResponse.Point(
                                        point.at(), point.value()))
                                .toList()));
            }
        }
        out.sort(Comparator
                .comparing(MonitoringTimeseriesResponse.Series::instance)
                .thenComparing(series -> series.direction() == null ? "" : series.direction()));

        return MonitoringTimeseriesResponse.connected(
                metric.wireName(), range.wireName(), stepSeconds, metric.unit(), List.copyOf(out));
    }

    /** 방향이 있는 지표는 질의가 둘이다. 방향 이름은 응답의 범례가 된다. */
    private record DirectedQuery(String direction, String query) {
    }

    private List<DirectedQuery> directedQueries(MetricKind metric) {
        return switch (metric) {
            case CPU -> List.of(new DirectedQuery(null, queries.cpuPercent()));
            case MEMORY -> List.of(new DirectedQuery(null, queries.memoryPercent()));
            case NETWORK -> List.of(
                    new DirectedQuery("receive", queries.networkReceiveBytesPerSecond()),
                    new DirectedQuery("transmit", queries.networkTransmitBytesPerSecond()));
        };
    }

    /**
     * Kafka exporter 도달 여부. exporter가 없으면 시계열이 없고, 그때는 {@code false}가
     * 아니라 {@code null}이다. "브로커가 죽었다"와 "아직 재보지 않았다"는 다른 사실이다.
     */
    private KafkaStatus kafkaStatus() {
        List<PrometheusClient.Sample> samples = prometheus.instant(queries.kafkaUp());
        if (samples.isEmpty()) {
            return KafkaStatus.unknown();
        }
        return new KafkaStatus(samples.get(0).value() > 0);
    }

    private MonitoringOverviewResponse disconnectedOverview(PrometheusState state) {
        return new MonitoringOverviewResponse(
                Instant.now(),
                PrometheusStatus.disconnected(state),
                List.of(),
                KafkaStatus.unknown(),
                Coverage.current(),
                links());
    }

    private Links links() {
        return new Links(properties.grafanaLinkOrNull(), properties.prometheusLinkOrNull());
    }

    /**
     * instance 라벨로 묶는다. 라벨이 없는 샘플은 어느 서버의 값인지 알 수 없어 버린다.
     * 같은 instance가 두 번 오면(파일시스템이 여럿인 경우 등) 첫 값을 쓴다.
     */
    private static Map<String, Double> byInstance(List<PrometheusClient.Sample> samples) {
        Map<String, Double> byInstance = new HashMap<>();
        for (PrometheusClient.Sample sample : samples) {
            String instance = sample.label(INSTANCE);
            if (!instance.isEmpty()) {
                byInstance.putIfAbsent(instance, sample.value());
            }
        }
        return byInstance;
    }

    /** 둘 중 하나라도 없으면 사용량을 만들지 않는다. */
    private static Long usedBytes(Double total, Double available) {
        if (total == null || available == null) {
            return null;
        }
        return Math.max(0L, Math.round(total - available));
    }

    private static Long toLong(Double value) {
        return value == null ? null : Math.round(value);
    }

    private static Integer toInteger(Double value) {
        return value == null ? null : (int) Math.round(value);
    }

    private static String emptyToNull(String label) {
        return label.isEmpty() ? null : label;
    }
}
