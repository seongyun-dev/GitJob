package com.example.git_job.analysis.messaging;

import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.serialization.ByteArraySerializer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.springframework.boot.kafka.autoconfigure.KafkaProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaOperations;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.kafka.support.serializer.ErrorHandlingDeserializer;
import org.springframework.kafka.support.serializer.JacksonJsonDeserializer;
import org.springframework.util.backoff.FixedBackOff;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

@Configuration
@EnableConfigurationProperties(RepositoryAnalysisKafkaProperties.class)
class RepositoryAnalysisKafkaConfiguration {

    /**
     * 구독할 결과 토픽 (S15P21E102-279 후속).
     *
     * <p>워커는 Registry 버전에 따라 발행 토픽을 <b>바꾼다</b> -- v1 을 함께 보내지
     * 않는다. 그래서 v3 토픽도 함께 구독해야 {@code registry-20260911.3/.4} 결과가
     * 도달한다. 구독하지 않으면 분석이 QUEUED 에 남고 C 계산도 시작되지 않는다.</p>
     *
     * <p>애너테이션에 토픽 두 개를 직접 적지 않고 빈으로 만드는 이유는 v3 토픽이
     * 선택값이기 때문이다. 미설정이면 빈 문자열이 되는데, 그대로 넘기면 Spring 이
     * 이름 없는 토픽을 구독하려다 실패한다. 여기서 걸러 낸다.</p>
     */
    @Bean
    String[] repositoryAnalysisResultTopics(RepositoryAnalysisKafkaProperties topics) {
        return topics.hasResultsV3()
                ? new String[] {topics.results(), topics.resultsV3()}
                : new String[] {topics.results()};
    }

    /**
     * A dedicated factory rather than the autoconfigured one: this topic carries
     * exactly one payload type, and pinning it here means a message of another
     * shape fails at deserialization instead of arriving half-built.
     */
    @Bean
    ConcurrentKafkaListenerContainerFactory<String, RepositoryAnalysisResultEvent>
            repositoryAnalysisResultListenerFactory(
                    KafkaProperties kafka,
                    RepositoryAnalysisKafkaProperties topics,
                    KafkaTemplate<Object, Object> kafkaTemplate) {
        var factory =
                new ConcurrentKafkaListenerContainerFactory<String, RepositoryAnalysisResultEvent>();
        factory.setConsumerFactory(resultConsumerFactory(kafka));
        factory.setCommonErrorHandler(resultErrorHandler(kafka, topics, kafkaTemplate));
        // A custom factory does not read spring.kafka.listener.* on its own.
        // Honouring auto-startup here keeps one switch for both this listener
        // and any autoconfigured one, and lets a context test boot without a
        // broker it has no reason to need.
        factory.setAutoStartup(kafka.getListener().isAutoStartup());
        return factory;
    }

    /**
     * 결과 이벤트를 읽는 매퍼.
     *
     * <h2>왜 기본값에 기대지 않는가</h2>
     *
     * <p>{@code FAIL_ON_UNKNOWN_PROPERTIES} 는 Jackson 3 에서 기본이 꺼져 있고, 지금
     * v2·v3 결과는 그 기본값 덕분에만 읽힌다. 그 계약의 {@code stats} 에는 BE 가 쓰지
     * 않는 {@code source_file_count}·{@code annotation_count}·{@code config_count}·
     * {@code api_call_count} 가 실려 있기 때문이다.</p>
     *
     * <p>명시하는 이유는 이것이 취향이 아니라 <b>계약</b>이기 때문이다. 워커는 결과
     * 계약을 additive 로 늘리고, 새 필드가 하나 붙었다고 결과 전체가 버려지면 분석은
     * QUEUED 에 남는다 -- {@code syntax_node_count} 하나로 실제 일어난 일이다. 전역
     * 매퍼 설정이 언젠가 바뀌어도 이 토픽은 영향을 받지 않아야 한다.</p>
     *
     * <p>알 수 없는 필드를 넘긴다고 아무 JSON 이나 통과하지는 않는다. 계약 위반은
     * {@link RepositoryAnalysisResultEvent} 와 그 payload 의 생성자가 잡는다 --
     * 모르는 {@code schema_version}, 40자가 아닌 commit sha, 규칙 없는 판정은 모두
     * 거기서 거절된다.</p>
     */
    private static JsonMapper resultMapper() {
        return JsonMapper.builder()
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
    }

    /**
     * 결과 토픽의 값 역직렬화기.
     *
     * <p>{@code resultConsumerFactory} 안에 인라인으로 두지 않는 이유는 계약 테스트가
     * 이것을 그대로 불러야 하기 때문이다. 테스트가 자기 {@code JsonMapper} 를 만들면
     * 운영이 쓰는 설정이 아니라 테스트가 쓰는 설정을 검증하게 되고, 그 차이가 바로
     * 이번에 v1 결과를 전부 잃게 만든 종류의 구멍이다 -- 기존 테스트는 record 생성자만
     * 호출해서 JSON 을 한 번도 읽지 않았고, 그래서 전부 통과한 채로 배포됐다.</p>
     */
    static JacksonJsonDeserializer<RepositoryAnalysisResultEvent> resultValueDeserializer() {
        var value = new JacksonJsonDeserializer<>(
                RepositoryAnalysisResultEvent.class, resultMapper());
        // 타입 헤더를 믿지 않는다. 이 토픽은 워커가 쓰고, 워커는 Java 타입 이름을 모른다.
        value.setUseTypeHeaders(false);
        return value;
    }

