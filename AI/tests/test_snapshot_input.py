import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from github.snapshot_input import SnapshotInputError, load_published_snapshot

ROOT = "hdfs:///trusted/snapshot"


class PublishedReader:
    def __init__(self, documents):
        self.documents = documents
        self.files = {}
        self.calls = []
        self.publish()

    def publish(self):
        filenames = {
            "snapshot": "snapshot.json",
            "summary": "run-summary.json",
            "failures": "failures.json",
        }
        objects = {}
        for key, filename in filenames.items():
            uri = ROOT + "/" + filename
            body = json.dumps(self.documents[key]).encode()
            self.files[uri] = body
            objects[key] = {"uri": uri, "sha256": hashlib.sha256(body).hexdigest()}
        self.manifest = {
            "schema_version": "github-repo-snapshot-publish-manifest/v1",
            "dataset_snapshot_id": self.documents["snapshot"]["dataset_snapshot_id"],
            "objects": objects,
        }
        self.write_manifest()

    def write_manifest(self):
        self.files[ROOT + "/_SUCCESS.json"] = json.dumps(self.manifest).encode()

    def read(self, uri, *, max_bytes):
        self.calls.append(("read", uri))
        return self.files[uri][: max_bytes + 1]

    def stat(self, uri):
        self.calls.append(("stat", uri))
        if uri not in self.files:
            raise OSError("missing file")
        return {
            "type": "FILE",
            "length": len(self.files[uri]),
            "modificationTime": 100,
            "fileId": 12,
        }


@pytest.fixture
def published():
    batch = json.loads(
        Path("github/fixtures/github_repo_snapshot_v1.json").read_bytes()
    )
    rows = [
        {
            "repo_id": row["github_repo_id"],
            "rank": row["activity_rank"],
            "status": row["collection_status"],
        }
        for row in batch["records"]
    ]
    max_rank = max(row["rank"] for row in rows)
    rows.extend(
        [
            {"repo_id": 9999, "rank": max_rank + 1, "status": "NOT_FOUND"},
            {"repo_id": 9998, "rank": max_rank + 2, "status": "FAILED"},
        ]
    )
    batch["collection_policy"]["top_n_limit"] = max_rank + 2
    failures = [row for row in rows if row["status"] in {"NOT_FOUND", "FAILED"}]
    return PublishedReader(
        {
            "snapshot": batch,
            "summary": {
                "schema_version": "github-repo-snapshot-bootstrap-summary/v1",
                "dataset_snapshot_id": batch["dataset_snapshot_id"],
                "pipeline_run_id": batch["pipeline_run_id"],
                "record_count": len(batch["records"]),
                "status_counts": dict(Counter(row["status"] for row in rows)),
                "repos": rows,
                "snapshot_published": True,
                "stopped_reason": None,
                "future_operational_field": {"not_required_by_consumer": True},
            },
            "failures": {
                "schema_version": "github-repo-fetch-failures/v1",
                "dataset_snapshot_id": batch["dataset_snapshot_id"],
                "failure_count": len(failures),
                "repos": failures,
            },
        }
    )


def test_loads_verified_complete_input_and_reconciles_external_failures(published):
    result = load_published_snapshot(ROOT + "/", published)
    assert result.batch.dataset_snapshot_id == published.manifest["dataset_snapshot_id"]
    assert result.source_sha256 == published.manifest["objects"]["snapshot"]["sha256"]
    assert (
        result.manifest_sha256
        == hashlib.sha256(published.files[ROOT + "/_SUCCESS.json"]).hexdigest()
    )
    assert result.quality.candidate_count == len(result.batch.records) + 2
    assert result.quality.absent_from_snapshot_counts == {"NOT_FOUND": 1, "FAILED": 1}
    assert 9999 not in {row.github_repo_id for row in result.batch.records}
    assert len([item for item in published.calls if item[0] == "read"]) == 5


@pytest.mark.parametrize(
    "filename", ["_SUCCESS.json", "snapshot.json", "run-summary.json", "failures.json"]
)
def test_missing_or_bad_hashed_input_fails_closed(published, filename):
    published.files[ROOT + "/" + filename] = b"{}"
    with pytest.raises(SnapshotInputError):
        load_published_snapshot(ROOT, published)


def test_manifest_cannot_redirect_to_another_uri(published):
    published.manifest["objects"]["snapshot"]["uri"] = "https://example.test/arbitrary"
    published.write_manifest()
    with pytest.raises(SnapshotInputError):
        load_published_snapshot(ROOT, published)
    assert all(uri.startswith(ROOT) for _, uri in published.calls)


@pytest.mark.parametrize(
    "change",
    [
        "count",
        "duplicate_id",
        "duplicate_rank",
        "status",
        "missing_failure",
        "dataset",
        "run",
        "summary_schema",
    ],
)
def test_summary_failure_identity_or_count_mismatch_rejected(published, change):
    summary = published.documents["summary"]
    if change == "count":
        summary["status_counts"]["COMPLETE"] += 1
    elif change == "duplicate_id":
        summary["repos"][1]["repo_id"] = summary["repos"][0]["repo_id"]
    elif change == "duplicate_rank":
        summary["repos"][1]["rank"] = summary["repos"][0]["rank"]
    elif change == "status":
        summary["repos"][0]["status"] = "NOT_FOUND"
    elif change == "missing_failure":
        published.documents["failures"]["repos"].pop()
    elif change == "dataset":
        summary["dataset_snapshot_id"] = "different"
    elif change == "run":
        summary["pipeline_run_id"] = "different"
    else:
        summary["schema_version"] = "future/v2"
    published.publish()
    with pytest.raises(SnapshotInputError):
        load_published_snapshot(ROOT, published)


