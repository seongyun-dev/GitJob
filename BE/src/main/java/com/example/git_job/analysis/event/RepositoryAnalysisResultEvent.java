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
    /** Common44 Rule Pack 계보와 기술별 지원 범위가 붙는다. */
    public static final String SCHEMA_VERSION_V2 = "repository-analysis-result/v2";
    /** v2 에 구조 근거(SYNTAX_NODE)와 syntax_node_count 가 붙는다. */
    public static final String SCHEMA_VERSION_V3 = "repository-analysis-result/v3";

    /**
     * 받아들이는 계약 버전.
     *
     * <p>워커는 Registry 버전에 따라 <b>하나</b>를 골라 발행한다. v1 을 함께 보내지
     * 않으므로({@code AI/analysis/consumer.py} 의 publisher 선택), v3 만 발행하는
     * 환경에서 v1 만 받으면 결과가 통째로 도달하지 않고 분석이 QUEUED 에 남는다.</p>
     *
     * <p>v4 는 아직 열지 않는다. 개인 귀속({@code personal_assessments})이 붙는 계약이고
     * 그 값을 저장할 자리가 없다. 열기 전에 저장 경로를 먼저 만들어야 한다.</p>
     */
    public static final java.util.Set<String> SUPPORTED_SCHEMA_VERSIONS =
            java.util.Set.of(SCHEMA_VERSION, SCHEMA_VERSION_V2, SCHEMA_VERSION_V3);
    public static final String EVENT_TYPE = "repository.analysis.completed";

    public RepositoryAnalysisResultEvent {
        eventId = requireNonBlank(eventId, "eventId");
        schemaVersion = requireSupported(schemaVersion);
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

    /**
     * 아는 계약만 받는다.
     *
     * <p>모르는 버전을 통과시키지 않는 이유는 그대로다 -- 새 계약은 필드가 늘어날 뿐
     * 아니라 기존 필드의 뜻이 바뀔 수 있고, 반쯤 해석한 결과를 저장하면 그 사실이
     * 어디에도 남지 않는다. 늘릴 때는 저장 경로를 함께 만든다.</p>
     */
    private static String requireSupported(String value) {
        if (!SUPPORTED_SCHEMA_VERSIONS.contains(value)) {
            throw new IllegalArgumentException(
                    "schemaVersion must be one of " + SUPPORTED_SCHEMA_VERSIONS);
        }
        return value;
    }
}
