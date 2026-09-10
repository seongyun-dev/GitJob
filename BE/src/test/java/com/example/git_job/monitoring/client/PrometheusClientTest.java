package com.example.git_job.monitoring.client;

import static java.nio.charset.StandardCharsets.UTF_8;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.example.git_job.monitoring.config.MonitoringProperties;
import com.example.git_job.monitoring.controller.dto.PrometheusState;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.URLDecoder;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Prometheus 응답을 실제 HTTP로 받아 해석하는 부분을 고정한다 (S15P21E102-209).
 *
 * <p>루프백에 세운 stub 서버를 쓴다. 실제 Prometheus를 부르지 않으므로 단위 테스트이고
 * (PROJECT_GUIDE 10.9), 그러면서도 URL 인코딩·JSON 파싱·연결 실패까지 실제 경로로
 * 지나간다. Mock transport로는 PromQL의 중괄호가 URI 템플릿으로 삼켜지는 사고를 잡을 수
 * 없어서 이렇게 했다.</p>
 *
 * <p>실제 Prometheus 응답에 대한 검증은 이 테스트가 아니라 Runtime 검증에서 한다.</p>
 */
class PrometheusClientTest {

    private HttpServer server;
    private final Map<String, String> bodies = new HashMap<>();
    private final AtomicReference<String> lastQuery = new AtomicReference<>();
    private final AtomicReference<Map<String, String>> lastParams = new AtomicReference<>(Map.of());

