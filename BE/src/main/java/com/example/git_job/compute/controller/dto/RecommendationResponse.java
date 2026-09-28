package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.client.dto.CSnapshot;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 다음 학습 기술 후보 (화면 10) (S15P21E102-279).
 *
 * <p>점수를 노출하지 않는다. 근거는 C의 설명 Fact에서 온 <b>문장</b>이고, 순위는 C가 정한
 * 사전식 비교의 결과다. 여기에 숫자 점수를 더하면 화면이 "몇 점짜리 추천"으로 읽히는데,
 * 그런 점수는 계산된 적이 없다.</p>
 *
 * <p>{@code targetLevel}이 없다. "L0 → L2" 표기에 필요한 목표 Level을 C가 주지 않기
 * 때문이며, 만들어 넣으면 없는 요구를 화면이 말하게 된다. 계약 §6-3의 미결 항목이다.</p>
 */
public record RecommendationResponse(
        String dataStatus,
        String statusReason,
        Integer retryAfterSec,
        Basis basis,
        List<Candidate> candidates,
        List<String> dataGaps
) {

    public static RecommendationResponse pending(ComputeState state, Basis basis) {
        return new RecommendationResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), basis, List.of(), List.of());
    }

    public static RecommendationResponse of(ComputeState state, Basis basis,
                                            CSnapshot.Recommendation recommendation) {
        Map<String, List<String>> reasons = reasonsByTech(recommendation);
        Map<String, String> personalLevels = recommendation.personalLevels() == null
                ? Map.of() : recommendation.personalLevels();
        List<CSnapshot.Candidate> candidates = recommendation.candidates() == null
                ? List.of() : recommendation.candidates();
        return new RecommendationResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), basis,
                candidates.stream()
                        .map(candidate -> Candidate.of(candidate,
                                personalLevels.get(candidate.techId()),
                                reasons.getOrDefault(candidate.techId(), List.of())))
                        .toList(),
                recommendation.dataGaps() == null ? List.of() : recommendation.dataGaps());
    }

    /**
     * 기술별 설명 문장.
     *
     * <p>{@code techId}가 없는 Fact는 특정 후보의 근거가 아니라 전체 계산에 대한 설명이라
     * 후보 줄에 붙이지 않는다.</p>
     */
    private static Map<String, List<String>> reasonsByTech(CSnapshot.Recommendation recommendation) {
        if (recommendation.explanation() == null || recommendation.explanation().facts() == null) {
            return Map.of();
        }
        return recommendation.explanation().facts().stream()
                .filter(fact -> fact.techId() != null && fact.text() != null)
                .collect(Collectors.groupingBy(CSnapshot.Fact::techId,
                        Collectors.mapping(CSnapshot.Fact::text, Collectors.toList())));
    }

    /**
     * 후보 하나.
     *
     * @param personalLevel {@code null}은 미판정이다. 추천 대상이라고 해서 미보유로 단정하지
     *                      않는다 -- C의 {@code evidenceStatus}가 그 구분을 갖고 있다.
     * @param unknownPrerequisiteTechIds 선행 기술인데 판정하지 못한 것. 누락된 선행
     *                      ({@code missing})과 섞지 않는다.
     */
    public record Candidate(
            String techId,
            int rank,
            String personalLevel,
            /**
             * {@code NOT_HELD} · {@code L0} · {@code PERSONAL_LEVEL_UNKNOWN}.
             *
             * <p>{@code PERSONAL_LEVEL_UNKNOWN}은 S15P21E102-354에서 생긴 값이다.
             * 저장소에서 관측됐거나 미평가라 개인 Level이 없는 기술이며, 미보유로
             * 단정하지 않고 "아직 직접 쓴 적 없는 기술"로 추천한다.</p>
             */
            String evidenceStatus,
            Demand demand,
            WhatIfResponse.Counts whatIf,
            Impact impact,
            List<String> prerequisiteTechIds,
            List<String> missingPrerequisiteTechIds,
            List<String> unknownPrerequisiteTechIds,
            List<String> reasonCodes,
            List<String> reasons,
            List<String> dataGaps
    ) {

        static Candidate of(CSnapshot.Candidate candidate, String personalLevel,
                            List<String> reasons) {
            CSnapshot.TechnologyDemand demand = candidate.demand();
            CSnapshot.WhatIf whatIf = candidate.whatIf();
            return new Candidate(
                    candidate.techId(),
                    candidate.rank(),
                    personalLevel,
                    candidate.evidenceStatus(),
                    demand == null ? null : new Demand(demand.requiredCount(),
                            demand.requiredRatio(), demand.rank()),
                    whatIf == null ? null : new WhatIfResponse.Counts(whatIf.currentCount(),
                            whatIf.projectedCount(), whatIf.increasedCount()),
                    candidate.impact() == null ? null : new Impact(
                            candidate.impact().requiredCount(),
                            candidate.impact().preferredCount(),
                            candidate.impact().affectedCount()),
                    nullToEmpty(candidate.prerequisiteTechIds()),
                    nullToEmpty(candidate.missingPrerequisiteTechIds()),
                    nullToEmpty(candidate.unknownPrerequisiteTechIds()),
                    nullToEmpty(candidate.reasonCodes()),
                    reasons,
                    nullToEmpty(candidate.dataGaps()));
        }
    }

    /** 이 기술을 요구한 공고. 비율의 분모는 같은 COHORT의 공고 수다. */
    public record Demand(int requiredCount, double requiredRatio, int rank) {
    }

    /** 서로 다른 공고 기준. 필수·우대 공고가 겹치므로 affectedCount는 합산값이 아니다. */
    public record Impact(int requiredCount, int preferredCount, int affectedCount) {
    }

    private static <T> List<T> nullToEmpty(List<T> values) {
        return values == null ? List.of() : values;
    }
}
