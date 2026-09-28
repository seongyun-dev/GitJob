"""Offline contract tests for the Weekly candidate export wiring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Infra" / "spark"))

from github.weekly_artifact_resolver import (  # noqa: E402
    WEEKLY_CANDIDATE_SCHEMA,
    WeeklyArtifactResolutionError,
    load_weekly_candidates,
)
from github.weekly_candidate_export_cli import (  # noqa: E402
    EXPORT_SCHEMA_VERSION,
    assert_week_is_published,
    load_export_rows,
    main,
    render_candidate_document,
)
from jobs.weekly_candidate_export import (  # noqa: E402
    MAX_EXPORT_ROWS,
    build_export_document,
    parse_week,
    validate_limit,
)

WEEK = "2026-03-02"


def row(repo_id: int, events: int, *, week: str = WEEK) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "repo_name": f"octo/repo-{repo_id}",
        "event_count": events,
        "week_start": week,
    }


def write_rows(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "rows.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": EXPORT_SCHEMA_VERSION,
                "input_root": "hdfs:///weekly/snapshot=a",
                "week_start": WEEK,
                "limit": 1500,
                "row_count": len(rows),
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    return path


class StubClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.reads: list[str] = []

    def read(self, uri: str) -> bytes:
        self.reads.append(uri)
        return json.dumps(self.payload).encode("utf-8")


def test_rank_follows_event_count_then_repo_id(tmp_path: Path) -> None:
    rows_path = write_rows(tmp_path, [row(3, 5), row(1, 9), row(2, 5)])
    out = tmp_path / "candidates.json"

    main(["--rows", str(rows_path), "--output", str(out), "--skip-manifest-check"])

    document = json.loads(out.read_text(encoding="utf-8"))
    assert [c["repo_id"] for c in document["candidates"]] == [1, 2, 3]
    assert [c["rank"] for c in document["candidates"]] == [1, 2, 3]


def test_limit_truncates_the_pool(tmp_path: Path) -> None:
    rows_path = write_rows(tmp_path, [row(i, 100 - i) for i in range(1, 11)])
    out = tmp_path / "candidates.json"

    main(
        [
            "--rows",
            str(rows_path),
            "--output",
            str(out),
            "--candidate-pool-limit",
            "4",
            "--skip-manifest-check",
        ]
    )

    document = json.loads(out.read_text(encoding="utf-8"))
    assert len(document["candidates"]) == 4
    assert [c["repo_id"] for c in document["candidates"]] == [1, 2, 3, 4]


def test_output_loads_back_through_the_resolver_contract(tmp_path: Path) -> None:
    rows_path = write_rows(tmp_path, [row(1, 9), row(2, 4)])
    out = tmp_path / "candidates.json"

    main(["--rows", str(rows_path), "--output", str(out), "--skip-manifest-check"])

    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["schema_version"] == WEEKLY_CANDIDATE_SCHEMA

    loaded = load_weekly_candidates(out, limit=1500)
    assert loaded.week_start.isoformat() == WEEK
    assert [c.repo_id for c in loaded.candidates] == [1, 2]
    assert [c.activity_rank for c in loaded.candidates] == [1, 2]


def test_output_is_deterministic(tmp_path: Path) -> None:
    rows_path = write_rows(tmp_path, [row(2, 7), row(1, 7), row(3, 1)])
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"

    main(["--rows", str(rows_path), "--output", str(first), "--skip-manifest-check"])
    main(["--rows", str(rows_path), "--output", str(second), "--skip-manifest-check"])

    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_duplicate_repo_id_is_rejected(tmp_path: Path) -> None:
    rows_path = write_rows(tmp_path, [row(1, 9), row(1, 4)])
    with pytest.raises(ValueError, match="duplicate Weekly repo_id"):
        main(
            [
                "--rows",
                str(rows_path),
                "--output",
                str(tmp_path / "c.json"),
                "--skip-manifest-check",
            ]
        )


def test_historical_sha_column_is_rejected(tmp_path: Path) -> None:
    tainted = row(1, 9)
    tainted["monthly_event_sha"] = "a" * 40
    rows_path = write_rows(tmp_path, [tainted])
    with pytest.raises(WeeklyArtifactResolutionError, match="monthly_event_sha"):
        main(
            [
                "--rows",
                str(rows_path),
                "--output",
                str(tmp_path / "c.json"),
                "--skip-manifest-check",
            ]
        )


def test_empty_rows_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rows.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": EXPORT_SCHEMA_VERSION,
                "input_root": "hdfs:///weekly",
                "week_start": WEEK,
                "rows": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must contain rows"):
        load_export_rows(path)


def test_malformed_export_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rows.json"
    path.write_text(json.dumps({"schema_version": "something-else"}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported weekly row export"):
        load_export_rows(path)


def test_manifest_must_be_readable_and_name_a_snapshot() -> None:
    ok = StubClient({"dataset_snapshot_id": "s15p21e102-weekly-x"})
    assert_week_is_published(ok, "hdfs:///weekly/_SUCCESS.json")
    assert ok.reads == ["hdfs:///weekly/_SUCCESS.json"]

    with pytest.raises(ValueError, match="no dataset_snapshot_id"):
        assert_week_is_published(StubClient({}), "hdfs:///weekly/_SUCCESS.json")


def test_candidate_document_never_carries_a_month_sha(tmp_path: Path) -> None:
    rows_path = write_rows(tmp_path, [row(1, 9)])
    rows, input_root, week_start = load_export_rows(rows_path)
    from github.weekly_artifact_resolver import build_weekly_candidates

    document = render_candidate_document(
        build_weekly_candidates(
            rows, input_root=input_root, week_start=week_start, limit=1500
        )
    )
    assert all("monthly_event_sha" not in c for c in document["candidates"])


def test_spark_job_week_and_limit_guards() -> None:
    assert parse_week(WEEK).isoformat() == WEEK
    with pytest.raises(ValueError, match="Monday"):
        parse_week("2026-03-03")
    # `date.fromisoformat` accepts the basic format since 3.11, so this is the
    # input that reaches the canonical check rather than the parse failure.
    with pytest.raises(ValueError, match="canonical"):
        parse_week("20260302")
    with pytest.raises(ValueError, match="must be an ISO date"):
        parse_week("not-a-date")

    assert validate_limit(1500) == 1500
    with pytest.raises(ValueError, match="positive"):
        validate_limit(0)
    with pytest.raises(ValueError, match="MAX_EXPORT_ROWS"):
        validate_limit(MAX_EXPORT_ROWS + 1)


def test_spark_job_refuses_a_week_with_no_rows() -> None:
    with pytest.raises(ValueError, match="no Weekly activity rows"):
        build_export_document([], input_root="hdfs:///w", week=parse_week(WEEK), limit=10)
