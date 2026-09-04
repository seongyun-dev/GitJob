"""Bounded GitHub repository fetch benchmark with checkpoint and resume.

The module prepares repository metadata, a pinned default-branch commit, one
recursive tree, and a bounded set of manifest candidates.  It deliberately
does not perform technology detection or persist complete GitHub responses.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import urllib.parse
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from itertools import pairwise
from pathlib import Path
from typing import Any

from github.client import (
    RAW_ROOT,
    GitHubClient,
    HttpResponse,
    RateLimitState,
    RequestOutcome,
    RequestRecord,
)
from github.repo_fetch_policy import MANIFEST_BASENAMES

__all__ = (
    "GitHubClient",
    "HttpResponse",
    "RequestRecord",
)

CHECKPOINT_VERSION = 1
DEFAULT_SAFETY_THRESHOLD = 200
DEFAULT_MAX_MANIFESTS = 10
# Bootstrap phases for the 2026-08 MVP.  Rank is a processing priority, not a
# permanent cutoff: each phase is just "--limit N" against the same rank-ordered
# candidate list, and the checkpoint makes the next phase pay only for new repos.
MVP_PHASE_SIZES = (20_000, 50_000, 100_000)


class CollectionStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class MissingReason(str, Enum):
    """Why a historical repo_name no longer resolves."""

    RENAMED_OR_TRANSFERRED = "RENAMED_OR_TRANSFERRED"
    REPO_GONE_OWNER_ALIVE = "REPO_GONE_OWNER_ALIVE"
    OWNER_GONE = "OWNER_GONE"
    UNDETERMINED = "UNDETERMINED"


class Stage(str, Enum):
    CONTROL = "CONTROL"
    METADATA = "A_METADATA"
    HEAD = "B_HEAD"
    TREE = "C_TREE"
    MANIFEST = "D_MANIFEST"


@dataclass(frozen=True)
class RepoCandidate:
    repo_id: int
    repo_name: str
    rank: int
    stratum: str = "unspecified"


@dataclass
class RepoResult:
    repo_id: int
    repo_name: str
    rank: int
    stratum: str
    status: str
    attempts: int = 1
    last_error: str | None = None
    canonical_repo_name: str | None = None
    renamed: bool = False
    default_branch: str | None = None
    pinned_commit_sha: str | None = None
    artifact_key: str | None = None
    archived: bool | None = None
    fork: bool | None = None
    visibility: str | None = None
    tree_truncated: bool | None = None
    tree_entries: int | None = None
    manifest_candidates: tuple[str, ...] = ()
    manifest_fetch_count: int = 0
    manifest_success_count: int = 0
    cache_reused: bool = False
    collected_at: str = field(default_factory=lambda: _utc_now())
    requests: list[RequestRecord] = field(default_factory=list)
    _core_calls: int | None = None
    _api_calls: int | None = None
    _response_bytes: int | None = None
    _elapsed_seconds: float | None = None

    @property
    def api_calls(self) -> int:
        if not self.requests and self._api_calls is not None:
            return self._api_calls
        return len(self.requests)

    @property
    def core_calls(self) -> int:
        """Core REST requests this module issued.

        This is not the budget consumed.  ``urllib`` follows GitHub's 301 rename
        redirect transparently and GitHub charges both hops, so a renamed
        repository costs more budget than it logs.  Use ``budget_consumed`` for
        capacity planning and this for request accounting.
        """
        if not self.requests and self._core_calls is not None:
            return self._core_calls
        return sum(record.is_core for record in self.requests)

    @property
    def budget_consumed(self) -> int | None:
        """Core budget actually charged, from the x-ratelimit-used header delta.

        None when the run did not observe two usable header values.
        """
        used = [
            record.rate_limit_used
            for record in self.requests
            if record.is_core and record.rate_limit_used is not None
        ]
        if len(used) < 2:
            return None
        return max(used) - min(used) + 1

    @property
    def raw_calls(self) -> int:
        return self.api_calls - self.core_calls

    @property
    def response_bytes(self) -> int:
        if not self.requests and self._response_bytes is not None:
            return self._response_bytes
        return sum(record.response_bytes for record in self.requests)

    @property
    def elapsed_seconds(self) -> float:
        if not self.requests and self._elapsed_seconds is not None:
            return self._elapsed_seconds
        return sum(record.elapsed_seconds for record in self.requests)

    def as_dict(self) -> dict[str, Any]:
        value = {
            key: item for key, item in asdict(self).items() if not key.startswith("_")
        }
        value.update(
            api_calls=self.api_calls,
            core_calls=self.core_calls,
            raw_calls=self.raw_calls,
            response_bytes=self.response_bytes,
            elapsed_seconds=self.elapsed_seconds,
            budget_consumed=self.budget_consumed,
            has_analyzable_artifact=self.has_analyzable_artifact,
        )
        return value

    @property
    def has_analyzable_artifact(self) -> bool:
        """Whether this repository yielded a dependency manifest.

        HTTP 200 on the tree is not the same as usable input: a repository can
        be collected in full and still contain nothing C can analyse.  Coverage
        must be reported on this, not on SUCCEEDED.
        """
        return self.manifest_success_count > 0

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RepoResult:
        requests = [
            RequestRecord(**record)
            for record in value.get("requests", [])
            if isinstance(record, Mapping)
        ]
        return cls(
            repo_id=int(value["repo_id"]),
            repo_name=str(value["repo_name"]),
            rank=int(value["rank"]),
            stratum=str(value.get("stratum", "unspecified")),
            status=str(value["status"]),
            attempts=int(value.get("attempts", 1)),
            last_error=_optional_str(value.get("last_error")),
            canonical_repo_name=_optional_str(value.get("canonical_repo_name")),
            renamed=bool(value.get("renamed", False)),
            default_branch=_optional_str(value.get("default_branch")),
            pinned_commit_sha=_optional_str(value.get("pinned_commit_sha")),
            artifact_key=_optional_str(value.get("artifact_key")),
            archived=_optional_bool(value.get("archived")),
            fork=_optional_bool(value.get("fork")),
            visibility=_optional_str(value.get("visibility")),
            tree_truncated=_optional_bool(value.get("tree_truncated")),
            tree_entries=_optional_int(value.get("tree_entries")),
            manifest_candidates=tuple(value.get("manifest_candidates", ())),
            manifest_fetch_count=int(value.get("manifest_fetch_count", 0)),
            manifest_success_count=int(value.get("manifest_success_count", 0)),
            cache_reused=bool(value.get("cache_reused", False)),
            collected_at=str(value.get("collected_at", _utc_now())),
            requests=requests,
            _core_calls=_optional_int(value.get("core_calls")),
            _api_calls=_optional_int(value.get("api_calls")),
            _response_bytes=_optional_int(value.get("response_bytes")),
            _elapsed_seconds=_nested_or_float(value.get("elapsed_seconds")),
        )


class CheckpointStore:
    """Atomic summary-only checkpoint.  Complete API payloads are never stored."""

    def __init__(self, path: Path, *, flush_every: int = 1) -> None:
        """``flush_every`` bounds checkpoint write amplification.

        ``save`` rewrites the whole file, so flushing after every repository is
        O(N) per repo and O(N**2) per run.  At N=50,000 that write cost matches
        the entire per-repo time budget, so long runs must batch.  A hard kill
        loses at most ``flush_every`` repositories, which are simply re-fetched.
        """
        if flush_every < 1:
            raise ValueError("flush_every must be at least 1")
        self.flush_every = flush_every
        self._dirty = 0
        self.path = path.resolve()
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": CHECKPOINT_VERSION,
                "source": "github",
                "purpose": "historical_repo_fetch_benchmark",
                "repos": {},
            }
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read checkpoint: {self.path}") from exc
        if not isinstance(loaded, dict):
            raise TypeError("checkpoint root must be an object")
        if loaded.get("version") != CHECKPOINT_VERSION:
            raise ValueError("unsupported checkpoint version")
        if loaded.get("source") != "github":
            raise ValueError("checkpoint source must be github")
        if not isinstance(loaded.get("repos"), dict):
            raise TypeError("checkpoint repos must be an object")
        return loaded

    @property
    def repos(self) -> dict[str, Any]:
        return self.data["repos"]

    def bind_dataset(self, dataset_key: str) -> None:
        """Tie this checkpoint to one Repo Activity snapshot.

        The same pipeline runs for any period, so a checkpoint from 2026-08 must
        not silently resume against 2026-09 candidates: ranks differ and every
        skip decision would be wrong.
        """
        existing = self.data.get("dataset_key")
        if existing and existing != dataset_key:
            raise ValueError(
                "checkpoint belongs to a different dataset; "
                "use a separate checkpoint file per period"
            )
        self.data["dataset_key"] = dataset_key

    def ensure_candidates(self, candidates: Iterable[RepoCandidate]) -> None:
        changed = False
        for candidate in candidates:
            key = str(candidate.repo_id)
            current = self.repos.get(key)
            if current is None:
                self.repos[key] = {
                    "repo_id": candidate.repo_id,
                    "repo_name": candidate.repo_name,
                    "rank": candidate.rank,
                    "stratum": candidate.stratum,
                    "status": CollectionStatus.PENDING.value,
                    "attempts": 0,
                    "last_error": None,
                    "result": None,
                    "revalidations": [],
                }
                changed = True
                continue
            identity = (current.get("repo_name"), current.get("rank"))
            if identity != (candidate.repo_name, candidate.rank):
                raise ValueError(f"checkpoint candidate mismatch for repo_id={key}")
        if changed:
            self.save()

    def record_result(self, result: RepoResult) -> None:
        key = str(result.repo_id)
        current = self.repos[key]
        current.update(
            status=result.status,
            attempts=int(current.get("attempts", 0)) + 1,
            last_error=result.last_error,
            result=result.as_dict(),
        )
        self._mark_dirty()

    def record_revalidation(self, repo_id: int, result: RepoResult) -> None:
        current = self.repos[str(repo_id)]
        current.setdefault("revalidations", []).append(result.as_dict())
        self._mark_dirty()

    def prior_result(self, repo_id: int) -> Mapping[str, Any] | None:
        value = self.repos.get(str(repo_id), {}).get("result")
        return value if isinstance(value, Mapping) else None

    def status(self, repo_id: int) -> str:
        return str(self.repos.get(str(repo_id), {}).get("status", ""))

    def results(self) -> tuple[RepoResult, ...]:
        values = []
        for record in self.repos.values():
            result = record.get("result") if isinstance(record, Mapping) else None
            if isinstance(result, Mapping):
                values.append(RepoResult.from_dict(result))
        return tuple(sorted(values, key=lambda item: item.rank))

    def _mark_dirty(self) -> None:
        self._dirty += 1
        if self._dirty >= self.flush_every:
            self.save()

    def save(self) -> None:
        self._dirty = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)


def select_manifest_candidates(
    tree_entries: Sequence[Mapping[str, Any]],
    *,
    limit: int = DEFAULT_MAX_MANIFESTS,
) -> tuple[str, ...]:
    if limit < 0:
        raise ValueError("manifest limit cannot be negative")
    priority = {name: index for index, name in enumerate(MANIFEST_BASENAMES)}
    paths: set[str] = set()
    for entry in tree_entries:
        path = entry.get("path")
        if entry.get("type") != "blob" or not isinstance(path, str):
            continue
        basename = path.rsplit("/", 1)[-1]
        if basename in priority:
            paths.add(path)
    ordered = sorted(
        paths,
        key=lambda path: (
            path.count("/"),
            priority[path.rsplit("/", 1)[-1]],
            path,
        ),
    )
    return tuple(ordered[:limit])


class RepoFetchBenchmark:
    def __init__(
        self,
        client: GitHubClient,
        checkpoint: CheckpointStore,
        *,
        safety_threshold: int = DEFAULT_SAFETY_THRESHOLD,
        max_manifests: int = DEFAULT_MAX_MANIFESTS,
        now: Callable[[], float] = time.time,
    ) -> None:
        if safety_threshold < 0:
            raise ValueError("safety threshold cannot be negative")
        if max_manifests < 0:
            raise ValueError("max manifests cannot be negative")
        self.client = client
        self.checkpoint = checkpoint
        self.safety_threshold = safety_threshold
        self.max_manifests = max_manifests
        self.now = now

    def run(
        self,
        candidates: Sequence[RepoCandidate],
        *,
        limit: int | None = None,
        revalidate_succeeded: bool = False,
        max_cycles: int = 1,
    ) -> dict[str, Any]:
        if max_cycles < 1:
            raise ValueError("max_cycles must be at least 1")
        self.checkpoint.ensure_candidates(candidates)
        rate_before, before_records = self.client.core_rate_limit()
        pending = list(candidates[:limit] if limit is not None else candidates)
        results: list[RepoResult] = []
        stopped_reason: str | None = None
        latest_rate = rate_before
        cycles_used = 0
        waited_seconds = 0.0

        while True:
            cycles_used += 1
            stopped_reason = None
            while pending:
                if latest_rate.remaining is not None and (
                    latest_rate.remaining < self.safety_threshold
                ):
                    stopped_reason = "RATE_LIMIT_SAFETY_THRESHOLD"
                    break

                candidate = pending.pop(0)
                status = self.checkpoint.status(candidate.repo_id)
                if revalidate_succeeded:
                    if status != CollectionStatus.SUCCEEDED.value:
                        continue
                    result = self._revalidate(candidate)
                    self.checkpoint.record_revalidation(candidate.repo_id, result)
                else:
                    if status in {
                        CollectionStatus.SUCCEEDED.value,
                        CollectionStatus.NOT_FOUND.value,
                        CollectionStatus.PARTIAL.value,
                    }:
                        continue
                    result = self.fetch_repo(candidate)
                    self.checkpoint.record_result(result)
                results.append(result)
                record_rate = _last_rate(result.requests)
                if record_rate is not None:
                    latest_rate = record_rate
                if result.status == CollectionStatus.RATE_LIMITED.value:
                    pending.insert(0, candidate)
                    stopped_reason = "RATE_LIMIT_RESPONSE"
                    break

            if not pending or stopped_reason is None or cycles_used >= max_cycles:
                break
            delay = self._reset_delay(latest_rate)
            waited_seconds += delay
            self.client.sleep(delay)
            latest_rate, resumed_records = self.client.core_rate_limit()
            before_records = (*before_records, *resumed_records)

        self.checkpoint.save()
        rate_after, after_records = self.client.core_rate_limit()
        summary = benchmark_summary(
            results,
            mode="revalidation" if revalidate_succeeded else "full_fetch",
            rate_before=rate_before,
            rate_after=rate_after,
            control_records=(*before_records, *after_records),
            safety_threshold=self.safety_threshold,
            stopped_reason=stopped_reason,
        )
        summary["cycles_used"] = cycles_used
        summary["max_cycles"] = max_cycles
        summary["waited_seconds"] = waited_seconds
        summary["remaining_candidate_count"] = len(pending)
        summary["checkpoint_total"] = aggregate_results(
            self.checkpoint.results(), include_results=False
        )
        return summary

    def _reset_delay(self, rate: RateLimitState, *, minimum: float = 1.0) -> float:
        """Seconds to wait for the next core window.

        A multi-day bootstrap has to survive the hourly limit rather than exit
        at it, so the run sleeps to the reset the API reported and continues.
        """
        if rate.reset is None:
            return 3600.0
        return max(minimum, float(rate.reset) - self.now() + 1.0)

    def fetch_repo(self, candidate: RepoCandidate) -> RepoResult:
        result = RepoResult(
            repo_id=candidate.repo_id,
            repo_name=candidate.repo_name,
            rank=candidate.rank,
            stratum=candidate.stratum,
            status=CollectionStatus.PENDING.value,
        )
        encoded_repo = "/".join(
            urllib.parse.quote(part, safe="") for part in candidate.repo_name.split("/")
        )

        metadata = self.client.get_json(
            f"/repos/{encoded_repo}",
            stage=Stage.METADATA,
            endpoint_category="repository_metadata",
        )
        result.requests.extend(metadata.records)
        if not self._continue_after(
            metadata, result, missing_status=CollectionStatus.NOT_FOUND
        ):
            return result
        payload = metadata.payload or {}
        result.canonical_repo_name = _optional_str(payload.get("full_name"))
        result.renamed = bool(
            result.canonical_repo_name
            and result.canonical_repo_name.casefold() != candidate.repo_name.casefold()
        )
        result.default_branch = _optional_str(payload.get("default_branch"))
        result.archived = _optional_bool(payload.get("archived"))
        result.fork = _optional_bool(payload.get("fork"))
        result.visibility = _optional_str(payload.get("visibility"))
        if not result.default_branch:
            result.status = CollectionStatus.PARTIAL.value
            result.last_error = "repository has no default branch"
            return result

        head = self._fetch_head(candidate.repo_name, result.default_branch)
        result.requests.extend(head.records)
        if not self._continue_after(
            head, result, missing_status=CollectionStatus.PARTIAL
        ):
            return result
        head_payload = head.payload or {}
        commit = head_payload.get("commit")
        if not isinstance(commit, Mapping):
            return self._partial(result, "HEAD response has no commit object")
        result.pinned_commit_sha = _optional_str(commit.get("sha"))
        commit_detail = commit.get("commit")
        tree_sha: str | None = None
        if isinstance(commit_detail, Mapping):
            tree = commit_detail.get("tree")
            if isinstance(tree, Mapping):
                tree_sha = _optional_str(tree.get("sha"))
        tree_sha = tree_sha or result.pinned_commit_sha
        if not result.pinned_commit_sha or not tree_sha:
            return self._partial(result, "HEAD response has no pinned commit/tree SHA")

        tree = self.client.get_json(
            f"/repos/{encoded_repo}/git/trees/{urllib.parse.quote(tree_sha, safe='')}?recursive=1",
            stage=Stage.TREE,
            endpoint_category="recursive_tree",
        )
        result.requests.extend(tree.records)
        if not self._continue_after(
            tree, result, missing_status=CollectionStatus.PARTIAL
        ):
            return result
        tree_payload = tree.payload or {}
        entries = tree_payload.get("tree")
        if not isinstance(entries, list):
            return self._partial(result, "Tree response has no entry list")
        typed_entries = [entry for entry in entries if isinstance(entry, Mapping)]
        result.tree_entries = len(typed_entries)
        result.tree_truncated = bool(tree_payload.get("truncated"))
        result.manifest_candidates = select_manifest_candidates(
            typed_entries,
            limit=self.max_manifests,
        )

        raw_repo_name = result.canonical_repo_name or candidate.repo_name
        encoded_raw_repo = "/".join(
            urllib.parse.quote(part, safe="") for part in raw_repo_name.split("/")
        )
        manifest_failures = 0
        for path in result.manifest_candidates:
            encoded_path = urllib.parse.quote(path, safe="/")
            raw_url = f"{RAW_ROOT}/{encoded_raw_repo}/{result.pinned_commit_sha}/{encoded_path}"
            manifest = self.client.get_raw(raw_url)
            result.requests.extend(manifest.records)
            result.manifest_fetch_count += 1
            if manifest.response is not None and 200 <= manifest.response.status < 300:
                result.manifest_success_count += 1
            else:
                manifest_failures += 1

        result.artifact_key = f"github/{candidate.repo_id}/{result.pinned_commit_sha}"
        if result.tree_truncated:
            return self._partial(result, "recursive tree response is truncated")
        if manifest_failures:
            return self._partial(result, f"{manifest_failures} manifest fetches failed")
        result.status = CollectionStatus.SUCCEEDED.value
        return result

    def classify_missing(
        self,
        candidates: Sequence[RepoCandidate],
        *,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Explain NOT_FOUND rows using repo id and owner lookups.

        ``GET /repos/{owner}/{repo}`` already follows GitHub's 301 rename
        redirect, so a 404 there cannot be a plain rename.  This pass tests the
        remaining possibilities and costs up to two extra core calls per missing
        repository, which is why it is opt-in rather than part of ``run``.
        """
        missing = [
            candidate
            for candidate in candidates
            if self.checkpoint.status(candidate.repo_id)
            == CollectionStatus.NOT_FOUND.value
        ]
        if limit is not None:
            missing = missing[:limit]
        rows: list[dict[str, Any]] = []
        records: list[RequestRecord] = []
        for candidate in missing:
            by_id = self.client.get_json(
                f"/repositories/{candidate.repo_id}",
                stage=Stage.METADATA,
                endpoint_category="repository_by_id",
            )
            records.extend(by_id.records)
            status = by_id.response.status if by_id.response else 0
            row: dict[str, Any] = {
                "repo_id": candidate.repo_id,
                "historical_repo_name": candidate.repo_name,
                "rank": candidate.rank,
                "stratum": candidate.stratum,
                "repo_id_http_status": status,
                "current_repo_name": None,
                "owner_http_status": None,
                "reason": MissingReason.UNDETERMINED.value,
            }
            if 200 <= status < 300:
                payload = by_id.payload or {}
                row["current_repo_name"] = _optional_str(payload.get("full_name"))
                row["reason"] = MissingReason.RENAMED_OR_TRANSFERRED.value
                rows.append(row)
                continue
            if status == 404:
                owner = candidate.repo_name.split("/", 1)[0]
                owner_lookup = self.client.get_json(
                    f"/users/{urllib.parse.quote(owner, safe='')}",
                    stage=Stage.METADATA,
                    endpoint_category="owner_lookup",
                )
                records.extend(owner_lookup.records)
                owner_status = (
                    owner_lookup.response.status if owner_lookup.response else 0
                )
                row["owner_http_status"] = owner_status
                if owner_status == 404:
                    row["reason"] = MissingReason.OWNER_GONE.value
                elif 200 <= owner_status < 300:
                    row["reason"] = MissingReason.REPO_GONE_OWNER_ALIVE.value
            rows.append(row)
        return {
            "schema_version": "github-repo-fetch-missing-classification/v1",
            "generated_at": _utc_now(),
            "examined": len(rows),
            "core_calls": sum(record.is_core for record in records),
            "reason_counts": dict(
                sorted(Counter(row["reason"] for row in rows).items())
            ),
            "rows": rows,
        }

    def _revalidate(self, candidate: RepoCandidate) -> RepoResult:
        prior = self.checkpoint.prior_result(candidate.repo_id)
        result = RepoResult(
            repo_id=candidate.repo_id,
            repo_name=candidate.repo_name,
            rank=candidate.rank,
            stratum=candidate.stratum,
            status=CollectionStatus.PENDING.value,
        )
        if prior is None:
            return self._partial(result, "no prior result to revalidate")
        default_branch = _optional_str(prior.get("default_branch"))
        prior_sha = _optional_str(prior.get("pinned_commit_sha"))
        if not default_branch or not prior_sha:
            return self._partial(
                result, "prior result has no default branch or pinned SHA"
            )

        canonical = _optional_str(prior.get("canonical_repo_name"))
        head = self._fetch_head(canonical or candidate.repo_name, default_branch)
        result.requests.extend(head.records)
        if not self._continue_after(
            head, result, missing_status=CollectionStatus.PARTIAL
        ):
            return result
        payload = head.payload or {}
        commit = payload.get("commit")
        current_sha = (
            _optional_str(commit.get("sha")) if isinstance(commit, Mapping) else None
        )
        result.default_branch = default_branch
        result.pinned_commit_sha = current_sha
        if current_sha != prior_sha:
            result.status = CollectionStatus.PARTIAL.value
            result.last_error = "HEAD changed; a new full snapshot is required"
            return result

        result.status = CollectionStatus.SUCCEEDED.value
        result.cache_reused = True
        result.artifact_key = _optional_str(prior.get("artifact_key"))
        result.canonical_repo_name = _optional_str(prior.get("canonical_repo_name"))
        result.archived = _optional_bool(prior.get("archived"))
        result.fork = _optional_bool(prior.get("fork"))
        result.visibility = _optional_str(prior.get("visibility"))
        result.tree_truncated = _optional_bool(prior.get("tree_truncated"))
        result.tree_entries = _optional_int(prior.get("tree_entries"))
        return result

    def _fetch_head(self, repo_name: str, default_branch: str) -> RequestOutcome:
        encoded_repo = "/".join(
            urllib.parse.quote(part, safe="") for part in repo_name.split("/")
        )
        encoded_branch = urllib.parse.quote(default_branch, safe="")
        return self.client.get_json(
            f"/repos/{encoded_repo}/branches/{encoded_branch}",
            stage=Stage.HEAD,
            endpoint_category="default_branch_head",
        )

    def _continue_after(
        self,
        outcome: RequestOutcome,
        result: RepoResult,
        *,
        missing_status: CollectionStatus,
    ) -> bool:
        response = outcome.response
        if response is None:
            result.status = CollectionStatus.FAILED.value
            result.last_error = (
                outcome.records[-1].error if outcome.records else "request failed"
            )
            return False
        if 200 <= response.status < 300:
            return True
        if response.status == 404:
            result.status = missing_status.value
            result.last_error = "HTTP 404"
            return False
        rate = RateLimitState.from_headers(response.headers)
        lowered = {key.lower(): value for key, value in response.headers.items()}
        retry_after = lowered.get("retry-after")
        secondary = response.status == 403 and retry_after is not None
        primary = (
            response.status == 403
            and rate.remaining is not None
            and rate.remaining <= self.safety_threshold
        )
        if response.status == 429 or secondary or primary:
            result.status = CollectionStatus.RATE_LIMITED.value
            kind = "secondary" if secondary and not primary else "rate limit"
            result.last_error = f"HTTP {response.status} {kind}"
            return False
        if response.status in {401, 403}:
            result.status = CollectionStatus.FAILED.value
            result.last_error = f"HTTP {response.status} permission/authentication"
            return False
        result.status = CollectionStatus.FAILED.value
        result.last_error = f"HTTP {response.status}"
        return False

    @staticmethod
    def _partial(result: RepoResult, error: str) -> RepoResult:
        result.status = CollectionStatus.PARTIAL.value
        result.last_error = error
        return result


