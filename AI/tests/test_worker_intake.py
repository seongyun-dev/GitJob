"""Completed producer output is consumed automatically, safely and repeatably."""

import json
from hashlib import sha256

import pytest
from test_job_cohort import batch, criteria, posting

from worker.intake import IntakeConfig, IntakeRunner, load_job_output


def output(root, *, name="run-1", mutate=None):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    value = batch(posting("one")).model_copy(
        update={"pipeline_run_id": name, "dataset_snapshot_id": name}
    )
    manifest = {
        "schema_version": value.schema_version,
        "dataset_snapshot_id": value.dataset_snapshot_id,
        "pipeline_run_id": value.pipeline_run_id,
        "collector_version": value.collector_version,
        "source_site": value.records[0].source_site,
        "collected_at": value.records[0].collected_at.isoformat(),
        "counts": {"records": 1},
        "stopped_reason": None,
        "outputs": {"job_analysis_input.json": "job_analysis_input.json"},
    }
    if mutate:
        mutate(manifest)
    (folder / "job_analysis_input.json").write_text(
        value.model_dump_json(), encoding="utf-8"
    )
    manifest["output_sha256"] = {
        "job_analysis_input.json": sha256(
            (folder / "job_analysis_input.json").read_bytes()
        ).hexdigest()
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder, value, manifest


def config(root):
    return IntakeConfig.model_validate(
        {
            "schema_version": "c-intake-config/v1",
            "job_roots": [str(root)],
            "criteria": [criteria().model_dump(mode="json")],
            "poll_seconds": 1,
        }
    )


def test_load_only_matching_completed_pair(tmp_path):
    folder, value, _ = output(tmp_path)
    loaded = load_job_output(folder / "manifest.json", tmp_path)
    assert loaded.batch == value
    assert len(loaded.batch_sha256) == 64
    assert len(loaded.manifest_sha256) == 64


def test_unbound_legacy_manifest_is_inspectable_but_never_auto_published(tmp_path):
    folder, _, manifest = output(tmp_path)
    manifest.pop("output_sha256")
    (folder / "manifest.json").write_text(json.dumps(manifest))
    assert load_job_output(folder / "manifest.json", tmp_path).collection_issues == (
        "UNBOUND_LEGACY_MANIFEST",
    )
    sink = Sink()
    assert IntakeRunner(config(tmp_path), job_sink=sink).poll_once()["blocked"] == 1
    assert not sink.calls


@pytest.mark.parametrize(
    "field",
    ["outputs", "source", "collection", "counts", "stats", "listing_date_labels"],
)
def test_malformed_nested_manifest_does_not_stop_other_completed_inputs(
    tmp_path, field
):
    output(tmp_path, name="a-invalid", mutate=lambda m: m.update({field: []}))
    output(tmp_path, name="b-valid")
    sink = Sink()
    report = IntakeRunner(config(tmp_path), job_sink=sink).poll_once()
    assert report["failed"] == 1
    assert report["completed"] == 1
    assert len(sink.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m.update(pipeline_run_id="another"),
        lambda m: m.update(dataset_snapshot_id="another"),
        lambda m: m.update(collector_version="another"),
        lambda m: m.update(source_site="another"),
        lambda m: m.update(collected_at="2026-09-08"),
        lambda m: m["counts"].update(records=2),
        lambda m: m["counts"].update(records=True),
        lambda m: m["outputs"].update({"job_analysis_input.json": "../escape.json"}),
    ],
)
def test_reject_inconsistent_or_escaping_pair(tmp_path, change):
    folder, _, _ = output(tmp_path, mutate=change)
    with pytest.raises(ValueError):
        load_job_output(folder / "manifest.json", tmp_path)


def test_partial_collector_failure_is_retained_not_silently_ready(tmp_path):
    folder, _, _ = output(tmp_path, mutate=lambda m: m.update(stopped_reason="blocked"))
    loaded = load_job_output(folder / "manifest.json", tmp_path)
    assert loaded.collection_issues == ("COLLECTOR_STOPPED_EARLY",)


class Sink:
    def __init__(self):
        self.calls = []
        self.fail = False

    def __call__(self, loaded, cohort_criteria):
        self.calls.append((loaded.batch_sha256, cohort_criteria))
        if self.fail:
            raise ConnectionError("test unavailable")
        return {"status": "COMPLETED", "results": []}


def test_poll_skips_unfinished_and_consumes_newly_completed_output(tmp_path):
    folder, _, _ = output(tmp_path)
    manifest = folder / "manifest.json"
    text = manifest.read_text()
    manifest.unlink()
    sink = Sink()
    runner = IntakeRunner(config(tmp_path), job_sink=sink)
    assert runner.poll_once()["completed"] == 0
    manifest.write_text(text)
    assert runner.poll_once()["completed"] == 1
    assert runner.poll_once()["completed"] == 0
    assert len(sink.calls) == 1


