"""Synthetic B contract calibration; fixtures do not prove real source/blame."""

from copy import deepcopy

import pytest
from evidence_fixtures import proof_payload
from test_evidence_consumption import legacy_analysis_payload as analysis_payload

from recommendation.evidence import EvidenceAnalysis, consume_evidence


def profile_payload(level="L3"):
    payload = analysis_payload()
    payload["schema_version"] = "evidence-consumption-input/v2"
    evidence = payload["repositories"][0]["technologies"][0]
    kinds = ["DIRECT_DEPENDENCY", "PARTICIPATION"]
    if level in {"L2", "L3"}:
        kinds.append("IMPLEMENTATION")
    evidence.update(
        evidence_level=level,
        direct_dependency=True,
        implementation_present=level in {"L2", "L3"},
        implemented_by="SELF"
        if level == "L3"
        else "OTHER"
        if level == "L2"
        else "NONE",
        proofs=[proof_payload(kind) for kind in kinds],
    )
    if level == "L2":
        evidence["proofs"][-1]["attribution"] = "OTHER"
    evidence["fact_ids"] = [proof["fact_id"] for proof in evidence["proofs"]]
    return payload


def consume_profile(payload):
    return consume_evidence(
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
        tech_ids=("java", "docker"),
    )


@pytest.mark.parametrize("level", ["L1", "L2", "L3"])
def test_eligible_observed_policy_matches_each_valid_level(level):
    result = consume_profile(profile_payload(level))
    assert result.held_policy_version == "c-confirmed/eligible-observation/v1"
    assert result.held_tech_ids == ("java",)
    profile = result.by_tech_id["java"].profiles[0]
    assert profile.verified_level == level
    assert profile.direct_dependency_status == "CONFIRMED"
    assert profile.participation_status == "CONFIRMED"
    assert profile.self_implementation_status == (
        "CONFIRMED" if level == "L3" else "UNKNOWN"
    )


def test_legacy_positive_without_structured_proof_is_unknown_not_missing():
    result = consume_profile(analysis_payload())
    assert result.by_tech_id["java"].status == "UNKNOWN"
    assert "STRUCTURED_PROOF_REQUIRED" in result.by_tech_id["java"].data_gaps


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", "other-user"),
        ("analysis_id", "other-analysis"),
        ("repository_id", "other-repo"),
        ("repository_analysis_id", "other-repo-analysis"),
        ("source_commit_sha", "c" * 40),
        ("tech_id", "docker"),
        ("rule_version", "unsupported-rule-version"),
    ],
)
def test_wrong_proof_scope_never_supports_a_positive(field, value):
    payload = profile_payload("L1")
    payload["repositories"][0]["technologies"][0]["proofs"][0][field] = value
    result = consume_profile(payload).by_tech_id["java"]
    assert result.status == "UNKNOWN"
    assert all(
        proof.source_commit_sha == "a" * 40 for proof in result.supporting_proofs
    )
    assert result.data_gaps


@pytest.mark.parametrize(
    "field,value",
    [
        ("acceptance", "EXCLUDED"),
        ("acceptance", "UNCONFIRMED"),
        ("source_kind", "README"),
        ("source_kind", "LOCKFILE"),
        ("origin", "GENERATED"),
        ("origin", "VENDOR"),
        ("origin", "COPIED"),
        ("origin", "FORK_BASE"),
        ("inherited", True),
        ("direct_dependency", False),
    ],
)
def test_excluded_or_non_direct_observation_does_not_become_confirmed(field, value):
    payload = profile_payload("L1")
    payload["repositories"][0]["technologies"][0]["proofs"][0][field] = value
    assert consume_profile(payload).by_tech_id["java"].status == "UNKNOWN"


def test_l1_parse_failure_preserves_dependency_without_inventing_implementation():
    payload = profile_payload("L1")
    payload["status"] = "PARTIAL"
    repo = payload["repositories"][0]
    repo.update(status="PARTIAL", coverage_complete=False, data_gaps=["PARSE_FAILED"])
    repo["technologies"][0]["implementation_present"] = None
    result = consume_profile(payload).by_tech_id["java"]
    assert result.status == "HELD"
    assert result.profiles[0].implementation_status == "UNKNOWN"


def test_accepted_self_proof_survives_unrelated_partial_attribution():
    payload = profile_payload()
    evidence = payload["repositories"][0]["technologies"][0]
    evidence["attribution_status"] = "PARTIAL"
    other = proof_payload("IMPLEMENTATION", suffix="uncertain")
    other.update(attribution="UNKNOWN", attribution_commit_sha=None)
    evidence["proofs"].append(other)
    evidence["fact_ids"].append(other["fact_id"])
    result = consume_profile(payload).by_tech_id["java"]
    assert result.status == "HELD"
    assert result.profiles[0].verified_level == "L3"
    assert result.profiles[0].self_implementation_status == "CONFIRMED"


