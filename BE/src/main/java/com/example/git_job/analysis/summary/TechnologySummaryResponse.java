package com.example.git_job.analysis.summary;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * 요약 서비스가 돌려주는 것.
 *
 * <p>이 호출은 <b>언제나 200</b> 이다. 모델이 죽었거나 느리거나 틀린 문장을 써도
 * {@code llm_status: FALLBACK} 으로 문장이 온다. 그러므로 BE 가 다룰 실패는 연결
 * 불가와 timeout 둘뿐이다.</p>
 *
 * <p>{@link JsonIgnoreProperties} 를 둔 것은 저쪽이 진단용 필드를 늘릴 수 있기
 * 때문이다. 우리가 모르는 필드가 생겼다고 요약이 실패할 이유는 없다.</p>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record TechnologySummaryResponse(
        @JsonProperty("llm_status") String llmStatus,
        @JsonProperty("summary") Summary summary,
        @JsonProperty("cache_key") String cacheKey,
        @JsonProperty("model") String model,
        @JsonProperty("prompt_version") String promptVersion,
        @JsonProperty("attempts") List<Attempt> attempts,
        /** 모델이 낸 등급이 규칙에서 나온 값과 달랐을 때만 찬다. 보통 {@code null}. */
        @JsonProperty("model_confidence") String modelConfidence
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Summary(
            @JsonProperty("tech_id") String techId,
            @JsonProperty("headline") String headline,
            @JsonProperty("summary") String summary,
            @JsonProperty("gap") String gap,
            @JsonProperty("used_highlights") List<Integer> usedHighlights,
            @JsonProperty("confidence") String confidence
    ) {
    }

    /**
     * 버려진 시도와 그 이유.
     *
     * <p>카드에 보여줄 값이 아니라 로그다. {@code failure_codes} 가 자주 같은 값을
     * 내면 프롬프트 문제이고, 그것은 AI 쪽에서 고칠 일이다.</p>
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Attempt(
            @JsonProperty("temperature") double temperature,
            @JsonProperty("failure_codes") List<String> failureCodes,
            @JsonProperty("error") String error
    ) {
    }
}
