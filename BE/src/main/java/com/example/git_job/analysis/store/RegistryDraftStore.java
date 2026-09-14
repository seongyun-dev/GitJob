package com.example.git_job.analysis.store;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * The unpublished registry version an administrator is building.
 *
 * <h2>Why a draft and not a direct edit</h2>
 *
 * <p>{@code registry_version} is part of the primary key of every content
 * table, so a published version cannot change. That is deliberate: an analysis
 * event carries the version it was judged with, and half a year later someone
 * has to be able to ask which rules produced a given piece of evidence.</p>
 *
 * <p>Promoting a candidate straight into {@code CURRENT} would rewrite the
 * basis of every analysis already judged against it. So promotions accumulate
 * in a {@code DRAFT} copy, and publishing swaps it in as one act.</p>
 *
 * <p>That also makes a week of promotions one version rather than twenty, and
 * leaves them reversible until the moment they are published.</p>
 */
@Repository
public class RegistryDraftStore {

    private final JdbcTemplate jdbc;

    public RegistryDraftStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<String> currentVersion() {
        return jdbc.queryForList(
                        "SELECT registry_version FROM technology_registry WHERE status = 'CURRENT'",
                        String.class)
                .stream().findFirst();
    }

    public Optional<String> draftVersion() {
        return jdbc.queryForList(
                        "SELECT registry_version FROM technology_registry WHERE status = 'DRAFT'",
                        String.class)
                .stream().findFirst();
    }

    /**
     * The draft to promote into, created from {@code CURRENT} on first use.
     *
     * <p>Copying rather than starting empty: a draft that only holds the new
     * technologies would, on publication, lose every technology the current
     * version knows. Every repository would then report almost nothing, which
     * is a normal-looking result and therefore invisible.</p>
     */
    public String openDraft(Instant now) {
        Optional<String> existing = draftVersion();
        if (existing.isPresent()) {
            return existing.get();
        }
        String current = currentVersion().orElseThrow(() -> new IllegalStateException(
                "technology_registry에 CURRENT 버전이 없어 초안을 뜰 수 없다"));
        String draft = nextVersion(now);

        jdbc.update("""
                INSERT INTO technology_registry (registry_version, schema_version, status, published_at)
                SELECT ?, schema_version, 'DRAFT', NULL
                FROM technology_registry WHERE registry_version = ?
                """, draft, current);
        copyContent(current, draft);
        return draft;
    }

    /** Adds one technology and the mapping that recognises it, to the draft only. */
    public void addTechnology(String draft, String techId, String displayName,
            List<String> jobDomains, String mappingType, String ecosystem,
            String value, String matchMode) {
        jdbc.update("""
                INSERT INTO technology (tech_id, registry_version, display_name, status)
                VALUES (?, ?, ?, 'ACTIVE')
                """, techId, draft, displayName);
        for (String domain : jobDomains) {
            jdbc.update("""
                    INSERT INTO technology_category (job_domain, registry_version, tech_id)
                    VALUES (?, ?, ?)
                    """, domain, draft, techId);
        }
        jdbc.update("""
                INSERT INTO technology_mapping
                    (registry_version, tech_id, mapping_type, ecosystem, value, match_mode, status)
                VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')
                """, draft, techId, mappingType, ecosystem, value, matchMode);

        // L0 only. A promoted candidate is a dependency coordinate, so the
        // repository declared it; whether the code imports or exercises it is
        // what L1 and L2 answer, and those need mappings this promotion does
        // not have.
        String ruleId = techId + ".l0.dependency";
        jdbc.update("""
                INSERT INTO evidence_rule
                    (rule_id, tech_id, registry_version, rule_type, language, rule_name,
                     description, evaluation_scope, priority, status)
                VALUES (?, ?, ?, 'L0', NULL, ?, ?, 'REPOSITORY', 50, 'ACTIVE')
                """, ruleId, techId, draft, displayName + " 의존성 선언",
                displayName + "을(를) 매니페스트에 선언했다. 후보 승격으로 만들어진 규칙이다.");

        Long clauseId = jdbc.queryForObject("""
                INSERT INTO evidence_rule_clause
                    (rule_id, group_no, clause_key, role, fact_type, min_match_count,
                     clause_order, registry_version)
                VALUES (?, 1, 'resolved-tech', 'REQUIRED', 'DEPENDENCY', 1, 1, ?)
                RETURNING clause_id
                """, Long.class, ruleId, draft);
        Long predicateId = jdbc.queryForObject("""
                INSERT INTO evidence_rule_predicate
                    (clause_id, fact_field, match_operator, segment_delimiter, predicate_order)
                VALUES (?, 'TECH_ID', 'EXACT', NULL, 1)
                RETURNING predicate_id
                """, Long.class, clauseId);
        jdbc.update("""
                INSERT INTO evidence_rule_predicate_value
                    (value_order, predicate_id, tech_id, registry_version, expected_value)
                VALUES (1, ?, ?, ?, ?)
                """, predicateId, techId, draft, techId);
    }

