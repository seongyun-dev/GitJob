package com.example.git_job.global.security;

import com.example.git_job.auth.domain.Role;

import java.security.Principal;
import java.time.Instant;

/**
 * 서명 검증을 통과한 JWT에서 복원한 인증 사용자. REST와 STOMP 모두
 * 클라이언트가 보낸 사용자 ID 대신 이 Principal의 값을 신뢰한다.
 *
 * <p>{@code tokenId}(jti)와 {@code expiresAt}은 로그아웃 시 원본 JWT를 다시
 * 파싱하지 않고 blacklist에 등록하기 위해 검증 시점에 함께 보관한다.</p>
 */
public record AuthenticatedUser(
        String userId,
        String nickname,
        String tokenId,
        Instant expiresAt,
        Role role
) implements Principal {

    public AuthenticatedUser(
            String userId,
            String nickname,
            String tokenId,
            Instant expiresAt
    ) {
        this(userId, nickname, tokenId, expiresAt, Role.USER);
    }

    @Override
    public String getName() {
        return userId;
    }
}
