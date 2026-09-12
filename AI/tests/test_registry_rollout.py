"""Rollout gates: preserve old results, prepare new heads, never mix Registries."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_compute_api import PREFIX, REGISTRY, TOKEN, event, job_request, snapshot_ref
from test_job_cohort import criteria
from test_recommendation_engine import make_analysis

from job import requirements
from worker import api
from worker.jobs import job_stream
from worker.store import ComputeStore, apply_migration


@pytest.fixture
def rollout_store():
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires an explicitly selected isolated PostgreSQL database")
    apply_migration(dsn)
    return ComputeStore(dsn)


def test_job_batch_versions_bind_the_required_level_policy(monkeypatch):
    current = api.compute_versions("JOB_BATCH", REGISTRY)
    assert current["required_level_policy"] == (
        requirements.JOB_REQUIRED_LEVEL_POLICY_VERSION
    )

    with monkeypatch.context() as previous:
        previous.setattr(
            requirements,
            "JOB_REQUIRED_LEVEL_POLICY_VERSION",
            "job-required-level-policy/v1",
        )
        legacy = api.compute_versions("JOB_BATCH", REGISTRY)

    assert legacy["required_level_policy"] == "job-required-level-policy/v1"
    assert job_stream(criteria(), legacy) != job_stream(criteria(), current)
    pre_policy_versions = dict(current)
    pre_policy_versions.pop("required_level_policy")
    assert job_stream(criteria(), pre_policy_versions) != job_stream(
        criteria(), current
    )


@pytest.mark.parametrize("previous_field", ["review_queue", "required_level_policy"])
def test_new_calculation_version_requires_precompute_but_keeps_old_results(
    monkeypatch, rollout_store, previous_field
):
    current_versions = api.compute_versions
    # Isolate the stream from other tests without changing its product meaning.
    selected = REGISTRY.model_copy(
        update={
            "registry_version": f"registry-20260910.{int(uuid4().hex[:12], 16) + 1}"
        }
    )
    request = job_request()
    headers = {"Authorization": f"Bearer {TOKEN}"}

    def previous_versions(kind, registry):
        versions = current_versions(kind, registry)
        if kind == "JOB_BATCH":
            if previous_field == "required_level_policy":
                # Actual pre-fix calculation identity omitted this key entirely.
                versions.pop("required_level_policy")
            else:
                versions["review_queue"] = "pre-rollout-review/" + previous_tag
        return versions

    previous_tag = uuid4().hex
    with monkeypatch.context() as before:
        before.setattr(api, "compute_versions", previous_versions)
        with TestClient(
            api.create_compute_app(store=rollout_store, token=TOKEN, registry=selected),
            headers=headers,
        ) as client:
            old_ref = snapshot_ref(
                client.post(PREFIX + "/job-batches/completed", json=request), "COHORT"
            )
            old_payload = client.get(PREFIX + f"/snapshots/{old_ref}").json()

    with TestClient(
        api.create_compute_app(store=rollout_store, token=TOKEN, registry=selected),
        headers=headers,
    ) as client:
        resolved = client.post(
            PREFIX + "/job-cohorts/resolve", json=criteria().model_dump(mode="json")
        )
        assert resolved.status_code == 404
        assert resolved.json()["code"] == "COHORT_NOT_PREPARED"
        assert client.get(PREFIX + f"/snapshots/{old_ref}").json() == old_payload
        prepared = client.post(
            PREFIX + "/job-batches/completed",
            json={**request, "event_id": str(uuid4()), "trace_id": str(uuid4())},
        )
        new_ref = snapshot_ref(prepared, "COHORT")
        assert (
            client.post(
                PREFIX + "/job-cohorts/resolve", json=criteria().model_dump(mode="json")
            ).json()["data"]["cohort_snapshot_id"]
            == new_ref
        )


def test_registry_rollout_keeps_saved_results_but_rejects_mixed_recalculation(
    rollout_store,
):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(
        api.create_compute_app(store=rollout_store, token=TOKEN, registry=REGISTRY),
        headers=headers,
    ) as client:
        cohort_ref = snapshot_ref(
            client.post(PREFIX + "/job-batches/completed", json=job_request()), "COHORT"
        )
        payload = client.get(PREFIX + f"/snapshots/{cohort_ref}").json()

    next_registry = REGISTRY.model_copy(
        update={"registry_version": "registry-20260910.82"}
    )
    with TestClient(
        api.create_compute_app(
            store=rollout_store, token=TOKEN, registry=next_registry
        ),
        headers=headers,
    ) as client:
        assert client.get(PREFIX + f"/snapshots/{cohort_ref}").json() == payload
        rejected = client.post(
            PREFIX + "/analyses/completed",
            json=event(
                user_id="user-1",
                analysis_id="analysis-1",
                cohort_snapshot_id=cohort_ref,
                evidence=make_analysis().model_dump(mode="json"),
            ),
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "INVALID_INPUT"
