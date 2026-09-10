package com.example.git_job.monitoring.client;

import com.example.git_job.monitoring.controller.dto.PrometheusState;
import lombok.Getter;

/**
 * Prometheus에서 값을 얻지 못했을 때 (S15P21E102-209).
 *
 * <p>이 예외는 {@code CustomException}이 아니다. 모니터링 화면에서 Prometheus 장애는
 * 요청 실패가 아니라 <em>보여줘야 하는 상태</em>이기 때문이다. 서비스가 이 예외를 잡아
 * 응답의 상태 필드로 바꾸며, 그래야 화면이 "모니터링이 끊겼다"와 "서버가 죽었다"를
 * 구분해 그릴 수 있다.</p>
 *
 * <p>{@link #state}를 싣는 이유는 실패를 한 덩어리로 뭉개면 운영자가 어디를 고쳐야 할지
 * 알 수 없기 때문이다. 닿지 않는 것과 응답이 이상한 것은 원인과 담당자가 다르다.</p>
 */
@Getter
public class PrometheusUnavailableException extends RuntimeException {

    /** {@link PrometheusState#UNREACHABLE} 또는 {@link PrometheusState#INVALID_RESPONSE}. */
    private final PrometheusState state;

    public PrometheusUnavailableException(PrometheusState state, String message) {
        super(message);
        this.state = state;
    }

    public PrometheusUnavailableException(PrometheusState state, String message, Throwable cause) {
        super(message, cause);
        this.state = state;
    }

    /** 주소는 있는데 닿지 않는다. 관리자망 단절이거나 Prometheus가 내려갔다. */
    public static PrometheusUnavailableException unreachable(String message, Throwable cause) {
        return new PrometheusUnavailableException(PrometheusState.UNREACHABLE, message, cause);
    }

    /** 닿았는데 응답을 해석할 수 없다. 버전 불일치나 잘못된 주소일 수 있다. */
    public static PrometheusUnavailableException invalidResponse(String message) {
        return new PrometheusUnavailableException(PrometheusState.INVALID_RESPONSE, message);
    }
}
