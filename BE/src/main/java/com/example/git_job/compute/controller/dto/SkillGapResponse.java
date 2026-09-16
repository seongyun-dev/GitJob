package com.example.git_job.compute.controller.dto;

import com.example.git_job.compute.client.dto.CSnapshot;
import java.util.List;
import java.util.Map;

/**
 * Skill Gap (화면 17) (S15P21E102-279).
 *
 * <h2>미판정은 부족이 아니다</h2>
 *
 * <p>C의 {@code UNKNOWN}은 "그 기술을 평가하지 않았다"는 뜻이다. 부족으로 세면 화면이
 * 사용자에게 "이 기술이 없다"고 단정하게 되므로, 요약의 부족 집계에서 빼고
 * {@code undeterminedCount}로 따로 센다. 이것이 인수 조건의 "미확정 Evidence/요구 수준을
 * 부족으로 단정하지 않음"이다.</p>
 *
 * <h2>fillDelta가 대부분 null인 이유</h2>
 *
 * <p>C는 What-if를 상위 3개 후보에만 계산한다. 나머지 행에 숫자를 만들어 넣으려면 B가
 * What-if를 다시 계산해야 하는데, 그것은 하지 않기로 한 일이다. 계약 §6-2의 미결
 * 항목이며, 그때까지 이 열은 세 행에만 값이 있다.</p>
 */
public record SkillGapResponse(
        String dataStatus,
        String statusReason,
        Integer retryAfterSec,
        Basis basis,
        Summary summary,
        List<Row> rows,
        List<String> dataGaps
) {

    public static SkillGapResponse pending(ComputeState state, Basis basis) {
        return new SkillGapResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), basis, null, List.of(), List.of());
    }

    public static SkillGapResponse of(ComputeState state, Basis basis,
                                      CSnapshot.Recommendation recommendation) {
        Map<String, CSnapshot.TechnologyDemand> demand = demandByTech(recommendation);
        Map<String, Integer> fillDelta = fillDeltaByTech(recommendation);
        Map<String, String> personalLevels = recommendation.personalLevels() == null
                ? Map.of() : recommendation.personalLevels();
        Map<String, String> ceilings = recommendation.assessmentCeilings() == null
                ? Map.of() : recommendation.assessmentCeilings();

        List<Row> rows = recommendation.gap() == null || recommendation.gap().technologies() == null
                ? List.of()
                : recommendation.gap().technologies().stream()
                        .map(technology -> Row.of(technology, demand.get(technology.techId()),
                                personalLevels.get(technology.techId()),
                                ceilings.get(technology.techId()),
                                fillDelta.get(technology.techId())))
                        .toList();

        return new SkillGapResponse(state.dataStatus(), state.statusReason(),
                state.retryAfterSec(), basis, Summary.of(rows), rows,
                recommendation.gap() == null || recommendation.gap().dataGaps() == null
                        ? List.of() : recommendation.gap().dataGaps());
    }

    private static Map<String, CSnapshot.TechnologyDemand> demandByTech(
            CSnapshot.Recommendation recommendation) {
        if (recommendation.demand() == null || recommendation.demand().technologies() == null) {
            return Map.of();
        }
        return recommendation.demand().technologies().stream()
                .collect(java.util.stream.Collectors.toMap(CSnapshot.TechnologyDemand::techId,
                        technology -> technology, (first, second) -> first));
    }

    /** 상위 3개 후보에만 값이 있다. 나머지 기술은 C가 계산하지 않았다. */
    private static Map<String, Integer> fillDeltaByTech(CSnapshot.Recommendation recommendation) {
        if (recommendation.candidates() == null) {
            return Map.of();
        }
        return recommendation.candidates().stream()
                .filter(candidate -> candidate.whatIf() != null)
                .collect(java.util.stream.Collectors.toMap(CSnapshot.Candidate::techId,
                        candidate -> candidate.whatIf().increasedCount(),
                        (first, second) -> first));
    }

    /**
     * 요약.
     *
     * <p>{@code gapCount}에 {@code undeterminedCount}가 들어가지 않는다. 그 둘을 합치면
     * 화면이 판정하지 않은 기술까지 "부족"으로 세게 된다.</p>
     */
    public record Summary(int requiredTechCount, int metCount, int noEvidenceCount,
            int levelShortCount, int gapCount, int undeterminedCount) {

        static Summary of(List<Row> rows) {
            int met = count(rows, "MET");
            int noEvidence = count(rows, "NO_EVIDENCE");
            int levelShort = count(rows, "LEVEL_SHORT");
            int undetermined = count(rows, "UNDETERMINED");
            return new Summary(rows.size(), met, noEvidence, levelShort,
                    noEvidence + levelShort, undetermined);
        }

        private static int count(List<Row> rows, String verdict) {
            return (int) rows.stream().filter(row -> verdict.equals(row.verdict())).count();
        }
    }

    /**
     * 기술 한 줄.
     *
     * @param personalLevel     {@code null}은 미보유가 아니라 미판정이다.
     * @param assessmentCeiling BE의 규칙이 배제할 수 있었던 최고 Level. 화면은 이 값 위를
     *                          "확인되지 않음"으로 표시해야 한다.
     * @param fillDelta         이 기술만 채웠을 때 늘어나는 공고 수. 행끼리 더하지 않는다 --
     *                          같은 공고가 여러 행에 걸쳐 있어 합계는 뜻을 갖지 않는다.
     */
    public record Row(
            String techId,
            /** {@code MET} · {@code LEVEL_SHORT} · {@code NO_EVIDENCE} · {@code UNDETERMINED}. */
            String verdict,
            Integer requiredCount,
            Integer preferredCount,
            String personalLevel,
            String assessmentCeiling,
            List<String> reasonCodes,
            Integer fillDelta
    ) {

        static Row of(CSnapshot.GapTechnology technology, CSnapshot.TechnologyDemand demand,
                      String personalLevel, String assessmentCeiling, Integer fillDelta) {
            List<String> reasons = technology.reasonCodes() == null
                    ? List.of() : technology.reasonCodes();
            return new Row(
                    technology.techId(),
                    verdict(technology.status(), reasons),
                    demand == null ? null : demand.requiredCount(),
                    demand == null ? null : demand.preferredCount(),
                    personalLevel,
                    assessmentCeiling,
                    reasons,
                    fillDelta);
        }

        /**
         * C의 보유 상태를 화면 판정으로 옮긴다.
         *
         * <p>{@code NOT_HELD}를 둘로 나누는 것이 이 메서드의 전부다. Evidence가 아예 없는
         * 것과 요구 Level에 미치지 못한 것은 사용자가 할 일이 다르다 -- 앞은 새로 배우는
         * 것이고 뒤는 더 깊이 쓰는 것이다.</p>
         */
        private static String verdict(String status, List<String> reasonCodes) {
            if ("HELD".equals(status)) {
                return "MET";
            }
            if (!"NOT_HELD".equals(status)) {
                // UNKNOWN 과 알 수 없는 값. 부족으로 단정하지 않는다.
                return "UNDETERMINED";
            }
            boolean levelShort = reasonCodes.stream()
                    .anyMatch(code -> code.contains("LEVEL") || code.contains("CEILING"));
            return levelShort ? "LEVEL_SHORT" : "NO_EVIDENCE";
        }
    }
}
