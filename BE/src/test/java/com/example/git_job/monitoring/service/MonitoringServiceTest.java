package com.example.git_job.monitoring.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.monitoring.client.PrometheusClient;
import com.example.git_job.monitoring.client.PrometheusUnavailableException;
import com.example.git_job.monitoring.config.MonitoringProperties;
import com.example.git_job.monitoring.controller.dto.CoverageState;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.DataStoreStatus;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.ServerMetrics;
import com.example.git_job.monitoring.controller.dto.MonitoringTimeseriesResponse;
import com.example.git_job.monitoring.controller.dto.PrometheusState;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 화면이 실제로 받는 값을 고정한다 (S15P21E102-209).
 *
 * <p>이 테스트가 지키려는 것은 숫자의 정확성이 아니라 <strong>없는 값을 만들지 않는다</strong>는
 * 계약이다. 모니터링 화면에서 가장 위험한 버그는 예외가 아니라 조용한 0이다. CPU를 못
 * 읽었는데 0%가 뜨면 운영자는 서버가 한가하다고 읽고, 수집이 끊긴 것을 모른다.</p>
 *
 * <p>Prometheus는 mock이다. 실제 호출은 단위 테스트가 아니라 Runtime 검증에서 한다
 * (PROJECT_GUIDE 10.9).</p>
 */
class MonitoringServiceTest {

    private static final String SERVICE = "10.0.0.1:9100";
    private static final String DATA = "10.0.0.2:9100";

    private PrometheusClient prometheus;
    private MonitoringQueries queries;
    private DataStoreMetrics dataStoreMetrics;

    @BeforeEach
    void setUp() {
        prometheus = mock(PrometheusClient.class);
        dataStoreMetrics = mock(DataStoreMetrics.class);
        // 기본은 DB 미도달(모두 null) — 개별 테스트가 필요하면 실수치로 덮어쓴다.
        when(dataStoreMetrics.current()).thenReturn(DataStoreStatus.unknown());
        queries = new MonitoringQueries(configured());
    }

    private static MonitoringProperties configured() {
        return new MonitoringProperties(
                "http://prometheus:9090",
                Duration.ofSeconds(3),
                Duration.ofSeconds(15),
                "gitjob",
                "https://grafana.example.internal",
                "https://prometheus.example.internal");
    }

    private static MonitoringProperties notConfigured() {
        return new MonitoringProperties(
                "",
                Duration.ofSeconds(3),
                Duration.ofSeconds(15),
                "gitjob",
                "https://grafana.example.internal",
                "");
    }

    private MonitoringService service(MonitoringProperties properties) {
        return new MonitoringService(
                prometheus, new MonitoringQueries(properties), properties, dataStoreMetrics);
    }

    private static PrometheusClient.Sample node(String instance, String role, double up) {
        return new PrometheusClient.Sample(
                Map.of("instance", instance, "role", role, "node", role + "-1",
                        "host", role + "-server"),
                up);
    }

    private static PrometheusClient.Sample value(String instance, double v) {
        return new PrometheusClient.Sample(Map.of("instance", instance), v);
    }

