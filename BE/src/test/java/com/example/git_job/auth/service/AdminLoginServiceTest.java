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
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * 관리자 ID/PW 로그인의 계약을 고정한다: 자격 증명이 DB 의 해시와 맞고 그 사용자가
 * 여전히 ADMIN 일 때만 세션을 발급하고, 그 외는 원인을 구분하지 않고 401 로 접는다.
 */
class AdminLoginServiceTest {

    private static final String ID = "ssafygitjob";
    private static final String RAW = "correct-horse";
    private static final String HASH = "$2a$10$storedhash";

    private final UserRepository userRepository = mock(UserRepository.class);
    private final JwtTokenProvider jwtTokenProvider = mock(JwtTokenProvider.class);
    private final PasswordEncoder passwordEncoder = mock(PasswordEncoder.class);
    private final AdminLoginService service =
            new AdminLoginService(userRepository, jwtTokenProvider, passwordEncoder);

    private User user(Role role, String loginId, String hash) {
        User u = User.register(1L, "admin-handle", "관리자", "a@x.com", null, "read:user repo", "gho_t");
        ReflectionTestUtils.setField(u, "userId", 7L);
        ReflectionTestUtils.setField(u, "role", role);
        ReflectionTestUtils.setField(u, "adminLoginId", loginId);
        ReflectionTestUtils.setField(u, "adminPasswordHash", hash);
        return u;
    }

    private void found(User u) {
        when(userRepository.findByAdminLoginId(ID)).thenReturn(Optional.of(u));
    }

    @Test
    void issuesAdminSessionOnValidCredentials() {
        found(user(Role.ADMIN, ID, HASH));
        when(passwordEncoder.matches(RAW, HASH)).thenReturn(true);
        when(jwtTokenProvider.createToken(eq("7"), eq("ADMIN"), eq("admin-handle"), any(Instant.class)))
                .thenReturn("session-token");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(Duration.ofMinutes(30));

        AdminLoginService.LoginSession session = service.login(ID, RAW);

        assertThat(session.sessionToken()).isEqualTo("session-token");
        assertThat(session.maxAge()).isEqualTo(Duration.ofMinutes(30));
    }

    @Test
    void rejectsUnknownLoginId() {
        when(userRepository.findByAdminLoginId(ID)).thenReturn(Optional.empty());

        assertUnauthorized(ID, RAW);
    }

    @Test
    void rejectsWrongPassword() {
        found(user(Role.ADMIN, ID, HASH));
        when(passwordEncoder.matches("wrong", HASH)).thenReturn(false);

        assertUnauthorized(ID, "wrong");
    }

    @Test
    void rejectsWhenCredentialNotSet() {
        // 해시가 없으면 이 사용자는 ID/PW 로그인을 쓰지 않는다.
        found(user(Role.ADMIN, ID, null));

        assertUnauthorized(ID, RAW);
    }

    @Test
    void rejectsWhenRoleIsNoLongerAdmin() {
        // 자격 증명만 맞고 승격이 풀린 계정으로는 들어올 수 없다.
        found(user(Role.USER, ID, HASH));
        when(passwordEncoder.matches(RAW, HASH)).thenReturn(true);

        assertUnauthorized(ID, RAW);
    }

    @Test
    void rejectsBlankInput() {
        assertUnauthorized("", RAW);
        assertUnauthorized(ID, "");
        assertUnauthorized(null, null);
    }

    private void assertUnauthorized(String id, String password) {
        assertThatThrownBy(() -> service.login(id, password))
                .isInstanceOf(CustomException.class)
                .extracting(e -> ((CustomException) e).getErrorCode())
                .isEqualTo(ErrorCode.UNAUTHORIZED);
    }
}
