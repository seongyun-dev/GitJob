package com.example.git_job.analysis.outbox;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

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
 * 집계 쿼리를 실제 PostgreSQL 로 고정한다.
 *
 * <p>집계는 조용히 틀린다. 조인 하나가 어긋나면 행이 곱해지고, 그래도 결과는
 * 그럴듯한 숫자라 화면에서 알아볼 수 없다. 그래서 여기서 세는 값은 손으로 셀 수
 * 있게 적게 넣는다.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class TechnologyProfileStoreTest {

    private static final long USER = 7L;
    private static final long OTHER_USER = 8L;
    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";
    private static final Instant NOW = Instant.parse("2026-09-11T00:00:00Z");

    private PostgreSQLContainer postgres;
    private HikariDataSource dataSource;
    private JdbcTemplate jdbc;
    private TechnologyProfileStore store;
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
        store = new TechnologyProfileStore(jdbc);
        registry = jdbc.queryForObject(
                "SELECT registry_version FROM technology_registry WHERE status = 'CURRENT'",
                String.class);

        // analysis_job 이 user 를 참조한다. 없는 사용자의 분석은 만들 수 없다.
        for (long id : new long[] {USER, OTHER_USER}) {
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
    void clearAnalyses() {
        jdbc.update("DELETE FROM analysis_evidence");
        jdbc.update("DELETE FROM analysis_outbox");
        jdbc.update("DELETE FROM analysis_job");
    }

    private void job(String analysisId, long userId, String repositoryId, String fullName,
            String status, Instant completedAt) {
        jdbc.update("""
                INSERT INTO analysis_job (analysis_id, user_id, repository_id,
                    repository_full_name, branch_name, commit_sha, status, current_stage,
                    requested_at, completed_at)
                VALUES (?, ?, ?, ?, 'main', ?, ?, ?, ?, ?)
                """, analysisId, userId, repositoryId, fullName, SHA, status,
                "SUCCEEDED".equals(status) ? "COMPLETED" : "QUEUED",
                Timestamp.from(NOW), completedAt == null ? null : Timestamp.from(completedAt));
    }

    /** 시드 레지스트리에 실제로 있는 규칙만 쓴다. 없는 rule_id 는 조인에서 사라진다. */
    private void evidence(String analysisId, long userId, String ruleId, String path, int line) {
        jdbc.update("""
                INSERT INTO analysis_evidence (analysis_id, user_id, rule_id, file_path,
                    start_line, end_line, fact_type, fact_payload, matched_at, registry_version)
                VALUES (?, ?, ?, ?, ?, ?, 'IMPORT', '{}'::jsonb, ?, ?)
                """, analysisId, userId, ruleId, path, line, line, Timestamp.from(NOW), registry);
    }

    private String ruleOf(String techId, String ruleType) {
        return jdbc.queryForObject("""
                SELECT rule_id FROM evidence_rule
                WHERE tech_id = ? AND rule_type = ? AND registry_version = ?
                ORDER BY rule_id LIMIT 1
                """, String.class, techId, ruleType, registry);
    }

    @Test
    @DisplayName("같은 저장소를 두 번 분석하면 최신 것만 센다")
    void onlyTheLatestAnalysisPerRepositoryCounts() {
        // 합치면 지운 코드가 근거로 남는다. 옛 분석의 근거는 보이면 안 된다.
        job("an_old", USER, "111", "octocat/app", "SUCCEEDED", NOW.minusSeconds(3600));
        job("an_new", USER, "111", "octocat/app", "SUCCEEDED", NOW);
        evidence("an_old", USER, ruleOf("junit", "L1"), "Old.java", 1);
        evidence("an_new", USER, ruleOf("lombok", "L1"), "New.java", 2);

        List<TechnologyProfileStore.TechnologyVerdict> verdicts = store.verdicts(USER);

        assertEquals(1, verdicts.size());
        assertEquals("lombok", verdicts.getFirst().techId());
    }

    @Test
    @DisplayName("완료 시각 없는 레거시 행보다 완료된 분석을 최신으로 고른다")
    void completedAnalysisWinsOverLegacyRowWithoutCompletedAt() {
        job("an_legacy", USER, "111", "octocat/app", "SUCCEEDED", null);
        job("an_completed", USER, "111", "octocat/app", "SUCCEEDED", NOW.minusSeconds(60));
        evidence("an_legacy", USER, ruleOf("junit", "L1"), "Legacy.java", 1);
        evidence("an_completed", USER, ruleOf("lombok", "L1"), "Completed.java", 1);

        assertEquals(List.of("lombok"), store.verdicts(USER).stream()
                .map(TechnologyProfileStore.TechnologyVerdict::techId).toList());
    }

    @Test
    @DisplayName("여러 저장소에 걸치면 가장 높은 Level 을 채택한다")
    void theHighestLevelAcrossRepositoriesWins() {
        // 한쪽에서 import 만, 다른 쪽에서 호출까지 확인됐다면 답은 "해 봤다"이다.
        job("an_a", USER, "111", "octocat/a", "SUCCEEDED", NOW);
        job("an_b", USER, "222", "octocat/b", "SUCCEEDED", NOW);
        evidence("an_a", USER, ruleOf("spring-boot", "L1"), "A.java", 1);
        evidence("an_b", USER, ruleOf("spring-boot", "L2"), "B.java", 1);

        var verdict = store.verdicts(USER).getFirst();

        assertEquals("spring-boot", verdict.techId());
        assertEquals("L2", verdict.repositoryLevel());
        assertEquals(2, verdict.evidenceCount());
        assertEquals(2, verdict.repositoryCount());
    }

    @Test
    @DisplayName("실패한 분석의 근거는 세지 않는다")
    void evidenceFromAFailedAnalysisIsIgnored() {
        // FAILED 인데 근거가 있으면 계약 위반이지만, 조회 쪽도 그것에 기대지 않는다.
        job("an_fail", USER, "111", "octocat/app", "FAILED", NOW);
        evidence("an_fail", USER, ruleOf("junit", "L1"), "T.java", 1);

        assertTrue(store.verdicts(USER).isEmpty());
        assertEquals(0, store.summary(USER).repositoryCount());
    }

    @Test
    @DisplayName("남의 분석은 섞이지 않는다")
    void anotherUsersAnalysisIsNotIncluded() {
        job("an_mine", USER, "111", "octocat/app", "SUCCEEDED", NOW);
        job("an_theirs", OTHER_USER, "222", "someone/app", "SUCCEEDED", NOW);
        evidence("an_mine", USER, ruleOf("junit", "L1"), "T.java", 1);
        evidence("an_theirs", OTHER_USER, ruleOf("lombok", "L1"), "T.java", 1);

        assertEquals(List.of("junit"), store.verdicts(USER).stream()
                .map(TechnologyProfileStore.TechnologyVerdict::techId).toList());
    }

    @Test
    @DisplayName("지표는 기술 수·L2 이상·저장소 수를 센다")
    void theSummaryCountsWhatTheHeaderShows() {
        job("an_a", USER, "111", "octocat/a", "SUCCEEDED", NOW);
        job("an_b", USER, "222", "octocat/b", "SUCCEEDED", NOW.minusSeconds(60));
        evidence("an_a", USER, ruleOf("spring-boot", "L2"), "A.java", 1);
        evidence("an_a", USER, ruleOf("junit", "L1"), "A.java", 2);
        evidence("an_b", USER, ruleOf("lombok", "L0"), "build.gradle", 1);

        var summary = store.summary(USER);

        assertEquals(3, summary.technologyCount());
        assertEquals(1, summary.advancedCount());
        assertEquals(2, summary.repositoryCount());
        assertEquals(NOW, summary.analyzedAt());
    }

    @Test
    @DisplayName("분석한 적이 없으면 지표가 0이고 시각은 비어 있다")
    void anEmptyProfileIsNotAnError() {
        // 0 과 null 을 구분해야 화면이 "분석해 보세요"와 "결과가 없었습니다"를
        // 다르게 말할 수 있다.
        var summary = store.summary(USER);

        assertEquals(0, summary.technologyCount());
        assertEquals(0, summary.repositoryCount());
        assertNull(summary.analyzedAt());
        assertTrue(store.repositories(USER).isEmpty());
    }

    @Test
    @DisplayName("근거가 0건인 저장소도 목록에 남는다")
    void aRepositoryWithNoEvidenceStillAppears() {
        // 분석했는데 아는 기술이 없었던 것과, 분석 자체를 안 한 것은 다르다.
        job("an_empty", USER, "111", "octocat/empty", "SUCCEEDED", NOW);

        var repositories = store.repositories(USER);

        assertEquals(1, repositories.size());
        assertEquals("octocat/empty", repositories.getFirst().repositoryFullName());
        assertEquals(0, repositories.getFirst().evidenceCount());
    }

    @Test
    @DisplayName("완료 시각 없는 레거시 분석도 저장소 목록에서 읽을 수 있다")
    void legacyAnalysisWithoutCompletedAtHasANullTimestamp() {
        job("an_legacy", USER, "111", "octocat/legacy", "SUCCEEDED", null);

        var repositories = store.repositories(USER);

        assertEquals(1, repositories.size());
        assertNull(repositories.getFirst().completedAt());
    }

    @Test
    @DisplayName("근거는 파일과 라인, 커밋까지 함께 온다")
    void evidenceCarriesWhatAPermalinkNeeds() {
        job("an_a", USER, "111", "octocat/app", "SUCCEEDED", NOW);
        evidence("an_a", USER, ruleOf("spring-boot", "L1"), "src/App.java", 12);

        var line = store.evidence(USER, "spring-boot", 100).getFirst();

        assertEquals("octocat/app", line.repositoryFullName());
        assertEquals(SHA, line.commitSha());
        assertEquals("src/App.java", line.filePath());
        assertEquals(12, line.startLine());
        assertNotNull(line.ruleName());
    }

    @Test
    @DisplayName("레지스트리에 있는 기술과 오타를 구분한다")
    void aTypoIsNotTheSameAsNoEvidence() {
        assertTrue(store.isKnownTechnology("spring-boot"));
        assertFalse(store.isKnownTechnology("spirng-boot"));
    }
}