def benchmark_summary(
    results: Sequence[RepoResult],
    *,
    mode: str,
    rate_before: RateLimitState,
    rate_after: RateLimitState,
    control_records: Sequence[RequestRecord],
    safety_threshold: int,
    stopped_reason: str | None,
) -> dict[str, Any]:
    values = list(results)
    summary: dict[str, Any] = {
        "schema_version": "github-repo-fetch-benchmark/v1",
        "generated_at": _utc_now(),
        "mode": mode,
        "sample_size": len(values),
        "safety_threshold": safety_threshold,
        "stopped_reason": stopped_reason,
        "rate_limit_before": asdict(rate_before),
        "rate_limit_after": asdict(rate_after),
        "rate_limit_observed_delta": _remaining_delta(rate_before, rate_after),
        "control_request_count": len(control_records),
    }
    summary.update(aggregate_results(values, include_results=True))
    return summary


def aggregate_results(
    results: Sequence[RepoResult],
    *,
    include_results: bool,
) -> dict[str, Any]:
    values = list(results)
    status_counts = Counter(result.status for result in values)
    summary: dict[str, Any] = {
        "sample_size": len(values),
        "status_counts": dict(sorted(status_counts.items())),
        "repo_metrics": {
            "api_calls": distribution([float(item.api_calls) for item in values]),
            "core_calls": distribution([float(item.core_calls) for item in values]),
            "raw_calls": distribution([float(item.raw_calls) for item in values]),
            "response_bytes": distribution(
                [float(item.response_bytes) for item in values]
            ),
            "elapsed_seconds": distribution([item.elapsed_seconds for item in values]),
        },
        "stage_metrics": stage_summary(values),
        "outcome_metrics": outcome_metrics(values),
        "flags": {
            "archived": sum(item.archived is True for item in values),
            "fork": sum(item.fork is True for item in values),
            "renamed": sum(item.renamed for item in values),
            "truncated": sum(item.tree_truncated is True for item in values),
            "cache_reused": sum(item.cache_reused for item in values),
        },
    }
    if include_results:
        summary["results"] = [item.as_dict() for item in values]
    return summary


