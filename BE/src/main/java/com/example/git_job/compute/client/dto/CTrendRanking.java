package com.example.git_job.compute.client.dto;

import java.util.List;

/**
 * {@code GET /internal/v1/c/trends/rankings}의 응답 (S15P21E102-346).
 *
 * <p>한 기간에 실제로 많이 관측된 기술을 C가 정렬해서 준다. 우리가 기술 목록을 보내지
 * 않는 것이 요점이다 — 보내면 답이 "우리가 고른 것들 중의 순위"가 되고, 그것은 화면이
 * 물으려던 질문이 아니다.</p>
 *
 * <p>{@code dataStatus}는 C가 저장해 둔 판정을 그대로 옮긴 것이다. 값이 있는데 표본이
 * 얇은 것과 값이 없는 것은 다른 사실이라, BE가 이것을 READY로 올리지 않는다
 * (S15P21E102-327).</p>
 */
public record CTrendRanking(
        String source,
        String granularity,
        String period,
        /**
         * 이 출처가 실제로 게시한 기간 목록, 오름순 (S15P21E102-329).
         *
         * <p>화면이 기간을 옮기려면 어디로 갈 수 있는지 알아야 한다. 달력으로 계산하면
         * 아직 집계되지 않은 주를 물어 값이 있는데도 빈 카드가 뜬다.</p>
         */
        List<String> availablePeriods,
        /** 순위에 쓴 <b>필드의</b> 단위. snapshot 의 headline {@code unit}과 다르다. */
        String unit,
        /**
         * 이 기간의 모집단. 주차마다 크기가 달라(2026-08-31 = 4,045 / 09-07 = 133)
         * 이것 없이는 raw count 를 기간끼리 비교하게 된다.
         */
        Long sampleRepoCount,
        String registryVersion,
        Integer technologyPopulation,
        List<Technology> technologies
) {

    public record Technology(
            String techId,
            /** Registry에 없는 기술이면 {@code null}이다. 이름을 지어내지 않는다. */
            String displayName,
            int rank,
            long value,
            String dataStatus
    ) {
    }
}
