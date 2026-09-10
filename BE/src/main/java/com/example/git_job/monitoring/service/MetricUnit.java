package com.example.git_job.monitoring.service;

/**
 * 시계열 값의 단위 (S15P21E102-209).
 *
 * <p>화면이 축과 서식을 고르는 데 쓴다. 백분율에 "MB/s"를 붙이거나 바이트를 100에서
 * 잘라내는 실수를 응답 단계에서 막는다.</p>
 */
public enum MetricUnit {
    PERCENT,
    BYTES_PER_SECOND
}
