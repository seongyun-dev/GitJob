package com.example.git_job.analysis.service;

import com.example.git_job.analysis.client.GithubRepositoryClient;
import com.example.git_job.analysis.controller.dto.BranchSummaryResponse;
import com.example.git_job.analysis.controller.dto.PageResponse;
import com.example.git_job.analysis.controller.dto.RepositorySummaryResponse;
import com.example.git_job.analysis.domain.RepositoryCoordinate;
import com.example.git_job.auth.service.GithubAccessTokenProvider;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

/**
 * 분석 대상을 고르기 위한 조회 전용 서비스 (B-FN-002).
 *
 * <p>결과를 저장하지 않는다. 저장소 목록과 브랜치는 GitHub이 진실이고, 캐시하면
 * 방금 만든 브랜치가 목록에 없거나 권한 회수가 반영되지 않는 쪽이 더 큰 문제다.</p>
 */
@Service
@RequiredArgsConstructor
public class GithubRepositoryQueryService {

    private static final int MAX_PER_PAGE = 100;
    private static final int DEFAULT_PER_PAGE = 30;

    private final GithubRepositoryClient githubRepositoryClient;
    private final GithubAccessTokenProvider accessTokenProvider;

    public PageResponse<RepositorySummaryResponse> repositories(long userId, int page, int perPage) {
        int size = normalizePerPage(perPage);
        int number = normalizePage(page);
        List<RepositorySummaryResponse> items =
                githubRepositoryClient
                        .fetchRepositories(accessTokenProvider.accessTokenOf(userId), number, size)
                        .stream()
                        .map(RepositorySummaryResponse::from)
                        .toList();
        return PageResponse.of(items, number, size);
    }

    /**
     * 브랜치를 보여주기 전에 저장소 접근 권한을 확인하지 않는다. 브랜치 조회 자체가
     * 권한이 없으면 404로 끊기므로, 확인용 호출을 하나 더 하면 rate limit만 두 배로 쓴다.
     */
    public PageResponse<BranchSummaryResponse> branches(
            long userId, String owner, String repository, int page, int perPage) {
        // 브랜치 이름 검증은 여기서 할 것이 없으므로 기본 브랜치 자리표시자를 넣는다.
        var coordinate = new RepositoryCoordinate(owner, repository, "HEAD");
        int size = normalizePerPage(perPage);
        int number = normalizePage(page);
        List<BranchSummaryResponse> items =
                githubRepositoryClient
                        .fetchBranches(accessTokenProvider.accessTokenOf(userId),
                                coordinate.owner(), coordinate.repository(), number, size)
                        .stream()
                        .map(BranchSummaryResponse::from)
                        .toList();
        return PageResponse.of(items, number, size);
    }

    /** GitHub의 상한은 100이다. 그보다 큰 값을 넘기면 조용히 100으로 잘리므로 여기서 맞춘다. */
    private int normalizePerPage(int perPage) {
        if (perPage < 1) {
            return DEFAULT_PER_PAGE;
        }
        return Math.min(perPage, MAX_PER_PAGE);
    }

    private int normalizePage(int page) {
        return Math.max(page, 1);
    }
}
