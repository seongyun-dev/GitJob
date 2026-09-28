package com.example.git_job.global.security;

import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;

/**
 * JWT subject를 사용자 ID로 바꾼다.
 *
 * <p>{@code analysis.controller}에 있던 것을 옮겼다. {@code /me} 아래의 모든 기능이
 * 같은 판단을 하는데, 패키지마다 복사하면 어느 한 곳이 {@code null} 사용자를 다르게
 * 다루게 되고 그 차이가 곧 인가 구멍이 된다.</p>
 *
 * <p>subject는 문자열이고 우리 스키마의 user_id는 BIGINT다. 세션이 유효해도 여기서
 * 실패할 수 있는데(예: 토큰 서명 키를 공유하는 다른 서비스의 토큰), 그때 500이 아니라
 * 401을 주어야 한다. 사용자가 할 수 있는 일은 재로그인뿐이다.</p>
 */
public final class CurrentUser {

    private CurrentUser() {
    }

    public static long idOf(AuthenticatedUser user) {
        if (user == null || user.userId() == null) {
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }
        try {
            return Long.parseLong(user.userId());
        } catch (NumberFormatException notNumeric) {
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }
    }
}
