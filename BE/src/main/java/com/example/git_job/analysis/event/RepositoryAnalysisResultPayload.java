package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Objects;
import java.util.regex.Pattern;

/**
 * Everything this service needs to close out one analysis.
 *
 * <p>There is no userId. The worker never learns who owns an analysis, and
 * analysisId is enough to resolve the owner here. Widening this would put user
 * identity into a topic that outlives the request.</p>
 */
public record RepositoryAnalysisResultPayload(
        @JsonProperty("analysis_id") String analysisId,
        @JsonProperty("request_event_id") String requestEventId,
        @JsonProperty("registry_version") String registryVersion,
        @JsonProperty("commit_sha") String commitSha,
        @JsonProperty("status") Status status,
        @JsonProperty("error_code") String errorCode,
        @JsonProperty("error_detail") String errorDetail,
        @JsonProperty("technologies") List<TechnologyVerdict> technologies,
        @JsonProperty("evidence") List<EvidenceItem> evidence,
        @JsonProperty("candidates") List<TechnologyCandidate> candidates,
        @JsonProperty("stats") AnalysisStats stats,
        /**
         * 판정에 쓴 Rule Pack. {@code repository-analysis-result/v2} 부터 실린다.
         *
         * <p>v1 결과에는 없어 {@code null} 이고, 그때는 Registry 버전으로 대신하지
         * 않는다. C 는 이 값을 {@code evidence_rule_version} 으로 받아 근거의 범위를
         * 검사하는데, 다른 값을 넣으면 모든 근거가 범위 불일치로 버려진다. 모르면
         * 모른다고 두고 C 에 보내지 않는 편이 정확하다.</p>
         */
        @JsonProperty("rule_pack_version") String rulePackVersion,
        @JsonProperty("rule_pack_content_sha256") String rulePackContentSha256,
        /** 기술별 판정 상한과 지원 범위. v2 부터 실리며 v1 에서는 비어 있다. */
        @JsonProperty("technology_support") List<TechnologySupportItem> technologySupport
) {

    /**
     * FAILED arrives on the result topic, not only in the DLQ. The DLQ is for
     * operators; a user whose repository was deleted has to see the failure, and
     * analysis_job only moves when this event says so.
     */
    public enum Status { COMPLETED, FAILED }

    private static final Pattern COMMIT_SHA = Pattern.compile("^[0-9a-f]{40}$");

    public RepositoryAnalysisResultPayload {
        analysisId = requireNonBlank(analysisId, "analysisId");
        requestEventId = requireNonBlank(requestEventId, "requestEventId");
        registryVersion = requireNonBlank(registryVersion, "registryVersion");
        commitSha = Objects.requireNonNull(commitSha, "commitSha must not be null");
        if (!COMMIT_SHA.matcher(commitSha).matches()) {
            throw new IllegalArgumentException("commitSha must be 40 lowercase hex characters");
        }
        status = Objects.requireNonNull(status, "status must not be null");

        technologies = List.copyOf(technologies == null ? List.of() : technologies);
        evidence = List.copyOf(evidence == null ? List.of() : evidence);
        candidates = List.copyOf(candidates == null ? List.of() : candidates);
        technologySupport =
                List.copyOf(technologySupport == null ? List.of() : technologySupport);
        if (rulePackContentSha256 != null && !rulePackContentSha256.matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException(
                    "rulePackContentSha256 must be 64 lowercase hex characters");
        }

        if (status == Status.FAILED) {
            if (errorCode == null || errorCode.isBlank()) {
                throw new IllegalArgumentException("a FAILED result must carry an errorCode");
            }
            // Otherwise this service would write evidence rows for an analysis it
            // is about to mark failed.
            if (!technologies.isEmpty() || !evidence.isEmpty() || !candidates.isEmpty()) {
                throw new IllegalArgumentException("a FAILED result must not carry findings");
            }
        } else if (errorCode != null && !errorCode.isBlank()) {
            throw new IllegalArgumentException("errorCode belongs to a FAILED result");
        }
    }

    public boolean failed() {
        return status == Status.FAILED;
    }

    /**
     * Rule Pack 계보를 함께 받았는지.
     *
     * <p>이 값이 거짓이면 C 에 보낼 {@code evidence_rule_version} 을 만들 수 없다.
     * Registry 버전으로 대신하면 C 가 근거를 전부 버리므로, 그 분석은 재분석 대상이다.</p>
     */
    public boolean hasRulePackLineage() {
        return rulePackVersion != null && !rulePackVersion.isBlank()
                && rulePackContentSha256 != null && !rulePackContentSha256.isBlank();
    }

    /**
     * 저장소 전체를 봤다고 말할 수 있는지.
     *
     * <p>{@code COMPLETED} 만으로는 부족하다. 워커가 파일을 건너뛰고도 완료로 끝날 수
     * 있고, 그 분석을 완전 판정으로 보내면 C 가 "이 기술을 쓰지 않는다"까지 결론짓게
     * 된다. 건너뛴 사유를 받지 못한 계약(v1)도 참으로 만들지 않는다 -- 건너뛴 것이
     * 없다는 뜻이 아니라 모른다는 뜻이기 때문이다.</p>
     */
    public boolean coverageComplete() {
        return status == Status.COMPLETED && stats != null && !stats.skippedAnything();
    }

    private static String requireNonBlank(String value, String fieldName) {
        if (value == null || value.isBlank() || !value.equals(value.strip())) {
            throw new IllegalArgumentException(fieldName + " must be non-blank and trimmed");
        }
        return value;
    }
}