def outcome_metrics(results: Sequence[RepoResult]) -> dict[str, Any]:
    """Split cost by outcome.

    A NOT_FOUND repository costs one metadata call and returns no content, so a
    single blended mean across both outcomes understates the cost of a repository
    that is actually collected and overstates the coverage a run can reach.
    """
    grouped: dict[str, list[RepoResult]] = {}
    for item in results:
        grouped.setdefault(item.status, []).append(item)
    summary: dict[str, Any] = {}
    for status, items in sorted(grouped.items()):
        summary[status] = {
            "count": len(items),
            "core_calls": distribution([float(item.core_calls) for item in items]),
            "raw_calls": distribution([float(item.raw_calls) for item in items]),
            "response_bytes": distribution(
                [float(item.response_bytes) for item in items]
            ),
            "elapsed_seconds": distribution([item.elapsed_seconds for item in items]),
        }
    attempted = len(results)
    collected = len(grouped.get(CollectionStatus.SUCCEEDED.value, ()))
    missing = len(grouped.get(CollectionStatus.NOT_FOUND.value, ()))
    analyzable = sum(item.has_analyzable_artifact for item in results)
    budgets = [
        item.budget_consumed for item in results if item.budget_consumed is not None
    ]
    summary["totals"] = {
        "attempted": attempted,
        "collected": collected,
        "missing": missing,
        "analyzable": analyzable,
        "success_rate": (collected / attempted) if attempted else None,
        "missing_rate": (missing / attempted) if attempted else None,
        "artifact_rate": (analyzable / attempted) if attempted else None,
        "artifact_rate_given_collected": (analyzable / collected)
        if collected
        else None,
        "budget_consumed_total": sum(budgets) if budgets else None,
        "budget_vs_logged_core_calls": (
            sum(budgets)
            - sum(
                item.core_calls for item in results if item.budget_consumed is not None
            )
            if budgets
            else None
        ),
    }
    return summary


