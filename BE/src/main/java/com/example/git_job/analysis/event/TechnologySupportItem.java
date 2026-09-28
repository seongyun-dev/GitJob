package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * 그 Rule Pack 이 기술 하나를 어디까지 판정할 수 있었는지 (S15P21E102-279 후속).
 *
 * <p>{@code repository-analysis-result/v2} 부터 실린다. 이 값이 필요한 이유는 판정
 * 상한 때문이다. 규칙이 의존성 선언까지만 보는 기술을 두고 "관측된 최고 Level"을
 * 상한으로 삼으면, 규칙이 아예 볼 수 없었던 구간까지 "판정했는데 없었다"로 단정하게
 * 된다. C 의 {@code assessment_ceiling} 이 이 값에서 나온다.</p>
 *
 * @param coverage {@code SUPPORTED}·{@code PARTIAL}·{@code UNSUPPORTED}.
 *                 {@code UNSUPPORTED} 는 규칙이 없어 보지 못한 기술이며, 평가 범위에
 *                 넣으면 안 된다 -- 보지 못한 것과 없는 것은 다르다.
 */
public record TechnologySupportItem(
        @JsonProperty("tech_id") String techId,
        @JsonProperty("evaluation_scope") String evaluationScope,
        @JsonProperty("required_fact_types") List<String> requiredFactTypes,
        @JsonProperty("max_supported_level") String maxSupportedLevel,
        @JsonProperty("coverage") String coverage,
        @JsonProperty("limitations") List<String> limitations
) {

    public TechnologySupportItem {
        if (techId == null || techId.isBlank()) {
            throw new IllegalArgumentException("techId must be non-blank");
        }
        if (maxSupportedLevel == null || !maxSupportedLevel.matches("L[0-3]")) {
            throw new IllegalArgumentException("maxSupportedLevel must be L0..L3");
        }
        if (coverage == null
                || !List.of("SUPPORTED", "PARTIAL", "UNSUPPORTED").contains(coverage)) {
            throw new IllegalArgumentException("coverage must be SUPPORTED, PARTIAL or UNSUPPORTED");
        }
        requiredFactTypes = List.copyOf(requiredFactTypes == null ? List.of() : requiredFactTypes);
        limitations = List.copyOf(limitations == null ? List.of() : limitations);
    }

    /** 평가 범위에 넣을 기술인지. 규칙이 없는 기술은 판정한 것이 아니다. */
    public boolean evaluated() {
        return !"UNSUPPORTED".equals(coverage);
    }
}
