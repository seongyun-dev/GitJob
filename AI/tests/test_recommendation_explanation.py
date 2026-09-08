from test_recommendation_engine import make_analysis, recommend

from recommendation.evidence import EvidenceAnalysis
from recommendation.explanation import Explanation, explain_recommendations


def test_explanation_counts_and_sources_come_from_the_same_snapshot():
    result = recommend()
    explanation = explain_recommendations(result)
    assert explanation.snapshot_id == result.snapshot_id
    assert explanation.mode == "RULE"
    for candidate in result.candidates:
        facts = {
            fact.kind: fact
            for fact in explanation.facts
            if fact.tech_id == candidate.tech_id
        }
        assert facts["DEMAND"].values["denominator"] == result.demand.denominator
        assert facts["DEMAND"].values["total_count"] == candidate.demand.total_count
        what_if = facts["WHAT_IF"]
        assert what_if.values["current_count"] == candidate.what_if.current_count
        assert what_if.values["projected_count"] == candidate.what_if.projected_count
        assert what_if.values["increased_count"] == len(
            candidate.what_if.newly_matched_job_ids
        )
        assert set(what_if.source_refs) == {
            str(job.source_url)
            for job in result.jobs
            if job.job_id in candidate.what_if.newly_matched_job_ids
        }
    assert Explanation.model_validate_json(explanation.model_dump_json()) == explanation


def test_external_plan_cannot_add_text_change_numbers_or_reuse_another_snapshot():
    result = recommend()
    original = explain_recommendations(result)
    plan = {
        "schema_version": "explanation-order/v1",
        "snapshot_id": result.snapshot_id,
        "fact_ids": [fact.fact_id for fact in reversed(original.facts)],
    }
    reordered = explain_recommendations(result, narrative_plan=plan)
    assert reordered.mode == "GROUNDED_SELECTION"
    assert reordered.facts == tuple(reversed(original.facts))
    invalid = [
        {**plan, "text": "합격 확률 100%"},
        {**plan, "snapshot_id": "other"},
        {**plan, "fact_ids": plan["fact_ids"][:-1]},
        {**plan, "fact_ids": plan["fact_ids"] + ["invented"]},
        {**plan, "fact_ids": plan["fact_ids"] + plan["fact_ids"][:1]},
    ]
    for value in invalid:
        fallback = explain_recommendations(result, narrative_plan=value)
        assert fallback.mode == "RULE"
        assert fallback.fallback_reason == "INVALID_NARRATIVE_PLAN"
        assert fallback.facts == original.facts


def test_project_participation_is_not_described_as_self_authorship():
    payload = make_analysis().model_dump(mode="json")
    payload["repositories"][0]["technologies"][0].update(
        evidence_level="L2", implemented_by="OTHER"
    )
    for proof in payload["repositories"][0]["technologies"][0]["proofs"]:
        if proof["kind"] == "IMPLEMENTATION":
            proof["attribution"] = "OTHER"
    result = recommend(analysis=EvidenceAnalysis.model_validate(payload))
    explanation = explain_recommendations(result)
    texts = [fact.text for fact in explanation.facts if fact.kind == "EVIDENCE"]
    assert any("참여한 프로젝트" in text for text in texts)
    assert all("직접 작성" not in text for text in texts)


def test_failed_peer_and_unrelated_fact_never_support_positive_evidence_sentence():
    from copy import deepcopy

    payload = make_analysis().model_dump(mode="json")
    failed = deepcopy(payload["repositories"][0])
    failed.update(
        repository_id="failed-repo",
        repository_analysis_id="failed-analysis",
        status="FAILED",
        coverage_complete=False,
    )
    for proof in failed["technologies"][0]["proofs"]:
        proof.update(
            repository_id="failed-repo",
            repository_analysis_id="failed-analysis",
            source_ref="b-evidence://failed-repo/rejected",
        )
    payload["repositories"].append(failed)
    result = recommend(analysis=EvidenceAnalysis.model_validate(payload))
    fact = next(
        fact
        for fact in explain_recommendations(result).facts
        if fact.kind == "EVIDENCE" and fact.tech_id == "java"
    )
    assert fact.source_refs == ("b-evidence://repo-1/IMPLEMENTATION/1",)
    assert fact.values["fact_ids"] == ["fact-IMPLEMENTATION-1"]
    assert all(
        scope["repository_id"] == "repo-1" for scope in fact.values["supporting_scope"]
    )
    assert (
        len(fact.values["profiles"]) == 2
    )  # rejected scope remains inspectable, not cited


def test_l1_explanation_describes_confirmed_observation_not_self_implementation():
    from test_evidence_profiles import profile_payload

    result = recommend(analysis=EvidenceAnalysis.model_validate(profile_payload("L1")))
    fact = next(
        fact
        for fact in explain_recommendations(result).facts
        if fact.kind == "EVIDENCE" and fact.tech_id == "java"
    )
    assert "직접 의존성" in fact.text
    assert "추천 계산에 포함" in fact.text
    assert "직접 작성" not in fact.text
    assert set(fact.source_refs) == {
        "b-evidence://repo-1/DIRECT_DEPENDENCY/1",
        "b-evidence://repo-1/PARTICIPATION/1",
    }


def test_proofless_legacy_input_cannot_generate_positive_source_claims():
    from test_evidence_consumption import legacy_analysis_payload

    result = recommend(
        analysis=EvidenceAnalysis.model_validate(legacy_analysis_payload())
    )
    fact = next(
        fact
        for fact in explain_recommendations(result).facts
        if fact.kind == "EVIDENCE" and fact.tech_id == "java"
    )
    assert "미확정" in fact.text
    assert fact.source_refs == ()
    assert fact.values["fact_ids"] == []
