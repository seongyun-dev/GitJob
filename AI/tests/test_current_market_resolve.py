"""CURRENT_MARKET has to be expressible on the resolve and intake contracts.

`S15P21E102-332` gave `CohortCriteria` a market purpose, but nothing could ask
for it. B's selector carries no purpose and demands a role, and the intake never
passed one through, so every resolved cohort came back ACTIVE_MATCHING. The
aggregation was reachable only by writing a full `CohortCriteria` by hand, which
means choosing `as_of` -- and that choice belongs to C, not to the caller.

The role rules are the contract's, not a second copy of it: the selector builds
a `CohortCriteria` and lets it judge. A market that accepted a role would quietly
become a role cohort whose stored lineage disagreed with its own denominator.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_compute_api import PREFIX
from test_compute_resolve import (
    COHORT_ID,
    DEMAND_ID,
    IntakeRunner,
    ResolveStore,
    _client,
)
from test_job_cohort import criteria

from job.cohort import CohortPurpose
from worker.api import JobCohortResolveSelector
from worker.intake import IntakeRunner as WorkerIntakeRunner

CUTOFF = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
OFFICIAL_SOURCES = ("JOBKOREA", "SARAMIN")


def selector(**changes):
    return JobCohortResolveSelector.model_validate(
        {"schema_version": "job-cohort-resolve-selector/v1", **changes}
    )


def observation(source_site, occurred_at=CUTOFF):
    """Only the fields the criteria binding reads; the batch is never opened."""
    return SimpleNamespace(occurred_at=occurred_at, source_site=source_site)


def market_template(**changes):
    return criteria(purpose="CURRENT_MARKET", target_role=None, **changes)


def configured(*templates):
    """A runner holding only the configured scopes; prewarm reads nothing else."""
    runner = WorkerIntakeRunner.__new__(WorkerIntakeRunner)
    runner.config = SimpleNamespace(criteria=templates)
    return runner


def test_market_selector_resolves_without_a_target_role():
    selected = selector(purpose="CURRENT_MARKET").criteria_at(CUTOFF)

    assert selected.purpose is CohortPurpose.CURRENT_MARKET
    assert selected.target_role is None
    assert selected.as_of == CUTOFF


def test_market_selector_refuses_a_target_role():
    with pytest.raises(ValidationError, match="CURRENT_MARKET must not carry"):
        selector(purpose="CURRENT_MARKET", target_role="BACKEND")


def test_active_matching_selector_still_requires_a_target_role():
    with pytest.raises(ValidationError):
        selector()


def test_active_matching_selector_keeps_its_stored_byte_shape():
    """A default purpose must stay absent, or every stored cohort_id moves."""
    selected = selector(target_role="BACKEND").criteria_at(CUTOFF)

    assert selected.purpose is CohortPurpose.ACTIVE_MATCHING
    assert selected.target_role == "BACKEND"
    assert "purpose" not in selected.model_dump(mode="json")


def test_market_selector_carries_the_declared_source_scope():
    """The official population is named by the caller, never hardcoded here."""
    selected = selector(
        purpose="CURRENT_MARKET", sources=[" jobkorea ", "saramin"]
    ).criteria_at(CUTOFF)

    assert selected.sources == OFFICIAL_SOURCES


def test_market_selector_round_trips_through_json():
    original = selector(purpose="CURRENT_MARKET", sources=list(OFFICIAL_SOURCES))

    restored = JobCohortResolveSelector.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.criteria_at(CUTOFF).purpose is CohortPurpose.CURRENT_MARKET


def test_intake_binds_the_market_selector_to_the_verified_cutoff():
    outputs = (
        observation("JOBKOREA", datetime(2026, 9, 17, tzinfo=UTC)),
        observation("SARAMIN", CUTOFF),
    )

    bound = WorkerIntakeRunner._selector_criteria(
        outputs,
        target_role=None,
        purpose=CohortPurpose.CURRENT_MARKET,
        sources=OFFICIAL_SOURCES,
        regions=(),
        career_levels=(),
        min_jobs=1,
    )

    assert bound.purpose is CohortPurpose.CURRENT_MARKET
    assert bound.target_role is None
    assert bound.as_of == CUTOFF


def test_intake_prewarms_the_configured_market_scope():
    runner = configured(market_template(sources=OFFICIAL_SOURCES), criteria())
    outputs = (observation("JOBKOREA"), observation("SARAMIN"), observation("WORKNET"))

    prewarmed = runner._latest_selector_criteria(outputs)

    markets = [
        item for item in prewarmed if item.purpose is CohortPurpose.CURRENT_MARKET
    ]
    assert [item.sources for item in markets] == [OFFICIAL_SOURCES]
    assert markets[0].as_of == CUTOFF
    assert any(item.target_role == "BACKEND" for item in prewarmed)


def test_intake_does_not_prewarm_an_unofficial_all_source_market():
    """`()` would mean WORKNET/GAMEJOB/CAREER counted as the current market."""
    runner = configured(market_template(sources=OFFICIAL_SOURCES))

    prewarmed = runner._latest_selector_criteria((observation("JOBKOREA"),))

    assert [item.sources for item in prewarmed] == [OFFICIAL_SOURCES]


def test_market_resolve_returns_the_completed_pair(monkeypatch, tmp_path):
    receipt = {
        "status": "COMPLETED",
        "results": [
            {"kind": "COHORT", "snapshot_id": COHORT_ID},
            {"kind": "DEMAND", "snapshot_id": DEMAND_ID},
        ],
    }
    store = ResolveStore(pair=None)
    runner = IntakeRunner(
        receipt, selected_criteria=criteria(as_of="2026-09-18T03:00:00Z")
    )

    with _client(
        store, runner=runner, monkeypatch=monkeypatch, tmp_path=tmp_path
    ) as client:
        response = client.post(
            PREFIX + "/job-cohorts/resolve",
            json={
                "schema_version": "job-cohort-resolve-selector/v1",
                "purpose": "CURRENT_MARKET",
                "sources": list(OFFICIAL_SOURCES),
            },
        )

    assert response.status_code == 200, response.text
    resolved = response.json()["data"]["criteria"]
    assert resolved["purpose"] == "CURRENT_MARKET"
    assert "target_role" not in resolved
    assert resolved["sources"] == list(OFFICIAL_SOURCES)
    assert response.json()["data"]["demand_snapshot_id"] == DEMAND_ID
    assert store.pair_calls == []


def test_market_resolve_rejects_a_target_role_over_http(monkeypatch, tmp_path):
    store = ResolveStore(pair=None)
    runner = IntakeRunner({"status": "COMPLETED", "results": []})

    with _client(
        store, runner=runner, monkeypatch=monkeypatch, tmp_path=tmp_path
    ) as client:
        response = client.post(
            PREFIX + "/job-cohorts/resolve",
            json={
                "schema_version": "job-cohort-resolve-selector/v1",
                "purpose": "CURRENT_MARKET",
                "target_role": "BACKEND",
            },
        )

    assert response.status_code == 422, response.text
