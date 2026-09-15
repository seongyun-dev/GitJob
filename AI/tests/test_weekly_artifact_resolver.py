"""Offline contract tests for the Weekly-to-Artifact adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from github.client import GitHubClient, HttpResponse
from github.repo_fetch_orchestrator import RepoActivityCandidate, RepoFetchOrchestrator
from github.repo_fetch_policy import RepoFetchPolicy
from github.repo_fetch_store import (
    FileArtifactStore,
    RepoFetchCheckpoint,
    RepoSnapshotCache,
)
from github.weekly_artifact_resolver import (
    WEEKLY_CANDIDATE_SCHEMA,
    WeeklyArtifactResolutionError,
    WeeklyArtifactResolver,
    build_weekly_candidates,
    load_weekly_candidates,
)

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
TREE_A = "c" * 40
TREE_B = "d" * 40
RATE_HEADERS = {
    "X-RateLimit-Limit": "5000",
    "X-RateLimit-Remaining": "4999",
    "X-RateLimit-Used": "1",
    "X-RateLimit-Reset": "2000000000",
    "X-RateLimit-Resource": "core",
}


class ScriptedTransport:
    def __init__(self, outcomes: list[HttpResponse]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        del headers, timeout
        self.calls.append(url)
        if not self.outcomes:
            raise AssertionError(f"unexpected GitHub request: {url}")
        return self.outcomes.pop(0)


def response(payload: Mapping[str, object] | bytes = b"", *, status: int = 200):
    body = json.dumps(payload).encode("utf-8") if isinstance(payload, Mapping) else payload
    return HttpResponse(status=status, headers=RATE_HEADERS, body=body)


def rate_control() -> HttpResponse:
    return response(
        {
            "resources": {
                "core": {
                    "limit": 5000,
                    "remaining": 4999,
                    "used": 1,
                    "reset": 2_000_000_000,
                }
            }
        }
    )


def metadata(repo_id: int = 1, name: str = "octo/repo") -> HttpResponse:
    return response({"id": repo_id, "full_name": name, "default_branch": "main"})


def branch_head(commit_sha: str = COMMIT_A, tree_sha: str = TREE_A) -> HttpResponse:
    return response(
        {"commit": {"sha": commit_sha, "commit": {"tree": {"sha": tree_sha}}}}
    )


def commit(commit_sha: str = COMMIT_A, tree_sha: str = TREE_A) -> HttpResponse:
    return branch_head(commit_sha, tree_sha)


def tree(tree_sha: str = TREE_A) -> HttpResponse:
    return response(
        {
            "sha": tree_sha,
            "truncated": False,
            "tree": [{"path": "package.json", "type": "blob", "size": 2}],
        }
    )


def policy() -> RepoFetchPolicy:
    return RepoFetchPolicy(
        policy_version="repo-fetch-policy/weekly-test-v1",
        top_n_limit=10,
        max_api_calls=100,
        max_runtime_seconds=3600,
        max_tree_entries=100,
        max_artifact_files=3,
        max_artifact_bytes=100_000,
        max_manifest_files=3,
        max_source_files=0,
        max_file_bytes=50_000,
        max_depth=8,
        source_prefix_bytes=8192,
        rate_limit_safety_threshold=10,
    )


def candidate(
    *,
    repo_id: int = 1,
    name: str = "octo/repo",
    monthly_sha: str | None = None,
) -> RepoActivityCandidate:
    return RepoActivityCandidate(
        repo_id=repo_id,
        repo_name=name,
        activity_count=10,
        activity_rank=1,
        activity_metric="repo_activity_weekly_event_count",
        activity_period_start=date(2026, 9, 7),
        activity_period_end=date(2026, 9, 13),
        monthly_event_sha=monthly_sha,
    )


def make_orchestrator(
    tmp_path: Path,
    transport: ScriptedTransport,
    *,
    dataset: str = "weekly-001",
    require_historical_head: bool = False,
    cache_name: str = "cache.json",
) -> RepoFetchOrchestrator:
    return RepoFetchOrchestrator(
        client=GitHubClient(
            "offline-token",
            transport=transport,
            sleep=lambda _: None,
        ),
        policy=policy(),
        artifact_store=FileArtifactStore(tmp_path / "artifacts"),
        cache=RepoSnapshotCache(tmp_path / cache_name),
        checkpoint=RepoFetchCheckpoint(tmp_path / f"{dataset}.checkpoint.json"),
        dataset_snapshot_id=dataset,
        pipeline_run_id=f"run-{dataset}",
        now=lambda: datetime(2026, 9, 15, tzinfo=timezone.utc),
        require_historical_head=require_historical_head,
    )


def weekly_set(tmp_path: Path):
    path = tmp_path / "weekly-candidates.json"
    row = {
        "repo_id": 1,
        "repo_name": "octo/repo",
        "event_count": 10,
        "rank": 1,
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": WEEKLY_CANDIDATE_SCHEMA,
                "input_root": "hdfs:///gitjob/parquet/github/repo_activity_weekly",
                "week_start": "2026-09-07",
                "candidates": [row],
            }
        ),
        encoding="utf-8",
    )
    return load_weekly_candidates(path, limit=10)


def test_weekly_candidate_uses_current_head_not_month_event_sha(tmp_path: Path) -> None:
    loaded = weekly_set(tmp_path)
    item = loaded.candidates[0]
    assert item.monthly_event_sha is None
    assert not hasattr(item, "current_default_head")
    assert item.activity_metric == "repo_activity_weekly_event_count"
    assert item.activity_period_start == date(2026, 9, 7)
    assert item.activity_period_end == date(2026, 9, 13)


def test_weekly_rows_are_ranked_deterministically_without_a_sha_column() -> None:
    loaded = build_weekly_candidates(
        [
            {
                "repo_id": 2,
                "repo_name": "octo/two",
                "event_count": 10,
                "week_start": "2026-09-07",
            },
            {
                "repo_id": 1,
                "repo_name": "octo/one",
                "event_count": 10,
                "week_start": "2026-09-07",
            },
        ],
        input_root="hdfs:///gitjob/parquet/github/repo_activity_weekly",
        week_start="2026-09-07",
        limit=2,
    )
    assert [item.repo_id for item in loaded.candidates] == [1, 2]
    assert all(item.monthly_event_sha is None for item in loaded.candidates)


def test_weekly_rows_reject_historical_sha_column() -> None:
    with pytest.raises(WeeklyArtifactResolutionError, match="monthly_event_sha"):
        build_weekly_candidates(
            [
                {
                    "repo_id": 1,
                    "repo_name": "octo/one",
                    "event_count": 1,
                    "week_start": "2026-09-07",
                    "monthly_event_sha": None,
                }
            ],
            input_root="hdfs:///weekly",
            week_start="2026-09-07",
            limit=1,
        )


def test_month_event_sha_is_rejected_at_weekly_boundary(tmp_path: Path) -> None:
    path = tmp_path / "historical-shaped.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": WEEKLY_CANDIDATE_SCHEMA,
                "input_root": "hdfs:///weekly",
                "week_start": "2026-09-07",
                "candidates": [
                    {
                        "repo_id": 1,
                        "repo_name": "octo/repo",
                        "event_count": 1,
                        "rank": 1,
                        "monthly_event_sha": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(WeeklyArtifactResolutionError, match="monthly_event_sha"):
        load_weekly_candidates(path, limit=10)


def test_same_repo_and_same_resolved_sha_reuses_existing_artifact(
    tmp_path: Path,
) -> None:
    first_transport = ScriptedTransport(
        [rate_control(), metadata(), commit(COMMIT_A, TREE_A), tree(TREE_A), response(b"{}")]
    )
    first = make_orchestrator(tmp_path, first_transport).run([candidate()])

    replay_transport = ScriptedTransport(
        [rate_control(), metadata(), branch_head(COMMIT_A, TREE_A)]
    )
    replay = make_orchestrator(
        tmp_path,
        replay_transport,
        dataset="weekly-002",
    ).run([candidate()])

    assert first.batch.records[0].collection_status.value == "COMPLETE"
    assert replay.batch.records[0].collection_status.value == "REUSED"
    assert len(replay_transport.calls) == 3  # rate control, metadata, current head
    assert all("/git/trees/" not in url for url in replay_transport.calls)
    assert all("raw.githubusercontent.com" not in url for url in replay_transport.calls)
    assert replay.batch.records[0].artifacts == first.batch.records[0].artifacts


def test_same_repo_with_different_sha_does_not_reuse(tmp_path: Path) -> None:
    make_orchestrator(
        tmp_path,
        ScriptedTransport(
            [rate_control(), metadata(), commit(COMMIT_A, TREE_A), tree(TREE_A), response(b"a")]
        ),
    ).run([candidate()])

    transport = ScriptedTransport(
        [rate_control(), metadata(), commit(COMMIT_B, TREE_B), tree(TREE_B), response(b"b")]
    )
    result = make_orchestrator(tmp_path, transport, dataset="weekly-002").run(
        [candidate()]
    )
    record = result.batch.records[0]
    assert record.collection_status.value == "COMPLETE"
    assert record.pinned_commit_sha == COMMIT_B
    assert result.summary()["repo_api_calls"] == 4


def test_historical_cache_identity_is_isolated_from_weekly(tmp_path: Path) -> None:
    historical = RepoActivityCandidate(
        repo_id=1,
        repo_name="octo/repo",
        activity_count=10,
        activity_rank=1,
        activity_metric="gh_archive_event_count",
        activity_period_start=date(2026, 8, 1),
        activity_period_end=date(2026, 8, 31),
        monthly_event_sha=COMMIT_B,
    )
    historical_result = make_orchestrator(
        tmp_path,
        ScriptedTransport(
            [rate_control(), metadata(), commit(COMMIT_B, TREE_B), tree(TREE_B), response(b"h")]
        ),
        require_historical_head=True,
    ).run([historical])
    assert historical_result.batch.records[0].sha_source == "MONTH_EVENT_SHA"
    assert historical_result.batch.records[0].current_default_head is None

    weekly_result = make_orchestrator(
        tmp_path,
        ScriptedTransport(
            [rate_control(), metadata(), commit(COMMIT_A, TREE_A), tree(TREE_A), response(b"w")]
        ),
        dataset="weekly-002",
    ).run([candidate()])
    record = weekly_result.batch.records[0]
    assert record.collection_status.value == "COMPLETE"
    assert record.sha_source == "CURRENT_DEFAULT_HEAD"
    assert record.monthly_event_sha is None
    assert record.pinned_commit_sha == COMMIT_A


def test_repo_rename_reuses_by_stable_id_and_sha(tmp_path: Path) -> None:
    make_orchestrator(
        tmp_path,
        ScriptedTransport(
            [rate_control(), metadata(name="old/repo"), commit(), tree(), response(b"a")]
        ),
    ).run([candidate(name="old/repo")])

    replay = make_orchestrator(
        tmp_path,
        ScriptedTransport(
            [rate_control(), metadata(name="new/repo"), branch_head(COMMIT_A, TREE_A)]
        ),
        dataset="weekly-002",
    ).run([candidate(name="new/repo")])
    assert replay.batch.records[0].collection_status.value == "REUSED"
    assert replay.batch.records[0].github_repo_id == 1


def test_weekly_resolver_publishes_existing_snapshot_contract(
    tmp_path: Path,
) -> None:
    candidate_set = weekly_set(tmp_path)
    resolver = WeeklyArtifactResolver(
        make_orchestrator(
            tmp_path,
            ScriptedTransport(
                [rate_control(), metadata(), branch_head(), tree(), response(b"{}")]
            ),
        )
    )
    result = resolver.resolve(
        candidate_set,
        output=tmp_path / "snapshot.json",
        summary_output=tmp_path / "run-summary.json",
        failure_output=tmp_path / "failures.json",
        state_output=tmp_path / "state.json",
    )
    assert result.reused_count == 0
    assert result.extracted_count == 1
    assert result.artifact_ready_count == 1
    assert (tmp_path / "snapshot.json").exists()
    assert (tmp_path / "run-summary.json").exists()
    assert result.run.batch.records[0].sha_source == "CURRENT_DEFAULT_HEAD"
    assert result.run.batch.records[0].sha_fallback_reason == (
        "MONTH_EVENT_SHA_NOT_AVAILABLE"
    )
