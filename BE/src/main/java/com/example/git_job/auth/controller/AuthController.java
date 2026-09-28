package com.example.git_job.auth.controller;

import com.example.git_job.auth.controller.dto.AdminLoginRequest;
import com.example.git_job.auth.controller.dto.MeResponse;
import com.example.git_job.auth.service.AdminLoginService;
import com.example.git_job.auth.service.AuthQueryService;
import com.example.git_job.auth.service.GithubOAuthService;
import com.example.git_job.global.config.GithubOAuthProperties;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.response.ApiResponse;
import com.example.git_job.global.security.AuthenticatedUser;
import com.example.git_job.global.web.CookieUtil;
import java.net.URI;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
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
    private final AuthQueryService authQueryService;
    private final AdminLoginService adminLoginService;
    private final GithubOAuthProperties properties;
    private final CookieUtil cookieUtil;

    /**
     * 현재 로그인 사용자 요약 · 티켓 S15P21E102-246.
     *
     * <p>헤더 프로필 영역이 부른다. 인증이 필요한 경로라, 세션이 없거나 만료되면
     * SecurityConfig가 401(AUTH-401-1)로 응답한다. FE는 200이면 로그인 상태로 이름·아바타를
     * 그리고, 401이면 로그아웃 상태로 로그인 버튼을 그린다. 즉 이 한 경로가 로그인 여부의
     * 단일 출처다 — 세션이 HttpOnly 쿠키라 FE가 직접 읽을 수 없기 때문이다.</p>
     */
    @GetMapping("/me")
    public ApiResponse<MeResponse> me(@AuthenticationPrincipal AuthenticatedUser user) {
        return ApiResponse.success(authQueryService.me(user));
    }

    /**
     * 로그아웃 · 티켓 S15P21E102-246.
     *
     * <p>세션 쿠키를 만료시킨다. 인증 없이도 동작해야 하므로(만료된 쿠키를 든 사용자가
     * 정리하려는 상황) SecurityConfig에서 공개한다. 서버측 blacklist는 두지 않는다 —
     * 저장소가 없고, 쿠키를 지우면 브라우저가 더는 토큰을 싣지 않는다. 탈취된 토큰은
     * 만료(30분)까지 유효하다는 기존 한계는 그대로다.</p>
     */
    @PostMapping("/logout")
    public ResponseEntity<ApiResponse<Void>> logout() {
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, cookieUtil.expired(CookieUtil.SESSION).toString())
                .body(ApiResponse.success());
    }

    /**
     * 관리자 전용 ID/PW 로그인. GitHub OAuth 없이 관리자 화면에 들어가기 위한 진입점이다.
     *
     * <p>세션 발급 이전 단계라 인증이 필요 없고 SecurityConfig에서 공개한다. 성공하면
     * OAuth 콜백과 동일하게 SESSION 쿠키를 심는다 — 이후 요청은 GitHub 로그인과 구분 없이
     * 그 세션으로 동작한다. 실패는 원인을 구분하지 않고 401(AUTH-401-1)로 접는다.</p>
     */
    @PostMapping("/admin-login")
    public ResponseEntity<ApiResponse<Void>> adminLogin(@RequestBody AdminLoginRequest request) {
        AdminLoginService.LoginSession session =
                adminLoginService.login(request.id(), request.password());

        return ResponseEntity.ok()
                .header(
                        HttpHeaders.SET_COOKIE,
                        cookieUtil.session(session.sessionToken(), session.maxAge()).toString()
                )
                .body(ApiResponse.success());
    }

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
