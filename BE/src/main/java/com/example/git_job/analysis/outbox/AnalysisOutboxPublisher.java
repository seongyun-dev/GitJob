package com.example.git_job.analysis.outbox;

import com.example.git_job.analysis.event.RepositoryAnalysisRequestedEvent;
import com.example.git_job.analysis.messaging.RepositoryAnalysisEventProducer;
import java.time.Instant;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.json.JsonMapper;

/**
 * Legacy polling-only at-least-once relay. One bounded send per row-lock transaction.
 * A crash after Kafka acknowledgement but before DB commit can redeliver the same event ID.
 */
public class AnalysisOutboxPublisher {
    private static final Logger log = LoggerFactory.getLogger(AnalysisOutboxPublisher.class);
    private final AnalysisOutboxStore store;
    private final RepositoryAnalysisEventProducer producer;
    private final JsonMapper mapper;
    private final AnalysisOutboxProperties properties;
    private final TransactionTemplate transaction;

    public AnalysisOutboxPublisher(AnalysisOutboxStore store, RepositoryAnalysisEventProducer producer,
            JsonMapper mapper, AnalysisOutboxProperties properties, PlatformTransactionManager manager) {
        this.store = store;
        this.producer = producer;
        this.mapper = mapper;
        this.properties = properties;
        this.transaction = new TransactionTemplate(manager);
        this.transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    @Scheduled(fixedDelayString = "${gitjob.analysis.outbox.poll-interval:2s}",
            initialDelayString = "${gitjob.analysis.outbox.initial-delay:10s}")
    public void publishPending() {
        if (!properties.enabled()) {
            return;
        }
        for (int i = 0; i < properties.batchSize() && !Thread.currentThread().isInterrupted(); i++) {
            try {
                if (!publishNext()) {
                    break;
                }
            } catch (RuntimeException error) {
                // A DB failure rolls back the row, making it eligible on the next poll.
                log.error("Outbox relay transaction failed: errorType={}", error.getClass().getSimpleName());
                break;
            }
        }
    }

    public boolean publishNext() {
        return Boolean.TRUE.equals(transaction.execute(status -> {
            var entry = store.lockNext();
            if (entry.isEmpty()) {
                return false;
            }
            dispatch(entry.get());
            return true;
        }));
    }

    private void dispatch(AnalysisOutboxStore.Entry entry) {
        RepositoryAnalysisRequestedEvent event;
        try {
            event = mapper.readValue(entry.json(), RepositoryAnalysisRequestedEvent.class);
            if (!entry.eventId().equals(event.eventId())) {
                throw new IllegalArgumentException("Outbox/event identity mismatch");
            }
        } catch (RuntimeException invalid) {
            recordFailure(entry, "INVALID_EVENT", true);
            return;
        }

        try {
            producer.publish(event, entry.topic())
                    .get(properties.sendTimeout().toMillis(), TimeUnit.MILLISECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            // Roll back without consuming an attempt during shutdown.
            throw new IllegalStateException("Outbox relay interrupted", interrupted);
        } catch (TimeoutException timeout) {
            recordFailure(entry, "KAFKA_ACK_TIMEOUT", false);
            return;
        } catch (ExecutionException | RuntimeException failure) {
            // Covers both async broker failures and synchronous send/serialization errors.
            recordFailure(entry, "KAFKA_SEND_FAILED", false);
            return;
        }
        // Keep DB failures outside the Kafka catch: roll back and allow redelivery.
        store.published(entry.eventId());
    }

    private void recordFailure(AnalysisOutboxStore.Entry entry, String code, boolean permanent) {
        int attempts = entry.attempts() + 1;
        boolean exhausted = permanent || attempts >= properties.maxAttempts();
        store.failed(entry.eventId(), code, exhausted,
                Instant.now().plus(properties.delayAfter(attempts)));
        log.warn("Outbox publish failed: eventId={}, attempt={}, status={}, errorCode={}",
                entry.eventId(), attempts, exhausted ? "FAILED" : "PENDING", code);
    }
}
