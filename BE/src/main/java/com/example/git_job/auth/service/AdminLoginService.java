package com.example.git_job.auth.service;

import com.example.git_job.auth.domain.Role;
import com.example.git_job.auth.domain.User;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.security.JwtTokenProvider;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 관리자 전용 ID/PW 로그인. GitHub OAuth를 거치지 않고 관리자 화면에 들어가기 위한
 * 진입점이다(운영/시연용).
 *
 * <p>별도의 관리자 계정 테이블을 만들지 않는다. 자격 증명(ID/PW)은 환경변수로만 받고,
 * 검증에 성공하면 <b>이미 role=ADMIN 으로 승격된 실제 사용자</b>의 세션을 발급한다.
 * 그래야 {@code /me}와 {@code /api/v1/admin/**}이 GitHub 로그인과 똑같이 동작한다.</p>
 *
 * <p>자격 증명은 코드·응답·로그에 싣지 않는다. 비교는 {@link MessageDigest#isEqual}로
 * 상수시간에 하고, 실패는 원인을 구분하지 않고 {@link ErrorCode#UNAUTHORIZED}로 접는다
 * (ID/PW 중 무엇이 틀렸는지, 기능이 꺼져 있는지 드러내지 않는다).</p>
 */
@Service
public class AdminLoginService {

    private static final Logger log = LoggerFactory.getLogger(AdminLoginService.class);

    private final UserRepository userRepository;
    private final JwtTokenProvider jwtTokenProvider;
    private final String adminId;
    private final String adminPassword;

    public AdminLoginService(
            UserRepository userRepository,
            JwtTokenProvider jwtTokenProvider,
            @Value("${admin.login.id:}") String adminId,
            @Value("${admin.login.password:}") String adminPassword
    ) {
        this.userRepository = userRepository;
        this.jwtTokenProvider = jwtTokenProvider;
        this.adminId = adminId;
        this.adminPassword = adminPassword;
    }

    @Transactional(readOnly = true)
    public LoginSession login(String id, String password) {
        // 자격 증명이 설정되지 않았으면 기능이 꺼진 것이다. 실패로 접되 이유는 로그에만 남긴다.
        if (adminId == null || adminId.isBlank() || adminPassword == null || adminPassword.isBlank()) {
            log.warn("관리자 로그인 시도, 그러나 ADMIN_LOGIN_ID/PASSWORD 가 설정되지 않았다.");
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }

        // 앞에서 끊지 않고 두 비교를 모두 수행한다 — 어느 필드에서 갈렸는지 응답 시간으로도 드러내지 않는다.
        boolean matched = constantTimeEquals(id, adminId) & constantTimeEquals(password, adminPassword);
        if (!matched) {
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }

        User admin = userRepository.findFirstByRoleOrderByUserIdAsc(Role.ADMIN)
                .orElseThrow(() -> {
                    log.warn("관리자 자격 증명은 맞았으나 role=ADMIN 사용자가 DB에 없다.");
                    return new CustomException(ErrorCode.UNAUTHORIZED);
                });

        String sessionToken = jwtTokenProvider.createToken(
                String.valueOf(admin.getUserId()),
                admin.getRole().name(),
                admin.getGithubLogin(),
                Instant.now()
        );
        return new LoginSession(sessionToken, jwtTokenProvider.getAccessTokenExpiration());
    }

    /**
     * 길이가 다르면 곧바로 false지만, 그 판정 자체는 값 내용에 의존하지 않는다.
     * 같은 길이일 때는 {@link MessageDigest#isEqual}이 전체 바이트를 상수시간에 비교한다.
     */
    private boolean constantTimeEquals(String a, String b) {
        if (a == null || b == null) {
            return false;
        }
        return MessageDigest.isEqual(
                a.getBytes(StandardCharsets.UTF_8),
                b.getBytes(StandardCharsets.UTF_8)
        );
    }

    /** 발급된 세션 토큰과 쿠키 수명. 컨트롤러가 이 값으로 SESSION 쿠키를 심는다. */
    public record LoginSession(String sessionToken, Duration maxAge) {
    }
}
