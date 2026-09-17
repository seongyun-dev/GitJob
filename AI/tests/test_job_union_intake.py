"""Observed multi-source input sets survive restart and cannot mask source filters."""

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_compute_api import REGISTRY, TOKEN
from test_job_cohort import batch, criteria, posting

from job import requirements
from registry.mapper import RegistryMapper
from Saramin_Collector_V1.crawler import CrawlResult, write_outputs
from worker.api import JobCohortResolveSelector, create_compute_app
from worker.intake import (
    IntakeConfig,
    IntakeRunner,
    JobOutput,
    publish_job_input_set,
)
from worker.store import ComputeStore, Ticket, apply_migration


def completed(root, source, identifier, *, at="2026-09-07T00:00:00Z", **changes):
    value = batch(
        posting(identifier, source_site=source, collected_at=at, **changes)
    ).model_copy(
        update={"pipeline_run_id": uuid4().hex, "dataset_snapshot_id": uuid4().hex}
    )
    manifest = {
        "schema_version": value.schema_version,
        "dataset_snapshot_id": value.dataset_snapshot_id,
        "pipeline_run_id": value.pipeline_run_id,
        "collector_version": value.collector_version,
        "source_site": source,
        "collected_at": value.records[0].collected_at.isoformat(),
        "counts": {"records": 1},
        "stopped_reason": None,
    }
    return write_outputs(CrawlResult(value, manifest), root)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires explicitly selected isolated PostgreSQL")
    apply_migration(dsn)
    store = ComputeStore(dsn)
    # Each poll is controlled here; the separate lifespan tests exercise threading.
    monkeypatch.setattr(IntakeRunner, "start", lambda self: None)
    query = criteria(as_of=datetime.now(UTC))

    def open_runtime(selected=None):
        selected = selected or query
        config = IntakeConfig(
            schema_version="c-intake-config/v1",
            job_roots=(tmp_path,),
            criteria=(selected,),
        )
        path = tmp_path / "intake-config.json"
        path.write_text(config.model_dump_json(), encoding="utf-8")
        app = create_compute_app(
            store=store, registry=REGISTRY, token=TOKEN, intake_config=path
        )
        client = TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})
        return client, app.state.intake_runner

    return tmp_path, query, open_runtime


def resolve(client, query):
    response = client.post(
        "/internal/v1/c/job-cohorts/resolve", json=query.model_dump(mode="json")
    )
    assert response.status_code == 200, response.text
    resolved = response.json()["data"]
    identifier = resolved["cohort_snapshot_id"]
    value = client.get("/internal/v1/c/snapshots/" + identifier).json()["data"]
    demand = client.get(
        "/internal/v1/c/snapshots/" + resolved["demand_snapshot_id"]
    ).json()["data"]
    assert demand["kind"] == "DEMAND"
    assert demand["payload"]["cohort_id"] == value["payload"]["cohort_id"]
    return identifier, value["payload"]


