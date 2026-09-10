package com.example.git_job.analysis.messaging;

import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import com.example.git_job.analysis.service.AnalysisResultService;
import lombok.RequiredArgsConstructor;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

/**
 * Consumes the analysis worker's results.
 *
 * <p>This listener is the only reason {@code analysis_job} ever leaves
 * {@code QUEUED}. Without it the worker can clone, parse and judge perfectly
 * and the user still sees "대기 중" forever.</p>
 *
 * <p>Deliberately thin. Deserialization is the container's job, the decision is
 * {@link AnalysisResultService}'s, and this only connects them — so the
 * transaction boundary is the service method rather than the poll loop.</p>
 *
 * <p>Throwing here means the offset is not committed and the message comes
 * back. The container's error handler decides how many times before giving up;
 * see {@code RepositoryAnalysisKafkaConfiguration}.</p>
 */
@Component
@RequiredArgsConstructor
public class RepositoryAnalysisResultConsumer {

    private final AnalysisResultService results;

    @KafkaListener(
            // A placeholder, not SpEL: a @ConfigurationProperties bean is named
            // after its prefix, not its class, so "@repositoryAnalysisKafkaProperties"
            // does not resolve. The record still validates the value at startup.
            topics = "${gitjob.kafka.topics.repository-analysis.results}",
            groupId = "${gitjob.kafka.consumer.repository-analysis-results.group-id}",
            containerFactory = "repositoryAnalysisResultListenerFactory")
    public void onResult(RepositoryAnalysisResultEvent event) {
        results.apply(event);
    }
}
