package com.example.git_job.auth.client.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * {@code POST https://github.com/login/oauth/access_token} 응답.
 *
 * <p>GitHub은 잘못된 code에도 <b>200</b>과 함께 {@code error} 필드를 돌려준다.
 * 그래서 HTTP 상태만 보고 성공을 판단할 수 없다.</p>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record GithubTokenResponse(
        @JsonProperty("access_token") String accessToken,
        @JsonProperty("token_type") String tokenType,
        @JsonProperty("scope") String scope,
        @JsonProperty("error") String error,
        @JsonProperty("error_description") String errorDescription
) {

    public boolean isSuccess() {
        return error == null && accessToken != null && !accessToken.isBlank();
    }
}
