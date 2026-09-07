import json
from pathlib import Path

import pytest
from github.repo_fetch_benchmark import (
    CheckpointStore,
    CollectionStatus,
    GitHubClient,
    HttpResponse,
    MissingReason,
    RepoCandidate,
    RepoFetchBenchmark,
    RepoResult,
    RequestRecord,
    Stage,
    coverage_for_n,
    distribution,
    estimate_bootstrap,
    load_candidate_payload,
    outcome_metrics,
    select_manifest_candidates,
)
from github.root_manifest_probe import (
    ProbeTarget,
    probe_repository,
    summarize,
    targets_from_checkpoint,
)
from repo_fetch_candidates import (
    build_parser as build_candidate_parser,
)
from repo_fetch_candidates import (
    coverage_rows_from_counts,
    deduplicate_top_n_rows,
    parse_positive_ints,
    stratified_target_ranks,
)

RATE_HEADERS = {
    "x-ratelimit-limit": "5000",
    "x-ratelimit-remaining": "4999",
    "x-ratelimit-used": "1",
    "x-ratelimit-reset": "2000000000",
    "x-ratelimit-resource": "core",
}


def test_candidate_cli_supports_contiguous_phase_top_n(tmp_path: Path) -> None:
    arguments = build_candidate_parser().parse_args(
        [
            "--candidate-mode",
            "top-n",
            "--phase-top-n",
            "20000",
            "--output",
            str(tmp_path / "candidates.json"),
        ]
    )
    assert arguments.candidate_mode == "top-n"
    assert arguments.phase_top_n == 20_000


def test_top_n_deduplicates_casefold_names_and_backfills_deterministically() -> None:
    rows = [
        {
            "repo_id": 10,
            "repo_name": "Owner/Repo",
            "activity_count": 100,
            "rank": 1,
        },
        {
            "repo_id": 11,
            "repo_name": "owner/repo",
            "activity_count": 99,
            "rank": 2,
        },
        {
            "repo_id": 12,
            "repo_name": "next/one",
            "activity_count": 98,
            "rank": 3,
        },
        {
            "repo_id": 13,
            "repo_name": "last/one",
            "activity_count": 97,
            "rank": 4,
        },
    ]

    selected = deduplicate_top_n_rows(rows, 3)
    reversed_selected = deduplicate_top_n_rows(list(reversed(rows)), 3)

    assert selected == reversed_selected
    assert [row["repo_id"] for row in selected] == [10, 12, 13]
    assert [row["rank"] for row in selected] == [1, 2, 3]
    assert [row["activity_count"] for row in selected] == [100, 98, 97]


