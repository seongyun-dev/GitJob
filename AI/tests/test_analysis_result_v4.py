"""V4 adds C-produced personal attribution without changing historical v3."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from test_analysis_result_v2 import _reports, _request
from test_analysis_result_v3 import depth_result

from analysis.attribution import AttributedEvidence
from analysis.judge import EvidenceFact, Fact, Judgement, Verdict
from analysis.personal_level import PersonalTechnologyAssessment
from analysis.publish import completed_result
from analysis.results import RepositoryAnalysisResultV3, RepositoryAnalysisResultV4


def _personal_inputs():
    evidence = EvidenceFact(
        "python.l3.task-timeout-cleanup",
        "python",
        Fact(
            "API_CALL",
            {"METHOD": "wait_for", "FILE_PATH": "main.py"},
            "main.py",
            4,
            frozenset({"python"}),
        ),
    )
    judgement = Judgement(
        verdicts=(Verdict("python", "L3", ("python.l3.task-timeout-cleanup",)),),
        evidence=(evidence,),
        candidates=(),
        rule_pack_version="rule-pack-20260911.4",
        rule_pack_content_sha256="a" * 64,
        technology_support={
            "python": {
                "evaluation_scope": "REPOSITORY",
                "required_fact_types": ("API_CALL",),
                "max_supported_level": "L3",
                "coverage": "PARTIAL",
                "limitations": (),
            }
        },
    )
    attributed = AttributedEvidence(
        evidence,
        evidence.fact_id,
        "ar_common44",
        "SELF",
        "b" * 40,
    )
    assessment = PersonalTechnologyAssessment(
        "python", "L3", "L3", "COMPLETE", ("RULE_PACK_COVERAGE_PARTIAL",), (attributed,)
    )
    return judgement, (attributed,), (assessment,)


def test_personal_producer_uses_additive_v4_contract():
    request = _request().model_copy(
        update={
            "payload": _request().payload.model_copy(
                update={"registry_version": "registry-20260911.4"}
            )
        }
    )
    judgement, attribution, assessments = _personal_inputs()
    report, dependencies, configs = _reports()

    result = completed_result(
        request,
        judgement,
        report,
        dependencies,
        configs=configs,
        attributed_evidence=attribution,
        personal_assessments=assessments,
    )

    assert isinstance(result, RepositoryAnalysisResultV4)
    assert result.schema_version == "repository-analysis-result/v4"
    assert result.payload.technologies[0].level == "L3"
    assert result.payload.personal_assessments[0].personal_level == "L3"
    assert result.payload.evidence[0].fact_id == attribution[0].fact_id
    assert result.payload.evidence[0].repository_analysis_id == "ar_common44"
    assert result.payload.evidence[0].attribution == "SELF"
    assert result.payload.evidence[0].attribution_commit_sha == "b" * 40
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs/data/contracts/repository-analysis-result-v4.schema.json"
    )
    Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).validate(
        result.model_dump(mode="json")
    )


def test_preexisting_v3_result_remains_valid_and_has_no_personal_fields():
    result = depth_result()

    assert isinstance(result, RepositoryAnalysisResultV3)
    assert result.schema_version == "repository-analysis-result/v3"
    assert "personal_assessments" not in result.payload.model_dump()
    assert "attribution" not in result.payload.evidence[0].model_dump()


def test_v4_adds_bounded_decisive_proof_beyond_display_evidence_cap():
    request = _request().model_copy(
        update={
            "payload": _request().payload.model_copy(
                update={"registry_version": "registry-20260911.4"}
            )
        }
    )
    evidence = tuple(
        EvidenceFact(
            "react.l1.import",
            "react",
            Fact(
                "IMPORT",
                {"MODULE": "react", "FILE_PATH": f"a{index:02d}.js"},
                f"a{index:02d}.js",
                1,
                frozenset({"react"}),
            ),
        )
        for index in range(21)
    )
    judgement = Judgement(
        verdicts=(Verdict("react", "L1", ("react.l1.import",)),),
        evidence=evidence[:20],
        personal_evidence=evidence,
        candidates=(),
        rule_pack_version="rule-pack-20260911.4",
        rule_pack_content_sha256="a" * 64,
        technology_support={
            "react": {
                "evaluation_scope": "REPOSITORY",
                "required_fact_types": ("IMPORT",),
                "max_supported_level": "L3",
                "coverage": "SUPPORTED",
                "limitations": (),
            }
        },
    )
    attributed = tuple(
        AttributedEvidence(
            item,
            item.fact_id,
            "ar_common44",
            "SELF" if index == 20 else "OTHER",
            chr(ord("a") + (index % 6)) * 40,
        )
        for index, item in enumerate(evidence)
    )
    assessment = PersonalTechnologyAssessment(
        "react", "L1", "L3", "COMPLETE", (), (attributed[-1],)
    )
    report, dependencies, configs = _reports()

    result = completed_result(
        request,
        judgement,
        report,
        dependencies,
        configs=configs,
        attributed_evidence=attributed,
        personal_assessments=(assessment,),
    )

    assert len(result.payload.evidence) == 21
    assert attributed[-1].fact_id in {item.fact_id for item in result.payload.evidence}
    assert result.payload.personal_assessments[0].decisive_fact_ids == (
        attributed[-1].fact_id,
    )
