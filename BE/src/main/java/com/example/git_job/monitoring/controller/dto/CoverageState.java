package com.example.git_job.monitoring.controller.dto;

/**
 * 지표 범위의 수집 여부 (S15P21E102-209).
 *
 * <p>두 값만 둔다. 이 계약이 답해야 하는 질문은 "이 값을 신뢰할 수 있는가" 하나이고,
 * 그 밖의 구분(대기·부분·실패)은 화면의 상태 어휘가 이미 갖고 있다.</p>
 */
public enum CoverageState {
    /** Prometheus에 시계열이 있고 값을 신뢰할 수 있다. */
    COLLECTED,
    /** exporter나 exposition endpoint가 아직 없다. 값을 만들지 않는다. */
    NOT_COLLECTED
}
