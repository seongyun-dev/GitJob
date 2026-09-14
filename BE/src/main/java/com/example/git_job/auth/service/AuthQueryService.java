package com.example.git_job.auth.service;

import com.example.git_job.auth.controller.dto.MeResponse;
import com.example.git_job.auth.domain.User;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.security.AuthenticatedUser;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 로그인 사용자 조회 · 티켓 S15P21E102-246.
 *
 * <p>세션은 유효하지만 DB에 사용자 행이 없을 수 있다 — 토큰(수명 30분)이 남아 있는데
 * 그 사이 행이 지워진 경우다. 그때 500이 아니라 {@code UNAUTHORIZED}(401)를 준다.
 * FE는 이 401을 "로그아웃 상태"로 읽어 로그인 버튼을 보인다. subject가 숫자가 아닌
 * 경우도(키를 공유하는 다른 서비스의 토큰) 같다 — {@code CurrentUser}와 같은 판단이다.</p>
 */
@Service
@RequiredArgsConstructor
public class AuthQueryService {

    private final UserRepository userRepository;

    @Transactional(readOnly = true)
    public MeResponse me(AuthenticatedUser principal) {
        long userId = userIdOf(principal);
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new CustomException(ErrorCode.UNAUTHORIZED));

        String name = user.getName();
        String displayName = (name != null && !name.isBlank()) ? name : user.getGithubLogin();

        String accessToken = user.getAccessToken();
        boolean githubConnected = accessToken != null && !accessToken.isBlank();

        return new MeResponse(displayName, user.getAvatarUrl(), githubConnected);
    }

    private long userIdOf(AuthenticatedUser principal) {
        if (principal == null || principal.userId() == null) {
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }
        try {
            return Long.parseLong(principal.userId());
        } catch (NumberFormatException notNumeric) {
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }
    }
}
