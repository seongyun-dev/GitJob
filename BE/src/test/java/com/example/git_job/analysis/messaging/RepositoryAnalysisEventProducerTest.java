package com.example.git_job.analysis.messaging;

import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.event.RepositoryAnalysisMode;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestPayload;
import com.example.git_job.analysis.event.RepositoryAnalysisRequestedEvent;
import java.time.Instant;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

class RepositoryAnalysisEventProducerTest {

    @Test
    void publishesToConfiguredTopicWithStableRepositoryAnalysisKey() {
        @SuppressWarnings("unchecked")
        KafkaTemplate<Object, Object> kafkaTemplate = mock(KafkaTemplate.class);
        RepositoryAnalysisKafkaProperties properties =
                new RepositoryAnalysisKafkaProperties(
                        "gitjob.repository-analysis.requests.v1",
                        "gitjob.repository-analysis.results.v1"
                , "", "gitjob.repository-analysis.results.dlq.v1");
        RepositoryAnalysisEventProducer producer =
                new RepositoryAnalysisEventProducer(kafkaTemplate, properties);
        RepositoryAnalysisRequestedEvent event = event();
        CompletableFuture<SendResult<Object, Object>> expected = new CompletableFuture<>();

        when(kafkaTemplate.send(properties.requests(), "ar_01ABC", event))
                .thenReturn(expected);

        CompletableFuture<SendResult<Object, Object>> actual = producer.publish(event);

        assertSame(expected, actual);
        verify(kafkaTemplate).send(properties.requests(), "ar_01ABC", event);
    }

    private RepositoryAnalysisRequestedEvent event() {
        return RepositoryAnalysisRequestedEvent.create(
                "ev_01ABC",
                Instant.parse("2026-09-07T10:00:00Z"),
                "tr_01ABC",
                new RepositoryAnalysisRequestPayload(
                        "an_01ABC",
                        "ar_01ABC",
                        123456789L,
                        "octocat/gitjob",
                        "main",
                        "0123456789abcdef0123456789abcdef01234567",
                        RepositoryAnalysisMode.SNAPSHOT,
                        "technology-registry/v1"
                )
        );
    }
}
