package com.example.git_job.analysis.credential;

import com.fasterxml.jackson.annotation.JsonProperty;

/** Returned only over the private Worker-to-BE route and never persisted by the Worker. */
public record AnalysisCredentialResponse(
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("credential_type") String credentialType,
        @JsonProperty("access_token") String accessToken
) {
    static AnalysisCredentialResponse github(String accessToken) {
        return new AnalysisCredentialResponse(
                "repository-analysis-credential-response/v1",
                "GITHUB_OAUTH_ACCESS_TOKEN",
                accessToken
        );
    }
}
