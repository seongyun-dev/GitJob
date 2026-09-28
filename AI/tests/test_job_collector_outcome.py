"""Tests for the shared scheduled collector outcome contract."""

from __future__ import annotations

import pytest

from job.collector.outcome import (
    collector_exit_code,
    empty_run_blockers,
    is_valid_empty_run,
)


def _manifest(source: str, **counts: int) -> dict[str, object]:
    return {
        "source_site": source,
        "pipeline_run_id": f"{source}-EMPTY-20260915",
        "stopped_reason": None,
        "counts": {
            "records": 0,
            "detail_errors": 0,
            "invalid_records": 0,
            **counts,
        },
    }


@pytest.mark.parametrize(
    ("source", "filter_counts"),
    [
        (
            "WORKNET",
            {"rows_seen": 24, "skipped_out_of_range": 24},
        ),
        (
            "SARAMIN",
            {"rows_seen": 18, "skipped_already_collected": 18},
        ),
        (
            "GAMEJOB",
            {
                "rows_seen": 80,
                "skipped_out_of_range": 35,
                "skipped_out_of_preset": 5,
            },
        ),
        (
            "CAREER",
            {"rows_seen": 1119, "skipped_out_of_range": 1116},
        ),
    ],
)
def test_valid_empty_contract_for_each_scheduled_source(
    source: str, filter_counts: dict[str, int]
):
    manifest = _manifest(source, **filter_counts)

    assert empty_run_blockers(manifest, source_site=source) == ()
    assert is_valid_empty_run(manifest, source_site=source)
    assert collector_exit_code(manifest, source_site=source) == 0


@pytest.mark.parametrize(
    "field",
    ["detail_errors", "invalid_records"],
)
def test_quality_error_never_becomes_success_empty(field: str):
    manifest = _manifest("GAMEJOB", **{field: 1})

    assert not is_valid_empty_run(manifest, source_site="GAMEJOB")
    assert collector_exit_code(manifest, source_site="GAMEJOB") == 1


def test_stopped_empty_run_is_failed():
    manifest = _manifest("CAREER")
    manifest["stopped_reason"] = "list fetch failed: HTTP 503"

    assert collector_exit_code(manifest, source_site="CAREER") == 1


def test_source_identity_mismatch_is_failed_closed():
    manifest = _manifest("CAREER")

    assert collector_exit_code(manifest, source_site="GAMEJOB") == 1


def test_nonempty_output_keeps_success_with_data():
    manifest = _manifest("WORKNET", records=3)

    assert collector_exit_code(manifest, source_site="WORKNET") == 0
