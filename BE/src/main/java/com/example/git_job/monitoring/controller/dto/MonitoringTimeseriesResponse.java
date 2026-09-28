package com.example.git_job.monitoring.controller.dto;

import com.example.git_job.monitoring.service.MetricUnit;
import java.time.Instant;
import java.util.List;

/**
 * 한 지표의 시계열 (S15P21E102-209).
 *
 * <p>서버별로 따로 내려준다. 합산한 한 줄만 주면 화면이 "어느 서버가 튀었는지"를 물을 수
 * 없고, 서버가 늘어날 때 계약이 바뀌어야 한다. 합산은 필요한 화면이 하면 된다.</p>
 *
 * <p>{@code reachable=false}일 때 {@code series}는 빈 목록이다. 0으로 채운 점을 만들지
 * 않는다 — 평평한 0 그래프는 장애가 아니라 한가한 서버로 읽힌다. 왜 비었는지는
 * {@code state}가 말한다.</p>
 */
public record MonitoringTimeseriesResponse(
        String metric,
        String range,
        int stepSeconds,
        MetricUnit unit,
        boolean reachable,
        PrometheusState state,
        List<Series> series
) {

    /**
     * 시계열 한 줄.
     *
     * <p>{@code direction}은 방향이 있는 지표에서만 채워진다. 현재는 network의
     * {@code receive}/{@code transmit}뿐이고, cpu·memory에서는 {@code null}이다. 화면은
     * 이 필드로 IN/OUT 범례를 만든다.</p>
     */
    public record Series(String instance, String role, String direction, List<Point> points) {
    }

    public record Point(Instant at, double value) {
    }

    public static MonitoringTimeseriesResponse connected(
            String metric, String range, int stepSeconds, MetricUnit unit, List<Series> series
    ) {
        return new MonitoringTimeseriesResponse(
                metric, range, stepSeconds, unit, true, PrometheusState.CONNECTED, series);
    }

    /** {@code state}는 미설정·도달 실패·응답 이상을 구분해 넘긴다. */
    public static MonitoringTimeseriesResponse disconnected(
            String metric, String range, int stepSeconds, MetricUnit unit, PrometheusState state
    ) {
        return new MonitoringTimeseriesResponse(
                metric, range, stepSeconds, unit, false, state, List.of());
    }
}
