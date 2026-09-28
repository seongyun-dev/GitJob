package com.example.git_job.monitoring.controller.dto;

/**
 * 모니터링 데이터 출처의 상태 (S15P21E102-209).
 *
 * <p>실패를 한 값으로 뭉개지 않기 위해 있는 타입이다. 운영자가 화면에서 답을 얻어야 하는
 * 질문이 서로 다르다.</p>
 *
 * <ul>
 *   <li>{@link #NOT_CONFIGURED} — 이 배포에 Prometheus 주소가 없다. 인프라 설정 문제이고,
 *       서버가 죽은 것이 아니다. 고칠 사람은 배포 담당자다.</li>
 *   <li>{@link #UNREACHABLE} — 주소는 있는데 닿지 않는다. 관리자망이 끊겼거나 Prometheus가
 *       내려갔다. 고칠 사람은 운영자다.</li>
 *   <li>{@link #INVALID_RESPONSE} — 닿았는데 응답을 해석할 수 없다. 버전 불일치나 잘못된
 *       주소를 가리킬 수 있다.</li>
 * </ul>
 *
 * <p>세 경우 모두 서버 지표는 알 수 없는 상태이지 "정상이며 0"이 아니다. 화면은 이 값으로
 * 무엇이 고장났는지를 구분해 보여준다.</p>
 */
public enum PrometheusState {
    CONNECTED,
    NOT_CONFIGURED,
    UNREACHABLE,
    INVALID_RESPONSE
}
