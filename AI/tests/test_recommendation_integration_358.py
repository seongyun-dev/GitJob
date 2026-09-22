"""S15P21E102-358 RED integration contracts for 354 + 355.

These tests deliberately describe the Phase-B boundary without changing the
recommendation engine.  They are expected to fail on develop, and to become
green only after the 355 trend tie-break is wired into the 354 engine and the
trend basis is persisted in the immutable snapshot.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

TREND_RULE_TOKEN = "top3-near-tie-weekly-active-repo-v1"
TREND_SOURCE = "GITHUB_GH_ARCHIVE"
TREND_GRANULARITY = "WEEK"
TREND_METRIC = "active_repo_count"


@dataclass(frozen=True)
class TrendFixtureStore:
    period: str
    values: dict[str, int]

    def get_trend_periods(self, *, source: str, granularity: str) -> list[str]:
        assert source == TREND_SOURCE
        assert granularity == TREND_GRANULARITY
        return [self.period]

    def get_trend_values(
        self,
        *,
        source: str,
        granularity: str,
        period: str,
        tech_ids: tuple[str, ...],
    ) -> dict[str, int]:
        assert source == TREND_SOURCE
        assert granularity == TREND_GRANULARITY
        assert period == self.period
        return {tech_id: self.values[tech_id] for tech_id in tech_ids}


TREND_A = TrendFixtureStore(
    period="TREND_PERIOD_A",
    values={"docker": 100, "redis": 300, "aws": 150},
)
TREND_B = TrendFixtureStore(
    period="TREND_PERIOD_B",
    values={"docker": 100, "redis": 300, "aws": 150},
)


def _phase_b_modules():
    """Return Phase-B modules or fail explicitly instead of erroring at collect."""
    try:
        from recommendation import engine
        from recommendation.trend_tiebreak import resolve_trend_basis
    except ImportError as exc:  # develop intentionally lacks Phase-B wiring
        pytest.fail(f"Phase-B recommendation contract is not present: {exc}")
    return engine, resolve_trend_basis


def _build_fixture_snapshot(*, trend_store: TrendFixtureStore):
    """Build the shared user/candidate fixture through public contracts."""
    try:
        from evidence_fixtures import proof_payload
        from test_evidence_consumption import legacy_analysis_payload
        from test_job_cohort import batch, criteria, posting

        from job.cohort import build_cohort
        from job.contracts import JobPostingInput
        from recommendation.evidence import EvidenceAnalysis
        from registry.contracts import load_registry
        from registry.mapper import RegistryMapper
    except ImportError as exc:  # develop intentionally lacks the 354 fixture
        pytest.fail(f"S15P21E102-354 fixture is not present: {exc}")

    def held_technology(tech_id: str, personal_level: str | None = None) -> dict:
        proofs = [
            proof_payload(kind, tech_id=tech_id, suffix=f"358-{tech_id}")
            for kind in ("DIRECT_DEPENDENCY", "PARTICIPATION", "IMPLEMENTATION")
        ]
        item = {
            "tech_id": tech_id,
            "fact_ids": [proof["fact_id"] for proof in proofs],
            "evidence_level": "L2",
            "direct_dependency": True,
            "implementation_present": True,
            "user_participation": True,
            "implemented_by": "SELF",
            "attribution_status": "COMPLETE",
            "source_refs": [f"https://github.com/example/repo/blob/358/{tech_id}"],
            "proofs": proofs,
        }
        if personal_level is not None:
            item["personal_level"] = personal_level
        return item

    typed_records = []
    for tech_id, count in (
        ("docker", 31),
        ("redis", 30),
        ("aws", 20),
        ("gcp", 19),
    ):
        for index in range(count):
            payload = posting(
                f"{tech_id}-{index}", required=(tech_id.upper(),)
            ).model_dump(mode="json")
            for mention in payload["technology_mentions"]:
                mention["technology_id"] = tech_id
            typed_records.append(JobPostingInput.model_validate(payload))
    ai_root = Path(__file__).resolve().parents[1]
    mapper = RegistryMapper(
        load_registry(
            ai_root / "registry/data/technology_registry_20260911_3.json",
            repository_root=ai_root.parent,
        )
    )
    cohort = build_cohort(batch(*typed_records), criteria(), mapper=mapper)
    payload = legacy_analysis_payload()
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["registry_version"] = cohort.registry_version
    payload["repositories"][0]["technologies"] = [
        held_technology("python", "L2"),
        held_technology("django", "L1"),
        held_technology("aws", "L0"),
    ]
    payload["repositories"][0]["evaluated_tech_ids"] = [
        "python",
        "django",
        "docker",
        "redis",
        "aws",
        "gcp",
    ]
    payload["repositories"][0]["coverage_complete"] = False
    analysis = EvidenceAnalysis.model_validate(payload)
    engine, _ = _phase_b_modules()
    parameters: dict[str, Any] = {
        "user_id": "user-1",
        "analysis_id": "analysis-1",
    }
    signature = inspect.signature(engine.build_recommendations)
    if "trend_lookup" in signature.parameters:
        basis_type = engine.TrendTieBreakBasis

        def trend_lookup(tech_ids: tuple[str, ...]):
            return basis_type(
                source=TREND_SOURCE,
                granularity=TREND_GRANULARITY,
                period=trend_store.period,
                metric=TREND_METRIC,
                values={tech_id: trend_store.values[tech_id] for tech_id in tech_ids},
            )

        parameters["trend_lookup"] = trend_lookup
    elif "trend_store" in signature.parameters:
        parameters["trend_store"] = trend_store
    elif "trend_basis" in signature.parameters:
        _, resolve_trend_basis = _phase_b_modules()
        basis = resolve_trend_basis(trend_store, ("docker", "redis", "aws"))
        parameters["trend_basis"] = basis
    else:
        pytest.fail(
            "build_recommendations has no Phase-B trend_store/trend_basis input"
        )
    return engine.build_recommendations(cohort, analysis, **parameters)


def _build_level_compatibility_snapshot(
    *,
    personal_level: str | None,
    required_text: str,
    evidence_mode: str = "PERSONAL",
):
    """Build one level-aware recommendation without changing production code.

    ``required_text`` is intentionally passed through the real requirement
    parser so these regressions exercise the same L1/L2/L3 contract as the
    service.  ``evidence_mode`` distinguishes an UNKNOWN technology from a
    repository observation that simply has no personal level.
    """
    try:
        from evidence_fixtures import proof_payload
        from test_evidence_consumption import legacy_analysis_payload
        from test_job_cohort import batch, criteria, posting

        from job.cohort import build_cohort
        from job.contracts import JobPostingInput
        from recommendation.evidence import EvidenceAnalysis
        from registry.contracts import load_registry
        from registry.mapper import RegistryMapper
    except ImportError as exc:  # develop intentionally lacks the 354 fixture
        pytest.fail(f"S15P21E102-354 fixture is not present: {exc}")

    def held_technology(tech_id: str, level: str | None = None) -> dict:
        proofs = [
            proof_payload(kind, tech_id=tech_id, suffix=f"358-compat-{tech_id}")
            for kind in ("DIRECT_DEPENDENCY", "PARTICIPATION", "IMPLEMENTATION")
        ]
        item = {
            "tech_id": tech_id,
            "fact_ids": [proof["fact_id"] for proof in proofs],
            "evidence_level": "L2",
            "direct_dependency": True,
            "implementation_present": True,
            "user_participation": True,
            "implemented_by": "SELF",
            "attribution_status": "COMPLETE",
            "source_refs": [f"https://github.com/example/repo/blob/358/{tech_id}"],
            "proofs": proofs,
        }
        if level is not None:
            item["personal_level"] = level
        return item

    record = posting(
        "docker-compat",
        required=("Docker",),
        required_text=required_text,
    ).model_dump(mode="json")
    for mention in record["technology_mentions"]:
        mention["technology_id"] = "docker"
    typed_record = JobPostingInput.model_validate(record)
    ai_root = Path(__file__).resolve().parents[1]
    mapper = RegistryMapper(
        load_registry(
            ai_root / "registry/data/technology_registry_20260911_3.json",
            repository_root=ai_root.parent,
        )
    )
    cohort = build_cohort(batch(typed_record), criteria(), mapper=mapper)

    payload = legacy_analysis_payload()
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["registry_version"] = cohort.registry_version
    repository = payload["repositories"][0]
    if evidence_mode == "UNKNOWN":
        repository["technologies"] = [held_technology("python", "L2")]
        evaluated_tech_ids = ["python"]
    elif evidence_mode == "NO_PERSONAL":
        repository["technologies"] = [held_technology("docker")]
        evaluated_tech_ids = ["docker", "python"]
    else:
        repository["technologies"] = [held_technology("docker", personal_level)]
        evaluated_tech_ids = ["docker", "python"]
    repository["evaluated_tech_ids"] = evaluated_tech_ids
    repository["coverage_complete"] = True
    analysis = EvidenceAnalysis.model_validate(payload)

    engine, _ = _phase_b_modules()
    parameters: dict[str, Any] = {
        "user_id": "user-1",
        "analysis_id": "analysis-1",
    }
    signature = inspect.signature(engine.build_recommendations)
    if "trend_lookup" in signature.parameters:
        basis_type = engine.TrendTieBreakBasis
        parameters["trend_lookup"] = lambda tech_ids: basis_type(
            source=TREND_SOURCE,
            granularity=TREND_GRANULARITY,
            period="TREND_COMPATIBILITY",
            metric=TREND_METRIC,
            values={tech_id: 1 for tech_id in tech_ids},
        )
    elif "trend_store" in signature.parameters:
        parameters["trend_store"] = TREND_A
    elif "trend_basis" in signature.parameters:
        _, resolve_trend_basis = _phase_b_modules()
        parameters["trend_basis"] = resolve_trend_basis(TREND_A, ("docker",))
    else:
        pytest.fail(
            "build_recommendations has no Phase-B trend_store/trend_basis input"
        )
    return engine.build_recommendations(cohort, analysis, **parameters)


def test_engine_applies_trend_only_inside_the_already_selected_top3():
    """31/30/20 selects Docker/Redis/AWS; Trend reorders only Docker/Redis."""
    snapshot = _build_fixture_snapshot(trend_store=TREND_A)

    assert [candidate.tech_id for candidate in snapshot.candidates] == [
        "redis",
        "docker",
        "aws",
    ]
    assert "gcp" not in {candidate.tech_id for candidate in snapshot.candidates}
    assert snapshot.gap.unknown_tech_ids == ("docker", "gcp", "redis")
    assert snapshot.status == "PARTIAL"
    assert {
        candidate.tech_id: candidate.impact.affected_count
        for candidate in snapshot.candidates
    } == {"docker": 31, "redis": 30, "aws": 20}


def test_recommendation_snapshot_persists_complete_trend_basis():
    snapshot = _build_fixture_snapshot(trend_store=TREND_A)
    basis = snapshot.trend_tiebreak

    assert basis.source == TREND_SOURCE
    assert basis.granularity == TREND_GRANULARITY
    assert basis.period == "TREND_PERIOD_A"
    assert basis.metric == TREND_METRIC
    assert basis.values == TREND_A.values


def test_same_order_with_different_trend_periods_has_distinct_immutable_identity():
    first = _build_fixture_snapshot(trend_store=TREND_A)
    second = _build_fixture_snapshot(trend_store=TREND_B)

    assert [candidate.tech_id for candidate in first.candidates] == [
        candidate.tech_id for candidate in second.candidates
    ]
    assert first.snapshot_id != second.snapshot_id


def test_trend_rule_is_accepted_by_snapshot_validation_and_is_versioned():
    snapshot = _build_fixture_snapshot(trend_store=TREND_A)

    assert TREND_RULE_TOKEN in snapshot.tie_break_rule
    restored = type(snapshot).model_validate_json(snapshot.model_dump_json())
    assert restored.snapshot_id == snapshot.snapshot_id


def test_personal_l2_meeting_required_l2_keeps_existing_satisfied_judgement():
    snapshot = _build_level_compatibility_snapshot(
        personal_level="L2",
        required_text="Docker 개발 경험",
    )

    assert "docker" not in {candidate.tech_id for candidate in snapshot.candidates}


def test_personal_l0_remains_a_candidate():
    snapshot = _build_level_compatibility_snapshot(
        personal_level="L0",
        required_text="Docker 개발 경험",
    )

    assert "docker" in {candidate.tech_id for candidate in snapshot.candidates}


def test_unknown_evidence_can_be_a_candidate_without_changing_unknown_gap():
    snapshot = _build_level_compatibility_snapshot(
        personal_level=None,
        required_text="Docker 개발 경험",
        evidence_mode="UNKNOWN",
    )

    assert "docker" in {candidate.tech_id for candidate in snapshot.candidates}
    assert "docker" in snapshot.gap.unknown_tech_ids


def test_no_personal_level_keeps_repository_candidate_eligibility():
    snapshot = _build_level_compatibility_snapshot(
        personal_level=None,
        required_text="Docker 개발 경험",
        evidence_mode="NO_PERSONAL",
    )

    assert "docker" in {candidate.tech_id for candidate in snapshot.candidates}


def test_condition_impact_counts_match_stored_job_ids():
    snapshot = _build_fixture_snapshot(trend_store=TREND_A)

    for candidate in snapshot.candidates:
        assert candidate.impact.affected_count == len(
            set(candidate.impact.affected_job_ids)
        )
