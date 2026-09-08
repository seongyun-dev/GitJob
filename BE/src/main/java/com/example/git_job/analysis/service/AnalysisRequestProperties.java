package com.example.git_job.analysis.service;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 서버가 분석 요청에 채워 넣는 값. 클라이언트가 보낸 값을 쓰지 않는다.
 *
 * @param registryVersion 판정 기준 Registry 버전. 요청 시점 값을 이벤트에 박아
 *                        두어야 나중에 Registry가 바뀌어도 재현·replay할 수 있다
 * @param pollAfterSeconds 202 응답에 실어 보낼 재조회 권장 간격
 */
@ConfigurationProperties("gitjob.analysis.request")
public record AnalysisRequestProperties(
        @DefaultValue("technology-registry/v1") String registryVersion,
        @DefaultValue("2") int pollAfterSeconds
) {

    public AnalysisRequestProperties {
        if (registryVersion == null || registryVersion.isBlank()) {
            throw new IllegalArgumentException("registryVersion must be configured");
        }
        if (pollAfterSeconds < 1) {
            throw new IllegalArgumentException("pollAfterSeconds must be at least 1");
        }
    }
}