def stage_summary(results: Sequence[RepoResult]) -> dict[str, Any]:
    grouped: dict[str, list[RequestRecord]] = {stage.value: [] for stage in Stage}
    for result in results:
        for record in result.requests:
            grouped.setdefault(record.stage, []).append(record)
    summary: dict[str, Any] = {}
    for stage, records in grouped.items():
        if stage == Stage.CONTROL.value:
            continue
        summary[stage] = {
            "request_count": len(records),
            "response_bytes": sum(record.response_bytes for record in records),
            "elapsed_seconds": sum(record.elapsed_seconds for record in records),
            "http_status_counts": dict(
                sorted(Counter(record.http_status for record in records).items())
            ),
        }
    return summary


def distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
    }


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def estimate_bootstrap(
    summary: Mapping[str, Any],
    coverage_rows: Sequence[Mapping[str, Any]],
    *,
    candidate_sizes: Sequence[int],
) -> dict[str, Any]:
    metrics = summary.get("repo_metrics", {})
    core_mean = _nested_float(metrics, "core_calls", "mean")
    bytes_mean = _nested_float(metrics, "response_bytes", "mean")
    runtime_mean = _nested_float(metrics, "elapsed_seconds", "mean")
    rate = summary.get("rate_limit_before", {})
    rate_limit = _optional_int(rate.get("limit")) if isinstance(rate, Mapping) else None
    safety = _optional_int(summary.get("safety_threshold")) or 0
    if not core_mean or not rate_limit or rate_limit <= safety:
        return {"available": False, "reason": "insufficient benchmark/rate-limit data"}

    cycle_budget = rate_limit - safety
    rate_limited_per_hour = math.floor(cycle_budget / core_mean)
    runtime_limited_per_hour = (
        math.floor(3600 / runtime_mean)
        if runtime_mean and runtime_mean > 0
        else rate_limited_per_hour
    )
    repos_per_hour = max(1, min(rate_limited_per_hour, runtime_limited_per_hour))
    repos_per_day = repos_per_hour * 24
    success_rate = _total_rate(summary, "success_rate")
    artifact_rate = _total_rate(summary, "artifact_rate")
    projections: list[dict[str, Any]] = []
    for size in candidate_sizes:
        calls = size * core_mean
        active_runtime = size * (runtime_mean or 0)
        cycles = max(1, math.ceil(calls / cycle_budget))
        calendar_seconds = size / repos_per_hour * 3600
        coverage = coverage_for_n(coverage_rows, size)
        projection = {
            "repo_count": size,
            "coverage_valid": coverage,
            "estimated_core_calls": calls,
            "estimated_response_bytes": size * (bytes_mean or 0),
            "estimated_active_runtime_seconds": active_runtime,
            "estimated_calendar_seconds": calendar_seconds,
            "estimated_days": calendar_seconds / 86400,
            "rate_limit_cycles": cycles,
        }
        projection.update(_collected_view(size, coverage, success_rate, artifact_rate))
        projections.append(projection)

    estimate = {
        "available": True,
        "cycle_core_budget": cycle_budget,
        "repos_per_cycle": rate_limited_per_hour,
        "repos_per_hour": repos_per_hour,
        "repos_per_day": repos_per_day,
        "repo_count_basis": "attempted",
        "measured_success_rate": success_rate,
        "measured_artifact_rate": artifact_rate,
        "success_rate_basis": "rank_stratified_sample_not_population",
        "candidate_projections": projections,
    }
    if success_rate is not None:
        estimate["collected_repos_per_day"] = repos_per_day * success_rate
    if artifact_rate is not None:
        estimate["analyzable_repos_per_day"] = repos_per_day * artifact_rate
    return estimate


