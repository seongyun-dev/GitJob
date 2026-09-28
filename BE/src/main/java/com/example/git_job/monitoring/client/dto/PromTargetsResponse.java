package com.example.git_job.monitoring.client.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

/**
 * Prometheus {@code /api/v1/targets} 응답 (S15P21E102-209).
 *
 * <p>화면의 "6 / 6 targets UP"이 이 값에서 나온다. {@code up} 메트릭을 세는 것과 다른 이유는,
 * scrape가 아예 실패해 시계열이 없는 target도 여기에는 {@code health=down}으로 남기 때문이다.</p>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record PromTargetsResponse(String status, Data data) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Data(List<ActiveTarget> activeTargets) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ActiveTarget(String health) {
        public boolean isUp() {
            return "up".equals(health);
        }
    }

    public boolean isSuccess() {
        return "success".equals(status);
    }

    public List<ActiveTarget> activeTargets() {
        if (data == null || data.activeTargets() == null) {
            return List.of();
        }
        return data.activeTargets();
    }
}
