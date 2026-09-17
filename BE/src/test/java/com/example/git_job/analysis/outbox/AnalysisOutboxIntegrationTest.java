package com.example.git_job.analysis.outbox;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.example.git_job.analysis.event.RepositoryAnalysisMode;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestPayload;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestedEvent;
import com.example.git_job.analysis.messaging.RepositoryAnalysisEventProducer;
import com.example.git_job.analysis.messaging.RepositoryAnalysisKafkaProperties;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.analysis.service.AnalysisRequestService;
import com.example.git_job.analysis.support.AnalysisJpaSupport;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.*;
import org.mockito.ArgumentCaptor;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.json.JsonMapper;

/** Default: isolated H2; OUTBOX_TEST_DATABASE=postgres: the same tests on disposable PostgreSQL. */
class AnalysisOutboxIntegrationTest {
    private static final String TOPIC = "gitjob.repository-analysis.requests.v1";
    private static PostgreSQLContainer postgres;
    private static boolean realPostgres;
    private static HikariDataSource dataSource;
    private AnnotationConfigApplicationContext context;
    private JdbcTemplate jdbc;
    private AnalysisRequestService service;
    private FailingOnceStore store;
    private RepositoryAnalysisEventProducer producer;
    private AnalysisOutboxPublisher publisher;
    private JpaTransactionManager transactions;
    private LocalContainerEntityManagerFactoryBean entityManagers;
    private final JsonMapper mapper = JsonMapper.builder().build();
    private final AnalysisOutboxProperties properties = new AnalysisOutboxProperties(
            AnalysisOutboxProperties.Mode.POLLING, true, 20, 3,
            Duration.ofMillis(50), Duration.ofSeconds(5), Duration.ofMinutes(5));

    @Configuration(proxyBeanMethods = false)
    @EnableTransactionManagement
    static class TransactionConfiguration {
    }

