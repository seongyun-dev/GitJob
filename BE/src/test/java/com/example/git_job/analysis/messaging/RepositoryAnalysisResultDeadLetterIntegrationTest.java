package com.example.git_job.analysis.messaging;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import org.apache.kafka.clients.admin.Admin;
import org.apache.kafka.clients.admin.AdminClientConfig;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.serialization.ByteArrayDeserializer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.boot.kafka.autoconfigure.KafkaProperties;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.ConcurrentMessageListenerContainer;
import org.springframework.kafka.listener.MessageListener;
import org.testcontainers.kafka.KafkaContainer;

/**
 * 적용하지 못한 결과가 어디로 가는지 확인한다.
 *
 * <h2>왜 브로커를 띄워서까지 확인하는가</h2>
 *
 * <p>이 경로의 고장은 예외로 드러나지 않았다. 결과 이벤트가 역직렬화에 실패했을 때
 * {@code DefaultErrorHandler} 는 그것을 재시도 불가로 분류해 <b>로그 한 줄만 남기고
 * 오프셋을 커밋</b>했다. lag 는 0 이고 컨슈머는 건강해 보였으며, 화면만 5초마다 QUEUED 를
 * 다시 물었다. 저장소 4개의 판정과 근거가 그렇게 사라졌고, 무엇을 재생해야 하는지조차
 * 남지 않아 오프셋을 시각으로 되감아 짐작해야 했다.</p>
 *
 * <p>그 동작은 설정 한 줄로 되돌아온다. 그래서 "DLQ 로 갔다"를 브로커에서 직접 확인한다
 * -- 목으로는 같은 결론을 낼 수 없다. 역직렬화 실패 레코드의 값이 객체가 아니라 원본
 * 바이트라는 것, 그래서 전용 직렬화기가 필요하다는 것도 여기서만 드러난다.</p>
 */
