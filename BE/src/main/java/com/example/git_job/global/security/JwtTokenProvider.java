package com.example.git_job.global.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import java.util.UUID;
import javax.crypto.SecretKey;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Access Token과 Refresh Token의 발급, 검증을 담당한다.
 *
 * <p>토큰에는 사용자 ID를 {@code subject}로, {@code nickname}, {@code role},
 * 토큰 ID({@code jti})와 만료 시각을 담는다. REST와 STOMP 인증 모두
 * 클라이언트가 보낸 사용자 ID 대신 이 토큰의 {@code subject}를 신뢰한다.</p>
 *
 * <p>{@code tokenType} claim으로 두 토큰을 구분한다. 이 claim이 없으면 수명이
 * 긴 Refresh Token을 Access Token 자리에 넣어 API를 호출할 수 있으므로,
 * 검증하는 쪽(REST Filter, STOMP Interceptor)이 반드시 확인한다.</p>
 */
@Component
public class JwtTokenProvider {

    public static final String ACCESS_TOKEN_TYPE = "ACCESS";
    public static final String REFRESH_TOKEN_TYPE = "REFRESH";

    private final SecretKey signingKey;
    private final String issuer;
    private final Duration accessTokenExpiration;
    private final Duration refreshTokenExpiration;

    public JwtTokenProvider(
            @Value("${jwt.secret}") String secret,
            @Value("${jwt.issuer}") String issuer,
            @Value("${jwt.access-token-expiration}") Duration accessTokenExpiration,
            @Value("${jwt.refresh-token-expiration}") Duration refreshTokenExpiration
    ) {
        this.signingKey = createSigningKey(secret);
        this.issuer = issuer;
        this.accessTokenExpiration = accessTokenExpiration;
        this.refreshTokenExpiration = refreshTokenExpiration;
    }

    public String createToken(String subject, String role, Instant issuedAt) {
        return createToken(
                subject,
                role,
                null,
                ACCESS_TOKEN_TYPE,
                issuedAt,
                accessTokenExpiration
        );
    }

    public String createToken(
            String subject,
            String role,
            String nickname,
            Instant issuedAt
    ) {
        return createToken(
                subject,
                role,
                nickname,
                ACCESS_TOKEN_TYPE,
                issuedAt,
                accessTokenExpiration
        );
    }

    /**
     * Refresh Token을 발급한다. 회원과 비회원 모두 같은 형식을 사용한다.
     *
     * <p>비회원은 DB에 행이 없어 회원 테이블 컬럼으로는 갱신 상태를 보관할 수
     * 없다. 그래서 발급된 토큰의 {@code jti}만 Redis에 남기고, 여기서는 서명된
     * 토큰 문자열만 만든다({@code RefreshTokenStore} 참고).</p>
     */
    public String createRefreshToken(
            String subject,
            String role,
            String nickname,
            Instant issuedAt
    ) {
        return createToken(
                subject,
                role,
                nickname,
                REFRESH_TOKEN_TYPE,
                issuedAt,
                refreshTokenExpiration
        );
    }

    private String createToken(
            String subject,
            String role,
            String nickname,
            String tokenType,
            Instant issuedAt,
            Duration expiration
    ) {
        Instant expiresAt = issuedAt.plus(expiration);
        String tokenId = UUID.randomUUID().toString();

        var tokenBuilder = Jwts.builder()
                .id(tokenId)
                .subject(subject)
                .issuer(issuer)
                .issuedAt(Date.from(issuedAt))
                .expiration(Date.from(expiresAt))
                .claim("role", role)
                .claim("tokenType", tokenType);

        if (nickname != null) {
            tokenBuilder.claim("nickname", nickname);
        }

        return tokenBuilder.signWith(signingKey).compact();
    }

    /**
     * 서명과 발급자를 검증하고 Claims를 반환한다. 서명 위조, 발급자 불일치
     * 또는 만료 시 JJWT 예외가 발생하며, 처리 방식은 호출 측(REST Filter,
     * STOMP Interceptor)이 각자 결정한다.
     */
    public Claims parseClaims(String token) {
        return Jwts.parser()
                .verifyWith(signingKey)
                .requireIssuer(issuer)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }

    public Duration getAccessTokenExpiration() {
        return accessTokenExpiration;
    }

    public Duration getRefreshTokenExpiration() {
        return refreshTokenExpiration;
    }

    // HMAC-SHA256 서명 강도를 보장하기 위해 256bit(32byte) 미만의 비밀키는
    // 애플리케이션 기동 시점에 거절한다. 짧은 키로 운영에 배포되는 것을 막는다.
    private SecretKey createSigningKey(String secret) {
        byte[] keyBytes = secret.getBytes(StandardCharsets.UTF_8);

        if (keyBytes.length < 32) {
            throw new IllegalArgumentException("JWT secret must be at least 32 bytes");
        }
        return Keys.hmacShaKeyFor(keyBytes);
    }
}

