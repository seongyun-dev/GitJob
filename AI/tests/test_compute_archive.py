"""Archive endpoint consumes checked bytes and persisted public snapshots."""

# ruff: noqa: F811 -- pytest discovers the imported client fixture.

import hashlib
import json
import os

import pytest
from test_compute_api import PREFIX, REGISTRY, client, event, snapshot_ref  # noqa: F401
from test_trend_archive import _metadata, _public, _record

from worker.archive_input import (
    MAX_TOTAL_ACTIVITY_BYTES,
    MAX_TOTAL_ACTIVITY_ROWS,
    ArchiveInputBudget,
    ArchiveInputReference,
    ArchiveInputUnavailable,
    verified_activity_rows,
)
from worker.store import Artifact, ComputeStore


def archive_request(tmp_path, monkeypatch):
    monkeypatch.setenv("C_ARCHIVE_ACTIVITY_ROOT", str(tmp_path))
    raw = (
        json.dumps(
            {
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "period": "2026-08",
                "event_count": 12,
            }
        )
        + "\n"
    ).encode()
    (tmp_path / "activity.ndjson").write_bytes(raw)
    metadata = _metadata("2026-08", selected_repo_count=1).model_copy(
        update={"source_hash": hashlib.sha256(raw).hexdigest()}
    )
    public = _public(REGISTRY, (_record(1, tech_ids=("react",)),))
    artifact = Artifact(
        "PUBLIC_GITHUB", None, public.model_dump(mode="json"), "test-archive-public"
    )
    db = ComputeStore(os.environ["C_COMPUTE_TEST_DATABASE_URL"])
    request = event()
    from datetime import datetime

    ticket = db.claim(
        event_id=request["event_id"],
        kind="PUBLIC_REPO",
        owner=None,
        occurred_at=datetime.fromisoformat(request["occurred_at"]),
        request={"source": "test"},
    )
    db.complete(ticket, [artifact])
    return event(
        tech_id="react",
        periods=["2026-08"],
        granularity="MONTH",
        inputs=[
            {
                "metadata": metadata.model_dump(mode="json"),
                "public_snapshot_id": artifact.snapshot_id,
                "activity_path": "activity.ndjson",
            }
        ],
    )


def historical_archive_request(tmp_path, monkeypatch, *, sha_source="MONTH_EVENT_SHA"):
    request = archive_request(tmp_path, monkeypatch)
    commit_sha = "1".rjust(40, "0")
    a_snapshot = {
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
        "records": [
            {
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
                "monthly_event_sha": (
                    commit_sha if sha_source == "MONTH_EVENT_SHA" else None
                ),
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
        ],
    }
    a_snapshot_bytes = json.dumps(
        a_snapshot, sort_keys=True, separators=(",", ":")
    ).encode()
    (tmp_path / "a-snapshot.json").write_bytes(a_snapshot_bytes)
    request["archive_version"] = "v2"
    request["inputs"][0].update(
        {
            "a_snapshot_path": "a-snapshot.json",
            "a_snapshot_uri": "hdfs:///gitjob/repo_snapshot/2026-08/snapshot.json",
            "a_snapshot_sha256": hashlib.sha256(a_snapshot_bytes).hexdigest(),
        }
    )
    return request


def test_archive_completed_stores_trend_with_original_public_reference(
    client, tmp_path, monkeypatch
):
    request = archive_request(tmp_path, monkeypatch)
    response = client.post(PREFIX + "/archive-trends/completed", json=request)
    sid = snapshot_ref(response, "TREND")
    result = client.get(PREFIX + f"/snapshots/{sid}").json()["data"]["payload"]
    assert result["points"][0]["event_count"] == 12
    assert (
        result["points"][0]["public_snapshot_uri"]
        == "c-compute://snapshot/" + request["inputs"][0]["public_snapshot_id"]
    )
    assert (
        client.post(PREFIX + "/archive-trends/completed", json=request).json()
        == response.json()
    )


def test_historical_archive_v2_api_stores_monthly_head_payload(
    client, tmp_path, monkeypatch
):
    request = historical_archive_request(tmp_path, monkeypatch)

    response = client.post(PREFIX + "/archive-trends/completed", json=request)
    sid = snapshot_ref(response, "TREND")
    payload = client.get(PREFIX + f"/snapshots/{sid}").json()["data"]["payload"]

    assert payload["schema_version"] == "c-gharchive-historical-trend/v2"
    assert payload["points"][0]["event_count"] == 12
    assert payload["points"][0]["historical_head_repo_coverage"] == 1
    assert (
        client.post(PREFIX + "/archive-trends/completed", json=request).json()
        == response.json()
    )


def test_historical_archive_v2_api_rejects_a_snapshot_tampering(
    client, tmp_path, monkeypatch
):
    request = historical_archive_request(tmp_path, monkeypatch)
    (tmp_path / "a-snapshot.json").write_text("{}", encoding="utf-8")

    response = client.post(PREFIX + "/archive-trends/completed", json=request)

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


def test_archive_rejects_tampering_and_unknown_public_snapshot(
    client, tmp_path, monkeypatch
):
    request = archive_request(tmp_path, monkeypatch)
    (tmp_path / "activity.ndjson").write_text("{}\n", encoding="utf-8")
    assert (
        client.post(PREFIX + "/archive-trends/completed", json=request).status_code
        == 422
    )
    request = archive_request(tmp_path, monkeypatch)
    request["inputs"][0]["public_snapshot_id"] = "c-" + "f" * 64
    assert (
        client.post(PREFIX + "/archive-trends/completed", json=request).status_code
        == 404
    )


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.ndjson",
        "C:/secret.ndjson",
        "sub/../../outside.ndjson",
        "/absolute.ndjson",
        "sub\\file.ndjson",
    ],
)
def test_archive_export_rejects_unsafe_paths(tmp_path, relative):
    reference = ArchiveInputReference(
        metadata=_metadata("2026-08"),
        public_snapshot_id="c-" + "a" * 64,
        activity_path=relative,
    )
    with pytest.raises(ValueError):
        verified_activity_rows(reference, tmp_path)


