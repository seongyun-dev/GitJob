package com.example.git_job.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.example.git_job.auth.controller.dto.MeResponse;
import com.example.git_job.auth.domain.Role;
import com.example.git_job.auth.domain.User;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.security.AuthenticatedUser;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * displayName fallback 과 githubConnected 판정, 그리고 "유효한 세션인데 사용자 없음"을
 * 401 로 접는 계약을 고정한다.
 */
class AuthQueryServiceTest {

    private final UserRepository userRepository = mock(UserRepository.class);
    private final AuthQueryService service = new AuthQueryService(userRepository);

    private AuthenticatedUser principal(String userId) {
        return new AuthenticatedUser(userId, "handle", "jti", Instant.now().plusSeconds(600),
                com.example.git_job.auth.domain.Role.USER);
    }

    private User user(String name, String githubLogin, String avatarUrl, String accessToken) {
        User u = User.register(1L, githubLogin, name, "e@x.com", avatarUrl, "read:user", accessToken);
        ReflectionTestUtils.setField(u, "userId", 42L);
        return u;
    }

    @Test
    void usesProfileNameWhenPresent() {
        when(userRepository.findById(42L))
                .thenReturn(Optional.of(user("윤서", "yoonseo-aa", "http://a/x.png", "gho_token")));

        MeResponse me = service.me(principal("42"));

        assertThat(me.displayName()).isEqualTo("윤서");
        assertThat(me.avatarUrl()).isEqualTo("http://a/x.png");
        assertThat(me.githubConnected()).isTrue();
        // 가입 기본값은 USER. 헤더는 이 값으로 관리자 링크 노출 여부를 정한다.
        assertThat(me.role()).isEqualTo("USER");
    }

    @Test
    void adminRoleIsReported() {
        // role 은 DB 에서만 바뀐다(운영자 UPDATE). ADMIN 이면 그대로 내려간다.
        User admin = user("윤서", "yoonseo-aa", null, "gho_token");
        ReflectionTestUtils.setField(admin, "role", Role.ADMIN);
        when(userRepository.findById(42L)).thenReturn(Optional.of(admin));

        assertThat(service.me(principal("42")).role()).isEqualTo("ADMIN");
    }

    @Test
    void fallsBackToGithubLoginWhenNameBlank() {
        when(userRepository.findById(42L))
                .thenReturn(Optional.of(user("", "yoonseo-aa", null, null)));

        MeResponse me = service.me(principal("42"));

        assertThat(me.displayName()).isEqualTo("yoonseo-aa");
        assertThat(me.avatarUrl()).isNull();
        // access token 이 없으면 GitHub 미연결이다.
        assertThat(me.githubConnected()).isFalse();
    }

    @Test
    void unknownUserWithValidSessionIsUnauthorized() {
        when(userRepository.findById(42L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.me(principal("42")))
                .isInstanceOf(CustomException.class)
                .extracting(e -> ((CustomException) e).getErrorCode())
                .isEqualTo(ErrorCode.UNAUTHORIZED);
    }

    @Test
    void nonNumericSubjectIsUnauthorized() {
        assertThatThrownBy(() -> service.me(principal("not-a-number")))
                .isInstanceOf(CustomException.class)
                .extracting(e -> ((CustomException) e).getErrorCode())
                .isEqualTo(ErrorCode.UNAUTHORIZED);
    }

    @Test
    void nullPrincipalIsUnauthorized() {
        assertThatThrownBy(() -> service.me(null))
                .isInstanceOf(CustomException.class)
                .extracting(e -> ((CustomException) e).getErrorCode())
                .isEqualTo(ErrorCode.UNAUTHORIZED);
    }
}