@pytest.mark.parametrize("field", ["length", "modificationTime", "fileId"])
def test_file_metadata_mutation_during_read_rejected(published, monkeypatch, field):
    original = published.stat
    target = ROOT + "/snapshot.json"
    calls = 0

    def changed(uri):
        nonlocal calls
        value = original(uri)
        if uri == target:
            calls += 1
            if calls > 1:
                value[field] += 1
        return value

    monkeypatch.setattr(published, "stat", changed)
    with pytest.raises(SnapshotInputError, match="changed"):
        load_published_snapshot(ROOT, published)


def test_completion_marker_is_reread_and_compared_byte_for_byte(published, monkeypatch):
    original = published.read
    marker_reads = 0

    def changed(uri, *, max_bytes):
        nonlocal marker_reads
        body = original(uri, max_bytes=max_bytes)
        if uri.endswith("_SUCCESS.json"):
            marker_reads += 1
            if marker_reads == 2:
                return body.replace(b"fixture", b"changed", 1)
        return body

    monkeypatch.setattr(published, "read", changed)
    with pytest.raises(SnapshotInputError, match="marker changed"):
        load_published_snapshot(ROOT, published)
    assert marker_reads == 2


@pytest.mark.parametrize("field", ["length", "modificationTime", "fileId"])
def test_absent_stat_identity_is_not_assumed_stable(published, monkeypatch, field):
    original = published.stat

    def missing(uri):
        value = original(uri)
        value.pop(field)
        return value

    monkeypatch.setattr(published, "stat", missing)
    with pytest.raises(SnapshotInputError):
        load_published_snapshot(ROOT, published)
    assert all(operation != "read" for operation, _ in published.calls)


def test_oversized_json_is_rejected_before_body_read(published, monkeypatch):
    from github.snapshot_input import MAX_JSON_BYTES

    original = published.stat
    target = ROOT + "/snapshot.json"

    def oversized(uri):
        value = original(uri)
        if uri == target:
            value["length"] = MAX_JSON_BYTES + 1
        return value

    monkeypatch.setattr(published, "stat", oversized)
    with pytest.raises(SnapshotInputError, match="budget"):
        load_published_snapshot(ROOT, published)
    assert ("read", target) not in published.calls


@pytest.mark.parametrize(
    "root",
    [
        "https://example.test/root",
        "hdfs:///",
        "hdfs:///trusted/../snapshot",
        ROOT + "?key=secret",
        ROOT + "/%2e%2e",
    ],
)
def test_unsafe_root_rejected_before_reader_use(published, root):
    with pytest.raises(SnapshotInputError):
        load_published_snapshot(root, published)
    assert not published.calls


def test_missing_marker_never_falls_back_to_snapshot(published):
    del published.files[ROOT + "/_SUCCESS.json"]
    with pytest.raises(SnapshotInputError):
        load_published_snapshot(ROOT, published)
    assert published.calls == [("stat", ROOT + "/_SUCCESS.json")]


def test_supported_run_summary_does_not_require_bootstrap_only_counters(published):
    published.documents["summary"]["schema_version"] = (
        "github-repo-fetch-run-summary/v1"
    )
    published.publish()
    assert load_published_snapshot(ROOT, published).quality.candidate_count > 0


def _remove_not_found_candidate(published):
    summary = published.documents["summary"]
    failures = published.documents["failures"]
    summary["repos"] = [row for row in summary["repos"] if row["status"] != "NOT_FOUND"]
    failures["repos"] = [
        row for row in failures["repos"] if row["status"] != "NOT_FOUND"
    ]
    summary["status_counts"] = dict(Counter(row["status"] for row in summary["repos"]))
    failures["failure_count"] = len(failures["repos"])


def test_bootstrap_rejects_jointly_removed_candidate_even_with_valid_hashes(published):
    _remove_not_found_candidate(published)
    published.publish()
    with pytest.raises(SnapshotInputError, match="bootstrap"):
        load_published_snapshot(ROOT, published)


def test_bootstrap_rejects_early_stop_despite_complete_marker(published):
    published.documents["summary"]["stopped_reason"] = "RUN_TIME_LIMIT"
    published.publish()
    with pytest.raises(SnapshotInputError, match="bootstrap"):
        load_published_snapshot(ROOT, published)


def test_generic_fetch_summary_keeps_legitimate_partial_candidate_scope(published):
    _remove_not_found_candidate(published)
    summary = published.documents["summary"]
    summary["schema_version"] = "github-repo-fetch-run-summary/v1"
    summary["stopped_reason"] = "RUN_TIME_LIMIT"
    summary.pop("snapshot_published")
    published.publish()
    loaded = load_published_snapshot(ROOT, published)
    assert (
        loaded.quality.candidate_count == loaded.batch.collection_policy.top_n_limit - 1
    )