def test_archive_input_budget_supports_the_six_month_mvp_and_rejects_overage():
    budget = ArchiveInputBudget()
    for row_count in (10_000, 10_000, 10_000, 10_000, 10_000, 20_000):
        budget = budget.include(byte_count=4 * 1024 * 1024, row_count=row_count)

    assert budget.row_count == 70_000
    assert budget.byte_count == 24 * 1024 * 1024
    assert MAX_TOTAL_ACTIVITY_ROWS >= budget.row_count
    assert MAX_TOTAL_ACTIVITY_BYTES >= budget.byte_count
    with pytest.raises(ValueError, match="total row limit"):
        ArchiveInputBudget(row_count=MAX_TOTAL_ACTIVITY_ROWS).include(
            byte_count=1, row_count=1
        )
    with pytest.raises(ValueError, match="total byte limit"):
        ArchiveInputBudget(byte_count=MAX_TOTAL_ACTIVITY_BYTES).include(
            byte_count=1, row_count=0
        )


def test_missing_archive_mount_is_retryable_operational_failure(tmp_path):
    reference = ArchiveInputReference(
        metadata=_metadata("2026-08"),
        public_snapshot_id="c-" + "a" * 64,
        activity_path="activity.ndjson",
    )

    with pytest.raises(ArchiveInputUnavailable) as raised:
        verified_activity_rows(reference, tmp_path / "missing-root")

    assert raised.value.activity_path == "activity.ndjson"
    assert raised.value.error_type == "FileNotFoundError"
    assert raised.value.errno is not None


def test_malformed_archive_bytes_remain_invalid_input(client, tmp_path, monkeypatch):
    request = archive_request(tmp_path, monkeypatch)
    malformed = b"\xff\n"
    (tmp_path / "activity.ndjson").write_bytes(malformed)
    request["inputs"][0]["metadata"]["source_hash"] = hashlib.sha256(
        malformed
    ).hexdigest()

    response = client.post(PREFIX + "/archive-trends/completed", json=request)

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


def test_missing_archive_mount_returns_retryable_503(client, tmp_path, monkeypatch):
    request = archive_request(tmp_path, monkeypatch)
    monkeypatch.setenv("C_ARCHIVE_ACTIVITY_ROOT", str(tmp_path / "missing-root"))

    response = client.post(PREFIX + "/archive-trends/completed", json=request)

    assert response.status_code == 503
    assert response.json()["code"] == "ARCHIVE_INPUT_UNAVAILABLE"
    monkeypatch.setenv("C_ARCHIVE_ACTIVITY_ROOT", str(tmp_path))
    retry = client.post(PREFIX + "/archive-trends/completed", json=request)
    snapshot_id = snapshot_ref(retry, "TREND")
    assert client.get(PREFIX + f"/snapshots/{snapshot_id}").status_code == 200


def test_archive_request_rejects_the_whole_cumulative_row_overage(
    client, tmp_path, monkeypatch
):
    from worker import archive_input

    request = archive_request(tmp_path, monkeypatch)
    march_raw = (
        json.dumps(
            {
                "repo_id": 1,
                "repo_name": "owner/repo-1",
                "period": "2026-03",
                "event_count": 12,
            }
        )
        + "\n"
    ).encode()
    (tmp_path / "march.ndjson").write_bytes(march_raw)
    march_metadata = _metadata("2026-03", selected_repo_count=1).model_copy(
        update={"source_hash": hashlib.sha256(march_raw).hexdigest()}
    )
    august = request["inputs"][0]
    request["periods"] = ["2026-03", "2026-08"]
    request["inputs"] = [
        {
            "metadata": march_metadata.model_dump(mode="json"),
            "public_snapshot_id": august["public_snapshot_id"],
            "activity_path": "march.ndjson",
        },
        august,
    ]
    monkeypatch.setattr(archive_input, "MAX_TOTAL_ACTIVITY_ROWS", 1)

    response = client.post(PREFIX + "/archive-trends/completed", json=request)

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


def test_exporter_output_is_consumed_without_rewriting_metadata(
    client, tmp_path, monkeypatch
):
    from test_export_c_archive_activity import write_bounded_export

    request = archive_request(tmp_path, monkeypatch)
    exported = tmp_path / "exported"
    write_bounded_export(
        exported,
        ({"repo_id": 1, "repo_name": "owner/repo-1", "event_count": 12},),
        request["inputs"][0]["metadata"],
        output_format="ndjson",
    )
    request["inputs"][0]["metadata"] = json.loads(
        (exported / "metadata.json").read_bytes()
    )
    request["inputs"][0]["activity_path"] = "exported/activity.ndjson"
    snapshot_ref(
        client.post(PREFIX + "/archive-trends/completed", json=request), "TREND"
    )


def test_valid_hash_does_not_allow_malformed_activity_rows(
    client, tmp_path, monkeypatch
):
    request = archive_request(tmp_path, monkeypatch)
    malformed = b"{}\n"
    (tmp_path / "activity.ndjson").write_bytes(malformed)
    request["inputs"][0]["metadata"]["source_hash"] = hashlib.sha256(
        malformed
    ).hexdigest()
    response = client.post(PREFIX + "/archive-trends/completed", json=request)
    assert response.status_code == 422
