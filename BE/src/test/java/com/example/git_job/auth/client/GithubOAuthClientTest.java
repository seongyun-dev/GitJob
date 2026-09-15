package com.example.git_job.auth.client;

import static org.assertj.core.api.Assertions.assertThat;

import com.example.git_job.global.config.GithubOAuthProperties;
import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * authorize URL 조립 계약을 고정한다. 특히 {@code prompt=select_account} 는
 * 로그아웃 직후 재로그인이 화면 없이 즉시 인가되는 것을 끊는 근거라 회귀로 지킨다.
 */
class GithubOAuthClientTest {

    private GithubOAuthClient client() {
        GithubOAuthProperties properties = new GithubOAuthProperties(
                "cid", "secret",
                "http://localhost:8080/api/v1/auth/github/callback",
                "https://api.github.com",
                "http://localhost:8080/auth/callback",
                List.of("/onboarding/repositories", "/"));
        return new GithubOAuthClient(properties);
    }

    @Test
    void authorizeUrlForcesAccountPicker() {
        // 이 파라미터가 없으면 github.com 세션이 살아 있는 사용자는 authorize가
        // 즉시 콜백으로 튕겨, 로그아웃 후 다시 로그인해도 계정 선택 없이 자동 로그인된다.
        assertThat(client().buildAuthorizeUrl("st_abc")).contains("prompt=select_account");
    }

    @Test
    void authorizeUrlCarriesClientRedirectScopeAndState() {
        String url = client().buildAuthorizeUrl("st_abc");

        assertThat(url).startsWith("https://github.com/login/oauth/authorize");
        assertThat(url).contains("client_id=cid");
        assertThat(url).contains("redirect_uri=http://localhost:8080/api/v1/auth/github/callback");
        // scope 의 공백만 인코딩된다(query 컴포넌트라 : / 는 그대로).
        assertThat(url).contains("scope=read:user%20repo");
        assertThat(url).contains("state=st_abc");
    }
}
