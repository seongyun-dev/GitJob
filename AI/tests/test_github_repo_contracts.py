import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from github.contracts import GitHubRepoSnapshotBatch, RepoCollectionStatus

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "github" / "fixtures"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "data"
    / "contracts"
    / "github-repo-snapshot-v1.schema.json"
)
EXPECTED_INVALID_CASE_NAMES = {
    "unsupported_schema_version",
    "missing_pinned_commit_sha",
    "invalid_tree_sha",
    "non_positive_policy_limit",
    "partial_without_issue",
    "rate_limited_without_checkpoint",
    "reused_without_source_snapshot",
    "unsafe_artifact_path",
    "artifact_file_limit_exceeded",
    "duplicate_github_repo_id",
    "numeric_generated_at",
    "unknown_record_field",
}


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "github-repo-snapshot/v1",
        "dataset_snapshot_id": "fixture-github-repo-snapshot-20260902",
        "pipeline_run_id": "fixture-github-repo-run-001",
        "collector_version": "fixture-a-github-collector-v1",
        "generated_at": "2026-09-02T03:00:00Z",
        "collection_policy": {
            "policy_version": "fixture-repo-collection-policy-v1",
            "top_n_limit": 5000,
            "max_api_calls": 15000,
            "max_runtime_seconds": 3600,
            "max_tree_entries": 100000,
            "max_artifact_files": 100,
            "max_artifact_bytes": 10485760,
        },
        "records": [
            {
                "repo_snapshot_id": "fixture-repo-snapshot-001",
                "github_repo_id": 1296269,
                "repo_full_name": "fixture-owner/fixture-repository",
                "activity_metric": "gh_archive_event_count",
                "activity_period_start": "2026-08-01",
                "activity_period_end": "2026-08-31",
                "activity_count": 120,
                "activity_rank": 1,
                "pinned_commit_sha": "a" * 40,
                "tree_sha": "b" * 40,
                "collection_status": "COMPLETE",
                "collection_issues": [],
                "checkpoint_uri": None,
                "reused_from_snapshot_id": None,
                "tree_truncated": False,
                "observed_tree_entries": 42,
                "artifacts": [
                    {
                        "artifact_type": "MANIFEST",
                        "path": "backend/build.gradle",
                        "uri": "hdfs://namenode:9000/gitjob/github/fixture/build.gradle",
                        "content_hash": "c" * 64,
                        "size_bytes": 2048,
                    }
                ],
            }
        ],
    }


def test_valid_snapshot_preserves_commit_and_artifact_boundary() -> None:
    batch = GitHubRepoSnapshotBatch.model_validate(valid_payload())

    record = batch.records[0]
    artifact = record.artifacts[0]
    assert record.collection_status is RepoCollectionStatus.COMPLETE
    assert record.pinned_commit_sha == "a" * 40
    assert record.tree_sha == "b" * 40
    assert artifact.path == "backend/build.gradle"
    assert str(artifact.uri) == (
        "hdfs://namenode:9000/gitjob/github/fixture/build.gradle"
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "top_n_limit",
        "max_api_calls",
        "max_runtime_seconds",
        "max_tree_entries",
        "max_artifact_files",
        "max_artifact_bytes",
    ],
)
def test_collection_policy_rejects_non_positive_limits(field_name: str) -> None:
    payload = valid_payload()
    payload["collection_policy"][field_name] = 0  # type: ignore[index]

    with pytest.raises(ValidationError):
        GitHubRepoSnapshotBatch.model_validate(payload)


@pytest.mark.parametrize("status", ["PARTIAL", "FAILED"])
def test_incomplete_snapshot_requires_collection_issue(status: str) -> None:
    payload = valid_payload()
    record = payload["records"][0]  # type: ignore[index]
    record["collection_status"] = status

    with pytest.raises(ValidationError, match="collection issue"):
        GitHubRepoSnapshotBatch.model_validate(payload)


def test_rate_limited_snapshot_requires_checkpoint() -> None:
    payload = valid_payload()
    record = payload["records"][0]  # type: ignore[index]
    record.update(  # type: ignore[union-attr]
        {
            "collection_status": "PARTIAL",
            "collection_issues": ["RATE_LIMITED"],
        }
    )

    with pytest.raises(ValidationError, match="checkpoint_uri"):
        GitHubRepoSnapshotBatch.model_validate(payload)


def test_reused_snapshot_requires_source_snapshot_id() -> None:
    payload = valid_payload()
    record = payload["records"][0]  # type: ignore[index]
    record["collection_status"] = "REUSED"  # type: ignore[index]

    with pytest.raises(ValidationError, match="reused_from_snapshot_id"):
        GitHubRepoSnapshotBatch.model_validate(payload)


