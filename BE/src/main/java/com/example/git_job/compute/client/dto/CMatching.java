package com.example.git_job.compute.client.dto;

import java.util.List;

/**
 * 공고별 부분 부합 결과 (S15P21E102-279).
 *
 * <p>{@code GET .../matching-job-postings}(목록)와 {@code .../matching-job-posting}(상세)의
 * 응답이다. 두 endpoint가 같은 저장 평가를 읽으므로 항목 모양이 같고, 그래서
 * {@link Item}을 공유한다.</p>
 *
 * <p>여기 있는 판정을 B가 다시 계산하지 않는다. {@code requiredStatus}와 절별
 * {@code status}가 C의 결론이고, B는 화면 어휘로 옮기기만 한다.</p>
 */
public record CMatching(
        String snapshotId,
        String calculationSnapshotId,
        String cohortId,
        int totalCount,
        int conditionalCount,
        int excludedConditionalCount,
        Integer currentCount,
        CSnapshot.Demand demand,
        int page,
        int size,
        boolean hasNext,
        List<Item> items,
        List<String> dataGaps
) {

    /** 상세 응답. 목록과 같은 항목 하나를 준다. */
    public record Detail(String snapshotId, String calculationSnapshotId, String cohortId,
            String analysisId, Item item) {
    }

    /**
     * 공고 하나의 평가.
     *
     * <p>충족 비율은 여기가 아니라 {@link Condition#fulfillmentRatio()}에 있다. 필수와
     * 우대는 분모가 다르므로 하나로 합친 비율을 만들지 않는다.</p>
     */
    public record Item(Job job, Condition required, Condition preferred,
            /** {@code FULL} · {@code PARTIAL} · {@code NONE} · {@code UNKNOWN} · {@code NOT_APPLICABLE}. */
            String requiredStatus) {
    }

    public record Job(
            String jobId,
            String sourceSite,
            String sourceUrl,
            String companyName,
            String title,
            String region,
            String careerLevel,
            String deadline,
            String collectedAt,
            /** {@code ELIGIBLE} · {@code CONDITIONAL}. */
            String eligibility,
            List<String> eligibilityReasons
    ) {
    }

    /**
     * 필수 또는 우대 요건 묶음.
     *
     * <p>{@code unknownCount}를 {@code unsatisfiedCount}에 더하지 않는다. "요구를 해석하지
     * 못했다"와 "충족하지 못했다"는 사용자에게 다른 말이다.</p>
     */
    public record Condition(
            List<Clause> clauses,
            List<Unresolved> unresolved,
            int satisfiedCount,
            int unsatisfiedCount,
            int unknownCount,
            Double fulfillmentRatio
    ) {
    }

    public record Clause(
            /** 요구 자체. 어떤 기술을 어떤 수준으로 요구했는지가 여기 있다. */
            Requirement clause,
            /** {@code SATISFIED} · {@code UNSATISFIED} · {@code UNKNOWN}. */
            String status,
            List<String> heldTechIds,
            List<String> missingTechIds,
            List<String> unknownTechIds,
            String verdict,
            boolean assessmentCeilingApplied
    ) {
    }

    /**
     * 요구 절 하나.
     *
     * @param requiredLevel {@code null}이면 공고가 수준을 말하지 않은 것이다. 수준 없음을
     *                      L1 같은 기본값으로 채우면 화면이 없는 요구를 만들어 낸다.
     */
    public record Requirement(String operator, List<String> techIds, String requiredLevel) {
    }

    /** 요구 자체를 해석하지 못한 절. 부족으로 세면 안 되는 자리다. */
    public record Unresolved(String requirementKind, String reason, List<String> knownTechIds) {
    }
}
