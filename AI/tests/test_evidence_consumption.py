"""B-result consumption never turns incomplete analysis into negative evidence."""

import json

import pytest
from evidence_fixtures import proof_payload
from pydantic import ValidationError

from recommendation.evidence import (
    EvidenceAnalysis,
    HeldStatus,
    HeldTechnologySelection,
    build_gap,
    consume_evidence,
    consume_personal_assessments,
    consume_personal_levels,
)


def legacy_analysis_payload() -> dict:
    return {
        "schema_version": "evidence-consumption-input/v1",
        "user_id": "user-1",
        "analysis_id": "analysis-1",
        "registry_version": "registry-20260901.1",
        "level_policy_version": "level-policy/v2",
        "evidence_rule_version": "evidence-rules/v2",
        "status": "COMPLETE",
        "repositories": [
            {
                "user_id": "user-1",
                "repository_id": "repo-1",
                "repository_analysis_id": "repo-analysis-1",
                "commit_sha": "a" * 40,
                "status": "COMPLETE",
                "coverage_complete": True,
                "evaluated_tech_ids": ["java", "docker"],
                "technologies": [
                    {
                        "tech_id": "java",
                        "fact_ids": ["fact-java-1"],
                        "evidence_level": "L3",
                        "direct_dependency": None,
                        "implementation_present": True,
                        "user_participation": True,
                        "implemented_by": "SELF",
                        "attribution_status": "COMPLETE",
                        "source_refs": [
                            "https://github.com/example/repo/blob/aaa/A.java"
                        ],
                    }
                ],
            }
        ],
    }


def analysis_payload() -> dict:
    """Same scenario with explicit synthetic v2 dependency/participation/source proof."""
    payload = legacy_analysis_payload()
    payload["schema_version"] = "evidence-consumption-input/v2"
    evidence = payload["repositories"][0]["technologies"][0]
    evidence["direct_dependency"] = True
    evidence["proofs"] = [
        proof_payload(kind)
        for kind in ("DIRECT_DEPENDENCY", "PARTICIPATION", "IMPLEMENTATION")
    ]
    evidence["fact_ids"] = [proof["fact_id"] for proof in evidence["proofs"]]
    return payload


def consume(payload: dict, tech_ids: tuple[str, ...] = ("java", "docker")):
    return consume_evidence(
        EvidenceAnalysis.model_validate_json(json.dumps(payload)),
        user_id="user-1",
        analysis_id="analysis-1",
        tech_ids=tech_ids,
    )


def v4_analysis_payload(*, level: str = "L2", ceiling: str = "L2") -> dict:
    payload = analysis_payload()
    payload["schema_version"] = "evidence-consumption-input/v4"
    payload["personal_assessments"] = [
        {
            "tech_id": "java",
            "personal_level": level,
            "assessment_ceiling": ceiling,
            "attribution_status": "COMPLETE",
            "missing_scope": (["L3_RULE_NOT_SUPPORTED"] if ceiling != "L3" else []),
        }
    ]
    return payload


def test_v4_requires_a_personal_level_and_assessment_ceiling_pair():
    payload = v4_analysis_payload()
    del payload["personal_assessments"][0]["assessment_ceiling"]

    with pytest.raises(ValueError, match="assessment_ceiling"):
        EvidenceAnalysis.model_validate(payload)


def test_v4_rejects_personal_level_above_assessment_ceiling():
    with pytest.raises(ValueError, match="above assessment ceiling"):
        EvidenceAnalysis.model_validate(v4_analysis_payload(level="L3", ceiling="L2"))


def test_v4_exposes_level_ceiling_and_complete_scope_separately():
    analysis = EvidenceAnalysis.model_validate(v4_analysis_payload())
    selection = consume_evidence(
        analysis,
        user_id="user-1",
        analysis_id="analysis-1",
        tech_ids=("java",),
    )

    assessment = consume_personal_assessments(analysis, selection)["java"]

    assert assessment.personal_level == "L2"
    assert assessment.assessment_ceiling == "L2"
    assert assessment.scope_complete is True
    assert assessment.missing_scope == ("L3_RULE_NOT_SUPPORTED",)


def test_v4_partial_analysis_keeps_positive_level_but_not_below_level_certainty():
    payload = v4_analysis_payload()
    payload["status"] = "PARTIAL"
    payload["repositories"][0].update(status="PARTIAL", coverage_complete=False)
    analysis = EvidenceAnalysis.model_validate(payload)
    selection = consume_evidence(
        analysis,
        user_id="user-1",
        analysis_id="analysis-1",
        tech_ids=("java",),
    )

    assessment = consume_personal_assessments(analysis, selection)["java"]

    assert assessment.personal_level == "L2"
    assert assessment.scope_complete is False


