"""Persistence boundaries for repo artifacts, cache, and resumable checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from common.webhdfs import WebHdfsClient, WebHdfsTransport, normalize_hdfs_path

from github.client import RequestRecord
from github.contracts import GitHubRepoSnapshot, RepoCollectionStatus

STORE_VERSION = 1


class ArtifactStore(Protocol):
    def store(
        self,
        *,
        policy_version: str,
        repo_id: int,
        pinned_commit_sha: str,
        path: str,
        content: bytes,
    ) -> str: ...


class FileArtifactStore:
    """Immutable local artifact store used by the orchestrator interface."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def store(
        self,
        *,
        policy_version: str,
        repo_id: int,
        pinned_commit_sha: str,
        path: str,
        content: bytes,
    ) -> str:
        relative = _safe_relative_path(path)
        policy_key = hashlib.sha256(policy_version.encode("utf-8")).hexdigest()[:16]
        destination = (
            self.root
            / f"policy={policy_key}"
            / f"repo_id={repo_id}"
            / f"commit={pinned_commit_sha}"
            / Path(*relative.parts)
        ).resolve()
        if not destination.is_relative_to(self.root):
            raise ValueError("artifact destination escapes store root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != content:
                raise FileExistsError(
                    "immutable artifact already exists with different content"
                )
            return destination.as_uri()

        temporary = destination.with_name(
            f"{destination.name}.uploading-{uuid.uuid4().hex}"
        )
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination.as_uri()


class WebHdfsArtifactStore:
    """Immutable shared artifact store for bootstrap and C-team read-back."""

    def __init__(
        self,
        *,
        base_url: str,
        root: str,
        user: str = "hadoop",
        timeout: float = 120.0,
        transport: WebHdfsTransport | None = None,
    ) -> None:
        self.root = normalize_hdfs_path(root)
        client_arguments: dict[str, Any] = {
            "base_url": base_url,
            "user": user,
            "timeout": timeout,
        }
        if transport is not None:
            client_arguments["transport"] = transport
        self.client = WebHdfsClient(**client_arguments)

    def store(
        self,
        *,
        policy_version: str,
        repo_id: int,
        pinned_commit_sha: str,
        path: str,
        content: bytes,
    ) -> str:
        relative = _safe_relative_path(path)
        policy_key = hashlib.sha256(policy_version.encode("utf-8")).hexdigest()[:16]
        destination = (
            self.root
            / f"policy={policy_key}"
            / f"repo_id={repo_id}"
            / f"commit={pinned_commit_sha}"
            / relative
        )
        return self.client.store_immutable(destination, content)


class RepoSnapshotCache:
    """Cross-period cache keyed by policy, GitHub repo id, and pinned SHA."""

    def __init__(self, path: Path, *, flush_every: int = 100) -> None:
        if flush_every < 1:
            raise ValueError("flush_every must be positive")
        self.path = path.resolve()
        self.flush_every = flush_every
        self._dirty = 0
        self.data = _load_json_store(
            self.path,
            purpose="github_repo_snapshot_cache",
            default={"entries": {}},
        )

    def get(
        self,
        *,
        policy_version: str,
        repo_id: int,
        pinned_commit_sha: str,
    ) -> GitHubRepoSnapshot | None:
        payload = self.data["entries"].get(
            _cache_key(policy_version, repo_id, pinned_commit_sha)
        )
        if not isinstance(payload, Mapping):
            return None
        record = GitHubRepoSnapshot.model_validate(payload)
        if record.collection_status is not RepoCollectionStatus.COMPLETE:
            raise ValueError("cache contains a non-COMPLETE snapshot")
        return record

    def put(
        self,
        *,
        policy_version: str,
        record: GitHubRepoSnapshot,
    ) -> None:
        if record.collection_status is not RepoCollectionStatus.COMPLETE:
            return
        key = _cache_key(
            policy_version,
            record.github_repo_id,
            record.pinned_commit_sha,
        )
        payload = record.model_dump(mode="json")
        existing = self.data["entries"].get(key)
        if existing is not None and existing != payload:
            raise ValueError("cache key collision contains different snapshot data")
        self.data["entries"][key] = payload
        self._mark_dirty()

    def repair_tree_sha(
        self,
        *,
        policy_version: str,
        repo_id: int,
        pinned_commit_sha: str,
        tree_sha: str,
    ) -> GitHubRepoSnapshot | None:
        """Repair cached tree metadata without touching immutable artifacts.

        Cache identity is still policy + repo ID + pinned commit.  When an
        older run stored the commit SHA in ``tree_sha``, the current HEAD
        response can provide the authoritative tree SHA.  Only that metadata
        field is replaced; artifact URIs and content hashes remain byte-for-
        byte unchanged.
        """

        key = _cache_key(policy_version, repo_id, pinned_commit_sha)
        payload = self.data["entries"].get(key)
        if not isinstance(payload, Mapping):
            return None
        record = GitHubRepoSnapshot.model_validate(payload)
        if record.tree_sha == tree_sha:
            return record
        repaired = record.model_copy(update={"tree_sha": tree_sha})
        self.data["entries"][key] = repaired.model_dump(mode="json")
        self._mark_dirty()
        return repaired

    def _mark_dirty(self) -> None:
        self._dirty += 1
        if self._dirty >= self.flush_every:
            self.save()

    def save(self) -> None:
        if self._dirty or not self.path.exists():
            _atomic_json_write(self.path, self.data)
        self._dirty = 0


class RepoFetchCheckpoint:
    """Dataset-bound execution state; pre-commit failures remain outside C contract."""

    def __init__(self, path: Path, *, flush_every: int = 100) -> None:
        if flush_every < 1:
            raise ValueError("flush_every must be positive")
        self.path = path.resolve()
        self.flush_every = flush_every
        self._dirty = 0
        self.data = _load_json_store(
            self.path,
            purpose="github_repo_fetch_checkpoint",
            default={
                "dataset_snapshot_id": None,
                "pipeline_run_id": None,
                "collector_version": None,
                "policy_version": None,
                "generated_at": None,
                "repos": {},
            },
        )

    @property
    def uri(self) -> str:
        return self.path.as_uri()

    @property
    def generated_at(self) -> str:
        value = self.data.get("generated_at")
        if not isinstance(value, str) or not value:
            raise ValueError("checkpoint has not been bound to a dataset")
        return value

    def bind(
        self,
        *,
        dataset_snapshot_id: str,
        pipeline_run_id: str,
        collector_version: str,
        policy_version: str,
        generated_at: str,
    ) -> None:
        expected = {
            "dataset_snapshot_id": dataset_snapshot_id,
            "pipeline_run_id": pipeline_run_id,
            "collector_version": collector_version,
            "policy_version": policy_version,
        }
        for key, value in expected.items():
            existing = self.data.get(key)
            if existing is not None and existing != value:
                raise ValueError(f"checkpoint belongs to a different {key}")
            self.data[key] = value
        if self.data.get("generated_at") is None:
            self.data["generated_at"] = generated_at
        _atomic_json_write(self.path, self.data)

    def ensure_candidate(
        self,
        *,
        repo_id: int,
        repo_name: str,
        rank: int,
        activity_count: int,
        activity_metric: str,
        period_start: str,
        period_end: str,
        monthly_event_sha: str | None = None,
    ) -> None:
        key = str(repo_id)
        existing = self.data["repos"].get(key)
        identity = {
            "repo_id": repo_id,
            "repo_name": repo_name,
            "rank": rank,
            "activity_count": activity_count,
            "activity_metric": activity_metric,
            "period_start": period_start,
            "period_end": period_end,
            "monthly_event_sha": monthly_event_sha,
        }
        if existing is None:
            self.data["repos"][key] = {
                **identity,
                "status": "PENDING",
                "attempts": 0,
                "last_error": None,
                "api_calls": 0,
                "core_calls": 0,
                "raw_calls": 0,
                "http_statuses": [],
                "contract_record": None,
            }
            self._mark_dirty()
            return
        if any(existing.get(name) != value for name, value in identity.items()):
            raise ValueError(f"checkpoint candidate mismatch for repo_id={repo_id}")

    def status(self, repo_id: int) -> str:
        entry = self.data["repos"].get(str(repo_id), {})
        return str(entry.get("status", ""))

    def contract_record(self, repo_id: int) -> GitHubRepoSnapshot | None:
        """Return the terminal contract record stored for one candidate."""

        entry = self.data["repos"].get(str(repo_id), {})
        payload = entry.get("contract_record")
        if not isinstance(payload, Mapping):
            return None
        return GitHubRepoSnapshot.model_validate(payload)

    def repair_tree_sha(
        self,
        *,
        repo_id: int,
        tree_sha: str | None,
    ) -> GitHubRepoSnapshot | None:
        """Replace only legacy checkpoint tree metadata.

        A checkpoint can outlive the code that produced it.  If an older run
        stored the pinned commit SHA as ``tree_sha``, a later lightweight
        commit lookup may repair that field without touching Artifact bytes or
        retrying the repository collection.
        """

        entry = self.data["repos"].get(str(repo_id))
        if not isinstance(entry, dict):
            return None
        payload = entry.get("contract_record")
        if not isinstance(payload, Mapping):
            return None
        record = GitHubRepoSnapshot.model_validate(payload)
        if record.tree_sha == tree_sha:
            return record
        repaired = record.model_copy(update={"tree_sha": tree_sha})
        entry["contract_record"] = repaired.model_dump(mode="json")
        self._mark_dirty()
        return repaired

    def record_tree_repair_requests(
        self,
        *,
        repo_id: int,
        requests: Sequence[RequestRecord],
        last_error: str | None = None,
    ) -> None:
        """Account a metadata-only tree repair without incrementing attempts."""

        entry = self.data["repos"].get(str(repo_id))
        if not isinstance(entry, dict):
            return
        entry["api_calls"] = int(entry.get("api_calls", 0)) + len(requests)
        entry["core_calls"] = int(entry.get("core_calls", 0)) + sum(
            request.is_core for request in requests
        )
        entry["raw_calls"] = int(entry.get("raw_calls", 0)) + sum(
            not request.is_core for request in requests
        )
        entry["http_statuses"] = [
            *entry.get("http_statuses", []),
            *(request.http_status for request in requests),
        ]
        if last_error is not None:
            entry["last_error"] = last_error
        self._mark_dirty()

    def record(
        self,
        *,
        repo_id: int,
        status: str,
        last_error: str | None,
        api_calls: int,
        core_calls: int,
        raw_calls: int,
        http_statuses: list[int],
        contract_record: GitHubRepoSnapshot | None,
        selection_metrics: Mapping[str, Any] | None = None,
        lineage: Mapping[str, Any] | None = None,
    ) -> None:
        entry = self.data["repos"][str(repo_id)]
        entry.update(
            status=status,
            attempts=int(entry.get("attempts", 0)) + 1,
            last_error=last_error,
            api_calls=int(entry.get("api_calls", 0)) + api_calls,
            core_calls=int(entry.get("core_calls", 0)) + core_calls,
            raw_calls=int(entry.get("raw_calls", 0)) + raw_calls,
            http_statuses=[*entry.get("http_statuses", []), *http_statuses],
            contract_record=(
                contract_record.model_dump(mode="json")
                if contract_record is not None
                else None
            ),
            selection_metrics=dict(selection_metrics or {}),
        )
        if lineage:
            entry["lineage"] = dict(lineage)
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        self._dirty += 1
        if self._dirty >= self.flush_every:
            self.save()

    def save(self) -> None:
        if self._dirty or not self.path.exists():
            _atomic_json_write(self.path, self.data)
        self._dirty = 0

    def contract_records(self) -> tuple[GitHubRepoSnapshot, ...]:
        records = []
        for entry in self.data["repos"].values():
            payload = entry.get("contract_record")
            if isinstance(payload, Mapping):
                records.append(GitHubRepoSnapshot.model_validate(payload))
        return tuple(sorted(records, key=lambda record: record.activity_rank))

    def summary_rows(self) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in entry.items() if key != "contract_record"}
            for entry in sorted(
                self.data["repos"].values(),
                key=lambda value: int(value["rank"]),
            )
        ]


def _load_json_store(
    path: Path,
    *,
    purpose: str,
    default: dict[str, Any],
) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": STORE_VERSION,
            "source": "github",
            "purpose": purpose,
            **default,
        }
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON store: {path}") from exc
    if not isinstance(loaded, dict):
        raise TypeError("JSON store root must be an object")
    if loaded.get("version") != STORE_VERSION:
        raise ValueError("unsupported JSON store version")
    if loaded.get("source") != "github" or loaded.get("purpose") != purpose:
        raise ValueError("JSON store identity mismatch")
    return loaded


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _cache_key(policy_version: str, repo_id: int, pinned_commit_sha: str) -> str:
    return f"{policy_version}\u001f{repo_id}\u001f{pinned_commit_sha}"


def _safe_relative_path(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if (
        not path
        or path != path.strip()
        or "\\" in path
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("artifact path must be a safe repository-relative POSIX path")
    return candidate