@EnabledIf("com.example.git_job.support.DockerAvailable#check")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class RepositoryAnalysisResultDeadLetterIntegrationTest {

    private static final String RESULTS = "gitjob.repository-analysis.results.v1";
    private static final String DLQ = "gitjob.repository-analysis.results.dlq.v1";
    private static final Path V1_FIXTURE = Path.of("..", "AI", "tests", "fixtures",
            "repository-analysis-result-v1-base-3a4c57c.json");

    private KafkaContainer kafka;
    private ConcurrentMessageListenerContainer<String, RepositoryAnalysisResultEvent> container;
    private KafkaConsumer<String, byte[]> deadLetters;

    private final BlockingQueue<RepositoryAnalysisResultEvent> applied = new LinkedBlockingQueue<>();

    @BeforeAll
    void startBroker() throws Exception {
        // 토픽 자동 생성을 끈다. DLQ 가 없는 브로커에서 조용히 만들어지면, 운영에서
        // 토픽 이름을 잘못 적어도 테스트는 통과한다.
        kafka = new KafkaContainer("apache/kafka:4.0.0")
                .withEnv("KAFKA_AUTO_CREATE_TOPICS_ENABLE", "false");
        kafka.start();
        try (Admin admin = Admin.create(Map.of(
                AdminClientConfig.BOOTSTRAP_SERVERS_CONFIG, kafka.getBootstrapServers()))) {
            admin.createTopics(List.of(
                    new NewTopic(RESULTS, 1, (short) 1),
                    new NewTopic(DLQ, 1, (short) 1))).all().get(30, TimeUnit.SECONDS);
        }

        deadLetters = new KafkaConsumer<>(Map.of(
                ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, kafka.getBootstrapServers(),
                ConsumerConfig.GROUP_ID_CONFIG, "dlq-observer-" + UUID.randomUUID(),
                ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
                ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, ByteArrayDeserializer.class,
                ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest",
                ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false"));
        deadLetters.subscribe(List.of(DLQ));

        container = listenerContainer();
        container.start();
        assertTrue(waitForAssignment(), "listener never took its partition");
    }

    @AfterAll
    void stopBroker() {
        if (container != null) {
            container.stop();
        }
        if (deadLetters != null) {
            deadLetters.close();
        }
        if (kafka != null) {
            kafka.stop();
        }
    }

    @Test
    void appliesAResultTheWorkerActuallyPublished() throws Exception {
        String json = Files.readString(V1_FIXTURE, StandardCharsets.UTF_8);

        publish("an_1", json);

        RepositoryAnalysisResultEvent event = applied.poll(30, TimeUnit.SECONDS);
        assertNotNull(event, "the v1 result never reached the listener");
        assertEquals("repository-analysis-result/v1", event.schemaVersion());
        // 이 계약에는 syntax_node_count 가 없다. 그것 하나로 결과 전체가 버려지던 자리다.
        assertEquals("an_1", event.payload().analysisId());
    }

    @Test
    void sendsAResultItCannotInterpretToTheDeadLetterTopic() throws Exception {
        // 모르는 계약이라 역직렬화에서 거절된다 -- 재시도로 고쳐지지 않는 종류의 실패이며,
        // 전에는 바로 이 경로가 조용히 커밋됐다.
        String unknownContract = Files.readString(V1_FIXTURE, StandardCharsets.UTF_8)
                .replace("repository-analysis-result/v1", "repository-analysis-result/v99");

        publish("an_poison", unknownContract);

        ConsumerRecord<String, byte[]> dead = pollDeadLetter();
        assertNotNull(dead, "the rejected result did not reach the DLQ");
        // 원본 바이트 그대로여야 재생할 수 있다. JSON 직렬화기로 나가면 base64 문자열이 된다.
        assertEquals(unknownContract, new String(dead.value(), StandardCharsets.UTF_8));
        assertEquals("an_poison", dead.key());
        assertEquals(RESULTS, header(dead, "kafka_dlt-original-topic"));
        // 리스너는 이것을 본 적이 없어야 한다. 반쯤 해석한 결과를 적용하는 것보다
        // 사람이 DLQ 를 비우는 편이 낫다.
        assertEquals(0, applied.size());
    }

    private ConcurrentMessageListenerContainer<String, RepositoryAnalysisResultEvent>
            listenerContainer() {
        var kafkaProperties = new KafkaProperties();
        kafkaProperties.setBootstrapServers(List.of(kafka.getBootstrapServers()));
        kafkaProperties.getConsumer().setGroupId("results-" + UUID.randomUUID());

        var topics = new RepositoryAnalysisKafkaProperties(
                "gitjob.repository-analysis.requests.v1", RESULTS, "", DLQ, "");

        var factory = new RepositoryAnalysisKafkaConfiguration()
                .repositoryAnalysisResultListenerFactory(
                        kafkaProperties, topics, fallbackTemplate());

        var created = factory.createContainer(RESULTS);
        created.setupMessageListener(
                (MessageListener<String, RepositoryAnalysisResultEvent>)
                        record -> applied.add(record.value()));
        return created;
    }

    /**
     * 역직렬화가 아닌 실패에 쓰이는 템플릿. 이 테스트에서는 닿지 않지만, 운영 설정이
     * 두 템플릿을 모두 요구하므로 같은 모양으로 넘긴다.
     */
    private KafkaTemplate<Object, Object> fallbackTemplate() {
        return new KafkaTemplate<>(new DefaultKafkaProducerFactory<>(Map.of(
                ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, kafka.getBootstrapServers(),
                ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class,
                ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class)));
    }

    private void publish(String key, String json) throws Exception {
        try (var producer = new KafkaProducer<String, String>(Map.of(
                ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, kafka.getBootstrapServers(),
                ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class,
                ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class))) {
            producer.send(new ProducerRecord<>(RESULTS, key, json)).get(30, TimeUnit.SECONDS);
        }
    }

    private ConsumerRecord<String, byte[]> pollDeadLetter() {
        long deadline = System.nanoTime() + Duration.ofSeconds(60).toNanos();
        while (System.nanoTime() < deadline) {
            ConsumerRecords<String, byte[]> records = deadLetters.poll(Duration.ofSeconds(2));
            for (ConsumerRecord<String, byte[]> record : records) {
                return record;
            }
        }
        return null;
    }

    private boolean waitForAssignment() throws InterruptedException {
        long deadline = System.nanoTime() + Duration.ofSeconds(60).toNanos();
        while (System.nanoTime() < deadline) {
            if (container.isRunning() && !container.getAssignedPartitions().isEmpty()) {
                return true;
            }
            TimeUnit.MILLISECONDS.sleep(200);
        }
        return false;
    }

    private static String header(ConsumerRecord<String, byte[]> record, String name) {
        Header header = record.headers().lastHeader(name);
        return header == null ? null : new String(header.value(), StandardCharsets.UTF_8);
    }
}