def test_v4_partial_peer_repository_prevents_a_negative_level_conclusion():
    payload = v4_analysis_payload(level="L1", ceiling="L3")
    peer = json.loads(json.dumps(payload["repositories"][0]))
    peer.update(
        repository_id="repo-2",
        repository_analysis_id="repo-analysis-2",
        commit_sha="b" * 40,
        status="PARTIAL",
        coverage_complete=False,
    )
    for technology in peer["technologies"]:
        for proof in technology["proofs"]:
            proof.update(
                evidence_id=proof["evidence_id"] + "-peer",
                repository_id="repo-2",
                repository_analysis_id="repo-analysis-2",
                source_commit_sha="b" * 40,
                attribution_commit_sha="b" * 40,
            )
    payload["repositories"].append(peer)
    payload["status"] = "PARTIAL"
    analysis = EvidenceAnalysis.model_validate(payload)
    selection = consume_evidence(
        analysis,
        user_id="user-1",
        analysis_id="analysis-1",
        tech_ids=("java",),
    )

    assessment = consume_personal_assessments(analysis, selection)["java"]

    assert assessment.personal_level == "L1"
    assert assessment.assessment_ceiling == "L3"
    assert assessment.scope_complete is False


@pytest.mark.parametrize(
    "schema_version",
    ["evidence-consumption-input/v3", "evidence-consumption-input/v4"],
)
def test_personal_level_is_not_interpreted_under_an_unknown_level_policy(
    schema_version,
):
    payload = v4_analysis_payload()
    payload["schema_version"] = schema_version
    payload["level_policy_version"] = "level-policy/future"
    if schema_version == "evidence-consumption-input/v3":
        payload.pop("personal_assessments")
        payload["repositories"][0]["technologies"][0]["personal_level"] = "L2"
    analysis = EvidenceAnalysis.model_validate(payload)
    selection = consume_evidence(
        analysis,
        user_id="user-1",
        analysis_id="analysis-1",
        tech_ids=("java",),
    )

    if schema_version == "evidence-consumption-input/v3":
        assert consume_personal_levels(analysis, selection) == {}
    else:
        assert consume_personal_assessments(analysis, selection) == {}


def test_self_implementation_is_held_and_scan_scoped_absence_has_reason():
    result = consume(analysis_payload())
    assert result.held_tech_ids == ("java",)
    java, docker = result.by_tech_id["java"], result.by_tech_id["docker"]
    assert java.status is HeldStatus.HELD
    assert "SELF_IMPLEMENTATION" in java.reason_codes
    assert docker.status is HeldStatus.NOT_HELD
    assert docker.reason_codes == ("NO_QUALIFYING_EVIDENCE_IN_ANALYZED_REPOSITORIES",)
    assert java.provenance[0].fact_ids == (
        "fact-DIRECT_DEPENDENCY-1",
        "fact-IMPLEMENTATION-1",
        "fact-PARTICIPATION-1",
    )
    assert java.provenance[0].analysis_id == "analysis-1"
    assert java.provenance[0].commit_sha == "a" * 40
    assert (
        HeldTechnologySelection.model_validate_json(result.model_dump_json()) == result
    )


@pytest.mark.parametrize(
    ("changes", "expected", "reason"),
    [
        (
            {
                "evidence_level": "L1",
                "direct_dependency": True,
                "implementation_present": False,
                "implemented_by": "NONE",
            },
            "HELD",
            "ELIGIBLE_DIRECT_DEPENDENCY",
        ),
        (
            {"evidence_level": "L2", "implemented_by": "OTHER"},
            "HELD",
            "PROJECT_IMPLEMENTATION_WITH_PARTICIPATION",
        ),
        (
            {
                "evidence_level": "L2",
                "implemented_by": "OTHER",
                "user_participation": False,
            },
            "UNKNOWN",
            "INCONSISTENT_LEVEL_FACTS",
        ),
        (
            {"evidence_level": "L3", "attribution_status": "PARTIAL"},
            "HELD",
            "SELF_IMPLEMENTATION",
        ),
        (
            {"evidence_level": "L2", "implementation_present": None},
            "HELD",
            "SELF_IMPLEMENTATION",
        ),
        (
            {"evidence_level": "L3", "implemented_by": "OTHER"},
            "UNKNOWN",
            "INCONSISTENT_LEVEL_FACTS",
        ),
    ],
)
def test_held_policy_uses_authoritative_level_and_explicit_b_facts(
    changes, expected, reason
):
    payload = analysis_payload()
    evidence = payload["repositories"][0]["technologies"][0]
    evidence.update(changes)
    if changes.get("evidence_level") == "L1":
        evidence["proofs"] = [
            proof for proof in evidence["proofs"] if proof["kind"] != "IMPLEMENTATION"
        ]
    if (
        changes.get("evidence_level") == "L2"
        and changes.get("implemented_by") == "OTHER"
    ):
        for proof in evidence["proofs"]:
            if proof["kind"] == "IMPLEMENTATION":
                proof["attribution"] = "OTHER"
    decision = consume(payload).by_tech_id["java"]
    assert decision.status.value == expected
    assert reason in decision.reason_codes


