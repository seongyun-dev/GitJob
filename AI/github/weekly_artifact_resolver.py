"""Adapt Weekly repo-activity rows to the existing Artifact pipeline.

Weekly rows do not carry Historical ``monthly_event_sha`` semantics. This
adapter validates that boundary and delegates head resolution, extraction,
cache reuse, and snapshot publication to the existing common pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common.webhdfs import WebHdfsClient
from github.contracts import (
    GitHubRepoSnapshotBatch,
    RepoCollectionStatus,
)
from github.repo_fetch_orchestrator import (
    RepoActivityCandidate,
    RepoFetchOrchestrator,
    RepoFetchRun,
    TERMINAL_STATUSES,
    create_orchestrator,
)
from github.repo_snapshot_bootstrap import (
    BootstrapBatchRunner,
    BootstrapResult,
    build_parser as build_bootstrap_parser,
)

WEEKLY_CANDIDATE_SCHEMA = "repo-activity-weekly-candidates/v1"
WEEKLY_ACTIVITY_METRIC = "repo_activity_weekly_event_count"
WEEKLY_REFERENCE_SOURCE = "CURRENT_DEFAULT_HEAD"


class WeeklyArtifactResolutionError(ValueError):
    """The Weekly handoff is not safe to expose to the public pipeline."""


@dataclass(frozen=True)
class WeeklyCandidateSet:
    """Validated candidates produced from one Weekly snapshot input."""

    input_root: str
    week_start: date
    candidates: tuple[RepoActivityCandidate, ...]


@dataclass(frozen=True)
class WeeklyArtifactResolution:
    """Result of one Weekly resolution and existing snapshot publication."""

    week_start: date
    run: RepoFetchRun
    bootstrap: BootstrapResult

    @property
    def summary(self) -> Mapping[str, Any]:
        return self.bootstrap.summary

    @property
    def published_uris(self) -> Mapping[str, str]:
        return self.bootstrap.published_uris

    @property
    def reused_count(self) -> int:
        return sum(
            record.collection_status is RepoCollectionStatus.REUSED
            for record in self.run.batch.records
        )

    @property
    def extracted_count(self) -> int:
        return sum(
            record.collection_status is RepoCollectionStatus.COMPLETE
            for record in self.run.batch.records
        )

    @property
    def artifact_ready_count(self) -> int:
        return sum(
            record.collection_status
            in {RepoCollectionStatus.COMPLETE, RepoCollectionStatus.REUSED}
            and bool(record.artifacts)
            for record in self.run.batch.records
        )


def load_weekly_candidates(path: Path, *, limit: int) -> WeeklyCandidateSet:
    """Load a strict Weekly candidate adapter contract.

    The existing orchestrator resolves the current default-branch head and
    records it as ``CURRENT_DEFAULT_HEAD``.
    """

    if limit < 1:
        raise ValueError("limit must be positive")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("weekly candidate payload must be an object")
    if payload.get("schema_version") != WEEKLY_CANDIDATE_SCHEMA:
        raise ValueError("unsupported Weekly candidate schema_version")
    input_root = payload.get("input_root")
    if not isinstance(input_root, str) or not input_root.strip():
        raise ValueError("weekly candidate input_root must not be blank")
    week_start = _monday(payload.get("week_start"))
    rows = payload.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise ValueError("weekly candidate payload must contain candidates")
    if len(rows) > limit:
        raise ValueError("weekly candidate count exceeds limit")

    candidates: list[RepoActivityCandidate] = []
    seen_ids: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("weekly candidate row must be an object")
        # A null month SHA is still rejected when the field is present: this
        # prevents a producer from accidentally routing a Historical-shaped
        # payload into the Weekly adapter.
        if "monthly_event_sha" in row:
            raise WeeklyArtifactResolutionError(
                "Weekly candidates must not contain monthly_event_sha"
            )
        repo_id = _required_int(row, "repo_id", minimum=1)
        repo_name = _required_str(row, "repo_name")
        event_count = _required_int(row, "event_count", minimum=0)
        rank = _required_int(row, "rank", minimum=1)
        if repo_id in seen_ids:
            raise ValueError(f"duplicate Weekly repo_id={repo_id}")
        seen_ids.add(repo_id)
        candidates.append(
            RepoActivityCandidate(
                repo_id=repo_id,
                repo_name=repo_name,
                activity_count=event_count,
                activity_rank=rank,
                activity_metric=WEEKLY_ACTIVITY_METRIC,
                activity_period_start=week_start,
                activity_period_end=week_start + timedelta(days=6),
            )
        )

    candidates.sort(key=lambda item: item.activity_rank)
    if [item.activity_rank for item in candidates] != list(
        range(1, len(candidates) + 1)
    ):
        raise ValueError("Weekly candidate ranks must be contiguous from 1")
    return WeeklyCandidateSet(input_root, week_start, tuple(candidates))


def build_weekly_candidates(
    rows: Sequence[Mapping[str, object]],
    *,
    input_root: str,
    week_start: str,
    limit: int,
) -> WeeklyCandidateSet:
    """Convert read-back rows from ``repo_activity_weekly`` into candidates.

    Spark's Weekly rows contain ``repo_id``, ``repo_name``, ``event_count`` and
    ``week_start`` but no GitHub commit SHA. This pure adapter performs
    deterministic top-N selection and intentionally does not read a
    ``monthly_event_sha`` column.
    """

    if not isinstance(input_root, str) or not input_root.strip():
        raise ValueError("input_root must be a non-blank string")
    monday = _monday(week_start)
    if limit < 1:
        raise ValueError("limit must be positive")
    if not rows:
        raise ValueError("Weekly rows must not be empty")
    normalized: list[tuple[int, str, int]] = []
    seen_ids: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("Weekly activity row must be an object")
        if "monthly_event_sha" in row:
            raise WeeklyArtifactResolutionError(
                "Weekly activity rows must not contain monthly_event_sha"
            )
        if row.get("week_start") != monday.isoformat():
            raise ValueError("Weekly row week_start does not match input week")
        repo_id = _required_int(row, "repo_id", minimum=1)
        if repo_id in seen_ids:
            raise ValueError(f"duplicate Weekly repo_id={repo_id}")
        seen_ids.add(repo_id)
        normalized.append(
            (
                repo_id,
                _required_str(row, "repo_name"),
                _required_int(row, "event_count", minimum=0),
            )
        )
    normalized.sort(key=lambda item: (-item[2], item[0]))
    selected = normalized[:limit]
    candidates = tuple(
        RepoActivityCandidate(
            repo_id=repo_id,
            repo_name=repo_name,
            activity_count=event_count,
            activity_rank=rank,
            activity_metric=WEEKLY_ACTIVITY_METRIC,
            activity_period_start=monday,
            activity_period_end=monday + timedelta(days=6),
        )
        for rank, (repo_id, repo_name, event_count) in enumerate(selected, start=1)
    )
    return WeeklyCandidateSet(input_root, monday, candidates)


class WeeklyArtifactResolver:
    """Adapt Weekly candidates to the existing Artifact extraction runner."""

    def __init__(self, orchestrator: RepoFetchOrchestrator) -> None:
        if orchestrator.require_historical_head:
            raise WeeklyArtifactResolutionError(
                "Weekly resolver cannot use require_historical_head"
            )
        if "historical-head-required" in orchestrator.cache_policy_version:
            raise WeeklyArtifactResolutionError(
                "Weekly resolver cannot use a Historical cache identity"
            )
        self.orchestrator = orchestrator

    def resolve(
        self,
        candidate_set: WeeklyCandidateSet,
        *,
        output: Path,
        summary_output: Path,
        failure_output: Path,
        state_output: Path,
        publisher: Any | None = None,
        publish_root: str | None = None,
    ) -> WeeklyArtifactResolution:
        for candidate in candidate_set.candidates:
            _assert_weekly_candidate(candidate, candidate_set.week_start)
        bootstrap = BootstrapBatchRunner(
            orchestrator=self.orchestrator,
            candidates=candidate_set.candidates,
            output=output,
            summary_output=summary_output,
            failure_output=failure_output,
            state_output=state_output,
            publisher=publisher,
            publish_root=publish_root,
        ).run()
        if bootstrap.exit_code != 0:
            raise WeeklyArtifactResolutionError(
                f"Weekly Artifact resolution incomplete: "
                f"{bootstrap.summary.get('stopped_reason')}"
            )
        _assert_weekly_batch(
            bootstrap.run.batch,
            candidate_set.candidates,
            candidate_set.week_start,
            checkpoint_rows=bootstrap.run.checkpoint_rows,
        )
        return WeeklyArtifactResolution(
            week_start=candidate_set.week_start,
            run=bootstrap.run,
            bootstrap=bootstrap,
        )


def _assert_weekly_candidate(
    candidate: RepoActivityCandidate, week_start: date
) -> None:
    if candidate.monthly_event_sha is not None:
        raise WeeklyArtifactResolutionError(
            "Weekly candidate carries Historical monthly_event_sha"
        )
    if candidate.activity_metric != WEEKLY_ACTIVITY_METRIC:
        raise WeeklyArtifactResolutionError("Weekly candidate metric mismatch")
    if candidate.activity_period_start != week_start:
        raise WeeklyArtifactResolutionError("Weekly candidate period start mismatch")
    if candidate.activity_period_end != week_start + timedelta(days=6):
        raise WeeklyArtifactResolutionError("Weekly candidate period end mismatch")


def _assert_weekly_batch(
    batch: GitHubRepoSnapshotBatch,
    candidates: Sequence[RepoActivityCandidate],
    week_start: date,
    *,
    checkpoint_rows: Sequence[Mapping[str, Any]],
) -> None:
    """Validate terminal coverage without requiring every source row in batch.

    The common snapshot batch intentionally contains contract records only.
    ``NOT_FOUND`` and hard failures live in the summary/failures artifacts, while
    ``PARTIAL`` remains a contract record.  Weekly must validate the complete
    candidate disposition from the checkpoint rather than treating the absent
    ``NOT_FOUND`` records as missing candidates.
    """

    expected = {candidate.repo_id: candidate for candidate in candidates}
    rows_by_id = {int(row["repo_id"]): row for row in checkpoint_rows}
    if set(rows_by_id) != set(expected):
        raise WeeklyArtifactResolutionError(
            "Weekly Artifact checkpoint does not contain every candidate"
        )

    hard_failures: list[str] = []
    for repo_id in expected:
        row = rows_by_id[repo_id]
        status = str(row.get("status"))
        if status not in TERMINAL_STATUSES:
            raise WeeklyArtifactResolutionError(
                f"Weekly Artifact candidate is not terminal: {repo_id} ({status})"
            )
        if status in {"FAILED", "HISTORICAL_HEAD_UNAVAILABLE"}:
            hard_failures.append(f"{repo_id}:{status}")

    if hard_failures:
        raise WeeklyArtifactResolutionError(
            "Weekly Artifact batch contains hard failures: "
            + ", ".join(sorted(hard_failures))
        )

    records_by_id = {record.github_repo_id: record for record in batch.records}
    expected_record_statuses = {"COMPLETE", "PARTIAL", "REUSED"}
    if set(records_by_id) - set(expected):
        unexpected = sorted(set(records_by_id) - set(expected))
        raise WeeklyArtifactResolutionError(
            f"unexpected repo_id in Weekly Artifact batch: {unexpected}"
        )

    for record in batch.records:
        candidate = expected.get(record.github_repo_id)
        if candidate is None:
            raise WeeklyArtifactResolutionError(
                f"unexpected repo_id in Weekly Artifact batch: {record.github_repo_id}"
            )
        if record.activity_period_start != week_start:
            raise WeeklyArtifactResolutionError("Weekly Artifact period start mismatch")
        if record.activity_period_end != week_start + timedelta(days=6):
            raise WeeklyArtifactResolutionError("Weekly Artifact period end mismatch")
        if record.sha_source != WEEKLY_REFERENCE_SOURCE:
            raise WeeklyArtifactResolutionError(
                "Weekly Artifact must use CURRENT_DEFAULT_HEAD"
            )
        if record.monthly_event_sha is not None:
            raise WeeklyArtifactResolutionError(
                "Weekly Artifact must not carry monthly_event_sha"
            )
        if record.current_default_head != record.pinned_commit_sha:
            raise WeeklyArtifactResolutionError(
                "Weekly Artifact current_default_head/pinned SHA mismatch"
            )
        if record.selected_commit_sha != record.pinned_commit_sha:
            raise WeeklyArtifactResolutionError(
                "Weekly Artifact selected/pinned SHA mismatch"
            )
        if record.collection_status not in {
            RepoCollectionStatus.COMPLETE,
            RepoCollectionStatus.PARTIAL,
            RepoCollectionStatus.REUSED,
        }:
            raise WeeklyArtifactResolutionError(
                "Weekly Artifact batch contains an incomplete record"
            )

    for repo_id, row in rows_by_id.items():
        status = str(row.get("status"))
        if status in expected_record_statuses and repo_id not in records_by_id:
            raise WeeklyArtifactResolutionError(
                f"Weekly Artifact batch is missing terminal record: {repo_id}"
            )

        record = records_by_id.get(repo_id)
        if record is not None and record.collection_status.value != status:
            raise WeeklyArtifactResolutionError(
                f"Weekly Artifact status mismatch for {repo_id}: "
                f"checkpoint={status}, record={record.collection_status.value}"
            )


def _monday(value: object) -> date:
    if not isinstance(value, str):
        raise TypeError("week_start must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("week_start must be an ISO date string") from error
    if parsed.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    return parsed


def _required_int(row: Mapping[str, object], name: str, *, minimum: int) -> int:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _required_str(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value


def build_parser() -> argparse.ArgumentParser:
    # The bootstrap entrypoint owns the artifact/cache/checkpoint/publish
    # options. Reuse that parser so Weekly cannot drift from the existing
    # runtime contract.
    parser = build_bootstrap_parser()
    parser.description = (
        "Resolve Weekly repo candidates through the existing Artifact pipeline."
    )
    for action in parser._actions:
        if action.dest in {"period_start", "period_end"}:
            action.required = False
            action.default = None
        elif action.dest == "summary_output":
            action.required = True
        elif action.dest == "activity_metric":
            action.default = WEEKLY_ACTIVITY_METRIC
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    token = os.environ.get(arguments.token_env)
    if not token:
        raise SystemExit(f"GitHub token environment is missing: {arguments.token_env}")
    candidate_set = load_weekly_candidates(arguments.candidates, limit=arguments.limit)
    # create_orchestrator is the existing extractor wiring.  The explicit
    # false value is intentional: Weekly must never opt into Historical mode.
    arguments.require_historical_head = False
    orchestrator = create_orchestrator(arguments, token=token)
    publisher = None
    if arguments.publish_root is not None:
        if arguments.artifact_store != "webhdfs" or not arguments.webhdfs_url:
            raise SystemExit("--publish-root requires WebHDFS artifact configuration")
        publisher = WebHdfsClient(
            arguments.webhdfs_url,
            user=arguments.webhdfs_user,
            timeout=arguments.webhdfs_timeout,
        )
    resolution = WeeklyArtifactResolver(orchestrator).resolve(
        candidate_set,
        output=arguments.output,
        summary_output=arguments.summary_output,
        failure_output=arguments.failure_output,
        state_output=arguments.state_output,
        publisher=publisher,
        publish_root=arguments.publish_root,
    )
    print(
        json.dumps(
            {
                "dataset_snapshot_id": resolution.run.batch.dataset_snapshot_id,
                "week_start": resolution.week_start.isoformat(),
                "record_count": len(resolution.run.batch.records),
                "reused_count": resolution.reused_count,
                "extracted_count": resolution.extracted_count,
                "artifact_ready_count": resolution.artifact_ready_count,
                "published_uris": dict(resolution.published_uris),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return resolution.bootstrap.exit_code


if __name__ == "__main__":  # pragma: no cover - CLI delegation
    raise SystemExit(main())