def test_poll_prewarms_latest_selector_scope_before_first_http_request():
    configured = criteria(
        as_of="2026-09-08T00:00:00Z", sources=("SARAMIN",), min_jobs=20
    )
    saramin = batch(
        posting(
            "saramin-latest",
            source_site="SARAMIN",
            collected_at="2026-09-15T20:00:00Z",
        )
    )
    worknet = batch(
        posting(
            "worknet-latest",
            source_site="WORKNET",
            collected_at="2026-09-15T22:30:04Z",
        )
    )
    outputs = (
        JobOutput(
            batch=saramin,
            occurred_at=saramin.records[0].collected_at,
            batch_sha256="a" * 64,
            manifest_sha256="b" * 64,
            collection_issues=(),
            source_site="SARAMIN",
            batch_size_bytes=len(saramin.model_dump_json().encode()),
        ),
        JobOutput(
            batch=worknet,
            occurred_at=worknet.records[0].collected_at,
            batch_sha256="c" * 64,
            manifest_sha256="d" * 64,
            collection_issues=(),
            source_site="WORKNET",
            batch_size_bytes=len(worknet.model_dump_json().encode()),
        ),
    )
    calls = []

    def publish(_outputs, selected):
        calls.append(selected)
        return {"status": "COMPLETED", "results": []}

    runner = IntakeRunner(
        IntakeConfig.model_construct(
            schema_version="c-intake-config/v1",
            job_roots=(),
            job_hdfs_sources=(),
            criteria=(configured,),
            public_sources=(),
        ),
        job_sink=publish,
        job_set_sink=publish,
    )

    runner._publish_input_set(outputs, {"completed": 0, "failed": 0, "pending": 0})

    # BE는 min_jobs를 보내지 않으므로 1이 계약 기본값이다. source를 고르면 그
    # source의 최신 시각, 생략하면 전체 source의 최신 시각을 써야 한다.
    source_latest = [
        item for item in calls if item.sources == ("SARAMIN",) and item.min_jobs == 1
    ]
    all_latest = [item for item in calls if not item.sources and item.min_jobs == 1]
    assert len(source_latest) == 1
    assert source_latest[0].as_of == saramin.records[0].collected_at
    assert len(all_latest) == 1
    assert all_latest[0].as_of == worknet.records[0].collected_at

    before_resolve = len(calls)
    selected, result = runner.resolve_job_selector(
        JobCohortResolveSelector(
            schema_version="job-cohort-resolve-selector/v1",
            target_role="BACKEND",
            sources=("SARAMIN",),
        )
    )
    assert selected == source_latest[0]
    assert result["status"] == "COMPLETED"
    assert len(calls) == before_resolve

    selected, result = runner.resolve_job_selector(
        JobCohortResolveSelector(
            schema_version="job-cohort-resolve-selector/v1", target_role="BACKEND"
        )
    )
    assert selected == all_latest[0]
    assert result["status"] == "COMPLETED"
    assert len(calls) == before_resolve


def test_review_preparation_failure_after_claim_is_heartbeated_and_failed(
    monkeypatch,
) -> None:
    value = batch(posting("review-preparation", required=("QuantumDB",)))
    output = JobOutput(
        batch=value,
        occurred_at=value.records[0].collected_at,
        batch_sha256="a" * 64,
        manifest_sha256="b" * 64,
        collection_issues=(),
        source_site="SARAMIN",
        batch_size_bytes=len(value.model_dump_json().encode()),
    )
    events = []

    class Store:
        lease_seconds = 120

        def claim(self, **kwargs):
            return Ticket(
                event_id=kwargs["event_id"],
                kind=kwargs["kind"],
                owner=kwargs["owner"],
                occurred_at=kwargs["occurred_at"],
                status="RUNNING",
                token="owned-token",
                attempt=1,
                results=[],
            )

        def complete(self, *_args):
            raise AssertionError("review preparation must fail before completion")

        def fail(self, _ticket, code):
            events.append(("fail", code))

    class Heartbeat:
        def __init__(self, _store, _ticket):
            pass

        def __enter__(self):
            events.append(("heartbeat", "enter"))
            return self

        def __exit__(self, *_args):
            events.append(("heartbeat", "exit"))
            return False

    monkeypatch.setattr("worker.intake.LeaseHeartbeat", Heartbeat)

    def fail_review_preparation(*_args):
        assert events == [("heartbeat", "enter")]
        raise RuntimeError("review preparation failed")

    monkeypatch.setattr("worker.jobs.job_review_records", fail_review_preparation)

    with pytest.raises(RuntimeError, match="review preparation failed"):
        publish_job_input_set(
            (output,),
            criteria(),
            store=Store(),
            mapper=RegistryMapper(REGISTRY),
            registry=REGISTRY,
        )

    assert events == [
        ("heartbeat", "enter"),
        ("heartbeat", "exit"),
        ("fail", "INPUT_UNION_COMPUTE_FAILED"),
    ]


