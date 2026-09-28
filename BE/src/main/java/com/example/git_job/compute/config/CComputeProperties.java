package com.example.git_job.compute.config;

import java.time.Duration;
import lombok.Getter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * C Compute 내부 API 접속 설정 (S15P21E102-279).
 *
 * <p>C Worker의 8080은 데이터 서버의 Tailscale 주소에만 게시된다. 주소도 토큰도 코드에
 * 적지 않고 서버 설정으로만 주입하는 이유는 둘 다 환경마다 다르고, 무엇보다
 * <em>브라우저에 닿으면 안 되기</em> 때문이다. 이 값은 FE 번들에도, 응답 본문에도,
 * 로그에도 들어가지 않는다.</p>
 *
 * <p>{@code base-url}이나 token이 비어 있으면 C를 호출하지 않는다. 미설정과 장애를 같은
 * 경로로 다루되({@code CComputeStatus#UNAVAILABLE}) 로그 메시지로 구분한다. 빈 주소로
 * 만든 RestClient는 첫 호출에서야 터지고, 그때는 원인이 설정이라는 사실이 스택트레이스에
 * 남지 않는다.</p>
 *
 * <p>timeout을 명시하는 이유는 관리자망이 끊겼을 때 사용자 요청 스레드가 OS 소켓
 * 타임아웃까지 매달리지 않게 하려는 것이다. C의 계산 자체는 비동기가 아니라 동기
 * 응답이므로 분석 완료 전달({@code write-timeout})은 조회보다 길게 둔다.</p>
 */
@Getter
@Component
public class CComputeProperties {

    private final String baseUrl;
    private final String token;
    /** 조회 계열 timeout. 화면 요청이 이 시간 이상 매달리지 않는다. */
    private final Duration readTimeout;
    /** 분석 완료 전달처럼 C가 실제로 계산하는 호출. 조회보다 길다. */
    private final Duration writeTimeout;

    public CComputeProperties(
            @Value("${gitjob.compute.base-url:}") String baseUrl,
            @Value("${gitjob.compute.token:}") String token,
            @Value("${gitjob.compute.read-timeout:5s}") Duration readTimeout,
            @Value("${gitjob.compute.write-timeout:30s}") Duration writeTimeout
    ) {
        this.baseUrl = trimTrailingSlash(baseUrl.strip());
        this.token = token.strip();
        this.readTimeout = readTimeout;
        this.writeTimeout = writeTimeout;
    }

    private static String trimTrailingSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }

    /**
     * 주소와 토큰이 모두 있어야 설정된 것으로 본다.
     *
     * <p>토큰 없이 주소만 있으면 모든 호출이 401이 되는데, 그 401은 C 장애가 아니라 배포
     * 설정 누락이다. 호출하기 전에 구분하는 편이 운영자에게 정확하다.</p>
     */
    public boolean isConfigured() {
        return !baseUrl.isEmpty() && !token.isEmpty();
    }

    /**
     * 설정 상태를 로그에 남길 때 쓰는 문구. <strong>토큰 값은 절대 넣지 않는다.</strong>
     */
    public String describeConfiguration() {
        if (baseUrl.isEmpty() && token.isEmpty()) {
            return "gitjob.compute.base-url, gitjob.compute.token 모두 미설정";
        }
        if (baseUrl.isEmpty()) {
            return "gitjob.compute.base-url 미설정";
        }
        if (token.isEmpty()) {
            return "gitjob.compute.token 미설정";
        }
        return "configured";
    }
}
