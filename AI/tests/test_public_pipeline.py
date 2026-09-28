import hashlib
import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from github import public_pipeline
from github.contracts import GitHubRepoSnapshotBatch
from github.public_analysis import analyze_public_batch
from github.public_pipeline import (
    PipelineBusyError,
    PipelineCheckpointError,
    PipelineExecutionError,
    merge_public_partitions,
    plan_public_pipeline,
    run_public_pipeline,
)
from registry.contracts import TechnologyRegistry
from registry.mapper import RegistryMapper


@pytest.fixture
def mapper():
    return RegistryMapper(
        TechnologyRegistry.model_validate_json(
            Path("registry/data/technology_registry_20260908_1.json").read_bytes()
        )
    )


class Reader:
    def __init__(self, bodies):
        self.bodies = bodies
        self.calls = []
        self.fail_uri = None

    def read(self, uri, *, max_bytes):
        self.calls.append(uri)
        if uri == self.fail_uri:
            raise OSError("temporary transport failure")
        return self.bodies[uri][: max_bytes + 1]


def fixture_batch(count=5):
    payload = json.loads(
        Path("github/fixtures/github_repo_snapshot_v1.json").read_bytes()
    )
    template = payload["records"][0]
    payload["collection_policy"]["top_n_limit"] = max(count, 1)
    payload["records"] = []
    bodies = {}
    for index in range(count):
        row = dict(template)
        row.update(
            repo_snapshot_id=f"fixture-{index}",
            github_repo_id=index + 1,
            repo_full_name=f"fixture-owner/repo-{index}",
            activity_rank=index + 1,
        )
        content = (
            b'{"dependencies":{"react":"1"}}' if index < 2 else b'{"dependencies":{}}'
        )
        uri = f"hdfs://trusted/artifacts/{index}"
        bodies[uri] = content
        row["artifacts"] = [
            {
                "artifact_type": "MANIFEST",
                "path": "package.json",
                "uri": uri,
                "size_bytes": len(content),
                "content_hash": hashlib.sha256(content).hexdigest(),
            }
        ]
        payload["records"].append(row)
    return GitHubRepoSnapshotBatch.model_validate(payload), Reader(bodies)


def test_partition_resume_matches_whole_batch_not_mean_of_ratios(tmp_path, mapper):
    batch, reader = fixture_batch()
    expected = analyze_public_batch(batch, Reader(reader.bodies), mapper)
    first = run_public_pipeline(
        batch, reader, mapper, tmp_path, max_records=2, max_new_partitions=1
    )
    assert first.status == "IN_PROGRESS"
    assert first.completed_partitions == 1
    assert first.result is None and first.final_path is None
    assert not (tmp_path / "final.json").exists()
    assert not (tmp_path / "_SUCCESS.json").exists()
    assert len(reader.calls) == 2

    resumed = run_public_pipeline(batch, reader, mapper, tmp_path, max_records=2)
    assert resumed.status == "COMPLETED"
    assert resumed.reused_partitions == 1
    assert resumed.result == expected
    assert resumed.result.technologies[0].observation_ratio == 2 / 5
    assert len(reader.calls) == 5
    replay = run_public_pipeline(batch, reader, mapper, tmp_path, max_records=2)
    assert replay.result == expected and replay.reused_partitions == 3
    assert len(reader.calls) == 5


def test_plan_preserves_rank_scope_and_both_limits(mapper):
    batch, reader = fixture_batch()
    batch.records = tuple(reversed(batch.records))
    plan = plan_public_pipeline(batch, mapper, max_records=2, max_declared_bytes=60)
    assert plan == plan_public_pipeline(
        batch, mapper, max_records=2, max_declared_bytes=60
    )
    assert [repo for part in plan.partitions for repo in part.github_repo_ids] == list(
        range(1, 6)
    )
    assert all(len(part.github_repo_ids) <= 2 for part in plan.partitions)
    assert all(part.readable_bytes <= 60 for part in plan.partitions)
    assert sum(part.declared_bytes for part in plan.partitions) == sum(
        len(body) for body in reader.bodies.values()
    )
    assert plan.collection_policy == batch.collection_policy


