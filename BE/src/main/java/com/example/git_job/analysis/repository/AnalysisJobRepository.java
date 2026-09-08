package com.example.git_job.analysis.repository;

import com.example.git_job.analysis.domain.AnalysisJob;
import java.util.Collection;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

/** The analysis ID is a server-assigned string, so it is also the JPA identifier type. */
public interface AnalysisJobRepository extends JpaRepository<AnalysisJob, String> {

    /**
     * Backs the "no duplicate job while one is already running" rule. Ordering by
     * requested_at keeps the answer stable if older rows were left behind by a crash.
     */
    Optional<AnalysisJob> findFirstByUserIdAndRepositoryIdAndStatusInOrderByRequestedAtDesc(
            Long userId, String repositoryId, Collection<String> statuses);
}
