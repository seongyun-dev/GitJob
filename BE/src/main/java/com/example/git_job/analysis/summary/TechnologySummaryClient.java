package com.example.git_job.analysis.summary;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.concurrent.Semaphore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.json.JsonMapper;

/**
 * 노트북 GPU 위의 요약 서비스를 부른다.
 *
 * <h2>실패를 위로 올리지 않는다</h2>
 *
 * <p>추론은 EC2 가 아니라 팀원 노트북에서 돈다. 노트북이 꺼져 있으면 연결 자체가
 * 안 되고, 그것은 장애가 아니라 정상적으로 자주 일어나는 일이다. 요약은 이미
 * 완성된 카드 위에 얹는 것이므로 -- 수준·근거·permalink 는 이 호출과 무관하게
 * 이미 있다 -- 못 받으면 없이 그린다.</p>
 *
 * <h2>동시에 둘까지만 보낸다</h2>
 *
 * <p>GPU 가 한 대라 요청이 몰리면 어차피 직렬화된다. 그대로 밀어 넣으면 서버 쪽
 * 큐만 길어지고 뒤의 요청은 timeout 까지 기다렸다 버려진다. 여기서 막으면 기다릴
 * 요청과 포기할 요청이 우리 쪽에서 갈린다.</p>
 *
 * <p>자리를 못 받은 요청은 실패가 아니라 {@link SummaryOutcome.Kind#BUSY} 다.
 * 오래 기다리게 두면 Tomcat 요청 스레드가 그만큼 묶이고, 결국 못 받았을 때 화면은
 * 그 자리를 "요약 없음"으로 그린다 -- 새로 고쳐도 같은 자리가 비는데 사실은 잠시
 * 뒤 다시 물으면 채워지는 상태다. 그래서 짧게 기다리고 빨리 돌려준다.</p>
 */
@Component
public class TechnologySummaryClient {

    private static final Logger log = LoggerFactory.getLogger(TechnologySummaryClient.class);

    private static final int MAX_IN_FLIGHT = 2;

    /**
     * 슬롯을 기다리는 상한. 넘으면 {@link SummaryOutcome#busy()} 다.
     *
     * <p>짧아야 한다. 생성 한 건이 4~8초이고 자리는 둘이라, 카드 열두 장이 한꺼번에
     * 들어오면 뒤쪽은 20초를 기다려도 대부분 못 받는다. 오래 기다리는 쪽을 택하면
     * 얻는 것 없이 두 가지를 잃는다 -- 그동안 Tomcat 요청 스레드가 묶이고, 결국
     * 실패했을 때 그 자리가 영구히 빈 것처럼 보인다.</p>
     *
     * <p>2초는 앞 건이 거의 끝나가던 경우만 건진다. 그보다 오래 걸릴 상황이면
     * 기다리지 말고 BUSY 로 돌려주고, 화면이 잠시 뒤 다시 묻게 한다.</p>
     */
    private static final Duration SLOT_WAIT = Duration.ofSeconds(2);

    /**
     * BUSY 를 받은 화면이 다시 묻기까지 권하는 시간.
     *
     * <p>자리가 둘이고 한 건이 4~8초이므로, 앞의 두 건이 끝날 즈음이 이쯤이다.
     * 더 짧으면 같은 요청이 BUSY 를 반복해서 받고, 더 길면 카드가 이유 없이
     * 오래 비어 있다.</p>
     */
    public static final int RETRY_AFTER_SECONDS = 5;

    /** 프롬프트 버전은 배포할 때나 바뀐다. */
    private static final Duration HEALTH_TTL = Duration.ofSeconds(60);

    private final RestClient restClient;
    private final boolean enabled;
    private final Semaphore slots = new Semaphore(MAX_IN_FLIGHT, true);
    private volatile Cached cachedVersion;
    private final JsonMapper mapper = JsonMapper.builder().build();

    public TechnologySummaryClient(
            @Value("${gitjob.llm.summary.base-url:}") String baseUrl,
            @Value("${gitjob.llm.summary.timeout:120s}") Duration timeout) {
        this.enabled = baseUrl != null && !baseUrl.isBlank();
        // 주소가 비어 있으면 아예 부르지 않는다. 기본이 꺼짐이어야 요약 서비스를
        // 띄우지 않은 환경에서 화면이 매번 timeout 을 기다리지 않는다.
        this.restClient = this.enabled
                ? RestClient.builder()
                        .baseUrl(baseUrl)
                        .requestFactory(requestFactory(timeout))
                        .build()
                : null;
    }