def _total_rate(summary: Mapping[str, Any], key: str) -> float | None:
    """Read one measured rate out of outcome_metrics, or None if not recorded."""
    outcome = summary.get("outcome_metrics")
    if not isinstance(outcome, Mapping):
        return None
    totals = outcome.get("totals")
    if not isinstance(totals, Mapping):
        return None
    value = totals.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _collected_view(
    attempted: int,
    coverage_attempted: float | None,
    success_rate: float | None,
    artifact_rate: float | None = None,
) -> dict[str, Any]:
    """Separate what a run *attempts* from what it actually *collects*.

    ``coverage_valid`` is the event share of a rank slice; it is only realised
    for repositories that still exist.  Reporting it as achieved coverage
    overstates the result by exactly the miss rate, so both are emitted.

    ``coverage_collected_uniform`` applies one sample-wide success rate to every
    rank.  The benchmark sample is rank-stratified, so that rate is not the
    population rate for any particular N; a rank-dependent model belongs in the
    analysis, not in this projection.
    """
    view: dict[str, Any] = {
        "attempted_repo_count": attempted,
        "coverage_attempted": coverage_attempted,
    }
    if success_rate is None:
        view["collected_repo_count"] = None
        view["coverage_collected_uniform"] = None
        return view
    view["collected_repo_count"] = int(attempted * success_rate)
    view["coverage_collected_uniform"] = (
        coverage_attempted * success_rate if coverage_attempted is not None else None
    )
    if artifact_rate is not None:
        view["analyzable_repo_count"] = int(attempted * artifact_rate)
        view["coverage_analyzable_uniform"] = (
            coverage_attempted * artifact_rate
            if coverage_attempted is not None
            else None
        )
    return view


