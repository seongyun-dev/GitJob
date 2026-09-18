package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * 한 분석이 지금 어느 단계에 있는지.
 *
 * <p>결과 payload 와 달리 저장할 값이 없다. 단계 하나가 전부이고, 나머지는
 * {@code analysisId} 로 이미 이 서비스가 알고 있다.</p>
 *
 * <h2>{@code stage} 가 enum 이 아닌 이유</h2>
 *
 * <p>여기서 {@link com.example.git_job.analysis.domain.AnalysisStage} 를 직접 받으면
 * 워커가 새 단계를 하나 더하는 순간 역직렬화가 깨진다. 깨진 레코드는 이 토픽에
 * DLQ 가 없으므로 로그 한 줄만 남기고 사라지는데, 그건 표시용 이벤트에 어울리는
 * 처리지만 <b>우연히 그렇게 되는 것</b>이라 기대고 싶지 않다.</p>
 *
 * <p>문자열로 받아 서비스에서 해석하면 모르는 단계는 "아직 내가 모르는 단계"로
 * 명시적으로 로그에 남고 메시지는 정상 소비된다. 워커와 BE 는 따로 배포되므로
 * 새 단계가 먼저 도착하는 순서는 정상이다.</p>
 */
public record RepositoryAnalysisProgressPayload(
        @JsonProperty("analysis_id") String analysisId,
        @JsonProperty("stage") String stage
) {

    public RepositoryAnalysisProgressPayload {
        analysisId = requireNonBlank(analysisId, "analysisId");
        stage = requireNonBlank(stage, "stage");
    }

    private static String requireNonBlank(String value, String fieldName) {
        if (value == null || value.isBlank() || !value.equals(value.strip())) {
            throw new IllegalArgumentException(fieldName + " must be non-blank and trimmed");
        }
        return value;
    }
}
