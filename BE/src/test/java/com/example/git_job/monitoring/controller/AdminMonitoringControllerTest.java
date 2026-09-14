package com.example.git_job.monitoring.controller;

import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.git_job.global.handler.GlobalExceptionHandler;
import com.example.git_job.monitoring.controller.dto.CoverageState;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.Coverage;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.DataStoreStatus;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.HdfsStatus;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.KafkaStatus;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.SparkStatus;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.Links;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.PrometheusStatus;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse.ServerMetrics;
import com.example.git_job.monitoring.controller.dto.MonitoringTimeseriesResponse;
import com.example.git_job.monitoring.controller.dto.PrometheusState;
import com.example.git_job.monitoring.service.MetricKind;
import com.example.git_job.monitoring.service.MetricUnit;
import com.example.git_job.monitoring.service.MonitoringService;
import com.example.git_job.monitoring.service.TimeRange;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

/**
 * 화면이 실제로 받는 HTTP 응답을 고정한다 (S15P21E102-209).
 *
 * <p>확인하는 것은 두 가지다. 하나는 미연결 상태가 오류가 아니라 200 본문으로 온다는 것 —
 * 500이면 화면은 "모니터링이 끊겼다"와 "서버가 죽었다"를 구분할 수 없다. 다른 하나는
 * 모르는 지표 이름이 조용히 기본값으로 바뀌지 않고 400이 된다는 것이다.</p>
 *
 * <p>{@code SecurityConfig}는 올리지 않는다. ADMIN 제한은 {@code /api/v1/admin/**} 매처가
 * 담당하며 이 슬라이스의 검증 대상이 아니다(기존 {@code AdminTechnologyCandidateControllerTest}와
 * 같은 판단).</p>
 */
class AdminMonitoringControllerTest {

    private static final String BASE = "/api/v1/admin/monitoring";
    private static final Instant AT = Instant.parse("2026-09-10T05:32:05Z");

    private MockMvc mockMvc;
    private MonitoringService monitoring;

