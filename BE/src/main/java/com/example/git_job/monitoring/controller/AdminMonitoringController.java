package com.example.git_job.monitoring.controller;

import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.monitoring.controller.dto.MonitoringOverviewResponse;
import com.example.git_job.monitoring.controller.dto.MonitoringTimeseriesResponse;
import com.example.git_job.monitoring.service.MetricKind;
import com.example.git_job.monitoring.service.MonitoringService;
import com.example.git_job.monitoring.service.TimeRange;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Admin System Monitoring 화면의 API (S15P21E102-209).
 *
 * <p>{@code /api/v1/admin} 아래에 있어 {@code SecurityConfig}가 ADMIN으로 제한한다. 별도
 * 보안 설정을 두지 않는 이유는 그 매처가 이미 이 경로를 덮기 때문이고, 여기서 다시 선언하면
 * 두 곳이 어긋날 수 있다.</p>
 *
 * <p>이 컨트롤러가 존재하는 이유는 Prometheus가 관리자망에만 열려 있어 브라우저가 직접
 * 조회할 수 없기 때문이다. 사설 주소를 FE 번들에 넣는 대신 Backend가 읽어 화면 모양으로
 * 바꿔 준다. 그래서 응답에도 주소가 아니라 값과 상태만 담는다.</p>
 *
 * <p>PromQL을 받는 파라미터는 없다. 지표는 {@link MetricKind}, 범위는 {@link TimeRange}의
 * 닫힌 목록에서만 고를 수 있다. 질의 문자열을 받으면 이 엔드포인트가 관리자망 Prometheus에
 * 대한 임의 질의 창구가 된다.</p>
 */
@RestController
@RequestMapping("/api/v1/admin/monitoring")
@RequiredArgsConstructor
public class AdminMonitoringController {

    private final MonitoringService monitoring;

    /**
     * 화면 전체가 쓰는 현재값. System Summary, Infrastructure Map의 상태 점, Server Detail
     * 표, Disk 용량, Quick Access 링크가 모두 이 응답 하나에서 나온다.
     *
     * <p>Prometheus에 닿지 못해도 200이다. 그 사실 자체가 화면이 보여줘야 하는 상태여서
     * {@code prometheus.reachable}로 내려간다.</p>
     */
    @GetMapping("/overview")
    public ResponseEntity<ApiResponse<MonitoringOverviewResponse>> overview() {
        return ResponseEntity.ok(ApiResponse.success(monitoring.overview()));
    }

    /**
     * Resource Overview의 그래프.
     *
     * <p>{@code metric}은 {@code cpu}·{@code memory}·{@code network}, {@code range}는
     * {@code 60m}(생략 시 기본값)이다. 화면이 시계열로 그리는 것이 그 셋이고 범위 선택
     * 컨트롤이 없어서다. Disk는 시계열이 아니라 용량 바로 표시되므로 {@code overview}의
     * 현재값을 쓴다.</p>
     *
     * <p>목록에 없는 값은 400이며 조용히 기본값으로 바꾸지 않는다 — 화면이 요청한 것과
     * 다른 지표를 그리면 눈으로는 구분되지 않는다.</p>
     */
    @GetMapping("/timeseries")
    public ResponseEntity<ApiResponse<MonitoringTimeseriesResponse>> timeseries(
            @RequestParam String metric,
            @RequestParam(required = false) String range
    ) {
        MonitoringTimeseriesResponse body = monitoring.timeseries(
                MetricKind.from(metric), TimeRange.from(range));
        return ResponseEntity.ok(ApiResponse.success(body));
    }
}
