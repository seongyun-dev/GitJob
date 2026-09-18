package com.example.git_job.compute.client.dto;

import java.util.List;

/**
 * {@code POST /internal/v1/c/job-cohorts/resolve}의 요청 (S15P21E102-279, -338).
 *
 * <p>시각을 보내지 않는 selector 형식을 쓴다. 전체 {@code CohortCriteria}도 받아주지만
 * 그쪽은 {@code as_of}를 호출자가 정해야 하고, 그러면 B가 "언제까지의 공고인지"를
 * 결정하게 된다. 그 결정은 C의 것이다 — C가 검증을 통과한 입력의 최신 시각을 고른다.</p>
 *
 * <p>필터가 없으면 빈 배열을 보낸다. C의 {@code regions}·{@code career_levels}는
 * {@code tuple} 이고 기본값이 {@code ()}이므로 빈 배열이 곧 "전체"다. {@code null}을
 * 보내면 타입이 맞지 않아 422가 난다.</p>
 *
 * <p>{@code purpose}는 어느 질문인지를 고른다. 직무 코호트({@code ACTIVE_MATCHING})와
 * 시장 전체({@code CURRENT_MARKET})는 분모가 다르므로 요청에 드러나야 한다. 시장에
 * {@code targetRole}을 실으면 C가 422를 준다 — 역할을 받는 순간 시장이 아니라 직무
 * 코호트가 되고, 저장된 lineage가 실제 모집단과 어긋나기 때문이다.</p>
 */
public record CohortSelector(
        String schemaVersion,
        String targetRole,
        String purpose,
        List<String> sources,
        List<String> regions,
        List<String> careerLevels
) {

    public static final String SCHEMA_VERSION = "job-cohort-resolve-selector/v1";
    public static final String ACTIVE_MATCHING = "ACTIVE_MATCHING";
    public static final String CURRENT_MARKET = "CURRENT_MARKET";

    /**
     * 공식 현재 시장의 모집단.
     *
     * <p>C는 출처를 코드에 고정하지 않고 criteria로 받는다. 그래서 "무엇이 공식인지"는
     * 부르는 쪽이 정해야 하고, 그 자리가 여기다. 생략하면 C는 전체 출처라는 다른 범위로
     * 읽으며 그 범위는 intake가 미리 계산해 두지도 않는다.</p>
     *
     * <p>WORKNET·GAMEJOB·CAREER는 현재 공식 모집단이 아니다.</p>
     */
    public static final List<String> OFFICIAL_MARKET_SOURCES = List.of("JOBKOREA", "SARAMIN");

    /** 직무 코호트. 출처를 좁히지 않으므로 {@code sources}는 보내지 않는다. */
    public static CohortSelector activeMatching(String targetRole, List<String> regions,
                                                List<String> careerLevels) {
        return new CohortSelector(SCHEMA_VERSION, targetRole, ACTIVE_MATCHING, null,
                copyOrEmpty(regions), copyOrEmpty(careerLevels));
    }

    /** 현재 시장. 직무는 없어야 하고 모집단은 공식 출처로 명시한다. */
    public static CohortSelector currentMarket(List<String> regions, List<String> careerLevels) {
        return new CohortSelector(SCHEMA_VERSION, null, CURRENT_MARKET,
                OFFICIAL_MARKET_SOURCES, copyOrEmpty(regions), copyOrEmpty(careerLevels));
    }

    private static List<String> copyOrEmpty(List<String> values) {
        return values == null ? List.of() : List.copyOf(values);
    }
}
