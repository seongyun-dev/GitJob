package com.example.git_job.auth.service;

import com.example.git_job.auth.client.GithubOAuthClient;
import com.example.git_job.auth.client.GithubUserClient;
import com.example.git_job.auth.client.dto.GithubTokenResponse;
import com.example.git_job.auth.client.dto.GithubUserResponse;
import com.example.git_job.auth.domain.Role;
import com.example.git_job.auth.domain.User;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.global.config.GithubOAuthProperties;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.security.JwtTokenProvider;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.Base64;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * GitHub OAuth 로그인 흐름을 조립한다 (B-FN-001 / GH-AUTH-001).
 *
 * <p>외부 응답 판정은 client에 두고, 여기서는 state 검증 → code 교환 → scope 확인
 * → 사용자 upsert → 세션 토큰 발급 순서와 실패 시 오류 코드만 결정한다.</p>
 */
@Service
@RequiredArgsConstructor
public class GithubOAuthService {

    private static final String STATE_PREFIX = "st_";
    private static final int STATE_RANDOM_BYTES = 16;
    private static final SecureRandom RANDOM = new SecureRandom();

    private final GithubOAuthClient githubOAuthClient;
    private final GithubUserClient githubUserClient;
    private final UserRepository userRepository;
    private final GithubOAuthProperties properties;
    private final JwtTokenProvider jwtTokenProvider;

    /** GitHub 인증 화면으로 보낼 URL과 함께 심어야 할 state·복귀 경로를 만든다. */
    public AuthorizeRedirect startLogin(String requestedRedirectTo) {
        String redirectTo = resolveRedirectTo(requestedRedirectTo);
        String state = STATE_PREFIX + randomToken();
        return new AuthorizeRedirect(githubOAuthClient.buildAuthorizeUrl(state), state, redirectTo);
    }

    @Transactional
    public LoginSession completeLogin(String code, String state, String cookieState) {
        verifyState(state, cookieState);

        if (code == null || code.isBlank()) {
            throw new CustomException(ErrorCode.OAUTH_INVALID_STATE);
        }

        GithubTokenResponse token = githubOAuthClient.exchangeCode(code);
        verifyGrantedScope(token.scope());

        GithubUserResponse githubUser = githubUserClient.fetchUser(token.accessToken());
        String email = githubUser.email() != null && !githubUser.email().isBlank()
                ? githubUser.email()
                : githubUserClient.fetchPrimaryVerifiedEmail(token.accessToken());

        User user = upsert(githubUser, email, token);

        // 클라이언트가 보낸 값이 아니라 이 subject를 사용자 식별의 근거로 삼는다.
        String sessionToken = jwtTokenProvider.createToken(
                String.valueOf(user.getUserId()),
                Role.USER.name(),
                githubUser.login(),
                Instant.now()
        );
        return new LoginSession(sessionToken, jwtTokenProvider.getAccessTokenExpiration());
    }

    /**
     * state는 CSRF 방지값이다. 쿠키가 없으면 우리가 시작한 흐름이 아니므로 거절한다
     * (명세: "없으면 CSRF로 간주").
     *
     * <p>비교는 {@link MessageDigest#isEqual}로 한다. 일반 문자열 비교는 앞부분부터
     * 다른 지점에서 즉시 끝나 응답 시간이 값에 따라 달라진다.</p>
     */
    private void verifyState(String state, String cookieState) {
        if (state == null || state.isBlank() || cookieState == null || cookieState.isBlank()) {
            throw new CustomException(ErrorCode.OAUTH_INVALID_STATE);
        }
        boolean matched = MessageDigest.isEqual(
                state.getBytes(StandardCharsets.UTF_8),
                cookieState.getBytes(StandardCharsets.UTF_8)
        );
        if (!matched) {
            throw new CustomException(ErrorCode.OAUTH_INVALID_STATE);
        }
    }

    /**
     * GitHub은 사용자가 일부 권한만 승인해도 Token을 발급한다. 요청한 scope가
     * 실제로 승인됐는지 응답의 scope로 확인해야 한다(명세 AUTH-403-4).
     * 응답 형식은 쉼표 구분이다(예: {@code read:user,repo}).
     */
    private void verifyGrantedScope(String grantedScope) {
        Set<String> granted = grantedScope == null
                ? Set.of()
                : Arrays.stream(grantedScope.split(","))
                        .map(String::trim)
                        .filter(value -> !value.isEmpty())
                        .collect(Collectors.toSet());

        for (String required : GithubOAuthClient.REQUIRED_SCOPE.split(" ")) {
            if (!granted.contains(required)) {
                throw new CustomException(ErrorCode.OAUTH_SCOPE_NOT_GRANTED);
            }
        }
    }

    private User upsert(GithubUserResponse githubUser, String email, GithubTokenResponse token) {
        // user.name은 NOT NULL이지만 GitHub name은 프로필 미설정 시 null이다. login으로 대체한다.
        String name = githubUser.name() != null && !githubUser.name().isBlank()
                ? githubUser.name()
                : githubUser.login();

        return userRepository.findByGithubId(githubUser.id())
                .map(existing -> {
                    existing.syncFromGithub(
                            githubUser.login(), name, email, githubUser.avatarUrl(),
                            token.scope(), token.accessToken()
                    );
                    return existing;
                })
                .orElseGet(() -> userRepository.save(User.register(
                        githubUser.id(), githubUser.login(), name, email, githubUser.avatarUrl(),
                        token.scope(), token.accessToken()
                )));
    }

    private String resolveRedirectTo(String requested) {
        if (requested == null || requested.isBlank()) {
            return properties.defaultRedirectPath();
        }
        if (!properties.isAllowedRedirectPath(requested)) {
            throw new CustomException(ErrorCode.OAUTH_REDIRECT_NOT_ALLOWED);
        }
        return requested;
    }

    private String randomToken() {
        byte[] bytes = new byte[STATE_RANDOM_BYTES];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public record AuthorizeRedirect(String authorizeUrl, String state, String redirectTo) {
    }

    public record LoginSession(String sessionToken, Duration maxAge) {
    }
}
