package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.Objects;

/**
 * 분석이 다음 단계로 넘어갔다는 알림.
 *
 * <p>워커가 발행하고 이 서비스가 소비한다. 봉투는 결과 이벤트
 * ({@link RepositoryAnalysisResultEvent}) 와 같은 모양이다 -- 같은 워커가 같은
 * 분석에 대해 보내는 두 종류의 소식이라, 읽는 쪽이 필드를 두 번 배울 이유가 없다.
 * 발행하는 쪽은 {@code AI/analysis/progress.py} 다.</p>
 *
 * <h2>결과 토픽에 싣지 않는 이유</h2>
 *
 * <p>결과 토픽은 분석이 끝나는 유일한 경로다({@code AI/analysis/publish.py}). 거기에
 * 표시용 메시지를 섞으면 진행 이벤트 하나의 계약 위반이 그 분석의 결과까지 DLQ 로
 * 보낸다. 잃어도 되는 것과 잃으면 안 되는 것을 같은 통로에 두지 않는다.</p>
 *
 * <h2>이 이벤트는 잃어도 된다</h2>
 *
 * <p>도달하지 않으면 화면이 한 단계 늦게 움직일 뿐, 분석 자체는 결과 이벤트로
 * 정상 종료된다. 그래서 워커는 발행 실패를 삼키고, 이쪽은 DLQ 를 두지 않는다.
 * 결과 이벤트와 정반대의 선택이며, 그 차이가 이 계약을 나눈 이유다.</p>
 */
public record RepositoryAnalysisProgressEvent(
        @JsonProperty("event_id") String eventId,
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("event_type") String eventType,
        @JsonProperty("occurred_at") Instant occurredAt,
        @JsonProperty("trace_id") String traceId,
        @JsonProperty("payload") RepositoryAnalysisProgressPayload payload
) {

    public static final String SCHEMA_VERSION = "repository-analysis-progress/v1";
    public static final String EVENT_TYPE = "repository.analysis.progressed";

    public RepositoryAnalysisProgressEvent {
        eventId = requireNonBlank(eventId, "eventId");
        schemaVersion = requireExact(schemaVersion, SCHEMA_VERSION, "schemaVersion");
        eventType = requireExact(eventType, EVENT_TYPE, "eventType");
        occurredAt = Objects.requireNonNull(occurredAt, "occurredAt must not be null");
        traceId = requireNonBlank(traceId, "traceId");
        payload = Objects.requireNonNull(payload, "payload must not be null");
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
