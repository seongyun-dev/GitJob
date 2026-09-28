package com.example.git_job.analysis.controller.dto;

import java.util.List;

/**
 * Everything optional except the decision itself.
 *
 * <p>{@code techId} and {@code displayName} default from the coordinate, and
 * {@code jobDomains} to BACKEND. An administrator promoting twenty candidates
 * in one sitting should not have to retype what the coordinate already says.</p>
 */
public record CandidatePromoteRequest(
        String techId,
        String displayName,
        List<String> jobDomains,
        String note
) {
}
