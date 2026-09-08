package com.example.git_job.global.web;

import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;

/**
 * 인증 관련 쿠키를 한곳에서 만든다. 이름·수명·속성은 B조 API 명세서 v1.0을 따른다.
 *
 * <p>세 쿠키 모두 {@code SameSite=Lax}다. {@code Strict}로 두면 github.com에서
 * 돌아오는 콜백 요청에 쿠키가 실리지 않아 state 검증이 항상 실패한다.</p>
 */
@Component
public class CookieUtil {

    /** OAuth state 보관용 단기 쿠키. 콜백에서 쿼리 state와 대조한다. */
    public static final String OAUTH_STATE = "OAUTH_STATE";

    /**
     * 로그인 후 돌아갈 FE 경로. 명세는 이 쿠키를 정의하지 않지만, 진입 시 받은
     * {@code redirectTo}를 콜백까지 나를 방법이 명세에 없어 state와 같은 수명의
     * 단기 쿠키로 보관한다. 콜백에서 화이트리스트로 다시 검증한다.
     */
    public static final String OAUTH_REDIRECT = "OAUTH_REDIRECT";

    /** 인증 세션 쿠키. 명세 §2-1의 이름을 그대로 쓴다. */
    public static final String SESSION = "SESSION";

    private static final Duration OAUTH_TTL = Duration.ofMinutes(10);

    private final boolean secure;

    public CookieUtil(@Value("${cookie.secure}") boolean secure) {
        this.secure = secure;
    }

    public ResponseCookie oauthState(String state) {
        return shortLived(OAUTH_STATE, state);
    }

    public ResponseCookie oauthRedirect(String redirectTo) {
        return shortLived(OAUTH_REDIRECT, redirectTo);
    }

    public ResponseCookie session(String token, Duration maxAge) {
        return base(SESSION, token).maxAge(maxAge).build();
    }

    /** 즉시 만료시켜 브라우저에서 지운다. state·redirect 쿠키는 1회용이다. */
    public ResponseCookie expired(String name) {
        return base(name, "").maxAge(Duration.ZERO).build();
    }

    private ResponseCookie shortLived(String name, String value) {
        return base(name, value).maxAge(OAUTH_TTL).build();
    }

    private ResponseCookie.ResponseCookieBuilder base(String name, String value) {
        return ResponseCookie.from(name, value)
                .httpOnly(true)
                .secure(secure)
                .sameSite("Lax")
                .path("/");
    }
}
