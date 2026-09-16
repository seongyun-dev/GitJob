package com.example.git_job.compute.controller.dto;

/**
 * 계산 계열 응답의 공통 상태 (S15P21E102-279).
 *
 * <p>인수 조건이 "C 장애 시 무조건 500으로 뭉개지 말고 계산 대기·미준비·일시 장애를
 * 구분하라"이다. 그 구분을 오류 코드로만 하면 화면이 오류 화면을 띄우게 되는데, 계산
 * 대기는 오류가 아니라 잠시 뒤 값이 생기는 상태다. 그래서 200 응답 안에 상태를 담는다.</p>
 *
 * <p>{@code dataStatus}는 FE에 이미 있는 {@code DataStatus} 7종을 쓴다. 값을 늘리면 FE의
 * 모든 분기를 고쳐야 하므로, 더 자세한 사유는 {@code statusReason}으로 뺐다.</p>
 */
public record ComputeState(String dataStatus, String statusReason, Integer retryAfterSec) {

    public static final String READY = "READY";
    public static final String PREPARING = "PREPARING";
    public static final String PARTIAL = "PARTIAL";
    public static final String NO_DATA = "NO_DATA";
    public static final String INSUFFICIENT_DATA = "INSUFFICIENT_DATA";
    public static final String NOT_SUPPORTED = "NOT_SUPPORTED";
    public static final String FAILED = "FAILED";

    public static ComputeState ready() {
        return new ComputeState(READY, "NONE", null);
    }

    /** C가 지금 계산 중이다. {@code Retry-After}를 그대로 넘겨 폴링 간격을 화면이 정한다. */
    public static ComputeState computing(Integer retryAfterSec) {
        return new ComputeState(PREPARING, "COMPUTING", retryAfterSec);
    }

    /** 결과가 아직 없다. 분석은 끝났지만 C 계산이 아직 돌지 않은 상태다. */
    public static ComputeState preparing(String reason) {
        return new ComputeState(PREPARING, reason, null);
    }

    /** 분석한 적이 없다. 계산 대기와 구분해야 화면이 "분석 시작"을 권할 수 있다. */
    public static ComputeState notAnalyzed() {
        return new ComputeState(NO_DATA, "INSUFFICIENT_EVIDENCE", null);
    }

    public static ComputeState failed(String reason) {
        return new ComputeState(FAILED, reason, null);
    }

    public static ComputeState notSupported(String reason) {
        return new ComputeState(NOT_SUPPORTED, reason, null);
    }

    /**
     * RECOMMENDATION Snapshot의 계산 상태를 화면 상태로 옮긴다.
     *
     * <p>{@code NO_CANDIDATES}는 정상 결과다. 추천할 것이 없다는 사실 자체가 답이므로
     * 오류나 준비 중으로 만들지 않고 {@code READY}에 사유만 붙인다.</p>
     */
    public static ComputeState ofRecommendation(String status) {
        if (status == null) {
            return ready();
        }
        return switch (status) {
            case "READY" -> ready();
            case "NO_CANDIDATES" -> new ComputeState(READY, "NO_CANDIDATES", null);
            case "PARTIAL" -> new ComputeState(PARTIAL, "PARTIAL_ANALYSIS", null);
            case "INSUFFICIENT_DATA" ->
                    new ComputeState(INSUFFICIENT_DATA, "INSUFFICIENT_JOB_SAMPLE", null);
            case "INSUFFICIENT_EVIDENCE" ->
                    new ComputeState(INSUFFICIENT_DATA, "INSUFFICIENT_EVIDENCE", null);
            default -> ready();
        };
    }

    /**
     * Trend Snapshot의 상태를 화면 상태로 옮긴다.
     *
     * <p>출처 하나가 비어도 나머지는 정상이다. 그래서 이 상태는 응답 전체가 아니라 출처
     * 카드 하나에 붙는다.</p>
     */
    public static ComputeState ofTrend(String status) {
        if (status == null) {
            return new ComputeState(NO_DATA, "TREND_NOT_PREPARED", null);
        }
        return switch (status) {
            case "READY" -> ready();
            case "PREPARING" -> computing(null);
            case "INSUFFICIENT_DATA" ->
                    new ComputeState(INSUFFICIENT_DATA, "INSUFFICIENT_TREND_SAMPLE", null);
            case "NOT_SUPPORTED" -> notSupported("TREND_NOT_SUPPORTED");
            case "FAILED" -> failed("TREND_FAILED");
            default -> new ComputeState(NO_DATA, "TREND_NOT_PREPARED", null);
        };
    }

    public boolean isReady() {
        return READY.equals(dataStatus) || PARTIAL.equals(dataStatus);
    }
}