    private ConsumerFactory<String, RepositoryAnalysisResultEvent> resultConsumerFactory(
            KafkaProperties kafka) {
        Map<String, Object> config = kafka.buildConsumerProperties();
        // The offset is committed after the listener returns, so a crash mid-apply
        // replays the message rather than losing the result. The service is
        // idempotent, which is what makes replaying safe.
        config.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, false);
        // Results published while this service was down still have to land.
        config.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        // One at a time: applying a result writes up to two thousand evidence rows
        // in one transaction, and a batch of them would hold it far too long.
        config.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, 1);

        return new DefaultKafkaConsumerFactory<>(
                config,
                new ErrorHandlingDeserializer<>(new StringDeserializer()),
                new ErrorHandlingDeserializer<>(resultValueDeserializer()));
    }

    /**
     * 포기한 결과를 DLQ 로 보낼 때 쓰는 전용 템플릿.
     *
     * <p>역직렬화에 실패한 레코드는 값이 객체가 아니라 <b>원본 바이트</b>다
     * ({@code DeserializationException.getData()}). 그것을 JSON 직렬화기로 보내면
     * base64 문자열이 되어 재생할 수 없다.</p>
     *
     * <p>키는 문자열 그대로다. 실패한 쪽은 값이고, 키 역직렬화기
     * ({@code StringDeserializer})는 실패하지 않는다.</p>
     */
    private static KafkaOperations<Object, Object> deadLetterBytesTemplate(KafkaProperties kafka) {
        Map<String, Object> config = kafka.buildProducerProperties();
        config.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        config.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, ByteArraySerializer.class);
        return new KafkaTemplate<>(new DefaultKafkaProducerFactory<>(config));
    }

    /**
     * 재시도로 고쳐지는 실패는 재시도하고, 나머지는 DLQ 로 보낸다.
     *
     * <h2>재시도가 닿지 않는 실패가 있다</h2>
     *
     * <p>{@code FixedBackOff} 는 역직렬화 오류에 적용되지 않는다.
     * {@code DefaultErrorHandler} 가 {@code DeserializationException} 을 재시도 불가로
     * 분류하기 때문이다 -- 같은 바이트를 다시 읽어도 결과가 같으니 그 판단 자체는 옳다.
     * 문제는 그다음이었다. recoverer 가 없어서 그런 레코드는 <b>로그 한 줄만 남기고
     * 커밋</b>됐고, 결과는 조용히 사라졌다. 오프셋은 끝까지 진행돼 lag 는 0 이었고,
     * 화면은 5초마다 QUEUED 를 다시 물었다.</p>
     *
     * <p>DLQ 가 그 구멍을 막는다. 원본 바이트와 예외가 헤더({@code kafka_dlt-*})와 함께
     * 남으므로, 계약을 고친 뒤 무엇을 재생해야 하는지 브로커가 알려 준다 -- 오프셋을
     * 시각으로 되감아 짐작하지 않아도 된다.</p>
     *
     * <h2>DLQ 전송이 실패하면 멈춘다</h2>
     *
     * <p>{@code failIfSendResultIsError} 기본값(참)을 그대로 둔다. "한 건 때문에 파티션을
     * 세우지 않는다"는 원칙은 유지되지만, 그것은 실패를 <b>어딘가에 남긴 뒤</b>의
     * 이야기다. 안전망 자체가 끊긴 상태에서 커밋하고 넘어가면 이번 장애를 그대로
     * 반복한다. DLQ 전송까지 실패하는 상황은 Kafka 가 아픈 것이고, 그때는 어차피 새
     * 결과도 들어오지 않는다.</p>
     */
    private DefaultErrorHandler resultErrorHandler(
            KafkaProperties kafka,
            RepositoryAnalysisKafkaProperties topics,
            KafkaTemplate<Object, Object> kafkaTemplate) {

        // 값 타입으로 템플릿을 고른다. 역직렬화 실패는 원본 바이트로, 리스너가 던진
        // 실패는 이미 객체이므로 기본 JSON 템플릿으로 나간다.
        Map<Class<?>, KafkaOperations<?, ?>> templates = new LinkedHashMap<>();
        templates.put(byte[].class, deadLetterBytesTemplate(kafka));
        templates.put(Object.class, kafkaTemplate);

        var recoverer = new DeadLetterPublishingRecoverer(templates,
                (record, exception) -> new TopicPartition(topics.resultsDlq(), -1));
        // 원본 토픽·파티션·오프셋을 헤더로 남긴다. v1 과 v3 결과가 같은 DLQ 에 섞이므로,
        // 재생할 때 어느 토픽에서 왔는지가 헤더에만 남는다.
        recoverer.setAppendOriginalHeaders(true);

        return new DefaultErrorHandler(
                recoverer, new FixedBackOff(Duration.ofSeconds(2).toMillis(), 3));
    }
}
