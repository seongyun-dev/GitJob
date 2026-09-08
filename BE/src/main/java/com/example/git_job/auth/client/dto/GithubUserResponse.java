package com.example.git_job.auth.client.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * {@code GET /user} 응답 중 GitJob이 쓰는 필드만 담는다.
 *
 * <p>{@code name}은 사용자가 프로필 이름을 설정하지 않으면 null이고,
 * {@code email}은 비공개로 두면 null이다. {@code login}과 {@code id}만 항상 있다.</p>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record GithubUserResponse(
        @JsonProperty("id") Long id,
        @JsonProperty("login") String login,
        @JsonProperty("name") String name,
        @JsonProperty("avatar_url") String avatarUrl,
        @JsonProperty("email") String email
) {
}
