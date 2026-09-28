package com.example.git_job.global.config;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class GithubOAuthPropertiesTest {

    private static final List<String> ALLOWED = List.of("/onboarding/repositories", "/repos", "/");

    private GithubOAuthProperties properties() {
        return new GithubOAuthProperties(
                "client-id", "client-secret",
                "http://localhost:8080/api/v1/auth/github/callback",
                "https://api.github.com",
                "http://localhost:8080/auth/callback",
                ALLOWED
        );
    }

    @Test
    @DisplayName("허용 목록에 있는 경로만 통과한다")
    void allowsWhitelistedPathsOnly() {
        GithubOAuthProperties properties = properties();

        assertThat(properties.isAllowedRedirectPath("/onboarding/repositories")).isTrue();
        assertThat(properties.isAllowedRedirectPath("/repos")).isTrue();
        assertThat(properties.isAllowedRedirectPath("/repos/extra")).isFalse();
        assertThat(properties.isAllowedRedirectPath("/admin")).isFalse();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "https://evil.com",           // 절대 URL
            "http://evil.com/repos",
            "//evil.com",                 // 프로토콜 상대 URL — "/"로 시작하므로 단순 검사로는 통과한다
            "//evil.com/repos",
            "repos",                      // 상대 경로
    })
    @DisplayName("외부 호스트로 나갈 수 있는 값은 모두 거부한다 (open redirect 방지)")
    void rejectsOffsiteRedirects(String candidate) {
        assertThat(properties().isAllowedRedirectPath(candidate)).isFalse();
    }

    @Test
    @DisplayName("빈 값은 거부하고, 기본 목적지는 허용 목록의 첫 항목이다")
    void handlesEmptyValues() {
        GithubOAuthProperties properties = properties();

        assertThat(properties.isAllowedRedirectPath(null)).isFalse();
        assertThat(properties.isAllowedRedirectPath("   ")).isFalse();
        assertThat(properties.defaultRedirectPath()).isEqualTo("/onboarding/repositories");
    }
}
