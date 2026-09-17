package com.example.git_job.compute.client;

import static java.nio.charset.StandardCharsets.UTF_8;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.example.git_job.compute.client.dto.CSnapshot;
import com.example.git_job.compute.client.dto.CTrend;
import com.example.git_job.compute.config.CComputeProperties;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.assertj.core.api.InstanceOfAssertFactories;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * C 응답을 실제 HTTP로 받아 상태로 바꾸는 부분을 고정한다 (S15P21E102-279).
 *
 * <p>루프백에 세운 stub 서버를 쓴다. 실제 C Worker를 부르지 않으므로 단위 테스트이고,
 * 그러면서도 Bearer 헤더·snake_case 변환·202·오류 코드 해석이 실제 경로로 지나간다.
 * 이 클래스가 지키는 것은 "C 장애를 한 덩어리로 뭉개지 않는다"는 인수 조건이다 — 404
 * 하나에도 기다려야 할 상태와 404를 보여야 할 상태가 같이 들어 있다.</p>
 *
 * <p>운영 C와의 실제 정합성은 이 테스트가 아니라 Runtime 검증에서 확인한다.</p>
 */
class CComputeClientTest {

    private static final String TOKEN = "test-token-0123456789abcdef0123456789";

    private HttpServer server;
    private final Map<String, Response> responses = new HashMap<>();
    private final AtomicReference<String> lastAuthorization = new AtomicReference<>();
    private final AtomicReference<String> lastQuery = new AtomicReference<>();
    private final AtomicReference<String> lastBody = new AtomicReference<>();
    private final AtomicInteger calls = new AtomicInteger();

    private record Response(int status, String body, String retryAfter) {
        static Response of(int status, String body) {
            return new Response(status, body, null);
        }
    }

