package com.example.git_job.global.config;

import java.util.List;
import lombok.Getter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * GitHub OAuth 설정값 (B-FN-001 / GH-AUTH-001).
 *
 * <p>client secret은 이 객체 밖으로 나가지 않는다. 로그·응답·예외 메시지에
 * 담지 않으며, toString을 만들지 않는 이유도 같다.</p>
 */
@Getter
@Component
public class GithubOAuthProperties {

    private final String clientId;
    private final String clientSecret;
    private final String redirectUri;
    private final String apiUrl;
    private final String frontendCallbackUrl;
    private final List<String> allowedRedirectPaths;

    public GithubOAuthProperties(
            @Value("${github.oauth.client-id}") String clientId,
            @Value("${github.oauth.client-secret}") String clientSecret,
            @Value("${github.oauth.redirect-uri}") String redirectUri,
            @Value("${github.oauth.api-url}") String apiUrl,
            @Value("${github.oauth.frontend-callback-url}") String frontendCallbackUrl,
            @Value("${github.oauth.allowed-redirect-paths}") List<String> allowedRedirectPaths
    ) {
        this.clientId = clientId;
        this.clientSecret = clientSecret;
        this.redirectUri = redirectUri;
        this.apiUrl = apiUrl;
        this.frontendCallbackUrl = frontendCallbackUrl;
        this.allowedRedirectPaths = List.copyOf(allowedRedirectPaths);
    }

    /**
     * {@code redirectTo}를 검증 없이 Location에 넣으면 open redirect가 된다.
     * 명세는 "서버 화이트리스트로 검증, 절대 URL 금지"를 요구한다.
     *
     * <p>{@code //evil.com}은 프로토콜 상대 URL로 외부 호스트로 나가므로,
     * {@code /}로 시작하는지만 보는 검사로는 막을 수 없다. 별도로 거른다.</p>
     */
    public boolean isAllowedRedirectPath(String path) {
        if (path == null || path.isBlank()) {
            return false;
        }
        if (!path.startsWith("/") || path.startsWith("//")) {
            return false;
        }
        return allowedRedirectPaths.contains(path);
    }

    /** redirectTo가 없을 때 쓰는 기본 목적지. 목록의 첫 항목이다. */
    public String defaultRedirectPath() {
        return allowedRedirectPaths.isEmpty() ? "/" : allowedRedirectPaths.get(0);
    }
}
