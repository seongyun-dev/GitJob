package com.example.git_job.analysis.messaging;

import com.example.git_job.analysis.event.RepositoryAnalysisResultEvent;
import java.time.Duration;
import java.util.Map;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.springframework.boot.kafka.autoconfigure.KafkaProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.kafka.support.serializer.ErrorHandlingDeserializer;
import org.springframework.kafka.support.serializer.JacksonJsonDeserializer;
import org.springframework.util.backoff.FixedBackOff;

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
            repositoryAnalysisResultListenerFactory(KafkaProperties kafka) {
        var factory =
                new ConcurrentKafkaListenerContainerFactory<String, RepositoryAnalysisResultEvent>();
        factory.setConsumerFactory(resultConsumerFactory(kafka));
        factory.setCommonErrorHandler(resultErrorHandler());
        // A custom factory does not read spring.kafka.listener.* on its own.
        // Honouring auto-startup here keeps one switch for both this listener
        // and any autoconfigured one, and lets a context test boot without a
        // broker it has no reason to need.
        factory.setAutoStartup(kafka.getListener().isAutoStartup());
        return factory;
    }

    private ConsumerFactory<String, RepositoryAnalysisResultEvent> resultConsumerFactory(
            KafkaProperties kafka) {
        var value = new JacksonJsonDeserializer<>(RepositoryAnalysisResultEvent.class);
        value.setUseTypeHeaders(false);

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
                new ErrorHandlingDeserializer<>(value));
    }

    /**
     * Retries a few times, then commits and moves on.
     *
     * <p>Same rule the worker follows: a failure a retry cannot fix must still be
     * committed, or one bad message stops the partition and no later analysis is
     * ever closed. A message given up on is logged, and the analysis stays
     * in-progress until an operator replays it.</p>
     */
    private DefaultErrorHandler resultErrorHandler() {
        return new DefaultErrorHandler(new FixedBackOff(Duration.ofSeconds(2).toMillis(), 3));
    }
}
