"""GitHub Repo Fetch Orchestrator producing the C-team v1 snapshot contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.parse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from github.client import (
    RAW_ROOT,
    GitHubClient,
    RateLimitState,
    RequestOutcome,
    RequestRecord,
)
from github.contracts import (
    GITHUB_REPO_SNAPSHOT_SCHEMA_VERSION,
    GitHubRepoSnapshot,
    GitHubRepoSnapshotBatch,
    RepoArtifact,
    RepoArtifactType,
    RepoCollectionIssue,
    RepoCollectionStatus,
    RepoLanguageMetadata,
)
from github.redis_artifact_index import RedisArtifactIndex
from github.repo_fetch_policy import (
    RepoFetchPolicy,
    devops_artifact_category,
    select_artifacts,
    summarize_language_metadata,
)
from github.repo_fetch_store import (
    ArtifactStore,
    FileArtifactStore,
    RepoFetchCheckpoint,
    RepoSnapshotCache,
    WebHdfsArtifactStore,
)

COLLECTOR_VERSION = "gitjob-repo-fetch-orchestrator/v2"
TERMINAL_STATUSES = {
    "COMPLETE",
    "PARTIAL",
    "FAILED",
    "NOT_FOUND",
    "REUSED",
    "HISTORICAL_HEAD_UNAVAILABLE",
}


class RepoExecutionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    REUSED = "REUSED"
    HISTORICAL_HEAD_UNAVAILABLE = "HISTORICAL_HEAD_UNAVAILABLE"


@dataclass(frozen=True)
class RepoActivityCandidate:
    repo_id: int
    repo_name: str
    activity_count: int
    activity_rank: int
    activity_metric: str
    activity_period_start: date
    activity_period_end: date
    monthly_event_sha: str | None = None

    def __post_init__(self) -> None:
        if self.repo_id < 1:
            raise ValueError("repo_id must be positive")
        if "/" not in self.repo_name or self.repo_name != self.repo_name.strip():
            raise ValueError("repo_name must use owner/repository form")
        if self.activity_count < 0:
            raise ValueError("activity_count cannot be negative")
        if self.activity_rank < 1:
            raise ValueError("activity_rank must be positive")
        if not self.activity_metric.strip():
            raise ValueError("activity_metric must not be blank")
        if self.activity_period_start > self.activity_period_end:
            raise ValueError("activity period start must not be after end")
        if (
            self.monthly_event_sha is not None
            and _valid_sha(self.monthly_event_sha) is None
        ):
            raise ValueError("monthly_event_sha must be a lowercase 40-character SHA")


@dataclass(frozen=True)
class RepoExecution:
    candidate: RepoActivityCandidate
    status: RepoExecutionStatus
    record: GitHubRepoSnapshot | None
    requests: tuple[RequestRecord, ...]
    last_error: str | None = None
    selection_metrics: dict[str, Any] | None = None
    lineage: dict[str, Any] | None = None

    @property
    def api_calls(self) -> int:
        return len(self.requests)

    @property
    def core_calls(self) -> int:
        return sum(request.is_core for request in self.requests)

    @property
    def raw_calls(self) -> int:
        return self.api_calls - self.core_calls

    @property
    def http_statuses(self) -> list[int]:
        return [request.http_status for request in self.requests]


@dataclass(frozen=True)
class RepoFetchRun:
    batch: GitHubRepoSnapshotBatch
    stopped_reason: str | None
    rate_limit_before: RateLimitState
    control_requests: tuple[RequestRecord, ...]
    checkpoint_rows: list[dict[str, Any]]
    rate_limit_after: RateLimitState | None = None
    active_runtime_seconds: float = 0.0

    def summary(self) -> dict[str, Any]:
        statuses = Counter(str(row["status"]) for row in self.checkpoint_rows)
        artifact_categories = Counter(
            category
            for record in self.batch.records
            for artifact in record.artifacts
            if (category := devops_artifact_category(artifact.path)) is not None
        )
        language_repos = sum(
            bool(record.language_metadata) for record in self.batch.records
        )
        return {
            "schema_version": "github-repo-fetch-run-summary/v1",
            "dataset_snapshot_id": self.batch.dataset_snapshot_id,
            "pipeline_run_id": self.batch.pipeline_run_id,
            "generated_at": self.batch.generated_at.isoformat(),
            "stopped_reason": self.stopped_reason,
            "record_count": len(self.batch.records),
            "status_counts": dict(sorted(statuses.items())),
            "repo_api_calls": sum(
                int(row["api_calls"]) for row in self.checkpoint_rows
            ),
            "repo_core_calls": sum(
                int(row["core_calls"]) for row in self.checkpoint_rows
            ),
            "repo_raw_calls": sum(
                int(row["raw_calls"]) for row in self.checkpoint_rows
            ),
            "control_core_calls": sum(
                request.is_core for request in self.control_requests
            ),
            "active_runtime_seconds": self.active_runtime_seconds,
            "core_rate_limit_before": _rate_limit_payload(self.rate_limit_before),
            "core_rate_limit_after": _rate_limit_payload(
                self.rate_limit_after or self.rate_limit_before
            ),
            "core_rate_limit": {
                "limit": self.rate_limit_before.limit,
                "remaining": self.rate_limit_before.remaining,
                "used": self.rate_limit_before.used,
                "reset": self.rate_limit_before.reset,
            },
            "repos": self.checkpoint_rows,
            "historical_head_unavailable_count": statuses.get(
                "HISTORICAL_HEAD_UNAVAILABLE", 0
            ),
            "language_metadata_repo_count": language_repos,
            "devops_artifact_counts": dict(sorted(artifact_categories.items())),
        }


class RepoFetchOrchestrator:
    """Coordinate metadata, pinned SHA, tree, artifact, cache, and checkpoint."""

    def __init__(
        self,
        *,
        client: GitHubClient,
        policy: RepoFetchPolicy,
        artifact_store: ArtifactStore,
        cache: RepoSnapshotCache,
        checkpoint: RepoFetchCheckpoint,
        dataset_snapshot_id: str,
        pipeline_run_id: str,
        collector_version: str = COLLECTOR_VERSION,
        now: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
        monotonic: Callable[[], float] = time.monotonic,
        progress: Callable[[RepoExecution, int, int], None] | None = None,
        redis_index: RedisArtifactIndex | None = None,
        require_historical_head: bool = False,
    ) -> None:
        if require_historical_head and redis_index is not None:
            raise ValueError("Historical orchestrators cannot use Redis artifact index")
        metadata = {
            "dataset_snapshot_id": dataset_snapshot_id,
            "pipeline_run_id": pipeline_run_id,
            "collector_version": collector_version,
        }
        for name, value in metadata.items():
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        self.client = client
        self.policy = policy
        self.artifact_store = artifact_store
        self.cache = cache
        self.checkpoint = checkpoint
        self.dataset_snapshot_id = dataset_snapshot_id
        self.pipeline_run_id = pipeline_run_id
        self.collector_version = collector_version
        self.now = now
        self.monotonic = monotonic
        self.progress = progress
        self.redis_index = redis_index
        self.require_historical_head = require_historical_head
        self.materialization_context = artifact_store.materialization_context
        self.cache_policy_version = (
            f"{policy.cache_identity}:historical-head-required"
            if require_historical_head
            else policy.cache_identity
        )

    def run(
        self,
        candidates: Sequence[RepoActivityCandidate],
        *,
        prior_active_seconds: float = 0.0,
        prior_control_core_calls: int = 0,
    ) -> RepoFetchRun:
        if prior_active_seconds < 0 or prior_control_core_calls < 0:
            raise ValueError("prior run accounting cannot be negative")
        ordered = _validate_candidates(candidates, self.policy.top_n_limit)
        generated_at = self.now().astimezone(UTC).isoformat().replace("+00:00", "Z")
        self.checkpoint.bind(
            dataset_snapshot_id=self.dataset_snapshot_id,
            pipeline_run_id=self.pipeline_run_id,
            collector_version=self.collector_version,
            policy_version=self.cache_policy_version,
            generated_at=generated_at,
        )
        for candidate in ordered:
            self.checkpoint.ensure_candidate(
                repo_id=candidate.repo_id,
                repo_name=candidate.repo_name,
                rank=candidate.activity_rank,
                activity_count=candidate.activity_count,
                activity_metric=candidate.activity_metric,
                period_start=candidate.activity_period_start.isoformat(),
                period_end=candidate.activity_period_end.isoformat(),
                monthly_event_sha=candidate.monthly_event_sha,
            )
        self.checkpoint.save()

        rate_before, control_requests = self.client.core_rate_limit()
        rate_after = rate_before
        used_core_calls = (
            prior_control_core_calls
            + sum(int(row["core_calls"]) for row in self.checkpoint.summary_rows())
            + sum(request.is_core for request in control_requests)
        )
        started = self.monotonic()
        stopped_reason: str | None = None
        if (
            rate_before.remaining is not None
            and rate_before.remaining < self.policy.rate_limit_safety_threshold
        ):
            stopped_reason = "RATE_LIMIT_SAFETY_THRESHOLD"
        terminal_count = sum(
            self.checkpoint.status(candidate.repo_id) in TERMINAL_STATUSES
            for candidate in ordered
        )

        for candidate in ordered:
            if stopped_reason is not None:
                break
            if self.checkpoint.status(candidate.repo_id) in TERMINAL_STATUSES:
                self._repair_legacy_checkpoint_tree(candidate)
            if self.checkpoint.status(candidate.repo_id) in TERMINAL_STATUSES:
                continue
            if used_core_calls >= self.policy.max_api_calls:
                stopped_reason = "API_CALL_BUDGET"
                break
            if (
                prior_active_seconds + self.monotonic() - started
                >= self.policy.max_runtime_seconds
            ):
                stopped_reason = "RUNTIME_BUDGET"
                break

            result = self.fetch_repo(candidate)
            rate_after = _latest_rate_limit(result.requests, rate_after)
            used_core_calls += result.core_calls
            self.checkpoint.record(
                repo_id=candidate.repo_id,
                status=result.status.value,
                last_error=result.last_error,
                api_calls=result.api_calls,
                core_calls=result.core_calls,
                raw_calls=result.raw_calls,
                http_statuses=result.http_statuses,
                contract_record=result.record,
                selection_metrics=result.selection_metrics,
                lineage=result.lineage or _record_lineage(result.record),
            )
            if (
                result.record is not None
                and result.record.collection_status is RepoCollectionStatus.COMPLETE
            ):
                self.cache.put(
                    policy_version=self.cache_policy_version,
                    materialization_context=self.materialization_context,
                    record=result.record,
                )
            if result.status is RepoExecutionStatus.RATE_LIMITED:
                stopped_reason = "RATE_LIMIT_RESPONSE"
            elif used_core_calls >= self.policy.max_api_calls:
                stopped_reason = "API_CALL_BUDGET"
            if result.status.value in TERMINAL_STATUSES:
                terminal_count += 1
            if self.progress is not None:
                self.progress(result, terminal_count, len(ordered))

        self.cache.save()
        self.checkpoint.save()
        batch = GitHubRepoSnapshotBatch(
            schema_version=GITHUB_REPO_SNAPSHOT_SCHEMA_VERSION,
            dataset_snapshot_id=self.dataset_snapshot_id,
            pipeline_run_id=self.pipeline_run_id,
            collector_version=self.collector_version,
            generated_at=self.checkpoint.generated_at,
            collection_policy=self.policy.contract_policy(),
            records=self.checkpoint.contract_records(),
        )
        return RepoFetchRun(
            batch=batch,
            stopped_reason=stopped_reason,
            rate_limit_before=rate_before,
            rate_limit_after=rate_after,
            control_requests=control_requests,
            checkpoint_rows=self.checkpoint.summary_rows(),
            active_runtime_seconds=max(0.0, self.monotonic() - started),
        )

    def fetch_repo(self, candidate: RepoActivityCandidate) -> RepoExecution:
        requests: list[RequestRecord] = []
        if self.require_historical_head and candidate.monthly_event_sha is None:
            return self._historical_head_unavailable(
                candidate,
                reason="MONTHLY_EVENT_SHA_MISSING",
                requests=requests,
            )
        encoded_historical = _encode_repo(candidate.repo_name)
        metadata = self.client.get_json(
            f"/repos/{encoded_historical}",
            stage="A_METADATA",
            endpoint_category="repository_metadata",
        )
        requests.extend(metadata.records)
        state, error = _request_state(
            metadata,
            safety_threshold=self.policy.rate_limit_safety_threshold,
        )
        if state != "OK":
            return self._before_pin_failure(candidate, state, error, requests)
        payload = metadata.payload
        if payload is None:
            return self._before_pin_failure(
                candidate,
                "FAILED",
                "repository metadata is not a JSON object",
                requests,
            )
        response_repo_id = payload.get("id")
        if response_repo_id is not None and response_repo_id != candidate.repo_id:
            return self._before_pin_failure(
                candidate,
                "FAILED",
                "repository metadata id does not match candidate repo_id",
                requests,
            )
        canonical_name = _optional_str(payload.get("full_name")) or candidate.repo_name
        default_branch = _optional_str(payload.get("default_branch"))
        if default_branch is None:
            return self._before_pin_failure(
                candidate,
                "FAILED",
                "repository has no default branch",
                requests,
            )

        monthly_event_sha = candidate.monthly_event_sha
        pinned_commit_sha: str | None = None
        head_tree_sha: str | None = None
        current_default_head: str | None = None
        sha_source: str | None = None
        sha_fallback_reason: str | None = None

        if monthly_event_sha is not None:
            monthly = self.client.get_json(
                f"/repos/{_encode_repo(canonical_name)}/commits/{monthly_event_sha}",
                stage="B_MONTHLY_COMMIT",
                endpoint_category="monthly_event_commit",
            )
            requests.extend(monthly.records)
            monthly_state, monthly_error = _request_state(
                monthly,
                safety_threshold=self.policy.rate_limit_safety_threshold,
            )
            observed_sha, observed_tree_sha = _commit_shas(monthly.payload)
            if monthly_state == "OK" and observed_sha == monthly_event_sha:
                pinned_commit_sha = monthly_event_sha
                head_tree_sha = observed_tree_sha
                sha_source = "MONTH_EVENT_SHA"
            else:
                sha_fallback_reason = (
                    monthly_error or "MONTH_EVENT_SHA_RESPONSE_MISMATCH"
                )

        if self.require_historical_head and pinned_commit_sha is None:
            return self._historical_head_unavailable(
                candidate,
                reason=(f"HISTORICAL_MONTHLY_COMMIT_UNAVAILABLE:{sha_fallback_reason}"),
                requests=requests,
                selected_commit_sha=None,
            )
        if self.require_historical_head and head_tree_sha is None:
            return self._historical_head_unavailable(
                candidate,
                reason="HISTORICAL_COMMIT_TREE_UNAVAILABLE",
                requests=requests,
                selected_commit_sha=pinned_commit_sha,
            )

        if pinned_commit_sha is None:
            head = self.client.get_json(
                (
                    f"/repos/{_encode_repo(canonical_name)}/branches/"
                    f"{urllib.parse.quote(default_branch, safe='')}"
                ),
                stage="B_HEAD",
                endpoint_category="default_branch_head",
            )
            requests.extend(head.records)
            state, error = _request_state(
                head,
                safety_threshold=self.policy.rate_limit_safety_threshold,
            )
            if state != "OK":
                return self._before_pin_failure(candidate, state, error, requests)
            pinned_commit_sha, head_tree_sha = _commit_shas(head.payload)
            if pinned_commit_sha is None:
                return self._before_pin_failure(
                    candidate,
                    "FAILED",
                    "HEAD response has no valid pinned commit SHA",
                    requests,
                )
            current_default_head = pinned_commit_sha
            sha_source = "CURRENT_DEFAULT_HEAD"
            sha_fallback_reason = sha_fallback_reason or "MONTH_EVENT_SHA_NOT_AVAILABLE"

        if pinned_commit_sha is None or sha_source is None:
            return self._before_pin_failure(
                candidate,
                "FAILED",
                "commit selection did not produce a valid SHA",
                requests,
            )

        cached = self.cache.get(
            policy_version=self.cache_policy_version,
            materialization_context=self.materialization_context,
            repo_id=candidate.repo_id,
            pinned_commit_sha=pinned_commit_sha,
        )
        if cached is not None:
            if head_tree_sha is not None and cached.tree_sha != head_tree_sha:
                repaired = self.cache.repair_tree_sha(
                    policy_version=self.cache_policy_version,
                    materialization_context=self.materialization_context,
                    repo_id=candidate.repo_id,
                    pinned_commit_sha=pinned_commit_sha,
                    tree_sha=head_tree_sha,
                )
                if repaired is not None:
                    cached = repaired
            record = self._reused_record(
                candidate,
                canonical_name,
                cached,
                monthly_event_sha=monthly_event_sha,
                current_default_head=current_default_head,
                sha_source=sha_source,
                sha_fallback_reason=sha_fallback_reason,
            )
            return RepoExecution(
                candidate=candidate,
                status=RepoExecutionStatus.REUSED,
                record=record,
                requests=tuple(requests),
            )

        if self.redis_index is not None:
            redis_hit = self.redis_index.lookup(
                cache_policy_version=self.cache_policy_version,
                repo_id=candidate.repo_id,
                pinned_commit_sha=pinned_commit_sha,
                sha_source=sha_source,
                artifact_store=self.artifact_store,
            )
            if redis_hit is not None:
                record = self._redis_reused_record(
                    candidate,
                    canonical_name,
                    redis_hit,
                    current_default_head=current_default_head,
                    sha_fallback_reason=sha_fallback_reason,
                )
                return RepoExecution(
                    candidate=candidate,
                    status=RepoExecutionStatus.REUSED,
                    record=record,
                    requests=tuple(requests),
                )

        # The branch HEAD response is the authoritative source for the
        # pinned commit's root Git tree.  A GitHub Tree response may echo the
        # ref used in the request (including a commit SHA), so never use its
        # top-level ``sha`` to replace the tree SHA we already obtained from
        # the commit object.
        tree_request_sha = head_tree_sha or pinned_commit_sha
        tree = self.client.get_json(
            (
                f"/repos/{_encode_repo(canonical_name)}/git/trees/"
                f"{tree_request_sha}?recursive=1"
            ),
            stage="C_TREE",
            endpoint_category="recursive_tree",
        )
        requests.extend(tree.records)
        state, error = _request_state(
            tree,
            safety_threshold=self.policy.rate_limit_safety_threshold,
        )
        if state != "OK":
            if self.require_historical_head:
                return self._historical_head_unavailable(
                    candidate,
                    reason=f"HISTORICAL_TREE_UNAVAILABLE:{error or state}",
                    requests=requests,
                    selected_commit_sha=pinned_commit_sha,
                )
            return self._after_pin_failure(
                candidate=candidate,
                canonical_name=canonical_name,
                pinned_commit_sha=pinned_commit_sha,
                tree_sha=head_tree_sha,
                monthly_event_sha=monthly_event_sha,
                current_default_head=current_default_head,
                sha_source=sha_source,
                sha_fallback_reason=sha_fallback_reason,
                state=state,
                error=error,
                requests=requests,
            )
        tree_payload = tree.payload
        entries = tree_payload.get("tree") if tree_payload is not None else None
        if not isinstance(entries, list):
            if self.require_historical_head:
                return self._historical_head_unavailable(
                    candidate,
                    reason="HISTORICAL_TREE_UNAVAILABLE:ENTRY_LIST_MISSING",
                    requests=requests,
                    selected_commit_sha=pinned_commit_sha,
                )
            return self._after_pin_failure(
                candidate=candidate,
                canonical_name=canonical_name,
                pinned_commit_sha=pinned_commit_sha,
                tree_sha=head_tree_sha,
                monthly_event_sha=monthly_event_sha,
                current_default_head=current_default_head,
                sha_source=sha_source,
                sha_fallback_reason=sha_fallback_reason,
                state="FAILED",
                error="recursive Tree response has no entry list",
                requests=requests,
            )
        truncated_value = tree_payload.get("truncated")
        if not isinstance(truncated_value, bool):
            if self.require_historical_head:
                return self._historical_head_unavailable(
                    candidate,
                    reason="HISTORICAL_TREE_UNAVAILABLE:TRUNCATED_FLAG_MISSING",
                    requests=requests,
                    selected_commit_sha=pinned_commit_sha,
                )
            return self._after_pin_failure(
                candidate=candidate,
                canonical_name=canonical_name,
                pinned_commit_sha=pinned_commit_sha,
                tree_sha=head_tree_sha,
                monthly_event_sha=monthly_event_sha,
                current_default_head=current_default_head,
                sha_source=sha_source,
                sha_fallback_reason=sha_fallback_reason,
                state="FAILED",
                error="recursive Tree response has no boolean truncated flag",
                requests=requests,
            )
        typed_entries = [entry for entry in entries if isinstance(entry, Mapping)]
        observed_entries = min(len(typed_entries), self.policy.max_tree_entries)
        tree_sha = _authoritative_tree_sha(
            pinned_commit_sha=pinned_commit_sha,
            head_tree_sha=head_tree_sha,
            tree_payload=tree_payload,
        )
        if self.require_historical_head and tree_sha is None:
            return self._historical_head_unavailable(
                candidate,
                reason="HISTORICAL_TREE_UNAVAILABLE:TREE_SHA_MISSING",
                requests=requests,
                selected_commit_sha=pinned_commit_sha,
            )
        tree_truncated = truncated_value
        selection = select_artifacts(typed_entries, self.policy)
        language_metadata = summarize_language_metadata(typed_entries)
        issues = list(selection.issues)
        if len(typed_entries) != len(entries):
            issues.append(RepoCollectionIssue.ARTIFACT_FETCH_FAILED)
        if tree_truncated:
            issues.append(RepoCollectionIssue.TREE_TRUNCATED)

        artifacts: list[RepoArtifact] = []
        raw_paths = (
            *((RepoArtifactType.MANIFEST, path) for path in selection.manifest_paths),
            *((RepoArtifactType.SOURCE, path) for path in selection.source_paths),
        )
        total_bytes = 0
        rate_limited = False
        for artifact_type, path in raw_paths:
            prefix = (
                self.policy.source_prefix_bytes
                if artifact_type is RepoArtifactType.SOURCE
                else None
            )
            raw = self.client.get_raw(
                _raw_url(canonical_name, pinned_commit_sha, path),
                stage="D_ARTIFACT",
                endpoint_category=(
                    "source_raw"
                    if artifact_type is RepoArtifactType.SOURCE
                    else "manifest_raw"
                ),
                prefix_bytes=prefix,
            )
            requests.extend(raw.records)
            raw_state, _ = _request_state(
                raw,
                safety_threshold=self.policy.rate_limit_safety_threshold,
                require_json=False,
            )
            if raw_state == "RATE_LIMITED":
                issues.append(RepoCollectionIssue.RATE_LIMITED)
                rate_limited = True
                break
            if raw_state != "OK" or raw.response is None:
                issues.append(RepoCollectionIssue.ARTIFACT_FETCH_FAILED)
                continue
            content = raw.response.body
            if len(content) > self.policy.max_file_bytes:
                issues.append(RepoCollectionIssue.BYTE_LIMIT_REACHED)
                continue
            if total_bytes + len(content) > self.policy.max_artifact_bytes:
                issues.append(RepoCollectionIssue.BYTE_LIMIT_REACHED)
                break
            try:
                uri = self.artifact_store.store(
                    policy_version=self.policy.cache_identity,
                    repo_id=candidate.repo_id,
                    pinned_commit_sha=pinned_commit_sha,
                    path=path,
                    content=content,
                )
            except (OSError, ValueError) as exc:
                issues.append(RepoCollectionIssue.ARTIFACT_FETCH_FAILED)
                error = f"artifact store failed: {type(exc).__name__}"
                continue
            artifacts.append(
                RepoArtifact(
                    artifact_type=artifact_type,
                    path=path,
                    uri=uri,
                    content_hash=hashlib.sha256(content).hexdigest(),
                    size_bytes=len(content),
                )
            )
            total_bytes += len(content)

        unique_issues = tuple(dict.fromkeys(issues))
        collection_status = (
            RepoCollectionStatus.PARTIAL
            if unique_issues
            else RepoCollectionStatus.COMPLETE
        )
        record = self._record(
            candidate=candidate,
            canonical_name=canonical_name,
            pinned_commit_sha=pinned_commit_sha,
            tree_sha=tree_sha,
            collection_status=collection_status,
            collection_issues=unique_issues,
            checkpoint_uri=self.checkpoint.uri if rate_limited else None,
            tree_truncated=tree_truncated,
            observed_tree_entries=observed_entries,
            artifacts=tuple(artifacts),
            language_metadata=language_metadata,
            monthly_event_sha=monthly_event_sha,
            current_default_head=current_default_head,
            sha_source=sha_source,
            sha_fallback_reason=sha_fallback_reason,
        )
        if (
            self.redis_index is not None
            and collection_status is RepoCollectionStatus.COMPLETE
            and artifacts
        ):
            self.redis_index.put(
                cache_policy_version=self.cache_policy_version,
                repo_id=candidate.repo_id,
                pinned_commit_sha=pinned_commit_sha,
                sha_source=sha_source,
                artifacts=tuple(artifacts),
            )
        status = (
            RepoExecutionStatus.RATE_LIMITED
            if rate_limited
            else RepoExecutionStatus(collection_status.value)
        )
        last_error = error if unique_issues else None
        if unique_issues and last_error is None:
            last_error = ",".join(issue.value for issue in unique_issues)
        return RepoExecution(
            candidate=candidate,
            status=status,
            record=record,
            requests=tuple(requests),
            last_error=last_error,
            selection_metrics=selection.metrics(),
        )

    def _historical_head_unavailable(
        self,
        candidate: RepoActivityCandidate,
        *,
        reason: str,
        requests: Sequence[RequestRecord],
        selected_commit_sha: str | None = None,
    ) -> RepoExecution:
        """Record an excluded monthly candidate without pinning current HEAD."""

        return RepoExecution(
            candidate=candidate,
            status=RepoExecutionStatus.HISTORICAL_HEAD_UNAVAILABLE,
            record=None,
            requests=tuple(requests),
            last_error=reason,
            lineage={
                "selected_commit_sha": selected_commit_sha,
                "sha_source": "HISTORICAL_HEAD_UNAVAILABLE",
                "monthly_event_sha": candidate.monthly_event_sha,
                "current_default_head": None,
                "sha_fallback_reason": reason,
                "target_period": (
                    f"{candidate.activity_period_start.isoformat()}"
                    f"/{candidate.activity_period_end.isoformat()}"
                ),
            },
        )

    def _repair_legacy_checkpoint_tree(self, candidate: RepoActivityCandidate) -> None:
        """Repair terminal checkpoint metadata without refetching artifacts."""

        existing = self.checkpoint.contract_record(candidate.repo_id)
        if existing is None or existing.tree_sha != existing.pinned_commit_sha:
            return
        response = self.client.get_json(
            (
                f"/repos/{_encode_repo(existing.repo_full_name)}/git/commits/"
                f"{existing.pinned_commit_sha}"
            ),
            stage="B_COMMIT_TREE_REPAIR",
            endpoint_category="commit_tree",
        )
        state, error = _request_state(
            response,
            safety_threshold=self.policy.rate_limit_safety_threshold,
        )
        tree_sha: str | None = None
        if state == "OK" and isinstance(response.payload, Mapping):
            tree = response.payload.get("tree")
            if isinstance(tree, Mapping):
                observed = _valid_sha(tree.get("sha"))
                if observed != existing.pinned_commit_sha:
                    tree_sha = observed
        self.checkpoint.record_tree_repair_requests(
            repo_id=candidate.repo_id,
            requests=response.records,
            last_error=(
                None
                if tree_sha is not None
                else error or "checkpoint tree metadata could not be verified"
            ),
        )
        self.checkpoint.repair_tree_sha(
            repo_id=candidate.repo_id,
            tree_sha=tree_sha,
        )

    def _before_pin_failure(
        self,
        candidate: RepoActivityCandidate,
        state: str,
        error: str | None,
        requests: Sequence[RequestRecord],
    ) -> RepoExecution:
        status = {
            "NOT_FOUND": RepoExecutionStatus.NOT_FOUND,
            "RATE_LIMITED": RepoExecutionStatus.RATE_LIMITED,
        }.get(state, RepoExecutionStatus.FAILED)
        return RepoExecution(
            candidate=candidate,
            status=status,
            record=None,
            requests=tuple(requests),
            last_error=error,
        )

    def _after_pin_failure(
        self,
        *,
        candidate: RepoActivityCandidate,
        canonical_name: str,
        pinned_commit_sha: str,
        tree_sha: str | None,
        monthly_event_sha: str | None,
        current_default_head: str | None,
        sha_source: str,
        sha_fallback_reason: str | None,
        state: str,
        error: str | None,
        requests: Sequence[RequestRecord],
    ) -> RepoExecution:
        rate_limited = state == "RATE_LIMITED"
        issue = (
            RepoCollectionIssue.RATE_LIMITED
            if rate_limited
            else RepoCollectionIssue.REPOSITORY_UNAVAILABLE
            if state == "NOT_FOUND"
            else RepoCollectionIssue.ARTIFACT_FETCH_FAILED
        )
        collection_status = (
            RepoCollectionStatus.PARTIAL
            if rate_limited
            else RepoCollectionStatus.FAILED
        )
        record = self._record(
            candidate=candidate,
            canonical_name=canonical_name,
            pinned_commit_sha=pinned_commit_sha,
            tree_sha=tree_sha,
            collection_status=collection_status,
            collection_issues=(issue,),
            checkpoint_uri=self.checkpoint.uri if rate_limited else None,
            tree_truncated=False,
            observed_tree_entries=0,
            artifacts=(),
            monthly_event_sha=monthly_event_sha,
            current_default_head=current_default_head,
            sha_source=sha_source,
            sha_fallback_reason=sha_fallback_reason,
        )
        return RepoExecution(
            candidate=candidate,
            status=(
                RepoExecutionStatus.RATE_LIMITED
                if rate_limited
                else RepoExecutionStatus.FAILED
            ),
            record=record,
            requests=tuple(requests),
            last_error=error,
        )

    def _reused_record(
        self,
        candidate: RepoActivityCandidate,
        canonical_name: str,
        cached: GitHubRepoSnapshot,
        *,
        monthly_event_sha: str | None,
        current_default_head: str | None,
        sha_source: str,
        sha_fallback_reason: str | None,
    ) -> GitHubRepoSnapshot:
        cached_source = cached.sha_source or sha_source
        cached_monthly_sha = cached.monthly_event_sha or monthly_event_sha
        cached_current_head = cached.current_default_head or current_default_head
        cached_reason = cached.sha_fallback_reason or sha_fallback_reason
        return self._record(
            candidate=candidate,
            canonical_name=canonical_name,
            pinned_commit_sha=cached.pinned_commit_sha,
            tree_sha=cached.tree_sha,
            collection_status=RepoCollectionStatus.REUSED,
            collection_issues=(),
            checkpoint_uri=None,
            reused_from_snapshot_id=cached.repo_snapshot_id,
            tree_truncated=False,
            observed_tree_entries=cached.observed_tree_entries,
            artifacts=cached.artifacts,
            language_metadata=cached.language_metadata,
            monthly_event_sha=cached_monthly_sha,
            current_default_head=cached_current_head,
            sha_source=cached_source,
            sha_fallback_reason=cached_reason,
        )

    def _redis_reused_record(
        self,
        candidate: RepoActivityCandidate,
        canonical_name: str,
        hit: Any,
        *,
        current_default_head: str | None,
        sha_fallback_reason: str | None,
    ) -> GitHubRepoSnapshot:
        return self._record(
            candidate=candidate,
            canonical_name=canonical_name,
            pinned_commit_sha=hit.pinned_commit_sha,
            tree_sha=None,
            collection_status=RepoCollectionStatus.REUSED,
            collection_issues=(),
            checkpoint_uri=None,
            reused_from_snapshot_id=(
                f"redis-artifact-index-repo-{candidate.repo_id}-"
                f"{hit.pinned_commit_sha[:12]}"
            ),
            tree_truncated=False,
            observed_tree_entries=0,
            artifacts=hit.artifacts,
            current_default_head=current_default_head,
            sha_source=hit.sha_source,
            sha_fallback_reason=sha_fallback_reason,
        )

    def _record(
        self,
        *,
        candidate: RepoActivityCandidate,
        canonical_name: str,
        pinned_commit_sha: str,
        tree_sha: str | None,
        collection_status: RepoCollectionStatus,
        collection_issues: tuple[RepoCollectionIssue, ...],
        checkpoint_uri: str | None,
        tree_truncated: bool,
        observed_tree_entries: int,
        artifacts: tuple[RepoArtifact, ...],
        language_metadata: tuple[RepoLanguageMetadata, ...] = (),
        reused_from_snapshot_id: str | None = None,
        monthly_event_sha: str | None = None,
        current_default_head: str | None = None,
        sha_source: str | None = None,
        sha_fallback_reason: str | None = None,
    ) -> GitHubRepoSnapshot:
        return GitHubRepoSnapshot(
            repo_snapshot_id=(
                f"{self.dataset_snapshot_id}-repo-{candidate.repo_id}-"
                f"{pinned_commit_sha[:12]}"
            ),
            github_repo_id=candidate.repo_id,
            repo_full_name=canonical_name,
            activity_metric=candidate.activity_metric,
            activity_period_start=candidate.activity_period_start,
            activity_period_end=candidate.activity_period_end,
            activity_count=candidate.activity_count,
            activity_rank=candidate.activity_rank,
            pinned_commit_sha=pinned_commit_sha,
            selected_commit_sha=pinned_commit_sha if sha_source else None,
            sha_source=sha_source,
            monthly_event_sha=monthly_event_sha,
            current_default_head=current_default_head,
            sha_fallback_reason=sha_fallback_reason,
            target_period=(
                f"{candidate.activity_period_start.isoformat()}"
                f"/{candidate.activity_period_end.isoformat()}"
            )
            if sha_source
            else None,
            tree_sha=tree_sha,
            collection_status=collection_status,
            collection_issues=collection_issues,
            checkpoint_uri=checkpoint_uri,
            reused_from_snapshot_id=reused_from_snapshot_id,
            tree_truncated=tree_truncated,
            observed_tree_entries=observed_tree_entries,
            artifacts=artifacts,
            language_metadata=language_metadata,
        )


def load_candidates(
    path: Path,
    *,
    activity_metric: str,
    period_start: date,
    period_end: date,
    limit: int,
) -> tuple[str, tuple[RepoActivityCandidate, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("candidate payload must be an object")
    if payload.get("schema_version") != "repo-fetch-candidates/v1":
        raise ValueError("unsupported candidate schema_version")
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        raise TypeError("candidate payload must contain a candidates array")
    source_dataset = payload.get("input_root")
    if not isinstance(source_dataset, str) or not source_dataset.strip():
        raise ValueError("candidate payload input_root must not be blank")
    candidates = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("candidate row must be an object")
        candidates.append(
            RepoActivityCandidate(
                repo_id=_required_int(row, "repo_id"),
                repo_name=_required_str(row, "repo_name"),
                activity_count=_required_int(row, "activity_count"),
                activity_rank=_required_int(row, "rank"),
                activity_metric=activity_metric,
                activity_period_start=period_start,
                activity_period_end=period_end,
                monthly_event_sha=_optional_sha(row.get("monthly_event_sha")),
            )
        )
    ordered = _validate_candidates(candidates, limit)
    return source_dataset, ordered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch pinned GitHub repo artifacts into the v1 A-to-C contract."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    artifact_group = parser.add_mutually_exclusive_group(required=True)
    artifact_group.add_argument("--artifact-root", type=Path)
    artifact_group.add_argument("--webhdfs-artifact-root")
    parser.add_argument(
        "--artifact-store",
        choices=("file", "webhdfs"),
        default="file",
    )
    parser.add_argument("--webhdfs-url")
    parser.add_argument("--webhdfs-user", default="hadoop")
    parser.add_argument("--webhdfs-timeout", type=float, default=120.0)
    parser.add_argument("--dataset-snapshot-id", required=True)
    parser.add_argument("--pipeline-run-id", required=True)
    parser.add_argument("--collector-version", default=COLLECTOR_VERSION)
    parser.add_argument("--activity-metric", default="gh_archive_event_count")
    parser.add_argument("--period-start", type=date.fromisoformat, required=True)
    parser.add_argument("--period-end", type=date.fromisoformat, required=True)
    parser.add_argument("--limit", type=int, default=20_000)
    parser.add_argument("--policy-version", default="repo-fetch-policy/v1")
    parser.add_argument("--max-api-calls", type=int, default=60_000)
    parser.add_argument("--max-runtime-seconds", type=int, default=86_400)
    parser.add_argument("--max-tree-entries", type=int, default=100_000)
    parser.add_argument("--max-artifact-files", type=int, default=24)
    parser.add_argument("--max-artifact-bytes", type=int, default=1_048_576)
    parser.add_argument("--max-manifest-files", type=int, default=24)
    parser.add_argument("--max-source-files", type=int, default=0)
    parser.add_argument("--max-file-bytes", type=int, default=262_144)
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument("--source-prefix-bytes", type=int, default=8_192)
    parser.add_argument("--rate-limit-safety-threshold", type=int, default=200)
    parser.add_argument(
        "--require-historical-head",
        action="store_true",
        help=(
            "Do not fall back to the current default branch head when the "
            "monthly historical commit/tree cannot be resolved."
        ),
    )
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    token = os.environ.get(arguments.token_env)
    if not token:
        raise SystemExit(f"GitHub token environment is missing: {arguments.token_env}")
    _, candidates = load_candidates(
        arguments.candidates,
        activity_metric=arguments.activity_metric,
        period_start=arguments.period_start,
        period_end=arguments.period_end,
        limit=arguments.limit,
    )
    run = create_orchestrator(arguments, token=token).run(candidates)
    if run.stopped_reason is None:
        _immutable_payload_write(arguments.output, run.batch.model_dump(mode="json"))
    if arguments.summary_output is not None:
        _replace_payload(arguments.summary_output, run.summary())
    print(
        json.dumps(
            {
                "dataset_snapshot_id": run.batch.dataset_snapshot_id,
                "record_count": len(run.batch.records),
                "stopped_reason": run.stopped_reason,
                "snapshot_published": run.stopped_reason is None,
                "checkpoint": str(arguments.checkpoint),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def create_policy(arguments: argparse.Namespace) -> RepoFetchPolicy:
    return RepoFetchPolicy(
        policy_version=arguments.policy_version,
        top_n_limit=arguments.limit,
        max_api_calls=arguments.max_api_calls,
        max_runtime_seconds=arguments.max_runtime_seconds,
        max_tree_entries=arguments.max_tree_entries,
        max_artifact_files=arguments.max_artifact_files,
        max_artifact_bytes=arguments.max_artifact_bytes,
        max_manifest_files=arguments.max_manifest_files,
        max_source_files=arguments.max_source_files,
        max_file_bytes=arguments.max_file_bytes,
        max_depth=arguments.max_depth,
        source_prefix_bytes=arguments.source_prefix_bytes,
        rate_limit_safety_threshold=arguments.rate_limit_safety_threshold,
    )


def create_orchestrator(
    arguments: argparse.Namespace,
    *,
    token: str,
    progress: Callable[[RepoExecution, int, int], None] | None = None,
) -> RepoFetchOrchestrator:
    artifact_store = create_artifact_store(arguments)
    redis_index = None
    if bool(getattr(arguments, "weekly_redis_enabled", False)):
        redis_index = create_redis_artifact_index(
            materialization_context=artifact_store.materialization_context,
        )
    return RepoFetchOrchestrator(
        client=GitHubClient(token),
        policy=create_policy(arguments),
        artifact_store=artifact_store,
        cache=RepoSnapshotCache(arguments.cache),
        checkpoint=RepoFetchCheckpoint(arguments.checkpoint),
        dataset_snapshot_id=arguments.dataset_snapshot_id,
        pipeline_run_id=arguments.pipeline_run_id,
        collector_version=arguments.collector_version,
        progress=progress,
        redis_index=redis_index,
        require_historical_head=arguments.require_historical_head,
    )


def create_redis_artifact_index(
    *,
    materialization_context: str,
) -> RedisArtifactIndex | None:
    """Create the optional Weekly Redis index without making Redis mandatory."""

    try:
        import redis

        ttl_seconds = int(
            os.environ.get("WEEKLY_REDIS_ARTIFACT_INDEX_TTL_SECONDS", "2592000")
        )
        namespace = os.environ.get(
            "WEEKLY_REDIS_ARTIFACT_INDEX_NAMESPACE",
            "gitjob:weekly:artifact-index:v1",
        )
        redis_url = os.environ.get("WEEKLY_REDIS_URL")
        if redis_url:
            client = redis.Redis.from_url(
                redis_url,
                decode_responses=False,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
        else:
            host = os.environ.get("REDIS_HOST")
            if not host:
                return None
            client = redis.Redis(
                host=host,
                port=int(os.environ.get("REDIS_PORT", "6379")),
                db=int(os.environ.get("WEEKLY_REDIS_DB", "1")),
                password=os.environ.get("REDIS_PASSWORD") or None,
                decode_responses=False,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
        return RedisArtifactIndex(
            client,
            materialization_context=materialization_context,
            ttl_seconds=ttl_seconds,
            namespace=namespace,
        )
    except (ImportError, TypeError, ValueError):
        return None


def create_artifact_store(arguments: argparse.Namespace) -> ArtifactStore:
    if arguments.artifact_store == "file":
        if arguments.artifact_root is None:
            raise ValueError("--artifact-root is required for --artifact-store file")
        return FileArtifactStore(arguments.artifact_root)
    if not arguments.webhdfs_url:
        raise ValueError("--webhdfs-url is required for --artifact-store webhdfs")
    if arguments.webhdfs_artifact_root is None:
        raise ValueError(
            "--webhdfs-artifact-root is required for --artifact-store webhdfs"
        )
    return WebHdfsArtifactStore(
        base_url=arguments.webhdfs_url,
        root=arguments.webhdfs_artifact_root,
        user=arguments.webhdfs_user,
        timeout=arguments.webhdfs_timeout,
    )


def _rate_limit_payload(state: RateLimitState) -> dict[str, int | str | None]:
    return {
        "limit": state.limit,
        "remaining": state.remaining,
        "used": state.used,
        "reset": state.reset,
        "resource": state.resource,
    }


def _latest_rate_limit(
    requests: Sequence[RequestRecord],
    fallback: RateLimitState,
) -> RateLimitState:
    for request in reversed(requests):
        if any(
            value is not None
            for value in (
                request.rate_limit_limit,
                request.rate_limit_remaining,
                request.rate_limit_used,
                request.rate_limit_reset,
            )
        ):
            return RateLimitState(
                limit=request.rate_limit_limit,
                remaining=request.rate_limit_remaining,
                used=request.rate_limit_used,
                reset=request.rate_limit_reset,
                resource="core" if request.is_core else None,
            )
    return fallback


def _request_state(
    outcome: RequestOutcome,
    *,
    safety_threshold: int,
    require_json: bool = True,
) -> tuple[str, str | None]:
    response = outcome.response
    if response is None:
        error = outcome.records[-1].error if outcome.records else "request failed"
        return "FAILED", error
    if 200 <= response.status < 300:
        if require_json and outcome.payload is None:
            return "FAILED", "response is not a JSON object"
        return "OK", None
    if response.status == 404:
        return "NOT_FOUND", "HTTP 404"
    rate = RateLimitState.from_headers(response.headers)
    lowered = {key.lower(): value for key, value in response.headers.items()}
    secondary = response.status == 403 and lowered.get("retry-after") is not None
    primary = (
        response.status == 403
        and rate.remaining is not None
        and rate.remaining <= safety_threshold
    )
    if response.status == 429 or secondary or primary:
        return "RATE_LIMITED", f"HTTP {response.status} rate limit"
    if response.status in {401, 403}:
        return "FAILED", f"HTTP {response.status} permission/authentication"
    return "FAILED", f"HTTP {response.status}"


def _commit_shas(payload: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    if payload is None:
        return None, None
    pinned = _valid_sha(payload.get("sha"))
    commit = payload.get("commit")
    if isinstance(commit, Mapping):
        pinned = pinned or _valid_sha(commit.get("sha"))
    else:
        commit = None
    detail = commit.get("commit") if isinstance(commit, Mapping) else None
    if detail is None and isinstance(commit, Mapping):
        detail = commit
    tree_sha = None
    if isinstance(detail, Mapping):
        tree = detail.get("tree")
        if isinstance(tree, Mapping):
            tree_sha = _valid_sha(tree.get("sha"))
    if tree_sha is None:
        tree = payload.get("tree")
        if isinstance(tree, Mapping):
            tree_sha = _valid_sha(tree.get("sha"))
    return pinned, tree_sha


def _authoritative_tree_sha(
    *,
    pinned_commit_sha: str,
    head_tree_sha: str | None,
    tree_payload: Mapping[str, Any],
) -> str | None:
    """Return a Git tree SHA without confusing it with the pinned commit SHA.

    The commit object's nested ``tree.sha`` is authoritative.  Older GitHub
    responses and test doubles can expose the request ref as the Tree
    response's top-level ``sha``; when that ref is the commit SHA, storing it
    as ``tree_sha`` would collapse the two distinct lineage fields.  A Tree
    response can still supply the SHA when the commit object omitted it, but a
    value equal to the commit SHA is rejected as ambiguous.
    """

    if head_tree_sha is not None:
        return head_tree_sha
    response_tree_sha = _valid_sha(tree_payload.get("sha"))
    if response_tree_sha == pinned_commit_sha:
        return None
    return response_tree_sha


def _valid_sha(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 40:
        return None
    if any(character not in "0123456789abcdef" for character in value):
        return None
    return value


def _validate_candidates(
    candidates: Sequence[RepoActivityCandidate],
    limit: int,
) -> tuple[RepoActivityCandidate, ...]:
    if limit < 1:
        raise ValueError("top_n limit must be positive")
    if len(candidates) > limit:
        raise ValueError("candidate rows exceed top_n limit")
    ordered = tuple(sorted(candidates, key=lambda candidate: candidate.activity_rank))
    identities = (
        [candidate.repo_id for candidate in ordered],
        [candidate.repo_name.casefold() for candidate in ordered],
        [candidate.activity_rank for candidate in ordered],
    )
    if any(len(values) != len(set(values)) for values in identities):
        raise ValueError("candidate repo id, name, and rank must be unique")
    return ordered


def _encode_repo(repo_name: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in repo_name.split("/"))


def _raw_url(repo_name: str, pinned_commit_sha: str, path: str) -> str:
    return (
        f"{RAW_ROOT}/{_encode_repo(repo_name)}/{pinned_commit_sha}/"
        f"{urllib.parse.quote(path, safe='/')}"
    )


def _required_int(payload: Mapping[str, Any], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _required_str(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_sha(value: object) -> str | None:
    if value is None:
        return None
    parsed = _valid_sha(value)
    if parsed is None:
        raise ValueError("monthly_event_sha must be a lowercase 40-character SHA")
    return parsed


def _record_lineage(record: GitHubRepoSnapshot | None) -> dict[str, Any] | None:
    if record is None or record.sha_source is None:
        return None
    return {
        "selected_commit_sha": record.selected_commit_sha,
        "sha_source": record.sha_source,
        "monthly_event_sha": record.monthly_event_sha,
        "current_default_head": record.current_default_head,
        "sha_fallback_reason": record.sha_fallback_reason,
        "target_period": record.target_period,
    }


def _immutable_payload_write(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing == payload:
            return
        raise FileExistsError("snapshot output already exists with different content")
    _replace_payload(path, payload)


def _replace_payload(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
