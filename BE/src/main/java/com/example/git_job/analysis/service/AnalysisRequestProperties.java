package com.example.git_job.analysis.service;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 서버가 분석 요청에 채워 넣는 값. 클라이언트가 보낸 값을 쓰지 않는다.
 *
 * <p>Registry 버전은 여기 없다. 설정으로 두면 실재하지 않는 버전이 기본값으로
 * 앉을 수 있고, 실제로 그랬다. {@link CurrentRegistryVersion}이 C Registry의
 * 활성 alias를 DB에서 읽는다.</p>
 *
 * @param pollAfterSeconds 202 응답에 실어 보낼 재조회 권장 간격
 */
@ConfigurationProperties("gitjob.analysis.request")
public record AnalysisRequestProperties(
        @DefaultValue("2") int pollAfterSeconds
) {

    public AnalysisRequestProperties {
        if (pollAfterSeconds < 1) {
            throw new IllegalArgumentException("pollAfterSeconds must be at least 1");
        }
    }
}