@pytest.mark.parametrize(
    "level,dependency", [("L2", False), ("L3", False), ("L2", None), ("L3", None)]
)
def test_v2_reported_positive_requires_confirmed_dependency(level, dependency):
    payload = profile_payload(level)
    payload["repositories"][0]["technologies"][0]["direct_dependency"] = dependency
    result = consume_profile(payload).by_tech_id["java"]
    assert result.status == ("UNKNOWN" if dependency is False else "HELD")
    assert result.profiles[0].verified_level is None


def test_v2_l0_dependency_priority_does_not_erase_implementation_observation():
    payload = profile_payload()
    evidence = payload["repositories"][0]["technologies"][0]
    evidence.update(evidence_level="L0", direct_dependency=False)
    evidence["proofs"] = evidence["proofs"][1:]
    evidence["fact_ids"] = [proof["fact_id"] for proof in evidence["proofs"]]
    result = consume_profile(payload).by_tech_id["java"]
    assert result.profiles[0].verified_level == "L0"
    assert result.profiles[0].implementation_status == "CONFIRMED"
    assert result.profiles[0].self_implementation_status == "CONFIRMED"
    assert result.status == "HELD"


def test_same_repo_conflicting_technology_assessments_rejected_despite_distinct_facts():
    payload = profile_payload()
    other = deepcopy(payload["repositories"][0]["technologies"][0])
    other.update(fact_ids=["different-fact"], evidence_level="L0", proofs=[])
    payload["repositories"][0]["technologies"].append(other)
    with pytest.raises(ValueError, match="conflicting.*technology"):
        consume_profile(payload)


def test_positive_proof_cannot_be_assembled_across_repositories():
    payload = profile_payload("L1")
    repo = payload["repositories"][0]
    other = deepcopy(repo)
    other.update(repository_id="repo-2", repository_analysis_id="analysis-2")
    repo["technologies"][0]["proofs"] = repo["technologies"][0]["proofs"][:1]
    other["technologies"][0]["proofs"] = other["technologies"][0]["proofs"][1:]
    for proof in other["technologies"][0]["proofs"]:
        proof.update(repository_id="repo-2", repository_analysis_id="analysis-2")
    payload["repositories"].append(other)
    assert consume_profile(payload).held_tech_ids == ()


def test_profile_roundtrip_retains_decisive_flags_and_rejects_modified_support():
    from recommendation.evidence import HeldTechnologySelection

    result = consume_profile(profile_payload())
    restored = HeldTechnologySelection.model_validate_json(result.model_dump_json())
    profile = restored.by_tech_id["java"].profiles[0]
    assert profile.reported.direct_dependency is True
    assert profile.reported.implementation_present is True
    assert profile.reported.user_participation is True
    assert profile.reported.implemented_by == "SELF"
    assert profile.reported.attribution_status == "COMPLETE"
    assert profile.proof_results[0].proof.attribution_commit_sha is None
    assert any(
        proof.attribution_commit_sha == "b" * 40 for proof in profile.supporting_proofs
    )
    payload = result.model_dump(mode="json")
    java = next(item for item in payload["technologies"] if item["tech_id"] == "java")
    java["supporting_proofs"][0]["source_ref"] = "b-evidence://invented"
    with pytest.raises(ValueError, match="supporting proof"):
        HeldTechnologySelection.model_validate(payload)
    payload = result.model_dump(mode="json")
    java = next(item for item in payload["technologies"] if item["tech_id"] == "java")
    java["profiles"][0]["reported"]["implemented_by"] = "OTHER"
    with pytest.raises(ValueError, match="validated B proof"):
        HeldTechnologySelection.model_validate(payload)


def test_access_only_repository_cannot_create_a_personal_negative():
    payload = profile_payload("L1")
    evidence = payload["repositories"][0]["technologies"][0]
    evidence["user_participation"] = False
    evidence["proofs"] = [
        proof for proof in evidence["proofs"] if proof["kind"] != "PARTICIPATION"
    ]
    result = consume_profile(payload)
    assert result.eligible_repository_ids == ()
    assert result.by_tech_id["java"].status == "UNKNOWN"
    assert result.by_tech_id["docker"].status == "UNKNOWN"


def test_self_implementation_also_proves_repository_participation_without_duplicate_fact():
    payload = profile_payload()
    evidence = payload["repositories"][0]["technologies"][0]
    evidence["proofs"] = [
        proof for proof in evidence["proofs"] if proof["kind"] != "PARTICIPATION"
    ]
    result = consume_profile(payload).by_tech_id["java"]
    assert result.status == "HELD"
    assert result.profiles[0].verified_level == "L3"
    assert result.profiles[0].eligibility_proofs[0].kind == "IMPLEMENTATION"


def test_other_technology_in_same_repository_proves_project_eligibility():
    payload = profile_payload("L1")
    evidence = payload["repositories"][0]["technologies"][0]
    evidence["proofs"] = [
        proof for proof in evidence["proofs"] if proof["kind"] != "PARTICIPATION"
    ]
    other = deepcopy(profile_payload()["repositories"][0]["technologies"][0])
    other["tech_id"] = "python"
    for proof in other["proofs"]:
        proof.update(tech_id="python", evidence_id="python-" + proof["evidence_id"])
    payload["repositories"][0]["technologies"].append(other)
    result = consume_profile(payload)
    assert result.by_tech_id["java"].status == "HELD"
    assert all(
        proof.tech_id == "python"
        for proof in result.by_tech_id["java"].profiles[0].eligibility_proofs
    )


