"""Synthetic policy-comparison cases, not a real-user proficiency benchmark.

The historical column records the reviewed pre-proof v1 policy outcome, not an
enabled alternate execution policy. Tests exercise the current confirmed gate.
"""

import pytest
from test_evidence_consumption import legacy_analysis_payload
from test_evidence_profiles import consume_profile, profile_payload

CALIBRATION = (
    ("eligible_l1", "NOT_HELD", "HELD"),
    ("project_other_l2", "HELD", "HELD"),
    ("self_l3", "HELD", "HELD"),
    ("partial_attribution_self", "UNKNOWN", "HELD"),
    ("l1_parse_failed", "UNKNOWN", "HELD"),
    ("legacy_no_proof", "HELD", "UNKNOWN"),
    ("language_no_sbom_l0", "UNKNOWN", "HELD"),
    ("level_mismatch_valid_source", "HELD", "HELD"),
    ("observation_flag_conflict", "HELD", "UNKNOWN"),
    ("access_only", "NOT_HELD", "UNKNOWN"),
    ("inherited_dependency", "NOT_HELD", "UNKNOWN"),
    ("failed_repository", "UNKNOWN", "UNKNOWN"),
    ("unsupported_repository", "UNKNOWN", "UNKNOWN"),
    ("partial_absence", "UNKNOWN", "UNKNOWN"),
    ("complete_eligible_absence", "NOT_HELD", "NOT_HELD"),
    ("unconfirmed_proofs", "HELD", "UNKNOWN"),
    ("bad_source_valid_dependency", "HELD", "HELD"),
    ("infra_other_source_no_sbom", "UNKNOWN", "HELD"),
)


@pytest.mark.parametrize(
    "case,historical,current", CALIBRATION, ids=[row[0] for row in CALIBRATION]
)
def test_confirmed_technology_policy_calibration(case, historical, current):
    level = (
        "L1"
        if case
        in {"eligible_l1", "l1_parse_failed", "access_only", "inherited_dependency"}
        else "L2"
        if case in {"project_other_l2", "infra_other_source_no_sbom"}
        else "L3"
    )
    payload = profile_payload(level)
    repo = payload["repositories"][0]
    evidence = repo["technologies"][0]
    tech_id = "java"
    if case == "partial_attribution_self":
        evidence["attribution_status"] = "PARTIAL"
    elif case in {"l1_parse_failed", "partial_absence"}:
        payload["status"] = "PARTIAL"
        repo.update(status="PARTIAL", coverage_complete=False)
        evidence["implementation_present"] = None
        if case == "partial_absence":
            tech_id = "docker"
    elif case == "legacy_no_proof":
        payload = legacy_analysis_payload()
    elif case in {
        "language_no_sbom_l0",
        "level_mismatch_valid_source",
        "infra_other_source_no_sbom",
    }:
        evidence["direct_dependency"] = False
        if case != "level_mismatch_valid_source":
            evidence["evidence_level"] = "L0"
        evidence["proofs"] = [
            proof
            for proof in evidence["proofs"]
            if proof["kind"] != "DIRECT_DEPENDENCY"
        ]
    elif case == "observation_flag_conflict":
        evidence["direct_dependency"] = False  # conflicts with accepted direct proof
    elif case == "access_only":
        evidence["user_participation"] = False
        evidence["proofs"] = [
            proof for proof in evidence["proofs"] if proof["kind"] != "PARTICIPATION"
        ]
    elif case == "inherited_dependency":
        evidence["proofs"][0]["inherited"] = True
    elif case in {"failed_repository", "unsupported_repository"}:
        repo.update(
            status="FAILED" if case == "failed_repository" else "UNSUPPORTED",
            coverage_complete=False,
        )
    elif case == "complete_eligible_absence":
        tech_id = "docker"
    elif case == "unconfirmed_proofs":
        for proof in evidence["proofs"]:
            proof["acceptance"] = "UNCONFIRMED"
    elif case == "bad_source_valid_dependency":
        for proof in evidence["proofs"]:
            if proof["kind"] == "IMPLEMENTATION":
                proof["source_commit_sha"] = "f" * 40
    result = consume_profile(payload).by_tech_id[tech_id]
    assert result.status == current
    assert historical in {"HELD", "NOT_HELD", "UNKNOWN"}
    if current == "HELD":
        assert result.supporting_proofs
        assert any(
            profile.participation_status == "CONFIRMED" for profile in result.profiles
        )
    elif current == "UNKNOWN":
        assert result.data_gaps
    if case in {"language_no_sbom_l0", "infra_other_source_no_sbom"}:
        assert result.profiles[0].verified_level == "L0"
        assert result.profiles[0].implementation_status == "CONFIRMED"
    if case == "level_mismatch_valid_source":
        assert result.profiles[0].validation_status == "INCONSISTENT"
        assert result.profiles[0].observation_validation_status == "VALID"
