package com.example.git_job.analysis.client;

import com.example.git_job.analysis.client.dto.GithubBranchResponse;
import com.example.git_job.analysis.client.dto.GithubCommitResponse;
import com.example.git_job.analysis.client.dto.GithubRepositoryResponse;
import com.example.git_job.global.config.GithubOAuthProperties;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.net.URI;
import java.util.Arrays;
import java.util.List;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * 로그인한 사용자의 Access Token으로 GitHub 저장소·브랜치를 조회한다 (B-FN-002).
 *
 * <p>토큰은 인자로만 받고 필드에 보관하지 않으며, 예외 메시지에도 싣지 않는다.
 * GitHub 응답 본문에는 요청 URL이 섞여 나올 수 있어 원문을 그대로 전파하지 않고
 * 상태 코드만 우리 오류 코드로 옮긴다.</p>
 */
@Component
public class GithubRepositoryClient {

    private static final String BEARER_PREFIX = "Bearer ";
    private static final String RATE_LIMIT_REMAINING = "x-ratelimit-remaining";

    private final RestClient restClient;
    private final String apiUrl;

    public GithubRepositoryClient(GithubOAuthProperties properties) {
        this.apiUrl = properties.getApiUrl();
        this.restClient = RestClient.builder()
                .baseUrl(apiUrl)
                .defaultHeader(HttpHeaders.ACCEPT, "application/vnd.github+json")
                .defaultHeader("X-GitHub-Api-Version", "2022-11-28")
                .build();
    }

    /**
     * 사용자가 접근할 수 있는 저장소 한 페이지. 최근 갱신 순으로 정렬해 첫 페이지에
     * 분석하고 싶을 만한 저장소가 오게 한다. GitHub은 전체 개수를 주지 않으므로
     * 페이지 크기만큼 왔는지로 다음 페이지 존재를 판단한다.
     */
    public List<GithubRepositoryResponse> fetchRepositories(String accessToken, int page, int perPage) {
        URI uri = UriComponentsBuilder.fromUriString(apiUrl)
                .path("/user/repos")
                .queryParam("visibility", "all")
                .queryParam("affiliation", "owner,collaborator,organization_member")
                .queryParam("sort", "updated")
                .queryParam("direction", "desc")
                .queryParam("per_page", perPage)
                .queryParam("page", page)
                .build()
                .encode()
                .toUri();
        GithubRepositoryResponse[] repositories =
                get(uri, accessToken, GithubRepositoryResponse[].class, ErrorCode.REPOSITORY_NOT_FOUND);
        return repositories == null ? List.of() : Arrays.asList(repositories);
    }

    /** 단건 조회의 성공 자체가 접근 권한의 증거다. 권한이 없으면 GitHub이 404를 준다. */
    public GithubRepositoryResponse fetchRepository(String accessToken, String owner, String repository) {
        URI uri = repositoryUri(owner, repository).build().encode().toUri();
        GithubRepositoryResponse response =
                get(uri, accessToken, GithubRepositoryResponse.class, ErrorCode.REPOSITORY_NOT_FOUND);
        if (response == null || response.id() == null || response.fullName() == null) {
            throw new CustomException(ErrorCode.REPOSITORY_NOT_FOUND);
        }
        return response;
    }

    public List<GithubBranchResponse> fetchBranches(
            String accessToken, String owner, String repository, int page, int perPage) {
        URI uri = repositoryUri(owner, repository)
                .path("/branches")
                .queryParam("per_page", perPage)
                .queryParam("page", page)
                .build()
                .encode()
                .toUri();
        GithubBranchResponse[] branches =
                get(uri, accessToken, GithubBranchResponse[].class, ErrorCode.REPOSITORY_NOT_FOUND);
        return branches == null ? List.of() : Arrays.asList(branches);
    }