def test_incorrect_reported_level_does_not_erase_independent_valid_source_observation():
    payload = profile_payload()
    evidence = payload["repositories"][0]["technologies"][0]
    evidence["direct_dependency"] = False
    evidence["proofs"] = [
        proof for proof in evidence["proofs"] if proof["kind"] != "DIRECT_DEPENDENCY"
    ]
    result = consume_profile(payload).by_tech_id["java"]
    assert result.status == "HELD"
    assert result.profiles[0].verified_level is None
    assert result.profiles[0].validation_status == "INCONSISTENT"
    assert result.profiles[0].observation_validation_status == "VALID"
    assert "ELIGIBLE_IMPLEMENTATION_SOURCE" in result.reason_codes


def test_proof_order_duplication_and_same_ids_in_different_repositories_are_scoped():
    payload = profile_payload()
    repo = payload["repositories"][0]
    other = deepcopy(repo)
    other.update(repository_id="repo-2", repository_analysis_id="analysis-2")
    for proof in other["technologies"][0]["proofs"]:
        proof.update(repository_id="repo-2", repository_analysis_id="analysis-2")
    payload["repositories"].append(other)
    first = consume_profile(payload)
    payload["repositories"].reverse()
    for repository in payload["repositories"]:
        evidence = repository["technologies"][0]
        evidence["proofs"].reverse()
        evidence["proofs"].append(deepcopy(evidence["proofs"][0]))
    second = consume_profile(payload)
    assert first == second
    assert len(second.by_tech_id["java"].profiles) == 2
    assert all(
        profile.verified_level == "L3" for profile in second.by_tech_id["java"].profiles
    )


def test_conflicting_cross_technology_proof_id_is_rejected():
    payload = profile_payload()
    other = deepcopy(payload["repositories"][0]["technologies"][0])
    other["tech_id"] = "python"
    for proof in other["proofs"]:
        proof["tech_id"] = "python"  # intentionally reuse IDs for different facts
    payload["repositories"][0]["technologies"].append(other)
    with pytest.raises(ValueError, match="conflicting proof ID"):
        consume_profile(payload)


def test_excluded_or_conflicting_peer_cannot_supply_repository_eligibility():
    payload = profile_payload("L1")
    repo = payload["repositories"][0]
    repo["technologies"][0]["proofs"] = [
        proof
        for proof in repo["technologies"][0]["proofs"]
        if proof["kind"] == "DIRECT_DEPENDENCY"
    ]
    other = deepcopy(profile_payload()["repositories"][0]["technologies"][0])
    other.update(tech_id="python", user_participation=False)
    for proof in other["proofs"]:
        proof.update(tech_id="python", evidence_id="python-" + proof["evidence_id"])
    repo["technologies"].append(other)
    assert consume_profile(payload).by_tech_id["java"].status == "UNKNOWN"


@pytest.mark.parametrize(
    "implementation,expected", [(None, "UNKNOWN"), (False, "NOT_HELD")]
)
def test_scoped_negative_requires_both_observation_dimensions_confirmed_absent(
    implementation, expected
):
    payload = profile_payload("L1")
    evidence = payload["repositories"][0]["technologies"][0]
    evidence.update(
        evidence_level="L0",
        direct_dependency=False,
        implementation_present=implementation,
        implemented_by="NONE",
    )
    evidence["proofs"] = [
        proof for proof in evidence["proofs"] if proof["kind"] == "PARTICIPATION"
    ]
    result = consume_profile(payload).by_tech_id["java"]
    assert result.profiles[0].verified_level == "L0"
    assert result.status == expected


def test_persisted_profile_cannot_promote_unknown_absence_or_invent_self_reason():
    from recommendation.evidence import HeldTechnologySelection

    payload = profile_payload("L1")
    evidence = payload["repositories"][0]["technologies"][0]
    evidence.update(
        evidence_level="L0", direct_dependency=False, implementation_present=None
    )
    evidence["proofs"] = [
        proof for proof in evidence["proofs"] if proof["kind"] == "PARTICIPATION"
    ]
    saved = consume_profile(payload).model_dump(mode="json")
    java = next(item for item in saved["technologies"] if item["tech_id"] == "java")
    java["status"] = "NOT_HELD"
    with pytest.raises(ValueError, match="confirmed observation absence"):
        HeldTechnologySelection.model_validate(saved)
    saved = consume_profile(profile_payload("L1")).model_dump(mode="json")
    java = next(item for item in saved["technologies"] if item["tech_id"] == "java")
    java["reason_codes"].append("SELF_IMPLEMENTATION")
    with pytest.raises(ValueError, match="explanation reasons"):
        HeldTechnologySelection.model_validate(saved)