    @Test
    @DisplayName("수집된 지표는 서버별로 실제 값이 실린다")
    void collectedMetricsLandOnTheServerTheyBelongTo() {
        when(prometheus.targets()).thenReturn(new PrometheusClient.TargetHealth(6, 6));
        when(prometheus.instant(queries.nodeUp()))
                .thenReturn(List.of(node(DATA, "data", 1), node(SERVICE, "service", 1)));
        when(prometheus.instant(queries.cpuPercent()))
                .thenReturn(List.of(value(SERVICE, 23.4), value(DATA, 37.1)));
        when(prometheus.instant(queries.cpuCores()))
                .thenReturn(List.of(value(SERVICE, 4), value(DATA, 4)));
        when(prometheus.instant(queries.memoryPercent()))
                .thenReturn(List.of(value(SERVICE, 41.0), value(DATA, 62.0)));
        when(prometheus.instant(queries.memoryTotalBytes()))
                .thenReturn(List.of(value(SERVICE, 16_000_000_000d)));
        when(prometheus.instant(queries.memoryAvailableBytes()))
                .thenReturn(List.of(value(SERVICE, 9_400_000_000d)));
        when(prometheus.instant(queries.diskPercent()))
                .thenReturn(List.of(value(SERVICE, 54.0)));
        when(prometheus.instant(queries.diskTotalBytes()))
                .thenReturn(List.of(value(SERVICE, 400_000_000_000d)));
        when(prometheus.instant(queries.diskAvailableBytes()))
                .thenReturn(List.of(value(SERVICE, 184_000_000_000d)));
        when(prometheus.instant(queries.networkReceiveBytesPerSecond()))
                .thenReturn(List.of(value(SERVICE, 4_100_000d)));
        when(prometheus.instant(queries.networkTransmitBytesPerSecond()))
                .thenReturn(List.of(value(SERVICE, 2_100_000d)));
        when(prometheus.instant(queries.kafkaUp())).thenReturn(List.of(value(SERVICE, 1)));

        MonitoringOverviewResponse overview = service(configured()).overview();

        assertThat(overview.prometheus().reachable()).isTrue();
        assertThat(overview.prometheus().state()).isEqualTo(PrometheusState.CONNECTED);
        assertThat(overview.prometheus().targetsUp()).isEqualTo(6);
        assertThat(overview.prometheus().targetsTotal()).isEqualTo(6);
        assertThat(overview.prometheus().scrapeIntervalSeconds()).isEqualTo(15);
        assertThat(overview.kafka().up()).isTrue();

        // role 순으로 정렬한다. 새로고침마다 행이 뒤바뀌면 값을 눈으로 비교할 수 없다.
        assertThat(overview.servers()).extracting(ServerMetrics::instance)
                .containsExactly(DATA, SERVICE);

        ServerMetrics serviceServer = overview.servers().get(1);
        assertThat(serviceServer.role()).isEqualTo("service");
        assertThat(serviceServer.node()).isEqualTo("service-1");
        assertThat(serviceServer.host()).isEqualTo("service-server");
        assertThat(serviceServer.up()).isTrue();
        assertThat(serviceServer.cpuPercent()).isEqualTo(23.4);
        assertThat(serviceServer.cpuCores()).isEqualTo(4);
        assertThat(serviceServer.memoryPercent()).isEqualTo(41.0);
        assertThat(serviceServer.memoryTotalBytes()).isEqualTo(16_000_000_000L);
        assertThat(serviceServer.memoryUsedBytes()).isEqualTo(6_600_000_000L);
        assertThat(serviceServer.diskUsedBytes()).isEqualTo(216_000_000_000L);
        assertThat(serviceServer.diskTotalBytes()).isEqualTo(400_000_000_000L);
        assertThat(serviceServer.networkReceiveBytesPerSecond()).isEqualTo(4_100_000d);
        assertThat(serviceServer.networkTransmitBytesPerSecond()).isEqualTo(2_100_000d);
    }

    @Test
    @DisplayName("못 읽은 값은 0이 아니라 비운다")
    void aMetricWeCouldNotReadStaysEmptyInsteadOfBecomingZero() {
        when(prometheus.targets()).thenReturn(new PrometheusClient.TargetHealth(3, 6));
        // cpu·memory·disk·network·kafka 질의는 모두 빈 결과를 준다. target은 살아 있지만
        // 시계열이 없는 상황 — scrape가 방금 시작됐거나 collector가 꺼진 경우다.
        when(prometheus.instant(anyString())).thenReturn(List.of());
        when(prometheus.instant(queries.nodeUp()))
                .thenReturn(List.of(node(DATA, "data", 0)));

        MonitoringOverviewResponse overview = service(configured()).overview();

        ServerMetrics dataServer = overview.servers().get(0);
        assertThat(dataServer.up()).isFalse();
        assertThat(dataServer.cpuPercent()).isNull();
        assertThat(dataServer.cpuCores()).isNull();
        assertThat(dataServer.memoryPercent()).isNull();
        assertThat(dataServer.memoryUsedBytes()).isNull();
        assertThat(dataServer.diskPercent()).isNull();
        assertThat(dataServer.diskUsedBytes()).isNull();
        assertThat(dataServer.networkReceiveBytesPerSecond()).isNull();
        // exporter 시계열이 없으면 "죽었다"가 아니라 "모른다"다.
        assertThat(overview.kafka().up()).isNull();
    }

