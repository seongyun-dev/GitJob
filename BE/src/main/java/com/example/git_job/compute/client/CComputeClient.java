package com.example.git_job.compute.client;

import com.example.git_job.compute.config.CComputeProperties;
import java.net.SocketTimeoutException;
import java.net.http.HttpTimeoutException;
import java.time.Duration;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.PropertyNamingStrategies;
import tools.jackson.databind.cfg.DateTimeFeature;
import tools.jackson.databind.json.JsonMapper;

/**
 * C Compute 내부 API의 클라이언트 (S15P21E102-279).
 *
 * <p>C가 계산한 공고 매칭·Skill Gap·추천·What-if·Trend를 읽는 유일한 통로다. 계산을 여기서
 * 다시 하지 않고, C DB를 직접 읽지도 않는다. 호출 순서와 각 endpoint의 의미는
 * {@code docs/ai/c-compute-backend-integration.md}, 공개 API로의 변환은
 * {@code docs/be/c-compute-public-api.md}에 있다.</p>
 *
 * <h2>왜 전용 ObjectMapper인가</h2>
 *
 * <p>C의 계약은 snake_case이고 이 서비스는 camelCase다. 전역 매퍼의 명명 규칙을 바꾸면
 * 이미 나간 공개 API의 필드 이름이 전부 바뀐다. 그래서 C 경계 전용 매퍼를 이 클래스가
 * 소유한다. 같은 이유로 응답을 문자열로 받아 직접 파싱한다 — 메시지 컨버터를 갈아끼우면
 * 그 설정이 애플리케이션 전체에 걸린다.</p>
 *
 * <p>{@code null} 필드를 생략하지 않는다. C의 Pydantic 모델에서 {@code X | None}은
 * "없어도 되는 필드"가 아니라 <em>null이 허용되는 필수 필드</em>다. 기본값이 없는
 * 그 필드들을 생략하면 {@code field required}로 422가 난다. 반대로 보내면 안 되는
 * 필드는 애초에 DTO에 두지 않는다 -- C의 event 모델은 {@code extra="forbid"}라
 * 모르는 필드를 실으면 역시 422다.</p>
 *
 * <h2>왜 200이 아닌 것을 전부 예외로 올리는가</h2>
 *
 * <p>202({@code PREPARING})는 HTTP로는 성공이지만 결과가 없다. 호출부가 200 본문과 202
 * 본문을 둘 다 파싱하게 두면 그 분기가 기능마다 복제되고, 한 곳에서 빠뜨리면 "계산 중"이
 * 빈 결과로 표시된다. 상태는 {@link CComputeException#getStatus()} 하나로 모은다.</p>
 *
 * <p>토큰은 어떤 경로로도 밖에 나가지 않는다. 로그에 URL을 남길 때도 헤더는 남기지
 * 않으며, 실패 메시지에는 경로와 C가 준 {@code code}만 넣는다.</p>
 */
@Component
public class CComputeClient {

    private static final Logger log = LoggerFactory.getLogger(CComputeClient.class);

    private final CComputeProperties properties;
    private final ObjectMapper mapper;
    /** 조회 계열. 미설정이면 {@code null}이고 호출 전에 막힌다. */
    private final RestClient readClient;
    /** C가 실제로 계산하는 호출. 조회보다 긴 timeout을 쓴다. */
    private final RestClient writeClient;

    public CComputeClient(CComputeProperties properties) {
        this.properties = properties;
        this.mapper = createMapper();
        this.readClient = properties.isConfigured()
                ? build(properties, properties.getReadTimeout()) : null;
        this.writeClient = properties.isConfigured()
                ? build(properties, properties.getWriteTimeout()) : null;
        if (!properties.isConfigured()) {
            log.warn("C Compute 미설정으로 계산 결과 조회가 비활성입니다: {}",
                    properties.describeConfiguration());
        }
    }

