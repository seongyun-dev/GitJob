package com.example.git_job.analysis.messaging;

import com.example.git_job.analysis.event.RepositoryAnalysisRequestedEvent;
import java.util.concurrent.CompletableFuture;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

/** Legacy polling transport. In CDC mode only Debezium publishes the saved event. */
public class RepositoryAnalysisEventProducer {

    private static final Logger log = LoggerFactory.getLogger(
            RepositoryAnalysisEventProducer.class
    );

    private final KafkaTemplate<Object, Object> kafkaTemplate;
    private final RepositoryAnalysisKafkaProperties properties;

    public RepositoryAnalysisEventProducer(
            KafkaTemplate<Object, Object> kafkaTemplate,
            RepositoryAnalysisKafkaProperties properties
    ) {
        this.kafkaTemplate = kafkaTemplate;
        this.properties = properties;
    }

    /**
     * Publishes an event that was created once by the analysis use case or its
     * outbox. Retrying this method must reuse the same event instance and ID.
     */
    public CompletableFuture<SendResult<Object, Object>> publish(
            RepositoryAnalysisRequestedEvent event
    ) {
        return publish(event, properties.requests());
    }

    /** Uses the destination saved with the outbox event, even if configuration changes later. */
    public CompletableFuture<SendResult<Object, Object>> publish(
            RepositoryAnalysisRequestedEvent event, String topic
    ) {
        CompletableFuture<SendResult<Object, Object>> send = kafkaTemplate.send(
                topic,
                event.partitionKey(),
                event
        );

        send.whenComplete((result, error) -> {
            if (error != null) {
                log.error(
                        "Repository analysis event publish failed: eventId={}, analysisId={}, "
                                + "analysisRepositoryId={}, topic={}",
                        event.eventId(),
                        event.payload().analysisId(),
                        event.payload().analysisRepositoryId(),
                        topic,
                        error
                );
                return;
            }

            log.info(
                    "Repository analysis event published: eventId={}, analysisId={}, "
                            + "analysisRepositoryId={}, topic={}, partition={}, offset={}",
                    event.eventId(),
                    event.payload().analysisId(),
                    event.payload().analysisRepositoryId(),
                    topic,
                    result.getRecordMetadata().partition(),
                    result.getRecordMetadata().offset()
            );
        });

        return send;
    }
}