    /**
     * 분석을 고정할 tip commit을 확정한다. 브랜치 이름에는 {@code feature/cdc}처럼
     * 슬래시가 들어갈 수 있고 GitHub은 그것을 경로 구분자로 받는다. 그래서 세그먼트로
     * 쪼개지 않고 경로에 이어 붙인 뒤 인코딩한다.
     */
    public GithubBranchResponse fetchBranch(
            String accessToken, String owner, String repository, String branch) {
        URI uri = repositoryUri(owner, repository)
                .path("/branches/")
                .path(branch)
                .build()
                .encode()
                .toUri();
        GithubBranchResponse response =
                get(uri, accessToken, GithubBranchResponse.class, ErrorCode.BRANCH_NOT_FOUND);
        if (response == null || response.commitSha() == null) {
            throw new CustomException(ErrorCode.BRANCH_NOT_FOUND);
        }
        return response;
    }

    /**
     * 커밋 하나에 연결된 GitHub 계정.
     *
     * <p>이메일 비교를 하지 않기 위한 호출이다. GitHub이 커밋의 이메일을 등록된
     * 계정과 이미 맞춰 두었으므로 그 결과를 받아 쓴다 -- 사용자의 주소 목록도,
     * 남의 이메일을 다루는 일도 필요 없다.</p>
     *
     * <p>없는 커밋은 {@code null}을 돌려준다. 예외로 올리지 않는 것은, 기여 판정을
     * 못 하는 것이 분석 실패는 아니기 때문이다. force push 로 사라진 커밋이 근거에
     * 남아 있을 수 있고, 그 하나 때문에 나머지 근거를 버릴 이유가 없다.</p>
     */
    public GithubCommitResponse fetchCommit(
            String accessToken, String owner, String repository, String commitSha) {
        URI uri = repositoryUri(owner, repository)
                .pathSegment("commits", commitSha)
                .build()
                .encode()
                .toUri();
        try {
            return get(uri, accessToken, GithubCommitResponse.class,
                    ErrorCode.REPOSITORY_NOT_FOUND);
        } catch (CustomException notFound) {
            if (notFound.getErrorCode() == ErrorCode.REPOSITORY_NOT_FOUND) {
                return null;
            }
            throw notFound;
        }
    }

    private UriComponentsBuilder repositoryUri(String owner, String repository) {
        return UriComponentsBuilder.fromUriString(apiUrl)
                .pathSegment("repos", owner, repository);
    }

    private <T> T get(URI uri, String accessToken, Class<T> type, ErrorCode notFound) {
        try {
            return restClient.get()
                    .uri(uri)
                    .header(HttpHeaders.AUTHORIZATION, BEARER_PREFIX + accessToken)
                    .retrieve()
                    .body(type);
        } catch (RestClientResponseException failure) {
            throw new CustomException(translate(failure, notFound));
        } catch (RestClientException unreachable) {
            throw new CustomException(ErrorCode.GITHUB_UNAVAILABLE);
        }
    }

    /**
     * GitHub은 한도 초과와 권한 부족을 모두 403으로 응답한다. 남은 호출 수가 0일 때만
     * 한도 초과이며, 이 둘을 뭉뚱그리면 사용자에게 "잠시 후 재시도"와 "권한 없음" 중
     * 잘못된 안내를 하게 된다.
     */
    private ErrorCode translate(RestClientResponseException failure, ErrorCode notFound) {
        HttpStatusCode status = failure.getStatusCode();
        if (status.value() == 429 || (status.value() == 403 && rateLimitExhausted(failure))) {
            return ErrorCode.GITHUB_RATE_LIMITED;
        }
        if (status.value() == 401) {
            return ErrorCode.GITHUB_TOKEN_INVALID;
        }
        if (status.value() == 403) {
            return ErrorCode.REPOSITORY_ACCESS_DENIED;
        }
        if (status.value() == 404) {
            return notFound;
        }
        if (status.is5xxServerError()) {
            return ErrorCode.GITHUB_UNAVAILABLE;
        }
        return ErrorCode.GITHUB_UNAVAILABLE;
    }

    private boolean rateLimitExhausted(RestClientResponseException failure) {
        String remaining = failure.getResponseHeaders() == null
                ? null
                : failure.getResponseHeaders().getFirst(RATE_LIMIT_REMAINING);
        return "0".equals(remaining);
    }
}
