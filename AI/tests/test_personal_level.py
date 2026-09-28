"""Personal level comes from SELF ownership of Rule Pack decisive facts."""

from __future__ import annotations

from analysis.attribution import AttributedEvidence
from analysis.judge import (
    EvidenceFact,
    Fact,
    Judge,
    Judgement,
    Verdict,
    facts_from_annotations,
    facts_from_calls,
    facts_from_imports,
    facts_from_sources,
    facts_from_syntax,
)
from analysis.parse import RepositoryParser
from analysis.personal_level import (
    PersonalTechnologyAssessment,
    _clause_implies_lower_prerequisite,
    aggregate_personal_assessments,
    assess_personal_levels,
)
from analysis.rulepack import (
    SCOPE_REGISTRY_PATH,
    SCOPE_RULE_PACK_PATH,
    load_rule_pack,
    mappings_from_registry_artifact,
)
from analysis.rules import Clause, Predicate, Rule, RuleSet


def _clause(number, key, fact_type, field, expected):
    return Clause(
        clause_id=number,
        group_no=1,
        clause_key=key,
        role="REQUIRED",
        fact_type=fact_type,
        min_match_count=1,
        predicates=(Predicate(field, "EXACT", None, (expected,)),),
    )


L1 = Rule(
    "python.l1.source",
    "python",
    "L1",
    None,
    "REPOSITORY",
    1,
    (_clause(1, "source", "SOURCE_FILE", "LANGUAGE", "python"),),
)
L2 = Rule(
    "python.l2.implementation",
    "python",
    "L2",
    None,
    "REPOSITORY",
    2,
    (
        _clause(2, "source", "SOURCE_FILE", "LANGUAGE", "python"),
        _clause(3, "function", "SYNTAX_NODE", "KIND", "FUNCTION"),
    ),
)
L3 = Rule(
    "python.l3.operations",
    "python",
    "L3",
    None,
    "REPOSITORY",
    3,
    (
        _clause(4, "function", "SYNTAX_NODE", "KIND", "FUNCTION"),
        _clause(5, "timeout", "API_CALL", "METHOD", "wait_for"),
    ),
)
RULE_SET = RuleSet(
    "registry-20260911.4",
    (),
    (L1, L2, L3),
    rule_pack_version="rule-pack-20260911.4",
    technology_support={
        "python": {
            "max_supported_level": "L3",
            "coverage": "PARTIAL",
            "limitations": ("static analysis misses dynamic calls",),
        }
    },
)


def _fact(rule, fact_type, fields, line):
    return EvidenceFact(
        rule.rule_id,
        "python",
        Fact(fact_type, fields, "service.py", line, frozenset({"python"})),
    )


SOURCE_L1 = _fact(L1, "SOURCE_FILE", {"LANGUAGE": "python"}, 1)
SOURCE_L2 = _fact(L2, "SOURCE_FILE", {"LANGUAGE": "python"}, 1)
FUNCTION_L2 = _fact(L2, "SYNTAX_NODE", {"KIND": "FUNCTION"}, 2)
FUNCTION_L3 = _fact(L3, "SYNTAX_NODE", {"KIND": "FUNCTION"}, 2)
TIMEOUT_L3 = _fact(L3, "API_CALL", {"METHOD": "wait_for"}, 3)


def _owned(
    evidence,
    attribution,
    *,
    missing=(),
    repository_analysis_id="fixture-repository",
):
    return AttributedEvidence(
        evidence=evidence,
        fact_id=evidence.fact_id,
        repository_analysis_id=repository_analysis_id,
        attribution=attribution,
        attribution_commit_sha=("a" * 40 if attribution in {"SELF", "OTHER"} else None),
        missing_scope=missing,
    )


def _judgement(level, rules, evidence):
    return Judgement(
        verdicts=(Verdict("python", level, tuple(rule.rule_id for rule in rules)),),
        evidence=tuple(evidence),
        candidates=(),
        rule_pack_version="rule-pack-20260911.4",
        technology_support=RULE_SET.technology_support,
    )


def test_l3_repository_with_only_l2_decisive_self_stays_l2():
    judgement = _judgement(
        "L3", (L1, L2, L3), (SOURCE_L1, SOURCE_L2, FUNCTION_L2, FUNCTION_L3, TIMEOUT_L3)
    )
    assessment = assess_personal_levels(
        RULE_SET,
        judgement,
        (
            _owned(SOURCE_L1, "SELF"),
            _owned(SOURCE_L2, "SELF"),
            _owned(FUNCTION_L2, "SELF"),
            _owned(FUNCTION_L3, "OTHER"),
            _owned(TIMEOUT_L3, "OTHER"),
        ),
    )[0]

    assert assessment.personal_level == "L2"
    assert assessment.assessment_ceiling == "L3"
    assert assessment.attribution_status == "COMPLETE"


