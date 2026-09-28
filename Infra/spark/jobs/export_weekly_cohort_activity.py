"""Join a fixed repository cohort against one week's activity aggregate.

`weekly_public_publish_cli` needs a `--week-activity` file: the `repo_id` and
`event_count` of every cohort repository that was active in one ISO week. The
job that produced that file for 2026-03-09 .. 2026-03-30 on 2026-09-20 was
named `gitjob-cohort-week-semijoin` and lived outside this repository; it is
gone, which is why the remaining weeks cannot be published. This job is that
step, written against the aggregate and the cohort that are still on HDFS.

### Why a semi join and not a left join

The weekly aggregate is a `groupBy` over events, so a repository with no
activity in the week has no row at all -- the minimum `event_count` in the
2026-03-09 aggregate is 1, across 3,854,460 rows. Left-joining the cohort onto
it would manufacture zero rows for repositories that did nothing that week, and
`build_weekly_cohort_publication` would then put them in the week's candidate
set. Keeping only aggregate rows whose `repo_id` is in the cohort is what the
published weeks actually contain: for 2026-03-09 the cohort met the aggregate
in 5,112 repositories and the publication carried 5,089 of them, the difference
being repositories the generator itself drops for having no reusable evidence.

### The cohort that reproduces the published weeks

Measured against the 2026-03-09 publication, which this reproduces byte for
byte in all four objects:

* the sources are the five monthly Top-10k snapshots `202604 .. 202608`;
  `202603` contributed no record and is not passed
* they are passed **newest month first**, because `select_cohort_records` keeps
  the first record it sees for a repository. All 5,089 published records come
  from the newest snapshot that holds their repository -- 5,089 of 5,089, no
  exceptions -- so oldest-first produces a different publication
* membership is the repositories that have an artifact directory under those
  five snapshots (10,211), not every record in them (18,575). Passing all the
  records yields 5,741 candidates instead of 5,089

### What this job does not decide

It does not choose the cohort. The caller passes the same repository-ID source
`export_c_archive_activity` accepts, and the publisher is handed the same
cohort snapshots, so the two stages cannot drift onto different populations.
It also does not filter by collection status or artifacts: that is
`weekly_cohort_snapshot._reusable`'s decision and duplicating it here would put
the same rule in two places.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from jobs.export_c_archive_activity import load_repo_ids

ACTIVITY_COLUMNS = ("repo_id", "event_count", "week_start")
# `export_c_archive_activity.MAX_EXPORT_ROWS` bounds what C will later read out
# of one week; there is no reason for this file to be larger than that.
MAX_ROWS = 50_000
MAX_COHORT_ROWS = 100_000


def select_week_activity(
    rows: Iterable[Mapping[str, object]],
    cohort_ids: Iterable[int],
    *,
    week_start: str,
    max_rows: int = MAX_ROWS,
) -> tuple[dict[str, object], ...]:
    """Keep the aggregate rows whose repository is in the cohort."""

    cohort = set(cohort_ids)
    if not cohort:
        raise ValueError("cohort must not be empty")
    selected: dict[int, int] = {}
    for number, row in enumerate(rows, start=1):
        repo_id, events, week = (
            row.get("repo_id"),
            row.get("event_count"),
            row.get("week_start"),
        )
        if str(week) != week_start:
            raise ValueError(
                f"activity row {number} has week_start {week}, expected {week_start}"
            )
        for name, value in (("repo_id", repo_id), ("event_count", events)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(
                    f"activity row {number} has a non-positive integer {name}: {value!r}"
                )
        if repo_id not in cohort:
            continue
        if repo_id in selected:
            raise ValueError(f"duplicate repo_id in the weekly aggregate: {repo_id}")
        selected[repo_id] = events
        if len(selected) > max_rows:
            raise ValueError(f"weekly activity exceeds max_rows={max_rows}")
    # Sorted the way the publication ranks its records, so the file, the ranks
    # and the run summary all describe the week in one order.
    return tuple(
        {"repo_id": repo_id, "event_count": selected[repo_id], "week_start": week_start}
        for repo_id in sorted(selected, key=lambda key: (-selected[key], key))
    )


def render_ndjson(rows: Sequence[Mapping[str, object]]) -> bytes:
    """One row per line, keys sorted, so the same week renders the same bytes."""

    return "".join(
        json.dumps(
            {column: row[column] for column in ACTIVITY_COLUMNS},
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for row in rows
    ).encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write one week's cohort activity for weekly_public_publish_cli"
    )
    parser.add_argument("--input", required=True, help="one week= directory")
    parser.add_argument("--repo-ids", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--week-start", required=True)
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS)
    parser.add_argument("--app-name", default="gitjob-weekly-cohort-activity")
    return parser


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - Spark entry point
    arguments = _parser().parse_args(argv)
    if arguments.output.exists():
        raise FileExistsError(
            f"refusing to overwrite existing output: {arguments.output}"
        )
    cohort = load_repo_ids(arguments.repo_ids, max_rows=MAX_COHORT_ROWS)

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = SparkSession.builder.appName(arguments.app_name).getOrCreate()
    try:
        activity = spark.read.parquet(arguments.input).select(
            F.col("repo_id").cast("long").alias("repo_id"),
            F.col("event_count").cast("long").alias("event_count"),
            F.date_format(F.col("week_start"), "yyyy-MM-dd").alias("week_start"),
        )
        ids = spark.createDataFrame([(repo_id,) for repo_id in cohort], "repo_id long")
        # Left semi, never left outer: a cohort repository with no row this week
        # must stay absent rather than arrive as a zero.
        matched = activity.join(F.broadcast(ids), "repo_id", "left_semi")
        rows = [row.asDict() for row in matched.toLocalIterator()]
    finally:
        spark.stop()

    selected = select_week_activity(
        rows, cohort, week_start=arguments.week_start, max_rows=arguments.max_rows
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(render_ndjson(selected))
    print(
        json.dumps(
            {
                "week_start": arguments.week_start,
                "cohort_repo_count": len(cohort),
                "matched_repo_count": len(selected),
                "event_count": sum(int(row["event_count"]) for row in selected),
                "output": str(arguments.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