def test_complete_snapshot_rejects_collection_issues() -> None:
    payload = valid_payload()
    record = payload["records"][0]  # type: ignore[index]
    record["collection_issues"] = ["ARTIFACT_FETCH_FAILED"]  # type: ignore[index]

    with pytest.raises(ValidationError, match="COMPLETE"):
        GitHubRepoSnapshotBatch.model_validate(payload)


def test_tree_truncation_flag_and_issue_must_agree() -> None:
    payload = valid_payload()
    record = payload["records"][0]  # type: ignore[index]
    record.update(  # type: ignore[union-attr]
        {
            "collection_status": "PARTIAL",
            "tree_truncated": True,
            "collection_issues": ["ARTIFACT_FETCH_FAILED"],
        }
    )

    with pytest.raises(ValidationError, match="TREE_TRUNCATED"):
        GitHubRepoSnapshotBatch.model_validate(payload)


@pytest.mark.parametrize("path", ["/package.json", "../package.json", "src\\app.py"])
def test_artifact_path_must_be_safe_repo_relative_posix_path(path: str) -> None:
    payload = valid_payload()
    artifact = payload["records"][0]["artifacts"][0]  # type: ignore[index]
    artifact["path"] = path  # type: ignore[index]

    with pytest.raises(ValidationError, match="relative POSIX"):
        GitHubRepoSnapshotBatch.model_validate(payload)


def test_batch_enforces_file_and_byte_policy_limits() -> None:
    payload = valid_payload()
    policy = payload["collection_policy"]  # type: ignore[assignment]
    policy["max_artifact_files"] = 1
    policy["max_artifact_bytes"] = 3000
    second_artifact = deepcopy(payload["records"][0]["artifacts"][0])  # type: ignore[index]
    second_artifact["path"] = "frontend/package.json"
    payload["records"][0]["artifacts"].append(second_artifact)  # type: ignore[index,union-attr]

    with pytest.raises(ValidationError, match="max_artifact_files"):
        GitHubRepoSnapshotBatch.model_validate(payload)

    payload["records"][0]["artifacts"] = [second_artifact]  # type: ignore[index]
    second_artifact["size_bytes"] = 3001
    with pytest.raises(ValidationError, match="max_artifact_bytes"):
        GitHubRepoSnapshotBatch.model_validate(payload)


def test_batch_rejects_duplicate_repository_identity_and_rank() -> None:
    payload = valid_payload()
    duplicate = deepcopy(payload["records"][0])  # type: ignore[index]
    duplicate["repo_snapshot_id"] = "fixture-repo-snapshot-002"
    payload["records"].append(duplicate)  # type: ignore[union-attr]

    with pytest.raises(ValidationError, match="duplicate github_repo_id"):
        GitHubRepoSnapshotBatch.model_validate(payload)


@pytest.mark.parametrize("generated_at", [0, 0.0, "0", True, "2026-09-02T03:00:00"])
def test_generated_at_requires_timezone_aware_iso_datetime(
    generated_at: object,
) -> None:
    payload = valid_payload()
    payload["generated_at"] = generated_at

    with pytest.raises(ValidationError, match="ISO 8601|timezone"):
        GitHubRepoSnapshotBatch.model_validate(payload)


def test_committed_fixture_covers_complete_partial_failed_and_reused_states() -> None:
    batch = GitHubRepoSnapshotBatch.model_validate_json(
        (FIXTURE_ROOT / "github_repo_snapshot_v1.json").read_text(encoding="utf-8")
    )

    assert {record.collection_status for record in batch.records} == set(
        RepoCollectionStatus
    )
    assert any(record.tree_sha is None for record in batch.records)
    assert {
        artifact.artifact_type.value
        for record in batch.records
        for artifact in record.artifacts
    } == {"MANIFEST", "SOURCE"}
    assert any(record.checkpoint_uri is not None for record in batch.records)
    assert any(record.reused_from_snapshot_id is not None for record in batch.records)


def test_committed_invalid_fixture_cases_are_all_rejected() -> None:
    invalid_cases = json.loads(
        (FIXTURE_ROOT / "invalid_github_repo_snapshot_v1.json").read_text(
            encoding="utf-8"
        )
    )["cases"]

    assert {case["name"] for case in invalid_cases} == EXPECTED_INVALID_CASE_NAMES
    for case in invalid_cases:
        with pytest.raises(ValidationError, match=case["expected_error"]):
            GitHubRepoSnapshotBatch.model_validate(case["payload"])


def test_committed_json_schema_matches_authoritative_model() -> None:
    expected = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    actual = GitHubRepoSnapshotBatch.model_json_schema()

    assert actual == expected
