package com.example.git_job.analysis.store;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.domain.AnalysisJob;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.analysis.service.AnalysisRequestProperties;
import com.example.git_job.analysis.service.StaleAnalysisReaper;
import com.example.git_job.analysis.support.AnalysisJpaSupport;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * 제출 차단과 멈춘 분석 정리를 <b>실제 PostgreSQL</b> 위에서 확인한다 (S15P21E102-136).
 *
 * <h2>왜 H2로는 안 되나</h2>
 *
 * <p>이 기능의 핵심 주장이 "reaper가 분석을 종료시키면 {@code uq_analysis_job_active}가
 * 풀려 같은 저장소를 다시 요청할 수 있다"인데, 그 인덱스는 <b>부분 UNIQUE 인덱스</b>이고
 * H2는 {@code CREATE INDEX ... WHERE}를 거부한다. 잠금도 마찬가지로
 * {@code pg_advisory_xact_lock}은 PostgreSQL에만 있다. 단위 테스트는 상태 전이까지만
 * 잡을 수 있고, 인덱스가 실제로 풀리는지는 진짜 DB에서만 보인다.</p>
 *
 * <p>스키마는 배포와 같은 방식으로 만든다 -- Flyway가 V1부터 전부 적용하므로 V27도
 * 여기서 함께 검증된다.</p>
 */
class AnalysisBatchGateIntegrationTest {

    private static final long USER_ID = 7L;
    private static final String REPOSITORY_ID = "555";
    private static final String SHA = "0123456789abcdef0123456789abcdef01234567";
    private static final Duration WINDOW = Duration.ofHours(2);

    private static PostgreSQLContainer<?> postgres;
    private static HikariDataSource dataSource;
    private static LocalContainerEntityManagerFactoryBean entityManagers;

    private JdbcTemplate jdbc;
    private AnalysisJobRepository jobs;
    private AnalysisBatchStore batches;
    private StaleAnalysisReaper reaper;
    private TransactionTemplate transaction;

    @BeforeAll
    static void startDatabase() {
        postgres = new PostgreSQLContainer<>("postgres:16-alpine");
        postgres.start();
        var config = new HikariConfig();
        config.setJdbcUrl(postgres.getJdbcUrl());
        config.setUsername(postgres.getUsername());
        config.setPassword(postgres.getPassword());
        config.setMaximumPoolSize(4);
        dataSource = new HikariDataSource(config);
        // 배포가 받는 것과 같은 마이그레이션을 같은 방식으로. V27도 여기서 적용된다.
        Flyway.configure().dataSource(dataSource).locations("classpath:db/migration")
                .load().migrate();
        // validate: 엔티티 매핑이 배포가 실제로 적용하는 SQL과 맞는지 함께 본다.
        entityManagers = AnalysisJpaSupport.entityManagerFactory(dataSource, "validate");
    }

    @AfterAll
    static void stopDatabase() {
        if (entityManagers != null) {
            entityManagers.destroy();
        }
        if (dataSource != null) {
            dataSource.close();
        }
        if (postgres != null) {
            postgres.stop();
        }
    }

    @BeforeEach
    void setUp() {
        jdbc = new JdbcTemplate(dataSource);
        jdbc.update("DELETE FROM analysis_job");
        jdbc.update("DELETE FROM \"user\" WHERE user_id = ?", USER_ID);
        // analysis_job.user_id 는 V4 이후 "user" 를 참조한다.
        jdbc.update("""
                INSERT INTO "user" (user_id, github_id, github_login, name)
                VALUES (?, ?, 'octocat', 'Octo Cat')
                """, USER_ID, USER_ID);

        var factory = entityManagers.getObject();
        jobs = AnalysisJpaSupport.repository(factory);
        batches = new AnalysisBatchStore(jdbc);
        reaper = new StaleAnalysisReaper(jobs, properties());
        transaction = new TransactionTemplate(new JpaTransactionManager(factory));
    }

    private static AnalysisRequestProperties properties() {
        return new AnalysisRequestProperties(2, WINDOW, Duration.ofMinutes(30), 10);
    }

    /** JPA를 거치지 않고 넣는다. 인덱스와 SQL을 보는 테스트라 매핑이 개입할 이유가 없다. */
    private void insertJob(String analysisId, String status, Instant requestedAt, String batchId) {
        jdbc.update("""
                INSERT INTO analysis_job (analysis_id, user_id, repository_id,
                        repository_full_name, branch_name, commit_sha, status, current_stage,
                        requested_at, batch_id)
                VALUES (?, ?, ?, 'octocat/repo', 'main', ?, ?, 'WAITING_FOR_WORKER', ?, ?)
                """, analysisId, USER_ID, REPOSITORY_ID, SHA, status,
                java.sql.Timestamp.from(requestedAt), batchId);
    }

