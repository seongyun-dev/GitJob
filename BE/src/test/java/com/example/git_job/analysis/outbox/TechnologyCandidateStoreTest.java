package com.example.git_job.analysis.outbox;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.event.TechnologyCandidate;
import com.example.git_job.analysis.event.TechnologyCandidate.Ecosystem;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.time.Instant;
import java.util.List;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.postgresql.PostgreSQLContainer;

/**
 * The candidate store against a real PostgreSQL.
 *
 * <p>Almost all of this class is SQL: an upsert, a conditional column, and an
 * aggregate recomputation. Mocking the JdbcTemplate would assert that the
 * strings are what they are and prove nothing about whether they work.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class TechnologyCandidateStoreTest {

    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";
    private static final Instant SEEN = Instant.parse("2026-09-10T03:00:00Z");

    private PostgreSQLContainer postgres;
    private HikariDataSource dataSource;
    private JdbcTemplate jdbc;
    private TechnologyCandidateStore store;

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
        store = new TechnologyCandidateStore(jdbc);
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

    /** Observations reference a real job and user, so both have to exist. */
    private void givenJob(String analysisId, long userId, String repositoryId) {
        jdbc.update("""
                INSERT INTO "user" (user_id, github_id, github_login, name)
                VALUES (?, ?, ?, 'Octo Cat') ON CONFLICT DO NOTHING
                """, userId, userId, "octocat" + userId);
        jdbc.update("""
                INSERT INTO analysis_job (analysis_id, user_id, repository_id, branch_name,
                                          commit_sha, status, current_stage, requested_at)
                VALUES (?, ?, ?, 'main', ?, 'SUCCEEDED', 'COMPLETED', now())
                """, analysisId, userId, repositoryId, SHA);
    }

    private TechnologyCandidate candidate(String coordinate, String scope, int occurrences) {
        return new TechnologyCandidate(Ecosystem.MAVEN, coordinate, scope, occurrences);
    }

    private Integer users(String coordinate) {
        return jdbc.queryForObject(
                "SELECT distinct_user_count FROM technology_candidate WHERE coordinate = ?",
                Integer.class, coordinate);
    }

    @Test
    @DisplayName("처음 본 의존성이 후보로 등록되고 NEW로 시작한다")
    void aFirstSightingCreatesTheCandidate() {
        givenJob("an_first", 101L, "repo_a");

        store.record("an_first", 101L, "repo_a",
                List.of(candidate("com.h2database:h2", "runtimeOnly", 2)), SEEN);

        var row = jdbc.queryForMap(
                "SELECT * FROM technology_candidate WHERE coordinate = 'com.h2database:h2'");
        assertEquals("NEW", row.get("status"));
        assertEquals(1, row.get("distinct_user_count"));
        assertEquals(1, row.get("distinct_repository_count"));
        assertEquals(2, row.get("occurrence_count"));
        assertEquals("runtimeOnly", row.get("scope"));
    }

    @Test
    @DisplayName("사용자 수로 세지, occurrence 수로 세지 않는다")
    void rankingCountsPeopleNotLines() {
        // 관리자가 답할 질문은 "몇 명에게 영향이 있는가"다. occurrence로 세면
        // 모노레포 하나가 순위를 지배한다.
        givenJob("an_many", 201L, "repo_many");
        givenJob("an_few", 202L, "repo_few");

        store.record("an_many", 201L, "repo_many",
                List.of(candidate("org.example:noisy", "implementation", 50)), SEEN);
        store.record("an_few", 202L, "repo_few",
                List.of(candidate("org.example:noisy", "implementation", 1)), SEEN);

        var row = jdbc.queryForMap(
                "SELECT * FROM technology_candidate WHERE coordinate = 'org.example:noisy'");
        assertEquals(2, row.get("distinct_user_count"));
        assertEquals(51, row.get("occurrence_count"));
    }

    @Test
    @DisplayName("같은 사용자가 저장소 둘에서 써도 사용자는 하나다")
    void oneUserWithTwoRepositoriesCountsOnce() {
        givenJob("an_r1", 301L, "repo_1");
        givenJob("an_r2", 301L, "repo_2");

        store.record("an_r1", 301L, "repo_1", List.of(candidate("org.example:dual", null, 1)), SEEN);
        store.record("an_r2", 301L, "repo_2", List.of(candidate("org.example:dual", null, 1)), SEEN);

        var row = jdbc.queryForMap(
                "SELECT * FROM technology_candidate WHERE coordinate = 'org.example:dual'");
        assertEquals(1, row.get("distinct_user_count"));
        assertEquals(2, row.get("distinct_repository_count"));
    }

    @Test
    @DisplayName("같은 분석이 두 번 반영돼도 카운트가 늘지 않는다")
    void replayingOneAnalysisDoesNotDoubleCount() {
        // 결과 이벤트는 at-least-once다. 카운터를 증가시키는 방식이었다면 이
        // 경우를 되돌릴 방법이 없다.
        givenJob("an_replay", 401L, "repo_replay");
        var candidates = List.of(candidate("org.example:replayed", "implementation", 3));

        store.record("an_replay", 401L, "repo_replay", candidates, SEEN);
        store.record("an_replay", 401L, "repo_replay", candidates, SEEN);

        var row = jdbc.queryForMap(
                "SELECT * FROM technology_candidate WHERE coordinate = 'org.example:replayed'");
        assertEquals(1, row.get("distinct_user_count"));
        assertEquals(3, row.get("occurrence_count"));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM technology_candidate_observation o
                JOIN technology_candidate c ON c.candidate_id = o.candidate_id
                WHERE c.coordinate = 'org.example:replayed'
                """, Integer.class));
    }

    @Test
    @DisplayName("scope가 갈리면 NULL이 되고, 일치하면 유지된다")
    void scopeIsReportedOnlyWhenEverySightingAgrees() {
        // spring-petclinic은 pom.xml과 build.gradle을 둘 다 갖고 있어 같은
        // 라이브러리가 runtime과 runtimeOnly로 선언된다.
        givenJob("an_s1", 501L, "repo_s1");
        givenJob("an_s2", 502L, "repo_s2");
        givenJob("an_s3", 503L, "repo_s3");

        store.record("an_s1", 501L, "repo_s1",
                List.of(candidate("org.example:agreed", "testImplementation", 1)), SEEN);
        store.record("an_s2", 502L, "repo_s2",
                List.of(candidate("org.example:agreed", "testImplementation", 1)), SEEN);
        store.record("an_s1", 501L, "repo_s1",
                List.of(candidate("org.example:split", "runtime", 1)), SEEN);
        store.record("an_s3", 503L, "repo_s3",
                List.of(candidate("org.example:split", "runtimeOnly", 1)), SEEN);

        assertEquals("testImplementation", jdbc.queryForObject(
                "SELECT scope FROM technology_candidate WHERE coordinate = 'org.example:agreed'",
                String.class));
        assertNull(jdbc.queryForObject(
                "SELECT scope FROM technology_candidate WHERE coordinate = 'org.example:split'",
                String.class));
    }

    @Test
    @DisplayName("거부한 후보는 계속 세지만 기본 목록에서 빠진다")
    void aRejectedCandidateKeepsCountingButLeavesTheList() {
        // 거부한 것이 매주 다시 1위로 올라오면 화면이 무용지물이 된다. 그래도
        // 세기는 해야 결정을 다시 볼 근거가 남는다.
        givenJob("an_rej1", 601L, "repo_rej1");
        givenJob("an_rej2", 602L, "repo_rej2");
        store.record("an_rej1", 601L, "repo_rej1",
                List.of(candidate("org.example:rejected", null, 1)), SEEN);
        jdbc.update("""
                UPDATE technology_candidate
                SET status = 'REJECTED', decided_at = now(), decision_note = '범위 밖'
                WHERE coordinate = 'org.example:rejected'
                """);

        store.record("an_rej2", 602L, "repo_rej2",
                List.of(candidate("org.example:rejected", null, 1)), SEEN);

        assertEquals(2, users("org.example:rejected"));
        assertTrue(store.topCandidates(100).stream()
                        .noneMatch(c -> c.coordinate().equals("org.example:rejected")),
                "거부한 후보가 기본 목록에 남아 있다");
    }

    @Test
    @DisplayName("나중에 본 것이 승격 결정을 되돌리지 않는다")
    void a_laterSightingDoesNotReopenADecision() {
        givenJob("an_pro1", 701L, "repo_pro1");
        givenJob("an_pro2", 702L, "repo_pro2");
        store.record("an_pro1", 701L, "repo_pro1",
                List.of(candidate("org.example:promoted", null, 1)), SEEN);
        jdbc.update("""
                UPDATE technology_candidate
                SET status = 'PROMOTED', promoted_tech_id = 'example', decided_at = now()
                WHERE coordinate = 'org.example:promoted'
                """);

        store.record("an_pro2", 702L, "repo_pro2",
                List.of(candidate("org.example:promoted", null, 1)), SEEN);

        var row = jdbc.queryForMap(
                "SELECT * FROM technology_candidate WHERE coordinate = 'org.example:promoted'");
        assertEquals("PROMOTED", row.get("status"));
        assertEquals("example", row.get("promoted_tech_id"));
        assertEquals(2, row.get("distinct_user_count"));
    }

    @Test
    @DisplayName("기본 목록은 사용자 수 내림차순이다")
    void theDefaultListIsRankedByPeopleAffected() {
        givenJob("an_rank1", 801L, "repo_rank1");
        givenJob("an_rank2", 802L, "repo_rank2");
        givenJob("an_rank3", 803L, "repo_rank3");
        for (long user = 801L; user <= 803L; user++) {
            store.record("an_rank" + (user - 800), user, "repo_rank" + (user - 800),
                    List.of(candidate("org.example:popular", null, 1)), SEEN);
        }
        store.record("an_rank1", 801L, "repo_rank1",
                List.of(candidate("org.example:rare", null, 99)), SEEN);

        var ranked = store.topCandidates(100).stream()
                .filter(c -> c.coordinate().startsWith("org.example:pop")
                        || c.coordinate().startsWith("org.example:rare"))
                .toList();

        assertEquals("org.example:popular", ranked.get(0).coordinate());
        assertEquals(3, ranked.get(0).distinctUserCount());
    }

    @Test
    @DisplayName("후보가 없는 분석은 아무것도 쓰지 않는다")
    void anAnalysisWithNoCandidatesWritesNothing() {
        givenJob("an_empty", 901L, "repo_empty");

        assertEquals(0, store.record("an_empty", 901L, "repo_empty", List.of(), SEEN));
    }
}
