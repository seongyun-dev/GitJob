"""Produce repository-scoped personal levels from Rule Pack decisive facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from analysis.attribution import AttributedEvidence
from analysis.judge import EvidenceFact, Judgement, fact_matches_clause
from analysis.rules import Clause, Predicate, RuleSet

Level = Literal["L0", "L1", "L2", "L3"]
_LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
_LEVELS: tuple[Level, ...] = ("L0", "L1", "L2", "L3")


@dataclass(frozen=True)
class PersonalTechnologyAssessment:
    tech_id: str
    personal_level: Level | None
    assessment_ceiling: Level
    attribution_status: Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
    missing_scope: tuple[str, ...]
    proofs: tuple[AttributedEvidence, ...]


def assess_personal_levels(
    rule_set: RuleSet,
    judgement: Judgement,
    attributed_evidence: tuple[AttributedEvidence, ...],
    *,
    repository_coverage_complete: bool = True,
) -> tuple[PersonalTechnologyAssessment, ...]:
    """Assess only repository-positive technologies; never invent absent L0s."""

    rules = {rule.rule_id: rule for rule in rule_set.rules}
    attributed = {item.fact_id: item for item in attributed_evidence}
    evidence_by_rule: dict[str, list[AttributedEvidence]] = {}
    unattributed_by_rule: dict[str, list[EvidenceFact]] = {}
    assessment_evidence = judgement.personal_evidence or judgement.evidence
    for evidence in assessment_evidence:
        item = attributed.get(evidence.fact_id)
        if item is not None:
            evidence_by_rule.setdefault(evidence.rule_id, []).append(item)
        else:
            unattributed_by_rule.setdefault(evidence.rule_id, []).append(evidence)

    assessments = []
    for verdict in judgement.verdicts:
        matched = [
            rules[rule_id] for rule_id in verdict.matched_rule_ids if rule_id in rules
        ]
        matched.sort(
            key=lambda rule: (_LEVEL_ORDER[rule.rule_type], rule.priority, rule.rule_id)
        )
        self_levels: list[Level] = []
        unknown_levels: list[Level] = []
        used: list[AttributedEvidence] = []
        missing: set[str] = set()
        technology_evidence = tuple(
            item
            for item in attributed_evidence
            if item.evidence.tech_id == verdict.tech_id
        )
        any_resolved = any(
            item.attribution in {"SELF", "OTHER"} for item in technology_evidence
        )
        any_unknown_attribution = any(
            item.attribution == "UNKNOWN" for item in technology_evidence
        ) or any(
            evidence.tech_id == verdict.tech_id
            for evidence in assessment_evidence
            if evidence.fact_id not in attributed
        )
        missing.update(
            scope for item in technology_evidence for scope in item.missing_scope
        )

        for rule in matched:
            lower_clauses = [
                clause
                for candidate in rule_set.rules
                if candidate.tech_id == rule.tech_id
                and _LEVEL_ORDER[candidate.rule_type] < _LEVEL_ORDER[rule.rule_type]
                for clause in candidate.clauses
                if clause.role == "REQUIRED"
            ]
            selected_group = judgement.matched_rule_groups.get(rule.rule_id)
            if selected_group is None:
                groups = {clause.group_no for clause in rule.clauses}
                if len(groups) == 1:
                    selected_group = next(iter(groups))
                else:
                    selected_group = _infer_selected_group(
                        rule, evidence_by_rule.get(rule.rule_id, ())
                    )
            required = [
                clause
                for clause in rule.clauses
                if clause.role == "REQUIRED" and clause.group_no == selected_group
            ]
            decisive = [
                clause
                for clause in required
                if not any(
                    _clause_implies_lower_prerequisite(clause, lower)
                    for lower in lower_clauses
                )
            ]
            if not decisive:
                decisive = required
            proof_items = [
                item
                for item in evidence_by_rule.get(rule.rule_id, ())
                if any(
                    fact_matches_clause(clause, item.evidence.fact)
                    for clause in decisive
                )
            ]
            unattributed_proofs = [
                evidence
                for evidence in unattributed_by_rule.get(rule.rule_id, ())
                if any(
                    fact_matches_clause(clause, evidence.fact) for clause in decisive
                )
            ]
            used.extend(_select_decisive_proofs(decisive, proof_items))
            incomplete_decisive = any(
                sum(
                    fact_matches_clause(clause, item.evidence.fact)
                    for item in proof_items
                )
                + sum(
                    fact_matches_clause(clause, evidence.fact)
                    for evidence in unattributed_proofs
                )
                < clause.min_match_count
                for clause in decisive
            )
            attribution_incomplete = bool(unattributed_proofs)
            has_unknown = (
                incomplete_decisive
                or attribution_incomplete
                or any(item.attribution == "UNKNOWN" for item in proof_items)
            )
            if incomplete_decisive:
                missing.add(f"DECISIVE_FACT_EVIDENCE_INCOMPLETE:{rule.rule_id}")
            if attribution_incomplete:
                missing.add(f"DECISIVE_FACT_ATTRIBUTION_INCOMPLETE:{rule.rule_id}")
            level = rule.rule_type
            if level != "L0" and any(
                item.attribution == "SELF" for item in proof_items
            ):
                self_levels.append(level)
            if has_unknown:
                unknown_levels.append(level)
        support = rule_set.technology_support.get(verdict.tech_id)
        max_supported = _support_value(support, "max_supported_level", verdict.level)
        coverage = _support_value(support, "coverage", "SUPPORTED")
        if coverage != "SUPPORTED":
            missing.add(f"RULE_PACK_COVERAGE_{coverage}")
        if not repository_coverage_complete:
            missing.add("REPOSITORY_FACT_COVERAGE_INCOMPLETE")

        personal_level: Level | None
        if self_levels:
            personal_level = max(self_levels, key=_LEVEL_ORDER.__getitem__)
        elif repository_coverage_complete and not unknown_levels:
            personal_level = "L0"
        else:
            personal_level = None

        ceiling_order = _LEVEL_ORDER[max_supported]
        if not repository_coverage_complete:
            ceiling_order = min(ceiling_order, _LEVEL_ORDER[verdict.level])
        if unknown_levels:
            first_unknown = min(_LEVEL_ORDER[level] for level in unknown_levels)
            ceiling_order = min(ceiling_order, max(0, first_unknown - 1))
        if personal_level is not None:
            ceiling_order = max(ceiling_order, _LEVEL_ORDER[personal_level])

        if any_unknown_attribution and not any_resolved:
            status = "UNKNOWN"
        elif (
            any_unknown_attribution
            or unknown_levels
            or not repository_coverage_complete
        ):
            status = "PARTIAL"
        else:
            status = "COMPLETE"
        assessments.append(
            PersonalTechnologyAssessment(
                tech_id=verdict.tech_id,
                personal_level=personal_level,
                assessment_ceiling=_LEVELS[ceiling_order],
                attribution_status=status,
                missing_scope=tuple(sorted(missing)),
                proofs=tuple(
                    sorted(
                        {item.fact_id: item for item in used}.values(),
                        key=lambda item: item.fact_id,
                    )
                ),
            )
        )
    return tuple(sorted(assessments, key=lambda item: item.tech_id))


def aggregate_personal_assessments(
    repositories: tuple[tuple[PersonalTechnologyAssessment, ...], ...],
) -> tuple[PersonalTechnologyAssessment, ...]:
    """Preserve per-repository positives without joining facts across repositories."""

    by_tech: dict[str, list[PersonalTechnologyAssessment]] = {}
    for repository in repositories:
        for assessment in repository:
            by_tech.setdefault(assessment.tech_id, []).append(assessment)

    combined = []
    for tech_id, items in sorted(by_tech.items()):
        positives = [
            item.personal_level
            for item in items
            if item.personal_level is not None and item.personal_level != "L0"
        ]
        if positives:
            personal_level = max(positives, key=_LEVEL_ORDER.__getitem__)
        elif all(item.personal_level == "L0" for item in items):
            personal_level = "L0"
        else:
            personal_level = None
        ceiling_order = min(_LEVEL_ORDER[item.assessment_ceiling] for item in items)
        if personal_level is not None:
            ceiling_order = max(ceiling_order, _LEVEL_ORDER[personal_level])
        statuses = {item.attribution_status for item in items}
        if statuses == {"COMPLETE"}:
            status = "COMPLETE"
        elif statuses == {"UNKNOWN"}:
            status = "UNKNOWN"
        else:
            status = "PARTIAL"
        proofs = {
            (proof.repository_analysis_id, proof.fact_id): proof
            for item in items
            for proof in item.proofs
        }
        combined.append(
            PersonalTechnologyAssessment(
                tech_id=tech_id,
                personal_level=personal_level,
                assessment_ceiling=_LEVELS[ceiling_order],
                attribution_status=status,
                missing_scope=tuple(
                    sorted({scope for item in items for scope in item.missing_scope})
                ),
                proofs=tuple(
                    sorted(
                        proofs.values(),
                        key=lambda proof: (
                            proof.repository_analysis_id,
                            proof.fact_id,
                        ),
                    )
                ),
            )
        )
    return tuple(combined)


def _clause_implies_lower_prerequisite(higher: Clause, lower: Clause) -> bool:
    """Prove that every fact satisfying ``higher`` also satisfies ``lower``."""

    if (
        higher.fact_type != lower.fact_type
        or higher.min_match_count < lower.min_match_count
    ):
        return False
    higher_predicates = tuple(
        predicate
        for predicate in higher.predicates
        if predicate.fact_field != "LANGUAGE"
    )
    lower_predicates = tuple(
        predicate
        for predicate in lower.predicates
        if predicate.fact_field != "LANGUAGE"
    )
    return all(
        any(
            _predicate_implies(higher_predicate, lower_predicate)
            for higher_predicate in higher_predicates
        )
        for lower_predicate in lower_predicates
    )


def _predicate_implies(higher: Predicate, lower: Predicate) -> bool:
    if higher.fact_field != lower.fact_field:
        return False
    if higher.match_operator == lower.match_operator == "EXACT":
        return set(higher.expected).issubset(lower.expected)
    return higher == lower


def _select_decisive_proofs(
    clauses: list[Clause], proof_items: list[AttributedEvidence]
) -> tuple[AttributedEvidence, ...]:
    """Keep the minimum decisive proof set, preferring SELF and uncertainty."""

    priority = {"SELF": 0, "UNKNOWN": 1, "OTHER": 2}
    selected: dict[str, AttributedEvidence] = {}
    for clause in clauses:
        matches = sorted(
            (
                item
                for item in proof_items
                if fact_matches_clause(clause, item.evidence.fact)
            ),
            key=lambda item: (priority[item.attribution], item.fact_id),
        )
        for item in matches[: clause.min_match_count]:
            selected[item.fact_id] = item
    return tuple(selected.values())


def _infer_selected_group(rule, evidence: list[AttributedEvidence]) -> int | None:
    for group_no, clauses in rule.groups().items():
        required = [clause for clause in clauses if clause.role == "REQUIRED"]
        if all(
            sum(fact_matches_clause(clause, item.evidence.fact) for item in evidence)
            >= clause.min_match_count
            for clause in required
        ):
            return group_no
    return None


def _support_value(support, name: str, default: str) -> str:
    if support is None:
        return default
    return (
        support.get(name, default)
        if isinstance(support, dict)
        else getattr(support, name)
    )
