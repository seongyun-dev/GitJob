package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.outbox.TechnologyCandidateStore.Ranked;
import java.time.Instant;

/**
 * One row of the admin list.
 *
 * <p>{@code distinctUserCount} leads because it is what the decision turns on:
 * how many people a technology would serve. Occurrence counts let one monorepo
 * decide the order, so they are shown but not sorted on.</p>
 */
public record TechnologyCandidateResponse(
        long candidateId,
        String ecosystem,
        String coordinate,
        String scope,
        String status,
        int distinctUserCount,
        int distinctRepositoryCount,
        int occurrenceCount,
        Instant firstSeenAt,
        Instant lastSeenAt
) {

    public static TechnologyCandidateResponse from(Ranked row) {
        return new TechnologyCandidateResponse(
                row.candidateId(), row.ecosystem(), row.coordinate(), row.scope(),
                row.status(), row.distinctUserCount(), row.distinctRepositoryCount(),
                row.occurrenceCount(), row.firstSeenAt(), row.lastSeenAt());
    }
}
