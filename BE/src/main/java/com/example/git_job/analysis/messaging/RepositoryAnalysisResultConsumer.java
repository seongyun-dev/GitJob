package com.example.git_job.analysis.messaging;

import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import com.example.git_job.analysis.service.AnalysisResultService;
import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.service.EvidenceAuthorshipService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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

    private static final Logger log =
            LoggerFactory.getLogger(RepositoryAnalysisResultConsumer.class);

    private final AnalysisResultService results;
    private final EvidenceAuthorshipService authorship;

    @KafkaListener(
            // A placeholder, not SpEL: a @ConfigurationProperties bean is named
            // after its prefix, not its class, so "@repositoryAnalysisKafkaProperties"
            // does not resolve. The record still validates the value at startup.
            topics = "${gitjob.kafka.topics.repository-analysis.results}",
            groupId = "${gitjob.kafka.consumer.repository-analysis-results.group-id}",
            containerFactory = "repositoryAnalysisResultListenerFactory")
    public void onResult(RepositoryAnalysisResultEvent event) {
        AnalysisResultService.Applied applied = results.apply(event);

        // 근거는 위에서 이미 커밋됐다. 기여 판정은 GitHub 을 호출하므로 따로 둔다 --
        // 여기서 던지면 오프셋이 안 올라가고 결과 전체가 재배달되는데, 그러면
        // GitHub 이 잠깐 느렸다는 이유로 판정된 근거 수백 건을 다시 쓰게 된다.
        // 판정이 없으면 Personal Level 만 비고, 재분석이 채운다.
        AnalysisJob job = results.attributionTarget(event, applied);
        if (job == null) {
            return;
        }
        try {
            authorship.attribute(job);
        } catch (RuntimeException unavailable) {
            log.warn("authorship deferred: analysisId={}, reason={}",
                    job.getAnalysisId(), unavailable.toString());
        }
    }
}
