package com.example.git_job.analysis.messaging;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Kafka destinations owned by repository analysis. */
@ConfigurationProperties(prefix = "gitjob.kafka.topics.repository-analysis")
public record RepositoryAnalysisKafkaProperties(String requests, String results) {

    public RepositoryAnalysisKafkaProperties {
        requests = require(requests, "requests");
        // Without this topic the worker's verdicts never arrive and analysis_job
        // stays at QUEUED, so it is required rather than defaulted.
        results = require(results, "results");
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