    @Test
    @DisplayName("총량과 잔여량 중 하나만 있으면 사용량을 만들지 않는다")
    void usedBytesNeedsBothSidesOfTheSubtraction() {
        when(prometheus.targets()).thenReturn(new PrometheusClient.TargetHealth(6, 6));
        when(prometheus.instant(anyString())).thenReturn(List.of());
        when(prometheus.instant(queries.nodeUp()))
                .thenReturn(List.of(node(SERVICE, "service", 1)));
        when(prometheus.instant(queries.diskTotalBytes()))
                .thenReturn(List.of(value(SERVICE, 400_000_000_000d)));

        MonitoringOverviewResponse overview = service(configured()).overview();

        ServerMetrics server = overview.servers().get(0);
        assertThat(server.diskTotalBytes()).isEqualTo(400_000_000_000L);
        assertThat(server.diskUsedBytes()).isNull();
    }

    @Test
    @DisplayName("instance 라벨이 없는 샘플은 어느 서버 값인지 알 수 없어 버린다")
    void aSampleWithoutAnInstanceLabelIsDropped() {
        when(prometheus.targets()).thenReturn(new PrometheusClient.TargetHealth(6, 6));
        when(prometheus.instant(anyString())).thenReturn(List.of());
        when(prometheus.instant(queries.nodeUp()))
                .thenReturn(List.of(node(SERVICE, "service", 1)));
        when(prometheus.instant(queries.cpuPercent()))
                .thenReturn(List.of(new PrometheusClient.Sample(Map.of("job", "node-exporter"), 99.9)));

        MonitoringOverviewResponse overview = service(configured()).overview();

        assertThat(overview.servers().get(0).cpuPercent()).isNull();
    }

    @Test
    @DisplayName("주소가 없으면 호출하지 않고 NOT_CONFIGURED를 내린다")
    void withoutAnAddressWeDoNotCallAndWeSayWhy() {
        MonitoringOverviewResponse overview = service(notConfigured()).overview();

        assertThat(overview.prometheus().reachable()).isFalse();
        assertThat(overview.prometheus().state()).isEqualTo(PrometheusState.NOT_CONFIGURED);
        assertThat(overview.prometheus().targetsUp()).isNull();
        assertThat(overview.prometheus().targetsTotal()).isNull();
        assertThat(overview.servers()).isEmpty();
        verify(prometheus, never()).instant(anyString());
        verify(prometheus, never()).targets();

        // 링크는 Prometheus와 무관하게 설정에서 온다. 미설정 링크는 null이어야 한다.
        assertThat(overview.links().grafanaUrl()).isEqualTo("https://grafana.example.internal");
        assertThat(overview.links().prometheusUrl()).isNull();
    }

    @Test
    @DisplayName("도달 실패와 응답 이상을 다른 상태로 구분한다")
    void unreachableAndInvalidResponseAreDifferentFacts() {
        when(prometheus.targets())
                .thenThrow(PrometheusUnavailableException.unreachable("연결 실패", null));
        assertThat(service(configured()).overview().prometheus().state())
                .isEqualTo(PrometheusState.UNREACHABLE);

        PrometheusClient other = mock(PrometheusClient.class);
        when(other.targets())
                .thenThrow(PrometheusUnavailableException.invalidResponse("형식 이상"));
        MonitoringProperties properties = configured();
        MonitoringOverviewResponse overview = new MonitoringService(
                other, new MonitoringQueries(properties), properties, dataStoreMetrics).overview();
        assertThat(overview.prometheus().state()).isEqualTo(PrometheusState.INVALID_RESPONSE);
        assertThat(overview.servers()).isEmpty();
    }