    @BeforeEach
    void startStubServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", this::respond);
        server.start();
    }

    @AfterEach
    void stopStubServer() {
        server.stop(0);
    }

    private void respond(HttpExchange exchange) throws IOException {
        calls.incrementAndGet();
        lastAuthorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
        lastQuery.set(exchange.getRequestURI().getRawQuery());
        lastBody.set(new String(exchange.getRequestBody().readAllBytes(), UTF_8));

        Response response = responses.getOrDefault(exchange.getRequestURI().getPath(),
                Response.of(404, "{\"code\":\"NOT_STUBBED\",\"message\":\"NOT_STUBBED\"}"));
        byte[] body = response.body().getBytes(UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        if (response.retryAfter() != null) {
            exchange.getResponseHeaders().add("Retry-After", response.retryAfter());
        }
        exchange.sendResponseHeaders(response.status(), body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
    }

    private CComputeClient client() {
        return new CComputeClient(new CComputeProperties(
                "http://127.0.0.1:" + server.getAddress().getPort(),
                TOKEN, Duration.ofSeconds(2), Duration.ofSeconds(2)));
    }

    @Test
    @DisplayName("200 응답은 봉투를 벗기고 snake_case를 필드로 옮긴다")
    void unwrapsEnvelope() {
        responses.put("/ready", Response.of(200,
                "{\"message\":\"C compute ready\","
                        + "\"data\":{\"status\":\"READY\",\"registry_version\":\"registry-20260911.4\"}}"));

        CComputeClient.Ready ready = client().ready();

        assertThat(ready.status()).isEqualTo("READY");
        assertThat(ready.registryVersion()).isEqualTo("registry-20260911.4");
    }

    @Test
    @DisplayName("수요 Snapshot의 입력·비교·엄격 분모를 서로 다른 필드로 읽는다")
    void readsDemandPopulationFunnel() {
        responses.put("/internal/v1/c/snapshots/snapshot-1", Response.of(200,
                "{\"message\":\"ok\",\"data\":{"
                        + "\"snapshot_id\":\"snapshot-1\","
                        + "\"kind\":\"RECOMMENDATION\","
                        + "\"payload\":{\"current_count\":0,\"demand\":{"
                        + "\"cohort_id\":\"cohort-1\",\"status\":\"READY\","
                        + "\"denominator\":13,\"input_count\":1744,"
                        + "\"duplicate_count\":0,\"excluded_count\":1452,"
                        + "\"review_count\":279,\"matching_count\":253,"
                        + "\"criteria\":{},\"technologies\":[]}}}}"));

        CSnapshot snapshot = client().get("/internal/v1/c/snapshots/snapshot-1",
                Map.of(), CSnapshot.class);

        assertThat(snapshot.payload().demand().denominator()).isEqualTo(13);
        assertThat(snapshot.payload().demand().inputCount()).isEqualTo(1_744);
        assertThat(snapshot.payload().demand().matchingCount()).isEqualTo(253);
        assertThat(snapshot.payload().demand().excludedCount()).isEqualTo(1_452);
        assertThat(snapshot.payload().demand().reviewCount()).isEqualTo(279);
    }

    @Test
    @DisplayName("모든 요청에 Bearer 토큰을 싣는다")
    void sendsBearerToken() {
        responses.put("/ready", Response.of(200, "{\"message\":\"ok\",\"data\":{\"status\":\"READY\"}}"));

        client().ready();

        assertThat(lastAuthorization.get()).isEqualTo("Bearer " + TOKEN);
    }

    @Test
    @DisplayName("202는 성공이 아니라 PREPARING이고 Retry-After를 함께 올린다")
    void treats202AsPreparing() {
        responses.put("/internal/v1/c/job-cohorts/resolve",
                new Response(202, "{\"message\":\"in progress\",\"data\":{\"status\":\"PREPARING\"}}", "2"));

        assertThatThrownBy(() -> client().post("/internal/v1/c/job-cohorts/resolve",
                Map.of("target_role", "BACKEND"), Object.class))
                .asInstanceOf(InstanceOfAssertFactories.type(CComputeException.class))
                .satisfies(e -> {
                    assertThat(e.getStatus()).isEqualTo(CComputeStatus.PREPARING);
                    assertThat(e.getRetryAfterSec()).isEqualTo(2);
                    assertThat(e.isRetryable()).isTrue();
                });
    }

    @Test
    @DisplayName("404는 code로 갈린다 — 미준비는 기다리는 상태, 없는 Snapshot은 404 화면")
    void splits404ByCode() {
        responses.put("/a", Response.of(404, "{\"code\":\"COHORT_NOT_PREPARED\",\"message\":\"x\"}"));
        responses.put("/b", Response.of(404, "{\"code\":\"SNAPSHOT_NOT_FOUND\",\"message\":\"x\"}"));
        CComputeClient client = client();

        assertThat(statusOf(() -> client.get("/a", Map.of(), Object.class)))
                .isEqualTo(CComputeStatus.NOT_PREPARED);
        assertThat(statusOf(() -> client.get("/b", Map.of(), Object.class)))
                .isEqualTo(CComputeStatus.NOT_FOUND);
    }

    @Test
    @DisplayName("409도 code로 갈린다 — 매칭 미준비와 멱등 충돌은 처리가 다르다")
    void splits409ByCode() {
        responses.put("/a", Response.of(409, "{\"code\":\"JOB_MATCHING_NOT_PREPARED\",\"message\":\"x\"}"));
        responses.put("/b", Response.of(409, "{\"code\":\"IDEMPOTENCY_CONFLICT\",\"message\":\"x\"}"));
        CComputeClient client = client();

        assertThat(statusOf(() -> client.get("/a", Map.of(), Object.class)))
                .isEqualTo(CComputeStatus.MATCHING_NOT_PREPARED);
        assertThat(statusOf(() -> client.get("/b", Map.of(), Object.class)))
                .isEqualTo(CComputeStatus.CONFLICT);
    }

    @Test
    @DisplayName("500도 갈린다 — 재시도 가능한 계산 실패와 저장 결과 무결성 실패")
    void splits500ByCode() {
        responses.put("/a", Response.of(500, "{\"code\":\"COMPUTE_FAILED\",\"message\":\"x\"}"));
        responses.put("/b", Response.of(500,
                "{\"code\":\"STORED_MATCHING_INTEGRITY_FAILED\",\"message\":\"x\"}"));
        CComputeClient client = client();

        assertThat(statusOf(() -> client.get("/a", Map.of(), Object.class)))
                .isEqualTo(CComputeStatus.COMPUTE_FAILED);
        assertThat(statusOf(() -> client.get("/b", Map.of(), Object.class)))
                .isEqualTo(CComputeStatus.INTEGRITY_FAILED);
    }

    @Test
    @DisplayName("422는 재시도해도 같으므로 INVALID_INPUT이다")
    void mapsInvalidInput() {
        responses.put("/a", Response.of(422, "{\"code\":\"INVALID_INPUT\",\"message\":\"x\"}"));

        CComputeException thrown = catchCompute(() -> client().get("/a", Map.of(), Object.class));

        assertThat(thrown.getStatus()).isEqualTo(CComputeStatus.INVALID_INPUT);
        assertThat(thrown.isRetryable()).isFalse();
    }

    @Test
    @DisplayName("503은 일시 장애다")
    void mapsUnavailable() {
        responses.put("/a", Response.of(503, "{\"code\":\"C_DATABASE_UNAVAILABLE\",\"message\":\"x\"}"));

        assertThat(statusOf(() -> client().get("/a", Map.of(), Object.class)))
                .isEqualTo(CComputeStatus.UNAVAILABLE);
    }

    @Test
    @DisplayName("미설정이면 호출하지 않고 UNAVAILABLE로 막는다")
    void doesNotCallWhenUnconfigured() {
        CComputeClient unconfigured = new CComputeClient(
                new CComputeProperties("", "", Duration.ofSeconds(1), Duration.ofSeconds(1)));

        assertThat(unconfigured.isConfigured()).isFalse();
        assertThat(statusOf(() -> unconfigured.ready())).isEqualTo(CComputeStatus.UNAVAILABLE);
        assertThat(calls.get()).isZero();
    }

    @Test
    @DisplayName("주소만 있고 토큰이 없으면 미설정이다 — 401을 C 장애로 오해하지 않는다")
    void requiresBothUrlAndToken() {
        CComputeProperties properties = new CComputeProperties(
                "http://127.0.0.1:1", "", Duration.ofSeconds(1), Duration.ofSeconds(1));

        assertThat(properties.isConfigured()).isFalse();
        assertThat(properties.describeConfiguration()).isEqualTo("gitjob.compute.token 미설정");
    }

    @Test
    @DisplayName("닿지 않으면 UNAVAILABLE이고 원인 예외를 잃지 않는다")
    void mapsUnreachable() {
        CComputeClient unreachable = new CComputeClient(new CComputeProperties(
                "http://127.0.0.1:1", TOKEN, Duration.ofMillis(300), Duration.ofMillis(300)));

        CComputeException thrown = catchCompute(unreachable::ready);

        assertThat(thrown.getStatus()).isEqualTo(CComputeStatus.UNAVAILABLE);
        assertThat(thrown.getCause()).isNotNull();
    }

    @Test
    @DisplayName("요청 본문은 snake_case이고 null 필드를 생략하지 않는다")
    void serializesRequestForCContract() {
        responses.put("/internal/v1/c/analyses/completed",
                Response.of(200, "{\"message\":\"ok\",\"data\":{\"status\":\"COMPLETED\"}}"));

        client().post("/internal/v1/c/analyses/completed",
                new SampleEvent("c-compute-event/v1", "ev-1",
                        Instant.parse("2026-09-15T01:30:00Z"), null),
                Object.class);

        assertThat(lastBody.get())
                .contains("\"schema_version\":\"c-compute-event/v1\"")
                .contains("\"event_id\":\"ev-1\"")
                // timezone 없는 epoch 숫자로 나가면 C가 422를 준다
                .contains("\"occurred_at\":\"2026-09-15T01:30:00Z\"")
                // C의 X | None은 "없어도 되는 필드"가 아니라 null 이 허용되는 필수
                // 필드다. 생략하면 field required 로 422 가 난다.
                .contains("\"cohort_snapshot_id\":null");
    }

    @Test
    @DisplayName("JOB Trend selector는 목표 직무와 공고 필터를 snake_case로 보낸다")
    void serializesJobTrendSelector() {
        responses.put("/internal/v1/c/trends/resolve",
                Response.of(200, "{\"message\":\"ok\",\"data\":{\"status\":\"COMPLETED\"}}"));

        client().post("/internal/v1/c/trends/resolve",
                CTrend.Selector.job("java", List.of("2026-07", "2026-08"), "BACKEND",
                        List.of("서울"), List.of("신입")),
                Object.class);

        assertThat(lastBody.get())
                .contains("\"source\":\"JOB\"")
                .contains("\"tech_id\":\"java\"")
                .contains("\"periods\":[\"2026-07\",\"2026-08\"]")
                .contains("\"granularity\":\"MONTH\"")
                .contains("\"target_role\":\"BACKEND\"")
                .contains("\"sources\":[]")
                .contains("\"regions\":[\"서울\"]")
                .contains("\"career_levels\":[\"신입\"]")
                .contains("\"min_jobs\":1");
    }

    @Test
    @DisplayName("주간 Trend selector는 C 계약에 맞게 빈 periods 배열을 보낸다")
    void serializesWeeklyTrendSelectorWithEmptyPeriods() {
        responses.put("/internal/v1/c/trends/resolve",
                Response.of(200, "{\"message\":\"ok\",\"data\":{\"status\":\"COMPLETED\"}}"));

        client().post("/internal/v1/c/trends/resolve",
                CTrend.Selector.weekly("java"), Object.class);

        assertThat(lastBody.get())
                .contains("\"source\":\"WEEKLY_REPO_ACTIVITY\"")
                .contains("\"tech_id\":\"java\"")
                .contains("\"periods\":[]");
    }

    @Test
    @DisplayName("값이 null인 쿼리 파라미터는 보내지 않는다")
    void skipsNullQueryParameters() {
        responses.put("/a", Response.of(200, "{\"message\":\"ok\",\"data\":{}}"));
        Map<String, Object> query = new HashMap<>();
        query.put("user_id", "7");
        query.put("recommended_tech_id", null);

        client().get("/a", query, Object.class);

        assertThat(lastQuery.get()).isEqualTo("user_id=7");
    }

    private record SampleEvent(String schemaVersion, String eventId, Instant occurredAt,
                               String cohortSnapshotId) {
    }

    private CComputeStatus statusOf(Runnable call) {
        return catchCompute(call).getStatus();
    }

    private CComputeException catchCompute(Runnable call) {
        try {
            call.run();
        } catch (CComputeException e) {
            return e;
        }
        throw new AssertionError("CComputeException이 발생하지 않았습니다.");
    }
}
