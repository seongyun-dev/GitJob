package com.example.git_job.analysis.messaging;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Kafka destinations owned by repository analysis. */
@ConfigurationProperties(prefix = "gitjob.kafka.topics.repository-analysis")
public record RepositoryAnalysisKafkaProperties(
        String requests, String results, String resultsV3) {

    public RepositoryAnalysisKafkaProperties {
        requests = require(requests, "requests");
        // Without this topic the worker's verdicts never arrive and analysis_job
        // stays at QUEUED, so it is required rather than defaulted.
        results = require(results, "results");
        resultsV3 = resultsV3 == null ? "" : resultsV3.strip();
    }

    /**
     * v3 결과 토픽. 선택값이다 (S15P21E102-279 후속).
     *
     * <p>워커는 Registry 버전에 따라 발행 토픽을 <b>바꾼다</b> -- v1 을 함께 보내지
     * 않는다. {@code registry-20260911.3/.4} 를 쓰는 환경에서 이 토픽을 구독하지
     * 않으면 결과가 도달하지 않아 분석이 QUEUED 에 남고, 그러면 C 계산도 시작되지
     * 않는다. 워커 쪽 환경 변수 이름이
     * {@code KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V3} 라 같은 이름을 쓴다.</p>
     *
     * <p>비어 있으면 구독하지 않는다. v1 만 쓰는 환경에서 존재하지 않는 토픽을
     * 구독하면 로그가 경고로 가득 찬다.</p>
     */
    public boolean hasResultsV3() {
        return !resultsV3.isEmpty();
    }

    private static String require(String value, String name) {
        if (value == null || value.isBlank() || !value.equals(value.strip())) {
            throw new IllegalArgumentException(
                    "gitjob.kafka.topics.repository-analysis." + name + " must be configured"
            );
        }
        return value;
    }
}
