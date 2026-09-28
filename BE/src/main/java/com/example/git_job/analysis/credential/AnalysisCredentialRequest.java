package com.example.git_job.analysis.credential;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.regex.Pattern;

/** Secret-free tuple copied from repository-analysis-request/v1. */
public record AnalysisCredentialRequest(
        @JsonProperty("schema_version")
        String schemaVersion,
        @JsonProperty("analysis_id")
        String analysisId,
        @JsonProperty("analysis_repository_id")
        String analysisRepositoryId,
        @JsonProperty("github_repository_id")
        long githubRepositoryId,
        @JsonProperty("repository_full_name")
        String repositoryFullName,
        @JsonProperty("commit_sha")
        String commitSha
) {
    private static final Pattern REPOSITORY_FULL_NAME = Pattern.compile(
            "^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+$"
    );
    private static final Pattern COMMIT_SHA = Pattern.compile("^[0-9a-f]{40}$");

    boolean hasValidShape() {
        return notBlank(schemaVersion)
                && notBlank(analysisId)
                && notBlank(analysisRepositoryId)
                && githubRepositoryId > 0
                && repositoryFullName != null
                && REPOSITORY_FULL_NAME.matcher(repositoryFullName).matches()
                && commitSha != null
                && COMMIT_SHA.matcher(commitSha).matches();
    }

    private static boolean notBlank(String value) {
        return value != null && !value.isBlank();
    }
}
