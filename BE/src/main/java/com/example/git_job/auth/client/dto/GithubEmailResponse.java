package com.example.git_job.auth.client.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/** {@code GET /user/emails} 응답 항목. {@code user:email} scope가 있어야 조회된다. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record GithubEmailResponse(
        @JsonProperty("email") String email,
        @JsonProperty("primary") boolean primary,
        @JsonProperty("verified") boolean verified
) {
}
