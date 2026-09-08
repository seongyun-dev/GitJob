package com.example.git_job.auth.repository;

import com.example.git_job.auth.domain.User;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserRepository extends JpaRepository<User, Long> {

    /** 신규 등록과 기존 사용자 식별의 기준. github_id는 UNIQUE다. */
    Optional<User> findByGithubId(Long githubId);
}
