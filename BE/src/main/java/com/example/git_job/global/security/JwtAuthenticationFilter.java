package com.example.git_job.global.security;

import com.example.git_job.auth.domain.Role;
import com.example.git_job.global.logging.TraceIdFilter;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.slf4j.MDC;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * REST 요청의 세션 토큰을 검증해 SecurityContext에 인증 사용자를 설정한다.
 * 토큰은 HttpOnly 쿠키 {@code SESSION}에서 읽고, 없을 때만 Bearer 헤더를 본다.
 *
 * <p>이 필터는 <b>거절하지 않는다.</b> 토큰이 없으면 그대로 통과시키고, 토큰이 있는데
 * 만료·위조·형식 오류로 유효하지 않으면 SecurityContext를 비운 채 통과시킨다 — 즉
 * 익명 요청과 같아진다. 허용 여부는 SecurityConfig의 인가 규칙이 정한다. 공개 경로는
 * 열리고, {@code authenticated()}·{@code hasRole()} 경로는 {@code ExceptionTranslationFilter}가
 * {@link JwtAuthenticationEntryPoint}로 401을 내리므로 응답 형태는 이전과 같다.</p>
 *
 * <p>이전에는 무효 토큰을 경로와 무관하게 여기서 즉시 401로 끊었다(위조 토큰이 공개
 * 경로에서 조용히 무시되는 것을 막으려는 의도). 그러나 공개 경로에서 무시된 위조 토큰은
 * 아무 권한도 얻지 못하므로 막는 것이 없었고, 대신 <b>만료된 세션 쿠키를 가진 사용자가
 * 로그인 진입점({@code /api/v1/auth/github})조차 401을 받아 재로그인이 막혔다</b>
 * (2026-09-11 로컬 재현). 세션 수명이 30분이고 로그아웃 API가 없어, 탭을 열어 둔 사용자는
 * 쿠키를 손으로 지우기 전까지 서비스에 돌아올 수 없었다. 공개 모니터링 화면도 같은 이유로
 * 열리지 않았다. 브라우저가 만료 쿠키를 자동으로 실어 보내는 것은 정상 동작이므로, 서버가
 * 그것을 "무효 토큰"이 아니라 "없는 토큰"처럼 다루는 편이 맞다.</p>
 */
@Component
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final String BEARER_PREFIX = "Bearer ";
    private static final String SESSION_COOKIE = "SESSION";
    private static final String TOKEN_REFRESH_PATH = "/api/v1/auth/refresh";

    private final JwtTokenProvider jwtTokenProvider;

    /**
     * 토큰 갱신 요청은 이 필터를 건너뛴다 (S15P11E207-1715).
     *
     * <p>갱신은 Access Token이 <b>이미 만료된 상태</b>에서 호출된다. 필터가 무효 토큰을
     * 익명으로 통과시키게 바뀐 뒤에는 건너뛰지 않아도 Controller에 닿지만, 갱신 경로에서
     * 만료 토큰을 파싱하는 일 자체가 불필요하므로 그대로 둔다. 인증은 HttpOnly 쿠키의
     * Refresh Token으로 대신한다.</p>
     */
    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return TOKEN_REFRESH_PATH.equals(request.getServletPath());
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String token = resolveToken(request);

        if (token == null) {
            filterChain.doFilter(request, response);
            return;
        }

        try {
            Claims claims = jwtTokenProvider.parseClaims(token);
            String role = claims.get("role", String.class);
            String nickname = claims.get("nickname", String.class);
            String tokenType = claims.get("tokenType", String.class);
            String tokenId = claims.getId();

            if (!"ACCESS".equals(tokenType)) {
                throw new JwtException("JWT token type is invalid");
            }

            // 로그아웃된 토큰은 만료 전이라도 blacklist(jti 기준)로 차단한다.
            // jti 없는 토큰은 blacklist 등록이 불가능하므로 처음부터 거절한다.
            if (tokenId == null
                    || tokenId.isBlank()
                    ) {
                throw new JwtException("JWT token is blacklisted or has no jti");
            }

            Role parsedRole;
            try {
                parsedRole = Role.valueOf(role);
            } catch (IllegalArgumentException | NullPointerException exception) {
                throw new JwtException("JWT role claim is invalid");
            }


            AuthenticatedUser principal = new AuthenticatedUser(
                    claims.getSubject(),
                    nickname,
                    tokenId,
                    claims.getExpiration().toInstant(),
                    parsedRole
            );

            UsernamePasswordAuthenticationToken authentication =
                    new UsernamePasswordAuthenticationToken(
                            principal,
                            null,
                            List.of(new SimpleGrantedAuthority("ROLE_" + role))
                    );
            SecurityContextHolder.getContext().setAuthentication(authentication);
            // 이 요청에서 이후 남는 모든 로그가 사용자 식별자를 함께 갖도록 MDC에 싣는다.
            // 정리는 TraceIdFilter가 요청 종료 시 일괄 수행한다(S15P11E207-1582).
            MDC.put(TraceIdFilter.USER_ID, principal.userId());
        } catch (JwtException | IllegalArgumentException exception) {
            // 무효 토큰은 익명으로 다룬다. 여기서 401을 커밋하지 않는다 — 허용 여부는 뒤의
            // 인가 규칙이 정하고, 거절될 때는 ExceptionTranslationFilter가 같은 EntryPoint로
            // 같은 봉투를 내린다. 원인(만료·위조·blacklist)은 남기지 않는다: 토큰 내용이
            // 섞일 수 있고, 공격자에게 어떤 검증에서 걸렸는지 알려 줄 이유도 없다.
            SecurityContextHolder.clearContext();
        }

        filterChain.doFilter(request, response);
    }

    /**
     * 인증 계약은 HttpOnly 세션 쿠키 {@code SESSION}이다(B조 API 명세서 v1.0 §2-1).
     * 브라우저가 자동으로 실어 보내므로 쿠키를 먼저 보고, 쿠키가 없을 때만
     * {@code Authorization} 헤더를 확인한다. 헤더 경로를 남겨 두는 것은 도구·테스트에서
     * 쿠키 없이 호출하는 경우를 위한 것이며, 브라우저 클라이언트는 쿠키만 사용한다.
     */
    private String resolveToken(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (Cookie cookie : cookies) {
                if (SESSION_COOKIE.equals(cookie.getName())
                        && cookie.getValue() != null
                        && !cookie.getValue().isBlank()) {
                    return cookie.getValue();
                }
            }
        }

        String authorization = request.getHeader("Authorization");
        if (authorization != null && authorization.startsWith(BEARER_PREFIX)) {
            return authorization.substring(BEARER_PREFIX.length());
        }
        return null;
    }
}

