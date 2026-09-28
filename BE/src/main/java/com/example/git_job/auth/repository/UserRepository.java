package com.example.git_job.auth.repository;

import com.example.git_job.auth.domain.User;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserRepository extends JpaRepository<User, Long> {

    /** 신규 등록과 기존 사용자 식별의 기준. github_id는 UNIQUE다. */
    Optional<User> findByGithubId(Long githubId);

    /**
     * 관리자 ID/PW 로그인의 조회 기준 (V15). {@code admin_login_id} 는 UNIQUE 이고,
     * 이 방식을 쓰지 않는 사용자는 NULL 이라 후보에 들어오지 않는다.
     *
     * <p>역할 확인은 여기서 하지 않는다 -- 조회된 사용자가 실제로 ADMIN 인지는
     * 서비스가 판단한다(자격 증명만 맞고 승격이 풀린 경우를 거르기 위해서다).</p>
     */
    Optional<User> findByAdminLoginId(String adminLoginId);
}
