package com.example.git_job.auth.service;

import com.example.git_job.auth.domain.User;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 로그인 세션의 사용자 ID로 GitHub Access Token을 꺼낸다.
 *
 * <p>토큰 접근을 auth 모듈 안에 가둬 두는 통로다. 다른 모듈이 {@link User}를 직접
 * 들고 다니면 토큰이 응답 DTO나 로그로 흘러갈 경로가 그만큼 늘어난다. 여기서는
 * 문자열 하나만 넘기고, 저장 방식이 바뀌어도(현재 평문, 암호화는 별도 티켓)
 * 호출부는 그대로 둔다.</p>
 */
@Service
@RequiredArgsConstructor
public class GithubAccessTokenProvider {

    private final UserRepository userRepository;

    /**
     * 세션은 유효하지만 GitHub 연결이 끊긴 경우(연결 해제, 토큰 폐기)를 인증 만료와
     * 같은 신호로 돌려준다. 사용자가 할 수 있는 일은 재로그인뿐이라 구분할 실익이 없다.
     */
    @Transactional(readOnly = true)
    public String accessTokenOf(long userId) {
        String accessToken = userRepository.findById(userId)
                .map(User::getAccessToken)
                .orElseThrow(() -> new CustomException(ErrorCode.GITHUB_TOKEN_INVALID));
        if (accessToken == null || accessToken.isBlank()) {
            throw new CustomException(ErrorCode.GITHUB_TOKEN_INVALID);
        }
        return accessToken;
    }
}