def test_required_level_policy_change_rekeys_durable_union_intake(monkeypatch):
    value = batch(posting("policy-input", required=("React",)))
    output = JobOutput(
        batch=value,
        occurred_at=value.records[0].collected_at,
        batch_sha256="a" * 64,
        manifest_sha256="b" * 64,
        collection_issues=(),
        source_site="SARAMIN",
        batch_size_bytes=len(value.model_dump_json().encode()),
    )
    claims = []

    class CompletedStore:
        def claim(self, **kwargs):
            claims.append(kwargs)
            return Ticket(
                event_id=kwargs["event_id"],
                kind=kwargs["kind"],
                owner=kwargs["owner"],
                occurred_at=kwargs["occurred_at"],
                status="COMPLETED",
                token=None,
                attempt=1,
                results=[{"kind": "COHORT", "snapshot_id": "existing"}],
            )

    store = CompletedStore()
    mapper = RegistryMapper(REGISTRY)
    with monkeypatch.context() as previous:
        previous.setattr(
            requirements,
            "JOB_REQUIRED_LEVEL_POLICY_VERSION",
            "job-required-level-policy/v1",
        )
        publish_job_input_set(
            (output,), criteria(), store=store, mapper=mapper, registry=REGISTRY
        )
    publish_job_input_set(
        (output,), criteria(), store=store, mapper=mapper, registry=REGISTRY
    )

    assert claims[0]["event_id"] != claims[1]["event_id"]
    assert claims[0]["request"]["compute_versions"]["required_level_policy"] == (
        "job-required-level-policy/v1"
    )
    assert claims[1]["request"]["compute_versions"]["required_level_policy"] == (
        requirements.JOB_REQUIRED_LEVEL_POLICY_VERSION
    )


def test_configured_union_combines_sources_and_source_filter_cannot_be_masked(runtime):
    root, query, open_runtime = runtime
    completed(root, "SARAMIN", "same-local-id")
    completed(root, "WORKNET", "same-local-id", at="2026-09-07T01:00:00Z")
    with open_runtime()[0] as client:
        runner = client.app.state.intake_runner
        assert runner.poll_once()["completed"] == 2
        _, cohort = resolve(client, query)
        assert len(cohort["jobs"]) == 2
        assert len({job["job_id"] for job in cohort["jobs"]}) == 2
        assert {job["source_record_id"] for job in cohort["jobs"]} == {"same-local-id"}
    selected = query.model_copy(update={"sources": ("SARAMIN",)})
    with open_runtime(selected)[0] as client:
        client.app.state.intake_runner.poll_once()
        first, cohort = resolve(client, selected)
        assert [job["source_site"] for job in cohort["jobs"]] == ["SARAMIN"]
        completed(root, "WORKNET", "foreign-new", at="2026-09-07T02:00:00Z")
        client.app.state.intake_runner.poll_once()
        assert resolve(client, selected)[0] == first


def test_stable_selector_builds_and_reuses_a_filtered_pair_from_verified_inputs(
    runtime,
):
    root, _, open_runtime = runtime
    completed(root, "SARAMIN", "seoul", region="서울")
    completed(root, "WORKNET", "busan", at="2026-09-07T01:00:00Z", region="부산")
    request = {
        "schema_version": "job-cohort-resolve-selector/v1",
        "target_role": "BACKEND",
        "regions": ["서울"],
    }
    with open_runtime()[0] as client:
        runner = client.app.state.intake_runner
        runner.poll_once()
        first = client.post("/internal/v1/c/job-cohorts/resolve", json=request)
        repeated = client.post("/internal/v1/c/job-cohorts/resolve", json=request)
        assert first.status_code == 200, first.text
        assert repeated.json() == first.json()
        data = first.json()["data"]
        assert data["criteria"]["as_of"] == "2026-09-07T01:00:00Z"
        assert data["criteria"]["regions"] == ["서울"]
        cohort = client.get(
            "/internal/v1/c/snapshots/" + data["cohort_snapshot_id"]
        ).json()["data"]
        demand = client.get(
            "/internal/v1/c/snapshots/" + data["demand_snapshot_id"]
        ).json()["data"]
        assert [job["region"] for job in cohort["payload"]["jobs"]] == ["서울"]
        assert demand["payload"]["cohort_id"] == cohort["payload"]["cohort_id"]

        completed(
            root, "SARAMIN", "seoul-new", at="2026-09-07T02:00:00Z", region="서울"
        )
        runner.poll_once()
        refreshed = client.post("/internal/v1/c/job-cohorts/resolve", json=request)
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["data"]["criteria"]["as_of"] == "2026-09-07T02:00:00Z"
        assert (
            refreshed.json()["data"]["cohort_snapshot_id"] != data["cohort_snapshot_id"]
        )


