import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from github.client import GitHubClient, HttpResponse
from github.contracts import (
    GitHubRepoSnapshotBatch,
    RepoArtifactType,
    RepoCollectionIssue,
    RepoCollectionStatus,
)
from github.repo_fetch_orchestrator import (
    RepoActivityCandidate,
    RepoExecutionStatus,
    RepoFetchOrchestrator,
    build_parser,
    load_candidates,
)
from github.repo_fetch_policy import RepoFetchPolicy, select_artifacts
from github.repo_fetch_store import (
    FileArtifactStore,
    RepoFetchCheckpoint,
    RepoSnapshotCache,
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
    def __init__(self, outcomes: list[HttpResponse | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        assert timeout > 0
        self.calls.append((url, dict(headers)))
        if not self.outcomes:
            raise AssertionError(f"unexpected request: {url}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def response(
    payload: Mapping[str, object] | bytes = b"",
    *,
    status: int = 200,
    headers: Mapping[str, str] = RATE_HEADERS,
) -> HttpResponse:
    body = (
        json.dumps(payload).encode("utf-8") if isinstance(payload, Mapping) else payload
    )
    return HttpResponse(status=status, headers=headers, body=body)


def rate_control(remaining: int = 4999) -> HttpResponse:
    return response(
        {
            "resources": {
                "core": {
                    "limit": 5000,
                    "remaining": remaining,
                    "used": 5000 - remaining,
                    "reset": 2000000000,
                }
            }
        }
    )


def metadata(repo_id: int = 1, name: str = "octo/repo") -> HttpResponse:
    return response(
        {
            "id": repo_id,
            "full_name": name,
            "default_branch": "main",
        }
    )


def head(commit_sha: str = COMMIT_A, tree_sha: str = TREE_A) -> HttpResponse:
    return response(
        {
            "commit": {
                "sha": commit_sha,
                "commit": {"tree": {"sha": tree_sha}},
            }
        }
    )


def commit_tree(tree_sha: str = TREE_A) -> HttpResponse:
    return response({"sha": COMMIT_A, "tree": {"sha": tree_sha}})


def tree(
    entries: list[dict[str, object]],
    *,
    tree_sha: str = TREE_A,
    response_sha: str | None = None,
    truncated: bool = False,
) -> HttpResponse:
    return response(
        {
            "sha": response_sha or tree_sha,
            "truncated": truncated,
            "tree": entries,
        }
    )


def candidate(
    *,
    repo_id: int = 1,
    name: str = "octo/repo",
    rank: int = 1,
    count: int = 10,
) -> RepoActivityCandidate:
    return RepoActivityCandidate(
        repo_id=repo_id,
        repo_name=name,
        activity_count=count,
        activity_rank=rank,
        activity_metric="gh_archive_event_count",
        activity_period_start=date(2026, 8, 1),
        activity_period_end=date(2026, 8, 31),
    )


def policy(**overrides: object) -> RepoFetchPolicy:
    values = {
        "policy_version": "repo-fetch-policy/test-v1",
        "top_n_limit": 10,
        "max_api_calls": 100,
        "max_runtime_seconds": 3600,
        "max_tree_entries": 100,
        "max_artifact_files": 3,
        "max_artifact_bytes": 100_000,
        "max_manifest_files": 3,
        "max_source_files": 0,
        "max_file_bytes": 50_000,
        "max_depth": 8,
        "source_prefix_bytes": 8_192,
        "rate_limit_safety_threshold": 10,
    }
    values.update(overrides)
    return RepoFetchPolicy(**values)  # type: ignore[arg-type]


def test_existing_file_artifact_cli_remains_path_based(tmp_path: Path) -> None:
    arguments = build_parser().parse_args(
        [
            "--candidates",
            str(tmp_path / "candidates.json"),
            "--output",
            str(tmp_path / "output.json"),
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--cache",
            str(tmp_path / "cache.json"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--dataset-snapshot-id",
            "snapshot-001",
            "--pipeline-run-id",
            "run-001",
            "--period-start",
            "2026-08-01",
            "--period-end",
            "2026-08-31",
        ]
    )
    assert arguments.artifact_store == "file"
    assert arguments.artifact_root == tmp_path / "artifacts"
    assert arguments.webhdfs_artifact_root is None


def orchestrator(
    tmp_path: Path,
    transport: ScriptedTransport,
    *,
    fetch_policy: RepoFetchPolicy | None = None,
    dataset: str = "dataset-001",
    checkpoint_name: str = "checkpoint.json",
    cache_name: str = "cache.json",
    now: datetime = datetime(2026, 9, 3, tzinfo=timezone.utc),
    max_attempts: int = 1,
) -> RepoFetchOrchestrator:
    return RepoFetchOrchestrator(
        client=GitHubClient(
            "not-logged",
            transport=transport,
            sleep=lambda _: None,
            max_attempts=max_attempts,
        ),
        policy=fetch_policy or policy(),
        artifact_store=FileArtifactStore(tmp_path / "artifacts"),
        cache=RepoSnapshotCache(tmp_path / cache_name),
        checkpoint=RepoFetchCheckpoint(tmp_path / checkpoint_name),
        dataset_snapshot_id=dataset,
        pipeline_run_id=f"run-{dataset}",
        now=lambda: now,
    )


def success_outcomes(
    *,
    commit_sha: str = COMMIT_A,
    tree_sha: str = TREE_A,
    response_tree_sha: str | None = None,
    path: str = "package.json",
    body: bytes = b'{"dependencies": {}}',
) -> list[HttpResponse]:
    return [
        rate_control(),
        metadata(),
        head(commit_sha, tree_sha),
        tree(
            [{"path": path, "type": "blob", "size": len(body)}],
            tree_sha=tree_sha,
            response_sha=response_tree_sha,
        ),
        response(body),
    ]


def test_complete_repo_uses_recursive_tree_and_emits_v1_contract(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport(success_outcomes())
    run = orchestrator(tmp_path, transport).run([candidate()])

    record = run.batch.records[0]
    assert run.stopped_reason is None
    assert run.batch.schema_version == "github-repo-snapshot/v1"
    assert record.collection_status is RepoCollectionStatus.COMPLETE
    assert record.pinned_commit_sha == COMMIT_A
    assert record.tree_sha == TREE_A
    assert record.artifacts[0].artifact_type is RepoArtifactType.MANIFEST
    assert (
        record.artifacts[0].content_hash
        == hashlib.sha256(b'{"dependencies": {}}').hexdigest()
    )
    GitHubRepoSnapshotBatch.model_validate(run.batch.model_dump(mode="json"))

    urls = [url for url, _ in transport.calls]
    assert "/git/trees/" in urls[3]
    assert urls[4].startswith("https://raw.githubusercontent.com/")
    assert "Authorization" in transport.calls[1][1]
    assert "Authorization" not in transport.calls[4][1]


def test_tree_response_commit_sha_cannot_overwrite_commit_tree_sha(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport(
        success_outcomes(response_tree_sha=COMMIT_A),
    )

    run = orchestrator(tmp_path, transport).run([candidate()])

    record = run.batch.records[0]
    assert record.pinned_commit_sha == COMMIT_A
    assert record.tree_sha == TREE_A
    assert f"/git/trees/{TREE_A}?recursive=1" in transport.calls[3][0]


def test_checkpoint_replay_preserves_authoritative_tree_sha(
    tmp_path: Path,
) -> None:
    first = orchestrator(
        tmp_path,
        ScriptedTransport(success_outcomes(response_tree_sha=COMMIT_A)),
    ).run([candidate()])
    replay = orchestrator(
        tmp_path,
        ScriptedTransport([rate_control()]),
    ).run([candidate()])

    assert first.batch.records[0].tree_sha == TREE_A
    assert replay.batch.records[0].tree_sha == TREE_A
    assert replay.batch == first.batch


def test_legacy_checkpoint_tree_metadata_is_repaired_without_artifact_fetch(
    tmp_path: Path,
) -> None:
    first = orchestrator(
        tmp_path,
        ScriptedTransport(success_outcomes()),
    ).run([candidate()])

    checkpoint_path = tmp_path / "checkpoint.json"
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    payload["repos"]["1"]["contract_record"]["tree_sha"] = COMMIT_A
    checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")

    repair_transport = ScriptedTransport([rate_control(), commit_tree()])
    repaired = orchestrator(tmp_path, repair_transport).run([candidate()])

    record = repaired.batch.records[0]
    assert record.tree_sha == TREE_A
    assert record.artifacts == first.batch.records[0].artifacts
    assert repaired.checkpoint_rows[0]["attempts"] == 1
    assert len(repair_transport.calls) == 2
    assert "/git/commits/" in repair_transport.calls[1][0]


def test_progress_callback_reports_terminal_count(tmp_path: Path) -> None:
    events: list[tuple[str, int, int]] = []
    runner = orchestrator(tmp_path, ScriptedTransport(success_outcomes()))
    runner.progress = lambda result, terminal, total: events.append(
        (result.status.value, terminal, total)
    )

    runner.run([candidate()])

    assert events == [("COMPLETE", 1, 1)]


def test_source_prefix_is_fetched_only_when_no_manifest_exists(
    tmp_path: Path,
) -> None:
    content = b"x" * 10_000
    transport = ScriptedTransport(
        [
            rate_control(),
            metadata(),
            head(),
            tree([{"path": "src/app.py", "type": "blob", "size": len(content)}]),
            response(content),
        ]
    )
    run = orchestrator(
        tmp_path,
        transport,
        fetch_policy=policy(max_source_files=1),
    ).run([candidate()])

    artifact = run.batch.records[0].artifacts[0]
    assert artifact.artifact_type is RepoArtifactType.SOURCE
    assert artifact.size_bytes == 8_192
    assert transport.calls[-1][1]["Range"] == "bytes=0-8191"


def test_manifest_presence_suppresses_source_fallback(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [
            rate_control(),
            metadata(),
            head(),
            tree(
                [
                    {"path": "src/app.py", "type": "blob", "size": 4},
                    {"path": "package.json", "type": "blob", "size": 2},
                ]
            ),
            response(b"{}"),
        ]
    )
    run = orchestrator(
        tmp_path,
        transport,
        fetch_policy=policy(max_source_files=1),
    ).run([candidate()])

    assert [artifact.path for artifact in run.batch.records[0].artifacts] == [
        "package.json"
    ]
    assert len(transport.calls) == 5


def test_not_found_stays_in_checkpoint_outside_pinned_contract(
    tmp_path: Path,
) -> None:
    first = ScriptedTransport([rate_control(), response(status=404)])
    first_run = orchestrator(tmp_path, first).run([candidate()])

    assert first_run.batch.records == ()
    assert first_run.checkpoint_rows[0]["status"] == "NOT_FOUND"
    assert first_run.checkpoint_rows[0]["http_statuses"] == [404]

    second = ScriptedTransport([rate_control()])
    second_run = orchestrator(tmp_path, second).run([candidate()])
    assert second_run.batch.records == ()
    assert len(second.calls) == 1


def test_same_sha_reuses_complete_cache_across_datasets(tmp_path: Path) -> None:
    first = ScriptedTransport(success_outcomes())
    first_run = orchestrator(tmp_path, first).run([candidate()])

    second = ScriptedTransport([rate_control(), metadata(), head()])
    second_run = orchestrator(
        tmp_path,
        second,
        dataset="dataset-002",
        checkpoint_name="checkpoint-002.json",
    ).run([candidate(count=11)])

    reused = second_run.batch.records[0]
    assert reused.collection_status is RepoCollectionStatus.REUSED
    assert reused.reused_from_snapshot_id == first_run.batch.records[0].repo_snapshot_id
    assert reused.activity_count == 11
    assert len(second.calls) == 3


def test_same_sha_reuse_repairs_legacy_commit_tree_cache_metadata(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    first = orchestrator(
        tmp_path,
        ScriptedTransport(success_outcomes()),
        cache_name=cache_path.name,
    ).run([candidate()])

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_key = next(iter(payload["entries"]))
    payload["entries"][cache_key]["tree_sha"] = COMMIT_A
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    second_transport = ScriptedTransport([rate_control(), metadata(), head()])
    second = orchestrator(
        tmp_path,
        second_transport,
        dataset="dataset-002",
        checkpoint_name="checkpoint-002.json",
        cache_name=cache_path.name,
    ).run([candidate()])

    reused = second.batch.records[0]
    assert reused.collection_status is RepoCollectionStatus.REUSED
    assert reused.tree_sha == TREE_A
    assert reused.artifacts == first.batch.records[0].artifacts
    assert len(second_transport.calls) == 3
    repaired = json.loads(cache_path.read_text(encoding="utf-8"))
    assert repaired["entries"][cache_key]["tree_sha"] == TREE_A


def test_same_dataset_replay_preserves_batch_and_skips_repo_fetch(
    tmp_path: Path,
) -> None:
    first = orchestrator(
        tmp_path,
        ScriptedTransport(success_outcomes()),
    ).run([candidate()])
    replay_transport = ScriptedTransport([rate_control()])
    replay = orchestrator(tmp_path, replay_transport).run([candidate()])

    assert replay.batch == first.batch
    assert replay.checkpoint_rows[0]["attempts"] == 1
    assert len(replay_transport.calls) == 1


def test_changed_sha_and_changed_policy_both_miss_cache(tmp_path: Path) -> None:
    orchestrator(
        tmp_path,
        ScriptedTransport(success_outcomes()),
    ).run([candidate()])

    changed_sha = ScriptedTransport(
        success_outcomes(commit_sha=COMMIT_B, tree_sha=TREE_B)
    )
    changed_run = orchestrator(
        tmp_path,
        changed_sha,
        dataset="dataset-002",
        checkpoint_name="checkpoint-002.json",
    ).run([candidate()])
    assert (
        changed_run.batch.records[0].collection_status is RepoCollectionStatus.COMPLETE
    )
    assert len(changed_sha.calls) == 5

    changed_policy = ScriptedTransport(success_outcomes())
    policy_run = orchestrator(
        tmp_path,
        changed_policy,
        fetch_policy=policy(max_depth=7),
        dataset="dataset-003",
        checkpoint_name="checkpoint-003.json",
    ).run([candidate()])
    assert (
        policy_run.batch.records[0].collection_status is RepoCollectionStatus.COMPLETE
    )
    assert len(changed_policy.calls) == 5


def test_rate_limit_before_pin_resumes_same_repo(tmp_path: Path) -> None:
    limited_headers = {**RATE_HEADERS, "X-RateLimit-Remaining": "0"}
    first = ScriptedTransport(
        [rate_control(), response(status=403, headers=limited_headers)]
    )
    first_run = orchestrator(tmp_path, first).run([candidate()])

    assert first_run.stopped_reason == "RATE_LIMIT_RESPONSE"
    assert first_run.rate_limit_after is not None
    assert first_run.rate_limit_after.remaining == 0
    assert first_run.batch.records == ()
    assert first_run.checkpoint_rows[0]["status"] == "RATE_LIMITED"

    second = ScriptedTransport(success_outcomes())
    second_run = orchestrator(tmp_path, second).run([candidate()])
    assert (
        second_run.batch.records[0].collection_status is RepoCollectionStatus.COMPLETE
    )
    assert second_run.checkpoint_rows[0]["attempts"] == 2
    assert second_run.checkpoint_rows[0]["api_calls"] == 5
    assert second_run.checkpoint_rows[0]["http_statuses"] == [
        403,
        200,
        200,
        200,
        200,
    ]


def test_resumed_checkpoint_counts_prior_calls_against_api_budget(
    tmp_path: Path,
) -> None:
    limited_headers = {**RATE_HEADERS, "X-RateLimit-Remaining": "0"}
    fetch_policy = policy(max_api_calls=2)
    first = orchestrator(
        tmp_path,
        ScriptedTransport(
            [rate_control(), response(status=403, headers=limited_headers)]
        ),
        fetch_policy=fetch_policy,
    ).run([candidate()])
    assert first.stopped_reason == "RATE_LIMIT_RESPONSE"

    replay_transport = ScriptedTransport([rate_control()])
    replay = orchestrator(
        tmp_path,
        replay_transport,
        fetch_policy=fetch_policy,
    ).run([candidate()])

    assert replay.stopped_reason == "API_CALL_BUDGET"
    assert len(replay_transport.calls) == 1
    assert replay.checkpoint_rows[0]["attempts"] == 1


def test_rate_limit_after_pin_emits_partial_checkpoint_then_resumes(
    tmp_path: Path,
) -> None:
    limited_headers = {**RATE_HEADERS, "X-RateLimit-Remaining": "0"}
    first = ScriptedTransport(
        [
            rate_control(),
            metadata(),
            head(),
            response(status=403, headers=limited_headers),
        ]
    )
    first_run = orchestrator(tmp_path, first).run([candidate()])

    partial = first_run.batch.records[0]
    assert partial.collection_status is RepoCollectionStatus.PARTIAL
    assert partial.collection_issues == (RepoCollectionIssue.RATE_LIMITED,)
    assert partial.checkpoint_uri is not None
    assert first_run.checkpoint_rows[0]["status"] == "RATE_LIMITED"

    second = ScriptedTransport(success_outcomes())
    resumed = orchestrator(tmp_path, second).run([candidate()])
    assert resumed.batch.records[0].collection_status is RepoCollectionStatus.COMPLETE


def test_truncated_tree_and_limits_are_explicit_partial_issues(
    tmp_path: Path,
) -> None:
    entries = [
        {"path": "package.json", "type": "blob", "size": 2},
        {"path": "nested/pyproject.toml", "type": "blob", "size": 2},
        {"path": "third/pom.xml", "type": "blob", "size": 2},
    ]
    transport = ScriptedTransport(
        [
            rate_control(),
            metadata(),
            head(),
            tree(entries, truncated=True),
            response(b"{}"),
        ]
    )
    run = orchestrator(
        tmp_path,
        transport,
        fetch_policy=policy(max_tree_entries=2, max_manifest_files=1),
    ).run([candidate()])

    record = run.batch.records[0]
    assert record.collection_status is RepoCollectionStatus.PARTIAL
    assert set(record.collection_issues) == {
        RepoCollectionIssue.TREE_TRUNCATED,
        RepoCollectionIssue.TREE_LIMIT_REACHED,
        RepoCollectionIssue.FILE_LIMIT_REACHED,
    }
    assert record.observed_tree_entries == 2


def test_empty_tree_is_complete_and_malformed_tree_is_failed(
    tmp_path: Path,
) -> None:
    empty = ScriptedTransport([rate_control(), metadata(), head(), tree([])])
    empty_run = orchestrator(tmp_path, empty).run([candidate()])
    assert empty_run.batch.records[0].collection_status is RepoCollectionStatus.COMPLETE
    assert empty_run.batch.records[0].artifacts == ()

    malformed = ScriptedTransport(
        [rate_control(), metadata(), head(), response({"truncated": False})]
    )
    malformed_run = orchestrator(
        tmp_path,
        malformed,
        dataset="dataset-002",
        checkpoint_name="checkpoint-002.json",
        cache_name="cache-002.json",
    ).run([candidate()])
    assert (
        malformed_run.batch.records[0].collection_status is RepoCollectionStatus.FAILED
    )
    assert malformed_run.batch.records[0].collection_issues == (
        RepoCollectionIssue.ARTIFACT_FETCH_FAILED,
    )


def test_timeout_is_bounded_retry_without_secret_in_checkpoint(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport(
        [
            rate_control(),
            TimeoutError("temporary"),
            metadata(),
            head(),
            tree([]),
        ]
    )
    run = orchestrator(tmp_path, transport, max_attempts=2).run([candidate()])

    assert run.batch.records[0].collection_status is RepoCollectionStatus.COMPLETE
    checkpoint_text = (tmp_path / "checkpoint.json").read_text(encoding="utf-8")
    assert "not-logged" not in checkpoint_text
    assert run.checkpoint_rows[0]["api_calls"] == 4


def test_policy_selection_rejects_large_vendor_and_uses_named_manifest_order() -> None:
    selection = select_artifacts(
        [
            {"path": "vendor/package.json", "type": "blob", "size": 2},
            {"path": "service/pom.xml", "type": "blob", "size": 2},
            {"path": "package.json", "type": "blob", "size": 100_000},
            {"path": "service/requirements.txt", "type": "blob", "size": 2},
        ],
        policy(max_file_bytes=10),
    )

    assert selection.manifest_paths == (
        "service/requirements.txt",
        "service/pom.xml",
    )
    assert selection.issues == (RepoCollectionIssue.BYTE_LIMIT_REACHED,)


def test_candidate_payload_and_checkpoint_identity_are_strict(
    tmp_path: Path,
) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "repo-fetch-candidates/v1",
                "input_root": "hdfs:///gitjob/parquet/github/repo_activity/x",
                "candidates": [
                    {
                        "repo_id": 1,
                        "repo_name": "octo/repo",
                        "activity_count": 10,
                        "rank": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source, candidates = load_candidates(
        path,
        activity_metric="gh_archive_event_count",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        limit=1,
    )
    assert source.startswith("hdfs:///")
    assert candidates == (candidate(),)

    first = ScriptedTransport(success_outcomes())
    orchestrator(tmp_path, first).run(candidates)
    with pytest.raises(ValueError, match="different dataset_snapshot_id"):
        orchestrator(
            tmp_path,
            ScriptedTransport([]),
            dataset="different-dataset",
        ).run(candidates)


def test_api_budget_and_rate_safety_stop_before_repo_request(tmp_path: Path) -> None:
    budget_transport = ScriptedTransport([rate_control()])
    budget_run = orchestrator(
        tmp_path,
        budget_transport,
        fetch_policy=policy(max_api_calls=1),
    ).run([candidate()])
    assert budget_run.stopped_reason == "API_CALL_BUDGET"
    assert len(budget_transport.calls) == 1

    safety_transport = ScriptedTransport([rate_control(remaining=9)])
    safety_run = orchestrator(
        tmp_path,
        safety_transport,
        dataset="dataset-002",
        checkpoint_name="checkpoint-002.json",
    ).run([candidate()])
    assert safety_run.stopped_reason == "RATE_LIMIT_SAFETY_THRESHOLD"
    assert len(safety_transport.calls) == 1


def test_fetch_repo_reports_execution_status_without_batch_wrapper(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport([metadata(), head(), tree([])])
    execution = orchestrator(tmp_path, transport).fetch_repo(candidate())
    assert execution.status is RepoExecutionStatus.COMPLETE
    assert execution.record is not None
