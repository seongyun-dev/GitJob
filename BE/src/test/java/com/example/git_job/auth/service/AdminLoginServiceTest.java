package com.example.git_job.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.example.git_job.auth.domain.Role;
import com.example.git_job.auth.domain.User;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.security.JwtTokenProvider;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * 관리자 ID/PW 로그인의 계약을 고정한다: 자격 증명이 맞을 때만 role=ADMIN 사용자의
 * 세션을 발급하고, 그 외(틀린 값·미설정·관리자 없음)는 원인을 구분하지 않고 401로 접는다.
 */
class AdminLoginServiceTest {

    private static final String ID = "ssafygitjob";
    private static final String PW = "correct-horse";

    private final UserRepository userRepository = mock(UserRepository.class);
    private final JwtTokenProvider jwtTokenProvider = mock(JwtTokenProvider.class);

    private AdminLoginService service(String id, String password) {
        return new AdminLoginService(userRepository, jwtTokenProvider, id, password);
    }

    private User adminUser() {
        User u = User.register(1L, "admin-handle", "관리자", "a@x.com", null, "read:user repo", "gho_t");
        ReflectionTestUtils.setField(u, "userId", 7L);
        ReflectionTestUtils.setField(u, "role", Role.ADMIN);
        return u;
    }

    @Test
    void issuesAdminSessionOnValidCredentials() {
        when(userRepository.findFirstByRoleOrderByUserIdAsc(Role.ADMIN))
                .thenReturn(Optional.of(adminUser()));
        when(jwtTokenProvider.createToken(eq("7"), eq("ADMIN"), eq("admin-handle"), any(Instant.class)))
                .thenReturn("session-token");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(Duration.ofMinutes(30));

        AdminLoginService.LoginSession session = service(ID, PW).login(ID, PW);

        assertThat(session.sessionToken()).isEqualTo("session-token");
        assertThat(session.maxAge()).isEqualTo(Duration.ofMinutes(30));
    }

    @Test
    void rejectsWrongPassword() {
        assertThatThrownBy(() -> service(ID, PW).login(ID, "wrong"))
                .isInstanceOf(CustomException.class)
                .extracting(e -> ((CustomException) e).getErrorCode())
                .isEqualTo(ErrorCode.UNAUTHORIZED);
    }

    @Test
    void rejectsWrongId() {
        assertThatThrownBy(() -> service(ID, PW).login("someone", PW))
                .isInstanceOf(CustomException.class)
                .extracting(e -> ((CustomException) e).getErrorCode())
                .isEqualTo(ErrorCode.UNAUTHORIZED);
    }

    @Test
    void rejectsWhenCredentialsNotConfigured() {
        assertThatThrownBy(() -> service("", "").login(ID, PW))
                .isInstanceOf(CustomException.class)
                .extracting(e -> ((CustomException) e).getErrorCode())
                .isEqualTo(ErrorCode.UNAUTHORIZED);
    }

    @Test
    void rejectsWhenNoAdminUserExists() {
        when(userRepository.findFirstByRoleOrderByUserIdAsc(Role.ADMIN)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service(ID, PW).login(ID, PW))
                .isInstanceOf(CustomException.class)
                .extracting(e -> ((CustomException) e).getErrorCode())
                .isEqualTo(ErrorCode.UNAUTHORIZED);
    }
}
