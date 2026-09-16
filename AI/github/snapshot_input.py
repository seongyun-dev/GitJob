"""Verify a published Snapshot and its summary/failures without collecting artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from common.webhdfs import WebHdfsError
from github.contracts import ContentHash, GitHubRepoSnapshotBatch

MAX_MARKER_BYTES = 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
_FILES = {
    "snapshot": "snapshot.json",
    "summary": "run-summary.json",
    "failures": "failures.json",
}
SourceStatus = Literal[
    "COMPLETE",
    "PARTIAL",
    "FAILED",
    "NOT_FOUND",
    "REUSED",
    "HISTORICAL_HEAD_UNAVAILABLE",
]


class SnapshotInputError(ValueError):
    """Publication is missing, inconsistent or changed during the bounded read."""


class PublishedInputReader(Protocol):
    def read(self, uri: str, *, max_bytes: int) -> bytes: ...

    def stat(self, uri: str) -> dict: ...


class _SourceModel(BaseModel):
    # Operational counters beyond the required consumption boundary may evolve.
    model_config = ConfigDict(extra="ignore", frozen=True)


class _PublishedObject(_SourceModel):
    uri: StrictStr
    sha256: ContentHash


class _Manifest(_SourceModel):
    schema_version: Literal["github-repo-snapshot-publish-manifest/v1"]
    dataset_snapshot_id: StrictStr
    objects: dict[str, _PublishedObject]


class _Disposition(_SourceModel):
    repo_id: StrictInt = Field(gt=0)
    rank: StrictInt = Field(gt=0)
    status: SourceStatus


class _Summary(_SourceModel):
    schema_version: Literal[
        "github-repo-snapshot-bootstrap-summary/v1", "github-repo-fetch-run-summary/v1"
    ]
    dataset_snapshot_id: StrictStr
    pipeline_run_id: StrictStr
    record_count: StrictInt = Field(ge=0)
    status_counts: dict[SourceStatus, StrictInt]
    repos: tuple[_Disposition, ...]
    snapshot_published: StrictBool | None = None
    stopped_reason: StrictStr | None = None
    # A Weekly run stops on its valid-artifact quota instead of consuming the
    # whole candidate pool (S15P21E102-274), so its summary covers a prefix of
    # `top_n_limit` rather than all of it. These three are what let the loader
    # tell that deliberate stop apart from a run that died early; they are
    # absent from Historical summaries, which stay on the full-coverage rule.
    quota_reached: StrictBool | None = None
    quota_shortfall: StrictInt | None = None
    candidates_examined: StrictInt | None = None


class _Failures(_SourceModel):
    schema_version: Literal["github-repo-fetch-failures/v1"]
    dataset_snapshot_id: StrictStr
    failure_count: StrictInt = Field(ge=0)
    repos: tuple[_Disposition, ...]


class SnapshotQuality(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_count: int
    snapshot_record_count: int
    failure_count: int
    summary_status_counts: dict[str, int]
    snapshot_status_counts: dict[str, int]
    absent_from_snapshot_counts: dict[str, int]
    failed_without_snapshot_ids: tuple[int, ...]
    complete_with_artifacts: int
    complete_without_artifacts: int
    declared_artifact_count: int
    declared_artifact_type_counts: dict[str, int]
    tree_equals_commit_count: int


class PublishedSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch: GitHubRepoSnapshotBatch
    source_root: str
    source_sha256: ContentHash
    manifest_sha256: ContentHash
    summary_sha256: ContentHash
    failures_sha256: ContentHash
    quality: SnapshotQuality


def _fixed_root(root_uri: str) -> str:
    parsed = urlsplit(root_uri)
    path = parsed.path.rstrip("/")
    if (
        parsed.scheme != "hdfs"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(c.isspace() or ord(c) < 32 for c in root_uri)
        or any(c in path for c in "%\\")
        or not path.startswith("/")
        or any(part in {"", ".", ".."} for part in path[1:].split("/"))
    ):
        raise SnapshotInputError("fixed HDFS publication root required")
    _ = parsed.port
    return "hdfs://" + parsed.netloc + path


def _unique_object(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise SnapshotInputError("duplicate JSON key")
        output[key] = value
    return output


def _reject_constant(value):
    raise SnapshotInputError("non-finite JSON constant")


def _decode(body: bytes):
    return json.loads(
        body, object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )


def _file_identity(metadata: dict) -> tuple[int, int, int]:
    keys = ("length", "modificationTime", "fileId")
    if (
        not isinstance(metadata, dict)
        or metadata.get("type") != "FILE"
        or any(type(metadata.get(key)) is not int or metadata[key] < 0 for key in keys)
    ):
        raise SnapshotInputError("file length, modification time and identity required")
    return tuple(metadata[key] for key in keys)


def _read_stable(reader: PublishedInputReader, uri: str, cap: int):
    before = _file_identity(reader.stat(uri))
    if before[0] > cap:
        raise SnapshotInputError("publication exceeds bounded read budget")
    body = reader.read(uri, max_bytes=before[0])
    after = _file_identity(reader.stat(uri))
    if not isinstance(body, bytes) or len(body) != before[0] or before != after:
        raise SnapshotInputError("publication changed during read")
    return body, before


def _index(rows: tuple[_Disposition, ...], top_n_limit: int) -> dict[int, _Disposition]:
    by_id = {}
    ranks = set()
    for row in rows:
        if row.repo_id in by_id or row.rank in ranks or row.rank > top_n_limit:
            raise SnapshotInputError("duplicate or out-of-range source identity/rank")
        by_id[row.repo_id] = row
        ranks.add(row.rank)
    return by_id


def _covers_its_candidates(
    by_id: dict[int, _Disposition], top_n_limit: int, summary: _Summary
) -> bool:
    """Did the run examine everything it was supposed to examine?

    For a Historical bootstrap that means the whole pool. `_index` already
    proves distinct ranks in 1..top_n_limit, so equal size proves exact
    contiguous coverage without allocating a range.
    """

    if len(by_id) == top_n_limit:
        return True
    # A Weekly run is allowed to stop short, but only because it filled its
    # valid-artifact quota. Every part of that has to be visible in the
    # summary: the quota was reached, nothing is outstanding, and the rows are
    # exactly the candidates it says it examined. `shortfall` is what separates
    # "we have all 100" from "we ran out of pool with 60"; without it a crashed
    # or truncated run would look the same as a deliberate stop.
    if (
        summary.quota_reached is not True
        or summary.quota_shortfall != 0
        or summary.candidates_examined != len(by_id)
        or len(by_id) > top_n_limit
    ):
        return False
    # The pool is rank-ordered and consumed from the top, so a quota stop
    # leaves a prefix. Ranks are already distinct, so the largest one matching
    # the count proves 1..examined with no gaps — a run that skipped
    # candidates it could not fetch would not satisfy this.
    return max((row.rank for row in by_id.values()), default=0) == len(by_id)


def _reconcile(batch: GitHubRepoSnapshotBatch, summary: _Summary, failures: _Failures):
    if not (
        summary.dataset_snapshot_id
        == failures.dataset_snapshot_id
        == batch.dataset_snapshot_id
        and summary.pipeline_run_id == batch.pipeline_run_id
        and summary.record_count == len(batch.records)
        and summary.snapshot_published is not False
    ):
        raise SnapshotInputError("publication dataset/run/record count mismatch")
    by_id = _index(summary.repos, batch.collection_policy.top_n_limit)
    failed = _index(failures.repos, batch.collection_policy.top_n_limit)
    if summary.schema_version == "github-repo-snapshot-bootstrap-summary/v1" and not (
        summary.snapshot_published is True
        and summary.stopped_reason is None
        and _covers_its_candidates(by_id, batch.collection_policy.top_n_limit, summary)
    ):
        raise SnapshotInputError(
            "bootstrap publication lacks complete candidate coverage or stopped early"
        )
    counts = Counter(row.status for row in summary.repos)
    if (
        len(summary.repos) > batch.collection_policy.top_n_limit
        or any(value < 0 for value in summary.status_counts.values())
        or dict(counts)
        != {key: value for key, value in summary.status_counts.items() if value}
        or len(failed) != failures.failure_count
        or set(failed)
        != {
            row.repo_id
            for row in summary.repos
            if row.status in {"FAILED", "NOT_FOUND", "HISTORICAL_HEAD_UNAVAILABLE"}
        }
        or any(row != by_id.get(repo_id) for repo_id, row in failed.items())
    ):
        raise SnapshotInputError(
            "summary/failures status counts or identities do not reconcile"
        )
    snapshot_ids = set()
    for row in batch.records:
        disposition = by_id.get(row.github_repo_id)
        if disposition is None or (
            disposition.status != row.collection_status.value
            or disposition.rank != row.activity_rank
        ):
            raise SnapshotInputError("Snapshot and summary status/rank mismatch")
        snapshot_ids.add(row.github_repo_id)
    absent = [row for row in summary.repos if row.repo_id not in snapshot_ids]
    if any(
        row.status not in {"FAILED", "NOT_FOUND", "HISTORICAL_HEAD_UNAVAILABLE"}
        for row in absent
    ):
        raise SnapshotInputError("successful source row is missing from Snapshot")
    complete = [
        row for row in batch.records if row.collection_status.value == "COMPLETE"
    ]
    artifact_types = Counter(
        a.artifact_type.value for row in batch.records for a in row.artifacts
    )
    return SnapshotQuality(
        candidate_count=len(summary.repos),
        snapshot_record_count=len(batch.records),
        failure_count=failures.failure_count,
        summary_status_counts=dict(counts),
        snapshot_status_counts=dict(
            Counter(row.collection_status.value for row in batch.records)
        ),
        absent_from_snapshot_counts=dict(Counter(row.status for row in absent)),
        failed_without_snapshot_ids=tuple(
            sorted(row.repo_id for row in absent if row.status == "FAILED")
        ),
        complete_with_artifacts=sum(bool(row.artifacts) for row in complete),
        complete_without_artifacts=sum(not row.artifacts for row in complete),
        declared_artifact_count=sum(artifact_types.values()),
        declared_artifact_type_counts=dict(artifact_types),
        tree_equals_commit_count=sum(
            row.tree_sha == row.pinned_commit_sha for row in batch.records
        ),
    )


def load_published_snapshot(
    root_uri: str, reader: PublishedInputReader
) -> PublishedSnapshot:
    """Return only a byte-verified, stable publication with reconciled source counts."""
    try:
        root = _fixed_root(root_uri)
        marker_uri = root + "/_SUCCESS.json"
        marker, marker_identity = _read_stable(reader, marker_uri, MAX_MARKER_BYTES)
        manifest = _Manifest.model_validate(_decode(marker))
        if not set(_FILES) <= set(manifest.objects):
            raise SnapshotInputError("publication manifest lacks required objects")
        # Check all destinations before following even the first advertised object.
        if any(
            manifest.objects[key].uri != root + "/" + filename
            for key, filename in _FILES.items()
        ):
            raise SnapshotInputError(
                "publication object URI differs from fixed same-root path"
            )
        remaining = MAX_TOTAL_BYTES - len(marker)
        objects = {}
        for key in _FILES:
            item = manifest.objects[key]
            body, _ = _read_stable(reader, item.uri, min(MAX_JSON_BYTES, remaining))
            remaining -= len(body)
            if hashlib.sha256(body).hexdigest() != item.sha256:
                raise SnapshotInputError("published object SHA-256 mismatch")
            objects[key] = _decode(body)
        batch = GitHubRepoSnapshotBatch.model_validate(objects["snapshot"])
        if batch.dataset_snapshot_id != manifest.dataset_snapshot_id:
            raise SnapshotInputError("manifest and Snapshot dataset identity differ")
        quality = _reconcile(
            batch,
            _Summary.model_validate(objects["summary"]),
            _Failures.model_validate(objects["failures"]),
        )
        final_marker, final_identity = _read_stable(
            reader, marker_uri, min(MAX_MARKER_BYTES, remaining)
        )
        if marker != final_marker or marker_identity != final_identity:
            raise SnapshotInputError(
                "completion marker changed during publication read"
            )
        return PublishedSnapshot(
            batch=batch,
            source_root=root,
            source_sha256=manifest.objects["snapshot"].sha256,
            manifest_sha256=hashlib.sha256(marker).hexdigest(),
            summary_sha256=manifest.objects["summary"].sha256,
            failures_sha256=manifest.objects["failures"].sha256,
            quality=quality,
        )
    except SnapshotInputError:
        raise
    except (ValueError, TypeError, KeyError, OSError, WebHdfsError) as error:
        raise SnapshotInputError("invalid or unavailable published Snapshot") from error
