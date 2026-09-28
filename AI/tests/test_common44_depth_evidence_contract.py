"""New structural result -> explicit synthetic B attribution -> C v4 consumption."""

import json

from depth_helpers import AI_ROOT, DEPTH_REGISTRY, depth_pack, evaluate_depth_files
from test_analysis_result_v2 import _request
from test_job_cohort import batch, criteria, posting

from analysis.configs import ConfigScanner
from analysis.manifests import ManifestScanner
from analysis.parse import RepositoryParser
from analysis.publish import completed_result
from analysis.results import RepositoryAnalysisResultV3
from job.cohort import build_cohort
from job.matching import build_job_matching
from recommendation.engine import build_recommendations
from recommendation.evidence import (
    EvidenceAnalysis,
    consume_evidence,
    consume_personal_assessments,
)
from registry.contracts import load_registry
from registry.mapper import RegistryMapper


def test_depth_l3_repository_results_preserve_personal_l1_and_partial(tmp_path):
    fixture = json.loads(
        (AI_ROOT / "tests/fixtures/common44-depth-b-evidence-v4.json").read_text(
            "utf-8"
        )
    )
    pack = depth_pack()
    observed_personal = []
    for source, declared in zip(
        fixture["repositories"],
        fixture["evidence_consumption_input"]["repositories"],
        strict=True,
    ):
        root = tmp_path / source["repository_id"]
        judgement = evaluate_depth_files(root, source["files"])
        request = _request()
        request = request.model_copy(
            update={
                "payload": request.payload.model_copy(
                    update={"registry_version": pack.registry_version}
                )
            }
        )
        result = completed_result(
            request,
            judgement,
            RepositoryParser().parse_repository(root),
            ManifestScanner().scan(root),
            configs=ConfigScanner().scan(root),
        )
        result = RepositoryAnalysisResultV3.model_validate_json(
            result.model_dump_json()
        )
        assert result.payload.rule_pack_content_sha256 == pack.content_sha256
        assert (
            next(t.level for t in result.payload.technologies if t.tech_id == "python")
            == "L3"
        )
        assert any(e.fact_type == "SYNTAX_NODE" for e in result.payload.evidence)
        for proof in declared["technologies"][0]["proofs"]:
            assert any(
                e.rule_id == proof["rule_id"]
                and e.file_path == proof["path"]
                and e.start_line == proof["line_start"]
                for e in result.payload.evidence
            )
        owned_files = {
            path: text
            for path, text in source["files"].items()
            if path in source["accepted_self_paths"]
        }
        personal = evaluate_depth_files(
            tmp_path / (source["repository_id"] + "-owned"), owned_files
        )
        observed_personal.extend(
            v.level for v in personal.verdicts if v.tech_id == "python"
        )
    assert observed_personal == ["L1"]

    analysis = EvidenceAnalysis.model_validate(fixture["evidence_consumption_input"])
    assert (analysis.registry_version, analysis.evidence_rule_version) == (
        pack.registry_version,
        pack.rule_pack_version,
    )
    selection = consume_evidence(
        analysis,
        user_id=analysis.user_id,
        analysis_id=analysis.analysis_id,
        tech_ids=("python",),
    )
    personal = consume_personal_assessments(analysis, selection)["python"]
    assert (
        personal.personal_level,
        personal.assessment_ceiling,
        personal.scope_complete,
    ) == ("L1", "L3", False)
    cohort = build_cohort(
        batch(posting("python-basic", required=("Python",))),
        criteria(),
        RegistryMapper(load_registry(DEPTH_REGISTRY, repository_root=AI_ROOT.parent)),
    )
    matching = build_job_matching(
        cohort, analysis, user_id=analysis.user_id, analysis_id=analysis.analysis_id
    )
    recommendation = build_recommendations(
        cohort, analysis, user_id=analysis.user_id, analysis_id=analysis.analysis_id
    )
    assert matching.registry_version == pack.registry_version
    assert recommendation.personal_levels == {"python": "L1"}
    assert recommendation.assessment_ceilings == {"python": "L3"}
    assert recommendation.level_assessment_complete_tech_ids == ()
    assert "RULE_PACK_PARTIAL" in recommendation.data_gaps
