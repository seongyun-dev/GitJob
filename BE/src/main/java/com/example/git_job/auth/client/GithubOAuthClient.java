package com.example.git_job.auth.client;

import com.example.git_job.auth.client.dto.GithubTokenResponse;
import com.example.git_job.global.config.GithubOAuthProperties;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.util.UriComponentsBuilder;

/** GitHub OAuth 인증 URL 생성과 code ↔ Access Token 교환만 담당한다. */
@Component
public class GithubOAuthClient {

    /**
     * B조 API 명세서 v1.0은 요청 scope를 {@code read:user}, {@code repo}로 고정한다.
     * 티켓의 "scope 2단 동의"는 구 API 명세서 기준이며 v1.0에서 고정으로 바뀌었다.
     */
    public static final String REQUIRED_SCOPE = "read:user repo";

    private static final String AUTHORIZE_URL = "https://github.com/login/oauth/authorize";
    private static final String TOKEN_URL = "https://github.com/login/oauth/access_token";

    private final RestClient restClient;
    private final GithubOAuthProperties properties;

    public GithubOAuthClient(GithubOAuthProperties properties) {
        this.restClient = RestClient.create();
        this.properties = properties;
    }

    public String buildAuthorizeUrl(String state) {
        return UriComponentsBuilder.fromUriString(AUTHORIZE_URL)
                .queryParam("client_id", properties.getClientId())
                .queryParam("redirect_uri", properties.getRedirectUri())
                .queryParam("scope", REQUIRED_SCOPE)
                .queryParam("state", state)
                // 계정 선택 화면을 강제한다. 없으면 github.com 세션이 살아 있고 앱이 이미
                // 인가된 사용자는 authorize가 화면 없이 즉시 콜백으로 튕겨, 로그아웃 직후
                // 다시 로그인하면 "자동 로그인"된 것처럼 보인다. GitHub이 2024-06부터
                // 지원하는 표준 파라미터로, 매번 계정 선택을 거치게 해 이 즉시 인가를 끊는다.
                .queryParam("prompt", "select_account")
                .build()
                .encode()
                .toUriString();
    }

    /**
     * code를 Access Token으로 교환한다.
     *
     * <p>예외 원인을 그대로 전파하지 않는다. RestClient의 예외 메시지에는 요청 본문
     * 조각이 섞일 수 있고 그 본문에는 {@code code}와 {@code client_secret}이 들어 있다.</p>
     */
    public GithubTokenResponse exchangeCode(String code) {
        MultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("client_id", properties.getClientId());
        form.add("client_secret", properties.getClientSecret());
        form.add("code", code);
        form.add("redirect_uri", properties.getRedirectUri());

        GithubTokenResponse response;
        try {
            response = restClient.post()
                    .uri(TOKEN_URL)
                    .accept(MediaType.APPLICATION_JSON)
                    .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                    .body(form)
                    .retrieve()
                    .body(GithubTokenResponse.class);
        } catch (RestClientException exception) {
            throw new CustomException(ErrorCode.OAUTH_GITHUB_UNAVAILABLE);
        }

        // 잘못된·만료된·재사용된 code는 200 + error 필드로 돌아온다.
        if (response == null || !response.isSuccess()) {
            throw new CustomException(ErrorCode.OAUTH_TOKEN_EXCHANGE_FAILED);
        }
        return response;
    }
}
