package com.example.git_job.auth.controller;

import com.example.git_job.auth.service.GithubOAuthService;
import com.example.git_job.global.config.GithubOAuthProperties;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.web.CookieUtil;
import java.net.URI;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * GitHub OAuth 진입·콜백 (B-FN-001 / GH-AUTH-001).
 *
 * <p>두 경로 모두 세션 발급 이전 단계라 인증이 필요 없고, SecurityConfig에서
 * 공개되어 있다. 콜백은 결과와 무관하게 FE 안내 화면으로 302하며, state를 신뢰할 수
 * 없는 단계의 실패만 GlobalExceptionHandler를 통해 JSON으로 응답한다.</p>
 */
@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
public class AuthController {

    private final GithubOAuthService githubOAuthService;
    private final GithubOAuthProperties properties;
    private final CookieUtil cookieUtil;

    /**
     * GitHub 인증 화면으로 302한다. FE는 이 경로를 링크로 열기만 하고
     * GitHub URL을 직접 조립하지 않는다(명세).
     */
    @GetMapping("/github")
    public ResponseEntity<Void> enterGithubLogin(
            @RequestParam(required = false) String redirectTo
    ) {
        GithubOAuthService.AuthorizeRedirect redirect = githubOAuthService.startLogin(redirectTo);

        return ResponseEntity.status(HttpStatus.FOUND)
                .location(URI.create(redirect.authorizeUrl()))
                .header(HttpHeaders.SET_COOKIE, cookieUtil.oauthState(redirect.state()).toString())
                .header(HttpHeaders.SET_COOKIE, cookieUtil.oauthRedirect(redirect.redirectTo()).toString())
                .build();
    }

    @GetMapping("/github/callback")
    public ResponseEntity<Void> githubCallback(
            @RequestParam(required = false) String code,
            @RequestParam(required = false) String state,
            @RequestParam(required = false) String error,
            @CookieValue(name = CookieUtil.OAUTH_STATE, required = false) String cookieState,
            @CookieValue(name = CookieUtil.OAUTH_REDIRECT, required = false) String cookieRedirect
    ) {
        // 권한 거부는 오류가 아니라 사용자의 선택이다. 재시도를 안내할 수 있게 화면으로 보낸다.
        if (error != null && !error.isBlank()) {
            return clearOauthCookies(ResponseEntity.status(HttpStatus.FOUND)
                    .location(frontendUri("denied", ErrorCode.OAUTH_ACCESS_DENIED.getCode(), null)));
        }

        GithubOAuthService.LoginSession session =
                githubOAuthService.completeLogin(code, state, cookieState);

        // 쿠키도 사용자가 조작할 수 있으므로 복귀 경로를 여기서 다시 검증한다.
        String redirectTo = properties.isAllowedRedirectPath(cookieRedirect)
                ? cookieRedirect
                : properties.defaultRedirectPath();

        return clearOauthCookies(ResponseEntity.status(HttpStatus.FOUND)
                .location(frontendUri("success", null, redirectTo))
                .header(
                        HttpHeaders.SET_COOKIE,
                        cookieUtil.session(session.sessionToken(), session.maxAge()).toString()
                ));
    }

    /** state·복귀 경로 쿠키는 1회용이다. 성공·실패 모두 콜백에서 지운다. */
    private ResponseEntity<Void> clearOauthCookies(ResponseEntity.BodyBuilder builder) {
        return builder
                .header(HttpHeaders.SET_COOKIE, cookieUtil.expired(CookieUtil.OAUTH_STATE).toString())
                .header(HttpHeaders.SET_COOKIE, cookieUtil.expired(CookieUtil.OAUTH_REDIRECT).toString())
                .build();
    }

    private URI frontendUri(String status, String errorCode, String redirectTo) {
        UriComponentsBuilder builder = UriComponentsBuilder
                .fromUriString(properties.getFrontendCallbackUrl())
                .queryParam("status", status);

        if (errorCode != null) {
            builder.queryParam("code", errorCode);
        }
        if (redirectTo != null) {
            builder.queryParam("redirectTo", redirectTo);
        }
        return builder.build().encode().toUri();
    }
}
