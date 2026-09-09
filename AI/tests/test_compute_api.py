"""Real PostgreSQL plus HTTP boundary, without B/FE or source-network mocks."""

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_job_cohort import batch, criteria, posting
from test_recommendation_engine import make_analysis

from registry.contracts import load_registry
from worker.api import create_compute_app
from worker.store import ComputeStore, apply_migration

TOKEN = "local-c-compute-test-token-only-00000000"
PREFIX = "/internal/v1/c"
REGISTRY = load_registry(
    Path(__file__).resolve().parents[1] / "registry/data/technology_registry_v1.json",
    repository_root=Path(__file__).resolve().parents[2],
)


def event(**payload):
    return {
        "schema_version": "c-compute-event/v1",
        "event_id": str(uuid4()),
        "trace_id": str(uuid4()),
        "occurred_at": datetime.now(UTC).isoformat(),
        **payload,
    }


@pytest.fixture
def client():
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires an explicitly selected isolated PostgreSQL database")
    apply_migration(dsn)
    app = create_compute_app(store=ComputeStore(dsn), token=TOKEN, registry=REGISTRY)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as value:
        yield value


def job_request():
    payload = batch(
        posting("current"),
        posting("docker", required=("Java", "Docker")),
        posting("redis", required=("Java", "Redis")),
        posting("both", required=("Java", "Docker", "Redis")),
    ).model_dump(mode="json")
    return event(batch=payload, criteria=criteria().model_dump(mode="json"))


def snapshot_ref(response, kind):
    assert response.status_code == 200, response.text
    return next(
        ref["snapshot_id"]
        for ref in response.json()["data"]["results"]
        if ref["kind"] == kind
    )


