package com.example.git_job.analysis.store;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.store.TechnologySummaryStore.Cached;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
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
 * 요약 캐시를 실제 PostgreSQL 로 고정한다.
 *
 * <p>여기서 틀리면 GPU 를 계속 태우거나(안 맞음), 지금 프롬프트로는 나올 수 없는
 * 문장을 계속 보여준다(너무 잘 맞음). 둘 다 화면에서는 보이지 않는다.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class TechnologySummaryStoreTest {

    private static final long USER = 41L;
    private static final String TECH = "spring-security";
    private static final String HASH =
            "1111111111111111111111111111111111111111111111111111111111111111";
    private static final String OTHER_HASH =
            "2222222222222222222222222222222222222222222222222222222222222222";
    private static final String PROMPT = "tech-summary/2026-09-14.2";
    private static final Instant NOW = Instant.parse("2026-09-15T00:00:00Z");

    private PostgreSQLContainer postgres;
    private HikariDataSource dataSource;
    private JdbcTemplate jdbc;
    private TechnologySummaryStore store;

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
        store = new TechnologySummaryStore(jdbc);
        jdbc.update("""
                INSERT INTO "user" (user_id, github_id, github_login, name, role)
                VALUES (?, ?, 'user41', 'User 41', 'USER')
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
        jdbc.update("DELETE FROM technology_summary");
    }

    private void save(String hash, String promptVersion, String headline) {
        store.save(USER, TECH, hash, "cache-key", promptVersion, "qwen3.5:4b", "OK",
                headline, "요약 문장", "다음 단계", "HIGH", List.of(0, 1), NOW);
    }

    @Test
    @DisplayName("같은 입력과 같은 프롬프트면 저장된 것을 돌려준다")
    void hitsOnSameInputAndPrompt() {
        save(HASH, PROMPT, "인증 필터 체인을 구성했다");

        Cached cached = store.find(USER, TECH, HASH, PROMPT).orElseThrow();

        assertEquals("인증 필터 체인을 구성했다", cached.headline());
        assertEquals("OK", cached.llmStatus());
        assertEquals("HIGH", cached.confidence());
    }

    @Test
    @DisplayName("입력이 달라지면 미스다")
    void missesWhenTheFactPackChanged() {
        // 레벨이나 근거가 바뀌면 해시가 달라진다. 옛 문장은 이제 틀린 말이다.
        save(HASH, PROMPT, "옛 문장");

        assertTrue(store.find(USER, TECH, OTHER_HASH, PROMPT).isEmpty());
    }

    @Test
    @DisplayName("프롬프트가 바뀌면 미스다")
    void missesWhenThePromptChanged() {
        // 지금 프롬프트로는 나올 수 없는 문장이 화면에 남으면 안 된다.
        save(HASH, "tech-summary/2026-09-14.2", "옛 프롬프트의 문장");

        assertTrue(store.find(USER, TECH, HASH, "tech-summary/2026-09-15.1").isEmpty());
    }

    @Test
    @DisplayName("프롬프트 버전을 모르면 버전을 따지지 않는다")
    void ignoresPromptVersionWhenUnknown() {
        // 서비스가 꺼져 있어 /health 를 못 물었다는 뜻이다. 새로 만들 수도 없으니
        // 조금 낡았을지 모르는 요약이라도 보여주는 편이 빈 자리보다 낫다.
        save(HASH, PROMPT, "저장된 문장");

        Cached cached = store.find(USER, TECH, HASH, null).orElseThrow();

        assertEquals("저장된 문장", cached.headline());
    }

    @Test
    @DisplayName("사용자·기술마다 한 행이고 덮어쓴다")
    void keepsOneRowPerUserAndTechnology() {
        // 해시를 키에 넣어 이력을 쌓으면 레벨이 오를 때마다 행이 늘고 아무도
        // 지우지 않는다.
        save(HASH, PROMPT, "처음");
        save(OTHER_HASH, PROMPT, "나중");

        Integer rows = jdbc.queryForObject("""
                SELECT count(*) FROM technology_summary WHERE user_id = ? AND tech_id = ?
                """, Integer.class, USER, TECH);

        assertEquals(1, rows);
        assertEquals("나중", store.find(USER, TECH, OTHER_HASH, PROMPT).orElseThrow().headline());
        assertTrue(store.find(USER, TECH, HASH, PROMPT).isEmpty(), "옛 해시로는 안 맞아야 한다");
    }

    @Test
    @DisplayName("gap 은 비어 있을 수 있다")
    void gapMayBeNull() {
        // 최고 Level 에 도달하면 다음 단계가 없다.
        store.save(USER, TECH, HASH, null, PROMPT, "qwen3.5:4b", "FALLBACK",
                "머리글", "요약", null, "LOW", List.of(), NOW);

        Cached cached = store.find(USER, TECH, HASH, PROMPT).orElseThrow();

        assertNull(cached.gap());
        assertEquals("FALLBACK", cached.llmStatus());
    }

    @Test
    @DisplayName("남의 요약은 보이지 않는다")
    void doesNotLeakAcrossUsers() {
        save(HASH, PROMPT, "내 문장");

        assertTrue(store.find(USER + 1, TECH, HASH, PROMPT).isEmpty());
    }
}
