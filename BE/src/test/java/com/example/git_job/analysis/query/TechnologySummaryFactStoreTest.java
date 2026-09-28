package com.example.git_job.analysis.query;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.query.TechnologySummaryFactStore.EvidenceFact;
import com.example.git_job.analysis.query.TechnologySummaryFactStore.LevelRules;
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
 * Fact Pack 을 채우는 질의를 실제 PostgreSQL 로 고정한다.
 *
 * <p>여기서 틀리면 요약이 "근거가 없다"고 말한다. 그 문장은 분석이 안 된 것과
 * 구별되지 않아 화면에서 알아볼 수 없으므로, 조인과 NULL 처리를 직접 건다.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class TechnologySummaryFactStoreTest {

    private static final long USER = 21L;
    private static final long OTHER = 22L;
    private static final String REPO = "331";
    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";
    private static final String OTHER_SHA = "9734616eb64fdea257a5f90ea73a56d46e88567b";
    private static final Instant NOW = Instant.parse("2026-09-15T00:00:00Z");

    private PostgreSQLContainer postgres;
    private HikariDataSource dataSource;
    private JdbcTemplate jdbc;
    private TechnologySummaryFactStore store;
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
        store = new TechnologySummaryFactStore(jdbc);
        registry = jdbc.queryForObject(
                "SELECT registry_version FROM technology_registry WHERE status = 'CURRENT'",
                String.class);

        for (long id : new long[] {USER, OTHER}) {
            jdbc.update("""
                    INSERT INTO "user" (user_id, github_id, github_login, name, role)
                    VALUES (?, ?, ?, ?, 'USER')
                    """, id, id, "user" + id, "User " + id);
        }
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

    private void job(String analysisId, long userId) {
        jdbc.update("""
                INSERT INTO analysis_job (analysis_id, user_id, repository_id,
                    repository_full_name, branch_name, commit_sha, status, current_stage,
                    requested_at, completed_at)
                VALUES (?, ?, ?, 'octocat/app', 'main', ?, 'SUCCEEDED', 'COMPLETED', ?, ?)
                """, analysisId, userId, REPO, SHA, Timestamp.from(NOW), Timestamp.from(NOW));
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

    /** 그 근거의 기여 판정을 남긴다. {@code type} 이 판정 결과다. */
    private void contribution(long evidenceId, String analysisId, String type, String sha) {
        jdbc.update("""
                INSERT INTO analysis_evidence_commit
                    (analysis_evidence_id, analysis_id, repository_id, commit_sha,
                     user_id, contribution_type, matched_line_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """, evidenceId, analysisId, REPO, sha, USER, type);
    }

    private void commit(String sha, Instant authoredAt) {
        jdbc.update("""
                INSERT INTO repository_commit (repository_id, commit_sha, author_name,
                    github_login, authored_at)
                VALUES (?, ?, 'someone', 'someone', ?)
                """, REPO, sha, Timestamp.from(authoredAt));
    }

    // ---- authorship -------------------------------------------------------

    @Test
    @DisplayName("기여 판정이 하나도 없으면 NOT_VERIFIED")
    void noContributionRowsIsNotVerified() {
        // 근거는 있는데 아무도 작성자를 확인하지 않은 상태다. "본인이 안 썼다"와
        // 다르며, 요약이 그 둘을 다르게 말해야 한다.
        job("an_1", USER);
        evidence("an_1", ruleOf("lombok", "L1"), "IMPORT",
                "{\"MODULE\":\"lombok.Getter\"}", "a/A.java", 1, SHA);

        assertEquals("NOT_VERIFIED", store.authorship(USER, "lombok"));
    }

    @Test
    @DisplayName("본인 근거가 과반이면 MOSTLY_MINE")
    void majorityMineIsMostlyMine() {
        job("an_1", USER);
        String rule = ruleOf("lombok", "L1");
        long first = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Getter\"}",
                "a/A.java", 1, SHA);
        long second = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Setter\"}",
                "a/B.java", 1, SHA);
        long third = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Builder\"}",
                "a/C.java", 1, OTHER_SHA);
        contribution(first, "an_1", "SOLE_AUTHOR", SHA);
        contribution(second, "an_1", "CO_AUTHORED", SHA);
        contribution(third, "an_1", "OTHER_AUTHOR", OTHER_SHA);

        assertEquals("MOSTLY_MINE", store.authorship(USER, "lombok"));
    }

    @Test
    @DisplayName("판정은 있는데 본인 것이 하나도 없으면 MOSTLY_OTHERS")
    void judgedButNoneMineIsMostlyOthers() {
        job("an_1", USER);
        String rule = ruleOf("lombok", "L1");
        long only = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Getter\"}",
                "a/A.java", 1, OTHER_SHA);
        contribution(only, "an_1", "OTHER_AUTHOR", OTHER_SHA);

        assertEquals("MOSTLY_OTHERS", store.authorship(USER, "lombok"));
    }

    @Test
    @DisplayName("미판정 근거는 분모에 넣지 않는다")
    void unjudgedEvidenceIsNotCountedAgainstTheUser() {
        // 미판정은 "남이 썼다"가 아니라 "모른다"다. 분모에 넣으면 본인 몫이
        // 체계적으로 과소평가된다 -- 실측에서 81% 가 MIXED 로 나왔다.
        job("an_1", USER);
        String rule = ruleOf("lombok", "L1");
        long mineRow = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Getter\"}",
                "a/A.java", 1, SHA);
        contribution(mineRow, "an_1", "SOLE_AUTHOR", SHA);
        // 판정이 없는 근거 셋. 이것들 때문에 구간이 내려가면 안 된다.
        for (int i = 0; i < 3; i++) {
            evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Kind" + i + "\"}",
                    "a/B" + i + ".java", 1, OTHER_SHA);
        }

        assertEquals("MOSTLY_MINE", store.authorship(USER, "lombok"));
    }

    @Test
    @DisplayName("UNVERIFIED 행도 분모에 넣지 않는다")
    void unverifiedRowsAreNotCountedAgainstTheUser() {
        // 행이 있다는 것과 답을 얻었다는 것은 다르다. UNVERIFIED 는 GitHub 이 커밋을
        // 계정에 붙이지 못했거나 조회 상한에 걸려 묻지 못한 근거이고, 분모에 넣으면
        // 바로 위 테스트가 막으려던 과소평가가 행이 있다는 이유만으로 되살아난다.
        job("an_1", USER);
        String rule = ruleOf("lombok", "L1");
        long mineRow = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Getter\"}",
                "a/A.java", 1, SHA);
        contribution(mineRow, "an_1", "SOLE_AUTHOR", SHA);
        for (int i = 0; i < 3; i++) {
            long row = evidence("an_1", rule, "IMPORT",
                    "{\"MODULE\":\"lombok.Kind" + i + "\"}", "a/B" + i + ".java", 1, OTHER_SHA);
            contribution(row, "an_1", "UNVERIFIED", OTHER_SHA);
        }

        assertEquals("MOSTLY_MINE", store.authorship(USER, "lombok"));
    }


    @Test
    @DisplayName("본인 것이 소수면 MOSTLY_OTHERS")
    void smallMinorityIsMostlyOthers() {
        // 본인 근거가 두어 건뿐인데 MIXED 로 올리면 요약이 그것을 대등하게 말한다.
        job("an_1", USER);
        String rule = ruleOf("lombok", "L1");
        long mineRow = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Getter\"}",
                "a/A.java", 1, SHA);
        contribution(mineRow, "an_1", "SOLE_AUTHOR", SHA);
        for (int i = 0; i < 5; i++) {
            long row = evidence("an_1", rule, "IMPORT",
                    "{\"MODULE\":\"lombok.Kind" + i + "\"}", "a/B" + i + ".java", 1, OTHER_SHA);
            contribution(row, "an_1", "OTHER_AUTHOR", OTHER_SHA);
        }

        assertEquals("MOSTLY_OTHERS", store.authorship(USER, "lombok"));
    }

    @Test
    @DisplayName("본인 것이 있지만 과반은 아니면 MIXED")
    void minorityMineIsMixed() {
        job("an_1", USER);
        String rule = ruleOf("lombok", "L1");
        long first = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Getter\"}",
                "a/A.java", 1, SHA);
        long second = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Setter\"}",
                "a/B.java", 1, OTHER_SHA);
        long third = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Builder\"}",
                "a/C.java", 1, OTHER_SHA);
        contribution(first, "an_1", "SOLE_AUTHOR", SHA);
        contribution(second, "an_1", "OTHER_AUTHOR", OTHER_SHA);
        contribution(third, "an_1", "OTHER_AUTHOR", OTHER_SHA);

        assertEquals("MIXED", store.authorship(USER, "lombok"));
    }

    @Test
    @DisplayName("PARTIAL_EDIT 는 본인 근거로 세지 않는다")
    void partialEditDoesNotCountAsMine() {
        // 정의상 그 근거 줄을 본인이 쓰지 않았다. 파일을 만졌다는 것은 레벨의
        // 근거가 아니다.
        job("an_1", USER);
        String rule = ruleOf("lombok", "L1");
        long only = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Getter\"}",
                "a/A.java", 1, OTHER_SHA);
        contribution(only, "an_1", "PARTIAL_EDIT", OTHER_SHA);

        assertEquals("MOSTLY_OTHERS", store.authorship(USER, "lombok"));
    }

    @Test
    @DisplayName("남의 분석은 섞이지 않는다")
    void otherUsersAnalysesAreExcluded() {
        job("an_mine", USER);
        job("an_theirs", OTHER);
        evidence("an_mine", ruleOf("lombok", "L1"), "IMPORT",
                "{\"MODULE\":\"lombok.Getter\"}", "a/A.java", 1, SHA);

        assertEquals(1, store.facts(USER, "lombok").size());
        assertTrue(store.facts(OTHER, "lombok").isEmpty());
    }

    // ---- facts ------------------------------------------------------------

    @Test
    @DisplayName("기여 판정이 없는 근거도 사실로 나온다 (LEFT JOIN)")
    void factsSurviveWithoutContributionRows() {
        // INNER 로 조이면 기여 판정 전 분석의 근거가 통째로 사라지고 highlights 가
        // 빈 채로 나간다. 그러면 요약이 아무것도 말하지 못한다.
        job("an_1", USER);
        evidence("an_1", ruleOf("lombok", "L1"), "IMPORT",
                "{\"MODULE\":\"lombok.Getter\"}", "a/A.java", 1, SHA);

        List<EvidenceFact> facts = store.facts(USER, "lombok");

        assertEquals(1, facts.size());
        assertEquals(null, facts.getFirst().mine(), "판정이 없으면 false 가 아니라 null 이다");
    }

    @Test
    @DisplayName("fact_payload 는 원문 그대로 온다")
    void payloadTravelsUnparsed() {
        job("an_1", USER);
        evidence("an_1", ruleOf("lombok", "L1"), "IMPORT",
                "{\"MODULE\":\"lombok.Getter\"}", "a/A.java", 1, SHA);

        assertTrue(store.facts(USER, "lombok").getFirst().payloadJson().contains("lombok.Getter"));
    }

    // ---- levels -----------------------------------------------------------

    @Test
    @DisplayName("Level 은 높은 것부터, mine 은 그 Level 에 본인 근거가 있는지")
    void levelsAreOrderedAndFlagMine() {
        job("an_1", USER);
        String l1 = ruleOf("spring-boot", "L1");
        String l2 = ruleOf("spring-boot", "L2");
        evidence("an_1", l1, "IMPORT", "{\"MODULE\":\"org.springframework.boot\"}",
                "a/A.java", 1, SHA);
        long call = evidence("an_1", l2, "API_CALL",
                "{\"CALL\":\"SpringApplication.run\"}", "a/B.java", 1, SHA);
        contribution(call, "an_1", "SOLE_AUTHOR", SHA);

        List<LevelRules> levels = store.levels(USER, "spring-boot");

        assertEquals(List.of("L2", "L1"), levels.stream().map(LevelRules::level).toList());
        assertTrue(levels.getFirst().mine(), "L2 근거를 본인이 썼다");
        assertFalse(levels.getLast().mine(), "L1 근거에는 판정이 없다");
    }

    // ---- period -----------------------------------------------------------

    @Test
    @DisplayName("기간은 본인 커밋만 센다")
    void periodCoversOnlyTheUsersCommits() {
        // 남의 커밋까지 재면 합류하기 전의 기간이 본인 것이 된다.
        job("an_1", USER);
        String rule = ruleOf("lombok", "L1");
        long mineRow = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Getter\"}",
                "a/A.java", 1, SHA);
        long theirRow = evidence("an_1", rule, "IMPORT", "{\"MODULE\":\"lombok.Setter\"}",
                "a/B.java", 1, OTHER_SHA);
        contribution(mineRow, "an_1", "SOLE_AUTHOR", SHA);
        contribution(theirRow, "an_1", "UNVERIFIED", OTHER_SHA);
        commit(SHA, Instant.parse("2025-08-11T00:00:00Z"));
        commit(OTHER_SHA, Instant.parse("2024-01-01T00:00:00Z"));

        var span = store.period(USER, "lombok").orElseThrow();

        assertEquals(Instant.parse("2025-08-11T00:00:00Z"), span.first());
        assertEquals(Instant.parse("2025-08-11T00:00:00Z"), span.last());
    }

    @Test
    @DisplayName("본인 커밋이 캐시에 없으면 기간은 비어 있다")
    void periodIsEmptyWithoutCachedCommits() {
        // 지어내지 않는다. 비어 있으면 요약이 기간을 언급하지 않는다.
        job("an_1", USER);
        long row = evidence("an_1", ruleOf("lombok", "L1"), "IMPORT",
                "{\"MODULE\":\"lombok.Getter\"}", "a/A.java", 1, SHA);
        contribution(row, "an_1", "SOLE_AUTHOR", SHA);

        assertTrue(store.period(USER, "lombok").isEmpty());
    }

    // ---- next level -------------------------------------------------------

    @Test
    @DisplayName("규칙이 없는 Level 을 물으면 비어 있다")
    void missingIsEmptyWhenTheLevelHasNoRule() {
        // 기술 29개 중 L3 규칙을 가진 것은 둘뿐이다. 흔한 경우이고 실패가 아니다.
        job("an_1", USER);

        assertTrue(store.missingForLevel(USER, "lombok", registry, "L3").isEmpty());
    }

    @Test
    @DisplayName("규칙이 안 걸렸으면 그 절의 기대값이 전부 남는다")
    void everyExpectedValueIsMissingWhenNothingMatched() {
        job("an_1", USER);

        var missing = store.missingForLevel(USER, "spring-boot", registry, "L2").orElseThrow();

        assertFalse(missing.missing().isEmpty());
        assertFalse(missing.ruleName().isBlank());
    }

    @Test
    @DisplayName("본인이 덮은 절은 빠진다")
    void coveredClausesDropOut() {
        // Repository 에서는 걸렸는데 Personal 이 못 미친 경우다. 본인이 이미 한
        // 것을 다시 하라고 말하면 안 된다.
        job("an_1", USER);
        String l2 = ruleOf("spring-boot", "L2");
        List<String> before = store.missingForLevel(USER, "spring-boot", registry, "L2")
                .orElseThrow().missing();

        long importRow = evidence("an_1", l2, "IMPORT",
                "{\"MODULE\":\"org.springframework.boot\"}", "a/A.java", 1, SHA);
        contribution(importRow, "an_1", "SOLE_AUTHOR", SHA);

        List<String> after = store.missingForLevel(USER, "spring-boot", registry, "L2")
                .orElseThrow().missing();

        assertTrue(after.size() < before.size(),
                "IMPORT 절을 본인이 덮었는데 기대값이 그대로다");
    }
}
