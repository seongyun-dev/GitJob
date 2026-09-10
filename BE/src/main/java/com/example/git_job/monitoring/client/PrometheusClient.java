package com.example.git_job.monitoring.client;

import static java.nio.charset.StandardCharsets.UTF_8;

import com.example.git_job.monitoring.client.dto.PromQueryResponse;
import com.example.git_job.monitoring.client.dto.PromTargetsResponse;
import com.example.git_job.monitoring.config.MonitoringProperties;
import com.example.git_job.monitoring.controller.dto.PrometheusState;
import java.net.URI;
import java.net.URLEncoder;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * Prometheus HTTP API의 읽기 전용 클라이언트 (S15P21E102-209).
 *
 * <p>호출하는 것은 {@code /api/v1/query}, {@code /api/v1/query_range},
 * {@code /api/v1/targets} 세 개뿐이다. Prometheus admin·쓰기 계열은 호출하지 않는다.
 * 모니터링 화면이 운영 시계열을 지울 수 있는 경로를 아예 갖지 않게 하려는 것이다.</p>
 *
 * <p>PromQL은 이 애플리케이션이 만든 문자열만 보낸다({@code MonitoringQueries}).
 * 클라이언트가 준 질의를 그대로 전달하는 통로는 두지 않는다. 두면 이 엔드포인트가
 * 관리자망 Prometheus에 대한 임의 질의 창구가 된다.</p>
 *
 * <p>URI를 {@code UriBuilder} 대신 직접 인코딩해 만든다. PromQL에는
 * {@code node_cpu_seconds_total{cluster="gitjob"}}처럼 중괄호가 들어가고, Spring의 기본
 * URI 빌더는 그것을 URI 템플릿 변수로 해석해 셀렉터를 삼킨다.</p>
 *
 * <p>타임아웃을 명시하는 이유는 관리자망이 끊겼을 때 화면이 무한정 기다리지 않게 하려는
 * 것이다. 지정하지 않으면 OS 소켓 타임아웃까지 매달린다.</p>
 */
@Component
public class PrometheusClient {

    private final String baseUrl;
    private final RestClient restClient;

    public PrometheusClient(MonitoringProperties properties) {
        this.baseUrl = trimTrailingSlash(properties.getPrometheusBaseUrl());
        this.restClient = properties.isPrometheusConfigured()
                ? RestClient.builder()
                        .requestFactory(requestFactory(properties.getPrometheusTimeout()))
                        .build()
                : null;
    }

