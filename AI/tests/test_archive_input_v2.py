import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_compute_api import PREFIX, REGISTRY, TOKEN, event, snapshot_ref
from test_compute_matching import MemoryStore
from test_trend_archive import _metadata, _public, _record
from worker.api import archive_compute_versions, create_compute_app
from worker.archive_input import ArchiveTrendFields, build_archive_artifact
from worker.store import Artifact, digest


def _historical_event(
    tmp_path, monkeypatch, *, sha_source="MONTH_EVENT_SHA", published_wrapper=False
):
    monkeypatch.setenv("C_ARCHIVE_ACTIVITY_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "C_ARCHIVE_A_SNAPSHOT_URI_ROOT", "hdfs:///gitjob/repo_snapshot/2026-08"
    )
    activity_bytes = (
        json.dumps(
            {
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "period": "2026-08",
                "event_count": 12,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    (tmp_path / "activity.ndjson").write_bytes(activity_bytes)
    commit_sha = "1".rjust(40, "0")
    lineage = {
        "repo_snapshot_id": "repo-snapshot-1",
        "github_repo_id": 1,
        "repo_full_name": "owner/repo-1",
        "activity_metric": "gh_archive_event_count",
        "activity_period_start": "2026-08-01",
        "activity_period_end": "2026-08-31",
        "activity_count": 1,
        "activity_rank": 1,
        "pinned_commit_sha": commit_sha,
        "tree_sha": None,
        "collection_status": "COMPLETE",
        "collection_issues": [],
        "checkpoint_uri": None,
        "reused_from_snapshot_id": None,
        "tree_truncated": False,
        "observed_tree_entries": 1,
        "artifacts": [],
        "selected_commit_sha": commit_sha,
        "sha_source": sha_source,
        "monthly_event_sha": commit_sha if sha_source == "MONTH_EVENT_SHA" else None,
        "current_default_head": (
            commit_sha if sha_source == "CURRENT_DEFAULT_HEAD" else None
        ),
        "sha_fallback_reason": (
            "MONTH_EVENT_SHA_NOT_AVAILABLE"
            if sha_source == "CURRENT_DEFAULT_HEAD"
            else None
        ),
        "target_period": "2026-08-01/2026-08-31",
    }
    a_snapshot_bytes = json.dumps(
        {
            "schema_version": "github-repo-snapshot/v1",
            "dataset_snapshot_id": "public-snapshot",
            "pipeline_run_id": "public-run",
            "collector_version": "collector-v1",
            "generated_at": "2026-09-11T00:00:00Z",
            "collection_policy": {
                "policy_version": "policy-v1",
                "top_n_limit": 10_000,
                "max_api_calls": 30_000,
                "max_runtime_seconds": 3_600,
                "max_tree_entries": 100_000,
                "max_artifact_files": 100,
                "max_artifact_bytes": 10_485_760,
            },
            "records": [lineage],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    (tmp_path / "a-snapshot.json").write_bytes(a_snapshot_bytes)
    public = _public(REGISTRY, (_record(1, tech_ids=("react",)),))
    public_payload = public.model_dump(mode="json")
    if published_wrapper:
        public_payload = {
            "schema_version": "c-public-published-result/v1",
            "publication": {
                "source_root": "hdfs:///gitjob/analysis_input/github/repo_snapshot",
                "source_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "summary_sha256": "c" * 64,
                "failures_sha256": "d" * 64,
                "quality": {},
                "pipeline_id": "public-pipeline-test",
            },
            "result": public_payload,
        }
    public_artifact = Artifact("PUBLIC_GITHUB", None, public_payload, "public-test")
    event = ArchiveTrendFields.model_validate(
        {
            "archive_version": "v2",
            "tech_id": "react",
            "periods": ["2026-08"],
            "granularity": "MONTH",
            "inputs": [
                {
                    "metadata": _metadata("2026-08", selected_repo_count=1).model_copy(
                        update={
                            "source_hash": hashlib.sha256(activity_bytes).hexdigest()
                        }
                    ),
                    "public_snapshot_id": public_artifact.snapshot_id,
                    "activity_path": "activity.ndjson",
                    "a_snapshot_path": "a-snapshot.json",
                    "a_snapshot_uri": "hdfs:///gitjob/repo_snapshot/2026-08/a-snapshot.json",
                    "a_snapshot_sha256": hashlib.sha256(a_snapshot_bytes).hexdigest(),
                }
            ],
        }
    )

    def snapshot(snapshot_id, owner, kind):
        assert (snapshot_id, owner, kind) == (
            public_artifact.snapshot_id,
            None,
            "PUBLIC_GITHUB",
        )
        return {"payload": public_artifact.payload}

    return event, snapshot, public_artifact


def test_v1_request_shape_remains_valid_without_archive_version():
    event = ArchiveTrendFields.model_validate(
        {
            "tech_id": "react",
            "periods": ["2026-08"],
            "granularity": "MONTH",
            "inputs": [
                {
                    "metadata": _metadata("2026-08").model_dump(mode="json"),
                    "public_snapshot_id": "c-" + "a" * 64,
                    "activity_path": "activity.ndjson",
                }
            ],
        }
    )

    assert event.archive_version == "v1"
    assert "archive_version" not in event.model_dump(mode="json", exclude_defaults=True)


def test_archive_compute_versions_separates_v1_and_v2_algorithms():
    v1 = archive_compute_versions("v1", REGISTRY)
    v2 = archive_compute_versions("v2", REGISTRY)

    assert v1["archive_trend"] == "c-gharchive-current-evidence-join/v1"
    assert v2["archive_trend"] == "c-gharchive-monthly-push-head-join/v2"
    assert {key: value for key, value in v1.items() if key != "archive_trend"} == {
        key: value for key, value in v2.items() if key != "archive_trend"
    }


def test_v2_request_requires_a_snapshot_reference():
    with pytest.raises(ValidationError, match="A snapshot"):
        ArchiveTrendFields.model_validate(
            {
                "archive_version": "v2",
                "tech_id": "react",
                "periods": ["2026-08"],
                "granularity": "MONTH",
                "inputs": [
                    {
                        "metadata": _metadata("2026-08").model_dump(mode="json"),
                        "public_snapshot_id": "c-" + "a" * 64,
                        "activity_path": "activity.ndjson",
                    }
                ],
            }
        )


def test_v2_worker_builds_historical_trend_artifact(tmp_path, monkeypatch):
    event, snapshot, _ = _historical_event(tmp_path, monkeypatch)

    artifact = build_archive_artifact(event, registry=REGISTRY, snapshot=snapshot)

    assert artifact.kind == "TREND"
    assert artifact.payload["schema_version"] == "c-gharchive-historical-trend/v2"
    assert artifact.payload["points"][0]["event_count"] == 12
    assert artifact.payload["points"][0]["a_snapshot_hash"] == (
        event.inputs[0].a_snapshot_sha256
    )


def test_worker_reads_the_provenance_wrapped_public_pipeline_result(
    tmp_path, monkeypatch
):
    event, snapshot, public_artifact = _historical_event(
        tmp_path, monkeypatch, published_wrapper=True
    )

    artifact = build_archive_artifact(event, registry=REGISTRY, snapshot=snapshot)

    point = artifact.payload["points"][0]
    assert point["event_count"] == 12
    assert point["public_snapshot_hash"] == digest(public_artifact.payload)
    assert point["public_snapshot_uri"].endswith(public_artifact.snapshot_id)


def test_worker_preserves_a_legacy_public_snapshot_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("C_ARCHIVE_ACTIVITY_ROOT", str(tmp_path))
    public_payload = json.loads(
        Path("github/fixtures/public_repo_analysis_v1_base_3a4c57c.json").read_bytes()
    )
    public_artifact = Artifact("PUBLIC_GITHUB", None, public_payload, "legacy")
    activity_bytes = (
        json.dumps(
            {
                "repo_id": 100001,
                "repo_name": "fixture-owner/complete-repository",
                "period": "2026-08",
                "event_count": 5,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    (tmp_path / "legacy-activity.ndjson").write_bytes(activity_bytes)
    event = ArchiveTrendFields.model_validate(
        {
            "tech_id": "react",
            "periods": ["2026-08"],
            "granularity": "MONTH",
            "inputs": [
                {
                    "metadata": _metadata(
                        "2026-08", selected_repo_count=1, selected_event_count=5
                    ).model_copy(
                        update={
                            "source_hash": hashlib.sha256(activity_bytes).hexdigest()
                        }
                    ),
                    "public_snapshot_id": public_artifact.snapshot_id,
                    "activity_path": "legacy-activity.ndjson",
                }
            ],
        }
    )
    legacy_registry = REGISTRY.model_copy(
        update={"registry_version": public_payload["registry_version"]}
    )

    artifact = build_archive_artifact(
        event,
        registry=legacy_registry,
        snapshot=lambda snapshot_id, owner, kind: {"payload": public_artifact.payload},
    )

    point = artifact.payload["points"][0]
    assert point["public_snapshot_uri"].endswith(public_artifact.snapshot_id)
    assert point["public_snapshot_hash"] == digest(public_payload)


def test_v1_worker_stream_identity_does_not_gain_a_version_field(tmp_path, monkeypatch):
    event, snapshot, _ = _historical_event(tmp_path, monkeypatch)
    event = ArchiveTrendFields.model_validate(
        {
            **event.model_dump(mode="json"),
            "archive_version": "v1",
            "inputs": [
                {
                    "metadata": event.inputs[0].metadata.model_dump(mode="json"),
                    "public_snapshot_id": event.inputs[0].public_snapshot_id,
                    "activity_path": event.inputs[0].activity_path,
                }
            ],
        }
    )

    artifact = build_archive_artifact(event, registry=REGISTRY, snapshot=snapshot)

    assert artifact.stream == digest(
        {
            "source": "GH_ARCHIVE",
            "tech_id": "react",
            "periods": ("2026-08",),
            "granularity": "MONTH",
            "include_partial": False,
            "registry": REGISTRY.registry_version,
            "algorithm": "c-gharchive-current-evidence-join/v1",
        }
    )


def test_v2_worker_excludes_current_head_fallback(tmp_path, monkeypatch):
    event, snapshot, _ = _historical_event(
        tmp_path, monkeypatch, sha_source="CURRENT_DEFAULT_HEAD"
    )

    point = build_archive_artifact(event, registry=REGISTRY, snapshot=snapshot).payload[
        "points"
    ][0]

    assert point["event_count"] is None
    assert point["historical_head_unavailable_repo_count"] == 1
    assert "HISTORICAL_HEAD_UNAVAILABLE" in point["quality_reasons"]


@pytest.mark.parametrize(
    "unsafe_path",
    ["../a-snapshot.json", "C:/a-snapshot.json", "/a-snapshot.json", "sub\\a.json"],
)
def test_v2_worker_rejects_unsafe_a_snapshot_paths(tmp_path, monkeypatch, unsafe_path):
    event, snapshot, _ = _historical_event(tmp_path, monkeypatch)
    event = event.model_copy(
        update={
            "inputs": (
                event.inputs[0].model_copy(update={"a_snapshot_path": unsafe_path}),
            )
        }
    )

    with pytest.raises(ValueError, match="safe relative"):
        build_archive_artifact(event, registry=REGISTRY, snapshot=snapshot)


def test_v2_worker_rejects_a_snapshot_uri_unbound_to_staged_bytes(
    tmp_path, monkeypatch
):
    event, snapshot, _ = _historical_event(tmp_path, monkeypatch)
    event = event.model_copy(
        update={
            "inputs": (
                event.inputs[0].model_copy(
                    update={
                        "a_snapshot_uri": "hdfs:///gitjob/repo_snapshot/2026-08/other.json"
                    }
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="does not match trusted staging path"):
        build_archive_artifact(event, registry=REGISTRY, snapshot=snapshot)


def test_archive_endpoint_keeps_v1_and_stores_v2_with_memory_store(
    tmp_path, monkeypatch
):
    historical_fields, _, public_artifact = _historical_event(tmp_path, monkeypatch)
    store = MemoryStore()
    store.snapshots[public_artifact.snapshot_id] = {
        "snapshot_id": public_artifact.snapshot_id,
        "kind": "PUBLIC_GITHUB",
        "owner": None,
        "payload": public_artifact.payload,
    }
    app = create_compute_app(store=store, token=TOKEN, registry=REGISTRY)

    historical_input = historical_fields.inputs[0]
    current_fields = ArchiveTrendFields.model_validate(
        {
            "tech_id": historical_fields.tech_id,
            "periods": historical_fields.periods,
            "granularity": historical_fields.granularity,
            "inputs": [
                {
                    "metadata": historical_input.metadata.model_dump(mode="json"),
                    "public_snapshot_id": historical_input.public_snapshot_id,
                    "activity_path": historical_input.activity_path,
                }
            ],
        }
    )
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        current_response = client.post(
            PREFIX + "/archive-trends/completed",
            json=event(**current_fields.model_dump(mode="json", exclude_defaults=True)),
        )
        current_id = snapshot_ref(current_response, "TREND")
        historical_response = client.post(
            PREFIX + "/archive-trends/completed",
            json=event(**historical_fields.model_dump(mode="json")),
        )
        historical_id = snapshot_ref(historical_response, "TREND")

    assert store.snapshots[current_id]["payload"]["schema_version"] == (
        "c-gharchive-trend/v1"
    )
    assert store.snapshots[historical_id]["payload"]["schema_version"] == (
        "c-gharchive-historical-trend/v2"
    )
    assert store.snapshots[historical_id]["payload"]["points"][0]["event_count"] == 12


def test_archive_endpoint_rejects_abbreviated_a_snapshot(tmp_path, monkeypatch):
    fields, _, public_artifact = _historical_event(tmp_path, monkeypatch)
    a_snapshot = json.loads((tmp_path / "a-snapshot.json").read_bytes())
    del a_snapshot["records"][0]["repo_full_name"]
    abbreviated = json.dumps(a_snapshot, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "a-snapshot.json").write_bytes(abbreviated)
    fields = fields.model_copy(
        update={
            "inputs": (
                fields.inputs[0].model_copy(
                    update={
                        "a_snapshot_sha256": hashlib.sha256(abbreviated).hexdigest()
                    }
                ),
            )
        }
    )
    store = MemoryStore()
    store.snapshots[public_artifact.snapshot_id] = {
        "snapshot_id": public_artifact.snapshot_id,
        "kind": "PUBLIC_GITHUB",
        "owner": None,
        "payload": public_artifact.payload,
    }
    app = create_compute_app(store=store, token=TOKEN, registry=REGISTRY)

    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = client.post(
            PREFIX + "/archive-trends/completed",
            json=event(**fields.model_dump(mode="json")),
        )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


@pytest.mark.parametrize(
    "updates",
    [
        {"sha_fallback_reason": "unexpected fallback"},
        {
            "sha_source": None,
            "selected_commit_sha": "1".rjust(40, "0"),
            "monthly_event_sha": "1".rjust(40, "0"),
        },
    ],
)
def test_archive_endpoint_rejects_invalid_additive_a_lineage(
    tmp_path, monkeypatch, updates
):
    fields, _, public_artifact = _historical_event(tmp_path, monkeypatch)
    a_snapshot = json.loads((tmp_path / "a-snapshot.json").read_bytes())
    a_snapshot["records"][0].update(updates)
    changed = json.dumps(a_snapshot, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "a-snapshot.json").write_bytes(changed)
    fields = fields.model_copy(
        update={
            "inputs": (
                fields.inputs[0].model_copy(
                    update={"a_snapshot_sha256": hashlib.sha256(changed).hexdigest()}
                ),
            )
        }
    )
    store = MemoryStore()
    store.snapshots[public_artifact.snapshot_id] = {
        "snapshot_id": public_artifact.snapshot_id,
        "kind": "PUBLIC_GITHUB",
        "owner": None,
        "payload": public_artifact.payload,
    }
    app = create_compute_app(store=store, token=TOKEN, registry=REGISTRY)

    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = client.post(
            PREFIX + "/archive-trends/completed",
            json=event(**fields.model_dump(mode="json")),
        )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


def test_archive_endpoint_reports_base_snapshot_period_mismatch(tmp_path, monkeypatch):
    fields, _, public_artifact = _historical_event(tmp_path, monkeypatch)
    a_snapshot = json.loads((tmp_path / "a-snapshot.json").read_bytes())
    a_snapshot["records"][0]["activity_period_start"] = "2026-07-01"
    mismatched = json.dumps(a_snapshot, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "a-snapshot.json").write_bytes(mismatched)
    fields = fields.model_copy(
        update={
            "inputs": (
                fields.inputs[0].model_copy(
                    update={"a_snapshot_sha256": hashlib.sha256(mismatched).hexdigest()}
                ),
            )
        }
    )
    store = MemoryStore()
    store.snapshots[public_artifact.snapshot_id] = {
        "snapshot_id": public_artifact.snapshot_id,
        "kind": "PUBLIC_GITHUB",
        "owner": None,
        "payload": public_artifact.payload,
    }
    app = create_compute_app(store=store, token=TOKEN, registry=REGISTRY)

    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = client.post(
            PREFIX + "/archive-trends/completed",
            json=event(**fields.model_dump(mode="json")),
        )

    trend_id = snapshot_ref(response, "TREND")
    point = store.snapshots[trend_id]["payload"]["points"][0]
    assert point["sample_repo_count"] == 0
    assert point["historical_head_mismatch_repo_count"] == 1
    assert "HISTORICAL_HEAD_MISMATCH" in point["quality_reasons"]


@pytest.mark.parametrize("budget", ["bytes", "rows"])
def test_v2_worker_enforces_cumulative_input_budget(tmp_path, monkeypatch, budget):
    from worker import archive_input

    fields, snapshot, _ = _historical_event(tmp_path, monkeypatch)
    if budget == "bytes":
        monkeypatch.setattr(archive_input, "MAX_TOTAL_HISTORICAL_BYTES", 1)
        message = "total byte limit"
    else:
        monkeypatch.setattr(archive_input, "MAX_TOTAL_ACTIVITY_ROWS", 0)
        message = "total row limit"

    with pytest.raises(ValueError, match=message):
        build_archive_artifact(fields, registry=REGISTRY, snapshot=snapshot)


def test_v2_rejects_second_a_snapshot_before_open_when_total_budget_is_exhausted(
    tmp_path, monkeypatch
):
    from worker import archive_input

    fields, snapshot, _ = _historical_event(tmp_path, monkeypatch)
    (tmp_path / "activity-2.ndjson").write_bytes(
        (tmp_path / "activity.ndjson").read_bytes()
    )
    (tmp_path / "a-snapshot-2.json").write_bytes(
        (tmp_path / "a-snapshot.json").read_bytes()
    )
    first = fields.inputs[0]
    second = first.model_copy(
        update={
            "activity_path": "activity-2.ndjson",
            "a_snapshot_path": "a-snapshot-2.json",
        }
    )
    fields = fields.model_copy(update={"inputs": (first, second)})
    total_size = sum(
        (tmp_path / name).stat().st_size
        for name in (
            "activity.ndjson",
            "a-snapshot.json",
            "activity-2.ndjson",
            "a-snapshot-2.json",
        )
    )
    monkeypatch.setattr(archive_input, "MAX_TOTAL_HISTORICAL_BYTES", total_size - 1)
    original_open = Path.open
    second_a_opened = False

    def spy_open(path, *args, **kwargs):
        nonlocal second_a_opened
        if path.name == "a-snapshot-2.json":
            second_a_opened = True
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)

    with pytest.raises(ValueError, match="total byte limit"):
        build_archive_artifact(fields, registry=REGISTRY, snapshot=snapshot)

    assert second_a_opened is False
