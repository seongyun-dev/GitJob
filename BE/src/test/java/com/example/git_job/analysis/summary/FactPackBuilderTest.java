package com.example.git_job.analysis.summary;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.query.TechnologyProfileStore;
import com.example.git_job.analysis.query.TechnologySummaryFactStore;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.postgresql.PostgreSQLContainer;

/**
 * 조립 결정을 고정한다.
 *
 * <p>질의가 맞아도 조립이 틀리면 요약이 없는 사실을 말한다. 특히 비워 둬야 할
 * 자리를 채우는 실수는 카드에서 드러나지 않으므로, 여기서는 "무엇이 {@code null}
 * 인가"를 질의 결과만큼 자주 확인한다.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class FactPackBuilderTest {

    private static final long USER = 31L;
    private static final String REPO = "441";
    private static final String OTHER_REPO = "442";
    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";
    private static final String OTHER_SHA = "9734616eb64fdea257a5f90ea73a56d46e88567b";
    private static final Instant NOW = Instant.parse("2026-09-15T00:00:00Z");

    private PostgreSQLContainer postgres;
    private HikariDataSource dataSource;
    private JdbcTemplate jdbc;
    private FactPackBuilder builder;
    private String registry;

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
        builder = new FactPackBuilder(new TechnologyProfileStore(jdbc),
                new TechnologySummaryFactStore(jdbc), new HighlightSelector());
        registry = jdbc.queryForObject(
                "SELECT registry_version FROM technology_registry WHERE status = 'CURRENT'",
                String.class);

        jdbc.update("""
                INSERT INTO "user" (user_id, github_id, github_login, name, role)
                VALUES (?, ?, 'user31', 'User 31', 'USER')
                """, USER, USER);
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

    @BeforeEach
    void clear() {
        jdbc.update("DELETE FROM analysis_evidence_commit");
        jdbc.update("DELETE FROM analysis_evidence");
        jdbc.update("DELETE FROM analysis_outbox");
        jdbc.update("DELETE FROM analysis_job");
        jdbc.update("DELETE FROM repository_commit");
    }

    // ---- fixtures ---------------------------------------------------------

    private void job(String analysisId, String repositoryId, String fullName) {
        jdbc.update("""
                INSERT INTO analysis_job (analysis_id, user_id, repository_id,
                    repository_full_name, branch_name, commit_sha, status, current_stage,
                    requested_at, completed_at)
                VALUES (?, ?, ?, ?, 'main', ?, 'SUCCEEDED', 'COMPLETED', ?, ?)
                """, analysisId, USER, repositoryId, fullName, SHA,
                Timestamp.from(NOW), Timestamp.from(NOW));
    }

    private String ruleOf(String techId, String ruleType) {
        return jdbc.queryForObject("""
                SELECT rule_id FROM evidence_rule
                WHERE tech_id = ? AND rule_type = ? AND registry_version = ?
                ORDER BY rule_id LIMIT 1
                """, String.class, techId, ruleType, registry);
    }

    private long evidence(String analysisId, String ruleId, String factType, String payload,
            String path, int line, String commitSha) {
        return jdbc.queryForObject("""
                INSERT INTO analysis_evidence (analysis_id, user_id, rule_id, file_path,
                    start_line, end_line, fact_type, fact_payload, matched_at,
                    registry_version, commit_sha)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?)
                RETURNING analysis_evidence_id
                """, Long.class, analysisId, USER, ruleId, path, line, line, factType,
                payload, Timestamp.from(NOW), registry, commitSha);
    }

    private void contribution(long evidenceId, String analysisId, String repositoryId,
            String type, String sha) {
        jdbc.update("""
                INSERT INTO analysis_evidence_commit
                    (analysis_evidence_id, analysis_id, repository_id, commit_sha,
                     user_id, contribution_type, matched_line_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """, evidenceId, analysisId, repositoryId, sha, USER, type);
    }

    private void commit(String repositoryId, String sha, String authoredAt) {
        jdbc.update("""
                INSERT INTO repository_commit (repository_id, commit_sha, author_name,
                    github_login, authored_at)
                VALUES (?, ?, 'someone', 'someone', ?)
                """, repositoryId, sha, Timestamp.from(Instant.parse(authoredAt)));
    }

    /** lombok L1 근거 하나. 가장 단순한 출발점이다. */
    private long lombokImport(String analysisId, String path) {
        return evidence(analysisId, ruleOf("lombok", "L1"), "IMPORT",
                "{\"MODULE\":\"lombok.Getter\"}", path, 1, SHA);
    }

    // ---- 없는 것 ----------------------------------------------------------

    @Test
    @DisplayName("판정이 없는 기술은 비어 있다")
    void unknownTechnologyIsEmpty() {
        // 오류가 아니다. 분석하지 않았거나 그 기술이 안 나온 상태다.
        job("an_1", REPO, "octocat/app");

        assertTrue(builder.build(USER, "lombok").isEmpty());
    }

    @Test
    @DisplayName("계약이 요구하는 고정값을 싣는다")
    void carriesTheContractConstants() {
        job("an_1", REPO, "octocat/app");
        lombokImport("an_1", "a/A.java");

        FactPack pack = builder.build(USER, "lombok").orElseThrow();

        assertEquals("technology-summary-request/v1", pack.schemaVersion());
        assertEquals("ko-KR", pack.locale());
        assertEquals("lombok", pack.technology().techId());
        assertEquals(registry, pack.technology().registryVersion());
    }

    // ---- personal level ---------------------------------------------------

    @Test
    @DisplayName("기여 판정이 없으면 personal_level 은 L0 이고 authorship 이 그것을 말한다")
    void withoutContributionPersonalLevelIsLowestAndAuthorshipSaysWhy() {
        // L0 을 보내는 것만으로는 "선언은 했다"로 읽힌다. 그 값이 미확인이라는
        // 사실은 authorship 이 실어야 한다 -- 둘이 함께 가야 뜻이 맞는다.
        job("an_1", REPO, "octocat/app");
        lombokImport("an_1", "a/A.java");

        FactPack pack = builder.build(USER, "lombok").orElseThrow();

        assertEquals("L1", pack.technology().repositoryLevel());
        assertEquals("L0", pack.technology().personalLevel());
        assertEquals("NOT_VERIFIED", pack.authorship());
    }

    @Test
    @DisplayName("본인이 쓴 근거가 있으면 personal_level 이 선다")
    void personalLevelRisesWithOwnEvidence() {
        job("an_1", REPO, "octocat/app");
        long row = lombokImport("an_1", "a/A.java");
        contribution(row, "an_1", REPO, "SOLE_AUTHOR", SHA);

        FactPack pack = builder.build(USER, "lombok").orElseThrow();

        assertEquals("L1", pack.technology().personalLevel());
        assertEquals("MOSTLY_MINE", pack.authorship());
    }

    // ---- next level -------------------------------------------------------

    @Test
    @DisplayName("다음 Level 은 한 단계 위만 가리킨다")
    void nextLevelIsOneStepUp() {
        // spring-boot 는 L2(bootstrap) 와 L3(actuator) 를 모두 갖고 있다. personal
        // 이 L1 이면 답은 L2 여야 한다 -- L3 를 가리키면 한 단계를 건너뛴 것이다.
        job("an_1", REPO, "octocat/app");
        long row = evidence("an_1", ruleOf("spring-boot", "L1"), "IMPORT",
                "{\"MODULE\":\"org.springframework.boot\"}", "a/A.java", 1, SHA);
        contribution(row, "an_1", REPO, "SOLE_AUTHOR", SHA);

        FactPack pack = builder.build(USER, "spring-boot").orElseThrow();

        assertEquals("L1", pack.technology().personalLevel());
        assertNotNull(pack.nextLevel());
        assertEquals("L2", pack.nextLevel().level());
    }

    @Test
    @DisplayName("다음 Level 에 규칙이 없으면 비운다")
    void noRuleAtNextLevelLeavesItNull() {
        // lombok 은 L0·L1 뿐이다(L2 는 23개 기술에만 있고 lombok 은 빠져 있다).
        // personal 이 L1 이면 물을 다음 Level 이 없다. 건너뛰어 L3 를 가리키면
        // 도달할 수 없는 목표가 붙는다.
        job("an_1", REPO, "octocat/app");
        long row = lombokImport("an_1", "a/A.java");
        contribution(row, "an_1", REPO, "SOLE_AUTHOR", SHA);

        FactPack pack = builder.build(USER, "lombok").orElseThrow();

        assertEquals("L1", pack.technology().personalLevel());
        assertNull(pack.nextLevel(), "규칙이 없는 Level 을 가리켰다");
    }

    @Test
    @DisplayName("기대값은 네 개까지만 싣는다")
    void missingIsCapped() {
        // 한 절이 메서드 이름 여럿을 OR 로 묶는다. 전부 나열하면 요약이 그것을
        // 옮기다 200자를 넘겨 버려진다.
        job("an_1", REPO, "octocat/app");
        long row = evidence("an_1", ruleOf("spring-boot", "L1"), "IMPORT",
                "{\"MODULE\":\"org.springframework.boot\"}", "a/A.java", 1, SHA);
        contribution(row, "an_1", REPO, "SOLE_AUTHOR", SHA);

        FactPack pack = builder.build(USER, "spring-boot").orElseThrow();

        assertNotNull(pack.nextLevel());
        assertFalse(pack.nextLevel().missing().isEmpty());
        assertTrue(pack.nextLevel().missing().size() <= 4,
                "기대값이 넷을 넘었다: " + pack.nextLevel().missing());
    }

    // ---- repositories -----------------------------------------------------

    @Test
    @DisplayName("기여가 확인되지 않은 저장소는 mine 이 false 다")
    void repositoryMineIsNotAssumed() {
        // 팀 저장소에 그 기술이 쓰였다는 것과 이 사람이 썼다는 것은 다르다.
        job("an_mine", REPO, "octocat/mine");
        job("an_theirs", OTHER_REPO, "octocat/theirs");
        long ours = lombokImport("an_mine", "a/A.java");
        contribution(ours, "an_mine", REPO, "SOLE_AUTHOR", SHA);
        evidence("an_theirs", ruleOf("lombok", "L1"), "IMPORT",
                "{\"MODULE\":\"lombok.Setter\"}", "b/B.java", 1, OTHER_SHA);

        FactPack pack = builder.build(USER, "lombok").orElseThrow();

        assertEquals(List.of("octocat/mine", "octocat/theirs"),
                pack.repositories().stream().map(FactPack.RepositoryRef::fullName).toList());
        assertTrue(pack.repositories().getFirst().mine());
        assertFalse(pack.repositories().getLast().mine(),
                "기여가 확인되지 않은 저장소를 본인 것으로 표시했다");
    }

    // ---- period -----------------------------------------------------------

    @Test
    @DisplayName("본인 커밋이 캐시에 없으면 기간을 비운다")
    void periodIsNullWithoutCachedCommits() {
        // 저장소의 첫 커밋으로 채우면 합류 전 남의 작업이 본인 기간이 된다.
        job("an_1", REPO, "octocat/app");
        long row = lombokImport("an_1", "a/A.java");
        contribution(row, "an_1", REPO, "SOLE_AUTHOR", SHA);

        assertNull(builder.build(USER, "lombok").orElseThrow().period());
    }

    @Test
    @DisplayName("하루만 만졌어도 기간은 0 이 아니라 1 이다")
    void oneDayIsOneMonth() {
        // 0 은 "쓴 적 없다"로 읽힌다.
        job("an_1", REPO, "octocat/app");
        long row = lombokImport("an_1", "a/A.java");
        contribution(row, "an_1", REPO, "SOLE_AUTHOR", SHA);
        commit(REPO, SHA, "2025-08-11T00:00:00Z");

        FactPack.Period period = builder.build(USER, "lombok").orElseThrow().period();

        assertNotNull(period);
        assertEquals(1, period.months());
        assertEquals(period.first(), period.last());
    }

    @Test
    @DisplayName("걸친 달을 센다")
    void countsCalendarMonthsSpanned() {
        job("an_1", REPO, "octocat/app");
        String rule = ruleOf("lombok", "L1");
        long first = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Getter\"}",
                "a/A.java", 1, SHA);
        long last = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Setter\"}",
                "a/B.java", 1, OTHER_SHA);
        contribution(first, "an_1", REPO, "SOLE_AUTHOR", SHA);
        contribution(last, "an_1", REPO, "SOLE_AUTHOR", OTHER_SHA);
        commit(REPO, SHA, "2025-08-11T00:00:00Z");
        commit(REPO, OTHER_SHA, "2025-10-02T00:00:00Z");

        FactPack.Period period = builder.build(USER, "lombok").orElseThrow().period();

        assertEquals(3, period.months(), "8월·9월·10월");
    }

    // ---- highlights -------------------------------------------------------

    @Test
    @DisplayName("근거가 많아도 여덟 개를 넘지 않는다")
    void highlightsStayWithinTheContractLimit() {
        job("an_1", REPO, "octocat/app");
        String rule = ruleOf("lombok", "L1");
        for (int i = 0; i < 12; i++) {
            evidence("an_1", rule, "IMPORT",
                    "{\"MODULE\":\"lombok.Kind" + i + "\"}", "a/A.java", i + 1, SHA);
        }

        FactPack pack = builder.build(USER, "lombok").orElseThrow();

        assertEquals(FactPack.MAX_HIGHLIGHTS, pack.highlights().size());
        assertEquals(List.of(0, 1, 2, 3, 4, 5, 6, 7),
                pack.highlights().stream().map(FactPack.Highlight::index).toList());
    }

    @Test
    @DisplayName("같은 입력이면 같은 Fact Pack 이 나온다")
    void isDeterministic() {
        // 캐시 키가 이 객체 전체의 해시다. 두 번 만들어 다르면 캐시가 안 맞는다.
        job("an_1", REPO, "octocat/app");
        String rule = ruleOf("lombok", "L1");
        for (int i = 0; i < 5; i++) {
            evidence("an_1", rule, "IMPORT",
                    "{\"MODULE\":\"lombok.Kind" + i + "\"}", "a/A.java", i + 1, SHA);
        }

        assertEquals(builder.build(USER, "lombok").orElseThrow(),
                builder.build(USER, "lombok").orElseThrow());
    }
}
