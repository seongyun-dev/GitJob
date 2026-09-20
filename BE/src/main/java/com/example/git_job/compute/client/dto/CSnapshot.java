package com.example.git_job.compute.client.dto;

import java.util.List;
import java.util.Map;

/**
 * {@code GET /internal/v1/c/snapshots/{id}}의 응답 (S15P21E102-279).
 *
 * <p>{@code payload}의 모양은 {@code kind}마다 다르다. 여기서는 공개 API가 실제로 읽는
 * 필드만 선언한다. C는 계약을 additive로 늘리므로(새 필드가 붙는다) 모르는 필드는
 * 무시하도록 매퍼를 맞춰 두었다 -- 새 필드 하나에 화면이 죽으면 안 된다.</p>
 *
 * <p>개인 결과는 {@code user_id}를 함께 보내야 하고, 남의 것이면 C가 존재 여부를
 * 드러내지 않도록 404를 준다. 그 404를 그대로 404로 옮기는 것이 B의 일이다.</p>
 */
public record CSnapshot(String snapshotId, String kind, Recommendation payload) {

    /**
     * {@code recommendation-snapshot/v2~v3}에서 화면이 쓰는 것만.
     *
     * <p>{@code currentCount}가 "지금 필수 전체 충족 공고 수"다. 이 값을 B가 목록에서
     * 세지 않는다 -- 세는 순간 C의 부합 판정을 다시 구현하는 것이 되고, 페이지 단위로
     * 세면 분모도 틀린다.</p>
     */
    public record Recommendation(
            String userId,
            String analysisId,
            String cohortId,
            /** {@code READY} · {@code PARTIAL} · {@code NO_CANDIDATES} · {@code INSUFFICIENT_DATA} · {@code INSUFFICIENT_EVIDENCE}. */
            String status,
            int currentCount,
            List<Candidate> candidates,
            Demand demand,
            Gap gap,
            /** 확인된 기술만 키가 있다. 없는 키는 "미보유"가 아니라 "미판정"이다. */
            Map<String, String> personalLevels,
            Map<String, String> assessmentCeilings,
            List<String> dataGaps,
            Explanation explanation
    ) {
    }

    public record Candidate(
            String techId,
            int rank,
            /**
             * {@code NOT_HELD} · {@code L0} · {@code PERSONAL_LEVEL_UNKNOWN}.
             *
             * <p>{@code PERSONAL_LEVEL_UNKNOWN}은 S15P21E102-354에서 생긴 값이다.
             * 저장소에서 관측됐거나 미평가라 개인 Level이 없는 기술이며, 미보유로
             * 단정하지 않고 "아직 직접 쓴 적 없는 기술"로 추천한다.</p>
             */
            String evidenceStatus,
            TechnologyDemand demand,
            WhatIf whatIf,
            List<String> prerequisiteTechIds,
            List<String> missingPrerequisiteTechIds,
            List<String> unknownPrerequisiteTechIds,
            List<String> reasonCodes,
            List<String> dataGaps
    ) {
    }

    /**
     * 후보 하나를 요구 수준까지 채웠다고 가정했을 때의 변화.
     *
     * <p>{@code increasedCount}와 {@code newlyMatchedJobIds}는 같은 계산에서 나온 쌍이다.
     * 화면의 "증가 건수"와 "신규 부합 공고 목록"이 어긋나면 둘을 다른 Snapshot에서
     * 읽었다는 뜻이다.</p>
     */
    public record WhatIf(
            String techId,
            int denominator,
            int currentCount,
            int projectedCount,
            int increasedCount,
            List<String> newlyMatchedJobIds,
            List<String> dataGaps
    ) {
    }

    public record Demand(
            String cohortId,
            String status,
            int denominator,
            Integer inputCount,
            Integer duplicateCount,
            Integer excludedCount,
            Integer reviewCount,
            Integer matchingCount,
            Map<String, Object> criteria,
            List<TechnologyDemand> technologies
    ) {
        /** 기존 테스트와 recommendation snapshot v2의 최소 payload 호환. */
        public Demand(String cohortId, String status, int denominator,
                      Map<String, Object> criteria, List<TechnologyDemand> technologies) {
            this(cohortId, status, denominator, null, null, null, null, null,
                    criteria, technologies);
        }
    }

    public record TechnologyDemand(
            String techId,
            int rank,
            int requiredCount,
            int preferredCount,
            int generalCount,
            int totalCount,
            double requiredRatio,
            double preferredRatio,
            double generalRatio,
            double totalRatio
    ) {
    }

    /**
     * {@code technology-gap/v2}. 수요 기술을 보유 정책 하나로 나눈 결과다.
     *
     * <p>{@code UNKNOWN}은 부족이 아니다. 평가하지 않은 기술이라는 뜻이고, 부족으로
     * 세면 화면이 "이 기술이 없다"고 단정한다.</p>
     */
    public record Gap(
            String schemaVersion,
            List<String> heldTechIds,
            List<GapTechnology> technologies,
            List<String> dataGaps
    ) {
    }

    public record GapTechnology(
            String techId,
            /** {@code HELD} · {@code NOT_HELD} · {@code UNKNOWN}. */
            String status,
            List<String> reasonCodes,
            List<String> dataGaps
    ) {
    }

    /** 추천 근거. 점수가 아니라 문장으로만 화면에 나간다. */
    public record Explanation(String mode, List<Fact> facts) {
    }

    public record Fact(String factId, String kind, String techId, String text) {
    }
}
