package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.client.dto.CTrendRanking;
import java.util.List;

/**
 * 한 기간에 실제로 많이 관측된 기술 (S15P21E102-346).
 *
 * <p>화면이 기술 후보를 고르지 않는다. 순위는 Registry 전체를 놓고 그 기간의 실측값을
 * 정렬한 결과이고, 그래서 기간이 바뀌면 기술 종류도 바뀐다.</p>
 *
 * <p>값과 순위를 다시 만들지 않는다. C가 저장해 둔 관측을 그대로 옮긴다 — 여기서 두
 * 기간을 빼거나 비율로 바꾸면 화면의 숫자와 근거가 갈라진다.</p>
 */
public record TrendRankingResponse(
        String dataStatus,
        String statusReason,
        Integer retryAfterSec,
        String sourceId,
        String granularity,
        String period,
        /**
         * 이 출처가 실제로 게시한 기간 목록, 오름순 (S15P21E102-329).
         *
         * <p>카드 안의 기간 이동이 이 목록으로 움직인다. 값이 없을 때도 실어 보낸다 —
         * 아직 집계되지 않은 기간으로 옮겨 간 화면이 되돌아올 수 있어야 한다.</p>
         */
        List<String> availablePeriods,
        /** 순위 값의 단위. GitHub 출처는 {@code REPOSITORIES}(그 기술이 관측된 저장소 수). */
        String unit,
        /** 이 기간의 모집단. 화면은 {@code value / sampleRepoCount}로 비율을 적는다. */
        Long sampleRepoCount,
        /** 순위를 매긴 모집단 크기. "상위 10개"가 무엇 중의 10개인지 밝힌다. */
        Integer technologyPopulation,
        List<Technology> technologies
) {

    public record Technology(
            String techId,
            String displayName,
            int rank,
            long value,
            /**
             * C가 내린 품질 판정. 표본이 얇아도 값은 값이므로 순위에 남기되, 상태를
             * 올려 적지 않는다 (S15P21E102-327).
             */
            String dataStatus
    ) {
    }

    /**
     * {@code sourceId}는 <b>화면이 물은 이름</b>이다. C 출처 이름을 되돌려 주면 주간·월별이
     * 같은 {@code GITHUB_GH_ARCHIVE}로 보여 두 카드가 구별되지 않고, 값이 없을 때와
     * 있을 때의 응답이 서로 다른 이름을 쓰게 된다.
     */
    public static TrendRankingResponse of(ComputeState state, String sourceId,
                                          CTrendRanking ranking) {
        return new TrendRankingResponse(
                state.dataStatus(), state.statusReason(), state.retryAfterSec(),
                sourceId, ranking.granularity(), ranking.period(),
                periods(ranking), ranking.unit(), ranking.sampleRepoCount(),
                ranking.technologyPopulation(),
                ranking.technologies().stream()
                        .map(item -> new Technology(item.techId(), item.displayName(),
                                item.rank(), item.value(), item.dataStatus()))
                        .toList());
    }

    /**
     * 값이 없지만 C 는 답했을 때. 기간 목록은 그대로 실어 보낸다.
     *
     * <p>비었다고 목록까지 버리면 아직 집계되지 않은 기간으로 옮겨 간 화면이 되돌아올
     * 길을 잃는다 — 그러면 기간 이동이 한 방향 함정이 된다.</p>
     */
    public static TrendRankingResponse pending(ComputeState state, String sourceId,
                                               String granularity, CTrendRanking ranking) {
        return new TrendRankingResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), sourceId, granularity,
                ranking == null ? null : ranking.period(), periods(ranking),
                ranking == null ? null : ranking.unit(),
                ranking == null ? null : ranking.sampleRepoCount(),
                null, List.of());
    }

    /** C 가 답하지 못했을 때. 요청한 기간만 남겨 화면이 무엇을 물었는지 보인다. */
    public static TrendRankingResponse pending(ComputeState state, String sourceId,
                                               String granularity, String period) {
        return new TrendRankingResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), sourceId, granularity, period, List.of(),
                null, null, null, List.of());
    }

    private static List<String> periods(CTrendRanking ranking) {
        return ranking == null || ranking.availablePeriods() == null
                ? List.of() : ranking.availablePeriods();
    }
}