    /**
     * Makes the draft current. The previous version keeps every row.
     *
     * <p>Retiring first is not a style choice: a partial unique index allows
     * exactly one {@code CURRENT}, so promoting before retiring is rejected.</p>
     */
    public void publish(String draft, Instant now) {
        jdbc.update("UPDATE technology_registry SET status = 'RETIRED' WHERE status = 'CURRENT'");
        int updated = jdbc.update("""
                UPDATE technology_registry
                SET status = 'CURRENT', published_at = ?
                WHERE registry_version = ? AND status = 'DRAFT'
                """, java.sql.Timestamp.from(now), draft);
        if (updated != 1) {
            throw new IllegalStateException("발행할 초안이 없다: " + draft);
        }
    }

    /** `registry-YYYYMMDD.n`, counting up within the day. */
    private String nextVersion(Instant now) {
        String day = LocalDate.ofInstant(now, ZoneOffset.UTC).toString().replace("-", "");
        String prefix = "registry-" + day + ".";
        Integer used = jdbc.queryForObject("""
                SELECT count(*) FROM technology_registry WHERE registry_version LIKE ?
                """, Integer.class, prefix + "%");
        return prefix + ((used == null ? 0 : used) + 1);
    }

    private void copyContent(String from, String to) {
        jdbc.update("""
                INSERT INTO technology (tech_id, registry_version, display_name, status)
                SELECT tech_id, ?, display_name, status FROM technology WHERE registry_version = ?
                """, to, from);
        jdbc.update("""
                INSERT INTO technology_category (job_domain, registry_version, tech_id)
                SELECT job_domain, ?, tech_id FROM technology_category WHERE registry_version = ?
                """, to, from);
        jdbc.update("""
                INSERT INTO technology_mapping
                    (registry_version, tech_id, mapping_type, ecosystem, value, match_mode, status)
                SELECT ?, tech_id, mapping_type, ecosystem, value, match_mode, status
                FROM technology_mapping WHERE registry_version = ?
                """, to, from);
        jdbc.update("""
                INSERT INTO evidence_rule
                    (rule_id, tech_id, registry_version, rule_type, language, rule_name,
                     description, evaluation_scope, priority, status)
                SELECT rule_id, tech_id, ?, rule_type, language, rule_name, description,
                       evaluation_scope, priority, status
                FROM evidence_rule WHERE registry_version = ?
                """, to, from);

        // Clause and predicate ids are IDENTITY, so the parent-child links are
        // rebuilt from natural keys. INSERT ... RETURNING does not promise to
        // return rows in insertion order, which rules out matching by position.
        jdbc.update("""
                INSERT INTO evidence_rule_clause
                    (rule_id, group_no, clause_key, role, fact_type, min_match_count,
                     clause_order, registry_version)
                SELECT rule_id, group_no, clause_key, role, fact_type, min_match_count,
                       clause_order, ?
                FROM evidence_rule_clause WHERE registry_version = ?
                """, to, from);
        jdbc.update("""
                INSERT INTO evidence_rule_predicate
                    (clause_id, fact_field, match_operator, segment_delimiter, predicate_order)
                SELECT new_clause.clause_id, p.fact_field, p.match_operator,
                       p.segment_delimiter, p.predicate_order
                FROM evidence_rule_predicate p
                JOIN evidence_rule_clause old_clause ON old_clause.clause_id = p.clause_id
                JOIN evidence_rule_clause new_clause
                  ON new_clause.registry_version = ?
                 AND new_clause.rule_id = old_clause.rule_id
                 AND new_clause.group_no = old_clause.group_no
                 AND new_clause.clause_order = old_clause.clause_order
                WHERE old_clause.registry_version = ?
                """, to, from);
        jdbc.update("""
                INSERT INTO evidence_rule_predicate_value
                    (value_order, predicate_id, tech_id, registry_version, expected_value)
                SELECT v.value_order, new_predicate.predicate_id, v.tech_id, ?, v.expected_value
                FROM evidence_rule_predicate_value v
                JOIN evidence_rule_predicate p ON p.predicate_id = v.predicate_id
                JOIN evidence_rule_clause old_clause ON old_clause.clause_id = p.clause_id
                JOIN evidence_rule_clause new_clause
                  ON new_clause.registry_version = ?
                 AND new_clause.rule_id = old_clause.rule_id
                 AND new_clause.group_no = old_clause.group_no
                 AND new_clause.clause_order = old_clause.clause_order
                JOIN evidence_rule_predicate new_predicate
                  ON new_predicate.clause_id = new_clause.clause_id
                 AND new_predicate.predicate_order = p.predicate_order
                WHERE old_clause.registry_version = ?
                """, to, to, from);
    }
}
