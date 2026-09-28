package com.example.git_job.auth.client;

import com.example.git_job.auth.client.dto.GithubEmailResponse;
import com.example.git_job.auth.client.dto.GithubUserResponse;
import com.example.git_job.global.config.GithubOAuthProperties;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/** 발급받은 Access Token으로 GitHub 사용자 정보를 조회한다. */
@Component
public class GithubUserClient {

    private static final String BEARER_PREFIX = "Bearer ";

    private final RestClient restClient;

    public GithubUserClient(GithubOAuthProperties properties) {
        this.restClient = RestClient.builder()
                .baseUrl(properties.getApiUrl())
                .defaultHeader(HttpHeaders.ACCEPT, "application/vnd.github+json")
                .defaultHeader("X-GitHub-Api-Version", "2022-11-28")
                .build();
    }

    /**
     * 사용자 식별 정보를 가져온다. 이 호출이 성공해야 발급된 Token이 실제로
     * 동작한다는 것이 확인된다(티켓 완료 기준: "발급된 토큰으로 GitHub API 호출 1건이 성공한다").
     */
    public GithubUserResponse fetchUser(String accessToken) {
        GithubUserResponse user;
        try {
            user = restClient.get()
                    .uri("/user")
                    .header(HttpHeaders.AUTHORIZATION, BEARER_PREFIX + accessToken)
                    .retrieve()
                    .body(GithubUserResponse.class);
        } catch (RestClientException exception) {
            throw new CustomException(ErrorCode.OAUTH_GITHUB_UNAVAILABLE);
        }

        if (user == null || user.id() == null || user.login() == null) {
            throw new CustomException(ErrorCode.OAUTH_TOKEN_EXCHANGE_FAILED);
        }
        return user;
    }

    /**
     * {@code /user}의 email이 null일 때만 호출한다. primary이면서 verified인 주소만
     * 채택하고, 없으면 null을 반환한다. email은 nullable 컬럼이므로(GH-AUTH-001)
     * 조회 실패로 로그인을 막지 않는다.
     */
    public String fetchPrimaryVerifiedEmail(String accessToken) {
        GithubEmailResponse[] emails;
        try {
            emails = restClient.get()
                    .uri("/user/emails")
                    .header(HttpHeaders.AUTHORIZATION, BEARER_PREFIX + accessToken)
                    .retrieve()
                    .body(GithubEmailResponse[].class);
        } catch (RestClientException exception) {
            return null;
        }

        if (emails == null) {
            return null;
        }
        for (GithubEmailResponse candidate : emails) {
            if (candidate.primary() && candidate.verified()) {
                return candidate.email();
            }
        }
        return null;
    }
}