    @Test
    @DisplayName("V27이 적용돼 batch_id 컬럼이 있다")
    void migrationAddsTheBatchColumn() {
        Integer columns = jdbc.queryForObject("""
                SELECT count(*) FROM information_schema.columns
                 WHERE table_name = 'analysis_job' AND column_name = 'batch_id'
                """, Integer.class);

        assertEquals(1, columns);
    }

    /**
     * 이 테스트가 이 기능의 존재 이유다.
     *
     * <p>멈춘 분석이 살아 있는 동안 그 저장소는 {@code uq_analysis_job_active}에 점유돼
     * 새 분석을 만들 수 없다. reaper가 종료로 옮겨야 그 점유가 풀린다. 차단에 유효시간만
     * 두고 잡을 살려 두면 차단은 풀리는데 저장소는 영영 막힌 채로 남는다.</p>
     */
    @Test
    @DisplayName("reaper가 종료시키면 같은 저장소를 다시 요청할 수 있다")
    void reapingAStuckJobReleasesTheRepositoryForANewRequest() {
        Instant longAgo = Instant.now().minus(Duration.ofHours(49));
        insertJob("an_stuck", AnalysisJob.STATUS_QUEUED, longAgo, null);

        // 멈춘 잡이 살아 있는 동안에는 같은 저장소로 새 분석을 만들 수 없다.
        assertThrows(DuplicateKeyException.class,
                () -> insertJob("an_new", AnalysisJob.STATUS_QUEUED, Instant.now(), "ab_1"));

        transaction.executeWithoutResult(status -> reaper.reapStale());

        assertEquals(AnalysisJob.STATUS_FAILED, jdbc.queryForObject(
                "SELECT status FROM analysis_job WHERE analysis_id = 'an_stuck'", String.class));
        assertEquals(AnalysisJob.ERROR_ANALYSIS_TIMED_OUT, jdbc.queryForObject(
                "SELECT error_code FROM analysis_job WHERE analysis_id = 'an_stuck'",
                String.class));

        // 점유가 실제로 풀렸다. 이 줄이 통과하는 것이 이 기능이 고친 고장이다.
        insertJob("an_new", AnalysisJob.STATUS_QUEUED, Instant.now(), "ab_1");
        assertEquals(2, jdbc.queryForObject(
                "SELECT count(*) FROM analysis_job", Integer.class));
    }

    /**
     * 제출 경로가 stale 잡을 직접 닫는 길. reaper 를 기다리면 새 잡의 INSERT 가 부분
     * UNIQUE 인덱스를 위반하고, 배치가 한 트랜잭션이라 묶음 전체가 롤백된다.
     */
    @Test
    @DisplayName("같은 트랜잭션에서 stale 잡을 닫고 그 저장소에 새 잡을 넣을 수 있다")
    void closingAStaleJobInTheSameTransactionMakesRoomForTheNewOne() {
        insertJob("an_stale", AnalysisJob.STATUS_QUEUED,
                Instant.now().minus(Duration.ofHours(49)), null);

        transaction.executeWithoutResult(status -> {
            AnalysisJob stale = jobs.findById("an_stale").orElseThrow();
            assertTrue(stale.fail(AnalysisJob.ERROR_ANALYSIS_TIMED_OUT, Instant.now()));
            jobs.saveAndFlush(stale);
            // 같은 트랜잭션 안에서 점유가 이미 풀려 있어야 한다.
            insertJob("an_new", AnalysisJob.STATUS_QUEUED, Instant.now(), "ab_new");
        });

        assertEquals(AnalysisJob.STATUS_FAILED, jdbc.queryForObject(
                "SELECT status FROM analysis_job WHERE analysis_id = 'an_stale'", String.class));
        assertEquals("ab_new", jdbc.queryForObject(
                "SELECT batch_id FROM analysis_job WHERE analysis_id = 'an_new'", String.class));
    }

    @Test
    @DisplayName("창 안의 분석은 정리하지 않는다")
    void doesNotReapJobsInsideTheWindow() {
        insertJob("an_fresh", AnalysisJob.STATUS_QUEUED,
                Instant.now().minus(Duration.ofMinutes(10)), "ab_1");

        transaction.executeWithoutResult(status -> reaper.reapStale());

        assertEquals(AnalysisJob.STATUS_QUEUED, jdbc.queryForObject(
                "SELECT status FROM analysis_job WHERE analysis_id = 'an_fresh'", String.class));
    }

