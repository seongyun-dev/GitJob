"""Executable C Rule Pack -> synthetic B attribution/aggregate -> C v4 contract.

The file ownership below is an explicit fixture answer, not a blame algorithm.
Actual OAuth/attribution and the B service consumer remain B acceptance work.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from test_job_cohort import batch, criteria, posting

from analysis.judge import (
    Judge,
    facts_from_calls,
    facts_from_dependencies,
    facts_from_imports,
)
from analysis.manifests import ManifestScanner
from analysis.parse import RepositoryParser
from analysis.results import RepositoryAnalysisResult
from analysis.rulepack import (
    RULE_PACK_PATH,
    load_rule_pack,
    mappings_from_registry_artifact,
)
from job.cohort import build_cohort
from job.matching import build_job_matching
from job.requirements import (
    RequirementLevel,
    RequirementLevelEvidence,
    RequirementLevelEvidenceSource,
)
from recommendation.engine import build_recommendations
from recommendation.evidence import (
    EvidenceAnalysis,
    consume_evidence,
    consume_personal_assessments,
)
from registry.contracts import load_registry
from registry.mapper import RegistryMapper

AI_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = AI_ROOT / "tests/fixtures/common44-b-evidence-v4.json"
REGISTRY = AI_ROOT / "registry/data/technology_registry_20260911_2.json"


def test_two_repository_verdicts_do_not_replace_the_personal_level(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack = load_rule_pack(RULE_PACK_PATH)
    rules = pack.as_rule_set(mappings=mappings_from_registry_artifact(REGISTRY))
    payload = fixture["evidence_consumption_input"]
    assert payload["registry_version"] == pack.registry_version
    assert payload["evidence_rule_version"] == pack.rule_pack_version
    observed_personal_levels = []

    for source, expected in zip(
        fixture["repositories"], payload["repositories"], strict=True
    ):
        root = tmp_path / source["repository_id"]
        for path, content in source["files"].items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        report = RepositoryParser().parse_repository(root)
        dependencies = ManifestScanner().scan(root)
        facts = (
            facts_from_imports(report.occurrences)
            + facts_from_calls(report.calls)
            + facts_from_dependencies(dependencies.occurrences)
        )
        verdict = Judge(rules).judge(facts)
        actual = {item.tech_id: item.level for item in verdict.verdicts}
        assert actual["react"] == expected["technologies"][0]["evidence_level"] == "L2"

        # The fixture's B acceptance answer names exactly the self-owned files.
        # Evaluate those facts again; do not take max(repository verdicts).
        owned = [fact for fact in facts if fact.file in source["accepted_self_paths"]]
        personal = Judge(rules).judge(owned)
        observed_personal_levels.extend(
            item.level for item in personal.verdicts if item.tech_id == "react"
        )
        for proof in expected["technologies"][0]["proofs"]:
            assert any(
                item.rule_id == proof["rule_id"]
                and item.fact.file == proof["path"]
                and item.fact.line == proof["line_start"]
                for item in verdict.evidence
            )

    assert observed_personal_levels == ["L1"]
    declared = payload["personal_assessments"][0]
    assert declared["personal_level"] == "L1"
    assert declared["assessment_ceiling"] == pack.support["react"].max_supported_level
    analysis = EvidenceAnalysis.model_validate(payload)
    selection = consume_evidence(
        analysis,
        user_id=analysis.user_id,
        analysis_id=analysis.analysis_id,
        tech_ids=("react",),
    )
    assert selection.held_tech_ids == ("react",)
    assessment = consume_personal_assessments(analysis, selection)["react"]
    assert assessment.personal_level == "L1"
    assert assessment.assessment_ceiling == "L2"
    assert (
        not assessment.scope_complete
    )  # Partial repository/Rule coverage is preserved.


def test_missing_b_personal_assessment_stays_unknown():
    payload = copy.deepcopy(
        json.loads(FIXTURE.read_text(encoding="utf-8"))["evidence_consumption_input"]
    )
    payload["personal_assessments"] = []
    analysis = EvidenceAnalysis.model_validate(payload)
    selection = consume_evidence(
        analysis,
        user_id=analysis.user_id,
        analysis_id=analysis.analysis_id,
        tech_ids=("react",),
    )
    assert selection.held_tech_ids == ("react",)
    assert consume_personal_assessments(analysis, selection) == {}


def test_actual_common44_evidence_drives_matching_and_recommendation(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack = load_rule_pack(RULE_PACK_PATH)
    rules = pack.as_rule_set(mappings=mappings_from_registry_artifact(REGISTRY))
    repository_levels = []
    owned_facts = []

    for source in fixture["repositories"]:
        root = tmp_path / source["repository_id"]
        for path, content in source["files"].items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        report = RepositoryParser().parse_repository(root)
        dependencies = ManifestScanner().scan(root)
        facts = (
            facts_from_imports(report.occurrences)
            + facts_from_calls(report.calls)
            + facts_from_dependencies(dependencies.occurrences)
        )
        verdict = Judge(rules).judge(facts)
        repository_levels.append(
            next(item.level for item in verdict.verdicts if item.tech_id == "react")
        )
        owned_facts.extend(
            fact for fact in facts if fact.file in source["accepted_self_paths"]
        )

    assert repository_levels == ["L2", "L2"]
    personal = Judge(rules).judge(owned_facts)
    assert (
        next(item.level for item in personal.verdicts if item.tech_id == "react")
        == "L1"
    )

    analysis = EvidenceAnalysis.model_validate(fixture["evidence_consumption_input"])
    base = build_cohort(
        batch(
            posting("react-l1", required=("React",)),
            posting("react-l2", required=("React",)),
            posting("react-l3", required=("React",)),
        ),
        criteria(),
        RegistryMapper(load_registry(REGISTRY, repository_root=AI_ROOT.parent)),
    )
    assert base.registry_version == analysis.registry_version
    levels = {
        "react-l1": RequirementLevel.L1,
        "react-l2": RequirementLevel.L2,
        "react-l3": RequirementLevel.L3,
    }

    def with_level(clause, level):
        return clause.model_copy(
            update={
                "required_level": level,
                "level_evidence_refs": (
                    RequirementLevelEvidence(
                        source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                        level=level,
                        text=f"fixture {level.value}",
                        mention_indices=(0,),
                    ),
                ),
            }
        )

    cohort = base.model_copy(
        update={
            "jobs": tuple(
                job.model_copy(
                    update={
                        "levelled_required_clauses": tuple(
                            with_level(clause, levels[job.job_id])
                            for clause in job.levelled_required_clauses or ()
                        )
                    }
                )
                for job in base.jobs
            ),
            "matching_jobs": tuple(
                job.model_copy(
                    update={
                        "requirements": job.requirements.model_copy(
                            update={
                                "required": tuple(
                                    with_level(clause, levels[job.job_id])
                                    for clause in job.requirements.required
                                )
                            }
                        )
                    }
                )
                for job in base.matching_jobs or ()
            ),
        }
    )

    matching = build_job_matching(
        cohort,
        analysis,
        user_id=analysis.user_id,
        analysis_id=analysis.analysis_id,
    )
    by_job = {row.job.job_id: row for row in matching.jobs}
    assert by_job["react-l1"].required.clauses[0].verdict == "SATISFIED"
    assert by_job["react-l1"].required_status == "FULL"
    for job_id in ("react-l2", "react-l3"):
        assert by_job[job_id].required.clauses[0].verdict == "EVIDENCE_SCOPE_INCOMPLETE"
        assert by_job[job_id].required_status == "UNKNOWN"

    recommendation = build_recommendations(
        cohort,
        analysis,
        user_id=analysis.user_id,
        analysis_id=analysis.analysis_id,
    )
    assert recommendation.current_job_ids == ("react-l1",)
    assert recommendation.personal_levels == {"react": "L1"}
    assert recommendation.assessment_ceilings == {"react": "L2"}
    assert "PERSONAL_LEVEL_SCOPE_INCOMPLETE:react" in recommendation.data_gaps
    assert "ASSESSMENT_CEILING_BELOW_REQUIREMENT:react:L3" in recommendation.data_gaps


def test_exact_base_generated_v1_result_remains_readable():
    # Created using clean 3a4c57c's model and completed-result scenario, before
    # importing any working-tree model. It is not a relabelled v2 result.
    path = AI_ROOT / "tests/fixtures/repository-analysis-result-v1-base-3a4c57c.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = RepositoryAnalysisResult.model_validate(payload)
    assert result.model_dump(mode="json") == payload
    assert result.schema_version == "repository-analysis-result/v1"
    assert result.payload.technologies[0].level == "L3"