    @Test
    @DisplayName("미수집 범위는 수치가 아니라 상태로 내려간다")
    void whatWeDoNotCollectIsReportedAsStateNotAsANumber() {
        MonitoringOverviewResponse overview = service(notConfigured()).overview();

        assertThat(overview.coverage().hdfs()).isEqualTo(CoverageState.NOT_COLLECTED);
        assertThat(overview.coverage().spark()).isEqualTo(CoverageState.NOT_COLLECTED);
        assertThat(overview.coverage().collector()).isEqualTo(CoverageState.NOT_COLLECTED);
        assertThat(overview.coverage().kafkaBusiness()).isEqualTo(CoverageState.NOT_COLLECTED);
    }

    @Test
    @DisplayName("kafka-exporter가 붙으면 kafkaBusiness가 COLLECTED로 실지표를 싣는다")
    void kafkaMetricsBecomeCollectedWhenExporterIsUp() {
        when(prometheus.targets()).thenReturn(new PrometheusClient.TargetHealth(6, 6));
        when(prometheus.instant(anyString())).thenReturn(List.of());
        when(prometheus.instant(queries.nodeUp()))
                .thenReturn(List.of(node(SERVICE, "service", 1)));
        when(prometheus.instant(queries.kafkaUp())).thenReturn(List.of(value(SERVICE, 1)));
        when(prometheus.instant(queries.kafkaTopicCount())).thenReturn(List.of(value(SERVICE, 10)));
        when(prometheus.instant(queries.kafkaMessagesInPerSecond()))
                .thenReturn(List.of(value(SERVICE, 0.5)));
        when(prometheus.instant(queries.kafkaConsumerLagTotal()))
                .thenReturn(List.of(value(SERVICE, 0)));

        MonitoringOverviewResponse overview = service(configured()).overview();

        assertThat(overview.kafka().up()).isTrue();
        assertThat(overview.kafka().topicCount()).isEqualTo(10);
        assertThat(overview.kafka().messagesInPerSecond()).isEqualTo(0.5);
        assertThat(overview.kafka().consumerLagTotal()).isEqualTo(0L);
        assertThat(overview.coverage().kafkaBusiness()).isEqualTo(CoverageState.COLLECTED);
        // 나머지 범위는 exporter가 없어 그대로 NOT_COLLECTED다.
        assertThat(overview.coverage().hdfs()).isEqualTo(CoverageState.NOT_COLLECTED);
    }

    @Test
    @DisplayName("kafka-exporter가 없으면 kafkaBusiness는 NOT_COLLECTED, 값은 비운다")
    void kafkaStaysNotCollectedWhenExporterIsAbsent() {
        when(prometheus.targets()).thenReturn(new PrometheusClient.TargetHealth(6, 6));
        when(prometheus.instant(anyString())).thenReturn(List.of());
        when(prometheus.instant(queries.nodeUp()))
                .thenReturn(List.of(node(SERVICE, "service", 1)));
        // kafkaUp 결과가 비어 있음 = exporter 미도달. 값을 만들지 않고 상태만 내린다.

        MonitoringOverviewResponse overview = service(configured()).overview();

        assertThat(overview.kafka().up()).isNull();
        assertThat(overview.kafka().topicCount()).isNull();
        assertThat(overview.kafka().consumerLagTotal()).isNull();
        assertThat(overview.coverage().kafkaBusiness()).isEqualTo(CoverageState.NOT_COLLECTED);
    }

