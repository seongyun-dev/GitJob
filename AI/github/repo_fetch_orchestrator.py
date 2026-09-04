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
)
from github.repo_fetch_policy import RepoFetchPolicy, select_artifacts
from github.repo_fetch_store import (
    ArtifactStore,
    FileArtifactStore,
    RepoFetchCheckpoint,
    RepoSnapshotCache,
)

COLLECTOR_VERSION = "gitjob-repo-fetch-orchestrator/v1"
TERMINAL_STATUSES = {
    "COMPLETE",
    "PARTIAL",
    "FAILED",
    "NOT_FOUND",
    "REUSED",
}


class RepoExecutionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    REUSED = "REUSED"


@dataclass(frozen=True)
class RepoActivityCandidate:
    repo_id: int
    repo_name: str
    activity_count: int
    activity_rank: int
    activity_metric: str
    activity_period_start: date
    activity_period_end: date

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


@dataclass(frozen=True)
class RepoExecution:
    candidate: RepoActivityCandidate
    status: RepoExecutionStatus
    record: GitHubRepoSnapshot | None
    requests: tuple[RequestRecord, ...]
    last_error: str | None = None

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

    def summary(self) -> dict[str, Any]:
        statuses = Counter(str(row["status"]) for row in self.checkpoint_rows)
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
            "core_rate_limit": {
                "limit": self.rate_limit_before.limit,
                "remaining": self.rate_limit_before.remaining,
                "used": self.rate_limit_before.used,
                "reset": self.rate_limit_before.reset,
            },
            "repos": self.checkpoint_rows,
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
    ) -> None:
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

    def run(self, candidates: Sequence[RepoActivityCandidate]) -> RepoFetchRun:
        ordered = _validate_candidates(candidates, self.policy.top_n_limit)
        generated_at = self.now().astimezone(UTC).isoformat().replace("+00:00", "Z")
        self.checkpoint.bind(
            dataset_snapshot_id=self.dataset_snapshot_id,
            pipeline_run_id=self.pipeline_run_id,
            collector_version=self.collector_version,
            policy_version=self.policy.cache_identity,
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
            )
        self.checkpoint.save()

        rate_before, control_requests = self.client.core_rate_limit()
        used_core_calls = sum(request.is_core for request in control_requests)
        started = self.monotonic()
        stopped_reason: str | None = None
        if (
            rate_before.remaining is not None
            and rate_before.remaining < self.policy.rate_limit_safety_threshold
        ):
            stopped_reason = "RATE_LIMIT_SAFETY_THRESHOLD"

        for candidate in ordered:
            if stopped_reason is not None:
                break
            if self.checkpoint.status(candidate.repo_id) in TERMINAL_STATUSES:
                continue
            if used_core_calls >= self.policy.max_api_calls:
                stopped_reason = "API_CALL_BUDGET"
                break
            if self.monotonic() - started >= self.policy.max_runtime_seconds:
                stopped_reason = "RUNTIME_BUDGET"
                break

            result = self.fetch_repo(candidate)
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
            )
            if (
                result.record is not None
                and result.record.collection_status is RepoCollectionStatus.COMPLETE
            ):
                self.cache.put(
                    policy_version=self.policy.cache_identity,
                    record=result.record,
                )
            if result.status is RepoExecutionStatus.RATE_LIMITED:
                stopped_reason = "RATE_LIMIT_RESPONSE"
            elif used_core_calls >= self.policy.max_api_calls:
                stopped_reason = "API_CALL_BUDGET"

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
            control_requests=control_requests,
            checkpoint_rows=self.checkpoint.summary_rows(),
        )

    def fetch_repo(self, candidate: RepoActivityCandidate) -> RepoExecution:
        requests: list[RequestRecord] = []
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

        cached = self.cache.get(
            policy_version=self.policy.cache_identity,
            repo_id=candidate.repo_id,
            pinned_commit_sha=pinned_commit_sha,
        )
        if cached is not None:
            record = self._reused_record(candidate, canonical_name, cached)
            return RepoExecution(
                candidate=candidate,
                status=RepoExecutionStatus.REUSED,
                record=record,
                requests=tuple(requests),
            )

        tree = self.client.get_json(
            (
                f"/repos/{_encode_repo(canonical_name)}/git/trees/"
                f"{pinned_commit_sha}?recursive=1"
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
            return self._after_pin_failure(
                candidate=candidate,
                canonical_name=canonical_name,
                pinned_commit_sha=pinned_commit_sha,
                tree_sha=head_tree_sha,
                state=state,
                error=error,
                requests=requests,
            )
        tree_payload = tree.payload
        entries = tree_payload.get("tree") if tree_payload is not None else None
        if not isinstance(entries, list):
            return self._after_pin_failure(
                candidate=candidate,
                canonical_name=canonical_name,
                pinned_commit_sha=pinned_commit_sha,
                tree_sha=head_tree_sha,
                state="FAILED",
                error="recursive Tree response has no entry list",
                requests=requests,
            )
        truncated_value = tree_payload.get("truncated")
        if not isinstance(truncated_value, bool):
            return self._after_pin_failure(
                candidate=candidate,
                canonical_name=canonical_name,
                pinned_commit_sha=pinned_commit_sha,
                tree_sha=head_tree_sha,
                state="FAILED",
                error="recursive Tree response has no boolean truncated flag",
                requests=requests,
            )
        typed_entries = [entry for entry in entries if isinstance(entry, Mapping)]
        observed_entries = min(len(typed_entries), self.policy.max_tree_entries)
        tree_sha = _valid_sha(tree_payload.get("sha")) or head_tree_sha
        tree_truncated = truncated_value
        selection = select_artifacts(typed_entries, self.policy)
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
    ) -> GitHubRepoSnapshot:
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
        reused_from_snapshot_id: str | None = None,
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
            tree_sha=tree_sha,
            collection_status=collection_status,
            collection_issues=collection_issues,
            checkpoint_uri=checkpoint_uri,
            reused_from_snapshot_id=reused_from_snapshot_id,
            tree_truncated=tree_truncated,
            observed_tree_entries=observed_tree_entries,
            artifacts=artifacts,
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
    parser.add_argument("--artifact-root", type=Path, required=True)
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
    policy = RepoFetchPolicy(
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
    run = RepoFetchOrchestrator(
        client=GitHubClient(token),
        policy=policy,
        artifact_store=FileArtifactStore(arguments.artifact_root),
        cache=RepoSnapshotCache(arguments.cache),
        checkpoint=RepoFetchCheckpoint(arguments.checkpoint),
        dataset_snapshot_id=arguments.dataset_snapshot_id,
        pipeline_run_id=arguments.pipeline_run_id,
        collector_version=arguments.collector_version,
    ).run(candidates)
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
    commit = payload.get("commit")
    if not isinstance(commit, Mapping):
        return None, None
    pinned = _valid_sha(commit.get("sha"))
    detail = commit.get("commit")
    tree_sha = None
    if isinstance(detail, Mapping):
        tree = detail.get("tree")
        if isinstance(tree, Mapping):
            tree_sha = _valid_sha(tree.get("sha"))
    return pinned, tree_sha


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
