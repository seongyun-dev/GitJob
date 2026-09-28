package com.example.git_job.monitoring.config;

import java.time.Duration;
import java.util.regex.Pattern;
import lombok.Getter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Admin Monitoring 설정 (S15P21E102-209).
 *
 * <p>Prometheus와 Grafana는 관리자망(Tailscale)에만 열려 있다. 주소를 코드에 적지 않고
 * 설정으로만 주입하는 이유는 환경마다 다르고 공개 번들에 들어가면 안 되기 때문이다.
 * FE는 이 값을 직접 읽지 않고 overview 응답의 {@code links}로만 받는다.</p>
 *
 * <p>{@code base-url}이 비어 있으면 Prometheus를 호출하지 않는다. 미설정과 장애를 같은
 * 경로로 처리해 화면이 둘 다 구분 가능한 "연결되지 않음"으로 그릴 수 있게 한다.</p>
 */
@Getter
@Component
public class MonitoringProperties {

    /**
     * cluster 값은 PromQL 문자열에 라벨 매처로 들어간다. 설정에서 오는 값이지만
     * 쿼리에 섞이는 이상 형식을 좁혀 둔다. 셀렉터를 깨뜨릴 수 있는 문자를 막는 것이
     * 목적이며, 사용자 입력은 애초에 이 자리에 오지 않는다.
     */
    private static final Pattern LABEL_VALUE = Pattern.compile("[A-Za-z0-9_.:-]+");

    private final String prometheusBaseUrl;
    private final Duration prometheusTimeout;
    /**
     * 화면이 "15초 간격으로 수집합니다"를 표시하는 데 쓴다. Prometheus의
     * {@code global.scrape_interval}과 같은 값이어야 하며, 코드에 숫자로 박지 않는 이유는
     * 그 설정이 {@code Infra/monitoring/prometheus/prometheus.yml}에 있기 때문이다.
     */
    private final Duration prometheusScrapeInterval;
    private final String cluster;
    private final String grafanaUrl;
    private final String prometheusUrl;

    public MonitoringProperties(
            @Value("${gitjob.monitoring.prometheus.base-url:}") String prometheusBaseUrl,
            @Value("${gitjob.monitoring.prometheus.timeout:3s}") Duration prometheusTimeout,
            @Value("${gitjob.monitoring.prometheus.scrape-interval:15s}") Duration prometheusScrapeInterval,
            @Value("${gitjob.monitoring.prometheus.cluster:gitjob}") String cluster,
            @Value("${gitjob.monitoring.links.grafana-url:}") String grafanaUrl,
            @Value("${gitjob.monitoring.links.prometheus-url:}") String prometheusUrl
    ) {
        if (!LABEL_VALUE.matcher(cluster).matches()) {
            throw new IllegalArgumentException("gitjob.monitoring.prometheus.cluster 형식이 올바르지 않습니다.");
        }
        this.prometheusBaseUrl = prometheusBaseUrl.strip();
        this.prometheusTimeout = prometheusTimeout;
        this.prometheusScrapeInterval = prometheusScrapeInterval;
        this.cluster = cluster;
        this.grafanaUrl = grafanaUrl.strip();
        this.prometheusUrl = prometheusUrl.strip();
    }

    /** 주소가 없으면 호출하지 않는다. 빈 값을 baseUrl로 준 RestClient는 런타임에야 터진다. */
    public boolean isPrometheusConfigured() {
        return !prometheusBaseUrl.isEmpty();
    }

    /**
     * 화면의 Quick Access가 쓰는 링크. 미설정이면 문자열이 아니라 {@code null}을 준다.
     * 빈 문자열을 내려보내면 FE가 눌러도 아무 일도 없는 링크를 그린다.
     */
    public String grafanaLinkOrNull() {
        return grafanaUrl.isEmpty() ? null : grafanaUrl;
    }

    public String prometheusLinkOrNull() {
        return prometheusUrl.isEmpty() ? null : prometheusUrl;
    }
}
