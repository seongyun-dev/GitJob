package com.example.git_job.analysis.service;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestPayload;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestedEvent;
import com.example.git_job.analysis.messaging.RepositoryAnalysisKafkaProperties;
import com.example.git_job.analysis.outbox.AnalysisOutboxStore;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.json.JsonMapper;

/**
 * Durable enqueue boundary for a single-repository job (the existing analysis_job model).
 * Call only after checking the authenticated user's repository/branch access and resolving SHA.
 * IDs and registry version must be assigned by the server, not copied from public request JSON.
 */
@Service
public class AnalysisRequestService {
    private final AnalysisJobRepository analysisJobs;
    private final AnalysisOutboxStore outbox;
    private final RepositoryAnalysisKafkaProperties topics;
    private final JsonMapper jsonMapper;

    public AnalysisRequestService(AnalysisJobRepository analysisJobs, AnalysisOutboxStore outbox,
            RepositoryAnalysisKafkaProperties topics, JsonMapper jsonMapper) {
        this.analysisJobs = analysisJobs;
        this.outbox = outbox;
        this.topics = topics;
        this.jsonMapper = jsonMapper;
    }

    /** Returns only after job and event are saved; no Kafka connection is needed here. */
    @Transactional
    public RepositoryAnalysisRequestedEvent enqueueAuthorized(
            long userId, RepositoryAnalysisRequestPayload payload, String traceId) {
        if (userId < 1) {
            throw new IllegalArgumentException("userId must be positive");
        }
        var event = RepositoryAnalysisRequestedEvent.create(
                "ev_" + UUID.randomUUID(), Instant.now(), traceId, payload);
        String json = jsonMapper.writeValueAsString(event);

        // saveAndFlush, not save: the outbox row below is written with JdbcTemplate, which
        // reaches the database immediately, while JPA would hold this insert until commit.
        // analysis_outbox.analysis_id references analysis_job, so the parent row has to be
        // there first. Both still roll back together as one transaction.
        analysisJobs.saveAndFlush(AnalysisJob.queue(
                payload.analysisId(), userId, Long.toString(payload.githubRepositoryId()),
                payload.branchName(), payload.commitSha(), event.occurredAt()));
        outbox.insert(event, topics.requests(), json);
        return event;
    }
}
