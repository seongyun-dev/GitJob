package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.client.dto.CMatching;
import java.util.List;
import java.util.Objects;

/**
 * 공고 매칭 목록과 상세 (화면 02·16) (S15P21E102-279).
 *
 * <p>C의 판정을 화면 어휘로 옮기기만 한다. 부합 여부를 다시 세지 않고, C가 주지 않는
 * 수치는 {@code null}로 둔다 -- 비어 있는 자리를 0으로 채우면 화면이 "측정했더니
 * 0이었다"로 읽는다.</p>
 */
public record JobMatchResponse(
        String dataStatus,
        String statusReason,
        Integer retryAfterSec,
        Basis basis,
        Summary summary,
        List<String> dataGaps,
        int page,
        int perPage,
        boolean hasNext,
        List<Item> items
) {

    public static JobMatchResponse pending(ComputeState state, Basis basis, int page, int perPage) {
        return new JobMatchResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), basis, null, List.of(), page, perPage, false, List.of());
    }

    public static JobMatchResponse of(ComputeState state, Basis basis, Summary summary,
                                      CMatching matching, int page, int perPage) {
        return new JobMatchResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), basis, summary,
                nullToEmpty(matching.dataGaps()), page, perPage, matching.hasNext(),
                matching.items() == null ? List.of()
                        : matching.items().stream().map(Item::of).toList());
    }

    /**
     * 상단 KPI.
     *
     * @param fullMatchCount    필수 전체 충족. RECOMMENDATION Snapshot의 {@code current_count}다.
     * @param nearMatchCount    <b>C가 주지 않는다.</b> 목록에서 세면 그것이 부합 판정 재계산이고,
     *                          페이지 단위로 세면 분모도 틀린다. 계약 §6-1의 미결 항목이다.
     * @param lowMatchCount     같은 이유로 {@code null}.
     * @param excludedConditionalCount 조건부라 목록에서 빠진 건수. 사라진 공고가 몇 건인지
     *                          화면이 말할 수 있어야 한다.
     */
    public record Summary(
            int totalCount,
            Integer fullMatchCount,
            Integer nearMatchCount,
            Integer lowMatchCount,
            int conditionalCount,
            int excludedConditionalCount
    ) {
    }

    public record Item(
            String jobId,
            String title,
            String companyName,
            String sourceSite,
            String sourceUrl,
            String region,
            String careerLevel,
            String deadline,
            /** {@code ELIGIBLE} · {@code CONDITIONAL}. */
            String eligibility,
            /** {@code FULL} · {@code PARTIAL} · {@code NONE} · {@code UNKNOWN} · {@code NOT_APPLICABLE}. */
            String requiredStatus,
            Double fulfillmentRatio,
            Condition required,
            Condition preferred
    ) {

        public static Item of(CMatching.Item item) {
            CMatching.Job job = item.job();
            return new Item(
                    job == null ? null : job.jobId(),
                    job == null ? null : job.title(),
                    job == null ? null : job.companyName(),
                    job == null ? null : job.sourceSite(),
                    job == null ? null : job.sourceUrl(),
                    job == null ? null : job.region(),
                    job == null ? null : job.careerLevel(),
                    job == null ? null : job.deadline(),
                    job == null ? null : job.eligibility(),
                    item.requiredStatus(),
                    item.required() == null ? null : item.required().fulfillmentRatio(),
                    Condition.of(item.required()),
                    Condition.of(item.preferred()));
        }
    }

    /**
     * 필수 또는 우대 요건.
     *
     * <p>{@code unknownCount}를 {@code unsatisfiedCount}에 더하지 않는다. "요구를 해석하지
     * 못했다"와 "충족하지 못했다"는 사용자에게 다른 말이고, 합치면 없는 부족이 생긴다.</p>
     */
    public record Condition(
            int satisfiedCount,
            int unsatisfiedCount,
            int unknownCount,
            Double fulfillmentRatio,
            List<Clause> clauses,
            List<Unresolved> unresolved
    ) {

        static Condition of(CMatching.Condition condition) {
            if (condition == null) {
                return null;
            }
            return new Condition(
                    condition.satisfiedCount(),
                    condition.unsatisfiedCount(),
                    condition.unknownCount(),
                    condition.fulfillmentRatio(),
                    condition.clauses() == null ? List.of()
                            : condition.clauses().stream().map(Clause::of).toList(),
                    condition.unresolved() == null ? List.of()
                            : condition.unresolved().stream().map(Unresolved::of).toList());
        }
    }

    /**
     * 요구 한 절과 그 판정.
     *
     * @param mark {@code HAVE} · {@code WEAK} · {@code NONE} · {@code UNKNOWN}.
     *             {@code UNKNOWN}을 {@code NONE}으로 접지 않는다 -- 그렇게 하면 화면이
     *             판정하지 않은 기술을 미보유로 표시한다. {@code WEAK}는 Evidence는 있는데
     *             요구 Level에 미치지 못한 경우이며, C가 상한을 적용했다고 표시한 절이다.
     */
    public record Clause(
            String mark,
            List<String> techIds,
            String requiredLevel,
            List<String> heldTechIds,
            List<String> missingTechIds,
            List<String> unknownTechIds
    ) {

        static Clause of(CMatching.Clause clause) {
            CMatching.Requirement requirement = clause.clause();
            return new Clause(
                    mark(clause),
                    requirement == null ? List.of() : nullToEmpty(requirement.techIds()),
                    requirement == null ? null : requirement.requiredLevel(),
                    nullToEmpty(clause.heldTechIds()),
                    nullToEmpty(clause.missingTechIds()),
                    nullToEmpty(clause.unknownTechIds()));
        }

        private static String mark(CMatching.Clause clause) {
            if (Objects.equals(clause.status(), "SATISFIED")) {
                return "HAVE";
            }
            if (Objects.equals(clause.status(), "UNKNOWN")) {
                return "UNKNOWN";
            }
            // 미충족인데 C가 판정 상한을 적용했다면, 보유 자체가 없는 것이 아니라 요구
            // Level에 닿지 못한 것이다. 화면이 그 둘을 다르게 표시한다.
            return clause.assessmentCeilingApplied() ? "WEAK" : "NONE";
        }
    }

    /** 요구 자체를 해석하지 못한 절. 부족으로 세지 않고 별도로 보여 준다. */
    public record Unresolved(String requirementKind, String reason, List<String> knownTechIds) {

        static Unresolved of(CMatching.Unresolved unresolved) {
            return new Unresolved(unresolved.requirementKind(), unresolved.reason(),
                    nullToEmpty(unresolved.knownTechIds()));
        }
    }

    /** 공고 매칭 상세. 항목 모양은 목록과 같다. */
    public record Detail(String dataStatus, String statusReason, Integer retryAfterSec,
            Basis basis, Item item) {

        public static Detail pending(ComputeState state, Basis basis) {
            return new Detail(state.dataStatus(), state.statusReason(), state.retryAfterSec(),
                    basis, null);
        }

        public static Detail of(ComputeState state, Basis basis, CMatching.Item item) {
            return new Detail(state.dataStatus(), state.statusReason(), state.retryAfterSec(),
                    basis, Item.of(item));
        }
    }

    private static <T> List<T> nullToEmpty(List<T> values) {
        return values == null ? List.of() : values;
    }
}
