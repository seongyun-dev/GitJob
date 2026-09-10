package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Objects;
import java.util.regex.Pattern;

/**
 * Everything this service needs to close out one analysis.
 *
 * <p>There is no userId. The worker never learns who owns an analysis, and
 * analysisId is enough to resolve the owner here. Widening this would put user
 * identity into a topic that outlives the request.</p>
 */
public record RepositoryAnalysisResultPayload(
        @JsonProperty("analysis_id") String analysisId,
        @JsonProperty("request_event_id") String requestEventId,
        @JsonProperty("registry_version") String registryVersion,
        @JsonProperty("commit_sha") String commitSha,
        @JsonProperty("status") Status status,
        @JsonProperty("error_code") String errorCode,
        @JsonProperty("error_detail") String errorDetail,
        @JsonProperty("technologies") List<TechnologyVerdict> technologies,
        @JsonProperty("evidence") List<EvidenceItem> evidence,
        @JsonProperty("candidates") List<TechnologyCandidate> candidates,
        @JsonProperty("stats") AnalysisStats stats
) {

    /**
     * FAILED arrives on the result topic, not only in the DLQ. The DLQ is for
     * operators; a user whose repository was deleted has to see the failure, and
     * analysis_job only moves when this event says so.
     */
    public enum Status { COMPLETED, FAILED }

    private static final Pattern COMMIT_SHA = Pattern.compile("^[0-9a-f]{40}$");

    public RepositoryAnalysisResultPayload {
        analysisId = requireNonBlank(analysisId, "analysisId");
        requestEventId = requireNonBlank(requestEventId, "requestEventId");
        registryVersion = requireNonBlank(registryVersion, "registryVersion");
        commitSha = Objects.requireNonNull(commitSha, "commitSha must not be null");
        if (!COMMIT_SHA.matcher(commitSha).matches()) {
            throw new IllegalArgumentException("commitSha must be 40 lowercase hex characters");
        }
        status = Objects.requireNonNull(status, "status must not be null");

        technologies = List.copyOf(technologies == null ? List.of() : technologies);
        evidence = List.copyOf(evidence == null ? List.of() : evidence);
        candidates = List.copyOf(candidates == null ? List.of() : candidates);

        if (status == Status.FAILED) {
            if (errorCode == null || errorCode.isBlank()) {
                throw new IllegalArgumentException("a FAILED result must carry an errorCode");
            }
            // Otherwise this service would write evidence rows for an analysis it
            // is about to mark failed.
            if (!technologies.isEmpty() || !evidence.isEmpty() || !candidates.isEmpty()) {
                throw new IllegalArgumentException("a FAILED result must not carry findings");
            }
        } else if (errorCode != null && !errorCode.isBlank()) {
            throw new IllegalArgumentException("errorCode belongs to a FAILED result");
        }
    }

    public boolean failed() {
        return status == Status.FAILED;
    }

    private static String requireNonBlank(String value, String fieldName) {
        if (value == null || value.isBlank() || !value.equals(value.strip())) {
            throw new IllegalArgumentException(fieldName + " must be non-blank and trimmed");
        }
        return value;
    }
}
