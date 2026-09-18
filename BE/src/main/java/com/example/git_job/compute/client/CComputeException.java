package com.example.git_job.compute.client;

import lombok.Getter;

/**
 * C 호출이 결과를 주지 못했을 때 (S15P21E102-279).
 *
 * <p>{@code CustomException}이 아니다. C의 상태 대부분은 요청 실패가 아니라 <em>화면이
 * 표시해야 하는 상태</em>이고(계산 중·미준비·표본 부족), 공개 API로 어떻게 바꿀지는
 * 기능마다 다르다. 이 예외를 그대로 사용자에게 흘려보내면 전부 500이 된다 — 그것이
 * 인수 조건에서 금지한 "C 장애를 무조건 500으로 뭉개는" 동작이다.</p>
 *
 * <p>서비스 층이 {@link #status}로 분기해 공개 응답의 {@code dataStatus}나
 * {@code ErrorCode}로 바꾼다. 변환표는 {@code docs/be/c-compute-public-api.md} §2-E.</p>
 */
@Getter
public class CComputeException extends RuntimeException {

    private final CComputeStatus status;

    /** C가 보낸 {@code code} 문자열. 연결 실패처럼 응답이 없으면 {@code null}. */
    private final String code;

    /** 202의 {@code Retry-After} 초. 없으면 {@code null}. */
    private final Integer retryAfterSec;

    public CComputeException(CComputeStatus status, String code, Integer retryAfterSec,
                             String message) {
        super(message);
        this.status = status;
        this.code = code;
        this.retryAfterSec = retryAfterSec;
    }

    public CComputeException(CComputeStatus status, String code, String message, Throwable cause) {
        super(message, cause);
        this.status = status;
        this.code = code;
        this.retryAfterSec = null;
    }

    /** 같은 요청으로 재시도하면 결과가 나올 수 있는 상태인지. */
    public boolean isRetryable() {
        return status == CComputeStatus.PREPARING
                || status == CComputeStatus.COMPUTE_FAILED
                || status == CComputeStatus.TIMEOUT
                || status == CComputeStatus.UNAVAILABLE;
    }

    public static CComputeException notConfigured(String detail) {
        return new CComputeException(CComputeStatus.UNAVAILABLE, null, null,
                "C Compute가 설정되지 않았습니다: " + detail);
    }

    public static CComputeException unreachable(String path, Throwable cause) {
        return new CComputeException(CComputeStatus.UNAVAILABLE, null,
                "C Compute에 연결할 수 없습니다: " + path, cause);
    }

    public static CComputeException timeout(String path, Throwable cause) {
        return new CComputeException(CComputeStatus.TIMEOUT, "C_COMPUTE_TIMEOUT",
                "C Compute 응답 시간이 초과되었습니다: " + path, cause);
    }

    /** 응답은 왔는데 봉투가 아니거나 본문을 해석할 수 없다. 버전 불일치일 수 있다. */
    public static CComputeException invalidResponse(String path, Throwable cause) {
        return new CComputeException(CComputeStatus.UNAVAILABLE, null,
                "C Compute 응답을 해석할 수 없습니다: " + path, cause);
    }
}
