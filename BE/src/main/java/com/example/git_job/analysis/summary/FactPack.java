package com.example.git_job.analysis.summary;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.LocalDate;
import java.util.List;

/**
 * 기술 하나를 요약해 달라고 로컬 LLM 서비스에 보내는 입력.
 *
 * <p>{@code technology-summary-request/v1}. 받는 쪽은 모르는 필드를 422 로 거절하므로
 * 이름과 모양이 계약과 정확히 같아야 한다.</p>
 *
 * <h2>근거 원문을 보내지 않는다</h2>
 *
 * <p>{@code spring-security} 한 기술이 근거 82 건을 낸다. 모델은 4B 에 컨텍스트가
 * 8K 라 그대로 넣으면 넘친다. 그래서 {@link Highlight} 로 <b>중복을 제거한 사실
 * 8개</b>까지만 싣는다.</p>
 *
 * <h2>사람을 지목하는 값이 없다</h2>
 *
 * <p>커밋 SHA, 이메일, GitHub 로그인, 코드 원문은 여기 없다. 요약에 필요하지
 * 않고, 이 객체는 그대로 프롬프트가 되기 때문이다. 사용자 식별자조차 이 밖에
 * 있다 -- 캐시 키는 사람을 구분해야 하지만 프롬프트는 그럴 이유가 없다.</p>
 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record FactPack(
        @JsonProperty("schema_version") String schemaVersion,
        @JsonProperty("locale") String locale,
        @JsonProperty("technology") Technology technology,
        @JsonProperty("authorship") String authorship,
        @JsonProperty("levels") List<LevelEvidence> levels,
        @JsonProperty("next_level") NextLevel nextLevel,
        @JsonProperty("highlights") List<Highlight> highlights,
        @JsonProperty("repositories") List<RepositoryRef> repositories,
        @JsonProperty("period") Period period
) {

    public static final String SCHEMA_VERSION = "technology-summary-request/v1";
    public static final String LOCALE = "ko-KR";

    /** 한 기술이 실을 수 있는 사실의 수. 계약의 상한이자 모델의 한계다. */
    public static final int MAX_HIGHLIGHTS = 8;

    public record Technology(
            @JsonProperty("tech_id") String techId,
            @JsonProperty("display_name") String displayName,
            @JsonProperty("repository_level") String repositoryLevel,
            @JsonProperty("personal_level") String personalLevel,
            @JsonProperty("registry_version") String registryVersion
    ) {
    }

    /**
     * 한 Level 에서 충족된 규칙들.
     *
     * @param mine 그 Level 의 근거 중 본인이 쓴 것이 있는지
     */
    public record LevelEvidence(
            @JsonProperty("level") String level,
            @JsonProperty("rules") List<String> rules,
            @JsonProperty("mine") boolean mine
    ) {
    }

    /**
     * 다음 Level 까지 무엇이 비었는지.
     *
     * <p>요약에서 가장 쓸모 있는 부분이다 -- "왜 L2 인가"보다 "왜 L3 가 아닌가"가
     * 사람에게 정보다. 받는 쪽이 {@code personal_level} 보다 위인지 검사하므로
     * 최고 Level 에 도달했으면 통째로 {@code null} 이어야 한다.</p>
     *
     * @param missing 덮이지 않은 절이 기대하던 값들. 규칙 이름이 아니라
     *                {@code @EnableMethodSecurity} 같은 실제 이름이다
     */
    public record NextLevel(
            @JsonProperty("level") String level,
            @JsonProperty("rule") String rule,
            @JsonProperty("missing") List<String> missing
    ) {
    }

    /**
     * 요약이 근거로 삼을 사실 하나.
     *
     * @param index 배열 순서 그대로 0..n-1. 모델이 세게 하지 않고 직접 넣어 주는
     *              이유는, 응답의 {@code used_highlights} 를 검사할 수 있게 하기
     *              위해서다
     * @param file  마지막 두 세그먼트로 줄인 경로. 전체 경로는 토큰만 먹는다
     * @param mine  본인이 쓴 근거인지. 기여 판정이 없으면 {@code false} 다 --
     *              그 구분은 {@code authorship} 이 이미 싣고 있다
     */
    public record Highlight(
            @JsonProperty("index") int index,
            @JsonProperty("fact_type") String factType,
            @JsonProperty("value") String value,
            @JsonProperty("file") String file,
            @JsonProperty("mine") boolean mine
    ) {
    }

    public record RepositoryRef(
            @JsonProperty("full_name") String fullName,
            @JsonProperty("mine") boolean mine
    ) {
    }

    /**
     * 본인이 이 기술을 건드린 기간.
     *
     * <p>본인 커밋만 센다. 저장소의 첫 커밋부터 재면 남이 쓴 기간까지 본인 것으로
     * 말하게 된다. 확인된 커밋이 없으면 이 객체 자체가 {@code null} 이고, 그때
     * 요약은 기간을 언급하지 않는다.</p>
     */
    public record Period(
            @JsonProperty("first") LocalDate first,
            @JsonProperty("last") LocalDate last,
            @JsonProperty("months") int months
    ) {
    }
}