def test_failed_read_retries_only_unfinished_partition(tmp_path, mapper):
    batch, reader = fixture_batch()
    reader.fail_uri = "hdfs://trusted/artifacts/2"
    with pytest.raises(PipelineExecutionError):
        run_public_pipeline(batch, reader, mapper, tmp_path, max_records=2)
    assert not (tmp_path / "_SUCCESS.json").exists()
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_bytes())
    assert list(checkpoint["completed"]) == ["0"]
    assert checkpoint["failure"]["partition_index"] == 1
    reader.fail_uri = None
    result = run_public_pipeline(batch, reader, mapper, tmp_path, max_records=2)
    assert result.result.analyzed_repo_count == 5
    assert reader.calls.count("hdfs://trusted/artifacts/0") == 1
    assert reader.calls.count("hdfs://trusted/artifacts/2") == 2


@pytest.mark.parametrize("target", ["checkpoint.json", "partition-000000.json"])
def test_corrupt_checkpoint_or_completed_output_fails_closed(tmp_path, mapper, target):
    batch, reader = fixture_batch()
    run_public_pipeline(
        batch, reader, mapper, tmp_path, max_records=2, max_new_partitions=1
    )
    (tmp_path / target).write_bytes(b"broken")
    with pytest.raises(PipelineCheckpointError):
        run_public_pipeline(batch, reader, mapper, tmp_path, max_records=2)
    assert len(reader.calls) == 2


@pytest.mark.parametrize("change", ["input", "policy", "partial", "registry", "size"])
def test_changed_identity_cannot_resume(tmp_path, mapper, change):
    batch, reader = fixture_batch()
    run_public_pipeline(batch, reader, mapper, tmp_path, max_new_partitions=0)
    kwargs = {}
    if change == "input":
        batch.pipeline_run_id += "-changed"
    elif change == "policy":
        batch.collection_policy.max_api_calls += 1
    elif change == "partial":
        kwargs["include_partial"] = True
    elif change == "registry":
        mapper.registry_version = "registry-20260909.1"
    else:
        kwargs["max_records"] = 2
    with pytest.raises(PipelineCheckpointError):
        run_public_pipeline(batch, reader, mapper, tmp_path, **kwargs)
    assert reader.calls == []


def test_merge_rejects_duplicate_and_missing_repositories(mapper):
    batch, reader = fixture_batch()
    first = batch.model_copy(update={"records": batch.records[:2]})
    result = analyze_public_batch(first, reader, mapper)
    with pytest.raises(ValueError, match="duplicate"):
        merge_public_partitions(batch, [result, result], mapper)
    with pytest.raises(ValueError, match="coverage"):
        merge_public_partitions(batch, [result], mapper)


def test_empty_batch_publishes_valid_empty_result(tmp_path, mapper):
    batch, reader = fixture_batch(0)
    result = run_public_pipeline(batch, reader, mapper, tmp_path)
    assert result.status == "COMPLETED"
    assert result.result == analyze_public_batch(batch, reader, mapper)
    assert result.result.total_repo_count == 0
    assert result.result.status == "INSUFFICIENT_DATA"


def test_registry_cannot_change_inside_reader_call(tmp_path, mapper):
    batch, reader = fixture_batch(1)

    class MutatingReader:
        def read(self, uri, *, max_bytes):
            mapper.registry_version = "registry-20260909.1"
            return reader.read(uri, max_bytes=max_bytes)

    with pytest.raises(PipelineExecutionError):
        run_public_pipeline(batch, MutatingReader(), mapper, tmp_path)
    assert not (tmp_path / "_SUCCESS.json").exists()


