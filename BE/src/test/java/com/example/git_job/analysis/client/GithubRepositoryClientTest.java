package com.example.git_job.analysis.client;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.example.git_job.global.config.GithubOAuthProperties;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;

/**
 * GitHub을 흉내 내는 JDK HttpServer로 상태 코드 변환과 URL 조립을 검증한다.
 * 실제 GitHub을 부르지 않으므로 네트워크와 토큰이 필요 없다.
 */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class GithubRepositoryClientTest {

    private static final String TOKEN = "gho_test_token";

    private HttpServer server;
    private GithubRepositoryClient client;
    private final AtomicReference<Canned> canned = new AtomicReference<>();
    private final List<String> requestedPaths = new CopyOnWriteArrayList<>();
    private final List<String> authorizationHeaders = new CopyOnWriteArrayList<>();

    private record Canned(int status, String body, Map<String, String> headers) {
        static Canned ok(String body) {
            return new Canned(200, body, Map.of());
        }

        static Canned status(int status, Map<String, String> headers) {
            return new Canned(status, "{\"message\":\"failed\"}", headers);
        }
    }

    @BeforeAll
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", this::respond);
        server.start();
        var properties = new GithubOAuthProperties("id", "secret", "http://localhost/cb",
                "http://127.0.0.1:" + server.getAddress().getPort(),
                "http://localhost/auth", List.of("/"));
        client = new GithubRepositoryClient(properties);
    }

    @AfterAll
    void stopServer() {
        server.stop(0);
    }

    @BeforeEach
    void reset() {
        requestedPaths.clear();
        authorizationHeaders.clear();
        canned.set(Canned.ok("{}"));
    }

    private void respond(HttpExchange exchange) throws IOException {
        String query = exchange.getRequestURI().getRawQuery();
        requestedPaths.add(exchange.getRequestURI().getRawPath() + (query == null ? "" : "?" + query));
        String authorization = exchange.getRequestHeaders().getFirst("Authorization");
        authorizationHeaders.add(authorization == null ? "" : authorization);

        Canned response = canned.get();
        response.headers().forEach((name, value) -> exchange.getResponseHeaders().add(name, value));
        byte[] body = response.body().getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(response.status(), body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
    }

    @Test
    void sendsTheAccessTokenAsABearerCredential() {
        canned.set(Canned.ok("{\"id\":1,\"full_name\":\"octocat/repo\"}"));

        client.fetchRepository(TOKEN, "octocat", "repo");

        assertEquals("Bearer " + TOKEN, authorizationHeaders.get(0));
    }

    @Test
    @DisplayName("슬래시가 든 브랜치 이름은 경로 구분자로 남아야 GitHub이 찾는다")
    void keepsSlashesInBranchNamesUnencoded() {
        canned.set(Canned.ok("{\"name\":\"feature/cdc\",\"commit\":{\"sha\":\"abc\"}}"));

        var branch = client.fetchBranch(TOKEN, "octocat", "repo", "feature/cdc");

        assertEquals("/repos/octocat/repo/branches/feature/cdc", requestedPaths.get(0));
        assertEquals("abc", branch.commitSha());
    }

    @Test
    void requestsRepositoriesMostRecentlyUpdatedFirst() {
        canned.set(Canned.ok("[]"));

        client.fetchRepositories(TOKEN, 2, 50);

        String path = requestedPaths.get(0);
        assertTrue(path.startsWith("/user/repos?"), path);
        assertTrue(path.contains("sort=updated"), path);
        assertTrue(path.contains("per_page=50"), path);
        assertTrue(path.contains("page=2"), path);
    }

    @Test
    @DisplayName("한도 초과와 권한 부족은 둘 다 403이라 남은 호출 수로 갈라야 한다")
    void separatesRateLimitFromForbidden() {
        canned.set(Canned.status(403, Map.of("x-ratelimit-remaining", "0")));
        var rateLimited = assertThrows(CustomException.class,
                () -> client.fetchRepository(TOKEN, "octocat", "repo"));
        assertEquals(ErrorCode.GITHUB_RATE_LIMITED, rateLimited.getErrorCode());

        canned.set(Canned.status(403, Map.of("x-ratelimit-remaining", "4999")));
        var forbidden = assertThrows(CustomException.class,
                () -> client.fetchRepository(TOKEN, "octocat", "repo"));
        assertEquals(ErrorCode.REPOSITORY_ACCESS_DENIED, forbidden.getErrorCode());
    }

    @Test
    void mapsSecondaryRateLimitStatusToTheSameCode() {
        canned.set(Canned.status(429, Map.of()));

        var failure = assertThrows(CustomException.class,
                () -> client.fetchRepository(TOKEN, "octocat", "repo"));

        assertEquals(ErrorCode.GITHUB_RATE_LIMITED, failure.getErrorCode());
    }

    @Test
    void mapsRevokedTokenToAReLoginSignal() {
        canned.set(Canned.status(401, Map.of()));

        var failure = assertThrows(CustomException.class,
                () -> client.fetchRepository(TOKEN, "octocat", "repo"));

        assertEquals(ErrorCode.GITHUB_TOKEN_INVALID, failure.getErrorCode());
    }

    @Test
    @DisplayName("404는 호출한 자원에 따라 저장소와 브랜치를 구분해 응답한다")
    void mapsNotFoundToTheResourceThatWasRequested() {
        canned.set(Canned.status(404, Map.of()));

        assertEquals(ErrorCode.REPOSITORY_NOT_FOUND, assertThrows(CustomException.class,
                () -> client.fetchRepository(TOKEN, "octocat", "repo")).getErrorCode());
        assertEquals(ErrorCode.BRANCH_NOT_FOUND, assertThrows(CustomException.class,
                () -> client.fetchBranch(TOKEN, "octocat", "repo", "main")).getErrorCode());
    }

    @Test
    void mapsGithubOutageToAnUnavailableCode() {
        canned.set(Canned.status(502, Map.of()));

        var failure = assertThrows(CustomException.class,
                () -> client.fetchRepositories(TOKEN, 1, 30));

        assertEquals(ErrorCode.GITHUB_UNAVAILABLE, failure.getErrorCode());
    }

    @Test
    @DisplayName("SHA 없는 브랜치 응답은 성공으로 취급하지 않는다")
    void rejectsBranchResponsesWithoutACommitSha() {
        canned.set(Canned.ok("{\"name\":\"main\"}"));

        var failure = assertThrows(CustomException.class,
                () -> client.fetchBranch(TOKEN, "octocat", "repo", "main"));

        assertEquals(ErrorCode.BRANCH_NOT_FOUND, failure.getErrorCode());
    }
}
