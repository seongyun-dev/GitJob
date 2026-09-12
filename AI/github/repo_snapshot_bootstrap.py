"""Long-running Top-N bootstrap around the single-cycle Repo Fetch Orchestrator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.webhdfs import WebHdfsClient, normalize_hdfs_path

from github.client import GitHubClient
from github.repo_fetch_orchestrator import (
    TERMINAL_STATUSES,
    RepoActivityCandidate,
    RepoExecution,
    RepoFetchOrchestrator,
    RepoFetchRun,
    _immutable_payload_write,
    _replace_payload,
    create_artifact_store,
    create_policy,
    load_candidates,
)
from github.repo_fetch_orchestrator import (
    build_parser as build_fetch_parser,
)
from github.repo_fetch_store import RepoFetchCheckpoint, RepoSnapshotCache

BOOTSTRAP_SUMMARY_VERSION = "github-repo-snapshot-bootstrap-summary/v1"
DEFAULT_ESTIMATED_CORE_CALLS = 50_345
DEFAULT_ESTIMATED_RUNTIME_SECONDS = 36_000
RATE_LIMIT_STOP_REASONS = {
    "RATE_LIMIT_RESPONSE",
    "RATE_LIMIT_SAFETY_THRESHOLD",
}


@dataclass(frozen=True)
class BootstrapResult:
    exit_code: int
    run: RepoFetchRun
    summary: Mapping[str, Any]
    published_uris: Mapping[str, str]


class BootstrapBatchRunner:
    """Resume rate-limited cycles and publish only a complete terminal batch."""

    def __init__(
        self,
        *,
        orchestrator: RepoFetchOrchestrator,
        candidates: Sequence[RepoActivityCandidate],
        output: Path,
        summary_output: Path,
        failure_output: Path,
        state_output: Path,
        publisher: WebHdfsClient | None = None,
        publish_root: str | None = None,
        reset_buffer_seconds: float = 5.0,
        max_wait_seconds: float = 7_200.0,
        estimated_core_calls: int = DEFAULT_ESTIMATED_CORE_CALLS,
        estimated_runtime_seconds: int = DEFAULT_ESTIMATED_RUNTIME_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        epoch: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if reset_buffer_seconds < 0:
            raise ValueError("reset_buffer_seconds cannot be negative")
        if max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds must be positive")
        if estimated_core_calls <= 0 or estimated_runtime_seconds <= 0:
            raise ValueError("estimates must be positive")
        if (publisher is None) != (publish_root is None):
            raise ValueError("publisher and publish_root must be provided together")
        self.orchestrator = orchestrator
        self.candidates = tuple(candidates)
        self.output = output
        self.summary_output = summary_output
        self.failure_output = failure_output
        self.state_output = state_output
        self.publisher = publisher
        self.publish_root = (
            normalize_hdfs_path(publish_root) if publish_root is not None else None
        )
        self.reset_buffer_seconds = reset_buffer_seconds
        self.max_wait_seconds = max_wait_seconds
        self.estimated_core_calls = estimated_core_calls
        self.estimated_runtime_seconds = estimated_runtime_seconds
        self.sleep = sleep
        self.epoch = epoch
        self.monotonic = monotonic
        self._state: dict[str, Any] | None = None
        self._status_by_repo: dict[int, str] = {}
        self._cycle_started = 0.0
        self.orchestrator.progress = self._on_progress

    def run(self) -> BootstrapResult:
        state = self._load_state()
        self._state = state
        checkpoint = getattr(self.orchestrator, "checkpoint", None)
        checkpoint_rows = checkpoint.summary_rows() if checkpoint is not None else []
        self._status_by_repo = {
            int(row["repo_id"]): str(row["status"]) for row in checkpoint_rows
        }
        self._resume_pending_wait(state)
        while True:
            self._cycle_started = self.monotonic()
            cycle = self.orchestrator.run(
                self.candidates,
                prior_active_seconds=float(state["active_runtime_seconds"]),
                prior_control_core_calls=int(state["control_core_calls"]),
            )
            state["cycle_count"] = int(state["cycle_count"]) + 1
            state["active_runtime_seconds"] = (
                float(state["active_runtime_seconds"]) + cycle.active_runtime_seconds
            )
            state["control_core_calls"] = int(state["control_core_calls"]) + sum(
                request.is_core for request in cycle.control_requests
            )
            state["last_stopped_reason"] = cycle.stopped_reason
            state["last_rate_limit"] = _rate_payload(cycle)
            state["updated_at"] = _utc_now()
            self._write_state(state, cycle)

            if cycle.stopped_reason in RATE_LIMIT_STOP_REASONS:
                rate_limit = cycle.rate_limit_after or cycle.rate_limit_before
                reset = rate_limit.reset
                if reset is None:
                    return self._incomplete(cycle, state, "RATE_LIMIT_RESET_UNKNOWN")
                wait_seconds = max(
                    0.0,
                    float(reset) - self.epoch() + self.reset_buffer_seconds,
                )
                if wait_seconds > self.max_wait_seconds:
                    return self._incomplete(cycle, state, "RATE_LIMIT_WAIT_TOO_LONG")
                state["rate_limit_wait_count"] = int(state["rate_limit_wait_count"]) + 1
                state["rate_limit_wait_started_epoch"] = self.epoch()
                state["next_resume_epoch"] = reset + self.reset_buffer_seconds
                self._write_state(state, cycle)
                self.sleep(wait_seconds)
                self._finish_pending_wait(state)
                continue

            if cycle.stopped_reason is not None:
                return self._incomplete(cycle, state, cycle.stopped_reason)
            return self._publish(cycle, state)

    def _publish(
        self,
        cycle: RepoFetchRun,
        state: dict[str, Any],
    ) -> BootstrapResult:
        current_snapshot = cycle.batch.model_dump(mode="json")
        if self.output.exists():
            snapshot = _read_json_object(self.output)
            failures = _read_json_object(self.failure_output)
            summary = _read_json_object(self.summary_output)
            if snapshot != current_snapshot:
                raise RuntimeError(
                    "frozen final Snapshot differs from resumed checkpoint"
                )
        else:
            snapshot = current_snapshot
            failures = _failure_payload(cycle)
            summary = self._summary(cycle, state, published=True)
            # The immutable local Snapshot is the completion marker and is last.
            _replace_payload(self.failure_output, failures)
            _replace_payload(self.summary_output, summary)
            _immutable_payload_write(self.output, snapshot)

        published: dict[str, str] = {
            "snapshot": self.output.resolve().as_uri(),
            "summary": self.summary_output.resolve().as_uri(),
            "failures": self.failure_output.resolve().as_uri(),
        }
        if self.publisher is not None and self.publish_root is not None:
            payloads = {
                "snapshot": ("snapshot.json", snapshot),
                "summary": ("run-summary.json", summary),
                "failures": ("failures.json", failures),
            }
            for name, (filename, payload) in payloads.items():
                content = _json_bytes(payload)
                path = self.publish_root / filename
                uri = self.publisher.store_immutable(path, content)
                if self.publisher.read(path) != content:
                    raise RuntimeError(f"WebHDFS read-back mismatch: {name}")
                published[name] = uri
            success = {
                "schema_version": "github-repo-snapshot-publish-manifest/v1",
                "dataset_snapshot_id": cycle.batch.dataset_snapshot_id,
                "objects": {
                    name: {
                        "uri": published[name],
                        "sha256": hashlib.sha256(_json_bytes(payload)).hexdigest(),
                    }
                    for name, (_, payload) in payloads.items()
                },
            }
            success_content = _json_bytes(success)
            success_path = self.publish_root / "_SUCCESS.json"
            published["success"] = self.publisher.store_immutable(
                success_path, success_content
            )
            if self.publisher.read(success_path) != success_content:
                raise RuntimeError("WebHDFS read-back mismatch: success manifest")
        state["published"] = True
        state["published_uris"] = published
        state["updated_at"] = _utc_now()
        self._write_state(state, cycle)
        return BootstrapResult(0, cycle, summary, published)

    def _incomplete(
        self,
        cycle: RepoFetchRun,
        state: dict[str, Any],
        reason: str,
    ) -> BootstrapResult:
        state["last_stopped_reason"] = reason
        summary = self._summary(cycle, state, published=False)
        _replace_payload(self.failure_output, _failure_payload(cycle))
        _replace_payload(self.summary_output, summary)
        self._write_state(state, cycle)
        return BootstrapResult(2, cycle, summary, {})

    def _summary(
        self,
        cycle: RepoFetchRun,
        state: Mapping[str, Any],
        *,
        published: bool,
    ) -> dict[str, Any]:
        base = cycle.summary()
        control_calls = int(state["control_core_calls"])
        actual_core = int(base["repo_core_calls"]) + control_calls
        actual_requests = int(base["repo_api_calls"]) + control_calls
        active = float(state["active_runtime_seconds"])
        return {
            **base,
            "schema_version": BOOTSTRAP_SUMMARY_VERSION,
            "stopped_reason": state["last_stopped_reason"],
            "snapshot_published": published,
            "cycle_count": int(state["cycle_count"]),
            "rate_limit_wait_count": int(state["rate_limit_wait_count"]),
            "rate_limit_wait_seconds": float(state["rate_limit_wait_seconds"]),
            "active_runtime_seconds": active,
            "wall_runtime_seconds": active + float(state["rate_limit_wait_seconds"]),
            "actual_requests": actual_requests,
            "actual_core_requests": actual_core,
            "actual_raw_requests": int(base["repo_raw_calls"]),
            "estimate_comparison": {
                "estimated_core_requests": self.estimated_core_calls,
                "actual_core_requests": actual_core,
                "core_request_delta": actual_core - self.estimated_core_calls,
                "estimated_active_runtime_seconds": self.estimated_runtime_seconds,
                "actual_active_runtime_seconds": active,
                "active_runtime_delta_seconds": (
                    active - self.estimated_runtime_seconds
                ),
            },
        }

    def _load_state(self) -> dict[str, Any]:
        default = {
            "schema_version": BOOTSTRAP_SUMMARY_VERSION,
            "dataset_snapshot_id": self.orchestrator.dataset_snapshot_id,
            "pipeline_run_id": self.orchestrator.pipeline_run_id,
            "cycle_count": 0,
            "control_core_calls": 0,
            "active_runtime_seconds": 0.0,
            "rate_limit_wait_count": 0,
            "rate_limit_wait_seconds": 0.0,
            "next_resume_epoch": None,
            "rate_limit_wait_started_epoch": None,
            "last_stopped_reason": None,
            "last_rate_limit": None,
            "published": False,
            "published_uris": {},
            "updated_at": _utc_now(),
        }
        if not self.state_output.exists():
            return default
        loaded = json.loads(self.state_output.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise TypeError("bootstrap state root must be an object")
        for key in ("schema_version", "dataset_snapshot_id", "pipeline_run_id"):
            if loaded.get(key) != default[key]:
                raise ValueError(f"bootstrap state belongs to a different {key}")
        return {**default, **loaded}

    def _resume_pending_wait(self, state: dict[str, Any]) -> None:
        if state["next_resume_epoch"] is None:
            return
        wait_until = float(state["next_resume_epoch"])
        now = self.epoch()
        self.sleep(max(0.0, wait_until - now))
        self._finish_pending_wait(state)

    def _finish_pending_wait(self, state: dict[str, Any]) -> None:
        started = state.get("rate_limit_wait_started_epoch")
        wait_until = state.get("next_resume_epoch")
        if started is not None and wait_until is not None:
            observed_end = min(self.epoch(), float(wait_until))
            state["rate_limit_wait_seconds"] = float(
                state["rate_limit_wait_seconds"]
            ) + max(0.0, observed_end - float(started))
        state["rate_limit_wait_started_epoch"] = None
        state["next_resume_epoch"] = None
        state["updated_at"] = _utc_now()
        _replace_payload(self.state_output, state)

    def _write_state(
        self,
        state: dict[str, Any],
        cycle: RepoFetchRun,
    ) -> None:
        rows = cycle.checkpoint_rows
        terminal = sum(str(row["status"]) in TERMINAL_STATUSES for row in rows)
        total = len(self.candidates)
        active = float(state["active_runtime_seconds"])
        throughput = terminal / active if active > 0 else 0.0
        remaining = max(0, total - terminal)
        state["progress"] = {
            "terminal": terminal,
            "total": total,
            "remaining": remaining,
            "percent": (terminal / total * 100.0) if total else 100.0,
            "throughput_repos_per_second": throughput,
            "eta_active_seconds": (remaining / throughput if throughput > 0 else None),
            "status_counts": dict(
                sorted(Counter(str(row["status"]) for row in rows).items())
            ),
        }
        _replace_payload(self.state_output, state)

    def _on_progress(
        self,
        result: RepoExecution,
        terminal: int,
        total: int,
    ) -> None:
        if self._state is None:
            return
        self._status_by_repo[result.candidate.repo_id] = result.status.value
        active = float(self._state["active_runtime_seconds"]) + max(
            0.0, self.monotonic() - self._cycle_started
        )
        throughput = terminal / active if active > 0 else 0.0
        remaining = max(0, total - terminal)
        rate_remaining = None
        rate_reset = None
        for request in reversed(result.requests):
            if request.rate_limit_remaining is not None:
                rate_remaining = request.rate_limit_remaining
                rate_reset = request.rate_limit_reset
                break
        self._state["updated_at"] = _utc_now()
        self._state["last_repo"] = {
            "repo_id": result.candidate.repo_id,
            "repo_name": result.candidate.repo_name,
            "rank": result.candidate.activity_rank,
            "status": result.status.value,
            "api_calls": result.api_calls,
        }
        self._state["last_rate_limit"] = {
            "remaining": rate_remaining,
            "reset": rate_reset,
        }
        self._state["progress"] = {
            "terminal": terminal,
            "total": total,
            "remaining": remaining,
            "percent": (terminal / total * 100.0) if total else 100.0,
            "throughput_repos_per_second": throughput,
            "eta_active_seconds": (remaining / throughput if throughput > 0 else None),
            "status_counts": dict(
                sorted(Counter(self._status_by_repo.values()).items())
            ),
        }
        _replace_payload(self.state_output, self._state)


def build_parser() -> argparse.ArgumentParser:
    parser = build_fetch_parser()
    parser.description = (
        "Run and resume the Top-N GitHub Repo Snapshot bootstrap batch."
    )
    parser.add_argument("--failure-output", type=Path, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--publish-root")
    parser.add_argument("--rate-limit-reset-buffer-seconds", type=float, default=5.0)
    parser.add_argument("--max-rate-limit-wait-seconds", type=float, default=7_200.0)
    parser.add_argument(
        "--estimated-core-calls", type=int, default=DEFAULT_ESTIMATED_CORE_CALLS
    )
    parser.add_argument(
        "--estimated-runtime-seconds",
        type=int,
        default=DEFAULT_ESTIMATED_RUNTIME_SECONDS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.summary_output is None:
        raise SystemExit("--summary-output is required for bootstrap execution")
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
    ranks = [item.activity_rank for item in candidates]
    if ranks != list(range(1, arguments.limit + 1)):
        raise SystemExit(
            "bootstrap candidates must contain every contiguous rank from 1 to --limit"
        )
    orchestrator = RepoFetchOrchestrator(
        client=GitHubClient(token),
        policy=create_policy(arguments),
        artifact_store=create_artifact_store(arguments),
        cache=RepoSnapshotCache(arguments.cache),
        checkpoint=RepoFetchCheckpoint(arguments.checkpoint),
        dataset_snapshot_id=arguments.dataset_snapshot_id,
        pipeline_run_id=arguments.pipeline_run_id,
        collector_version=arguments.collector_version,
        require_historical_head=arguments.require_historical_head,
    )
    publisher = None
    if arguments.publish_root is not None:
        if arguments.artifact_store != "webhdfs" or not arguments.webhdfs_url:
            raise SystemExit("--publish-root requires --artifact-store webhdfs")
        publisher = WebHdfsClient(
            arguments.webhdfs_url,
            user=arguments.webhdfs_user,
            timeout=arguments.webhdfs_timeout,
        )
    result = BootstrapBatchRunner(
        orchestrator=orchestrator,
        candidates=candidates,
        output=arguments.output,
        summary_output=arguments.summary_output,
        failure_output=arguments.failure_output,
        state_output=arguments.state_output,
        publisher=publisher,
        publish_root=arguments.publish_root,
        reset_buffer_seconds=arguments.rate_limit_reset_buffer_seconds,
        max_wait_seconds=arguments.max_rate_limit_wait_seconds,
        estimated_core_calls=arguments.estimated_core_calls,
        estimated_runtime_seconds=arguments.estimated_runtime_seconds,
    ).run()
    print(
        json.dumps(
            {
                "dataset_snapshot_id": result.run.batch.dataset_snapshot_id,
                "record_count": len(result.run.batch.records),
                "stopped_reason": result.summary["stopped_reason"],
                "snapshot_published": bool(result.published_uris),
                "published_uris": result.published_uris,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return result.exit_code


def _failure_payload(cycle: RepoFetchRun) -> dict[str, Any]:
    failures = [
        row
        for row in cycle.checkpoint_rows
        if str(row["status"]) in {"FAILED", "NOT_FOUND"}
        or str(row["status"]) == "HISTORICAL_HEAD_UNAVAILABLE"
    ]
    return {
        "schema_version": "github-repo-fetch-failures/v1",
        "dataset_snapshot_id": cycle.batch.dataset_snapshot_id,
        "failure_count": len(failures),
        "repos": failures,
    }


def _rate_payload(cycle: RepoFetchRun) -> dict[str, int | str | None]:
    state = cycle.rate_limit_after or cycle.rate_limit_before
    return {
        "limit": state.limit,
        "remaining": state.remaining,
        "used": state.used,
        "reset": state.reset,
        "resource": state.resource,
    }


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON payload must be an object: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