    /**
     * 연결과 읽기에 다른 상한을 둔다.
     *
     * <p>노트북이 꺼져 있으면 연결에서 갈리고, 그건 5초면 충분하다. 추론은
     * cold start 가 1분에 가까우므로 읽기는 길게 연다 -- 둘을 한 값으로 묶으면
     * 꺼진 서비스를 2분씩 기다리거나, 살아 있는 추론을 중간에 끊게 된다.</p>
     */
    private static SimpleClientHttpRequestFactory requestFactory(Duration readTimeout) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(5));
        factory.setReadTimeout(readTimeout);
        return factory;
    }

    public boolean isEnabled() {
        return enabled;
    }

    /**
     * 지금 서비스가 쓰는 프롬프트 버전. 못 물어보면 비어 있다.
     *
     * <p>저장된 요약이 아직 쓸 만한지 가르는 값이다. 프롬프트가 바뀌면 지금
     * 프롬프트로는 나올 수 없는 문장이 화면에 남는다.</p>
     *
     * <p>짧게 캐시한다. 카드마다 한 번씩 물으면 화면 한 장에 {@code /health} 가
     * 열두 번 나가는데, 이 값은 배포할 때나 바뀐다.</p>
     */
    public Optional<String> promptVersion() {
        if (!enabled) {
            return Optional.empty();
        }
        Cached current = cachedVersion;
        if (current != null && current.expiresAt().isAfter(Instant.now())) {
            return Optional.ofNullable(current.promptVersion());
        }
        String fetched = null;
        try {
            Health health = restClient.get().uri("/health").retrieve().body(Health.class);
            fetched = health == null ? null : health.promptVersion();
        } catch (RuntimeException unavailable) {
            log.debug("health unavailable: {}", unavailable.getClass().getSimpleName());
        }
        // 실패도 캐시한다. 노트북이 꺼져 있으면 카드마다 연결을 기다리게 된다.
        cachedVersion = new Cached(fetched, Instant.now().plus(HEALTH_TTL));
        return Optional.ofNullable(fetched);
    }

    /**
     * 요약 한 건. 실패하면 비어 있다.
     *
     * @param userId 캐시 키를 사람마다 가르기 위한 값. 프롬프트에는 들어가지
     *               않는다 -- 그래서 Fact Pack 밖에 있다
     */
    public SummaryOutcome summarize(long userId, FactPack factPack) {
        return summarize(factPack.technology().techId(), requestBody(userId, factPack));
    }

    /**
     * 보낼 본문을 우리 mapper 로 만든다.
     *
     * <p>{@code RestClient} 에 객체를 넘기면 Spring 이 설정한 mapper 가 직렬화하고,
     * 그 설정은 우리 것이 아니다. 날짜 하나가 배열로 나가면 받는 쪽이 422 로
     * 거절하는데 그 실패는 "요약이 아직 없음"과 화면에서 구별되지 않는다. 바이트를
     * 여기서 만들면 테스트가 고정한 모양이 그대로 나간다.</p>
     */
    public String requestBody(long userId, FactPack factPack) {
        return mapper.writeValueAsString(new Request(String.valueOf(userId), factPack));
    }

    private SummaryOutcome summarize(String techId, String body) {
        if (!enabled) {
            return SummaryOutcome.unavailable();
        }
        boolean acquired = false;
        try {
            acquired = slots.tryAcquire(SLOT_WAIT.toMillis(),
                    java.util.concurrent.TimeUnit.MILLISECONDS);
            if (!acquired) {
                // 실패가 아니다. 자리가 나면 같은 요청이 그대로 성공한다.
                log.info("summary busy, no slot: techId={}", techId);
                return SummaryOutcome.busy();
            }
            TechnologySummaryResponse response = restClient.post()
                    .uri("/technology-summary")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(TechnologySummaryResponse.class);
            return response == null
                    ? SummaryOutcome.unavailable()
                    : SummaryOutcome.generated(response);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return SummaryOutcome.unavailable();
        } catch (RuntimeException unavailable) {
            // 연결 불가·timeout·5xx 가 전부 여기로 온다. 메시지에 주소가 섞여
            // 나오므로 원문을 그대로 남기지 않고 종류만 적는다.
            log.info("summary unavailable: techId={}, cause={}",
                    techId, unavailable.getClass().getSimpleName());
            return SummaryOutcome.unavailable();
        } finally {
            if (acquired) {
                slots.release();
            }
        }
    }

    @com.fasterxml.jackson.annotation.JsonIgnoreProperties(ignoreUnknown = true)
    private record Health(@JsonProperty("prompt_version") String promptVersion) {
    }

    /** {@code promptVersion} 이 null 이면 "물어봤지만 못 받았다"는 뜻이다. */
    private record Cached(String promptVersion, Instant expiresAt) {
    }

    /** {@code user_id} 가 {@code fact_pack} 밖에 있는 것이 계약이다. */
    private record Request(
            @JsonProperty("user_id") String userId,
            @JsonProperty("fact_pack") FactPack factPack) {
    }
}