    @Test
    @DisplayName("차단 판정은 창 안의 진행 중 분석만 본다")
    void theGateOnlyCountsInProgressJobsInsideTheWindow() {
        Instant threshold = Instant.now().minus(WINDOW);

        insertJob("an_old", AnalysisJob.STATUS_QUEUED,
                Instant.now().minus(Duration.ofHours(49)), null);
        assertFalse(jobs.existsByUserIdAndStatusInAndRequestedAtAfter(
                USER_ID, AnalysisJob.IN_PROGRESS_STATUSES, threshold),
                "창을 넘긴 분석은 막지 않아야 사용자가 영구히 잠기지 않는다");

        jdbc.update("DELETE FROM analysis_job");
        insertJob("an_now", AnalysisJob.STATUS_QUEUED, Instant.now(), "ab_1");
        assertTrue(jobs.existsByUserIdAndStatusInAndRequestedAtAfter(
                USER_ID, AnalysisJob.IN_PROGRESS_STATUSES, threshold));

        jdbc.update("UPDATE analysis_job SET status = 'SUCCEEDED'");
        assertFalse(jobs.existsByUserIdAndStatusInAndRequestedAtAfter(
                USER_ID, AnalysisJob.IN_PROGRESS_STATUSES, threshold),
                "끝난 분석은 막지 않는다");
    }

    @Test
    @DisplayName("배치 이전에 만들어진 진행 중 분석도 제출을 막는다")
    void legacyJobsWithoutABatchStillBlock() {
        insertJob("an_legacy", AnalysisJob.STATUS_QUEUED, Instant.now(), null);

        assertTrue(jobs.existsByUserIdAndStatusInAndRequestedAtAfter(
                USER_ID, AnalysisJob.IN_PROGRESS_STATUSES, Instant.now().minus(WINDOW)));
        // 다만 배치 조회에는 잡히지 않는다 -- 없는 묶음을 지어내지 않는다.
        assertTrue(batches.latestBatch(USER_ID).isEmpty());
    }

    @Test
    @DisplayName("가장 최근 묶음만, 그 구성원 전부를 돌려준다")
    void latestBatchReturnsOnlyTheNewestGroup() {
        Instant base = Instant.now().minus(Duration.ofMinutes(30));
        insertJob("an_old1", "SUCCEEDED", base, "ab_old");
        insertJob("an_new1", "SUCCEEDED", base.plusSeconds(60), "ab_new");
        jdbc.update("UPDATE analysis_job SET repository_id = 'r2' WHERE analysis_id = 'an_new1'");
        insertJob("an_new2", AnalysisJob.STATUS_QUEUED, base.plusSeconds(61), "ab_new");

        List<AnalysisBatchStore.Row> rows = batches.latestBatch(USER_ID);

        assertEquals(2, rows.size());
        assertTrue(rows.stream().allMatch(row -> "ab_new".equals(row.batchId())));
    }

    @Test
    @DisplayName("멈춘 분석 수를 센다")
    void countsStaleJobs() {
        insertJob("an_stale", AnalysisJob.STATUS_QUEUED,
                Instant.now().minus(Duration.ofHours(49)), null);
        jdbc.update("UPDATE analysis_job SET repository_id = 'r9' WHERE analysis_id = 'an_stale'");
        insertJob("an_fresh", AnalysisJob.STATUS_QUEUED, Instant.now(), "ab_1");

        assertEquals(1, batches.countStaleSince(
                AnalysisJob.IN_PROGRESS_STATUSES, Instant.now().minus(WINDOW)));
    }

    /**
     * 잠금 자체가 PostgreSQL에서 실제로 잡히는지 본다. 같은 트랜잭션에서 두 번 잡아도
     * 교착하지 않아야 하고(재진입 가능), 커밋 뒤에는 남아 있지 않아야 한다.
     */
    @Test
    @DisplayName("advisory lock은 잡히고 트랜잭션이 끝나면 풀린다")
    void advisoryLockIsTakenAndReleasedWithTheTransaction() {
        transaction.executeWithoutResult(status -> {
            batches.lockUserBatchGate(USER_ID);
            batches.lockUserBatchGate(USER_ID);
            assertTrue(heldLocks() >= 1, "트랜잭션 안에서는 잠금이 잡혀 있어야 한다");
        });

        assertEquals(0, heldLocks(), "커밋 뒤에는 잠금이 남지 않아야 한다");
    }

    private int heldLocks() {
        Integer count = jdbc.queryForObject(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'", Integer.class);
        return count == null ? 0 : count;
    }
}