def test_incomplete_state_with_final_marker_fails_before_new_reads(tmp_path, mapper):
    batch, reader = fixture_batch()
    run_public_pipeline(
        batch, reader, mapper, tmp_path, max_records=2, max_new_partitions=1
    )
    (tmp_path / "_SUCCESS.json").write_text("{}")
    with pytest.raises(PipelineCheckpointError):
        run_public_pipeline(batch, reader, mapper, tmp_path, max_records=2)
    assert len(reader.calls) == 2


@pytest.mark.parametrize("filename", ["final.json", "_SUCCESS.json"])
def test_completed_run_revalidates_final_artifact(tmp_path, mapper, filename):
    batch, reader = fixture_batch(1)
    run_public_pipeline(batch, reader, mapper, tmp_path)
    (tmp_path / filename).write_text("{}")
    with pytest.raises(PipelineCheckpointError):
        run_public_pipeline(batch, reader, mapper, tmp_path)
    assert len(reader.calls) == 1


def test_written_but_uncommitted_partition_is_recomputed(tmp_path, mapper, monkeypatch):
    batch, reader = fixture_batch(2)
    original_save = public_pipeline._save

    def interrupted_save(root, checkpoint):
        if checkpoint.completed:
            raise KeyboardInterrupt
        original_save(root, checkpoint)

    with monkeypatch.context() as scoped:
        scoped.setattr(public_pipeline, "_save", interrupted_save)
        with pytest.raises(KeyboardInterrupt):
            run_public_pipeline(batch, reader, mapper, tmp_path)
    assert (tmp_path / "partition-000000.json").exists()
    assert not (tmp_path / "_SUCCESS.json").exists()
    result = run_public_pipeline(batch, reader, mapper, tmp_path)
    assert result.status == "COMPLETED" and result.reused_partitions == 0
    assert len(reader.calls) == 4


def test_interrupted_final_marker_resumes_without_rereading_artifacts(
    tmp_path, mapper, monkeypatch
):
    batch, reader = fixture_batch(1)
    original_write = public_pipeline._atomic_write

    def interrupted_write(root, name, content):
        if name == "_SUCCESS.json":
            raise KeyboardInterrupt
        original_write(root, name, content)

    with monkeypatch.context() as scoped:
        scoped.setattr(public_pipeline, "_atomic_write", interrupted_write)
        with pytest.raises(KeyboardInterrupt):
            run_public_pipeline(batch, reader, mapper, tmp_path)
    assert (tmp_path / "final.json").exists()
    assert not (tmp_path / "_SUCCESS.json").exists()
    result = run_public_pipeline(batch, reader, mapper, tmp_path)
    assert result.status == "COMPLETED" and len(reader.calls) == 1


def test_second_concurrent_runner_cannot_read_or_write(tmp_path, mapper):
    batch, reader = fixture_batch(1)
    started, release = Event(), Event()

    class BlockingReader:
        def read(self, uri, *, max_bytes):
            started.set()
            assert release.wait(5)
            return reader.read(uri, max_bytes=max_bytes)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            run_public_pipeline, batch, BlockingReader(), mapper, tmp_path
        )
        try:
            assert started.wait(5)
            with pytest.raises(PipelineBusyError):
                run_public_pipeline(batch, reader, mapper, tmp_path)
            assert not reader.calls
        finally:
            release.set()
        assert future.result(timeout=5).status == "COMPLETED"


def _hold_process_lock(directory, connection):
    with public_pipeline._directory_lock(Path(directory)):
        connection.send("LOCKED")
        connection.recv()


def test_abrupt_process_exit_releases_os_lock(tmp_path, mapper):
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe()
    process = context.Process(target=_hold_process_lock, args=(str(tmp_path), send))
    process.start()
    batch, reader = fixture_batch(1)
    try:
        assert receive.poll(8)
        assert receive.recv() == "LOCKED"
        with pytest.raises(PipelineBusyError):
            run_public_pipeline(batch, reader, mapper, tmp_path)
    finally:
        process.terminate()
        process.join(timeout=8)
        receive.close()
        send.close()
    assert not process.is_alive()
    assert run_public_pipeline(batch, reader, mapper, tmp_path).status == "COMPLETED"


