package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.Objects;

/**
 * Versioned Kafka contract that closes one repository analysis job.
 *
 * <p>The analysis worker publishes this; this service consumes it. The worker
 * does not write {@code analysis_job} or {@code analysis_evidence} because this
 * service owns them, maps them as JPA entities and boots with
 * {@code ddl-auto=validate}. A second writer in another language would turn
 * every column change into a two-repository migration, so the result arrives as
 * an event instead.</p>
 *
 * <p>Agreed shape:
 * {@code docs/data/contracts/repository-analysis-result-v1.schema.json}. The
 * producing half is {@code AI/analysis/results.py}. Both sides validate: they
 * deploy separately, and a message sitting in a topic was written by whatever
 * version was running then.</p>
 */
public record RepositoryAnalysisResultEvent(
        @JsonProperty("event_id") String eventId,
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("event_type") String eventType,
        @JsonProperty("occurred_at") Instant occurredAt,
        @JsonProperty("trace_id") String traceId,
        @JsonProperty("payload") RepositoryAnalysisResultPayload payload
) {

    public static final String SCHEMA_VERSION = "repository-analysis-result/v1";
    public static final String EVENT_TYPE = "repository.analysis.completed";

    public RepositoryAnalysisResultEvent {
        eventId = requireNonBlank(eventId, "eventId");
        schemaVersion = requireExact(schemaVersion, SCHEMA_VERSION, "schemaVersion");
        eventType = requireExact(eventType, EVENT_TYPE, "eventType");
        occurredAt = Objects.requireNonNull(occurredAt, "occurredAt must not be null");
        traceId = requireNonBlank(traceId, "traceId");
        payload = Objects.requireNonNull(payload, "payload must not be null");
    }

    /**
     * Deduplication key. Delivery is at-least-once, so a repeated eventId means
     * the work was already applied, not that it happened twice.
     */
    public String deduplicationKey() {
        return eventId;
    }

    private static String requireNonBlank(String value, String fieldName) {
        if (value == null || value.isBlank() || !value.equals(value.strip())) {
            throw new IllegalArgumentException(fieldName + " must be non-blank and trimmed");
        }
        return value;
    }

    private static String requireExact(String value, String expected, String fieldName) {
        if (!expected.equals(value)) {
            throw new IllegalArgumentException(fieldName + " must be " + expected);
        }
        return value;
    }
}
