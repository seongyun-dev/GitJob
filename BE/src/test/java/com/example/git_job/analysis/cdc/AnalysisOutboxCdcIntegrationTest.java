package com.example.git_job.analysis.cdc;

import static org.junit.jupiter.api.Assertions.*;

import com.example.git_job.analysis.event.RepositoryAnalysisMode;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestPayload;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestedEvent;
import com.example.git_job.analysis.messaging.RepositoryAnalysisKafkaProperties;
import com.example.git_job.analysis.outbox.AnalysisOutboxStore;
import com.example.git_job.analysis.repository.AnalysisJobRepository;
import com.example.git_job.analysis.service.AnalysisRequestService;
import com.example.git_job.analysis.support.AnalysisJpaSupport;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ByteArrayResource;
import org.flywaydb.core.Flyway;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.Network;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.kafka.KafkaContainer;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.json.JsonMapper;

/**
 * End-to-end contract tests. They run whenever Docker is available and are skipped when it
 * is not, so nobody has to remember a flag for the CDC pipeline to stay verified.
 * All infrastructure is disposable, with random host ports and a dedicated Docker network.
 * The production connector JSON is loaded unchanged except for the isolated database address/secret.
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class AnalysisOutboxCdcIntegrationTest {
    private static final String TOPIC = "gitjob.repository-analysis.requests.v1";
    private static final String CONNECTOR = "analysis-outbox-test";
    private static final long OWNER_ID = 1L;
    private static final String CDC_PASSWORD = "isolated-cdc-test-password";
    private static final Duration EVENT_TIMEOUT = Duration.ofSeconds(90);
    private final JsonMapper mapper = JsonMapper.builder().build();
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final Map<String, ConsumerRecord<String, String>> received = new LinkedHashMap<>();
    private final java.util.concurrent.atomic.AtomicLong nextRepositoryId =
            new java.util.concurrent.atomic.AtomicLong(123456789L);
    private Network network;
    private PostgreSQLContainer postgres;
    private KafkaContainer kafka;
    private GenericContainer<?> connect;
    private HikariDataSource dataSource;
    private AnnotationConfigApplicationContext context;
    private JdbcTemplate jdbc;
    private JpaTransactionManager transactions;
    private LocalContainerEntityManagerFactoryBean entityManagers;
    private AnalysisRequestService service;
    private KafkaConsumer<String, String> consumer;
    private RepositoryAnalysisRequestedEvent pendingBeforeCdc;
    private RepositoryAnalysisRequestedEvent publishedBeforeCdc;
    private RepositoryAnalysisRequestedEvent failedBeforeCdc;

    @Configuration(proxyBeanMethods = false)
    @EnableTransactionManagement
    static class TransactionConfiguration {
    }

    @BeforeAll
    void startIsolatedPipeline() throws Exception {
        network = Network.newNetwork();
        postgres = new PostgreSQLContainer("postgres:16.4-alpine")
                .withNetwork(network).withNetworkAliases("postgres")
                .withCommand("postgres", "-c", "wal_level=logical", "-c", "max_replication_slots=4",
                        "-c", "max_wal_senders=4");
        kafka = new KafkaContainer("apache/kafka:4.0.0")
                .withNetwork(network).withListener("kafka:19092")
                .withEnv("KAFKA_AUTO_CREATE_TOPICS_ENABLE", "false");
        postgres.start();
        kafka.start();
        prepareDatabaseAndService();
        prepareTopics();

        pendingBeforeCdc = enqueue("snapshot_pending");
        publishedBeforeCdc = enqueue("snapshot_published");
        failedBeforeCdc = enqueue("snapshot_failed");
        jdbc.update("UPDATE analysis_outbox SET status = 'PUBLISHED' WHERE event_id = ?",
                publishedBeforeCdc.eventId());
        jdbc.update("UPDATE analysis_outbox SET status = 'FAILED' WHERE event_id = ?",
                failedBeforeCdc.eventId());

        consumer = new KafkaConsumer<>(Map.of(
                ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, kafka.getBootstrapServers(),
                ConsumerConfig.GROUP_ID_CONFIG, "outbox-cdc-" + UUID.randomUUID(),
                ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
                ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
                ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest",
                ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false"));
        consumer.subscribe(List.of(TOPIC));
        connect = newConnectWorker();
        connect.start();
        String template = Files.readString(Path.of("../Infra/cdc/connector.json"));
        String config = template.replace("__DATABASE_HOST__", "postgres")
                .replace("__DATABASE_PORT__", "5432")
                .replace("__DATABASE_NAME__", postgres.getDatabaseName());
        var response = request("PUT", "/connectors/" + CONNECTOR + "/config", config);
        assertTrue(response.statusCode() == 201 || response.statusCode() == 200, response.body());
        awaitConnectorRunning();
    }

    @Test
    @Order(1)
    void pendingOnlySnapshotAndCommittedInsertKeepTheExistingKafkaContract() throws Exception {
        // One partition provides a fence: the streaming record comes after the complete snapshot.
        var committed = enqueue("committed");
        assertContract(committed, awaitEvent(committed.eventId()));
        assertContract(pendingBeforeCdc, received.get(pendingBeforeCdc.eventId()));
        assertFalse(received.containsKey(publishedBeforeCdc.eventId()), "Old PUBLISHED row was replayed");
        assertFalse(received.containsKey(failedBeforeCdc.eventId()), "Old FAILED row was replayed");
        assertEquals("PENDING", jdbc.queryForObject(
                "SELECT status FROM analysis_outbox WHERE event_id = ?", String.class, committed.eventId()));
        assertEquals(0, jdbc.queryForObject(
                "SELECT attempts FROM analysis_outbox WHERE event_id = ?", Integer.class, committed.eventId()));
        assertNull(jdbc.queryForObject(
                "SELECT published_at FROM analysis_outbox WHERE event_id = ?", Object.class, committed.eventId()));
    }

    @Test
    @Order(2)
    void rolledBackServiceTransactionNeverReachesKafka() throws Exception {
        var rolledBack = new TransactionTemplate(transactions).execute(tx -> {
            var event = enqueue("rolled_back");
            tx.setRollbackOnly();
            return event;
        });
        assertNotNull(rolledBack);
        var fence = enqueue("after_rollback");
        assertContract(fence, awaitEvent(fence.eventId()));
        assertFalse(received.containsKey(rolledBack.eventId()));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM analysis_job WHERE analysis_id = ?",
                Integer.class, rolledBack.payload().analysisId()));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM analysis_outbox WHERE event_id = ?", Integer.class, rolledBack.eventId()));
    }

    @Test
    @Order(3)
    void replacementConnectWorkerRestoresConfigurationAndResumesFromKafkaOffsets() throws Exception {
        // A graceful shutdown flushes source offsets to Kafka, not to this container's filesystem.
        connect.stop();
        var queuedDuringOutage = enqueue("while_connect_down");
        assertEquals("QUEUED", jdbc.queryForObject(
                "SELECT status FROM analysis_job WHERE analysis_id = ?",
                String.class, queuedDuringOutage.payload().analysisId()));

        connect = newConnectWorker();
        connect.start();
        // Do not register the connector again: distributed Connect must restore its saved config.
        awaitConnectorRunning();
        assertContract(queuedDuringOutage, awaitEvent(queuedDuringOutage.eventId()));
        awaitCommittedOffsets();
        awaitActiveReplicationSlot();
    }

    /** Offsets are committed on the worker's flush interval, so they lag a delivered record. */
    private void awaitCommittedOffsets() throws Exception {
        long deadline = System.nanoTime() + EVENT_TIMEOUT.toNanos();
        String lastBody = "no response";
        while (System.nanoTime() < deadline) {
            var offsets = request("GET", "/connectors/" + CONNECTOR + "/offsets", null);
            lastBody = offsets.body();
            if (offsets.statusCode() == 200 && !mapper.readTree(lastBody).path("offsets").isEmpty()) {
                return;
            }
            Thread.sleep(250);
        }
        fail("Connector never reported committed source offsets: " + lastBody);
    }

    private void awaitActiveReplicationSlot() throws Exception {
        long deadline = System.nanoTime() + EVENT_TIMEOUT.toNanos();
        while (System.nanoTime() < deadline) {
            if (Integer.valueOf(1).equals(jdbc.queryForObject(
                    "SELECT count(*) FROM pg_replication_slots "
                            + "WHERE slot_name = 'gitjob_analysis_outbox' AND active",
                    Integer.class))) {
                return;
            }
            Thread.sleep(250);
        }
        fail("Replication slot gitjob_analysis_outbox is not held by the replacement worker");
    }

    private void prepareDatabaseAndService() throws Exception {
        var config = new HikariConfig();
        config.setJdbcUrl(postgres.getJdbcUrl());
        config.setUsername(postgres.getUsername());
        config.setPassword(postgres.getPassword());
        config.setMaximumPoolSize(3);
        dataSource = new HikariDataSource(config);
        // The same migrations a new database receives, run the same way: no substitution.
        Flyway.configure().dataSource(dataSource).locations("classpath:db/migration")
                .load().migrate();
        jdbc = new JdbcTemplate(dataSource);
        // The CDC migration runs unchanged except for the isolated secret and database name.
        String cdcSql = new ClassPathResource("db/cdc/cdc_prerequisites.sql")
                .getContentAsString(StandardCharsets.UTF_8)
                .replace("__CDC_PASSWORD__", CDC_PASSWORD)
                .replace("__DATABASE_NAME__", postgres.getDatabaseName());
        new ResourceDatabasePopulator(new ByteArrayResource(cdcSql.getBytes(StandardCharsets.UTF_8)))
                .execute(dataSource);
        // analysis_job.user_id references "user" since V4, so the owner of these jobs has to
        // exist. Inserted with an explicit id because every enqueue below uses OWNER_ID.
        jdbc.update("""
                INSERT INTO "user" (user_id, github_id, github_login, name)
                VALUES (?, ?, 'octocat', 'Octo Cat')
                """, OWNER_ID, OWNER_ID);
        // validate: this database was built from the deployment SQL, so the entity mapping
        // is checked against exactly what production applies.
        entityManagers = AnalysisJpaSupport.entityManagerFactory(dataSource, "validate");
        var entityManagerFactory = entityManagers.getObject();
        transactions = new JpaTransactionManager(entityManagerFactory);
        transactions.afterPropertiesSet();
        var analysisJobs = AnalysisJpaSupport.repository(entityManagerFactory);
        context = new AnnotationConfigApplicationContext();
        context.register(TransactionConfiguration.class);
        context.registerBean(JdbcTemplate.class, () -> jdbc);
        context.registerBean(AnalysisOutboxStore.class, () -> new AnalysisOutboxStore(jdbc));
        context.registerBean(AnalysisJobRepository.class, () -> analysisJobs);
        context.registerBean(JpaTransactionManager.class, () -> transactions);
        context.registerBean(RepositoryAnalysisKafkaProperties.class,
                () -> new RepositoryAnalysisKafkaProperties(
                        TOPIC, "gitjob.repository-analysis.results.v1", ""));
        context.registerBean(JsonMapper.class, () -> mapper);
        context.registerBean(AnalysisRequestService.class);
        context.refresh();
        service = context.getBean(AnalysisRequestService.class);
    }

    private void prepareTopics() throws Exception {
        try (var admin = AdminClient.create(Map.of("bootstrap.servers", kafka.getBootstrapServers()))) {
            admin.createTopics(List.of(new NewTopic(TOPIC, 1, (short) 1),
                    new NewTopic("__debezium-heartbeat.gitjob_cdc", 1, (short) 1),
                    compactedTopic("cdc-test-configs"), compactedTopic("cdc-test-offsets"),
                    compactedTopic("cdc-test-status"))).all().get(30, TimeUnit.SECONDS);
        }
    }

    private NewTopic compactedTopic(String name) {
        return new NewTopic(name, 1, (short) 1).configs(Map.of("cleanup.policy", "compact"));
    }

    private GenericContainer<?> newConnectWorker() {
        return new GenericContainer<>("quay.io/debezium/connect:3.4.3")
                .withNetwork(network).withExposedPorts(8083)
                .withEnv("BOOTSTRAP_SERVERS", "kafka:19092")
                .withEnv("GROUP_ID", "cdc-test-connect")
                .withEnv("CONFIG_STORAGE_TOPIC", "cdc-test-configs")
                .withEnv("OFFSET_STORAGE_TOPIC", "cdc-test-offsets")
                .withEnv("STATUS_STORAGE_TOPIC", "cdc-test-status")
                .withEnv("CONFIG_STORAGE_REPLICATION_FACTOR", "1")
                .withEnv("OFFSET_STORAGE_REPLICATION_FACTOR", "1")
                .withEnv("STATUS_STORAGE_REPLICATION_FACTOR", "1")
                .withEnv("OFFSET_FLUSH_INTERVAL_MS", "1000")
                // Only CONNECT_-prefixed variables become worker properties in this image.
                .withEnv("CONNECT_CONFIG_PROVIDERS", "env")
                .withEnv("CONNECT_CONFIG_PROVIDERS_ENV_CLASS",
                        "org.apache.kafka.common.config.provider.EnvVarConfigProvider")
                .withEnv("CDC_DATABASE_PASSWORD", CDC_PASSWORD)
                .waitingFor(Wait.forHttp("/connectors").forPort(8083).forStatusCode(200))
                .withStartupTimeout(Duration.ofMinutes(2));
    }

    /**
     * Each call is a different repository. uq_analysis_job_active allows only one active job
     * per (user, repository), and these tests need several rows in flight at once.
     */
    private RepositoryAnalysisRequestedEvent enqueue(String suffix) {
        return service.enqueueAuthorized(OWNER_ID, new RepositoryAnalysisRequestPayload(
                "an_" + suffix, "ar_" + suffix, nextRepositoryId.incrementAndGet(),
                "octocat/gitjob", "feature/cdc",
                "0123456789abcdef0123456789abcdef01234567", RepositoryAnalysisMode.SNAPSHOT,
                "technology-registry/v1"), "trace_cdc_test");
    }

    private ConsumerRecord<String, String> awaitEvent(String eventId) throws Exception {
        long deadline = System.nanoTime() + EVENT_TIMEOUT.toNanos();
        while (System.nanoTime() < deadline) {
            for (var record : consumer.poll(Duration.ofMillis(500))) {
                assertNotNull(record.value(), "Unexpected tombstone in the analysis request topic");
                var event = mapper.readValue(record.value(), RepositoryAnalysisRequestedEvent.class);
                received.put(event.eventId(), record);
            }
            if (received.containsKey(eventId)) {
                return received.get(eventId);
            }
        }
        fail("No event " + eventId + "; connector status: "
                + request("GET", "/connectors/" + CONNECTOR + "/status", null).body()
                + "\n" + connect.getLogs());
        return null;
    }

    private void assertContract(RepositoryAnalysisRequestedEvent expected, ConsumerRecord<String, String> actual) {
        assertNotNull(actual);
        assertEquals(TOPIC, actual.topic());
        assertEquals(expected.partitionKey(), actual.key());
        assertEquals(expected, mapper.readValue(actual.value(), RepositoryAnalysisRequestedEvent.class));
        var json = mapper.readTree(actual.value());
        assertTrue(json.isObject(), "JSON must not be double encoded");
        assertFalse(json.has("schema"), "Connect schema envelope must be disabled");
        assertTrue(json.path("payload").path("github_repository_id").isIntegralNumber());
        assertEquals("feature/cdc", json.path("payload").path("branch_name").asString());
        assertEquals(expected.payload().commitSha(), json.path("payload").path("commit_sha").asString());
        assertFalse(actual.value().contains("access_token"));
        assertFalse(actual.value().contains("refresh_token"));
        assertFalse(actual.value().contains("private_key"));
        assertFalse(actual.value().contains(CDC_PASSWORD));
        assertNotNull(actual.headers().lastHeader("id"), "Debezium must retain the event ID header");
        assertEquals(expected.eventId(), new String(actual.headers().lastHeader("id").value(), StandardCharsets.UTF_8));
    }

    private void awaitConnectorRunning() throws Exception {
        long deadline = System.nanoTime() + EVENT_TIMEOUT.toNanos();
        String lastStatus = "not available";
        while (System.nanoTime() < deadline) {
            var response = request("GET", "/connectors/" + CONNECTOR + "/status", null);
            lastStatus = response.body();
            if (response.statusCode() == 200) {
                var status = mapper.readTree(lastStatus);
                if ("FAILED".equals(status.path("connector").path("state").asString())
                        || "FAILED".equals(status.path("tasks").path(0).path("state").asString())) {
                    fail("Connector failed: " + lastStatus + "\n" + connect.getLogs());
                }
                if ("RUNNING".equals(status.path("connector").path("state").asString())
                        && "RUNNING".equals(status.path("tasks").path(0).path("state").asString())) {
                    return;
                }
            }
            Thread.sleep(250);
        }
        fail("Connector did not start: " + lastStatus + "\n" + connect.getLogs());
    }

    private HttpResponse<String> request(String method, String path, String body) throws Exception {
        var uri = URI.create("http://" + connect.getHost() + ":" + connect.getMappedPort(8083) + path);
        var request = HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(10))
                .header("Content-Type", "application/json")
                .method(method, body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body));
        return http.send(request.build(), HttpResponse.BodyHandlers.ofString());
    }

    @AfterAll
    void stopIsolatedPipeline() {
        if (consumer != null) consumer.close(Duration.ofSeconds(5));
        if (connect != null) connect.stop();
        if (context != null) context.close();
        if (entityManagers != null) entityManagers.destroy();
        if (dataSource != null) dataSource.close();
        if (postgres != null) postgres.stop();
        if (kafka != null) kafka.stop();
        if (network != null) network.close();
    }
}