    @BeforeAll
    static void database() throws Exception {
        realPostgres = "postgres".equals(System.getenv("OUTBOX_TEST_DATABASE"));
        HikariConfig config = new HikariConfig();
        config.setMaximumPoolSize(4);
        if (realPostgres) {
            postgres = new PostgreSQLContainer("postgres:16-alpine");
            postgres.start();
            config.setJdbcUrl(postgres.getJdbcUrl());
            config.setUsername(postgres.getUsername());
            config.setPassword(postgres.getPassword());
        } else {
            config.setJdbcUrl(
                    "jdbc:h2:mem:outbox_" + UUID.randomUUID()
                            + ";MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1");
            config.setUsername("sa");
            config.setPassword("");
        }
        dataSource = new HikariDataSource(config);
        // The full baseline does not run on H2, so this builds the smallest schema the
        // outbox needs: analysis_job, then the outbox table and the index it is read by.
        String baseline = new ClassPathResource("db/migration/V1__baseline_schema.sql")
                .getContentAsString(StandardCharsets.UTF_8);
        int start = baseline.indexOf("CREATE TABLE \"analysis_job\"");
        String jobSql = baseline.substring(start, baseline.indexOf(");", start) + 2)
                + " ALTER TABLE analysis_job ADD PRIMARY KEY (analysis_id);"
                // baseline 이후 analysis_job 에 붙은 컬럼은 여기에 따라 붙여야 한다.
                // 이 테스트는 V1 만 잘라 쓰고 나머지 마이그레이션을 돌리지 않는다.
                + " ALTER TABLE analysis_job ADD COLUMN repository_full_name VARCHAR(255);"
                + " ALTER TABLE analysis_job ADD COLUMN compute_ready_at TIMESTAMPTZ;";
        // Stops at the outbox index: the baseline goes on to create a partial index on
        // analysis_job, and H2 rejects the WHERE clause on CREATE INDEX.
        int outboxStart = baseline.indexOf("CREATE TABLE analysis_outbox");
        int outboxIndex = baseline.indexOf("CREATE INDEX idx_analysis_outbox_pending", outboxStart);
        String outboxSql = baseline.substring(outboxStart, baseline.indexOf(';', outboxIndex) + 1);
        String sql = jobSql + outboxSql;
        if (!realPostgres) {
            sql = sql.replace("TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE");
        }
        new ResourceDatabasePopulator(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)))
                .execute(dataSource);
    }

    @AfterAll
    static void stopDatabase() {
        if (dataSource != null) {
            dataSource.close();
        }
        if (postgres != null) {
            postgres.stop();
        }
    }

    @BeforeEach
    void setup() {
        jdbc = new JdbcTemplate(dataSource);
        jdbc.update("DELETE FROM analysis_outbox");
        jdbc.update("DELETE FROM analysis_job");
        store = new FailingOnceStore(jdbc);
        // H2 only approximates the deployment schema, so the mapping is validated on PostgreSQL.
        entityManagers = AnalysisJpaSupport.entityManagerFactory(
                dataSource, realPostgres ? "validate" : "none");
        var entityManagerFactory = entityManagers.getObject();
        // JpaTransactionManager exposes its connection to JdbcTemplate, so the JPA job insert
        // and the JDBC outbox insert share one transaction.
        transactions = new JpaTransactionManager(entityManagerFactory);
        transactions.afterPropertiesSet();
        var analysisJobs = AnalysisJpaSupport.repository(entityManagerFactory);
        context = new AnnotationConfigApplicationContext();
        context.register(TransactionConfiguration.class);
        context.registerBean(JdbcTemplate.class, () -> jdbc);
        context.registerBean(AnalysisOutboxStore.class, () -> store);
        context.registerBean(AnalysisJobRepository.class, () -> analysisJobs);
        context.registerBean(JpaTransactionManager.class, () -> transactions);
        context.registerBean(RepositoryAnalysisKafkaProperties.class,
                () -> new RepositoryAnalysisKafkaProperties(
                        TOPIC, "gitjob.repository-analysis.results.v1", "",
                        "gitjob.repository-analysis.results.dlq.v1"));
        context.registerBean(JsonMapper.class, () -> mapper);
        context.registerBean(AnalysisRequestService.class);
        context.refresh();
        service = context.getBean(AnalysisRequestService.class);
        producer = mock(RepositoryAnalysisEventProducer.class);
        when(producer.publish(any(), anyString())).thenReturn(CompletableFuture.completedFuture(null));
        publisher = new AnalysisOutboxPublisher(store, producer, mapper, properties, transactions);
    }

    @AfterEach
    void closeContext() {
        context.close();
        if (entityManagers != null) {
            entityManagers.destroy();
        }
    }

    @Test
    void enqueueCommitsJobAndCompleteEventWithoutCallingKafka() {
        var event = enqueue("an_1", "ar_1");
        assertEquals("QUEUED", jdbc.queryForObject("SELECT status FROM analysis_job", String.class));
        assertEquals("PENDING", status());
        String json = jdbc.queryForObject("SELECT event_json FROM analysis_outbox", String.class);
        assertEquals(event, mapper.readValue(json, RepositoryAnalysisRequestedEvent.class));
        assertTrue(json.contains("\"branch_name\":\"feature/outbox\""));
        verifyNoInteractions(producer);
    }

    @Test
    void outboxInsertFailureRollsBackNewJob() {
        enqueue("an_1", "ar_1");
        // The failure is injected rather than provoked with a schema constraint: what matters is
        // that any outbox failure takes the job with it, not which constraint happened to fire.
        store.failNextInsert();
        assertThrows(DataAccessException.class, () -> enqueue("an_2", "ar_2"));
        assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM analysis_job", Integer.class));
        assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM analysis_outbox", Integer.class));
    }

    @Test
    @DisplayName("같은 analysis_repository_id를 새 event_id로 다시 넣을 수 있다 (재발행 절차)")
    void allowsRepublishingTheSameRepositoryUnderANewEventId() {
        var first = enqueue("an_1", "ar_1");
        String json = jdbc.queryForObject(
                "SELECT event_json FROM analysis_outbox WHERE event_id = ?", String.class, first.eventId());

        // The recovery procedure in the runbook: re-insert the same payload under a new event_id.
        jdbc.update("INSERT INTO analysis_outbox (event_id, analysis_id, analysis_repository_id,"
                        + " topic, event_json, status, attempts, created_at, next_attempt_at)"
                        + " VALUES (?, 'an_1', 'ar_1', ?, ?, 'PENDING', 0,"
                        + " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                "ev_republished", TOPIC, json);

        assertEquals(2, jdbc.queryForObject(
                "SELECT COUNT(*) FROM analysis_outbox WHERE analysis_repository_id = 'ar_1'",
                Integer.class));
    }

    @Test
    void credentialLookupRequiresTheAnalysisAndRepositoryScopedIdPair() {
        enqueue("an_1", "ar_1");

        assertTrue(store.containsAnalysisRepository("an_1", "ar_1"));
        assertFalse(store.containsAnalysisRepository("an_other", "ar_1"));
        assertFalse(store.containsAnalysisRepository("an_1", "ar_other"));

        store.published(jdbc.queryForObject(
                "SELECT event_id FROM analysis_outbox", String.class));
        assertTrue(store.containsAnalysisRepository("an_1", "ar_1"));
    }

    @Test
    void enclosingTransactionRollbackRemovesBothRows() {
        new TransactionTemplate(transactions).executeWithoutResult(tx -> {
            enqueue("an_1", "ar_1");
            tx.setRollbackOnly();
        });
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM analysis_job", Integer.class));
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM analysis_outbox", Integer.class));
    }

    @Test
    void ackMarksPublishedAndSubsequentPollDoesNotResend() {
        var event = enqueue("an_1", "ar_1");
        assertTrue(publisher.publishNext());
        assertEquals("PUBLISHED", status());
        assertNotNull(jdbc.queryForObject("SELECT published_at FROM analysis_outbox", java.sql.Timestamp.class));
        assertFalse(publisher.publishNext());
        verify(producer, times(1)).publish(event, TOPIC);
    }

    @Test
    void asynchronousFailureSchedulesRetryWithSameEventAndDestination() {
        var event = enqueue("an_1", "ar_1");
        when(producer.publish(any(), anyString())).thenReturn(
                CompletableFuture.failedFuture(new IllegalStateException("broker unavailable")),
                CompletableFuture.completedFuture(null));
        publisher.publishNext();
        assertEquals("PENDING", status());
        assertEquals(1, attempts());
        assertEquals("KAFKA_SEND_FAILED", errorCode());
        assertFalse(publisher.publishNext()); // backoff prevents an immediate retry
        makeDue();
        publisher.publishNext();
        assertEquals("PUBLISHED", status());
        verify(producer, times(2)).publish(event, TOPIC);
    }

    @Test
    void repeatedSynchronousFailuresAreRetainedAsFailed() {
        enqueue("an_1", "ar_1");
        when(producer.publish(any(), anyString())).thenThrow(new IllegalStateException("send failed"));
        for (int i = 0; i < 3; i++) {
            makeDue();
            publisher.publishNext();
        }
        assertEquals("FAILED", status());
        assertEquals(3, attempts());
        makeDue();
        assertFalse(publisher.publishNext());
    }

    @Test
    void timeoutDoesNotMarkPublished() {
        enqueue("an_1", "ar_1");
        when(producer.publish(any(), anyString())).thenReturn(new CompletableFuture<>());
        publisher.publishNext();
        assertEquals("PENDING", status());
        assertEquals("KAFKA_ACK_TIMEOUT", errorCode());
    }

    @Test
    void corruptPersistedEventIsRetainedForInspectionWithoutSending() {
        enqueue("an_1", "ar_1");
        jdbc.update("UPDATE analysis_outbox SET event_json = ?", "{broken-json");
        publisher.publishNext();
        assertEquals("FAILED", status());
        assertEquals("INVALID_EVENT", errorCode());
        verifyNoInteractions(producer);
    }

    @Test
    void dbFailureAfterAckRollsBackAndAllowsIdenticalRedelivery() {
        enqueue("an_1", "ar_1");
        var brokenStore = spy(store);
        doThrow(new DataAccessResourceFailureException("database lost"))
                .when(brokenStore).published(anyString());
        var brokenPublisher = new AnalysisOutboxPublisher(
                brokenStore, producer, mapper, properties, transactions);
        assertThrows(DataAccessException.class, brokenPublisher::publishNext);
        assertEquals("PENDING", status());
        publisher.publishNext();
        var events = ArgumentCaptor.forClass(RepositoryAnalysisRequestedEvent.class);
        verify(producer, times(2)).publish(events.capture(), eq(TOPIC));
        assertEquals(events.getAllValues().get(0), events.getAllValues().get(1));
    }

    @Test
    void concurrentRelaySkipsLockedRowAndCrashRollbackReleasesIt() throws Exception {
        enqueue("an_1", "ar_1");
        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        try (var executor = Executors.newSingleThreadExecutor()) {
            var holder = executor.submit(() -> new TransactionTemplate(transactions).execute(tx -> {
                assertTrue(store.lockNext().isPresent());
                locked.countDown();
                try {
                    assertTrue(release.await(5, TimeUnit.SECONDS));
                } catch (InterruptedException error) {
                    throw new IllegalStateException(error);
                }
                tx.setRollbackOnly();
                return null;
            }));
            try {
                assertTrue(locked.await(5, TimeUnit.SECONDS));
                assertFalse(publisher.publishNext());
                verifyNoInteractions(producer);
            } finally {
                release.countDown();
            }
            holder.get(5, TimeUnit.SECONDS);
        }
        assertTrue(publisher.publishNext());
        assertEquals("PUBLISHED", status());
    }

    @Test
    void retryDelayDoublesAndStopsAtConfiguredCap() {
        assertEquals(Duration.ofSeconds(5), properties.delayAfter(1));
        assertEquals(Duration.ofSeconds(10), properties.delayAfter(2));
        assertEquals(Duration.ofMinutes(5), properties.delayAfter(1000));
    }

    /** Lets a test fail the outbox insert without depending on a particular schema constraint. */
    private static final class FailingOnceStore extends AnalysisOutboxStore {
        private boolean armed;

        FailingOnceStore(JdbcTemplate jdbc) {
            super(jdbc);
        }

        void failNextInsert() {
            armed = true;
        }

        @Override
        public void insert(RepositoryAnalysisRequestedEvent event, String topic, String json) {
            if (armed) {
                armed = false;
                throw new DataAccessResourceFailureException("simulated outbox insert failure");
            }
            super.insert(event, topic, json);
        }
    }

    private RepositoryAnalysisRequestedEvent enqueue(String analysisId, String repositoryAnalysisId) {
        return service.enqueueAuthorized(1L, new RepositoryAnalysisRequestPayload(
                analysisId, repositoryAnalysisId, 123456789L, "octocat/gitjob", "feature/outbox",
                "0123456789abcdef0123456789abcdef01234567", RepositoryAnalysisMode.SNAPSHOT,
                "technology-registry/v1"), "tr_1");
    }

    private String status() {
        return jdbc.queryForObject("SELECT status FROM analysis_outbox", String.class);
    }

    private int attempts() {
        return jdbc.queryForObject("SELECT attempts FROM analysis_outbox", Integer.class);
    }

    private String errorCode() {
        return jdbc.queryForObject("SELECT last_error_code FROM analysis_outbox", String.class);
    }

    private void makeDue() {
        jdbc.update("UPDATE analysis_outbox SET next_attempt_at = ?",
                java.sql.Timestamp.from(java.time.Instant.parse("2020-01-01T00:00:00Z")));
    }
}
