package com.example.git_job.compute.client.dto;

import java.time.Instant;
import java.util.List;

/**
 * {@code POST /internal/v1/c/analyses/completed}의 요청과 응답 (S15P21E102-279).
 *
 * <p>{@code eventId}가 멱등의 전부다. C는 같은 ID의 재전달에 저장된 결과를 그대로 주고,
 * 같은 ID로 내용이 바뀌면 409로 거절한다. 그래서 이 값은 무작위가 아니라
 * {@code (userId, evidenceVersion, cohortSnapshotId, computeVersions)}에서 결정론적으로
 * 만든다 — 서버를 재시작하든 Kafka가 결과를 두 번 주든 같은 값이 나와야 한다.</p>
 *
 * <p>{@code traceId}만 다른 재전달은 C가 허용한다. 추적용 값이 멱등을 깨뜨리지 않도록
 * 계약에 그렇게 적혀 있다.</p>
 */
public record AnalysisCompleted(
        String schemaVersion,
        String eventId,
        String traceId,
        /** timezone이 있어야 한다. epoch 숫자로 직렬화되면 C가 422로 거절한다. */
        Instant occurredAt,
        String userId,
        /** 사용자 단위 분석 ID. 저장소별 BE 분석 ID가 아니다. */
        String analysisId,
        String cohortSnapshotId,
        EvidencePayload evidence
) {

    public static final String SCHEMA_VERSION = "c-compute-event/v1";

    /**
     * 완료 응답.
     *
     * <p>{@code results}에서 {@code kind=RECOMMENDATION}인 것만 쓴다. 같은 event가
     * 매칭 결과도 함께 저장하지만 그쪽은 RECOMMENDATION Snapshot ID로 조회한다.</p>
     */
    public record Result(String eventId, String status, List<Reference> results) {

        public String recommendationSnapshotId() {
            if (results == null) {
                return null;
            }
            return results.stream()
                    .filter(reference -> "RECOMMENDATION".equals(reference.kind()))
                    .map(Reference::snapshotId)
                    .filter(id -> id != null && !id.isBlank())
                    .findFirst()
                    .orElse(null);
        }
    }

    public record Reference(String kind, String snapshotId) {
    }
}