def test_checkpoint_digest_does_not_replace_input_provenance_validation(
    tmp_path, mapper
):
    batch, reader = fixture_batch(2)
    run_public_pipeline(
        batch, reader, mapper, tmp_path, max_records=1, max_new_partitions=1
    )
    path = tmp_path / "partition-000000.json"
    output = json.loads(path.read_bytes())
    output["records"][0]["pinned_commit_sha"] = "f" * 40
    body = json.dumps(output).encode()
    path.write_bytes(body)
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_bytes())
    checkpoint["completed"]["0"] = hashlib.sha256(body).hexdigest()
    (tmp_path / "checkpoint.json").write_text(json.dumps(checkpoint))
    with pytest.raises(PipelineCheckpointError):
        run_public_pipeline(batch, reader, mapper, tmp_path, max_records=1)
    assert len(reader.calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("selected_commit_sha", "f" * 40),
        (
            "language_metadata",
            [
                {
                    "language": "Python",
                    "file_count": 99,
                    "representative_paths": ["tampered.py"],
                }
            ],
        ),
    ],
)
def test_additive_provenance_tamper_is_rejected_on_resume(
    tmp_path, mapper, field, value
):
    batch, reader = fixture_batch(2)
    payload = batch.model_dump(mode="json")
    commit = payload["records"][0]["pinned_commit_sha"]
    payload["records"][0].update(
        selected_commit_sha=commit,
        sha_source="MONTH_EVENT_SHA",
        monthly_event_sha=commit,
        target_period="2026-08-01/2026-08-31",
        language_metadata=[
            {
                "language": "Python",
                "file_count": 1,
                "representative_paths": ["app.py"],
            }
        ],
    )
    batch = GitHubRepoSnapshotBatch.model_validate(payload)
    run_public_pipeline(
        batch, reader, mapper, tmp_path, max_records=1, max_new_partitions=1
    )
    path = tmp_path / "partition-000000.json"
    output = json.loads(path.read_bytes())
    output["records"][0][field] = value
    body = json.dumps(output).encode()
    path.write_bytes(body)
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_bytes())
    checkpoint["completed"]["0"] = hashlib.sha256(body).hexdigest()
    (tmp_path / "checkpoint.json").write_text(json.dumps(checkpoint))

    with pytest.raises(PipelineCheckpointError):
        run_public_pipeline(batch, reader, mapper, tmp_path, max_records=1)

    assert len(reader.calls) == 1


@pytest.mark.parametrize("include_partial", [False, True])
def test_collection_states_empty_artifacts_and_tree_flags_match_base(
    tmp_path, mapper, include_partial
):
    batch, reader = fixture_batch(5)
    payload = batch.model_dump(mode="json")
    payload["records"][0].update(
        collection_status="FAILED", collection_issues=["ARTIFACT_FETCH_FAILED"]
    )
    payload["records"][1].update(
        collection_status="PARTIAL", collection_issues=["FILE_LIMIT_REACHED"]
    )
    payload["records"][2]["artifacts"] = []
    payload["records"][3].update(
        collection_status="REUSED", reused_from_snapshot_id="prior"
    )
    payload["records"][4]["tree_sha"] = payload["records"][4]["pinned_commit_sha"]
    batch = GitHubRepoSnapshotBatch.model_validate(payload)
    expected = analyze_public_batch(
        batch, Reader(reader.bodies), mapper, include_partial=include_partial
    )
    result = run_public_pipeline(
        batch, reader, mapper, tmp_path, include_partial=include_partial, max_records=2
    )
    assert result.result == expected
    assert "hdfs://trusted/artifacts/0" not in reader.calls
    assert ("hdfs://trusted/artifacts/1" in reader.calls) is include_partial
    assert result.result.records[-1].quality_reasons == ("TREE_SHA_EQUALS_COMMIT_SHA",)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_records": 0},
        {"max_records": True},
        {"max_declared_bytes": 0},
        {"max_declared_bytes": 100_000_001},
        {"max_declared_bytes": 1},
        {"include_partial": 1},
        {"source_sha256": "bad"},
        {"registry_sha256": "bad"},
    ],
)
def test_invalid_plan_config_rejected_without_io(mapper, kwargs):
    batch, reader = fixture_batch(1)
    with pytest.raises(ValueError):
        plan_public_pipeline(batch, mapper, **kwargs)
    assert not reader.calls


