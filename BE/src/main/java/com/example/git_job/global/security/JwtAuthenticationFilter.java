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
 * <p>토큰이 없는 요청은 여기서 거절하지 않고 통과시킨다. 공개 경로는 그대로
 * 허용되고, 인증 필요 경로는 SecurityConfig의 {@code authenticated()} 규칙이
 * 거절한다. 반면 토큰이 있는데 유효하지 않으면 경로와 무관하게 즉시 401로
 * 응답해, 위조 토큰이 공개 경로를 통해 조용히 무시되는 상황을 막는다.</p>
 */
@Component
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final String BEARER_PREFIX = "Bearer ";
    private static final String SESSION_COOKIE = "SESSION";
    private static final String TOKEN_REFRESH_PATH = "/api/v1/auth/refresh";

    private final JwtTokenProvider jwtTokenProvider;
    private final JwtAuthenticationEntryPoint authenticationEntryPoint;

    /**
     * 토큰 갱신 요청은 이 필터를 건너뛴다 (S15P11E207-1715).
     *
     * <p>갱신은 Access Token이 <b>이미 만료된 상태</b>에서 호출된다. 이 필터는
     * 토큰이 있는데 유효하지 않으면 경로와 무관하게 401로 끊으므로, 건너뛰지
     * 않으면 만료된 Header가 함께 실려온 갱신 요청이 Controller에 닿지 못한다.
     * 클라이언트가 Header를 빼주기를 기대하는 것보다 서버에서 보장하는 편이
     * 안전하다. 인증은 HttpOnly 쿠키의 Refresh Token으로 대신한다.</p>
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
            SecurityContextHolder.clearContext();
            authenticationEntryPoint.commence(request, response, null);
            return;
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

