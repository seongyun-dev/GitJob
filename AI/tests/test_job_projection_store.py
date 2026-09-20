"""PostgreSQL integration checks for atomic job projection publication."""

import os
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from test_job_cohort import criteria, posting
from test_job_input_union import output

from job.input_union import prepare_input_union
from job.projection import materialize_job_projection
from registry.mapper import RegistryMapper
from worker.api import default_registry
from worker.job_projection_store import JobProjectionIntegrityError, JobProjectionStore
from worker.store import ComputeStore, apply_migration


@pytest.fixture(autouse=True)
def _file_registry(monkeypatch):
    monkeypatch.setenv("C_REGISTRY_BACKEND", "file")


@pytest.fixture
def store():
    dsn = os.environ.get("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set C_COMPUTE_TEST_DATABASE_URL to an isolated PostgreSQL test DB")
    apply_migration(dsn)
    value = ComputeStore(dsn)
    with value._connect() as conn:
        conn.execute("DELETE FROM c_compute.job_projection_head")
    return value


def _projection(job_id="projection-store"):
    prepared = prepare_input_union(
        (output(posting(f"{job_id}-{uuid4().hex}")),),
        criteria(),
        RegistryMapper(default_registry()),
    )
    return materialize_job_projection(prepared)


def _rekey(projection, marker: str, *, observed_at):
    projection_id = "jp-" + sha256(
        f"{marker}:{projection.projection_version_id}".encode()
    ).hexdigest()
    return replace(
        projection,
        projection_version_id=projection_id,
        observed_at=observed_at,
        jobs=tuple(
            replace(job, projection_version_id=projection_id)
            for job in projection.jobs
        ),
    )


def test_projection_publish_is_idempotent_and_head_is_published(store):
    projection = _projection()
    assert store.publish_job_projection(projection) == projection.projection_version_id
    assert store.publish_job_projection(projection) == projection.projection_version_id
    head = store.get_job_projection_head()
    assert head is not None
    assert head["projection_version_id"] == projection.projection_version_id
    assert head["state"] == "PUBLISHED"
    with store._connect() as conn:
        count = conn.execute(
            "SELECT count(*) AS count FROM c_compute.job_projection_job "
            "WHERE projection_version_id = %s",
            (projection.projection_version_id,),
        ).fetchone()["count"]
    assert count == len(projection.jobs)
    demand = store.query_job_projection_demand(criteria())
    assert len(demand.selected_job_ids) == 1
    assert demand.selected_job_ids[0].startswith("SARAMIN:projection-store-")
    assert demand.snapshot.denominator == 1
    readiness = store.get_job_projection_readiness()
    assert readiness["status"] == "READY"
    assert readiness["stored_job_count"] == readiness["job_count"]


def test_failed_build_keeps_previous_head_and_records_failure(store):
    good = _projection("projection-head")
    store.publish_job_projection(good)
    bad_id = "jp-" + sha256(good.projection_version_id.encode()).hexdigest()
    bad_job = replace(
        good.jobs[0],
        projection_version_id=bad_id,
        role_codes=("FRONTEND", "BACKEND"),
    )
    bad = replace(good, projection_version_id=bad_id, jobs=(bad_job,))
    with pytest.raises(psycopg.Error):
        store.publish_job_projection(bad)
    assert (
        store.get_job_projection_head()["projection_version_id"]
        == good.projection_version_id
    )
    with store._connect() as conn:
        state = conn.execute(
            "SELECT state, error_code FROM c_compute.job_projection_version "
            "WHERE projection_version_id = %s",
            (bad_id,),
        ).fetchone()
    assert state["state"] == "FAILED"
    assert state["error_code"]


def test_older_publish_cannot_regress_projection_head(store):
    base = _projection("projection-order")
    newer = _rekey(base, "a", observed_at=base.observed_at + timedelta(seconds=1))
    older = _rekey(base, "b", observed_at=base.observed_at)

    store.publish_job_projection(newer)
    store.publish_job_projection(older)

    assert store.get_job_projection_head()["projection_version_id"] == (
        newer.projection_version_id
    )


def test_projection_rollback_is_cas_audited_and_blocks_republication(store):
    base = _projection("projection-rollback")
    previous = _rekey(base, "c", observed_at=base.observed_at)
    rejected = _rekey(
        base, "d", observed_at=base.observed_at + timedelta(seconds=1)
    )
    store.publish_job_projection(previous)
    store.publish_job_projection(rejected)

    projection_store = JobProjectionStore(store._dsn)
    selected = projection_store.rollback(
        expected_current=rejected.projection_version_id,
        target_projection_version_id=previous.projection_version_id,
        actor="integration-test",
        reason="verify audited rollback",
    )

    assert selected == previous.projection_version_id
    assert store.get_job_projection_head()["projection_version_id"] == selected
    # The rejected immutable version may be retried, but it cannot reclaim the head.
    store.publish_job_projection(rejected)
    assert store.get_job_projection_head()["projection_version_id"] == selected
    with store._connect() as conn:
        blocked = conn.execute(
            "SELECT actor, reason FROM c_compute.job_projection_block "
            "WHERE projection_version_id = %s",
            (rejected.projection_version_id,),
        ).fetchone()
        audit = conn.execute(
            "SELECT actor, reason FROM c_compute.job_projection_head_audit "
            "WHERE from_projection_version_id = %s AND to_projection_version_id = %s",
            (rejected.projection_version_id, previous.projection_version_id),
        ).fetchone()
    assert blocked == audit == {
        "actor": "integration-test",
        "reason": "verify audited rollback",
    }
    with pytest.raises(JobProjectionIntegrityError, match="blocked"):
        projection_store.rollback(
            expected_current=previous.projection_version_id,
            target_projection_version_id=rejected.projection_version_id,
            actor="integration-test",
            reason="blocked target must not return",
        )
    assert store.get_job_projection_head()["projection_version_id"] == selected
