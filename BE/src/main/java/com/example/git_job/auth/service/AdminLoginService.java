package com.example.git_job.auth.service;

import com.example.git_job.auth.domain.Role;
import com.example.git_job.auth.domain.User;
import com.example.git_job.auth.repository.UserRepository;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.security.JwtTokenProvider;
import java.time.Duration;
import java.time.Instant;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 관리자 전용 ID/PW 로그인. GitHub OAuth 를 거치지 않고 관리자 화면에 들어가기 위한
 * 진입점이다(운영/시연용).
 *
 * <p>자격 증명은 <b>DB 의 사용자 행</b>에 있다(V15). 환경변수로 두면 환경마다 값을 맞추고
 * 컨테이너를 재생성해야 하는데, 관리자 승격({@code role}) 자체가 이미 DB 에서만 바뀌므로
 * 자격 증명도 같은 자리에 두는 편이 일관되고 값을 바꿀 때 재배포가 필요 없다.</p>
 *
 * <p>별도 관리자 계정 테이블은 없다. 발급되는 세션의 주체가 결국 그 사용자이므로
 * {@code /me} 와 {@code /api/v1/admin/**} 이 GitHub 로그인과 똑같이 동작한다.</p>
 *
 * <p>실패는 원인을 구분하지 않고 {@link ErrorCode#UNAUTHORIZED} 로 접는다 -- 아이디가
 * 없는지, 비밀번호가 틀렸는지, 승격이 풀렸는지 드러내지 않는다. 비밀번호는 BCrypt
 * 해시로만 비교하며 평문은 어디에도 남기지 않는다.</p>
 */
@Service
@RequiredArgsConstructor
public class AdminLoginService {

    private final UserRepository userRepository;
    private final JwtTokenProvider jwtTokenProvider;
    private final PasswordEncoder passwordEncoder;

    @Transactional(readOnly = true)
    public LoginSession login(String id, String password) {
        if (id == null || id.isBlank() || password == null || password.isEmpty()) {
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }

        User admin = userRepository.findByAdminLoginId(id)
                .filter(user -> user.getAdminPasswordHash() != null)
                .filter(user -> passwordEncoder.matches(password, user.getAdminPasswordHash()))
                // 자격 증명만 맞고 승격이 풀린 계정으로는 들어올 수 없다.
                .filter(user -> user.getRole() == Role.ADMIN)
                .orElseThrow(() -> new CustomException(ErrorCode.UNAUTHORIZED));

        String sessionToken = jwtTokenProvider.createToken(
                String.valueOf(admin.getUserId()),
                admin.getRole().name(),
                admin.getGithubLogin(),
                Instant.now()
        );
        return new LoginSession(sessionToken, jwtTokenProvider.getAccessTokenExpiration());
    }

    /** 발급된 세션 토큰과 쿠키 수명. 컨트롤러가 이 값으로 SESSION 쿠키를 심는다. */
    public record LoginSession(String sessionToken, Duration maxAge) {
    }
}
