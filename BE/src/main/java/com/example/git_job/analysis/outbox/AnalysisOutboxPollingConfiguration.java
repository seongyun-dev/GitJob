package com.example.git_job.analysis.outbox;

import com.example.git_job.analysis.messaging.RepositoryAnalysisEventProducer;
import com.example.git_job.analysis.messaging.RepositoryAnalysisKafkaProperties;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.transaction.PlatformTransactionManager;
import tools.jackson.databind.json.JsonMapper;

/** Legacy relay: never enabled by the old enabled flag alone, or alongside the CDC relay. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "gitjob.analysis.outbox", name = "mode", havingValue = "POLLING")
@EnableScheduling
class AnalysisOutboxPollingConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "gitjob.analysis.outbox", name = "enabled",
            havingValue = "true", matchIfMissing = true)
    RepositoryAnalysisEventProducer repositoryAnalysisEventProducer(
            KafkaTemplate<Object, Object> kafkaTemplate, RepositoryAnalysisKafkaProperties topics) {
        return new RepositoryAnalysisEventProducer(kafkaTemplate, topics);
    }

    @Bean
    @ConditionalOnProperty(prefix = "gitjob.analysis.outbox", name = "enabled",
            havingValue = "true", matchIfMissing = true)
    AnalysisOutboxPublisher analysisOutboxPublisher(AnalysisOutboxStore store,
            RepositoryAnalysisEventProducer producer, JsonMapper mapper,
            AnalysisOutboxProperties properties, PlatformTransactionManager manager) {
        return new AnalysisOutboxPublisher(store, producer, mapper, properties, manager);
    }
}