def test_completed_batch_to_automatic_recommendation_database_and_exact_new_jobs(
    client,
):
    request = job_request()
    job_response = client.post(PREFIX + "/job-batches/completed", json=request)
    cohort_id = snapshot_ref(job_response, "COHORT")
    demand_id = snapshot_ref(job_response, "DEMAND")
    demand = client.get(PREFIX + f"/snapshots/{demand_id}").json()["data"]["payload"]
    assert demand["denominator"] == 4
    repeated = client.post(
        PREFIX + "/job-batches/completed", json={**request, "trace_id": str(uuid4())}
    )
    assert repeated.json() == job_response.json()

    analysis_request = event(
        user_id="user-1",
        analysis_id="analysis-1",
        cohort_snapshot_id=cohort_id,
        evidence=make_analysis().model_dump(mode="json"),
    )
    result_id = snapshot_ref(
        client.post(PREFIX + "/analyses/completed", json=analysis_request),
        "RECOMMENDATION",
    )
    result = client.get(
        PREFIX + f"/snapshots/{result_id}", params={"user_id": "user-1"}
    ).json()["data"]["payload"]
    assert "job_matching" not in result
    assert result["job_matching_ref"]["schema_version"] == "job-matching-storage/v2"
    assert result["current_count"] == 1
    assert result["explanation"]["snapshot_id"] == result["snapshot_id"]
    candidate = next(
        item for item in result["candidates"] if item["tech_id"] == "docker"
    )
    assert candidate["what_if"]["current_count"] == 1
    assert candidate["what_if"]["increased_count"] == 1
    assert candidate["what_if"]["projected_count"] == 2
    url = PREFIX + f"/recommendations/{result_id}/job-postings"
    listing = client.get(
        url,
        params={
            "user_id": "user-1",
            "mode": "WHAT_IF",
            "recommended_tech_id": "docker",
        },
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["data"]["snapshot_id"] == result_id
    assert listing.json()["data"]["total_count"] == 1
    assert [job["job_id"] for job in listing.json()["data"]["items"]] == ["docker"]
    assert (
        client.get(url, params={"user_id": "user-1", "mode": "WHAT_IF"}).status_code
        == 422
    )
    assert client.get(url, params={"user_id": "user-1", "size": 51}).status_code == 422
    assert (
        client.get(
            PREFIX + f"/snapshots/{result_id}", params={"user_id": "user-2"}
        ).status_code
        == 404
    )
    assert client.get(PREFIX + f"/snapshots/{result_id}").status_code == 404
    assert client.get(url, params={"user_id": "user-2"}).status_code == 404
    assert (
        snapshot_ref(
            client.post(PREFIX + "/analyses/completed", json=analysis_request),
            "RECOMMENDATION",
        )
        == result_id
    )


def test_changed_event_conflicts_and_wrong_evidence_owner_rejected(client):
    request = job_request()
    cohort_id = snapshot_ref(
        client.post(PREFIX + "/job-batches/completed", json=request), "COHORT"
    )
    request["criteria"]["target_role"] = "FRONTEND"
    response = client.post(PREFIX + "/job-batches/completed", json=request)
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_CONFLICT"
    request = event(
        user_id="user-2",
        analysis_id="analysis-1",
        cohort_snapshot_id=cohort_id,
        evidence=make_analysis().model_dump(mode="json"),
    )
    assert client.post(PREFIX + "/analyses/completed", json=request).status_code == 403


def test_registry_mismatch_does_not_silently_mix_versions(client):
    cohort_id = snapshot_ref(
        client.post(PREFIX + "/job-batches/completed", json=job_request()), "COHORT"
    )
    evidence = make_analysis().model_dump(mode="json")
    evidence["registry_version"] = "registry-20990101.1"
    request = event(
        user_id="user-1",
        analysis_id="analysis-1",
        cohort_snapshot_id=cohort_id,
        evidence=evidence,
    )
    assert client.post(PREFIX + "/analyses/completed", json=request).status_code == 422


def test_rule_upgrade_requires_a_new_event_instead_of_silently_changing_retry(
    client, monkeypatch
):
    request = job_request()
    old_id = snapshot_ref(
        client.post(PREFIX + "/job-batches/completed", json=request), "COHORT"
    )
    monkeypatch.setattr("worker.api.JOB_QUALITY_VERSION", "job-cohort-quality/future")
    result = client.post(PREFIX + "/job-batches/completed", json=request)
    assert result.status_code == 409
    assert result.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert client.get(PREFIX + f"/snapshots/{old_id}").status_code == 200


def test_github_trend_is_stored_without_inventing_missing_history(client):
    request = event(tech_id="java", source="GITHUB", periods=["2026-Q1"])
    result_id = snapshot_ref(
        client.post(PREFIX + "/trends/completed", json=request), "TREND"
    )
    result = client.get(PREFIX + f"/snapshots/{result_id}").json()["data"]["payload"]
    assert result["status"] == "PREPARING"
    assert all(point["value"] is None for point in result["points"])
    request = event(tech_id="kafka", source="GITHUB", periods=["2026-Q1"])
    result_id = snapshot_ref(
        client.post(PREFIX + "/trends/completed", json=request), "TREND"
    )
    result = client.get(PREFIX + f"/snapshots/{result_id}").json()["data"]["payload"]
    assert result["status"] == "NOT_SUPPORTED"


def test_runtime_is_fail_closed_and_liveness_is_not_readiness(monkeypatch):
    monkeypatch.delenv("C_COMPUTE_DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    app = create_compute_app(token="", registry=REGISTRY)
    with TestClient(app) as value:
        assert value.get("/health").json() == {"status": "alive", "service": "worker"}
        assert value.get("/ready").status_code == 503
        assert value.get(PREFIX + "/registry").status_code == 503
    app = create_compute_app(token=TOKEN, registry=REGISTRY)
    with TestClient(app) as value:
        assert value.get(PREFIX + "/registry").status_code == 401
        assert (
            value.get(
                PREFIX + "/registry", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        value.headers["Authorization"] = f"Bearer {TOKEN}"
        assert value.get(PREFIX + "/registry").status_code == 200
        assert (
            value.post(
                PREFIX + "/job-batches/completed", json=job_request()
            ).status_code
            == 503
        )


def test_body_limit_and_validation_do_not_echo_input():
    app = create_compute_app(token=TOKEN, registry=REGISTRY, max_body_bytes=128)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as value:
        response = value.post(PREFIX + "/job-batches/completed", content=b"x" * 129)
        assert response.status_code == 413
        response = value.post(
            PREFIX + "/job-batches/completed", json={"secret": "do-not-echo"}
        )
        assert response.status_code == 422
        assert "do-not-echo" not in response.text
