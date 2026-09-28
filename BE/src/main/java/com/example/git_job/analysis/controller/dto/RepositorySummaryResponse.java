package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.client.dto.GithubRepositoryResponse;

/**
 * 저장소 선택 화면에 필요한 것만 추린 응답. GitHub 원본을 그대로 내려주지 않는 이유는
 * 응답에 clone URL·소유자 상세 등 화면에 쓰지 않는 필드가 대량으로 섞여 있기 때문이다.
 *
 * @param analyzable 아카이브·비활성 저장소는 false. 목록에서 감추지 않고 표시만 막는다
 */
public record RepositorySummaryResponse(
        long githubRepositoryId,
        String fullName,
        String name,
        String owner,
        boolean isPrivate,
        String defaultBranch,
        String description,
        String language,
        String updatedAt,
        boolean analyzable
) {

    public static RepositorySummaryResponse from(GithubRepositoryResponse repository) {
        return new RepositorySummaryResponse(
                repository.id(),
                repository.fullName(),
                repository.name(),
                repository.ownerLogin(),
                Boolean.TRUE.equals(repository.isPrivate()),
                repository.defaultBranch(),
                repository.description(),
                repository.language(),
                repository.updatedAt(),
                repository.analyzable());
    }
}
