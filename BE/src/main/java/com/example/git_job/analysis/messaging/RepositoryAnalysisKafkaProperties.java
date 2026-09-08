package com.example.git_job.analysis.messaging;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Kafka destinations owned by repository analysis. */
@ConfigurationProperties(prefix = "gitjob.kafka.topics.repository-analysis")
public record RepositoryAnalysisKafkaProperties(String requests) {

    public RepositoryAnalysisKafkaProperties {
        if (requests == null || requests.isBlank() || !requests.equals(requests.strip())) {
            throw new IllegalArgumentException(
                    "gitjob.kafka.topics.repository-analysis.requests must be configured"
            );
        }
    }
}
