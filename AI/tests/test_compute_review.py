"""The real job execution persists its unresolved inputs with its DB results."""

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from test_compute_api import PREFIX, REGISTRY, client, event, snapshot_ref  # noqa: F401
from test_job_cohort import batch as job_batch
from test_job_cohort import criteria, posting

from job.classifier import classify_job_batch
from job.contracts import JobAnalysisInputBatch
from registry.mapper import RegistryMapper
from registry.review import build_records
from worker.intake import JobOutput, publish_job_input_set
from worker.store import Artifact, ComputeStore, apply_migration


def review_batch():
    source = (
        Path(__file__).resolve().parents[1] / "job/fixtures/job_analysis_input_v1.json"
    )
    payload = JobAnalysisInputBatch.model_validate_json(source.read_bytes())
    return payload.model_copy(update={"dataset_snapshot_id": "review-" + uuid4().hex})


def test_job_completion_enqueues_review_and_retry_preserves_one_record(client):  # noqa: F811
    batch = review_batch()
    request = event(
        batch=batch.model_dump(mode="json"), criteria=criteria().model_dump(mode="json")
    )
    response = client.post(PREFIX + "/job-batches/completed", json=request)
    cohort_id = snapshot_ref(response, "COHORT")
    records = build_records(classify_job_batch(batch, RegistryMapper(REGISTRY)))
    assert len(records) == 4
    for record in records:
        reply = client.get(PREFIX + f"/registry/reviews/{record.review_id}")
        assert reply.status_code == 200, reply.text
        saved = reply.json()["data"]
        assert saved["version"] == 1
        assert (
            saved["record"]["source_dataset_snapshot_id"] == batch.dataset_snapshot_id
        )
        assert saved["record"]["evidence_text"] == record.evidence_text
        assert cohort_id in saved["cohort_snapshot_ids"]
    repeated = client.post(PREFIX + "/job-batches/completed", json=request)
    assert repeated.json() == response.json()


