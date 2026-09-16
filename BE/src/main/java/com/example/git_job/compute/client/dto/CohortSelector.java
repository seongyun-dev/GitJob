package com.example.git_job.compute.client.dto;

import java.util.List;

/**
 * {@code POST /internal/v1/c/job-cohorts/resolve}의 요청 (S15P21E102-279).
 *
 * <p>시각을 보내지 않는 selector 형식을 쓴다. 전체 {@code CohortCriteria}도 받아주지만
 * 그쪽은 {@code as_of}를 호출자가 정해야 하고, 그러면 B가 "언제까지의 공고인지"를
 * 결정하게 된다. 그 결정은 C의 것이다 — C가 검증을 통과한 입력의 최신 시각을 고른다.</p>
 *
 * <p>필터가 없으면 빈 배열을 보낸다. C의 {@code regions}·{@code career_levels}는
 * {@code tuple} 이고 기본값이 {@code ()}이므로 빈 배열이 곧 "전체"다. {@code null}을
 * 보내면 타입이 맞지 않아 422가 난다.</p>
 */
public record CohortSelector(
        String schemaVersion,
        String targetRole,
        List<String> regions,
        List<String> careerLevels
) {

    public static final String SCHEMA_VERSION = "job-cohort-resolve-selector/v1";

    public static CohortSelector of(String targetRole, List<String> regions,
                                    List<String> careerLevels) {
        return new CohortSelector(SCHEMA_VERSION, targetRole,
                copyOrEmpty(regions), copyOrEmpty(careerLevels));
    }

    private static List<String> copyOrEmpty(List<String> values) {
        return values == null ? List.of() : List.copyOf(values);
    }
}
