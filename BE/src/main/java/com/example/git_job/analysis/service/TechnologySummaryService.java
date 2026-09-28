package com.example.git_job.analysis.service;

import com.example.git_job.analysis.store.TechnologySummaryStore;
import com.example.git_job.analysis.store.TechnologySummaryStore.Cached;
import com.example.git_job.analysis.summary.FactPack;
import com.example.git_job.analysis.summary.FactPackBuilder;
import com.example.git_job.analysis.summary.SummaryOutcome;
import com.example.git_job.analysis.summary.TechnologySummaryClient;
import com.example.git_job.analysis.summary.TechnologySummaryResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Optional;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import tools.jackson.databind.json.JsonMapper;

/**
 * 기술 하나의 요약을 돌려준다. 저장된 것이 있으면 그것을, 없으면 만들어서.
 *
 * <h2>트랜잭션을 걸지 않는다</h2>
 *
 * <p>가운데에 4초짜리 HTTP 호출이 있다. 트랜잭션으로 감싸면 그동안 커넥션 하나가
 * 묶이고, 카드 열두 개면 열두 개가 묶인다. 읽기와 쓰기는 각각 한 문장이라 따로
 * 커밋돼도 문제가 없다 -- 최악의 경우 같은 요약을 두 번 만들고 뒤엣것이
 * 덮어쓴다.</p>
 *
 * <h2>실패는 요약 없음이지 오류가 아니다</h2>
 *
 * <p>화면은 요약 없이도 완성돼 있다. 수준·근거·permalink 는 이 경로와 무관하게
 * 이미 있으므로, 못 만들면 비운 채로 돌려준다. 이 약속은 요약 서비스가 무엇을
 * 주든 지켜야 한다 -- 쓸 수 없는 응답을 그대로 저장하려다 제약에 걸려 예외가
 * 올라가면, 요약 한 문단 때문에 카드 전체가 500 이 된다.</p>
 *
 * <h2>비었다고 다 같은 것은 아니다</h2>
 *
 * <p>{@link Status#PENDING} 은 GPU 자리가 없어 아직 못 만들었다는 뜻이고 잠시 뒤
 * 다시 물으면 채워진다. {@link Status#NONE} 은 다시 물어도 같다. 둘을 합치면
 * 화면은 새로 고칠 때마다 같은 자리가 비는 것을 보면서 그것이 영구적인지
 * 알 수 없다.</p>
 */
@Service
@RequiredArgsConstructor
public class TechnologySummaryService {

    private static final Logger log = LoggerFactory.getLogger(TechnologySummaryService.class);

    /** {@code technology_summary.llm_status} 의 CHECK 와 같은 집합이다. */
    private static final Set<String> STORABLE_STATUS = Set.of("OK", "FALLBACK");
    /** {@code technology_summary.confidence} 의 CHECK 와 같은 집합이다. */
    private static final Set<String> STORABLE_CONFIDENCE = Set.of("HIGH", "MEDIUM", "LOW");
    /** {@code prompt_version} 과 {@code model} 이 VARCHAR(80) 이다. */
    private static final int MAX_VERSION_LENGTH = 80;
    /** {@code cache_key} 가 CHAR(64) 다. 길이가 다르면 저장하지 않고 비운다. */
    private static final int CACHE_KEY_LENGTH = 64;

    private final FactPackBuilder factPacks;
    private final TechnologySummaryClient client;
    private final TechnologySummaryStore store;
    private final JsonMapper mapper = JsonMapper.builder().build();

    /**
     * @return 상태와 (있으면) 문장. {@code null} 을 돌려주지 않는다.
     */
    public SummaryResult summaryOf(long userId, String techId) {
        Optional<FactPack> factPack = factPacks.build(userId, techId);
        if (factPack.isEmpty()) {
            // 판정이 없는 기술이다. 다시 물어도 같으므로 기다릴 이유가 없다.
            return SummaryResult.none();
        }
        String fingerprint = fingerprint(factPack.get());
        // 물어보지 못하면 null 이고, 그때는 버전을 따지지 않고 저장된 것을 쓴다.
        String promptVersion = client.promptVersion().orElse(null);

        Optional<Cached> cached = store.find(userId, techId, fingerprint, promptVersion);
        if (cached.isPresent()) {
            return SummaryResult.ready(Summary.from(cached.get()));
        }
        return generate(userId, techId, factPack.get(), fingerprint);
    }

    private SummaryResult generate(long userId, String techId, FactPack factPack,
            String fingerprint) {
        SummaryOutcome outcome = client.summarize(userId, factPack);
        if (outcome.isBusy()) {
            // 자리가 없었을 뿐이다. 화면이 잠시 뒤 다시 물으면 같은 요청이 성공한다.
            return SummaryResult.pending();
        }
        Optional<TechnologySummaryResponse> received = outcome.body();
        if (received.isEmpty() || received.get().summary() == null) {
            return SummaryResult.none();
        }
        TechnologySummaryResponse body = received.get();
        TechnologySummaryResponse.Summary summary = body.summary();
        if (!techId.equals(summary.techId())) {
            // 요청과 다른 기술이 돌아왔다. 저쪽도 검사하지만, 그대로 저장하면
            // 한 기술의 문장이 다른 기술 카드에 앉는다.
            log.warn("summary tech mismatch: asked={}, got={}", techId, summary.techId());
            return SummaryResult.none();
        }
        String rejected = unstorable(body, summary);
        if (rejected != null) {
            log.warn("summary not storable: techId={}, reason={}", techId, rejected);
            return SummaryResult.none();
        }

        store.save(userId, techId, fingerprint, cacheKey(body.cacheKey()), body.promptVersion(),
                body.model(), body.llmStatus(), summary.headline(), summary.summary(),
                summary.gap(), summary.confidence(), summary.usedHighlights(),
                Instant.now());
        log.info("summary generated: techId={}, status={}, model={}",
                techId, body.llmStatus(), body.model());
        return SummaryResult.ready(new Summary(summary.headline(), summary.summary(),
                summary.gap(), summary.confidence(), body.llmStatus()));
    }

