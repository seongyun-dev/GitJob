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
        @JsonProperty("code_snippet") String codeSnippet
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