def test_failures_retry_without_blocking_later_inputs(tmp_path):
    output(tmp_path)
    sink = Sink()
    sink.fail = True
    runner = IntakeRunner(config(tmp_path), job_sink=sink)
    assert runner.poll_once()["failed"] == 1
    sink.fail = False
    assert runner.poll_once()["completed"] == 1
    assert len(sink.calls) == 2
    # Restart retries the identical immutable event; durable DB claim deduplicates it.
    assert IntakeRunner(config(tmp_path), job_sink=sink).poll_once()["completed"] == 1


def test_changed_batch_is_not_skipped_by_path_only_cache(tmp_path):
    folder, value, manifest = output(tmp_path)
    sink = Sink()
    runner = IntakeRunner(config(tmp_path), job_sink=sink)
    runner.poll_once()
    data = value.model_dump(mode="json")
    data["records"][0]["title"] = "New title"
    (folder / "job_analysis_input.json").write_text(json.dumps(data))
    assert runner.poll_once()["failed"] == 1
    manifest["output_sha256"]["job_analysis_input.json"] = sha256(
        (folder / "job_analysis_input.json").read_bytes()
    ).hexdigest()
    (folder / "manifest.json").write_text(json.dumps(manifest))
    assert runner.poll_once()["completed"] == 1
    assert sink.calls[0][0] != sink.calls[1][0]


def test_symlink_input_and_outside_root_rejected(tmp_path):
    folder, _, _ = output(tmp_path)
    with pytest.raises((ValueError, FileNotFoundError)):
        load_job_output(folder / "manifest.json", tmp_path / "another")


def test_background_loop_stops_and_runs_without_manual_poll(tmp_path):
    from threading import Event

    output(tmp_path)
    called = Event()

    def sink(*args):
        called.set()
        return {"status": "COMPLETED", "results": []}

    runner = IntakeRunner(config(tmp_path), job_sink=sink)
    runner.start()
    assert called.wait(3)
    runner.stop()
    assert not runner.running


def test_config_requires_explicit_existing_roots_and_criteria(tmp_path):
    with pytest.raises(ValueError):
        config(tmp_path / "missing")
    with pytest.raises(ValueError):
        IntakeConfig.model_validate({"schema_version": "c-intake-config/v1"})


def test_blocked_collection_and_mixed_posting_dates_not_published(tmp_path):
    folder, _, manifest = output(
        tmp_path, mutate=lambda m: m.update(stopped_reason="blocked")
    )
    sink = Sink()
    runner = IntakeRunner(config(tmp_path), job_sink=sink)
    assert runner.poll_once()["blocked"] == 1
    assert not sink.calls
    manifest["stopped_reason"] = None
    manifest["listing_date_labels"] = {"수정일": 1}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    constrained = config(tmp_path).model_dump(mode="json")
    constrained["criteria"][0]["posted_from"] = "2026-09-01T00:00:00Z"
    runner = IntakeRunner(IntakeConfig.model_validate(constrained), job_sink=sink)
    assert runner.poll_once()["blocked"] == 1
    assert not sink.calls


def test_changed_manifest_during_read_rejected(tmp_path, monkeypatch):
    from worker import intake

    folder, _, _ = output(tmp_path)
    original = intake._read
    count = 0

    def changing(path, maximum):
        nonlocal count
        raw = original(path, maximum)
        count += 1
        if count == 2:
            (folder / "manifest.json").write_text("{}")
        return raw

    monkeypatch.setattr(intake, "_read", changing)
    with pytest.raises(ValueError, match="changed"):
        load_job_output(folder / "manifest.json", tmp_path)


def test_jobkorea_completed_manifest_uses_existing_nested_contract(tmp_path):
    folder, value, _ = output(tmp_path)
    data = value.model_dump(mode="json")
    data["records"][0]["source_site"] = "JOBKOREA"
    (folder / "job_analysis_input_v1.json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    metadata = {
        "source": {"site": "JOBKOREA"},
        "collection": {
            "pipeline_run_id": value.pipeline_run_id,
            "collector_version": value.collector_version,
            "collected_at": value.records[0].collected_at.isoformat(),
        },
        "stats": {"records_written": 1, "stopped_reason": "short_page"},
        "outputs": {"job_analysis_input_v1.json": "job_analysis_input_v1.json"},
        "output_sha256": {
            "job_analysis_input_v1.json": sha256(
                (folder / "job_analysis_input_v1.json").read_bytes()
            ).hexdigest()
        },
    }
    (folder / "manifest.json").write_text(json.dumps(metadata))
    assert load_job_output(folder / "manifest.json", tmp_path).collection_issues == ()


