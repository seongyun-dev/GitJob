package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Objects;
import java.util.regex.Pattern;

/**
 * Non-secret input required by the repository analysis worker.
 *
 * <p>GitHub access tokens and installation credentials intentionally do not
 * belong to this contract. The worker exchanges {@code analysisRepositoryId}
 * for the request owner's stored GitHub credential through an authenticated
 * internal API only when an anonymous fetch needs it.</p>
 *
 * <p>{@code branchName} records the selected branch at request time; the worker
 * must still analyze {@code commitSha} even if that branch moves later.</p>
 */
public record RepositoryAnalysisRequestPayload(
        @JsonProperty("analysis_id") String analysisId,
        @JsonProperty("analysis_repository_id") String analysisRepositoryId,
        @JsonProperty("github_repository_id") long githubRepositoryId,
        @JsonProperty("repository_full_name") String repositoryFullName,
        @JsonProperty("branch_name") String branchName,
        @JsonProperty("commit_sha") String commitSha,
        @JsonProperty("analysis_mode") RepositoryAnalysisMode analysisMode,
        @JsonProperty("registry_version") String registryVersion
) {

    private static final Pattern REPOSITORY_FULL_NAME = Pattern.compile(
            "^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+$"
    );
    private static final Pattern COMMIT_SHA = Pattern.compile("^[0-9a-f]{40}$");

    public RepositoryAnalysisRequestPayload {
        analysisId = requireNonBlank(analysisId, "analysisId");
        analysisRepositoryId = requireNonBlank(
                analysisRepositoryId,
                "analysisRepositoryId"
        );
        if (githubRepositoryId < 1) {
            throw new IllegalArgumentException("githubRepositoryId must be positive");
        }
        repositoryFullName = requirePattern(
                repositoryFullName,
                REPOSITORY_FULL_NAME,
                "repositoryFullName"
        );
        branchName = requireNonBlank(branchName, "branchName");
        commitSha = requirePattern(commitSha, COMMIT_SHA, "commitSha");
        analysisMode = Objects.requireNonNull(analysisMode, "analysisMode must not be null");
        registryVersion = requireNonBlank(registryVersion, "registryVersion");
    }

    private static String requireNonBlank(String value, String fieldName) {
        if (value == null || value.isBlank() || !value.equals(value.strip())) {
            throw new IllegalArgumentException(fieldName + " must be non-blank and trimmed");
        }
        return value;
    }

    private static String requirePattern(String value, Pattern pattern, String fieldName) {
        String checkedValue = requireNonBlank(value, fieldName);
        if (!pattern.matcher(checkedValue).matches()) {
            throw new IllegalArgumentException(fieldName + " has an invalid format");
        }
        return checkedValue;
    }
}