    @BeforeEach
    void setUp() {
        monitoring = mock(MonitoringService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(new AdminMonitoringController(monitoring))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    @DisplayName("overview는 공용 봉투에 서버별 실제 값을 담아 준다")
    void overviewCarriesTheRealNumbersInsideTheSharedEnvelope() throws Exception {
        when(monitoring.overview()).thenReturn(new MonitoringOverviewResponse(
                AT,
                PrometheusStatus.connected(6, 6, 15),
                List.of(new ServerMetrics(
                        "10.0.0.1:9100", "service", "service-1", "service-server", true,
                        23.4, 4, 41.0, 6_600_000_000L, 16_000_000_000L,
                        54.0, 216_000_000_000L, 400_000_000_000L, 4_100_000d, 2_100_000d)),
                new KafkaStatus(true, 10, 0.5d, 0L),
                new HdfsStatus(true, 86016L, 3_243_303_530_496L, 0L, 3, 0),
                new SparkStatus(true, 1, 2, 0, 2048L, 0L),
                new DataStoreStatus(61L, 5L, 4L),
                new Coverage(CoverageState.COLLECTED, CoverageState.COLLECTED,
                        CoverageState.COLLECTED, CoverageState.COLLECTED),
                new Links("https://grafana.example.internal", null)));

        mockMvc.perform(get(BASE + "/overview"))
                .andExpect(status().isOk())
                // 공용 ApiResponse 계약. 이번 Jira에서 바꾸지 않았다.
                .andExpect(jsonPath("$.message").exists())
                .andExpect(jsonPath("$.data.prometheus.reachable").value(true))
                .andExpect(jsonPath("$.data.prometheus.state").value("CONNECTED"))
                .andExpect(jsonPath("$.data.prometheus.targetsUp").value(6))
                .andExpect(jsonPath("$.data.prometheus.scrapeIntervalSeconds").value(15))
                .andExpect(jsonPath("$.data.servers[0].instance").value("10.0.0.1:9100"))
                .andExpect(jsonPath("$.data.servers[0].role").value("service"))
                .andExpect(jsonPath("$.data.servers[0].cpuPercent").value(23.4))
                .andExpect(jsonPath("$.data.servers[0].cpuCores").value(4))
                .andExpect(jsonPath("$.data.servers[0].memoryUsedBytes").value(6_600_000_000L))
                .andExpect(jsonPath("$.data.kafka.up").value(true))
                // Kafka 실지표(S15P21E102-261 Phase 1). exporter가 붙으면 값과 COLLECTED가 함께 온다.
                .andExpect(jsonPath("$.data.kafka.topicCount").value(10))
                .andExpect(jsonPath("$.data.kafka.messagesInPerSecond").value(0.5))
                .andExpect(jsonPath("$.data.kafka.consumerLagTotal").value(0))
                .andExpect(jsonPath("$.data.coverage.kafkaBusiness")
                        .value(CoverageState.COLLECTED.name()))
                // HDFS 실지표(S15P21E102-261 Phase 2). json-exporter가 붙으면 값과 COLLECTED가 함께 온다.
                .andExpect(jsonPath("$.data.hdfs.up").value(true))
                .andExpect(jsonPath("$.data.hdfs.capacityTotalBytes").value(3_243_303_530_496L))
                .andExpect(jsonPath("$.data.hdfs.liveDataNodes").value(3))
                .andExpect(jsonPath("$.data.coverage.hdfs")
                        .value(CoverageState.COLLECTED.name()))
                // Spark 실지표(S15P21E102-261 Phase 3). json-exporter가 붙으면 값과 COLLECTED가 함께 온다.
                .andExpect(jsonPath("$.data.spark.up").value(true))
                .andExpect(jsonPath("$.data.spark.aliveWorkers").value(1))
                .andExpect(jsonPath("$.data.spark.coresTotal").value(2))
                .andExpect(jsonPath("$.data.spark.memoryTotalMb").value(2048))
                .andExpect(jsonPath("$.data.coverage.spark")
                        .value(CoverageState.COLLECTED.name()))
                // 데이터 적재 DB count(S15P21E102-261 Phase 4). collector 슬롯이 이걸 나타낸다.
                .andExpect(jsonPath("$.data.dataStore.technologyCount").value(61))
                .andExpect(jsonPath("$.data.dataStore.technologyCandidateCount").value(5))
                .andExpect(jsonPath("$.data.dataStore.analysisJobCount").value(4))
                .andExpect(jsonPath("$.data.coverage.collector")
                        .value(CoverageState.COLLECTED.name()))
                .andExpect(jsonPath("$.data.links.grafanaUrl")
                        .value("https://grafana.example.internal"))
                // 미설정 링크는 빈 문자열이 아니라 null이어야 한다. 화면이 눌러도 아무 일
                // 없는 링크를 그리지 않기 위해서다.
                .andExpect(jsonPath("$.data.links.prometheusUrl").value(nullValue()));
    }

    @Test
    @DisplayName("Prometheus 미연결은 오류가 아니라 상태로 200에 실린다")
    void aDisconnectedPrometheusIsAStateNotAnError() throws Exception {
        when(monitoring.overview()).thenReturn(new MonitoringOverviewResponse(
                AT,
                PrometheusStatus.disconnected(PrometheusState.UNREACHABLE),
                List.of(),
                KafkaStatus.unknown(),
                HdfsStatus.unknown(),
                SparkStatus.unknown(),
                DataStoreStatus.unknown(),
                Coverage.current(),
                new Links(null, null)));

        mockMvc.perform(get(BASE + "/overview"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.prometheus.reachable").value(false))
                .andExpect(jsonPath("$.data.prometheus.state").value("UNREACHABLE"))
                // 0이 아니라 없어야 한다. 0은 "target이 하나도 없다"는 다른 사실이다.
                .andExpect(jsonPath("$.data.prometheus.targetsUp").value(nullValue()))
                .andExpect(jsonPath("$.data.servers").isEmpty())
                .andExpect(jsonPath("$.data.kafka.up").value(nullValue()));
    }

    @Test
    @DisplayName("timeseries는 range를 생략하면 기본 범위로 조회한다")
    void timeseriesFallsBackToTheDefaultWindowWhenRangeIsOmitted() throws Exception {
        when(monitoring.timeseries(MetricKind.CPU, TimeRange.LAST_60M))
                .thenReturn(MonitoringTimeseriesResponse.connected(
                        "cpu", "60m", 300, MetricUnit.PERCENT,
                        List.of(new MonitoringTimeseriesResponse.Series(
                                "10.0.0.1:9100", "service", null,
                                List.of(new MonitoringTimeseriesResponse.Point(AT, 23.4))))));

        mockMvc.perform(get(BASE + "/timeseries").param("metric", "cpu"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.metric").value("cpu"))
                .andExpect(jsonPath("$.data.range").value("60m"))
                .andExpect(jsonPath("$.data.stepSeconds").value(300))
                .andExpect(jsonPath("$.data.unit").value("PERCENT"))
                .andExpect(jsonPath("$.data.series[0].points[0].value").value(23.4));
    }

    @Test
    @DisplayName("모르는 지표 이름은 기본값으로 바꾸지 않고 400을 낸다")
    void anUnknownMetricNameIsRejectedInsteadOfGuessed() throws Exception {
        mockMvc.perform(get(BASE + "/timeseries").param("metric", "hdfsBlocks"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("G-400-2"));

        verify(monitoring, never()).timeseries(any(), any());
    }

    @Test
    @DisplayName("모르는 범위도 400이다")
    void anUnknownRangeIsRejectedToo() throws Exception {
        mockMvc.perform(get(BASE + "/timeseries")
                        .param("metric", "cpu")
                        .param("range", "7d"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("G-400-2"));

        verify(monitoring, never()).timeseries(any(), any());
    }
}