@pytest.mark.parametrize(
    "status", ["PARTIAL", "FAILED", "UNSUPPORTED", "PERMISSION_DENIED"]
)
def test_incomplete_repository_does_not_create_absence(status):
    payload = analysis_payload()
    payload["status"] = "PARTIAL"
    payload["repositories"][0]["status"] = status
    payload["repositories"][0]["coverage_complete"] = False
    result = consume(payload)
    assert result.by_tech_id["docker"].status is HeldStatus.UNKNOWN
    assert result.data_gaps
    if status == "PARTIAL":
        assert result.held_tech_ids == ("java",)
    else:
        assert result.held_tech_ids == ()


def test_unknown_level_policy_is_not_reinterpreted_but_independent_proof_survives():
    payload = analysis_payload()
    payload["level_policy_version"] = "legacy-personal-level/v1"
    result = consume(payload)
    assert result.held_tech_ids == ("java",)
    assert result.by_tech_id["java"].profiles[0].verified_level is None
    assert result.by_tech_id["docker"].status is HeldStatus.UNKNOWN
    assert "UNSUPPORTED_LEVEL_POLICY:legacy-personal-level/v1" in result.data_gaps
    payload["repositories"][0]["technologies"][0]["personalLevel"] = 2
    with pytest.raises(ValidationError):
        EvidenceAnalysis.model_validate(payload)


@pytest.mark.parametrize(
    "location", ["analysis_user", "analysis_id", "repository_user"]
)
def test_identity_mismatch_fails_closed(location):
    payload = analysis_payload()
    if location == "analysis_user":
        payload["user_id"] = "user-2"
    elif location == "analysis_id":
        payload["analysis_id"] = "analysis-2"
    else:
        payload["repositories"][0]["user_id"] = "user-2"
    with pytest.raises(PermissionError):
        consume(payload)


def test_multiple_repositories_preserve_provenance_and_positive_evidence_with_partial_peer():
    payload = analysis_payload()
    other = json.loads(json.dumps(payload["repositories"][0]))
    other.update(repository_id="repo-2", repository_analysis_id="repo-analysis-2")
    other["technologies"][0]["fact_ids"] = ["fact-java-2"]
    for proof in other["technologies"][0]["proofs"]:
        proof.update(
            repository_id="repo-2",
            repository_analysis_id="repo-analysis-2",
            fact_id="fact-java-2",
        )
    payload["repositories"].append(other)
    result = consume(payload)
    assert result.held_tech_ids == ("java",)
    assert {x.repository_id for x in result.by_tech_id["java"].provenance} == {
        "repo-1",
        "repo-2",
    }
    other.update(status="FAILED", coverage_complete=False, technologies=[])
    payload["status"] = "PARTIAL"
    result = consume(payload)
    assert result.held_tech_ids == ("java",)
    assert result.by_tech_id["docker"].status is HeldStatus.UNKNOWN


def test_empty_analysis_cannot_assert_no_evidence_and_duplicate_snapshots_are_rejected():
    payload = analysis_payload()
    payload["repositories"] = []
    result = consume(payload)
    assert all(item.status is HeldStatus.UNKNOWN for item in result.technologies)
    payload = analysis_payload()
    payload["repositories"].append(payload["repositories"][0])
    with pytest.raises(ValidationError, match="duplicate repository"):
        EvidenceAnalysis.model_validate(payload)


def test_input_order_and_exact_duplicate_facts_do_not_change_output():
    payload = analysis_payload()
    tech = payload["repositories"][0]["technologies"][0]
    first = consume(payload, ("docker", "java", "java"))
    payload["repositories"][0]["technologies"].append(tech)
    second = consume(payload, ("java", "docker"))
    assert first == second


def test_gap_retains_unknown_separately_from_missing():
    selection = consume(analysis_payload())
    gap = build_gap(selection, demanded_tech_ids=("java", "docker", "unassessed"))
    assert gap.held_tech_ids == ("java",)
    assert gap.missing_tech_ids == ("docker",)
    assert gap.unknown_tech_ids == ("unassessed",)
    assert gap.technologies[0] == selection.by_tech_id["docker"]


def test_conflicting_same_fact_is_rejected_and_reference_order_is_canonical():
    payload = analysis_payload()
    evidence = payload["repositories"][0]["technologies"][0]
    evidence["fact_ids"] = ["fact-java-2", "fact-java-1", "fact-java-2"]
    assert consume(payload).by_tech_id["java"].provenance[0].fact_ids == (
        "fact-java-1",
        "fact-java-2",
    )
    conflicting = dict(evidence, implemented_by="OTHER")
    payload["repositories"][0]["technologies"].append(conflicting)
    with pytest.raises(ValidationError, match="conflicting assessments"):
        EvidenceAnalysis.model_validate(payload)


