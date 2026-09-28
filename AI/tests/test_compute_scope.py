"""Semantic latest-pointer scopes against explicitly isolated PostgreSQL."""

import os
from datetime import datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_compute_api import PREFIX, REGISTRY, TOKEN, event, snapshot_ref
from test_job_cohort import batch, criteria, posting
from test_public_analysis import Reader, batch_with

from worker.api import create_compute_app
from worker.store import ComputeStore, apply_migration


@pytest.fixture
def review_client():
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires explicitly selected isolated PostgreSQL test database")
    apply_migration(dsn)
    app = create_compute_app(store=ComputeStore(dsn), token=TOKEN, registry=REGISTRY)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as value:
        yield value


def create_job_trend(client, *, query_changes=None, count=1, occurred_at=None):
    query = criteria(
        purpose="MONTHLY_DEMAND",
        posted_from="2026-08-01T00:00:00+09:00",
        posted_to="2026-09-01T00:00:00+09:00",
        **(query_changes or {}),
    )
    jobs = [
        posting(
            str(uuid4()),
            title=query.target_role,
            raw_job_category=query.target_role,
            posted_at="2026-08-15T00:00:00+09:00",
            required=("Python",),
        )
        for _ in range(count)
    ]
    input_batch = batch(*jobs).model_dump(mode="json")
    input_batch.update(dataset_snapshot_id=str(uuid4()), pipeline_run_id=str(uuid4()))
    demand = snapshot_ref(
        client.post(
            PREFIX + "/job-batches/completed",
            json=event(batch=input_batch, criteria=query.model_dump(mode="json")),
        ),
        "DEMAND",
    )
    request = event(
        tech_id="python",
        source="JOB",
        periods=["2026-08"],
        demand_snapshot_ids=[demand],
    )
    if occurred_at is not None:
        request["occurred_at"] = occurred_at
    trend = snapshot_ref(
        client.post(PREFIX + "/trends/completed", json=request), "TREND"
    )
    result = client.get(PREFIX + f"/snapshots/{trend}").json()["data"]["payload"]
    assert result["points"][0]["value"] == count
    return request, trend, result


def heads_for(kind, requests):
    with psycopg.connect(os.environ["C_COMPUTE_TEST_DATABASE_URL"]) as conn:
        return conn.execute(
            "SELECT stream, snapshot_id, event_id FROM c_compute.head "
            "WHERE kind = %s AND event_id = ANY(%s)",
            (kind, [request["event_id"] for request in requests]),
        ).fetchall()


@pytest.mark.parametrize(
    "query_changes",
    [
        {"target_role": "FRONTEND"},
        {"sources": ["SARAMIN"]},
        {"regions": ["서울"]},
        {"career_levels": ["신입"]},
        {"min_jobs": 2},
    ],
)
def test_job_trend_latest_pointers_preserve_query_scope(review_client, query_changes):
    first, first_id, _ = create_job_trend(review_client)
    second, second_id, result = create_job_trend(
        review_client, query_changes=query_changes
    )
    for key, value in query_changes.items():
        assert result["filters"][key] == value
    assert first_id != second_id
    heads = heads_for("TREND", [first, second])
    assert len(heads) == 2, "different filters must not overwrite one latest pointer"


def test_job_trend_same_scope_refreshes_without_late_completion_regression(
    review_client,
):
    first, first_id, _ = create_job_trend(review_client)
    second, second_id, _ = create_job_trend(review_client, count=2)
    assert first_id != second_id
    old_time = (
        datetime.fromisoformat(first["occurred_at"]) - timedelta(days=1)
    ).isoformat()
    late, late_id, _ = create_job_trend(review_client, count=3, occurred_at=old_time)
    assert late_id not in (first_id, second_id)
    heads = heads_for("TREND", [first, second, late])
    assert len(heads) == 1, "new input runs and values do not create a new query scope"
    assert heads[0][1:] == (second_id, second["event_id"])


def test_public_latest_pointers_preserve_partial_inclusion_policy():
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires explicitly selected isolated PostgreSQL test database")
    apply_migration(dsn)
    content = b'{"dependencies":{"react":"1"}}'
    app = create_compute_app(
        store=ComputeStore(dsn),
        token=TOKEN,
        registry=REGISTRY,
        artifact_reader=Reader(content),
    )
    requests, result_ids = [], []
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        for include_partial in (False, True, False, False):
            input_batch = batch_with(content, status="PARTIAL").model_dump(mode="json")
            input_batch["pipeline_run_id"] = str(uuid4())
            request = event(
                batch=input_batch,
                include_partial=include_partial,
            )
            if len(requests) == 3:
                request["occurred_at"] = (
                    datetime.fromisoformat(requests[0]["occurred_at"])
                    - timedelta(days=1)
                ).isoformat()
            result_id = snapshot_ref(
                client.post(
                    PREFIX + "/public-repositories/completed",
                    json=request,
                ),
                "PUBLIC_GITHUB",
            )
            result = client.get(PREFIX + f"/snapshots/{result_id}").json()["data"][
                "payload"
            ]
            assert result["include_partial"] is include_partial
            assert result["sample_repo_count"] == int(include_partial)
            requests.append(request)
            result_ids.append(result_id)
    assert len(set(result_ids)) == 4
    heads = heads_for("PUBLIC_GITHUB", requests)
    assert len(heads) == 2, (
        "partial inclusion policies must not overwrite one latest pointer"
    )
    assert {row[1] for row in heads} == {result_ids[1], result_ids[2]}