    /**
     * C 경계 전용 매퍼.
     *
     * <p>알 수 없는 필드에서 실패하지 않는 이유는 C가 계약을 additive로 늘리기 때문이다
     * ({@code demand_snapshot_id}·{@code compute_versions}가 그렇게 붙었다). 새 필드가
     * 생겼다고 기존 화면이 죽으면 안 된다.</p>
     */
    private static ObjectMapper createMapper() {
        return JsonMapper.builder()
                .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                // C의 occurred_at은 timezone을 요구한다. epoch 숫자로 나가면 422다.
                // Jackson 3의 기본값이기도 하지만 명시한다 -- 전역 설정이 아니라 이
                // 매퍼의 계약이고, 조용히 바뀌면 원인이 C의 422로만 보인다.
                // java.time은 databind에 내장되어 모듈 등록이 없다.
                .disable(DateTimeFeature.WRITE_DATES_AS_TIMESTAMPS)
                .build();
    }

    private static RestClient build(CComputeProperties properties, Duration timeout) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(timeout);
        factory.setReadTimeout(timeout);
        return RestClient.builder()
                .baseUrl(properties.getBaseUrl())
                .requestFactory(factory)
                .defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + properties.getToken())
                .defaultHeader(HttpHeaders.ACCEPT, MediaType.APPLICATION_JSON_VALUE)
                // 기본 상태 핸들러를 끈다. 4xx/5xx 본문의 code를 읽어야 상태를 좁힐 수 있는데
                // 기본 핸들러는 그 전에 RestClientResponseException으로 바꿔 버린다.
                .defaultStatusHandler(status -> true, (request, response) -> { })
                .build();
    }

    /** 설정 여부. 호출부가 미설정을 장애와 다르게 로그할 수 있게 노출한다. */
    public boolean isConfigured() {
        return properties.isConfigured();
    }

    /**
     * 인증 포함 {@code /ready}. DB migration 준비까지 확인한다.
     *
     * <p>{@code /health}는 process liveness만 보므로 여기서 부르지 않는다. 그것으로는
     * C가 계산할 수 있는 상태인지 알 수 없다.</p>
     */
    public Ready ready() {
        return get("/ready", Map.of(), Ready.class);
    }

    public record Ready(String status, String registryVersion) {
    }

    /**
     * 조회. {@code path}는 {@code /internal/v1/c/...}처럼 baseUrl 뒤에 붙는 경로다.
     *
     * @param query 값이 {@code null}인 항목은 보내지 않는다. C는 선택 파라미터의 빈
     *              문자열을 값으로 읽는다.
     */
    public <T> T get(String path, Map<String, ?> query, Class<T> dataType) {
        return exchange(readClient, HttpMethod.GET, path, query, null, dataType);
    }

    /** 완료 event 전달과 resolve. 본문은 C 경계 매퍼로 snake_case 직렬화된다. */
    public <T> T post(String path, Object body, Class<T> dataType) {
        return exchange(writeClient, HttpMethod.POST, path, Map.of(), body, dataType);
    }

    private <T> T exchange(RestClient client, HttpMethod method, String path,
                           Map<String, ?> query, Object body, Class<T> dataType) {
        if (client == null) {
            throw CComputeException.notConfigured(properties.describeConfiguration());
        }

        ResponseEntity<String> response;
        try {
            RestClient.RequestBodySpec spec = client.method(method)
                    .uri(builder -> {
                        builder.path(path);
                        query.forEach((name, value) -> {
                            if (value != null) {
                                builder.queryParam(name, value);
                            }
                        });
                        return builder.build();
                    });
            if (body != null) {
                spec = spec.contentType(MediaType.APPLICATION_JSON).body(writeJson(body));
            }
            response = spec.retrieve().toEntity(String.class);
        } catch (ResourceAccessException e) {
            // 연결 거부·타임아웃. 관리자망 단절이거나 Worker가 내려갔다.
            if (isTimeout(e)) {
                throw CComputeException.timeout(path, e);
            }
            throw CComputeException.unreachable(path, e);
        } catch (RuntimeException e) {
            // HTTP 구현체가 timeout을 ResourceAccessException 밖에서 한 번 더 감싸도
            // 일반 500으로 새지 않게 cause chain을 확인한다.
            if (isTimeout(e)) {
                throw CComputeException.timeout(path, e);
            }
            throw e;
        }

        int status = response.getStatusCode().value();
        if (status == 202) {
            throw new CComputeException(CComputeStatus.PREPARING, "PREPARING",
                    retryAfterSeconds(response.getHeaders()),
                    "C 계산이 진행 중입니다: " + path);
        }
        if (status != 200) {
            throw translate(status, response.getBody(), path);
        }
        return unwrap(response.getBody(), dataType, path);
    }

    /**
     * 봉투에서 {@code data}만 꺼낸다.
     *
     * <p>봉투가 아니면 오류로 본다. C는 성공 응답을 예외 없이 {@code {message, data}}로
     * 주므로, 다른 모양이 왔다면 우리가 C가 아닌 무언가(프록시 오류 페이지 등)와 말하고
     * 있다는 뜻이다.</p>
     */
    private <T> T unwrap(String body, Class<T> dataType, String path) {
        try {
            JsonNode root = mapper.readTree(body == null ? "" : body);
            JsonNode data = root.get("data");
            if (data == null) {
                throw CComputeException.invalidResponse(path, null);
            }
            return mapper.treeToValue(data, dataType);
        } catch (CComputeException e) {
            throw e;
        } catch (Exception e) {
            throw CComputeException.invalidResponse(path, e);
        }
    }

    private String writeJson(Object body) {
        try {
            return mapper.writeValueAsString(body);
        } catch (Exception e) {
            // 우리가 만든 DTO를 직렬화하지 못한 것이므로 C 장애가 아니라 B 버그다.
            throw new IllegalStateException("C 요청 본문을 직렬화할 수 없습니다.", e);
        }
    }

    /**
     * C 오류 본문 {@code {code, message}}를 상태로 좁힌다.
     *
     * <p>HTTP 상태만으로는 부족하다. 404 하나에 "입력 묶음이 아직 없다"와 "그런 Snapshot은
     * 없다"가 함께 들어 있고, 화면이 해야 할 일은 정반대다(기다리기 / 404 표시).</p>
     */
    private CComputeException translate(int httpStatus, String body, String path) {
        String code = readErrorCode(body);
        CComputeStatus status = switch (httpStatus) {
            case 403 -> CComputeStatus.SCOPE_MISMATCH;
            case 404 -> "SNAPSHOT_NOT_FOUND".equals(code) || "JOB_NOT_FOUND".equals(code)
                    ? CComputeStatus.NOT_FOUND
                    : CComputeStatus.NOT_PREPARED;
            case 409 -> "JOB_MATCHING_NOT_PREPARED".equals(code)
                    ? CComputeStatus.MATCHING_NOT_PREPARED
                    : CComputeStatus.CONFLICT;
            case 413 -> CComputeStatus.TOO_LARGE;
            case 422 -> CComputeStatus.INVALID_INPUT;
            case 500 -> "STORED_MATCHING_INTEGRITY_FAILED".equals(code)
                    ? CComputeStatus.INTEGRITY_FAILED
                    : CComputeStatus.COMPUTE_FAILED;
            // 503과 401이 여기로 온다. 화면이 할 일은 같지만(잠시 후 재시도) 401은
            // C 장애가 아니라 배포 설정 오류이므로 아래에서 로그를 따로 남긴다.
            default -> CComputeStatus.UNAVAILABLE;
        };
        if (httpStatus == 401) {
            log.error("C Compute 인증 실패. C_COMPUTE_TOKEN이 C Worker와 다릅니다: path={}", path);
        }
        return new CComputeException(status, code, null,
                "C Compute 오류: path=" + path + ", status=" + httpStatus + ", code=" + code);
    }

    private String readErrorCode(String body) {
        if (body == null || body.isBlank()) {
            return null;
        }
        try {
            JsonNode node = mapper.readTree(body).get("code");
            return node == null ? null : node.asString();
        } catch (Exception e) {
            return null;
        }
    }

    private Integer retryAfterSeconds(HttpHeaders headers) {
        String header = headers.getFirst(HttpHeaders.RETRY_AFTER);
        if (header == null) {
            return null;
        }
        try {
            return Integer.parseInt(header.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static boolean isTimeout(Throwable failure) {
        Throwable current = failure;
        for (int depth = 0; current != null && depth < 12; depth++) {
            if (current instanceof SocketTimeoutException
                    || current instanceof HttpTimeoutException
                    || current instanceof java.util.concurrent.TimeoutException) {
                return true;
            }
            current = current.getCause();
        }
        return false;
    }
}
