package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.store.TechnologyCandidateStore.Detail;
import com.example.git_job.analysis.store.TechnologyCandidateStore.Observation;
import com.example.git_job.analysis.service.TechnologyCandidateAdminService.CandidateDetail;
import java.time.Instant;
import java.util.List;

/**
 * The technology-candidate detail screen (S15P21E102-141).
 *
 * <p>The list row plus what it does not carry: the decision fields
 * ({@code promotedTechId}/{@code decidedAt}/{@code decisionNote}, null while
 * undecided) so an administrator sees what a candidate became, and the recent
 * {@code observations} -- the evidence behind the summary counts, so the number
 * "14 users" can be traced to which repositories saw it and when.</p>
 */
public record TechnologyCandidateDetailResponse(
        long candidateId,
        String ecosystem,
        String coordinate,
        String scope,
        String status,
        int distinctUserCount,
        int distinctRepositoryCount,
        int occurrenceCount,
        Instant firstSeenAt,
        Instant lastSeenAt,
        String promotedTechId,
        Instant decidedAt,
        String decisionNote,
        List<ObservationResponse> observations
) {

    /** One sighting: which repository, in what scope, how often, when. */
    public record ObservationResponse(
            String repositoryId,
            String scope,
            int occurrenceCount,
            Instant observedAt
    ) {
        static ObservationResponse from(Observation observation) {
            return new ObservationResponse(
                    observation.repositoryId(), observation.scope(),
                    observation.occurrenceCount(), observation.observedAt());
        }
    }

    public static TechnologyCandidateDetailResponse from(CandidateDetail detail) {
        Detail candidate = detail.candidate();
        return new TechnologyCandidateDetailResponse(
                candidate.candidateId(), candidate.ecosystem(), candidate.coordinate(),
                candidate.scope(), candidate.status(), candidate.distinctUserCount(),
                candidate.distinctRepositoryCount(), candidate.occurrenceCount(),
                candidate.firstSeenAt(), candidate.lastSeenAt(), candidate.promotedTechId(),
                candidate.decidedAt(), candidate.decisionNote(),
                detail.observations().stream().map(ObservationResponse::from).toList());
    }
}
