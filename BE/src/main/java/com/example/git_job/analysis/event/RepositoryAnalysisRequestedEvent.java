package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.Objects;

/**
 * Versioned Kafka contract that starts one repository analysis job.
 */
public record RepositoryAnalysisRequestedEvent(
        @JsonProperty("event_id") String eventId,
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("event_type") String eventType,
        @JsonProperty("occurred_at") Instant occurredAt,
        @JsonProperty("trace_id") String traceId,
        @JsonProperty("payload") RepositoryAnalysisRequestPayload payload
) {

    public static final String SCHEMA_VERSION = "repository-analysis-request/v1";
    public static final String EVENT_TYPE = "repository.analysis.requested";

    public RepositoryAnalysisRequestedEvent {
        eventId = requireNonBlank(eventId, "eventId");
        schemaVersion = requireExact(schemaVersion, SCHEMA_VERSION, "schemaVersion");
        eventType = requireExact(eventType, EVENT_TYPE, "eventType");
        occurredAt = Objects.requireNonNull(occurredAt, "occurredAt must not be null");
        traceId = requireNonBlank(traceId, "traceId");
        payload = Objects.requireNonNull(payload, "payload must not be null");
    }

    public static RepositoryAnalysisRequestedEvent create(
            String eventId,
            Instant occurredAt,
            String traceId,
            RepositoryAnalysisRequestPayload payload
    ) {
        return new RepositoryAnalysisRequestedEvent(
                eventId,
                SCHEMA_VERSION,
                EVENT_TYPE,
                occurredAt,
                traceId,
                payload
        );
    }

    /**
     * Kafka key used to keep all deliveries for one repository analysis on a
     * stable partition.
     */
    public String partitionKey() {
        return payload.analysisRepositoryId();
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
