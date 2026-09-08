package com.example.git_job.analysis.controller;

import com.example.git_job.analysis.controller.dto.BranchSummaryResponse;
import com.example.git_job.analysis.controller.dto.PageResponse;
import com.example.git_job.analysis.controller.dto.RepositorySummaryResponse;
import com.example.git_job.analysis.service.GithubRepositoryQueryService;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 분석 대상 선택 화면이 쓰는 조회 API (B-FN-002).
 *
 * <p>대상 사용자는 항상 세션의 주인이다. 경로나 파라미터로 사용자 ID를 받지 않으므로
 * 남의 저장소 목록을 요청할 방법이 없다.</p>
 */
@RestController
@RequestMapping("/api/v1/me/repositories")
@RequiredArgsConstructor
public class RepositoryController {

    private final GithubRepositoryQueryService repositoryQueryService;

    /** 저장소 목록. GitHub이 전체 개수를 주지 않아 hasNext만 알려준다. */
    @GetMapping
    public ApiResponse<PageResponse<RepositorySummaryResponse>> repositories(
            @AuthenticationPrincipal AuthenticatedUser user,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "30") int perPage
    ) {
        return ApiResponse.success(
                repositoryQueryService.repositories(CurrentUser.idOf(user), page, perPage));
    }

    /**
     * 브랜치 목록. 저장소를 고른 다음 단계이며, 여기서 고른 브랜치가 분석 요청에 실린다.
     * API 카탈로그에는 없던 경로이나 브랜치 선택에 반드시 필요해 추가했다.
     */
    @GetMapping("/{owner}/{repository}/branches")
    public ApiResponse<PageResponse<BranchSummaryResponse>> branches(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable String owner,
            @PathVariable String repository,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "100") int perPage
    ) {
        return ApiResponse.success(repositoryQueryService.branches(
                CurrentUser.idOf(user), owner, repository, page, perPage));
    }
}