def test_mutated_input_duplicate_is_revalidated_before_checkpoint(tmp_path, mapper):
    batch, reader = fixture_batch(2)
    batch.records = (batch.records[0], batch.records[0])
    with pytest.raises(ValueError, match="duplicate"):
        run_public_pipeline(batch, reader, mapper, tmp_path)
    assert not (tmp_path / "checkpoint.json").exists()


def test_reader_configuration_error_does_not_become_cached_parser_failure(
    tmp_path, mapper
):
    batch, corrected_reader = fixture_batch(1)

    class WrongNamespace:
        def read(self, uri, *, max_bytes):
            raise ValueError("URI outside configured namespace; no network used")

    with pytest.raises(PipelineExecutionError):
        run_public_pipeline(batch, WrongNamespace(), mapper, tmp_path)
    state = json.loads((tmp_path / "checkpoint.json").read_bytes())
    assert state["completed"] == {}
    result = run_public_pipeline(batch, corrected_reader, mapper, tmp_path)
    assert result.status == "COMPLETED" and result.result.status == "READY"
    assert len(corrected_reader.calls) == 1


def test_hash_verified_malformed_json_remains_nonretryable_quality_failure(
    tmp_path, mapper
):
    batch, reader = fixture_batch(1)
    body = b"{malformed-json"
    artifact = batch.records[0].artifacts[0]
    artifact.size_bytes = len(body)
    artifact.content_hash = hashlib.sha256(body).hexdigest()
    reader.bodies[artifact.uri] = body
    result = run_public_pipeline(batch, reader, mapper, tmp_path)
    assert result.status == "COMPLETED" and result.result.status == "FAILED"
    assert result.result.records[0].artifacts[0].reason == "READ_OR_PARSE_FAILED"
    replay = run_public_pipeline(batch, reader, mapper, tmp_path)
    assert replay.reused_partitions == 1 and len(reader.calls) == 1


@pytest.mark.parametrize("old_version", ["v1", "v2", "v3", "v4", "v5"])
def test_old_parser_checkpoint_is_not_silently_reused_by_v6(
    tmp_path, mapper, old_version
):
    batch, reader = fixture_batch(1)
    run_public_pipeline(batch, reader, mapper, tmp_path, max_new_partitions=0)
    path = tmp_path / "checkpoint.json"
    state = json.loads(path.read_bytes())
    assert state["plan"]["parser_version"] == "c-public-static-observations/v6"
    state["plan"]["parser_version"] = "c-public-static-observations/" + old_version
    path.write_text(json.dumps(state))
    with pytest.raises(PipelineCheckpointError):
        run_public_pipeline(batch, reader, mapper, tmp_path)
    assert reader.calls == []


def test_manifest_parser_identity_is_bound_to_checkpoint(tmp_path, mapper):
    batch, reader = fixture_batch(1)
    run_public_pipeline(batch, reader, mapper, tmp_path, max_new_partitions=0)
    path = tmp_path / "checkpoint.json"
    state = json.loads(path.read_bytes())
    assert (
        state["plan"]["manifest_parser_version"]
        == public_pipeline.PUBLIC_MANIFEST_PARSER_VERSION
    )
    state["plan"]["manifest_parser_version"] = "tampered-manifest-parser/v1"
    path.write_text(json.dumps(state))

    with pytest.raises(PipelineCheckpointError):
        run_public_pipeline(batch, reader, mapper, tmp_path)

    assert reader.calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows transient sharing denial")