def test_source_selector_ignores_unselected_source_updates(runtime):
    root, _, open_runtime = runtime
    completed(root, "SARAMIN", "selected", at="2026-09-07T01:00:00Z")
    completed(root, "WORKNET", "other", at="2026-09-07T03:00:00Z")
    request = {
        "schema_version": "job-cohort-resolve-selector/v1",
        "target_role": "BACKEND",
        "sources": ["saramin"],
    }
    with open_runtime()[0] as client:
        runner = client.app.state.intake_runner
        runner.poll_once()
        first = client.post("/internal/v1/c/job-cohorts/resolve", json=request)
        assert first.status_code == 200, first.text
        first_data = first.json()["data"]
        assert first_data["criteria"]["as_of"] == "2026-09-07T01:00:00Z"
        assert first_data["criteria"]["sources"] == ["SARAMIN"]

        completed(root, "WORKNET", "other-new", at="2026-09-07T04:00:00Z")
        runner.poll_once()
        repeated = client.post("/internal/v1/c/job-cohorts/resolve", json=request)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == first.json()


def test_late_older_input_changes_current_union_and_restart_keeps_exact_result(runtime):
    root, query, open_runtime = runtime
    completed(root, "SARAMIN", "newer", at="2026-09-07T03:00:00Z")
    with open_runtime()[0] as client:
        client.app.state.intake_runner.poll_once()
        first, _ = resolve(client, query)
        completed(root, "WORKNET", "late-older", at="2026-09-07T01:00:00Z")
        client.app.state.intake_runner.poll_once()
        second, cohort = resolve(client, query)
        assert len(cohort["jobs"]) == 2
        assert second != first
    with open_runtime()[0] as client:
        client.app.state.intake_runner.poll_once()
        assert resolve(client, query)[0] == second


def test_restart_does_not_resolve_a_durable_head_before_the_first_valid_poll(runtime):
    root, query, open_runtime = runtime
    completed(root, "SARAMIN", "one")
    with open_runtime()[0] as client:
        client.app.state.intake_runner.poll_once()
        old_id, _ = resolve(client, query)
    with open_runtime()[0] as client:
        response = client.post(
            "/internal/v1/c/job-cohorts/resolve", json=query.model_dump(mode="json")
        )
        assert response.status_code == 404
        assert client.get("/internal/v1/c/snapshots/" + old_id).status_code == 200
        client.app.state.intake_runner.poll_once()
        assert resolve(client, query)[0] == old_id


def test_new_closed_observation_does_not_revive_old_active_job(runtime):
    root, query, open_runtime = runtime
    completed(root, "SARAMIN", "one")
    with open_runtime()[0] as client:
        client.app.state.intake_runner.poll_once()
        assert len(resolve(client, query)[1]["jobs"]) == 1
        completed(
            root, "SARAMIN", "one", at="2026-09-07T01:00:00Z", posting_status="CLOSED"
        )
        client.app.state.intake_runner.poll_once()
        cohort = resolve(client, query)[1]
        assert not cohort["jobs"]
        assert any("POSTING_CLOSED" in row["reasons"] for row in cohort["exclusions"])


