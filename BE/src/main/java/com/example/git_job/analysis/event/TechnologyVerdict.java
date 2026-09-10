package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Objects;

/**
 * One technology and the level the registry rules put it at.
 *
 * <p>matchedRuleIds lists every rule that matched, not only the one that set the
 * level. A level with no rule behind it cannot be explained, and explaining the
 * judgement is the point of Evidence.</p>
 */
public record TechnologyVerdict(
        @JsonProperty("tech_id") String techId,
        @JsonProperty("level") Level level,
        @JsonProperty("matched_rule_ids") List<String> matchedRuleIds
) {

    /**
     * L0 found (declared dependency), L1 applied (import, config, annotation),
     * L2 used (core API call, own contribution), L3 advanced (operational maturity).
     */
    public enum Level { L0, L1, L2, L3 }

    public TechnologyVerdict {
        if (techId == null || techId.isBlank()) {
            throw new IllegalArgumentException("techId must be non-blank");
        }
        level = Objects.requireNonNull(level, "level must not be null");
        matchedRuleIds = List.copyOf(matchedRuleIds == null ? List.of() : matchedRuleIds);
        if (matchedRuleIds.isEmpty()) {
            throw new IllegalArgumentException("a verdict must name the rules behind it");
        }
    }
}
