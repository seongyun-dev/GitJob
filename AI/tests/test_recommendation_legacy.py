"""Synthetic pre-proof v1 persisted snapshot: never recompute or rehash on read."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from test_compute_api import (
    client as client,  # noqa: PLC0414 - pytest fixture re-export
)

from recommendation.engine import RecommendationSnapshot, list_related_jobs
from worker.store import Artifact, ComputeStore


def test_pre_profile_snapshot_roundtrip_and_job_listing_are_byte_shape_stable():
    payload = json.loads(
        (Path(__file__).parent / "fixtures/recommendation-legacy-v1.json").read_text()
    )
    result = RecommendationSnapshot.model_validate(payload)
    assert result.model_dump(mode="json") == payload
    assert result.snapshot_id == payload["snapshot_id"]
    page = list_related_jobs(result, user_id="user-1", view="CURRENT")
    assert page.current_count == 1
    assert [job.job_id for job in page.items] == ["current"]
    projected = list_related_jobs(
        result, user_id="user-1", view="WHAT_IF", tech_id="docker"
    )
    assert projected.total_count == 2
    assert [job.job_id for job in projected.items] == ["docker-gain", "or-gain"]


def test_pre_profile_snapshot_postgres_and_http_listing_preserve_stored_identity(
    client,
):
    payload = json.loads(
        (Path(__file__).parent / "fixtures/recommendation-legacy-v1.json").read_text()
    )
    store = ComputeStore(os.environ["C_COMPUTE_TEST_DATABASE_URL"])
    ticket = store.claim(
        event_id=f"legacy-read-{uuid4()}",
        kind="ANALYSIS",
        owner="user-1",
        occurred_at=datetime.now(UTC),
        request={"legacy_snapshot_id": payload["snapshot_id"]},
    )
    saved = store.complete(
        ticket,
        [Artifact("RECOMMENDATION", "user-1", payload, f"legacy-read-{uuid4()}")],
    )[0]["snapshot_id"]
    response = client.get(
        f"/internal/v1/c/snapshots/{saved}", params={"user_id": "user-1"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["payload"] == payload
    listing = client.get(
        f"/internal/v1/c/recommendations/{saved}/job-postings",
        params={
            "user_id": "user-1",
            "mode": "WHAT_IF",
            "recommended_tech_id": "docker",
        },
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["data"]["snapshot_id"] == saved
    assert listing.json()["data"]["total_count"] == 2
    assert [job["job_id"] for job in listing.json()["data"]["items"]] == [
        "docker-gain",
        "or-gain",
    ]