    private static String trimTrailingSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }

    private static SimpleClientHttpRequestFactory requestFactory(Duration timeout) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(timeout);
        factory.setReadTimeout(timeout);
        return factory;
    }

    /** 한 시점의 값. instant query 결과에서 라벨과 값만 남긴다. */
    public record Sample(Map<String, String> labels, double value) {
        public String label(String name) {
            return labels.getOrDefault(name, "");
        }
    }

    /** 한 시계열. */
    public record Series(Map<String, String> labels, List<Point> points) {
        public String label(String name) {
            return labels.getOrDefault(name, "");
        }
    }

    public record Point(Instant at, double value) {
    }

    /** scrape target 건강 상태. */
    public record TargetHealth(int up, int total) {
    }

    /**
     * instant query.
     *
     * <p>값이 {@code NaN}이나 무한이면 그 샘플을 버린다. 그런 값은 화면에 숫자로 표시할 수
     * 없고, 0으로 바꾸면 "측정했더니 0이었다"는 거짓이 된다. 버려진 자리는 상위에서
     * 값 없음으로 다뤄진다.</p>
     */
    public List<Sample> instant(String query) {
        URI uri = URI.create(baseUrl + "/api/v1/query?query=" + encode(query));
        PromQueryResponse response = get(uri, PromQueryResponse.class);
        if (!response.isSuccess()) {
            throw PrometheusUnavailableException.invalidResponse(
                    "Prometheus instant query가 성공 상태를 반환하지 않았습니다.");
        }

        List<Sample> samples = new ArrayList<>();
        for (PromQueryResponse.Result result : response.results()) {
            Double value = parseSampleValue(result.value());
            if (value != null) {
                samples.add(new Sample(Map.copyOf(result.labels()), value));
            }
        }
        return List.copyOf(samples);
    }

    /**
     * range query. 범위와 step은 호출부가 정한다. 화면이 고른 범위를 여기서 다시
     * 해석하면 같은 규칙이 두 곳에 생긴다.
     */
    public List<Series> range(String query, Instant start, Instant end, Duration step) {
        URI uri = URI.create(baseUrl + "/api/v1/query_range"
                + "?query=" + encode(query)
                + "&start=" + start.getEpochSecond()
                + "&end=" + end.getEpochSecond()
                + "&step=" + step.toSeconds() + "s");
        PromQueryResponse response = get(uri, PromQueryResponse.class);
        if (!response.isSuccess()) {
            throw PrometheusUnavailableException.invalidResponse(
                    "Prometheus range query가 성공 상태를 반환하지 않았습니다.");
        }

        List<Series> series = new ArrayList<>();
        for (PromQueryResponse.Result result : response.results()) {
            List<Point> points = new ArrayList<>();
            List<List<Object>> rows = result.values() == null ? List.of() : result.values();
            for (List<Object> row : rows) {
                Double value = parseSampleValue(row);
                if (value != null) {
                    points.add(new Point(parseTimestamp(row), value));
                }
            }
            series.add(new Series(Map.copyOf(result.labels()), List.copyOf(points)));
        }
        return List.copyOf(series);
    }

    /**
     * active target의 UP 개수.
     *
     * <p>{@code up} 시계열을 세지 않는다. scrape가 완전히 실패한 target은 시계열이 없어
     * 셈에서 빠지고, 그러면 분모까지 줄어 "2 / 2 UP"처럼 장애가 정상으로 보인다.</p>
     */
    public TargetHealth targets() {
        URI uri = URI.create(baseUrl + "/api/v1/targets?state=active");
        PromTargetsResponse response = get(uri, PromTargetsResponse.class);
        if (!response.isSuccess()) {
            throw PrometheusUnavailableException.invalidResponse(
                    "Prometheus targets 조회가 성공 상태를 반환하지 않았습니다.");
        }

        List<PromTargetsResponse.ActiveTarget> targets = response.activeTargets();
        int up = (int) targets.stream().filter(PromTargetsResponse.ActiveTarget::isUp).count();
        return new TargetHealth(up, targets.size());
    }

    private <T> T get(URI uri, Class<T> type) {
        if (restClient == null) {
            // 서비스가 먼저 걸러내지만, 설정 없이 호출되면 조용히 0을 만들지 않고 여기서 멈춘다.
            throw new PrometheusUnavailableException(
                    PrometheusState.NOT_CONFIGURED, "Prometheus 주소가 설정되지 않았습니다.");
        }
        try {
            T body = restClient.get().uri(uri).retrieve().body(type);
            if (body == null) {
                throw PrometheusUnavailableException.invalidResponse("Prometheus 응답 본문이 비어 있습니다.");
            }
            return body;
        } catch (RestClientException e) {
            // 원문에는 관리자망 주소가 섞여 나올 수 있어 그대로 전파하지 않는다.
            throw PrometheusUnavailableException.unreachable("Prometheus에 연결할 수 없습니다.", e);
        }
    }

    /** 폼 인코딩. 공백이 {@code +}가 되는데 query string에서는 그것이 맞다. */
    private static String encode(String value) {
        return URLEncoder.encode(value, UTF_8);
    }

    /** {@code [timestamp, "value"]}의 두 번째 원소. 파싱 불가·NaN·무한이면 null. */
    private static Double parseSampleValue(List<Object> sample) {
        if (sample == null || sample.size() < 2 || sample.get(1) == null) {
            return null;
        }
        try {
            double value = Double.parseDouble(sample.get(1).toString());
            return Double.isFinite(value) ? value : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Instant parseTimestamp(List<Object> sample) {
        try {
            double epochSeconds = Double.parseDouble(sample.get(0).toString());
            return Instant.ofEpochMilli(Math.round(epochSeconds * 1000));
        } catch (NumberFormatException e) {
            throw PrometheusUnavailableException.invalidResponse(
                    "Prometheus 샘플의 타임스탬프를 읽을 수 없습니다.");
        }
    }
}