def test_l3_requires_self_on_a_fact_specific_to_the_l3_rule():
    judgement = _judgement(
        "L3", (L1, L2, L3), (SOURCE_L1, SOURCE_L2, FUNCTION_L2, FUNCTION_L3, TIMEOUT_L3)
    )
    assessment = assess_personal_levels(
        RULE_SET,
        judgement,
        (
            _owned(SOURCE_L1, "SELF"),
            _owned(SOURCE_L2, "SELF"),
            _owned(FUNCTION_L2, "SELF"),
            _owned(FUNCTION_L3, "OTHER"),
            _owned(TIMEOUT_L3, "SELF"),
        ),
    )[0]

    assert assessment.personal_level == "L3"


def test_unknown_l3_identity_preserves_l2_and_lowers_safe_ceiling():
    judgement = _judgement(
        "L3", (L1, L2, L3), (SOURCE_L1, SOURCE_L2, FUNCTION_L2, FUNCTION_L3, TIMEOUT_L3)
    )
    assessment = assess_personal_levels(
        RULE_SET,
        judgement,
        (
            _owned(SOURCE_L1, "SELF"),
            _owned(SOURCE_L2, "SELF"),
            _owned(FUNCTION_L2, "SELF"),
            _owned(FUNCTION_L3, "OTHER"),
            _owned(TIMEOUT_L3, "UNKNOWN", missing=("AUTHOR_IDENTITY_UNRESOLVED",)),
        ),
    )[0]

    assert assessment.personal_level == "L2"
    assert assessment.assessment_ceiling == "L2"
    assert assessment.attribution_status == "PARTIAL"
    assert "AUTHOR_IDENTITY_UNRESOLVED" in assessment.missing_scope


def test_shallow_or_incomplete_coverage_never_infers_l0():
    judgement = _judgement("L1", (L1,), (SOURCE_L1,))
    assessment = assess_personal_levels(
        RULE_SET,
        judgement,
        (_owned(SOURCE_L1, "UNKNOWN", missing=("BLAME_HISTORY_INCOMPLETE",)),),
        repository_coverage_complete=False,
    )[0]

    assert assessment.personal_level is None
    assert assessment.assessment_ceiling == "L0"
    assert assessment.attribution_status == "UNKNOWN"
    assert set(assessment.missing_scope) >= {
        "BLAME_HISTORY_INCOMPLETE",
        "REPOSITORY_FACT_COVERAGE_INCOMPLETE",
        "RULE_PACK_COVERAGE_PARTIAL",
    }


def test_actual_rule_pack_repeated_prerequisites_do_not_promote_l3(tmp_path):
    (tmp_path / "service.py").write_text(
        "import asyncio\n"
        "async def supervise(coro):\n"
        "    task = asyncio.create_task(coro)\n"
        "    try:\n"
        "        return await asyncio.wait_for(task, timeout=2)\n"
        "    finally:\n"
        "        task.cancel()\n",
        encoding="utf-8",
    )
    report = RepositoryParser().parse_repository(tmp_path)
    rule_set = load_rule_pack(SCOPE_RULE_PACK_PATH).as_rule_set(
        mappings=mappings_from_registry_artifact(SCOPE_REGISTRY_PATH)
    )
    judgement = Judge(rule_set).judge(
        facts_from_imports(report.occurrences)
        + facts_from_calls(report.calls)
        + facts_from_sources(report.sources)
        + facts_from_annotations(report.annotations)
        + facts_from_syntax(report.syntax)
    )
    python_evidence = tuple(
        item for item in judgement.evidence if item.tech_id == "python"
    )
    attributed = tuple(
        _owned(item, "OTHER" if ".l3." in item.rule_id else "SELF")
        for item in python_evidence
    )

    assessment = assess_personal_levels(
        rule_set,
        judgement,
        attributed,
    )
    python = next(item for item in assessment if item.tech_id == "python")

    assert (
        next(item.level for item in judgement.verdicts if item.tech_id == "python")
        == "L3"
    )
    assert python.personal_level == "L2"