@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_atomic_replace_retries_only_three_bounded_windows_attempts(
    tmp_path, monkeypatch, winerror
):
    original = public_pipeline.os.replace
    attempts, sleeps = [], []

    def temporarily_locked(source, destination):
        attempts.append(destination)
        if len(attempts) < 3:
            error = PermissionError("fixture temporary sharing denial")
            error.winerror = winerror
            raise error
        return original(source, destination)

    monkeypatch.setattr(public_pipeline.os, "replace", temporarily_locked)
    monkeypatch.setattr(public_pipeline.time, "sleep", sleeps.append)
    public_pipeline._atomic_write(tmp_path, "checkpoint.json", b"verified")
    assert len(attempts) == 3 and sleeps == [0.05, 0.1]
    assert (tmp_path / "checkpoint.json").read_bytes() == b"verified"


@pytest.mark.skipif(os.name != "nt", reason="Windows transient sharing denial")
def test_persistent_replace_denial_keeps_previous_checkpoint_and_can_resume(
    tmp_path, mapper, monkeypatch
):
    batch, reader = fixture_batch(2)
    run_public_pipeline(
        batch, reader, mapper, tmp_path, max_records=1, max_new_partitions=1
    )
    before = (tmp_path / "checkpoint.json").read_bytes()
    original = public_pipeline.os.replace
    attempts, sleeps = [], []

    def locked_checkpoint(source, destination):
        if destination.name == "checkpoint.json":
            attempts.append(destination)
            error = PermissionError("fixture locked checkpoint")
            error.winerror = 5
            raise error
        return original(source, destination)

    with monkeypatch.context() as scoped:
        scoped.setattr(public_pipeline.os, "replace", locked_checkpoint)
        scoped.setattr(public_pipeline.time, "sleep", sleeps.append)
        with pytest.raises(PermissionError):
            run_public_pipeline(batch, reader, mapper, tmp_path, max_records=1)
    assert len(attempts) == 3 and sleeps == [0.05, 0.1]
    assert (tmp_path / "checkpoint.json").read_bytes() == before
    assert not (tmp_path / "_SUCCESS.json").exists()
    result = run_public_pipeline(batch, reader, mapper, tmp_path, max_records=1)
    assert result.status == "COMPLETED" and result.reused_partitions == 1
    assert reader.calls.count("hdfs://trusted/artifacts/0") == 1


def test_other_replace_error_fails_immediately(tmp_path, monkeypatch):
    attempts, sleeps = [], []

    def invalid_handle(source, destination):
        attempts.append(destination)
        error = OSError("fixture unrelated write failure")
        error.winerror = 6
        raise error

    monkeypatch.setattr(public_pipeline.os, "replace", invalid_handle)
    monkeypatch.setattr(public_pipeline.time, "sleep", sleeps.append)
    with pytest.raises(OSError):
        public_pipeline._atomic_write(tmp_path, "checkpoint.json", b"not published")
    assert len(attempts) == 1 and sleeps == []


def test_non_windows_replace_error_never_uses_windows_retry_policy(
    tmp_path, monkeypatch
):
    attempts, sleeps = [], []

    def denied(source, destination):
        attempts.append(destination)
        error = PermissionError("fixture non-Windows denial")
        error.winerror = 5
        raise error

    source, destination = tmp_path / "source", tmp_path / "destination"
    monkeypatch.setattr(
        public_pipeline, "os", SimpleNamespace(name="posix", replace=denied)
    )
    monkeypatch.setattr(public_pipeline.time, "sleep", sleeps.append)
    with pytest.raises(PermissionError):
        public_pipeline._replace_file(source, destination)
    assert len(attempts) == 1 and sleeps == []
