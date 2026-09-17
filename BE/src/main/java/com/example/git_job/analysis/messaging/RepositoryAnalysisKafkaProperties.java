package com.example.git_job.analysis.messaging;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Kafka destinations owned by repository analysis. */
@ConfigurationProperties(prefix = "gitjob.kafka.topics.repository-analysis")
public record RepositoryAnalysisKafkaProperties(
        String requests, String results, String resultsV3, String resultsDlq) {

    public RepositoryAnalysisKafkaProperties {
        requests = require(requests, "requests");
        // Without this topic the worker's verdicts never arrive and analysis_job
        // stays at QUEUED, so it is required rather than defaulted.
        results = require(results, "results");
        resultsV3 = resultsV3 == null ? "" : resultsV3.strip();
        resultsDlq = require(resultsDlq, "results-dlq");
    }

    /**
     * 적용하지 못한 결과가 가는 곳.
     *
     * <p>v3 토픽과 달리 선택값이 아니다. 비워 두면 "DLQ 없이 돌린다"가 되는데, 그것이
     * 바로 결과 4건이 어디로 갔는지 아무도 모르게 된 상태다. 값이 없으면 기동에서
     * 멈추는 편이 낫다 -- 운영 중에 조용히 사라지는 것보다 배포 때 이름이 불리는 것이
     * 싸다.</p>
     *
     * <p>워커의 {@code KAFKA_TOPIC_REPOSITORY_ANALYSIS_DLQ} 와는 <b>다른 토픽</b>이다.
     * 그쪽은 처리하지 못한 <i>요청</i>이 가는 곳이고 payload 모양이 다르다. 섞으면
     * 비우는 사람이 무엇을 보고 있는지 알 수 없다.</p>
     */
    public String resultsDlq() {
        return resultsDlq;
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