def coverage_for_n(rows: Sequence[Mapping[str, Any]], n: int) -> float | None:
    points = sorted(
        (
            (int(row["top_n"]), float(row["coverage_valid"]))
            for row in rows
            if row.get("top_n") is not None and row.get("coverage_valid") is not None
        ),
        key=lambda item: item[0],
    )
    if not points or n < 0:
        return None
    for point_n, coverage in points:
        if n == point_n:
            return coverage
    if n < points[0][0]:
        return points[0][1] * n / points[0][0]
    for (left_n, left_value), (right_n, right_value) in pairwise(points):
        if left_n < n < right_n:
            fraction = (n - left_n) / (right_n - left_n)
            return left_value + (right_value - left_value) * fraction
    return None


def load_candidate_payload(
    path: Path,
) -> tuple[list[RepoCandidate], list[Mapping[str, Any]], str]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping) or not isinstance(
        loaded.get("candidates"), list
    ):
        raise TypeError("candidate payload must contain a candidates list")
    candidates = []
    for item in loaded["candidates"]:
        if not isinstance(item, Mapping):
            raise TypeError("candidate entry must be an object")
        candidates.append(
            RepoCandidate(
                repo_id=int(item["repo_id"]),
                repo_name=str(item["repo_name"]),
                rank=int(item["rank"]),
                stratum=str(item.get("stratum", "unspecified")),
            )
        )
    coverage = loaded.get("coverage", [])
    if not isinstance(coverage, list):
        raise TypeError("coverage must be a list")
    dataset_key = str(loaded.get("input_root", "unspecified"))
    return (
        candidates,
        [item for item in coverage if isinstance(item, Mapping)],
        dataset_key,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded, resumable GitHub Repo Fetch cost benchmark."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--safety-threshold", type=int, default=DEFAULT_SAFETY_THRESHOLD
    )
    parser.add_argument("--max-manifests", type=int, default=DEFAULT_MAX_MANIFESTS)
    parser.add_argument("--revalidate-succeeded", action="store_true")
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=1,
        help=(
            "number of rate-limit windows to use in one invocation; values "
            "above 1 sleep to the reported reset and continue"
        ),
    )
    parser.add_argument(
        "--classify-missing",
        type=Path,
        help=(
            "write a NOT_FOUND explanation report to this path; costs up to "
            "two extra core calls per missing repository"
        ),
    )
    parser.add_argument("--classify-missing-limit", type=int)
    parser.add_argument(
        "--flush-every",
        type=int,
        default=1,
        help=(
            "write the checkpoint every N repositories; the whole file is "
            "rewritten each time, so raise this for long runs"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    token = os.environ.get("GITHUB_API_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_API_TOKEN or GITHUB_TOKEN must be set")
    candidates, coverage, dataset_key = load_candidate_payload(arguments.candidates)
    checkpoint = CheckpointStore(
        arguments.checkpoint, flush_every=arguments.flush_every
    )
    checkpoint.bind_dataset(dataset_key)
    runner = RepoFetchBenchmark(
        GitHubClient(token),
        checkpoint,
        safety_threshold=arguments.safety_threshold,
        max_manifests=arguments.max_manifests,
    )
    summary = runner.run(
        candidates,
        limit=arguments.limit,
        revalidate_succeeded=arguments.revalidate_succeeded,
        max_cycles=arguments.max_cycles,
    )
    if arguments.classify_missing is not None:
        classification = runner.classify_missing(
            candidates, limit=arguments.classify_missing_limit
        )
        arguments.classify_missing.parent.mkdir(parents=True, exist_ok=True)
        with arguments.classify_missing.open(
            "w", encoding="utf-8", newline="\n"
        ) as stream:
            json.dump(
                classification, stream, ensure_ascii=False, indent=2, sort_keys=True
            )
            stream.write("\n")
        summary["missing_classification"] = {
            key: value for key, value in classification.items() if key != "rows"
        }
    if not arguments.revalidate_succeeded:
        projection_metrics = summary["checkpoint_total"]
        projection_input = {
            "safety_threshold": summary["safety_threshold"],
            "rate_limit_before": summary["rate_limit_before"],
            "repo_metrics": projection_metrics["repo_metrics"],
        }
        summary["bootstrap_estimate"] = estimate_bootstrap(
            projection_input,
            coverage,
            candidate_sizes=MVP_PHASE_SIZES,
        )
    arguments.summary.parent.mkdir(parents=True, exist_ok=True)
    with arguments.summary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "results"}, indent=2
        )
    )
    return 0


def _last_rate(records: Sequence[RequestRecord]) -> RateLimitState | None:
    for record in reversed(records):
        if record.rate_limit_remaining is not None:
            return RateLimitState(
                record.rate_limit_limit,
                record.rate_limit_remaining,
                record.rate_limit_used,
                record.rate_limit_reset,
                "core" if record.is_core else None,
            )
    return None


def _remaining_delta(before: RateLimitState, after: RateLimitState) -> int | None:
    if before.remaining is None or after.remaining is None:
        return None
    return before.remaining - after.remaining


def _nested_float(value: Any, first: str, second: str) -> float | None:
    if not isinstance(value, Mapping):
        return None
    child = value.get(first)
    if not isinstance(child, Mapping):
        return None
    raw = child.get(second)
    return float(raw) if isinstance(raw, (int, float)) else None


def _nested_or_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
