"""HTTP review revision and retry semantics on a real local PostgreSQL."""

# ruff: noqa: F811 -- pytest discovers the imported client fixture.

from uuid import uuid4

from test_compute_api import PREFIX, REGISTRY, client, event, snapshot_ref  # noqa: F401
from test_compute_review import review_batch
from test_job_cohort import criteria

from job.classifier import classify_job_batch
from registry.mapper import RegistryMapper
from registry.review import build_records


def test_review_resolution_preserves_source_and_rejects_stale_mutation(client):
    batch = review_batch()
    snapshot_ref(
        client.post(
            PREFIX + "/job-batches/completed",
            json=event(
                batch=batch.model_dump(mode="json"),
                criteria=criteria().model_dump(mode="json"),
            ),
        ),
        "COHORT",
    )
    record = next(
        row
        for row in build_records(classify_job_batch(batch, RegistryMapper(REGISTRY)))
        if row.raw_technology == "QuantumDB"
    )
    path = PREFIX + f"/registry/reviews/{record.review_id}"
    action = {
        "actor": "test-b-admin",
        "note": "원문 확인",
        "idempotency_key": uuid4().hex,
        "expected_version": 1,
        "tech_id": "postgresql",
    }
    response = client.post(path + "/resolve", json=action)
    assert response.status_code == 200, response.text
    saved = response.json()["data"]
    assert saved["version"] == 2
    assert saved["record"]["evidence_text"] == record.evidence_text
    assert saved["record"]["resolved_tech_id"] == "postgresql"
    assert client.post(path + "/resolve", json=action).json() == response.json()
    stale = client.post(
        path + "/resolve", json={**action, "idempotency_key": uuid4().hex}
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "REVIEW_VERSION_CONFLICT"
    conflict = client.post(path + "/resolve", json={**action, "tech_id": "java"})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "REVIEW_IDEMPOTENCY_CONFLICT"
    no_auth = client.post(path + "/resolve", json=action, headers={"Authorization": ""})
    assert no_auth.status_code == 401