def test_review_read_requires_internal_auth_and_missing_is_404(client):  # noqa: F811
    assert (
        client.get(
            PREFIX + "/registry/reviews", headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert (
        client.get(PREFIX + "/registry/reviews/review-" + "0" * 24).status_code == 404
    )


def test_review_failure_rolls_back_snapshot_and_event_completion() -> None:
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires an explicitly selected isolated PostgreSQL database")
    store = ComputeStore(dsn)
    event_id = str(uuid4())
    occurred_at = datetime.now(UTC)
    ticket = store.claim(
        event_id=event_id,
        kind="JOB_BATCH",
        owner=None,
        occurred_at=occurred_at,
        request={"review_rollback": event_id},
    )
    record = build_records(
        classify_job_batch(review_batch(), RegistryMapper(REGISTRY))
    )[0]
    invalid = record.model_copy(update={"source_dataset_snapshot_id": None})
    artifact = Artifact(
        "COHORT",
        None,
        {"rollback": event_id},
        event_id,
        review_records=(invalid.model_dump(mode="json"),),
    )

    with pytest.raises(ValueError, match="source_dataset_snapshot_id"):
        store.complete(ticket, [artifact])

    assert store.get_snapshot(artifact.snapshot_id, owner=None) is None
    replay = store.claim(
        event_id=event_id,
        kind="JOB_BATCH",
        owner=None,
        occurred_at=occurred_at,
        request={"review_rollback": event_id},
    )
    assert replay.status == "RUNNING" and replay.token is None
    store.fail(ticket, "INVALID_REVIEW")


def test_same_source_record_id_from_different_sites_preserves_both_reviews() -> None:
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires an explicitly selected isolated PostgreSQL database")
    apply_migration(dsn)
    store = ComputeStore(dsn)
    identifier = uuid4().hex
    batch = job_batch(
        posting(
            identifier,
            source_site="SARAMIN",
            source_url=f"https://example.com/saramin/{identifier}",
            required=("QuantumDB",),
        ),
        posting(
            identifier,
            source_site="WANTED",
            source_url=f"https://example.com/wanted/{identifier}",
            required=("QuantumDB",),
        ),
    ).model_copy(
        update={
            "dataset_snapshot_id": "review-sites-" + identifier,
            "pipeline_run_id": "review-sites-run-" + identifier,
        }
    )
    records = build_records(classify_job_batch(batch, RegistryMapper(REGISTRY)))
    ticket = store.claim(
        event_id=str(uuid4()),
        kind="JOB_BATCH",
        owner=None,
        occurred_at=datetime.now(UTC),
        request={"review_sites": identifier},
    )
    artifact = Artifact(
        "COHORT",
        None,
        {"review_sites": identifier},
        identifier,
        review_records=tuple(record.model_dump(mode="json") for record in records),
    )

    store.complete(ticket, [artifact])

    assert len(records) == 2
    assert len({record.review_id for record in records}) == 2
    assert {
        store.get_review(record.review_id).record.source_site for record in records
    } == {"SARAMIN", "WANTED"}


def test_changed_source_variants_persist_as_distinct_review_evidence(client):  # noqa: F811
    identifier = uuid4().hex
    first = posting(identifier, required=("QuantumDB",))
    changed = posting(
        identifier,
        required=("QuantumDB",),
        source_url=f"https://example.com/revised/{identifier}",
        title="수정된 백엔드 개발자",
    )
    source_batch = job_batch(first, changed).model_copy(
        update={
            "dataset_snapshot_id": "review-variants-" + identifier,
            "pipeline_run_id": "review-variants-run-" + identifier,
        }
    )
    records = build_records(classify_job_batch(source_batch, RegistryMapper(REGISTRY)))

    assert len(records) == 2
    assert len({record.review_id for record in records}) == 2
    response = client.post(
        PREFIX + "/job-batches/completed",
        json=event(
            batch=source_batch.model_dump(mode="json"),
            criteria=criteria().model_dump(mode="json"),
        ),
    )
    cohort_id = snapshot_ref(response, "COHORT")
    stored = [
        client.get(PREFIX + f"/registry/reviews/{record.review_id}").json()["data"]
        for record in records
    ]
    assert {item["record"]["source_url"] for item in stored} == {
        str(first.source_url),
        str(changed.source_url),
    }
    assert all(cohort_id in item["cohort_snapshot_ids"] for item in stored)


def test_long_contract_valid_dataset_snapshot_id_persists_with_review(client):  # noqa: F811
    source_batch = review_batch().model_copy(
        update={"dataset_snapshot_id": "dataset-" + "x" * 300}
    )
    records = build_records(classify_job_batch(source_batch, RegistryMapper(REGISTRY)))

    response = client.post(
        PREFIX + "/job-batches/completed",
        json=event(
            batch=source_batch.model_dump(mode="json"),
            criteria=criteria().model_dump(mode="json"),
        ),
    )

    snapshot_ref(response, "COHORT")
    stored = client.get(PREFIX + f"/registry/reviews/{records[0].review_id}").json()[
        "data"
    ]
    assert stored["record"]["source_dataset_snapshot_id"] == (
        source_batch.dataset_snapshot_id
    )


def test_review_preparation_failure_is_failed_then_same_union_retries(
    monkeypatch,
) -> None:
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires an explicitly selected isolated PostgreSQL database")
    apply_migration(dsn)
    store = ComputeStore(dsn)
    identifier = uuid4().hex
    source_batch = job_batch(posting(identifier, required=("QuantumDB",))).model_copy(
        update={
            "dataset_snapshot_id": "review-retry-" + identifier,
            "pipeline_run_id": "review-retry-run-" + identifier,
        }
    )
    output = JobOutput(
        batch=source_batch,
        occurred_at=source_batch.records[0].collected_at,
        batch_sha256="c" * 64,
        manifest_sha256="d" * 64,
        collection_issues=(),
        source_site="SARAMIN",
        batch_size_bytes=len(source_batch.model_dump_json().encode()),
    )
    from worker import jobs

    original = jobs.job_review_records

    def fail_review_preparation(*_args):
        raise RuntimeError("review preparation failed")

    monkeypatch.setattr(jobs, "job_review_records", fail_review_preparation)
    with pytest.raises(RuntimeError, match="review preparation failed"):
        publish_job_input_set(
            (output,),
            criteria(),
            store=store,
            mapper=RegistryMapper(REGISTRY),
            registry=REGISTRY,
        )
    monkeypatch.setattr(jobs, "job_review_records", original)

    retried = publish_job_input_set(
        (output,),
        criteria(),
        store=store,
        mapper=RegistryMapper(REGISTRY),
        registry=REGISTRY,
    )

    assert retried["status"] == "COMPLETED"
    assert {item["kind"] for item in retried["results"]} == {"COHORT", "DEMAND"}


def test_observed_input_union_enqueues_selected_original_review() -> None:
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires an explicitly selected isolated PostgreSQL database")
    apply_migration(dsn)
    store = ComputeStore(dsn)
    identifier = uuid4().hex
    source_batch = job_batch(posting(identifier, required=("QuantumDB",))).model_copy(
        update={
            "dataset_snapshot_id": "union-review-" + identifier,
            "pipeline_run_id": "union-review-run-" + identifier,
        }
    )
    output = JobOutput(
        batch=source_batch,
        occurred_at=source_batch.records[0].collected_at,
        batch_sha256="a" * 64,
        manifest_sha256="b" * 64,
        collection_issues=(),
        source_site="SARAMIN",
        batch_size_bytes=len(source_batch.model_dump_json().encode()),
    )
    mapper = RegistryMapper(REGISTRY)

    result = publish_job_input_set(
        (output,),
        criteria(),
        store=store,
        mapper=mapper,
        registry=REGISTRY,
    )

    cohort_id = next(
        item["snapshot_id"] for item in result["results"] if item["kind"] == "COHORT"
    )
    record = build_records(classify_job_batch(source_batch, mapper))[0]
    stored = store.get_review(record.review_id)
    assert stored.record.source_dataset_snapshot_id == source_batch.dataset_snapshot_id
    assert stored.cohort_snapshot_ids == (cohort_id,)
