package com.example.git_job.analysis.client.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * GitHub 저장소 응답 중 우리가 쓰는 필드만 담는다.
 *
 * <p>{@code permissions}는 인증된 사용자의 권한이며 목록 조회에도 포함된다.
 * 공개 저장소는 누구나 읽을 수 있으므로, 분석 대상 자격은 {@code pull} 여부가 아니라
 * 호출 자체의 성공으로 판단한다.</p>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record GithubRepositoryResponse(
        Long id,
        String name,
        @JsonProperty("full_name") String fullName,
        @JsonProperty("private") Boolean isPrivate,
        @JsonProperty("default_branch") String defaultBranch,
        String description,
        String language,
        @JsonProperty("updated_at") String updatedAt,
        @JsonProperty("pushed_at") String pushedAt,
        Boolean archived,
        Boolean disabled,
        Owner owner,
        Permissions permissions
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Owner(String login, @JsonProperty("avatar_url") String avatarUrl) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Permissions(Boolean admin, Boolean push, Boolean pull) {
    }

    public String ownerLogin() {
        return owner == null ? null : owner.login();
    }

    /** 아카이브·비활성 저장소는 clone은 되지만 분석 대상으로 제시하지 않는다. */
    public boolean analyzable() {
        return !Boolean.TRUE.equals(archived) && !Boolean.TRUE.equals(disabled);
    }
}