    @Test
    @DisplayName("json-exporter가 붙으면 hdfs가 COLLECTED로 실지표를 싣는다")
    void hdfsMetricsBecomeCollectedWhenExporterIsUp() {
        when(prometheus.targets()).thenReturn(new PrometheusClient.TargetHealth(6, 6));
        when(prometheus.instant(anyString())).thenReturn(List.of());
        when(prometheus.instant(queries.nodeUp()))
                .thenReturn(List.of(node(SERVICE, "service", 1)));
        when(prometheus.instant(queries.hdfsUp()))
                .thenReturn(List.of(value("hdfs-namenode", 1)));
        when(prometheus.instant(queries.hdfsCapacityUsedBytes()))
                .thenReturn(List.of(value("hdfs-namenode", 86016)));
        when(prometheus.instant(queries.hdfsCapacityTotalBytes()))
                .thenReturn(List.of(value("hdfs-namenode", 3_243_303_530_496d)));
        when(prometheus.instant(queries.hdfsCapacityRemainingBytes()))
                .thenReturn(List.of(value("hdfs-namenode", 3_243_303_444_480d)));
        when(prometheus.instant(queries.hdfsBlocksTotal()))
                .thenReturn(List.of(value("hdfs-namenode", 0)));
        when(prometheus.instant(queries.hdfsUnderReplicatedBlocks()))
                .thenReturn(List.of(value("hdfs-namenode", 2)));
        when(prometheus.instant(queries.hdfsLiveDataNodes()))
                .thenReturn(List.of(value("hdfs-namenode", 3)));
        when(prometheus.instant(queries.hdfsDeadDataNodes()))
                .thenReturn(List.of(value("hdfs-namenode", 0)));

        MonitoringOverviewResponse overview = service(configured()).overview();

        assertThat(overview.hdfs().up()).isTrue();
        assertThat(overview.hdfs().capacityUsedBytes()).isEqualTo(86016L);
        assertThat(overview.hdfs().capacityTotalBytes()).isEqualTo(3_243_303_530_496L);
        assertThat(overview.hdfs().capacityRemainingBytes()).isEqualTo(3_243_303_444_480L);
        assertThat(overview.hdfs().blocksTotal()).isEqualTo(0L);
        assertThat(overview.hdfs().underReplicatedBlocks()).isEqualTo(2L);
        assertThat(overview.hdfs().liveDataNodes()).isEqualTo(3);
        assertThat(overview.hdfs().deadDataNodes()).isEqualTo(0);
        assertThat(overview.coverage().hdfs()).isEqualTo(CoverageState.COLLECTED);
    }

    @Test
    @DisplayName("json-exporter가 붙으면 spark가 COLLECTED로 실지표를 싣는다")
    void sparkMetricsBecomeCollectedWhenExporterIsUp() {
        when(prometheus.targets()).thenReturn(new PrometheusClient.TargetHealth(6, 6));
        when(prometheus.instant(anyString())).thenReturn(List.of());
        when(prometheus.instant(queries.nodeUp()))
                .thenReturn(List.of(node(SERVICE, "service", 1)));
        when(prometheus.instant(queries.sparkUp()))
                .thenReturn(List.of(value("spark-master", 1)));
        when(prometheus.instant(queries.sparkWorkersAlive()))
                .thenReturn(List.of(value("spark-master", 1)));
        when(prometheus.instant(queries.sparkCoresTotal()))
                .thenReturn(List.of(value("spark-master", 2)));
        when(prometheus.instant(queries.sparkCoresUsed()))
                .thenReturn(List.of(value("spark-master", 0)));
        when(prometheus.instant(queries.sparkMemoryTotalMb()))
                .thenReturn(List.of(value("spark-master", 2048)));
        when(prometheus.instant(queries.sparkMemoryUsedMb()))
                .thenReturn(List.of(value("spark-master", 0)));

        MonitoringOverviewResponse overview = service(configured()).overview();

        assertThat(overview.spark().up()).isTrue();
        assertThat(overview.spark().aliveWorkers()).isEqualTo(1);
        assertThat(overview.spark().coresTotal()).isEqualTo(2);
        assertThat(overview.spark().coresUsed()).isEqualTo(0);
        assertThat(overview.spark().memoryTotalMb()).isEqualTo(2048L);
        assertThat(overview.spark().memoryUsedMb()).isEqualTo(0L);
        assertThat(overview.coverage().spark()).isEqualTo(CoverageState.COLLECTED);
    }

    @Test
    @DisplayName("DB 적재 건수가 있으면 collector 슬롯이 COLLECTED로 실수치를 싣는다")
    void dataStoreBecomesCollectedWhenCountsExist() {
        when(prometheus.targets()).thenReturn(new PrometheusClient.TargetHealth(6, 6));
        when(prometheus.instant(anyString())).thenReturn(List.of());
        when(prometheus.instant(queries.nodeUp()))
                .thenReturn(List.of(node(SERVICE, "service", 1)));
        when(dataStoreMetrics.current()).thenReturn(new DataStoreStatus(61L, 5L, 4L));

        MonitoringOverviewResponse overview = service(configured()).overview();

        assertThat(overview.dataStore().technologyCount()).isEqualTo(61L);
        assertThat(overview.dataStore().technologyCandidateCount()).isEqualTo(5L);
        assertThat(overview.dataStore().analysisJobCount()).isEqualTo(4L);
        assertThat(overview.coverage().collector()).isEqualTo(CoverageState.COLLECTED);
    }