    /**
     * 저장할 수 없는 응답인지 본다. 저장 가능하면 {@code null}.
     *
     * <h2>왜 여기서 한 번 더 보는가</h2>
     *
     * <p>{@code technology_summary} 의 여러 칸이 NOT NULL 이고 두 칸은 CHECK 까지
     * 걸려 있다. 응답의 한 칸이 비었거나 모르는 값이면 INSERT 에서 예외가 나는데,
     * 그 예외는 이 클래스 밖으로 올라가 카드 전체를 500 으로 만든다 -- "실패는
     * 요약 없음이지 오류가 아니다"라는 약속이 깨지는 유일한 지점이다.</p>
     *
     * <p>요약 서비스가 언제나 200 을 준다는 것이 이 위험을 가린다. 계약을 지키는
     * 응답만 온다는 전제로 두면, 어긋나는 날 원인이 DB 제약 위반으로만 보인다.</p>
     */
    private String unstorable(TechnologySummaryResponse body,
            TechnologySummaryResponse.Summary summary) {
        if (isBlank(body.llmStatus()) || !STORABLE_STATUS.contains(body.llmStatus())) {
            return "llm_status=" + body.llmStatus();
        }
        if (isBlank(summary.confidence()) || !STORABLE_CONFIDENCE.contains(summary.confidence())) {
            return "confidence=" + summary.confidence();
        }
        if (isBlank(summary.headline())) {
            return "headline is blank";
        }
        if (isBlank(summary.summary())) {
            return "summary is blank";
        }
        if (isBlank(body.promptVersion()) || body.promptVersion().length() > MAX_VERSION_LENGTH) {
            return "prompt_version length=" + length(body.promptVersion());
        }
        if (isBlank(body.model()) || body.model().length() > MAX_VERSION_LENGTH) {
            return "model length=" + length(body.model());
        }
        return null;
    }

    /**
     * 추적용 키. 길이가 계약과 다르면 비워서 저장한다.
     *
     * <p>조회에 쓰지 않는 값이라, 이것 하나 때문에 문장을 통째로 버릴 이유가 없다.
     * CHAR(64) 에 다른 길이를 넣으면 INSERT 가 실패하므로 여기서 걸러 둔다.</p>
     */
    private static String cacheKey(String cacheKey) {
        return cacheKey != null && cacheKey.length() == CACHE_KEY_LENGTH ? cacheKey : null;
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private static int length(String value) {
        return value == null ? -1 : value.length();
    }

    /**
     * 우리가 보낸 Fact Pack 의 지문.
     *
     * <p>레코드는 선언 순서대로 직렬화되고 {@code highlights} 선별도 결정적이라,
     * 같은 입력이면 같은 바이트가 나온다. 레벨이나 근거가 바뀌면 값이 달라져
     * 저장된 요약이 저절로 밀려난다.</p>
     *
     * <p>요약 서비스가 주는 {@code cache_key} 를 쓰지 않는 이유는 그것을 호출
     * <b>전에</b> 알 수 없기 때문이다. 재현하려면 저쪽 직렬화의 바이트까지
     * 맞춰야 하고, 한쪽이 바뀌면 조용히 어긋난다.</p>
     */
    private String fingerprint(FactPack factPack) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(
                    mapper.writeValueAsString(factPack).getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 을 쓸 수 없다", impossible);
        }
    }

    /** 요약을 못 받은 이유. 화면이 다시 물을지 말지를 여기서 정한다. */
    public enum Status {
        /** 보여줄 문장이 있다. */
        READY,
        /** GPU 자리가 없어 아직 못 만들었다. 잠시 뒤 다시 물으면 채워진다. */
        PENDING,
        /** 지금은 없고 다시 물어도 같다. 판정이 없거나 서비스가 꺼져 있다. */
        NONE
    }

    /**
     * 한 기술의 조회 결과.
     *
     * @param retryAfterSeconds {@code PENDING} 일 때만 0 보다 크다. 화면이 이 값을
     *                          쓰면 자리가 날 즈음에 다시 묻게 된다.
     */
    public record SummaryResult(Status status, Summary summary, int retryAfterSeconds) {

        static SummaryResult ready(Summary summary) {
            return new SummaryResult(Status.READY, summary, 0);
        }

        static SummaryResult pending() {
            return new SummaryResult(Status.PENDING, null,
                    TechnologySummaryClient.RETRY_AFTER_SECONDS);
        }

        static SummaryResult none() {
            return new SummaryResult(Status.NONE, null, 0);
        }
    }

    /**
     * 화면에 보여줄 요약.
     *
     * @param llmStatus {@code OK} 든 {@code FALLBACK} 이든 둘 다 정상이다. 화면은
     *                  구분하지 않고, 이 값은 로그와 되짚기를 위해 남긴다
     */
    public record Summary(String headline, String summary, String gap, String confidence,
            String llmStatus) {

        static Summary from(Cached cached) {
            return new Summary(cached.headline(), cached.summary(), cached.gap(),
                    cached.confidence(), cached.llmStatus());
        }
    }

    /** 테스트가 지문 계산을 직접 확인할 수 있게 열어 둔다. */
    String fingerprintOf(FactPack factPack) {
        return fingerprint(factPack);
    }
}