    @BeforeEach
    void startStubServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/v1/", this::respond);
        server.start();
    }

    @AfterEach
    void stopStubServer() {
        server.stop(0);
    }

    private void respond(HttpExchange exchange) throws IOException {
        Map<String, String> params = parseQuery(exchange.getRequestURI().getRawQuery());
        lastParams.set(params);
        lastQuery.set(params.get("query"));

        String path = exchange.getRequestURI().getPath();
        String body = bodies.getOrDefault(path, "{\"status\":\"success\",\"data\":{}}");
        byte[] bytes = body.getBytes(UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    private static Map<String, String> parseQuery(String rawQuery) {
        Map<String, String> params = new HashMap<>();
        if (rawQuery == null) {
            return params;
        }
        for (String pair : rawQuery.split("&")) {
            int eq = pair.indexOf('=');
            if (eq > 0) {
                params.put(
                        URLDecoder.decode(pair.substring(0, eq), UTF_8),
                        URLDecoder.decode(pair.substring(eq + 1), UTF_8));
            }
        }
        return params;
    }

    private PrometheusClient clientFor(String baseUrl) {
        return new PrometheusClient(new MonitoringProperties(
                baseUrl, Duration.ofSeconds(2), Duration.ofSeconds(15), "gitjob", "", ""));
    }

    private PrometheusClient client() {
        return clientFor("http://127.0.0.1:" + server.getAddress().getPort());
    }

    @Test
    @DisplayName("PromQL의 중괄호가 URI 템플릿으로 삼켜지지 않고 그대로 전달된다")
    void thePromQlSelectorSurvivesTheTrip() {
        String query = "up{job=\"node-exporter\",cluster=\"gitjob\"}";
        bodies.put("/api/v1/query", """
                {"status":"success","data":{"resultType":"vector","result":[]}}""");

        client().instant(query);

        assertThat(lastQuery.get()).isEqualTo(query);
    }

    @Test
    @DisplayName("instant 응답의 라벨과 값을 그대로 읽는다")
    void instantSamplesKeepTheirLabelsAndValue() {
        bodies.put("/api/v1/query", """
                {"status":"success","data":{"resultType":"vector","result":[
                  {"metric":{"instance":"10.0.0.1:9100","role":"service"},
                   "value":[1757480000.5,"23.4"]}
                ]}}""");

        List<PrometheusClient.Sample> samples = client().instant("up");

        assertThat(samples).hasSize(1);
        assertThat(samples.get(0).label("instance")).isEqualTo("10.0.0.1:9100");
        assertThat(samples.get(0).label("role")).isEqualTo("service");
        assertThat(samples.get(0).value()).isEqualTo(23.4);
        // 없는 라벨은 예외가 아니라 빈 문자열이다. 상위에서 null로 바꾼다.
        assertThat(samples.get(0).label("node")).isEmpty();
    }

    @Test
    @DisplayName("NaN과 무한 샘플은 0으로 바꾸지 않고 버린다")
    void nonFiniteSamplesAreDroppedNotZeroed() {
        bodies.put("/api/v1/query", """
                {"status":"success","data":{"resultType":"vector","result":[
                  {"metric":{"instance":"a"},"value":[1757480000,"NaN"]},
                  {"metric":{"instance":"b"},"value":[1757480000,"+Inf"]},
                  {"metric":{"instance":"c"},"value":[1757480000,"not-a-number"]},
                  {"metric":{"instance":"d"},"value":[1757480000,"7.5"]}
                ]}}""");

        List<PrometheusClient.Sample> samples = client().instant("up");

        assertThat(samples).hasSize(1);
        assertThat(samples.get(0).label("instance")).isEqualTo("d");
    }

    @Test
    @DisplayName("range 응답은 시계열의 시각과 값을 보존한다")
    void rangeSeriesKeepTimestamps() {
        bodies.put("/api/v1/query_range", """
                {"status":"success","data":{"resultType":"matrix","result":[
                  {"metric":{"instance":"10.0.0.1:9100"},
                   "values":[[1757480000,"20.0"],[1757480300,"21.5"]]}
                ]}}""");

        List<PrometheusClient.Series> series = client().range(
                "cpu",
                Instant.parse("2026-09-10T05:00:00Z"),
                Instant.parse("2026-09-10T06:00:00Z"),
                Duration.ofMinutes(5));

        assertThat(series).hasSize(1);
        assertThat(series.get(0).points()).containsExactly(
                new PrometheusClient.Point(Instant.ofEpochMilli(1757480000000L), 20.0),
                new PrometheusClient.Point(Instant.ofEpochMilli(1757480300000L), 21.5));
        // 범위와 step은 호출부가 정한 값이 그대로 나가야 한다.
        assertThat(lastParams.get().get("step")).isEqualTo("300s");
        assertThat(lastParams.get().get("start")).isEqualTo("1789016400");
        assertThat(lastParams.get().get("end")).isEqualTo("1789020000");
    }

    @Test
    @DisplayName("target은 DOWN까지 분모에 세어야 장애가 정상으로 보이지 않는다")
    void downTargetsStillCountTowardTheTotal() {
        bodies.put("/api/v1/targets", """
                {"status":"success","data":{"activeTargets":[
                  {"health":"up"},{"health":"up"},{"health":"down"}
                ]}}""");

        PrometheusClient.TargetHealth health = client().targets();

        assertThat(health.up()).isEqualTo(2);
        assertThat(health.total()).isEqualTo(3);
    }

    @Test
    @DisplayName("success가 아닌 응답은 INVALID_RESPONSE로 구분한다")
    void aNonSuccessBodyIsAnInvalidResponse() {
        bodies.put("/api/v1/query", """
                {"status":"error","errorType":"bad_data","error":"parse error"}""");

        assertThatThrownBy(() -> client().instant("up"))
                .isInstanceOf(PrometheusUnavailableException.class)
                .extracting(e -> ((PrometheusUnavailableException) e).getState())
                .isEqualTo(PrometheusState.INVALID_RESPONSE);
    }

    @Test
    @DisplayName("닿지 않으면 UNREACHABLE이고, 주소는 메시지에 싣지 않는다")
    void anUnreachableServerIsReportedWithoutLeakingTheAddress() throws IOException {
        int closedPort;
        try (ServerSocket socket = new ServerSocket(0)) {
            closedPort = socket.getLocalPort();
        }
        PrometheusClient client = clientFor("http://127.0.0.1:" + closedPort);

        assertThatThrownBy(() -> client.instant("up"))
                .isInstanceOf(PrometheusUnavailableException.class)
                .extracting(e -> ((PrometheusUnavailableException) e).getState())
                .isEqualTo(PrometheusState.UNREACHABLE);

        assertThatThrownBy(() -> client.instant("up"))
                .hasMessageNotContaining("127.0.0.1")
                .hasMessageNotContaining(String.valueOf(closedPort));
    }

    @Test
    @DisplayName("주소가 없으면 호출하지 않고 NOT_CONFIGURED로 멈춘다")
    void withoutAnAddressTheClientRefusesInsteadOfReturningZero() {
        PrometheusClient client = clientFor("");

        assertThatThrownBy(() -> client.instant("up"))
                .isInstanceOf(PrometheusUnavailableException.class)
                .extracting(e -> ((PrometheusUnavailableException) e).getState())
                .isEqualTo(PrometheusState.NOT_CONFIGURED);
    }
}