def test_incomplete_input_set_never_exposes_smaller_union_as_complete(runtime):
    root, query, open_runtime = runtime
    completed(root, "SARAMIN", "one")
    bad = completed(root, "WORKNET", "two")
    with open_runtime()[0] as client:
        runner = client.app.state.intake_runner
        runner.poll_once()
        old_id, _ = resolve(client, query)
        manifest = json.loads(bad["manifest"].read_bytes())
        manifest["counts"]["detail_errors"] = 1
        bad["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
        assert runner.poll_once()["blocked"] == 1
        response = client.post(
            "/internal/v1/c/job-cohorts/resolve", json=query.model_dump(mode="json")
        )
        assert response.status_code == 404
        assert client.get("/internal/v1/c/snapshots/" + old_id).status_code == 200


def test_union_record_bound_stops_before_sink_without_stopping_public(
    tmp_path, monkeypatch
):
    from worker import intake

    completed(tmp_path, "SARAMIN", "one")
    completed(tmp_path, "WORKNET", "two")
    monkeypatch.setattr(intake, "MAX_JOB_SET_RECORDS", 1)
    calls = []

    def forbidden(*args):
        raise AssertionError("oversized or incomplete sets must not be published")

    def public():
        calls.append(True)
        return {"status": "COMPLETED", "results": []}

    runner = IntakeRunner(
        IntakeConfig(
            schema_version="c-intake-config/v1",
            job_roots=(tmp_path,),
            criteria=(criteria(),),
        ),
        job_sink=forbidden,
        job_set_sink=forbidden,
        public_sinks=(public,),
    )
    assert runner.poll_once()["failed"] == 1
    assert runner.current_job_result(criteria()) is None
    assert calls == [True]


def test_source_limited_config_still_checks_unfiltered_selector_capacity(
    tmp_path, monkeypatch
):
    from worker import intake

    completed(tmp_path, "SARAMIN", "one")
    completed(tmp_path, "WORKNET", "two")
    monkeypatch.setattr(intake, "MAX_JOB_SET_RECORDS", 1)
    selected = criteria(sources=("SARAMIN",))

    def forbidden(*_args):
        raise AssertionError("unfiltered oversized selector reached the sink")

    runner = IntakeRunner(
        IntakeConfig(
            schema_version="c-intake-config/v1",
            job_roots=(tmp_path,),
            criteria=(selected,),
        ),
        job_sink=forbidden,
        job_set_sink=forbidden,
    )

    assert runner.poll_once()["failed"] == 1


def test_empty_input_directory_is_pending_not_empty_market(tmp_path):
    calls = []
    runner = IntakeRunner(
        IntakeConfig(
            schema_version="c-intake-config/v1",
            job_roots=(tmp_path,),
            criteria=(criteria(),),
        ),
        job_sink=lambda *args: calls.append(args),
        job_set_sink=lambda *args: calls.append(args),
    )
    assert runner.poll_once()["pending"] == 1
    assert not calls


def test_previously_consumed_manifest_missing_from_discovery_is_not_a_deletion(
    tmp_path, monkeypatch
):
    completed(tmp_path, "SARAMIN", "one")
    completed(tmp_path, "WORKNET", "two")
    published = []
    public_calls = []

    def publish(values, query):
        published.append(len(values))
        return {"status": "COMPLETED", "results": []}

    def public():
        public_calls.append(True)
        return {"status": "IN_PROGRESS", "results": []}

    runner = IntakeRunner(
        IntakeConfig(
            schema_version="c-intake-config/v1",
            job_roots=(tmp_path,),
            criteria=(criteria(),),
        ),
        job_sink=publish,
        job_set_sink=publish,
        public_sinks=(public,),
    )
    manifests = runner._manifests()
    assert runner.poll_once()["completed"] == 2
    monkeypatch.setattr(runner, "_manifests", lambda: manifests[:1])
    assert runner.poll_once()["failed"] == 1
    assert runner.current_job_result(criteria()) is None
    assert published == [2, 2]
    assert len(public_calls) == 2
    monkeypatch.setattr(runner, "_manifests", lambda: manifests)
    runner.poll_once()
    assert runner.current_job_result(criteria())["status"] == "COMPLETED"
    assert published == [2, 2]


def republish(root, value):
    """Use the real writer with a fixed run identity, including its new byte hash."""
    manifest = {
        "schema_version": value.schema_version,
        "dataset_snapshot_id": value.dataset_snapshot_id,
        "pipeline_run_id": value.pipeline_run_id,
        "collector_version": value.collector_version,
        "source_site": "SARAMIN",
        "collected_at": value.records[0].collected_at.isoformat(),
        "counts": {"records": len(value.records)},
        "stopped_reason": None,
    }
    return write_outputs(CrawlResult(value, manifest), root)


@pytest.mark.parametrize("change", ["shrink", "same_count", "manifest_only"])
def test_republished_completion_never_replaces_verified_input(tmp_path, change):
    value = batch(posting("one"), posting("two"))
    paths = republish(tmp_path, value)
    original = {name: path.read_bytes() for name, path in paths.items()}
    published = []

    def publish(outputs, query):
        published.append(sum(len(output.batch.records) for output in outputs))
        return {"status": "COMPLETED", "results": []}

    runner = IntakeRunner(
        IntakeConfig(
            schema_version="c-intake-config/v1",
            job_roots=(tmp_path,),
            criteria=(criteria(),),
        ),
        job_sink=publish,
        job_set_sink=publish,
    )
    assert runner.poll_once()["completed"] == 2
    # Byte-identical publisher retry is still an idempotent delivery.
    republish(tmp_path, value)
    assert runner.poll_once()["failed"] == 0
    assert published == [2, 2]
    if change == "manifest_only":
        manifest = json.loads(paths["manifest"].read_bytes())
        manifest["review_note"] = "replaced"
        paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
    else:
        records = (
            (posting("one"),)
            if change == "shrink"
            else (posting("one"), posting("other"))
        )
        republish(tmp_path, value.model_copy(update={"records": records}))
    assert runner.poll_once()["failed"] == 1
    assert runner.current_job_result(criteria()) is None
    assert published == [2, 2]
    # Restoring the original verified bytes recovers the existing result.
    for name, raw in original.items():
        paths[name].write_bytes(raw)
    assert runner.poll_once()["failed"] == 0
    assert runner.current_job_result(criteria())["status"] == "COMPLETED"
    assert published == [2, 2]


def test_replaced_input_is_rejected_after_worker_restart(runtime):
    root, query, open_runtime = runtime
    value = batch(posting("one"), posting("two"))
    republish(root, value)
    with open_runtime()[0] as client:
        runner = client.app.state.intake_runner
        assert runner.poll_once()["completed"] == 2
        old_id, cohort = resolve(client, query)
        assert len(cohort["jobs"]) == 2
    republish(root, value.model_copy(update={"records": (posting("one"),)}))
    with open_runtime()[0] as client:
        runner = client.app.state.intake_runner
        assert runner.poll_once()["failed"] == 1
        assert (
            client.post(
                "/internal/v1/c/job-cohorts/resolve", json=query.model_dump(mode="json")
            ).status_code
            == 404
        )
        # Only the live resolve is unavailable; accepted immutable history remains.
        assert (
            len(
                client.get("/internal/v1/c/snapshots/" + old_id).json()["data"][
                    "payload"
                ]["jobs"]
            )
            == 2
        )
        republish(root, value)
        assert runner.poll_once()["failed"] == 0
        assert resolve(client, query)[0] == old_id


def test_durable_binding_failure_blocks_union_without_stopping_public(tmp_path):
    republish(tmp_path, batch(posting("one")))
    published, public_calls = [], []

    def guard(_):
        raise RuntimeError("binding database unavailable")

    runner = IntakeRunner(
        IntakeConfig(
            schema_version="c-intake-config/v1",
            job_roots=(tmp_path,),
            criteria=(criteria(),),
        ),
        job_sink=lambda *args: published.append(args),
        job_set_sink=lambda *args: published.append(args),
        job_input_guard=guard,
        public_sinks=(lambda: public_calls.append(True) or {"status": "COMPLETED"},),
    )
    assert runner.poll_once()["failed"] == 1
    assert runner.current_job_result(criteria()) is None
    assert not published
    assert public_calls == [True]
