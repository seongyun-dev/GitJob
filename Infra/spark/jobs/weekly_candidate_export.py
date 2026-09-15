"""Bounded Top-N read-back of `repo_activity_weekly` for the Weekly resolver.

`weekly_artifact_resolver.py` takes `--candidates <JSON>` and has always had
`build_weekly_candidates()` to produce it, but nothing ever called that
function outside tests. The gap was not a path or a config value: there was no
job that turned the Weekly Parquet into candidate rows at all, so the Weekly
Artifact run could not start (S15P21E102-276).

## Why this is a separate job from the resolver

The Spark image copies `Infra/spark` and nothing else, so a job here cannot
import `github.weekly_artifact_resolver`. The split follows what
`weekly_activity_publish.py` already does for manifests: Spark does the wide
read, and the contract is applied where the clients live. This job therefore
emits *rows*, not the candidate contract — `weekly_candidate_export_cli`
feeds those rows to `build_weekly_candidates()` and writes the real
`repo-activity-weekly-candidates/v1` document.

## Why the driver never sees the week

A week of `repo_activity_weekly` is millions of rows — 2026-08 alone carries
about 7.9M. The select/sort/limit stays in Spark and only the surviving
`--limit` rows are collected, so the driver holds the candidate pool and not
the week. `MAX_EXPORT_ROWS` is the hard ceiling on that promise: a caller that
asks for a limit large enough to hurt the driver is refused rather than
quietly tolerated.

The ordering is `event_count` descending then `repo_id` ascending, which is
the same key `build_weekly_candidates()` sorts by. Matching it here means the
rank the resolver assigns is the rank this job selected, not a second opinion.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

# Must match `ACTIVITY_COLUMNS` in `repo_activity_weekly.py`; the Weekly
# adapter in AI rejects a row that carries anything else (notably
# `monthly_event_sha`, which is Historical-only).
ACTIVITY_COLUMNS = ("repo_id", "repo_name", "event_count", "week_start")

EXPORT_SCHEMA_VERSION = "repo-activity-weekly-candidate-rows/v1"

# The driver collects at most this many rows. 50,000 is the same ceiling
# `AI/worker/weekly_activity_intake.py` uses for a bounded export, kept
# identical so the two limits cannot drift into disagreeing about what
# "bounded" means.
MAX_EXPORT_ROWS = 50_000

DEFAULT_LIMIT = 1_500


def parse_week(value: str) -> date:
    """A week is named by its Monday, exactly as the Parquet partition is."""

    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"week must be an ISO date: {value}") from error
    if parsed.isoformat() != value:
        raise ValueError(f"week must be a canonical ISO date: {value}")
    if parsed.weekday() != 0:
        raise ValueError(f"week must be a Monday: {value}")
    return parsed


def validate_limit(limit: int) -> int:
    if limit < 1:
        raise ValueError("limit must be positive")
    if limit > MAX_EXPORT_ROWS:
        raise ValueError(f"limit exceeds MAX_EXPORT_ROWS={MAX_EXPORT_ROWS}")
    return limit


def select_candidate_rows(frame: Any, *, week: date, limit: int) -> list[dict[str, Any]]:
    """Bounded Top-N selection pushed down to Spark.

    Kept out of `main` so the ordering and the column projection can be
    exercised without a cluster.
    """

    from pyspark.sql import functions as F

    selected = (
        frame.select(*ACTIVITY_COLUMNS)
        .where(F.col("week_start") == F.lit(week.isoformat()))
        .orderBy(F.col("event_count").desc(), F.col("repo_id").asc())
        .limit(limit)
    )
    return [row.asDict() for row in selected.collect()]


def build_export_document(
    rows: list[dict[str, Any]], *, input_root: str, week: date, limit: int
) -> dict[str, Any]:
    if not rows:
        raise ValueError(f"no Weekly activity rows for week {week.isoformat()}")
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "input_root": input_root,
        "week_start": week.isoformat(),
        "limit": limit,
        "row_count": len(rows),
        "rows": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export the Top-N rows of one repo_activity_weekly week for the "
            "Weekly Artifact candidate adapter."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="repo_activity_weekly root for the snapshot being read back.",
    )
    parser.add_argument("--week", required=True, help="Monday of the week, ISO date.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Candidate pool size to export (rank-ordered).",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Destination rows JSON."
    )
    parser.add_argument("--app-name", default="gitjob-weekly-candidate-export")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    week = parse_week(arguments.week)
    limit = validate_limit(arguments.limit)

    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName(arguments.app_name).getOrCreate()
    try:
        frame = spark.read.parquet(arguments.input)
        rows = select_candidate_rows(frame, week=week, limit=limit)
    finally:
        spark.stop()

    document = build_export_document(
        rows, input_root=arguments.input, week=week, limit=limit
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "week_start": document["week_start"],
                "limit": document["limit"],
                "row_count": document["row_count"],
                "output": str(arguments.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI delegation
    raise SystemExit(main())
