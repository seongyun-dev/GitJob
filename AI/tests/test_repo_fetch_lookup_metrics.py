"""Durable lookup instrumentation for the Redis before/after baseline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from github.repo_fetch_orchestrator import DurableLookupMetrics
from github.snapshot_input import _Summary
from tests.test_repo_fetch_orchestrator import (
    COMMIT_A,
    ScriptedTransport,
    candidate,
    head,
    metadata,
    orchestrator,
    rate_control,
    response,
    success_outcomes,
    tree,
)

LATER = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _second_pass_outcomes() -> list:
    """Resolve the same SHA, then stop at the durable cache."""

    return [rate_control(), metadata(), head(COMMIT_A)]


def test_cold_lookup_is_counted_as_a_durable_miss(tmp_path: Path) -> None:
    run = orchestrator(tmp_path, ScriptedTransport(success_outcomes())).run(
        [candidate()]
    )

    summary = run.summary()

    assert summary["durable_lookup_count"] == 1
    assert summary["durable_miss"] == 1
    assert summary["durable_hit"] == 0
    assert summary["durable_hit_rate"] == 0.0


def test_replay_counts_durable_hit_and_avoids_new_extraction(tmp_path: Path) -> None:
    first = orchestrator(tmp_path, ScriptedTransport(success_outcomes()))
    first_summary = first.run([candidate()]).summary()

    second = orchestrator(
        tmp_path,
        ScriptedTransport(_second_pass_outcomes()),
        now=LATER,
        checkpoint_name="checkpoint-2.json",
    )
    summary = second.run([candidate()]).summary()

    assert summary["durable_lookup_count"] == 1
    assert summary["durable_hit"] == 1
    assert summary["durable_miss"] == 0
    assert summary["durable_hit_rate"] == 1.0
    assert summary["artifact_writes"] == 0
    assert summary["reused_artifact_count"] == 1
    assert summary["new_extraction_count"] == 0
    assert summary["github_api_total"] < first_summary["github_api_total"]


def test_durable_hit_and_miss_partition_lookup_count(tmp_path: Path) -> None:
    orchestrator(tmp_path, ScriptedTransport(success_outcomes())).run([candidate()])

    summary = (
        orchestrator(
            tmp_path,
            ScriptedTransport(_second_pass_outcomes()),
            now=LATER,
            checkpoint_name="checkpoint-2.json",
        )
        .run([candidate()])
        .summary()
    )

    assert (
        summary["durable_hit"] + summary["durable_miss"]
        == summary["durable_lookup_count"]
    )


def test_lookup_percentiles_are_safe_for_empty_and_small_samples() -> None:
    empty = DurableLookupMetrics()
    assert empty.percentile_ms(0.50) is None
    assert empty.percentile_ms(0.95) is None
    assert empty.hit_rate is None

    metrics = DurableLookupMetrics()
    for value in (10.0, 1.0, 5.0, 100.0):
        metrics.record_lookup(hit=False, elapsed_ms=value)

    assert metrics.percentile_ms(0.50) == 5.0
    assert metrics.percentile_ms(0.95) == 100.0
    assert metrics.lookups == 4


def test_artifact_writes_count_successful_store_calls(tmp_path: Path) -> None:
    body = b'{"dependencies": {}}'
    transport = ScriptedTransport(
        [
            rate_control(),
            metadata(),
            head(),
            tree(
                [
                    {"path": "package.json", "type": "blob", "size": len(body)},
                    {"path": "Dockerfile", "type": "blob", "size": len(body)},
                ]
            ),
            response(body),
            response(body),
        ]
    )

    run = orchestrator(tmp_path, transport).run([candidate()])

    assert run.summary()["artifact_writes"] == 2
    assert run.summary()["artifact_writes"] == sum(
        len(record.artifacts) for record in run.batch.records
    )
    assert run.summary()["new_extraction_count"] == 1


def test_additive_metrics_preserve_summary_schema_and_consumer_compatibility(
    tmp_path: Path,
) -> None:
    summary = (
        orchestrator(tmp_path, ScriptedTransport(success_outcomes()))
        .run([candidate()])
        .summary()
    )

    assert summary["schema_version"] == "github-repo-fetch-run-summary/v1"
    assert summary["redis_enabled"] is False
    assert summary["redis_lookup_count"] == 0
    assert summary["redis_hit_count"] == 0
    assert summary["redis_miss_count"] == 0
    assert summary["redis_hit_rate"] is None
    assert summary["redis_lookup_latency_p50_ms"] is None
    assert summary["redis_lookup_latency_p95_ms"] is None
    assert summary["redis_error_count"] == 0
    assert summary["redis_fail_open_count"] == 0
    assert summary["redis_durable_validation_count"] == 0
    assert summary["redis_durable_fallback_count"] == 0
    loaded = _Summary.model_validate(summary)
    assert loaded.schema_version == summary["schema_version"]
    assert summary["github_api_total"] == (
        summary["github_api_core"] + summary["github_api_raw"]
    )
    # Throughput is reported only when there is a duration to divide by
    # (`repo_fetch_orchestrator`: `... if elapsed > 0 else None`). A scripted
    # transport can finish inside the clock's resolution, so `elapsed` of 0 and
    # a `None` rate is the contract working, not a defect. Asserting the rate is
    # always present made this test fail on roughly 40% of runs.
    assert summary["elapsed_seconds"] >= 0.0
    if summary["elapsed_seconds"] > 0:
        assert summary["repos_per_second"] is not None
        assert summary["repos_per_second"] > 0
    else:
        assert summary["repos_per_second"] is None


def test_historical_lookup_uses_isolated_cache_identity(tmp_path: Path) -> None:
    orchestrator(tmp_path, ScriptedTransport(success_outcomes())).run([candidate()])

    historical_summary = (
        orchestrator(
            tmp_path,
            ScriptedTransport(success_outcomes()),
            now=LATER,
            require_historical_head=True,
            checkpoint_name="checkpoint-historical.json",
        )
        .run([candidate(monthly_sha=COMMIT_A)])
        .summary()
    )

    assert historical_summary["durable_lookup_count"] == 1
    assert historical_summary["durable_hit"] == 0
    assert historical_summary["durable_miss"] == 1
