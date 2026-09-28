package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

/**
 * One fact that supported one rule. Becomes a row in analysis_evidence.
 *
 * <p>filePath and the line range are why the worker carries positions all the
 * way through parsing: a permalink needs them, and an aggregate count cannot
 * produce one.</p>
 *
 * <p>factPayload is keyed by the rules' fact_field vocabulary (MODULE,
 * COORDINATE, ECOSYSTEM, SCOPE, LANGUAGE, FILE_PATH) and is stored as jsonb, so
 * a new fact type needs no change here.</p>
 */
public record EvidenceItem(
        @JsonProperty("rule_id") String ruleId,
        @JsonProperty("fact_type") String factType,
        @JsonProperty("file_path") String filePath,
        @JsonProperty("start_line") int startLine,
        @JsonProperty("end_line") int endLine,
        @JsonProperty("fact_payload") Map<String, Object> factPayload,
        @JsonProperty("code_snippet") String codeSnippet,
        /**
         * 이 줄을 마지막에 바꾼 커밋. 워커의 {@code git blame} 결과다.
         *
         * <p>{@code null}이면 작성자를 읽지 못한 것이다 -- 얕은 체크아웃이거나,
         * blame 이 안 되는 파일이거나, 기여 판정을 끄고 돌린 분석이다. 없는 값을
         * 채우지 않고 그대로 두며, 조회 쪽이 "확인되지 않음"으로 읽는다.</p>
         *
         * <p>작성자가 아니라 커밋인 것은 의도한 것이다. 누구의 커밋인지는 요청자의
         * 신원을 알아야 정해지고, 이 이벤트는 그 신원보다 오래 사는 토픽을 탄다.</p>
         */
        @JsonProperty("commit_sha") String commitSha
) {

    public EvidenceItem {
        if (ruleId == null || ruleId.isBlank()) {
            throw new IllegalArgumentException("ruleId must be non-blank");
        }
        if (factType == null || factType.isBlank()) {
            throw new IllegalArgumentException("factType must be non-blank");
        }
        if (filePath == null || filePath.isBlank()) {
            throw new IllegalArgumentException("filePath must be non-blank");
        }
        if (startLine < 1) {
            throw new IllegalArgumentException("startLine must be at least 1");
        }
        if (endLine < startLine) {
            throw new IllegalArgumentException("endLine must not precede startLine");
        }
        factPayload = Map.copyOf(factPayload == null ? Map.of() : factPayload);
    }
}
