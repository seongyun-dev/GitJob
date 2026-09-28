package com.example.git_job.analysis.store;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

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
 * The draft-and-publish flow, against a real PostgreSQL.
 *
 * <p>What matters here is that a published version never changes. An analysis
 * event carries the version it was judged with, so editing a published one
 * rewrites the basis of evidence that already exists.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class RegistryDraftStoreTest {

    private static final Instant NOW = Instant.parse("2026-09-11T00:00:00Z");

    private PostgreSQLContainer postgres;
    private HikariDataSource dataSource;
    private JdbcTemplate jdbc;
    private RegistryDraftStore store;

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
        store = new RegistryDraftStore(jdbc);
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

    /**
     * A fresh id per call. These tests share one container and one schema, and
     * a draft published by one of them becomes the CURRENT the next one copies
     * -- so a fixed id would collide depending on execution order.
     */
    private String uniqueTechId(String prefix) {
        return prefix + "-" + Long.toString(System.nanoTime(), 36).toLowerCase();
    }

    private int count(String table, String version) {
        return jdbc.queryForObject(
                "SELECT count(*) FROM " + table + " WHERE registry_version = ?",
                Integer.class, version);
    }

    @Test
    @DisplayName("초안은 CURRENT 를 복사해서 열린다")
    void aDraftStartsAsACopyOfCurrent() {
        // 새 기술만 담은 빈 초안을 발행하면 지금 아는 기술이 전부 사라진다.
        // 그러면 모든 저장소가 "거의 아무것도 안 쓴다"로 나오는데, 그건 정상
        // 결과처럼 보여서 눈에 띄지 않는다.
        String current = store.currentVersion().orElseThrow();

        String draft = store.openDraft(NOW);

        assertNotEquals(current, draft);
        assertEquals(count("technology", current), count("technology", draft));
        assertEquals(count("technology_mapping", current), count("technology_mapping", draft));
        assertEquals(count("evidence_rule", current), count("evidence_rule", draft));
        assertEquals(count("evidence_rule_clause", current), count("evidence_rule_clause", draft));
        assertEquals(count("evidence_rule_predicate_value", current),
                count("evidence_rule_predicate_value", draft));
    }

    @Test
    @DisplayName("초안을 두 번 열어도 하나다")
    void openingTwiceReturnsTheSameDraft() {
        // 승격 스무 건이 버전 스무 개가 되면 안 된다.
        String first = store.openDraft(NOW);

        assertEquals(first, store.openDraft(NOW));
    }

    @Test
    @DisplayName("승격한 기술은 초안에만 들어가고 CURRENT 는 그대로다")
    void aPromotionTouchesOnlyTheDraft() {
        String current = store.currentVersion().orElseThrow();
        int before = count("technology", current);
        String draft = store.openDraft(NOW);

        String techId = uniqueTechId("h2database");
        store.addTechnology(draft, techId, "H2 Database", List.of("BACKEND"),
                "PACKAGE", "MAVEN", "com.h2database:h2:" + techId, "EXACT");

        assertEquals(before, count("technology", current));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM technology
                WHERE tech_id = ? AND registry_version = ?
                """, Integer.class, techId, draft));
        // The mapping and an L0 rule come with it, or the technology is in the
        // registry but nothing can ever match it.
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM technology_mapping
                WHERE tech_id = ? AND registry_version = ?
                """, Integer.class, techId, draft));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM evidence_rule
                WHERE tech_id = ? AND registry_version = ? AND rule_type = 'L0'
                """, Integer.class, techId, draft));
    }

    @Test
    @DisplayName("승격으로 만든 규칙은 술어와 기대값까지 온전하다")
    void aPromotedRuleIsComplete() {
        // 절이나 기대값이 빠진 규칙은 조용히 아무것도 매칭하지 않는다.
        String draft = store.openDraft(NOW);
        String techId = uniqueTechId("caffeine");
        store.addTechnology(draft, techId, "Caffeine", List.of("BACKEND"),
                "PACKAGE", "MAVEN", "com.github.ben-manes.caffeine:" + techId, "EXACT");

        String expected = jdbc.queryForObject("""
                SELECT v.expected_value
                FROM evidence_rule r
                JOIN evidence_rule_clause c
                  ON c.rule_id = r.rule_id AND c.registry_version = r.registry_version
                JOIN evidence_rule_predicate p ON p.clause_id = c.clause_id
                JOIN evidence_rule_predicate_value v ON v.predicate_id = p.predicate_id
                WHERE r.rule_id = ? AND r.registry_version = ?
                """, String.class, techId + ".l0.dependency", draft);

        assertEquals(techId, expected);
    }

    @Test
    @DisplayName("발행하면 이전 버전은 RETIRED 가 되고 행은 남는다")
    void publishingRetiresThePreviousVersionWithoutDeletingIt() {
        String previous = store.currentVersion().orElseThrow();
        int previousTechs = count("technology", previous);
        String draft = store.openDraft(NOW);

        store.publish(draft, NOW);

        assertEquals(draft, store.currentVersion().orElseThrow());
        assertEquals("RETIRED", jdbc.queryForObject(
                "SELECT status FROM technology_registry WHERE registry_version = ?",
                String.class, previous));
        // 과거 분석이 그 버전으로 판정됐으므로 되짚을 수 있어야 한다.
        assertEquals(previousTechs, count("technology", previous));
        assertTrue(store.draftVersion().isEmpty());
    }

    @Test
    @DisplayName("발행할 초안이 없으면 거절한다")
    void publishingNothingIsRefused() {
        assertThrows(IllegalStateException.class, () -> store.publish("registry-nope.1", NOW));
    }

    @Test
    @DisplayName("CURRENT 는 언제나 하나다")
    void exactlyOneVersionIsCurrent() {
        // 둘이면 요청마다 다른 규칙으로 판정되고, 그 차이는 결과를 비교하기
        // 전까지 드러나지 않는다. 부분 유니크 인덱스가 막는다.
        store.publish(store.openDraft(NOW), NOW);

        assertEquals(1, jdbc.queryForObject(
                "SELECT count(*) FROM technology_registry WHERE status = 'CURRENT'",
                Integer.class));
    }
}