def test_actual_rule_pack_language_context_does_not_make_l2_async_prerequisite_l3():
    rule_set = load_rule_pack(SCOPE_RULE_PACK_PATH).as_rule_set(
        mappings=mappings_from_registry_artifact(SCOPE_REGISTRY_PATH)
    )
    facts = (
        Fact(
            "SOURCE_FILE",
            {"LANGUAGE": "python", "IS_TEST": "false", "FILE_PATH": "tasks.py"},
            "tasks.py",
            1,
        ),
        Fact(
            "SYNTAX_NODE",
            {
                "KIND": "ASYNC_FUNCTION_DECLARATION",
                "LANGUAGE": "python",
                "IS_TEST": "false",
                "FILE_PATH": "tasks.py",
                "COMPONENT": "function:run@2:1",
            },
            "tasks.py",
            2,
        ),
        Fact(
            "SYNTAX_NODE",
            {
                "KIND": "TRY_FINALLY",
                "LANGUAGE": "python",
                "IS_TEST": "false",
                "FILE_PATH": "tasks.py",
                "COMPONENT": "function:run@2:1",
            },
            "tasks.py",
            6,
        ),
        *(
            Fact(
                "API_CALL",
                {
                    "METHOD": method,
                    "RESOLVED_MODULE": "asyncio",
                    "LANGUAGE": "python",
                    "IS_TEST": "false",
                    "FILE_PATH": "tasks.py",
                    "COMPONENT": "function:run@2:1",
                },
                "tasks.py",
                line,
            )
            for method, line in (("create_task", 3), ("wait_for", 5), ("cancel", 7))
        ),
    )
    judgement = Judge(rule_set).judge(facts)
    attributed = tuple(
        _owned(
            item,
            (
                "SELF"
                if item.fact.fields.get("KIND") == "ASYNC_FUNCTION_DECLARATION"
                else "OTHER"
            ),
        )
        for item in judgement.evidence
    )

    python = next(
        item
        for item in assess_personal_levels(rule_set, judgement, attributed)
        if item.tech_id == "python"
    )

    assert (
        next(
            verdict.level
            for verdict in judgement.verdicts
            if verdict.tech_id == "python"
        )
        == "L3"
    )
    assert python.personal_level == "L2"


def test_prerequisite_implication_only_proves_safe_exact_expected_subsets():
    lower_exact = Clause(
        100,
        1,
        "declaration",
        "REQUIRED",
        "SYNTAX_NODE",
        1,
        (
            Predicate(
                "KIND",
                "EXACT",
                None,
                ("TYPE_ALIAS_DECLARATION", "INTERFACE_DECLARATION"),
            ),
        ),
    )
    higher_exact = Clause(
        101,
        1,
        "alias",
        "REQUIRED",
        "SYNTAX_NODE",
        1,
        (Predicate("KIND", "EXACT", None, ("TYPE_ALIAS_DECLARATION",)),),
    )
    lower_prefix = Clause(
        102,
        1,
        "module",
        "REQUIRED",
        "IMPORT",
        1,
        (Predicate("MODULE", "PREFIX", ".", ("pkg",)),),
    )
    higher_module = Clause(
        103,
        1,
        "module",
        "REQUIRED",
        "IMPORT",
        1,
        (Predicate("MODULE", "EXACT", None, ("pkg.sub",)),),
    )

    assert _clause_implies_lower_prerequisite(higher_exact, lower_exact)
    assert not _clause_implies_lower_prerequisite(lower_exact, higher_exact)
    assert not _clause_implies_lower_prerequisite(higher_module, lower_prefix)


def test_actual_react_twenty_first_self_import_survives_display_cap(tmp_path):
    for index in range(20):
        (tmp_path / f"a{index:02d}.js").write_text(
            "import React from 'react';\n", encoding="utf-8"
        )
    (tmp_path / "zzz.js").write_text("import React from 'react';\n", encoding="utf-8")
    report = RepositoryParser().parse_repository(tmp_path)
    rule_set = load_rule_pack(SCOPE_RULE_PACK_PATH).as_rule_set(
        mappings=mappings_from_registry_artifact(SCOPE_REGISTRY_PATH)
    )
    judgement = Judge(rule_set, max_evidence_per_rule=20).judge(
        facts_from_imports(report.occurrences)
        + facts_from_calls(report.calls)
        + facts_from_sources(report.sources)
        + facts_from_annotations(report.annotations)
        + facts_from_syntax(report.syntax)
    )
    react_display = tuple(
        item for item in judgement.evidence if item.rule_id == "react.l1.import"
    )
    react_personal = tuple(
        item
        for item in judgement.personal_evidence
        if item.rule_id == "react.l1.import"
    )
    attributed = tuple(
        _owned(item, "SELF" if item.fact.file == "zzz.js" else "OTHER")
        for item in judgement.personal_evidence
    )
    display_only_attributed = tuple(_owned(item, "OTHER") for item in react_display)

    react = next(
        item
        for item in assess_personal_levels(rule_set, judgement, attributed)
        if item.tech_id == "react"
    )

    assert len(react_display) == 20
    assert len(react_personal) == 21
    assert all(item.fact.file != "zzz.js" for item in react_display)
    assert react.personal_level == "L1"
    assert any(
        proof.attribution == "SELF" and proof.evidence.fact.file == "zzz.js"
        for proof in react.proofs
    )
    display_only = next(
        item
        for item in assess_personal_levels(rule_set, judgement, display_only_attributed)
        if item.tech_id == "react"
    )
    assert display_only.personal_level is None
    assert display_only.attribution_status == "PARTIAL"
    assert any(
        scope.startswith("DECISIVE_FACT_ATTRIBUTION_INCOMPLETE")
        for scope in display_only.missing_scope
    )


