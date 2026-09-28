package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.query.TechnologyProfileStore;
import com.example.git_job.analysis.query.TechnologySummaryFactStore;
import com.example.git_job.analysis.service.TechnologySummaryService.Status;
import com.example.git_job.analysis.store.TechnologySummaryStore;
import com.example.git_job.analysis.summary.FactPack;
import com.example.git_job.analysis.summary.FactPackBuilder;
import com.example.git_job.analysis.summary.HighlightSelector;
import com.example.git_job.analysis.summary.SummaryOutcome;
import com.example.git_job.analysis.summary.TechnologySummaryClient;
import com.example.git_job.analysis.summary.TechnologySummaryResponse;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
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
 * 캐시 히트·미스와 실패 경로를 고정한다.
 *
 * <p>모델은 부르지 않는다. 여기서 확인할 것은 문장의 품질이 아니라 "언제 부르고
 * 언제 안 부르는가"이고, 그것은 GPU 없이 결정된다.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class TechnologySummaryServiceTest {

    private static final long USER = 51L;
    private static final String REPO = "551";
    private static final String SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe";
    private static final String PROMPT = "tech-summary/2026-09-14.2";
    private static final Instant NOW = Instant.parse("2026-09-15T00:00:00Z");

    private PostgreSQLContainer postgres;
    private HikariDataSource dataSource;
    private JdbcTemplate jdbc;
    private TechnologySummaryStore store;
    private FactPackBuilder factPacks;
    private String registry;

    /** 부른 횟수를 세는 가짜 클라이언트. 캐시가 실제로 막는지 보려면 이게 필요하다. */
    private static final class FakeClient extends TechnologySummaryClient {

        private final AtomicInteger calls = new AtomicInteger();
        private String promptVersion = PROMPT;
        private String techIdToReturn;
        private boolean available = true;
        /** GPU 자리를 못 받은 상태. 실패와 구분되는지 보려고 따로 둔다. */
        private boolean busy;
        /** 계약을 어긴 응답을 흉내 낼 때 쓴다. {@code null} 이면 정상 응답이다. */
        private TechnologySummaryResponse malformed;

        FakeClient() {
            super("", Duration.ofSeconds(1));
        }

        @Override
        public Optional<String> promptVersion() {
            return Optional.ofNullable(promptVersion);
        }

        @Override
        public SummaryOutcome summarize(long userId, FactPack factPack) {
            calls.incrementAndGet();
            if (busy) {
                return SummaryOutcome.busy();
            }
            if (!available) {
                return SummaryOutcome.unavailable();
            }
            if (malformed != null) {
                return SummaryOutcome.generated(malformed);
            }
            String techId = techIdToReturn == null
                    ? factPack.technology().techId()
                    : techIdToReturn;
            return SummaryOutcome.generated(new TechnologySummaryResponse(
                    "OK",
                    new TechnologySummaryResponse.Summary(techId, "머리글", "요약 문장",
                            "다음 단계", List.of(0), "HIGH"),
                    "cache-key-from-service", "qwen3.5:4b", PROMPT, List.of(), null));
        }
    }

    /** 계약을 어긴 응답 하나. 어느 칸이 어긋났는지는 인자로 준다. */
    private static TechnologySummaryResponse response(String llmStatus, String headline,
            String confidence, String model) {
        return new TechnologySummaryResponse(
                llmStatus,
                new TechnologySummaryResponse.Summary("lombok", headline, "요약 문장",
                        null, List.of(), confidence),
                "cache-key-from-service", model, PROMPT, List.of(), null);
    }

    private FakeClient client;
    private TechnologySummaryService service;

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
        factPacks = new FactPackBuilder(new TechnologyProfileStore(jdbc),
                new TechnologySummaryFactStore(jdbc), new HighlightSelector());
        registry = jdbc.queryForObject(
                "SELECT registry_version FROM technology_registry WHERE status = 'CURRENT'",
                String.class);

        jdbc.update("""
                INSERT INTO "user" (user_id, github_id, github_login, name, role)
                VALUES (?, ?, 'user51', 'User 51', 'USER')
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
    void reset() {
        jdbc.update("DELETE FROM technology_summary");
        jdbc.update("DELETE FROM analysis_evidence_commit");
        jdbc.update("DELETE FROM analysis_evidence");
        jdbc.update("DELETE FROM analysis_outbox");
        jdbc.update("DELETE FROM analysis_job");
        client = new FakeClient();
        service = new TechnologySummaryService(factPacks, client, store);
    }

    /** lombok 근거 하나짜리 분석. Fact Pack 이 만들어질 최소 조건이다. */
    private void analysedLombok() {
        jdbc.update("""
                INSERT INTO analysis_job (analysis_id, user_id, repository_id,
                    repository_full_name, branch_name, commit_sha, status, current_stage,
                    requested_at, completed_at)
                VALUES ('an_1', ?, ?, 'octocat/app', 'main', ?, 'SUCCEEDED', 'COMPLETED', ?, ?)
                """, USER, REPO, SHA, Timestamp.from(NOW), Timestamp.from(NOW));
        String rule = jdbc.queryForObject("""
                SELECT rule_id FROM evidence_rule
                WHERE tech_id = 'lombok' AND rule_type = 'L1' AND registry_version = ?
                ORDER BY rule_id LIMIT 1
                """, String.class, registry);
        jdbc.update("""
                INSERT INTO analysis_evidence (analysis_id, user_id, rule_id, file_path,
                    start_line, end_line, fact_type, fact_payload, matched_at,
                    registry_version, commit_sha)
                VALUES ('an_1', ?, ?, 'a/A.java', 1, 1, 'IMPORT',
                    '{"MODULE":"lombok.Getter"}'::jsonb, ?, ?, ?)
                """, USER, rule, Timestamp.from(NOW), registry, SHA);
    }

    @Test
    @DisplayName("판정이 없는 기술은 모델을 부르지 않는다")
    void doesNotCallForAnUnknownTechnology() {
        // 근거가 없으면 요약할 것도 없다. GPU 를 쓸 이유가 없다.
        assertEquals(Status.NONE, service.summaryOf(USER, "lombok").status());
        assertEquals(0, client.calls.get());
    }

    @Test
    @DisplayName("처음에는 만들고 두 번째부터는 저장된 것을 쓴다")
    void generatesOnceThenServesFromCache() {
        analysedLombok();

        var first = service.summaryOf(USER, "lombok").summary();
        var second = service.summaryOf(USER, "lombok").summary();

        assertEquals("머리글", first.headline());
        assertEquals(first.headline(), second.headline());
        assertEquals(1, client.calls.get(), "캐시가 두 번째 호출을 막지 못했다");
    }

    @Test
    @DisplayName("근거가 바뀌면 다시 만든다")
    void regeneratesWhenTheEvidenceChanged() {
        analysedLombok();
        service.summaryOf(USER, "lombok");

        // 같은 기술에 근거가 하나 늘면 Fact Pack 이 달라지고 지문도 달라진다.
        String rule = jdbc.queryForObject("""
                SELECT rule_id FROM evidence_rule
                WHERE tech_id = 'lombok' AND rule_type = 'L1' AND registry_version = ?
                ORDER BY rule_id LIMIT 1
                """, String.class, registry);
        jdbc.update("""
                INSERT INTO analysis_evidence (analysis_id, user_id, rule_id, file_path,
                    start_line, end_line, fact_type, fact_payload, matched_at,
                    registry_version, commit_sha)
                VALUES ('an_1', ?, ?, 'a/B.java', 2, 2, 'IMPORT',
                    '{"MODULE":"lombok.Setter"}'::jsonb, ?, ?, ?)
                """, USER, rule, Timestamp.from(NOW), registry, SHA);

        service.summaryOf(USER, "lombok");

        assertEquals(2, client.calls.get(), "근거가 달라졌는데 옛 요약을 돌려줬다");
    }

    @Test
    @DisplayName("프롬프트가 바뀌면 다시 만든다")
    void regeneratesWhenThePromptChanged() {
        analysedLombok();
        service.summaryOf(USER, "lombok");

        client.promptVersion = "tech-summary/2026-09-15.1";
        service.summaryOf(USER, "lombok");

        assertEquals(2, client.calls.get(), "옛 프롬프트의 문장을 그대로 썼다");
    }

    @Test
    @DisplayName("서비스가 꺼져 있으면 저장된 것을 쓴다")
    void servesCachedWhenTheServiceIsDown() {
        // /health 를 못 물으면 버전을 따질 수 없다. 새로 만들 수도 없으니
        // 조금 낡았을지 모르는 요약이라도 보여주는 편이 빈 자리보다 낫다.
        analysedLombok();
        service.summaryOf(USER, "lombok");

        client.promptVersion = null;
        client.available = false;

        assertEquals("머리글", service.summaryOf(USER, "lombok").summary().headline());
        assertEquals(1, client.calls.get(), "꺼진 서비스를 다시 불렀다");
    }

    @Test
    @DisplayName("못 만들면 비어 있을 뿐 오류가 아니다")
    void missingSummaryIsNotAnError() {
        analysedLombok();
        client.available = false;

        assertEquals(Status.NONE, service.summaryOf(USER, "lombok").status());
    }

    @Test
    @DisplayName("다른 기술의 문장이 돌아오면 버린다")
    void rejectsAMismatchedTechnology() {
        // 저쪽도 검사하지만, 그대로 저장하면 한 기술의 문장이 다른 기술 카드에
        // 앉는다. 카드에서는 그럴듯해 보여 눈에 띄지 않는다.
        analysedLombok();
        client.techIdToReturn = "spring-security";

        assertEquals(Status.NONE, service.summaryOf(USER, "lombok").status());
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM technology_summary", Integer.class));
    }

    @Test
    @DisplayName("지문은 같은 입력에 같고 다른 입력에 다르다")
    void fingerprintTracksTheInput() {
        analysedLombok();
        FactPack pack = factPacks.build(USER, "lombok").orElseThrow();

        assertEquals(service.fingerprintOf(pack), service.fingerprintOf(pack));

        FactPack changed = new FactPack(pack.schemaVersion(), pack.locale(),
                new FactPack.Technology(pack.technology().techId(),
                        pack.technology().displayName(), "L2",
                        pack.technology().personalLevel(),
                        pack.technology().registryVersion()),
                pack.authorship(), pack.levels(), pack.nextLevel(), pack.highlights(),
                pack.repositories(), pack.period());

        assertNotEquals(service.fingerprintOf(pack), service.fingerprintOf(changed));
    }

    @Test
    @DisplayName("자리를 못 받으면 PENDING 이다. 요약 없음과 구분된다")
    void reportsPendingWhenNoSlotWasAvailable() {
        // GPU 자리가 둘뿐이라 카드가 몰리면 흔한 상태다. NONE 으로 내리면 화면은
        // 새로 고칠 때마다 같은 자리가 비는 것을 보면서 그것이 영구적인지 모른다.
        analysedLombok();
        client.busy = true;

        var result = service.summaryOf(USER, "lombok");

        assertEquals(Status.PENDING, result.status());
        assertTrue(result.retryAfterSeconds() > 0, "다시 물을 시점을 알려주지 않았다");
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM technology_summary", Integer.class),
                "만들지 못한 것을 저장했다");
    }

    @Test
    @DisplayName("저장할 수 없는 응답은 버린다. 예외로 올리지 않는다")
    void discardsAResponseTheTableWouldReject() {
        // 이 표의 여러 칸이 NOT NULL 이고 두 칸은 CHECK 까지 걸려 있다. 그대로
        // INSERT 하면 DataIntegrityViolationException 이 밖으로 올라가 카드
        // 전체가 500 이 된다 -- "실패는 요약 없음이지 오류가 아니다"가 깨진다.
        analysedLombok();

        List<TechnologySummaryResponse> rejected = List.of(
                response(null, "머리글", "HIGH", "qwen3.5:4b"),
                response("MAYBE", "머리글", "HIGH", "qwen3.5:4b"),
                response("OK", "머리글", "VERY_HIGH", "qwen3.5:4b"),
                response("OK", "머리글", null, "qwen3.5:4b"),
                response("OK", " ", "HIGH", "qwen3.5:4b"),
                response("OK", "머리글", "HIGH", "m".repeat(81)));

        for (TechnologySummaryResponse body : rejected) {
            jdbc.update("DELETE FROM technology_summary");
            client.malformed = body;

            assertEquals(Status.NONE, service.summaryOf(USER, "lombok").status(),
                    "쓸 수 없는 응답인데 문장이 있다고 했다");
            assertEquals(0, jdbc.queryForObject(
                    "SELECT count(*) FROM technology_summary", Integer.class),
                    "제약을 어기는 응답을 저장했다");
        }
    }

    @Test
    @DisplayName("계약 밖 cache_key 는 비워서 저장한다. 문장은 버리지 않는다")
    void keepsTheSentenceWhenOnlyTheTrackingKeyIsOdd() {
        // cache_key 는 CHAR(64) 이고 조회에 쓰지 않는다. 길이가 다르다고 문장까지
        // 버리면 추적용 값 하나 때문에 카드가 빈다.
        analysedLombok();

        assertEquals(Status.READY, service.summaryOf(USER, "lombok").status());
        assertEquals(1, jdbc.queryForObject(
                "SELECT count(*) FROM technology_summary WHERE cache_key IS NULL",
                Integer.class));
    }
}
