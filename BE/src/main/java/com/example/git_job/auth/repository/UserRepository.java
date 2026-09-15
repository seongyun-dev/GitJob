package com.example.git_job.auth.repository;

import com.example.git_job.auth.domain.Role;
import com.example.git_job.auth.domain.User;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserRepository extends JpaRepository<User, Long> {

    /** 신규 등록과 기존 사용자 식별의 기준. github_id는 UNIQUE다. */
    Optional<User> findByGithubId(Long githubId);

    /**
     * 관리자 ID/PW 로그인이 발급할 세션의 주체를 찾는다. 별도 관리자 계정을 두지 않고
     * 이미 role=ADMIN 으로 승격된 사용자로 로그인시키므로, 그 사용자가 필요하다.
     * 여럿이면 가장 먼저 승격된(userId 오름차순) 한 명을 쓴다.
     */
    Optional<User> findFirstByRoleOrderByUserIdAsc(Role role);
}