def test_repository_aggregate_preserves_positive_but_not_negative_certainty():
    positive = PersonalTechnologyAssessment(
        "python", "L2", "L3", "COMPLETE", (), (_owned(FUNCTION_L2, "SELF"),)
    )
    shallow = PersonalTechnologyAssessment(
        "python",
        None,
        "L1",
        "UNKNOWN",
        ("BLAME_HISTORY_INCOMPLETE",),
        (),
    )

    combined = aggregate_personal_assessments(((positive,), (shallow,)))[0]

    assert combined.personal_level == "L2"
    assert combined.assessment_ceiling == "L2"
    assert combined.attribution_status == "PARTIAL"
    assert combined.missing_scope == ("BLAME_HISTORY_INCOMPLETE",)


def test_facts_from_two_repositories_never_complete_one_l3_rule():
    repository_one = Judge(RULE_SET).judge(
        (
            Fact("SOURCE_FILE", {"LANGUAGE": "python"}, "one.py", 1),
            Fact("SYNTAX_NODE", {"KIND": "FUNCTION"}, "one.py", 2),
        )
    )
    repository_two = Judge(RULE_SET).judge(
        (
            Fact("SOURCE_FILE", {"LANGUAGE": "python"}, "two.py", 1),
            Fact("API_CALL", {"METHOD": "wait_for"}, "two.py", 2),
        )
    )

    assessments = []
    for judgement in (repository_one, repository_two):
        attributed = tuple(_owned(item, "SELF") for item in judgement.evidence)
        assessments.append(assess_personal_levels(RULE_SET, judgement, attributed))

    combined = aggregate_personal_assessments(tuple(assessments))[0]

    assert [
        repository.verdicts[0].level for repository in (repository_one, repository_two)
    ] == [
        "L2",
        "L1",
    ]
    assert combined.personal_level == "L2"


def test_aggregate_preserves_same_local_fact_id_from_distinct_repositories():
    self_proof = _owned(
        FUNCTION_L2,
        "SELF",
        repository_analysis_id="analysis-repository-self",
    )
    other_proof = _owned(
        FUNCTION_L2,
        "OTHER",
        repository_analysis_id="analysis-repository-other",
    )
    self_assessment = PersonalTechnologyAssessment(
        "python", "L2", "L3", "COMPLETE", (), (self_proof,)
    )
    other_assessment = PersonalTechnologyAssessment(
        "python", "L0", "L3", "COMPLETE", (), (other_proof,)
    )

    combined = aggregate_personal_assessments(
        ((self_assessment,), (other_assessment,))
    )[0]

    assert combined.personal_level == "L2"
    assert {
        (proof.repository_analysis_id, proof.attribution) for proof in combined.proofs
    } == {
        ("analysis-repository-self", "SELF"),
        ("analysis-repository-other", "OTHER"),
    }


def test_actual_python_l2_comprehension_uses_only_the_selected_group(tmp_path):
    (tmp_path / "service.py").write_text(
        "def normalize(values):\n"
        "    return [value.strip() for value in values if value]\n",
        encoding="utf-8",
    )
    report = RepositoryParser().parse_repository(tmp_path)
    rule_set = load_rule_pack(SCOPE_RULE_PACK_PATH).as_rule_set(
        mappings=mappings_from_registry_artifact(SCOPE_REGISTRY_PATH)
    )
    judgement = Judge(rule_set).judge(
        facts_from_sources(report.sources) + facts_from_syntax(report.syntax)
    )
    python_evidence = tuple(
        item for item in judgement.evidence if item.tech_id == "python"
    )
    attributed = tuple(
        _owned(
            item,
            "UNKNOWN" if item.fact.fact_type == "SOURCE_FILE" else "SELF",
            missing=(
                ("EVIDENCE_LINE_UNAVAILABLE",)
                if item.fact.fact_type == "SOURCE_FILE"
                else ()
            ),
        )
        for item in python_evidence
    )

    assessment = next(
        item
        for item in assess_personal_levels(rule_set, judgement, attributed)
        if item.tech_id == "python"
    )

    assert judgement.matched_rule_groups["python.l2.structured-function"] == 1
    assert assessment.personal_level == "L2"
    assert not any(
        scope.startswith("DECISIVE_FACT_EVIDENCE_INCOMPLETE")
        for scope in assessment.missing_scope
    )
