package com.example.git_job.analysis.store;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.example.git_job.analysis.store.EvidenceAuthorshipStore.Authorship;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.util.List;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.postgresql.PostgreSQLContainer;

/**
 * 기여 판정 적재를 실제 PostgreSQL 에 대고 확인한다.
 *
 * <p>{@link EvidenceAuthorshipService} 쪽 테스트는 어떤 라벨을 고르는지를 보고,
 * 저장은 목이다. 여기서 보는 것은 그 라벨이 <b>DB 를 통과하는지</b>다 --
 * {@code contribution_type} 에는 CHECK 제약이 걸려 있어서, 코드에만 새 값을 넣고
 * 제약을 안 늘리면 판정은 맞는데 트랜잭션이 깨진다. 목으로는 드러나지 않는다.</p>
 *
 * <p>재배달 멱등성도 SQL 에만 있다({@code ON CONFLICT DO NOTHING}). 결과 이벤트는
 * at-least-once 라 같은 분석을 두 번 처리하는 것이 정상 경로이고, 그때 기여가 두
 * 배로 세어지면 Level 판정이 흔들린다.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class EvidenceAuthorshipStoreTest {

    private static final String ANALYSIS = "an_1";
    private static final String REPO_ID = "repo_1";
    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";
    private static final long USER_ID = 101L;

    private PostgreSQLContainer postgres;
    private HikariDataSource dataSource;
    private JdbcTemplate jdbc;
    private EvidenceAuthorshipStore store;
    private String ruleId;
    private String registryVersion;

    @BeforeAll
    void startDatabase() {
        postgres = new PostgreSQLContainer("postgres:16.4-alpine");
        postgres.start();

        var config = new HikariConfig();
        config.setJdbcUrl(postgres.getJdbcUrl());
        config.setUsername(postgres.getUsername());
        config.setPassword(postgres.getPassword());
        config.setMaximumPoolSize(2);
        dataSource = new HikariDataSource(config);

        Flyway.configure().dataSource(dataSource).locations("classpath:db/migration")
                .load().migrate();

        jdbc = new JdbcTemplate(dataSource);
        store = new EvidenceAuthorshipStore(jdbc);

        jdbc.update("""
                INSERT INTO "user" (user_id, github_id, github_login, name)
                VALUES (?, ?, 'octocat', 'Octo Cat')
                """, USER_ID, USER_ID);
        jdbc.update("""
                INSERT INTO analysis_job (analysis_id, user_id, repository_id, branch_name,
                                          commit_sha, status, current_stage, requested_at)
                VALUES (?, ?, ?, 'main', ?, 'SUCCEEDED', 'COMPLETED', now())
                """, ANALYSIS, USER_ID, REPO_ID, SHA);

        // 근거는 (rule_id, registry_version) 으로 규칙을 참조한다. 값을 지어내면 FK 가
        // 막으므로 마이그레이션이 심은 규칙 하나를 그대로 빌려 쓴다 -- 어느 규칙인지는
        // 이 테스트의 관심사가 아니다.
        var rule = jdbc.queryForMap(
                "SELECT rule_id, registry_version FROM evidence_rule ORDER BY rule_id LIMIT 1");
        ruleId = (String) rule.get("rule_id");
        registryVersion = (String) rule.get("registry_version");
    }

    @AfterAll
    void stopDatabase() {
        if (dataSource != null) {
            dataSource.close();
        }
        if (postgres != null) {
            postgres.stop();
        }
    }

    @Test
    @DisplayName("기여 라벨 5종이 모두 저장된다 -- OTHER_AUTHOR 포함")
    void storesEveryContributionLabel() {
        // OTHER_AUTHOR 를 코드에만 넣고 CHECK 제약을 안 늘리면 여기서 깨진다.
        List<String> labels = List.of(
                "SOLE_AUTHOR", "CO_AUTHORED", "PARTIAL_EDIT", "OTHER_AUTHOR", "UNVERIFIED");
        List<Authorship> rows = labels.stream()
                .map(label -> authorship(evidenceRow(), label))
                .toList();

        assertEquals(labels.size(), store.insertAll(rows));

        assertEquals(labels.size(), jdbc.queryForObject("""
                SELECT count(DISTINCT contribution_type) FROM analysis_evidence_commit
                WHERE analysis_id = ?
                """, Integer.class, ANALYSIS));
    }

    @Test
    @DisplayName("제약 밖의 라벨은 거절된다")
    void refusesALabelOutsideTheContract() {
        // 제약이 아직 살아 있다는 것까지 확인한다. 위 테스트만 있으면 제약을 통째로
        // 지워도 통과한다.
        long evidenceId = evidenceRow();

        assertThrows(DataIntegrityViolationException.class,
                () -> store.insertAll(List.of(authorship(evidenceId, "NOT_A_LABEL"))));
    }

    @Test
    @DisplayName("같은 근거를 두 번 적재해도 행은 하나다")
    void doesNotDoubleCountARedeliveredResult() {
        // 결과 이벤트는 at-least-once 다. 재배달이 오류가 아니라 정상 경로다.
        long evidenceId = evidenceRow();
        Authorship row = authorship(evidenceId, "SOLE_AUTHOR");

        assertEquals(1, store.insertAll(List.of(row)));
        assertEquals(0, store.insertAll(List.of(row)));

        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM analysis_evidence_commit WHERE analysis_evidence_id = ?
                """, Integer.class, evidenceId));
    }

    @Test
    @DisplayName("커밋 메타는 같은 커밋을 다시 물어도 한 행이다")
    void cachesEachCommitOnce() {
        store.cacheCommit(REPO_ID, SHA, "octocat", "Octo Cat", "octo@example.invalid",
                java.time.OffsetDateTime.parse("2026-09-01T00:00:00Z"));
        store.cacheCommit(REPO_ID, SHA, "octocat", "Octo Cat", "octo@example.invalid",
                java.time.OffsetDateTime.parse("2026-09-01T00:00:00Z"));

        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM repository_commit WHERE repository_id = ? AND commit_sha = ?
                """, Integer.class, REPO_ID, SHA));
        assertEquals("octocat", store.findCommit(REPO_ID, SHA).orElseThrow().githubLogin());
    }

    /** 근거 한 줄. 기여 판정이 붙을 자리가 있어야 적재를 볼 수 있다. */
    private long evidenceRow() {
        return jdbc.queryForObject("""
                INSERT INTO analysis_evidence
                    (analysis_id, user_id, rule_id, file_path, start_line, end_line,
                     fact_type, fact_payload, matched_at, registry_version)
                VALUES (?, ?, ?, 'src/main/java/App.java', 1, 1, 'IMPORT', '{}'::jsonb, now(), ?)
                RETURNING analysis_evidence_id
                """, Long.class, ANALYSIS, USER_ID, ruleId, registryVersion);
    }

    private static Authorship authorship(long evidenceId, String contributionType) {
        return new Authorship(evidenceId, ANALYSIS, REPO_ID, SHA, USER_ID, contributionType, 1);
    }
}