def test_discovery_is_bounded_before_any_computation(tmp_path):
    output(tmp_path)
    output(tmp_path, name="run-2")
    sink = Sink()
    runner = IntakeRunner(
        config(tmp_path).model_copy(update={"max_manifests": 1}), job_sink=sink
    )
    assert runner.poll_once()["failed"] == 1
    assert not sink.calls


def test_actual_app_startup_consumes_to_postgres_and_restart_deduplicates(
    tmp_path, monkeypatch
):
    import os
    from datetime import UTC, datetime
    from threading import Event
    from uuid import uuid4

    from fastapi.testclient import TestClient
    from test_compute_api import REGISTRY, TOKEN

    from worker import intake
    from worker.api import create_compute_app
    from worker.store import ComputeStore, apply_migration

    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires explicit isolated PostgreSQL")
    apply_migration(dsn)
    store = ComputeStore(dsn)
    output(tmp_path, name=uuid4().hex)
    config_path = tmp_path / "intake-config.json"
    query = criteria(as_of=datetime.now(UTC))
    configured = config(tmp_path).model_copy(update={"criteria": (query,)})
    config_path.write_text(configured.model_dump_json(), encoding="utf-8")
    original = intake.publish_job_input_set
    results = []
    completed = Event()

    def recording(*args, **kwargs):
        result = original(*args, **kwargs)
        results.append(result)
        completed.set()
        return result

    monkeypatch.setattr(intake, "publish_job_input_set", recording)
    for _ in range(2):
        completed.clear()
        app = create_compute_app(
            store=store, token=TOKEN, registry=REGISTRY, intake_config=config_path
        )
        with TestClient(app) as client:
            assert completed.wait(5)
            response = client.get(
                "/internal/v1/c/intake/status",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            assert response.status_code == 200
            assert response.json()["data"]["running"]
            resolved = client.post(
                "/internal/v1/c/job-cohorts/resolve",
                json=query.model_dump(mode="json"),
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            assert resolved.status_code == 200
            assert resolved.json()["data"]["cohort_snapshot_id"] == next(
                ref["snapshot_id"]
                for ref in results[-1]["results"]
                if ref["kind"] == "COHORT"
            )
            for ref in results[-1]["results"]:
                saved = store.get_snapshot(ref["snapshot_id"], owner=None)
                assert saved["kind"] in {"COHORT", "DEMAND"}
        assert not app.state.intake_runner.running
    assert len(results) == 2
    assert results[0] == results[1]


def test_public_callbacks_resume_and_do_not_publish_in_progress(tmp_path):
    calls = []

    def public():
        calls.append(True)
        return {
            "status": "IN_PROGRESS" if len(calls) == 1 else "COMPLETED",
            "results": [],
        }

    runner = IntakeRunner(config(tmp_path), job_sink=Sink(), public_sinks=(public,))
    runner.poll_once()
    assert runner.public_reports[0]["status"] == "IN_PROGRESS"
    runner.poll_once()
    assert runner.public_reports[0]["status"] == "COMPLETED"
    runner.poll_once()
    assert len(calls) == 2


def test_public_configuration_is_explicit_and_offline(tmp_path):
    value = IntakeConfig.model_validate(
        {
            "schema_version": "c-intake-config/v1",
            "public_sources": [
                {
                    "root_uri": "hdfs:///gitjob/snapshot/test",
                    "artifact_root_uris": ["hdfs:///gitjob/snapshot/source/artifacts"],
                    "namenode_base_url": "http://hdfs-namenode:9870/webhdfs/v1",
                    "checkpoint_dir": str(tmp_path),
                }
            ],
        }
    )
    assert not value.job_roots
    assert not value.public_sources[0].include_partial
    assert value.public_sources[0].artifact_root_uris == (
        "hdfs:///gitjob/snapshot/source/artifacts",
    )
    raw = value.model_dump(mode="json")
    raw["public_sources"][0]["root_uri"] = "hdfs:///gitjob/../escape"
    with pytest.raises(ValueError):
        IntakeConfig.model_validate(raw)
    raw = value.model_dump(mode="json")
    raw["public_sources"][0]["artifact_root_uris"] = [
        "hdfs://other/gitjob/source/artifacts"
    ]
    with pytest.raises(ValueError, match="configured authority"):
        IntakeConfig.model_validate(raw)


def test_job_discovery_failure_does_not_block_independent_public_source(
    tmp_path, monkeypatch
):
    called = []

    def public():
        called.append(True)
        return {"status": "COMPLETED", "results": []}

    runner = IntakeRunner(config(tmp_path), job_sink=Sink(), public_sinks=(public,))

    def unavailable():
        raise OSError("read-only job mount temporarily unavailable")

    monkeypatch.setattr(runner, "_manifests", unavailable)
    assert runner.poll_once()["failed"] == 1
    assert called == [True]