class ScriptedTransport:
    def __init__(self, outcomes: list[HttpResponse | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        assert timeout > 0
        self.requests.append((url, dict(headers)))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def response(
    status: int,
    payload: object = None,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> HttpResponse:
    if body is None:
        body = json.dumps(payload if payload is not None else {}).encode()
    return HttpResponse(status=status, headers=headers or RATE_HEADERS, body=body)


def candidate(
    repo_id: int = 1, name: str = "owner/repo", rank: int = 1
) -> RepoCandidate:
    return RepoCandidate(repo_id=repo_id, repo_name=name, rank=rank, stratum="top")


def full_success_responses(*, truncated: bool = False) -> list[HttpResponse]:
    return [
        response(
            200,
            {
                "full_name": "owner/repo",
                "default_branch": "main",
                "archived": False,
                "fork": False,
                "visibility": "public",
            },
        ),
        response(
            200,
            {
                "commit": {
                    "sha": "a" * 40,
                    "commit": {"tree": {"sha": "b" * 40}},
                }
            },
        ),
        response(
            200,
            {
                "truncated": truncated,
                "tree": [
                    {"path": "src/main.py", "type": "blob"},
                    {"path": "package.json", "type": "blob"},
                ],
            },
        ),
        response(200, headers={}, body=b'{"name":"fixture"}'),
    ]


def rate_response(remaining: int = 5000) -> HttpResponse:
    return response(
        200,
        {
            "resources": {
                "core": {
                    "limit": 5000,
                    "remaining": remaining,
                    "used": 5000 - remaining,
                    "reset": 2000000000,
                }
            }
        },
    )


def test_success_fetch_counts_core_raw_bytes_and_manifest() -> None:
    outcomes = full_success_responses()
    transport = ScriptedTransport(outcomes)
    runner = RepoFetchBenchmark(
        GitHubClient("secret-not-logged", transport=transport, sleep=lambda _: None),
        CheckpointStore(Path("unused-checkpoint.json")),
    )

    result = runner.fetch_repo(candidate())

    assert result.status == CollectionStatus.SUCCEEDED.value
    assert result.core_calls == 3
    assert result.raw_calls == 1
    assert result.api_calls == 4
    assert result.response_bytes == sum(len(item.body) for item in outcomes)
    assert result.pinned_commit_sha == "a" * 40
    assert result.artifact_key == f"github/1/{'a' * 40}"
    assert result.manifest_candidates == ("package.json",)
    assert result.manifest_success_count == 1
    assert "Authorization" in transport.requests[0][1]
    assert "Authorization" not in transport.requests[-1][1]
    assert all(
        "secret-not-logged" not in json.dumps(record.__dict__)
        for record in result.requests
    )


def test_not_found_is_terminal_and_does_not_retry(tmp_path: Path) -> None:
    transport = ScriptedTransport([response(404)])
    runner = RepoFetchBenchmark(
        GitHubClient(
            "token", transport=transport, max_attempts=3, sleep=lambda _: None
        ),
        CheckpointStore(tmp_path / "checkpoint.json"),
    )

    result = runner.fetch_repo(candidate())

    assert result.status == CollectionStatus.NOT_FOUND.value
    assert result.api_calls == 1


@pytest.mark.parametrize("status", [403, 429])
def test_rate_limit_responses_do_not_retry(status: int, tmp_path: Path) -> None:
    headers = dict(RATE_HEADERS, **{"x-ratelimit-remaining": "0"})
    transport = ScriptedTransport([response(status, headers=headers)])
    runner = RepoFetchBenchmark(
        GitHubClient(
            "token", transport=transport, max_attempts=3, sleep=lambda _: None
        ),
        CheckpointStore(tmp_path / "checkpoint.json"),
    )

    result = runner.fetch_repo(candidate())

    assert result.status == CollectionStatus.RATE_LIMITED.value
    assert result.api_calls == 1


def test_permission_403_is_failed_not_rate_limited(tmp_path: Path) -> None:
    transport = ScriptedTransport([response(403)])
    runner = RepoFetchBenchmark(
        GitHubClient("token", transport=transport, sleep=lambda _: None),
        CheckpointStore(tmp_path / "checkpoint.json"),
    )

    result = runner.fetch_repo(candidate())

    assert result.status == CollectionStatus.FAILED.value
    assert "permission" in (result.last_error or "")


def test_5xx_and_timeout_are_bounded_retries() -> None:
    five_xx = ScriptedTransport([response(500), response(200, {"ok": True})])
    client = GitHubClient(
        "token", transport=five_xx, max_attempts=2, sleep=lambda _: None
    )
    outcome = client.get_json(
        "/fixture", stage=Stage.METADATA, endpoint_category="fixture"
    )
    assert [record.http_status for record in outcome.records] == [500, 200]

    timeout = ScriptedTransport([TimeoutError("slow"), response(200, {"ok": True})])
    client = GitHubClient(
        "token", transport=timeout, max_attempts=2, sleep=lambda _: None
    )
    outcome = client.get_json(
        "/fixture", stage=Stage.METADATA, endpoint_category="fixture"
    )
    assert [record.http_status for record in outcome.records] == [0, 200]
    assert outcome.records[0].error == "TimeoutError: slow"


def test_truncated_tree_is_partial_without_subtree_calls(tmp_path: Path) -> None:
    transport = ScriptedTransport(full_success_responses(truncated=True))
    runner = RepoFetchBenchmark(
        GitHubClient("token", transport=transport, sleep=lambda _: None),
        CheckpointStore(tmp_path / "checkpoint.json"),
    )

    result = runner.fetch_repo(candidate())

    assert result.status == CollectionStatus.PARTIAL.value
    assert result.tree_truncated is True
    assert result.core_calls == 3
    assert result.raw_calls == 1
    assert all(
        "/git/trees/" not in url or "recursive=1" in url
        for url, _ in transport.requests
    )


def test_checkpoint_resume_skips_successful_repo(tmp_path: Path) -> None:
    checkpoint = CheckpointStore(tmp_path / "checkpoint.json")
    first_transport = ScriptedTransport(
        [rate_response(), *full_success_responses(), rate_response(4997)]
    )
    runner = RepoFetchBenchmark(
        GitHubClient("token", transport=first_transport, sleep=lambda _: None),
        checkpoint,
    )
    first = runner.run([candidate()])
    assert first["sample_size"] == 1

    second_transport = ScriptedTransport([rate_response(4997), rate_response(4997)])
    runner = RepoFetchBenchmark(
        GitHubClient("token", transport=second_transport, sleep=lambda _: None),
        CheckpointStore(tmp_path / "checkpoint.json"),
    )
    second = runner.run([candidate()])

    assert second["sample_size"] == 0
    assert second["checkpoint_total"]["sample_size"] == 1
    assert len(second_transport.requests) == 2
    persisted = json.loads((tmp_path / "checkpoint.json").read_text())
    assert persisted["repos"]["1"]["status"] == CollectionStatus.SUCCEEDED.value


def test_safety_threshold_stops_before_repo_request(tmp_path: Path) -> None:
    transport = ScriptedTransport([rate_response(199), rate_response(199)])
    runner = RepoFetchBenchmark(
        GitHubClient("token", transport=transport, sleep=lambda _: None),
        CheckpointStore(tmp_path / "checkpoint.json"),
        safety_threshold=200,
    )

    summary = runner.run([candidate()])

    assert summary["sample_size"] == 0
    assert summary["stopped_reason"] == "RATE_LIMIT_SAFETY_THRESHOLD"
    assert len(transport.requests) == 2


def test_same_sha_reuses_artifact_and_changed_sha_requires_snapshot(
    tmp_path: Path,
) -> None:
    checkpoint = CheckpointStore(tmp_path / "checkpoint.json")
    first_transport = ScriptedTransport(
        [rate_response(), *full_success_responses(), rate_response(4997)]
    )
    RepoFetchBenchmark(
        GitHubClient("token", transport=first_transport, sleep=lambda _: None),
        checkpoint,
    ).run([candidate()])

    same_head = response(200, {"commit": {"sha": "a" * 40}})
    same_transport = ScriptedTransport(
        [rate_response(4997), same_head, rate_response(4996)]
    )
    summary = RepoFetchBenchmark(
        GitHubClient("token", transport=same_transport, sleep=lambda _: None),
        CheckpointStore(tmp_path / "checkpoint.json"),
    ).run([candidate()], revalidate_succeeded=True)
    result = summary["results"][0]
    assert result["status"] == CollectionStatus.SUCCEEDED.value
    assert result["cache_reused"] is True
    assert result["core_calls"] == 1

    changed_head = response(200, {"commit": {"sha": "c" * 40}})
    changed_transport = ScriptedTransport(
        [rate_response(4996), changed_head, rate_response(4995)]
    )
    summary = RepoFetchBenchmark(
        GitHubClient("token", transport=changed_transport, sleep=lambda _: None),
        CheckpointStore(tmp_path / "checkpoint.json"),
    ).run([candidate()], revalidate_succeeded=True)
    assert summary["results"][0]["status"] == CollectionStatus.PARTIAL.value
    assert "new full snapshot" in summary["results"][0]["last_error"]


def test_manifest_selection_is_bounded_and_root_first() -> None:
    entries = [
        {"path": "nested/package.json", "type": "blob"},
        {"path": "requirements.txt", "type": "blob"},
        {"path": "package.json", "type": "tree"},
        {"path": "README.md", "type": "blob"},
        {"path": "Cargo.toml", "type": "blob"},
    ]

    assert select_manifest_candidates(entries, limit=2) == (
        "requirements.txt",
        "Cargo.toml",
    )


def test_distributions_and_bootstrap_estimate_distinguish_measured_projection() -> None:
    assert distribution([1, 2, 3, 4])["p95"] == pytest.approx(3.85)
    summary = {
        "safety_threshold": 200,
        "rate_limit_before": {"limit": 5000},
        "repo_metrics": {
            "core_calls": {"mean": 3.0},
            "response_bytes": {"mean": 1000.0},
            "elapsed_seconds": {"mean": 2.0},
        },
    }
    coverage = [
        {"top_n": 20_000, "coverage_valid": 0.24},
        {"top_n": 50_000, "coverage_valid": 0.32},
    ]

    estimate = estimate_bootstrap(summary, coverage, candidate_sizes=(20_000,))
    assert "duration_scenarios" not in estimate

    assert estimate["available"] is True
    assert estimate["repos_per_cycle"] == 1600
    assert estimate["repos_per_day"] == 38_400
    assert estimate["candidate_projections"][0]["estimated_core_calls"] == 60_000
    assert estimate["candidate_projections"][0][
        "estimated_calendar_seconds"
    ] == pytest.approx(45_000)
    assert coverage_for_n(coverage, 35_000) == pytest.approx(0.28)
    assert coverage_for_n(coverage, 100_000) is None
    assert estimate["repo_count_basis"] == "attempted"
    assert estimate["measured_success_rate"] is None
    assert estimate["candidate_projections"][0]["collected_repo_count"] is None

    with_outcome = dict(summary)
    with_outcome["outcome_metrics"] = {
        "totals": {
            "attempted": 50,
            "collected": 28,
            "missing": 22,
            "success_rate": 0.56,
            "missing_rate": 0.44,
        }
    }
    measured = estimate_bootstrap(with_outcome, coverage, candidate_sizes=(20_000,))
    projection = measured["candidate_projections"][0]
    assert measured["measured_success_rate"] == pytest.approx(0.56)
    assert measured["collected_repos_per_day"] == pytest.approx(38_400 * 0.56)
    assert projection["attempted_repo_count"] == 20_000
    assert projection["collected_repo_count"] == 11_200
    assert projection["coverage_attempted"] == pytest.approx(0.24)
    assert projection["coverage_collected_uniform"] == pytest.approx(0.1344)


def test_outcome_metrics_separate_collected_from_missing_cost(tmp_path: Path) -> None:
    """A NOT_FOUND repo costs 1 core call; blending it hides the real unit cost."""
    store = CheckpointStore(tmp_path / "cp.json")
    transport = ScriptedTransport(
        [
            rate_response(),
            *full_success_responses(),
            response(404, {"message": "Not Found"}),
            rate_response(),
        ]
    )
    runner = RepoFetchBenchmark(
        GitHubClient("t", transport=transport, sleep=lambda _: None), store
    )
    summary = runner.run(
        [candidate(1, "owner/repo"), candidate(2, "gone/repo", rank=2)]
    )
    totals = summary["outcome_metrics"]["totals"]
    assert totals["attempted"] == 2
    assert totals["collected"] == 1
    assert totals["missing"] == 1
    assert totals["success_rate"] == 0.5
    assert totals["missing_rate"] == 0.5
    metrics = summary["outcome_metrics"]
    assert metrics[CollectionStatus.SUCCEEDED.value]["core_calls"]["mean"] == 3.0
    assert metrics[CollectionStatus.NOT_FOUND.value]["core_calls"]["mean"] == 1.0
    assert outcome_metrics([])["totals"]["success_rate"] is None


def test_artifact_rate_separates_http_200_from_usable_input(tmp_path: Path) -> None:
    """HTTP 200 on the tree is not the same as a repo C can analyse.

    Measured n=50: 28 repos returned 200 but only 6 carried a dependency
    manifest, so coverage reported on SUCCEEDED overstates usable input 4.7x.
    """
    transport = ScriptedTransport(
        [
            rate_response(),
            *full_success_responses(),
            response(
                200,
                {"full_name": "bare/repo", "default_branch": "main"},
            ),
            response(
                200,
                {"commit": {"sha": "c" * 40, "commit": {"tree": {"sha": "d" * 40}}}},
            ),
            response(
                200,
                {"truncated": False, "tree": [{"path": "README.md", "type": "blob"}]},
            ),
            rate_response(),
        ]
    )
    runner = RepoFetchBenchmark(
        GitHubClient("t", transport=transport, sleep=lambda _: None),
        CheckpointStore(tmp_path / "cp.json"),
    )
    summary = runner.run(
        [candidate(1, "owner/repo"), candidate(2, "bare/repo", rank=2)]
    )
    totals = summary["outcome_metrics"]["totals"]
    assert totals["collected"] == 2
    assert totals["analyzable"] == 1
    assert totals["success_rate"] == 1.0
    assert totals["artifact_rate"] == 0.5
    assert totals["artifact_rate_given_collected"] == 0.5


def test_budget_consumed_counts_the_followed_301_that_core_calls_misses() -> None:
    """A renamed repo costs 2 budget units per request; only 1 is logged.

    Measured n=50: the one renamed repo showed x-ratelimit-used stepping +2 on
    each of its three requests, so 'exactly 3 core calls' is true of requests
    and false of budget.
    """
    redirected = dict(RATE_HEADERS)
    redirected["x-ratelimit-used"] = "10"
    later = dict(RATE_HEADERS)
    later["x-ratelimit-used"] = "16"
    transport = ScriptedTransport(
        [
            response(
                200,
                {"full_name": "new/name", "default_branch": "main"},
                headers=redirected,
            ),
            response(
                200,
                {"commit": {"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}}},
                headers=later,
            ),
            response(200, {"truncated": False, "tree": []}, headers=later),
        ]
    )
    runner = RepoFetchBenchmark(
        GitHubClient("t", transport=transport, sleep=lambda _: None),
        CheckpointStore(Path("/tmp/unused-cp.json")),
    )
    result = runner.fetch_repo(candidate(1, "old/name"))
    assert result.renamed is True
    assert result.core_calls == 3
    assert result.budget_consumed == 7


def test_checkpoint_flush_interval_bounds_write_amplification(tmp_path: Path) -> None:
    """save() rewrites the whole file, so flushing per repo is O(N**2) per run."""
    path = tmp_path / "cp.json"
    store = CheckpointStore(path, flush_every=3)
    cands = [candidate(i, f"o/r{i}", rank=i) for i in range(1, 4)]
    store.ensure_candidates(cands)
    store.save()
    for index, cand in enumerate(cands, start=1):
        store.record_result(
            RepoResult(
                repo_id=cand.repo_id,
                repo_name=cand.repo_name,
                rank=cand.rank,
                stratum="top",
                status=CollectionStatus.NOT_FOUND.value,
            )
        )
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        recorded = sum(
            1 for row in on_disk["repos"].values() if row.get("status") == "NOT_FOUND"
        )
        assert recorded == (3 if index == 3 else 0)
    with pytest.raises(ValueError):
        CheckpointStore(path, flush_every=0)


def test_persisted_scalars_survive_a_checkpoint_without_the_request_log() -> None:
    """Dropping `requests` must not silently zero the derived cost metrics."""
    full = RepoResult(
        repo_id=1,
        repo_name="o/r",
        rank=1,
        stratum="top",
        status=CollectionStatus.SUCCEEDED.value,
        manifest_success_count=2,
    )
    full.requests.append(
        RequestRecord(
            stage=Stage.TREE.value,
            endpoint_category="recursive_tree",
            http_status=200,
            response_bytes=1234,
            elapsed_seconds=1.5,
            is_core=True,
        )
    )
    stripped = dict(full.as_dict())
    stripped["requests"] = []
    restored = RepoResult.from_dict(stripped)
    assert restored.core_calls == 1
    assert restored.response_bytes == 1234
    assert restored.elapsed_seconds == pytest.approx(1.5)
    assert restored.has_analyzable_artifact is True


def test_403_with_retry_after_is_rate_limited_not_failed(tmp_path: Path) -> None:
    """GitHub signals the secondary limit with 403 + Retry-After and full quota."""
    headers = dict(RATE_HEADERS)
    headers["Retry-After"] = "60"
    transport = ScriptedTransport(
        [
            rate_response(),
            response(403, {"message": "secondary"}, headers=headers),
            rate_response(),
        ]
    )
    runner = RepoFetchBenchmark(
        GitHubClient("t", transport=transport, sleep=lambda _: None),
        CheckpointStore(tmp_path / "cp.json"),
    )
    summary = runner.run([candidate()])
    assert summary["status_counts"] == {CollectionStatus.RATE_LIMITED.value: 1}
    assert summary["stopped_reason"] == "RATE_LIMIT_RESPONSE"
    assert summary["remaining_candidate_count"] == 1


def test_multi_cycle_run_waits_for_reset_and_finishes_remaining(
    tmp_path: Path,
) -> None:
    """A multi-day bootstrap must survive the hourly window, not exit at it."""
    exhausted = dict(RATE_HEADERS)
    exhausted["x-ratelimit-remaining"] = "0"
    transport = ScriptedTransport(
        [
            rate_response(),
            response(404, {"message": "Not Found"}, headers=exhausted),
            rate_response(),
            *full_success_responses(),
            rate_response(),
        ]
    )
    slept: list[float] = []
    runner = RepoFetchBenchmark(
        GitHubClient("t", transport=transport, sleep=slept.append),
        CheckpointStore(tmp_path / "cp.json"),
        now=lambda: 1_999_999_000.0,
    )
    summary = runner.run(
        [candidate(1, "gone/one"), candidate(2, "owner/repo", rank=2)], max_cycles=2
    )
    assert summary["cycles_used"] == 2
    assert slept == [pytest.approx(1001.0)]
    assert summary["waited_seconds"] == pytest.approx(1001.0)
    assert summary["remaining_candidate_count"] == 0
    assert CollectionStatus.SUCCEEDED.value in summary["status_counts"]


def test_classify_missing_separates_rename_from_deletion(tmp_path: Path) -> None:
    """A 404 by name cannot be a plain rename: /repos already follows the 301."""
    store = CheckpointStore(tmp_path / "cp.json")
    candidates = [
        candidate(1, "old/one", rank=1),
        candidate(2, "gone/two", rank=2),
        candidate(3, "alive/three", rank=3),
    ]
    transport = ScriptedTransport(
        [
            rate_response(),
            response(404, {"message": "Not Found"}),
            response(404, {"message": "Not Found"}),
            response(404, {"message": "Not Found"}),
            rate_response(),
            response(200, {"full_name": "new/one"}),
            response(404, {"message": "Not Found"}),
            response(404, {"message": "Not Found"}),
            response(404, {"message": "Not Found"}),
            response(200, {"login": "alive"}),
        ]
    )
    runner = RepoFetchBenchmark(
        GitHubClient("t", transport=transport, sleep=lambda _: None), store
    )
    runner.run(candidates)
    report = runner.classify_missing(candidates)
    assert report["examined"] == 3
    assert report["reason_counts"] == {
        MissingReason.OWNER_GONE.value: 1,
        MissingReason.RENAMED_OR_TRANSFERRED.value: 1,
        MissingReason.REPO_GONE_OWNER_ALIVE.value: 1,
    }
    assert report["core_calls"] == 5
    assert report["rows"][0]["current_repo_name"] == "new/one"


def test_candidate_coverage_and_strata_are_deterministic() -> None:
    assert parse_positive_ints("200000, 50000,50000") == (50_000, 200_000)
    with pytest.raises(ValueError):
        parse_positive_ints("0,100")

    targets = stratified_target_ranks(50)
    assert len(targets) == 50
    assert len({rank for _, rank in targets}) == 50
    assert {name for name, _ in targets} == {
        "rank_1_100",
        "around_1k",
        "around_5k",
        "around_20k",
        "around_50k",
        "around_100k",
        "around_200k",
    }

    rows = coverage_rows_from_counts(
        (20_000, 50_000),
        (20_000, 50_000),
        (240, 320),
        valid_event_count=1000,
        total_event_count=1100,
    )
    assert rows[0]["coverage_valid"] == pytest.approx(0.24)
    assert rows[1]["coverage_delta_valid"] == pytest.approx(0.08)


def test_root_probe_agrees_with_the_tree_without_spending_core_budget() -> None:
    """The recursive tree is 98.6% of bytes; root probing must be shown equivalent.

    Measured n=28: root probing found a manifest in exactly the 6 repositories
    whose recursive tree contained one, and widening the basename list from 12
    to 30 added none.
    """
    served = {"package.json", "README.md"}
    calls: list[str] = []

    def fake_fetch(url: str, head_bytes: int, timeout: float) -> tuple[int, int]:
        calls.append(url)
        assert url.startswith("https://raw.githubusercontent.com/")
        return (206, 128) if url.rsplit("/", 1)[-1] in served else (404, 0)

    hit = ProbeTarget(1, "o/hit", "a" * 40, 1, ("package.json", "apps/x/package.json"))
    miss = ProbeTarget(2, "o/miss", "b" * 40, 2, ())
    served_none = {"README.md"}

    hit_result = probe_repository(hit, fetch=fake_fetch)
    served = served_none
    miss_result = probe_repository(miss, fetch=fake_fetch, widen=True)

    assert hit_result.found["probe"] == ("package.json",)
    assert miss_result.found["probe"] == ()
    assert miss_result.found["widened"] == ()
    assert miss_result.reachable is True

    summary = summarize([hit_result, miss_result])
    assert summary["core_calls"] == 0
    assert summary["tree_positive"] == 1
    assert summary["root_probe_positive"] == 1
    assert summary["recall_vs_tree"] == 1.0
    assert summary["agreement_rate"] == 1.0
    assert summary["widened_list_only"] == 0
    assert all("raw.githubusercontent.com" in url for url in calls)


def test_targets_from_checkpoint_uses_canonical_name_and_skips_unpinned() -> None:
    payload = {
        "repos": {
            "1": {
                "result": {
                    "status": "SUCCEEDED",
                    "repo_id": 1,
                    "repo_name": "old/name",
                    "canonical_repo_name": "new/name",
                    "pinned_commit_sha": "c" * 40,
                    "rank": 5,
                    "manifest_candidates": ["package.json"],
                }
            },
            "2": {"result": {"status": "NOT_FOUND", "repo_id": 2, "repo_name": "x/y"}},
            "3": {
                "result": {
                    "status": "SUCCEEDED",
                    "repo_id": 3,
                    "repo_name": "a/b",
                    "pinned_commit_sha": None,
                    "rank": 1,
                }
            },
        }
    }
    targets = targets_from_checkpoint(payload)
    assert [item.repo_name for item in targets] == ["new/name"]


def test_checkpoint_is_bound_to_one_dataset_period(tmp_path: Path) -> None:
    """The same pipeline runs for any month, so a checkpoint must not cross periods."""
    store = CheckpointStore(tmp_path / "cp.json")
    store.bind_dataset("hdfs:///.../period=2026-08/snapshot=s15p21e102-109-20260902")
    store.bind_dataset("hdfs:///.../period=2026-08/snapshot=s15p21e102-109-20260902")
    with pytest.raises(ValueError, match="different dataset"):
        store.bind_dataset("hdfs:///.../period=2026-09/snapshot=other")


def test_candidate_payload_reports_its_source_dataset(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            {
                "input_root": "hdfs:///gitjob/.../period=2026-08/snapshot=x",
                "candidates": [
                    {"repo_id": 1, "repo_name": "o/r", "rank": 1, "stratum": "top"}
                ],
                "coverage": [{"top_n": 20_000, "coverage_valid": 0.24}],
            }
        ),
        encoding="utf-8",
    )
    candidates, coverage, dataset_key = load_candidate_payload(path)
    assert [item.repo_name for item in candidates] == ["o/r"]
    assert coverage[0]["top_n"] == 20_000
    assert dataset_key.endswith("period=2026-08/snapshot=x")
