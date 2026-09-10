package com.example.git_job.monitoring.client.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;
import java.util.Map;

/**
 * Prometheus {@code /api/v1/query} · {@code /api/v1/query_range} 응답 (S15P21E102-209).
 *
 * <p>필요한 필드만 받는다. Prometheus는 버전에 따라 {@code warnings}·{@code infos} 같은
 * 필드를 덧붙이므로 미지의 필드를 무시해야 업그레이드에서 파싱이 깨지지 않는다.</p>
 *
 * <p>샘플 값이 {@code ["1757480000.5", "23.5"]} 형태의 혼합 배열이라 {@code List<Object>}로
 * 받는다. 숫자 문자열을 그대로 double로 바꾸지 않고 {@code NaN}·{@code +Inf}를 걸러내는 일은
 * 클라이언트가 한다.</p>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record PromQueryResponse(String status, Data data) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Data(String resultType, List<Result> result) {
        public List<Result> resultOrEmpty() {
            return result == null ? List.of() : result;
        }
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Result(
            Map<String, String> metric,
            /** instant query의 단일 샘플. {@code [epochSeconds, "value"]} */
            List<Object> value,
            /** range query의 샘플 목록. 각 원소가 {@code [epochSeconds, "value"]} */
            List<List<Object>> values
    ) {
        public Map<String, String> labels() {
            return metric == null ? Map.of() : metric;
        }
    }

    public boolean isSuccess() {
        return "success".equals(status);
    }

    public List<Result> results() {
        return data == null ? List.of() : data.resultOrEmpty();
    }
}
