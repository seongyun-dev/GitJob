package com.example.git_job.global.web;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseCookie;

class CookieUtilTest {

    @Test
    @DisplayName("OAUTH_STATE는 HttpOnly·SameSite=Lax·10분 만료로 발급된다")
    void oauthStateFollowsSpec() {
        ResponseCookie cookie = new CookieUtil(false).oauthState("st_abc");

        assertThat(cookie.getName()).isEqualTo("OAUTH_STATE");
        assertThat(cookie.getValue()).isEqualTo("st_abc");
        assertThat(cookie.isHttpOnly()).isTrue();
        assertThat(cookie.getPath()).isEqualTo("/");
        assertThat(cookie.getMaxAge()).isEqualTo(Duration.ofMinutes(10));
    }

    @Test
    @DisplayName("SameSite는 Lax다 — Strict면 GitHub에서 돌아오는 콜백에 쿠키가 실리지 않는다")
    void sameSiteMustBeLax() {
        CookieUtil cookieUtil = new CookieUtil(false);

        assertThat(cookieUtil.oauthState("st_abc").getSameSite()).isEqualTo("Lax");
        assertThat(cookieUtil.oauthRedirect("/repos").getSameSite()).isEqualTo("Lax");
        assertThat(cookieUtil.session("jwt", Duration.ofMinutes(30)).getSameSite()).isEqualTo("Lax");
    }

    @Test
    @DisplayName("SESSION은 전달받은 수명으로 발급되고 COOKIE_SECURE를 따른다")
    void sessionCookie() {
        ResponseCookie insecure = new CookieUtil(false).session("jwt", Duration.ofMinutes(30));
        ResponseCookie secure = new CookieUtil(true).session("jwt", Duration.ofMinutes(30));

        assertThat(insecure.getName()).isEqualTo("SESSION");
        assertThat(insecure.isHttpOnly()).isTrue();
        assertThat(insecure.isSecure()).isFalse();
        assertThat(insecure.getMaxAge()).isEqualTo(Duration.ofMinutes(30));
        assertThat(secure.isSecure()).isTrue();
    }

    @Test
    @DisplayName("만료 쿠키는 값이 비고 Max-Age가 0이다")
    void expiredCookie() {
        ResponseCookie cookie = new CookieUtil(false).expired(CookieUtil.OAUTH_STATE);

        assertThat(cookie.getValue()).isEmpty();
        assertThat(cookie.getMaxAge()).isZero();
    }
}