def test_failed_analysis_cannot_publish_stale_positive_results():
    payload = analysis_payload()
    payload["status"] = "FAILED"
    result = consume(payload)
    assert result.held_tech_ids == ()
    assert all(item.status is HeldStatus.UNKNOWN for item in result.technologies)


def test_complete_repository_without_explicit_technology_coverage_is_unknown():
    payload = analysis_payload()
    payload["repositories"][0].pop("evaluated_tech_ids")
    result = consume(payload)
    assert result.held_tech_ids == ("java",)
    assert result.by_tech_id["docker"].status is HeldStatus.UNKNOWN
    assert "TECHNOLOGY_NOT_COVERED:repo-1" in result.by_tech_id["docker"].data_gaps
    payload["repositories"][0]["evaluated_tech_ids"] = ["java"]
    assert consume(payload).by_tech_id["docker"].status is HeldStatus.UNKNOWN


def test_uncovered_peer_prevents_negative_inference_and_none_author_contradicts_implementation():
    payload = analysis_payload()
    other = dict(
        payload["repositories"][0],
        repository_id="repo-2",
        repository_analysis_id="repo-analysis-2",
        evaluated_tech_ids=["java"],
        technologies=[],
    )
    payload["repositories"].append(other)
    assert consume(payload).by_tech_id["docker"].status is HeldStatus.UNKNOWN
    payload = analysis_payload()
    payload["repositories"][0]["technologies"][0].update(
        evidence_level="L2", implemented_by="NONE"
    )
    decision = consume(payload).by_tech_id["java"]
    assert decision.status is HeldStatus.UNKNOWN
    assert "INCONSISTENT_LEVEL_FACTS" in decision.reason_codes


def test_persisted_negative_decision_retains_repository_scope_without_raw_input():
    selection = consume(analysis_payload())
    restored = HeldTechnologySelection.model_validate_json(selection.model_dump_json())
    scope = restored.repository_coverage[0]
    assert scope.repository_id == "repo-1"
    assert scope.repository_analysis_id == "repo-analysis-1"
    assert scope.commit_sha == "a" * 40
    assert scope.status == "COMPLETE"
    assert scope.coverage_complete is True
    assert scope.evaluated_tech_ids == ("docker", "java")
    assert restored.user_id == "user-1"
    assert restored.analysis_id == "analysis-1"
    assert restored.evidence_rule_version == "evidence-rules/v2"
    assert restored.by_tech_id["docker"].status is HeldStatus.NOT_HELD
    payload = restored.model_dump(mode="json")
    payload["repository_coverage"][0]["evaluated_tech_ids"] = ["java"]
    with pytest.raises(ValidationError, match="complete explicit technology coverage"):
        HeldTechnologySelection.model_validate(payload)


def test_failed_and_unsupported_repository_scopes_survive_serialization():
    payload = analysis_payload()
    payload["status"] = "PARTIAL"
    payload["repositories"][0].update(
        status="UNSUPPORTED",
        coverage_complete=False,
        evaluated_tech_ids=[],
        technologies=[],
        data_gaps=["UNSUPPORTED_RULE"],
    )
    restored = HeldTechnologySelection.model_validate_json(
        consume(payload).model_dump_json()
    )
    scope = restored.repository_coverage[0]
    assert scope.status == "UNSUPPORTED"
    assert not scope.coverage_complete
    assert scope.evaluated_tech_ids == ()
    assert scope.data_gaps == ("UNSUPPORTED_RULE",)


@pytest.mark.parametrize(
    "changes",
    [
        {
            "evidence_level": "L1",
            "direct_dependency": True,
            "implementation_present": False,
            "implemented_by": "SELF",
        },
        {
            "evidence_level": "L0",
            "direct_dependency": False,
            "implementation_present": False,
            "implemented_by": "SELF",
        },
        {
            "evidence_level": "L1",
            "direct_dependency": True,
            "implementation_present": False,
            "implemented_by": "OTHER",
        },
        {"evidence_level": "L3", "implemented_by": "SELF", "user_participation": False},
    ],
)
def test_contradictory_authorship_facts_never_create_a_confirmed_gap(changes):
    payload = analysis_payload()
    payload["repositories"][0]["technologies"][0].update(changes)
    selection = consume(payload)
    decision = selection.by_tech_id["java"]
    assert decision.status is HeldStatus.UNKNOWN
    assert "INCONSISTENT_LEVEL_FACTS" in decision.reason_codes
    assert build_gap(selection, demanded_tech_ids=("java",)).missing_tech_ids == ()