    @Test
    @DisplayName("Prometheus가 끊겨도 DB 적재 현황은 collector 슬롯에 그대로 실린다")
    void dataStoreSurvivesPrometheusDisconnect() {
        when(dataStoreMetrics.current()).thenReturn(new DataStoreStatus(61L, 5L, 4L));

        MonitoringOverviewResponse overview = service(notConfigured()).overview();

        assertThat(overview.prometheus().reachable()).isFalse();
        assertThat(overview.dataStore().technologyCount()).isEqualTo(61L);
        assertThat(overview.coverage().collector()).isEqualTo(CoverageState.COLLECTED);
        // Prometheus 계열은 여전히 미수집이다.
        assertThat(overview.coverage().hdfs()).isEqualTo(CoverageState.NOT_COLLECTED);
    }

    @Test
    @DisplayName("network 시계열은 IN/OUT 두 방향으로 나뉜다")
    void networkComesBackAsTwoDirections() {
        Instant at = Instant.parse("2026-09-10T05:30:00Z");
        when(prometheus.range(any(), any(), any(), any())).thenReturn(List.of());
        when(prometheus.range(
                org.mockito.ArgumentMatchers.eq(queries.networkReceiveBytesPerSecond()),
                any(), any(), any()))
                .thenReturn(List.of(new PrometheusClient.Series(
                        Map.of("instance", SERVICE, "role", "service"),
                        List.of(new PrometheusClient.Point(at, 4_100_000d)))));
        when(prometheus.range(
                org.mockito.ArgumentMatchers.eq(queries.networkTransmitBytesPerSecond()),
                any(), any(), any()))
                .thenReturn(List.of(new PrometheusClient.Series(
                        Map.of("instance", SERVICE, "role", "service"),
                        List.of(new PrometheusClient.Point(at, 2_100_000d)))));

        MonitoringTimeseriesResponse response =
                service(configured()).timeseries(MetricKind.NETWORK, TimeRange.LAST_60M);

        assertThat(response.reachable()).isTrue();
        assertThat(response.metric()).isEqualTo("network");
        assertThat(response.range()).isEqualTo("60m");
        assertThat(response.stepSeconds()).isEqualTo(300);
        assertThat(response.unit()).isEqualTo(MetricUnit.BYTES_PER_SECOND);
        assertThat(response.series()).extracting(MonitoringTimeseriesResponse.Series::direction)
                .containsExactly("receive", "transmit");
        assertThat(response.series().get(0).points())
                .containsExactly(new MonitoringTimeseriesResponse.Point(at, 4_100_000d));
    }

    @Test
    @DisplayName("cpu 시계열에는 방향이 없다")
    void cpuHasNoDirection() {
        when(prometheus.range(any(), any(), any(), any()))
                .thenReturn(List.of(new PrometheusClient.Series(
                        Map.of("instance", SERVICE, "role", "service"), List.of())));

        MonitoringTimeseriesResponse response =
                service(configured()).timeseries(MetricKind.CPU, TimeRange.LAST_60M);

        assertThat(response.unit()).isEqualTo(MetricUnit.PERCENT);
        assertThat(response.series().get(0).direction()).isNull();
    }

    @Test
    @DisplayName("시계열 수집이 실패하면 0으로 채운 점을 만들지 않는다")
    void aFailedTimeseriesStaysEmpty() {
        when(prometheus.range(any(), any(), any(), any()))
                .thenThrow(PrometheusUnavailableException.unreachable("연결 실패", null));

        MonitoringTimeseriesResponse response =
                service(configured()).timeseries(MetricKind.CPU, TimeRange.LAST_60M);

        assertThat(response.reachable()).isFalse();
        assertThat(response.state()).isEqualTo(PrometheusState.UNREACHABLE);
        assertThat(response.series()).isEmpty();
        assertThat(response.stepSeconds()).isEqualTo(300);
    }
}
