package com.example.git_job.global.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import jakarta.servlet.http.Cookie;
import java.time.Instant;
import java.util.Date;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

/**
 * 필터는 인증만 세우고 거절은 하지 않는다 — 그 계약을 고정한다.
 *
 * <p>핵심은 두 번째 테스트다. 이전 구현은 무효 토큰을 경로와 무관하게 401로 끊었고,
 * 그래서 만료된 세션 쿠키를 가진 브라우저는 공개 경로(로그인 진입점, 공개 모니터링)조차
 * 열 수 없었다. 필터가 다시 거절하는 쪽으로 돌아가면 여기서 걸린다.</p>
 */
class JwtAuthenticationFilterTest {

    private JwtTokenProvider tokenProvider;
    private JwtAuthenticationFilter filter;
    private MockHttpServletResponse response;
    private MockFilterChain chain;

    @BeforeEach
    void setUp() {
        tokenProvider = mock(JwtTokenProvider.class);
        filter = new JwtAuthenticationFilter(tokenProvider);
        response = new MockHttpServletResponse();
        chain = new MockFilterChain();
    }

    @AfterEach
    void cleanUp() {
        SecurityContextHolder.clearContext();
        MDC.clear();
    }

    private MockHttpServletRequest requestWithSession(String token) {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/admin/monitoring/overview");
        request.setCookies(new Cookie("SESSION", token));
        return request;
    }

    @Test
    @DisplayName("토큰이 없으면 익명으로 통과한다")
    void passesThroughWithoutToken() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/auth/github");

        filter.doFilter(request, response, chain);

        assertThat(chain.getRequest()).as("체인이 이어졌다").isNotNull();
        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("만료·위조 토큰은 401로 끊지 않고 익명으로 통과시킨다")
    void treatsInvalidTokenAsAnonymous() throws Exception {
        when(tokenProvider.parseClaims(anyString()))
                .thenThrow(new ExpiredJwtException(null, null, "expired"));

        filter.doFilter(requestWithSession("stale.session.cookie"), response, chain);

        // 이전 구현이 한 일 — EntryPoint 호출로 401 커밋 — 이 더는 일어나지 않는다.
        assertThat(response.getStatus()).as("필터가 상태 코드를 정하지 않는다").isEqualTo(200);
        assertThat(response.isCommitted()).isFalse();
        assertThat(response.getContentAsString()).isEmpty();
        assertThat(chain.getRequest()).as("인가 단계가 판단하도록 체인을 잇는다").isNotNull();
        assertThat(SecurityContextHolder.getContext().getAuthentication())
                .as("무효 토큰으로는 어떤 인증도 세우지 않는다").isNull();
    }

    @Test
    @DisplayName("유효한 ACCESS 토큰은 role 권한으로 인증을 세운다")
    void authenticatesValidToken() throws Exception {
        Claims claims = mock(Claims.class);
        when(claims.get("role", String.class)).thenReturn("USER");
        when(claims.get("nickname", String.class)).thenReturn("tester");
        when(claims.get("tokenType", String.class)).thenReturn("ACCESS");
        when(claims.getId()).thenReturn("jti-1");
        when(claims.getSubject()).thenReturn("42");
        when(claims.getExpiration()).thenReturn(Date.from(Instant.now().plusSeconds(600)));
        when(tokenProvider.parseClaims(anyString())).thenReturn(claims);

        filter.doFilter(requestWithSession("valid.token"), response, chain);

        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        assertThat(authentication).isNotNull();
        assertThat(authentication.getAuthorities())
                .extracting("authority").containsExactly("ROLE_USER");
        assertThat(authentication.getPrincipal()).isInstanceOf(AuthenticatedUser.class);
        assertThat(((AuthenticatedUser) authentication.getPrincipal()).userId()).isEqualTo("42");
        assertThat(chain.getRequest()).isNotNull();
    }

    @Test
    @DisplayName("ACCESS 가 아닌 토큰 타입은 인증을 세우지 않고 통과한다")
    void ignoresNonAccessTokenType() throws Exception {
        Claims claims = mock(Claims.class);
        when(claims.get("tokenType", String.class)).thenReturn("REFRESH");
        when(claims.get("role", String.class)).thenReturn("USER");
        when(claims.get("nickname", String.class)).thenReturn("tester");
        when(claims.getId()).thenReturn("jti-2");
        when(tokenProvider.parseClaims(anyString())).thenReturn(claims);

        filter.doFilter(requestWithSession("refresh.token"), response, chain);

        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(chain.getRequest()).isNotNull();
    }
}
