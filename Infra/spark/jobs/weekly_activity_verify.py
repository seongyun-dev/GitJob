"""Independent 7-day completeness verifier for the Weekly stream input.

`repo_activity_weekly` gates its stream input on *hour coverage*: an expected
UTC hour with no row in the archive is refused.  2026-09-17 showed what that
gate cannot see.  Of the 82 hours the pre-`S15P21E102-257` publisher never
checkpointed, **80 were present in HDFS** and would have satisfied it while
carrying 39.9% of their events -- the publisher died part-way through each
hour and every later pass re-sent the same prefix, so the hours looked
populated and were not.  A `week_start=2026-08-31` aggregation would have
reported zero missing hours and produced a weekly result from 37.9% of the
week.

So this job asks the question the gate does not: *for each hour, did every
event arrive?*  It reads the archive and nothing else, writes no HDFS output,
and answers with a PASS/FAIL report.  It is a pre-flight check for a recovery
run, not part of the aggregation -- `repo_activity_weekly` is unchanged.

### Why a count and not a checkpoint

The publisher's checkpoint says an hour finished.  It is silent about the
hours that did not, which are exactly the hours at risk: an hour that failed
part-way has no entry at all.  Completeness therefore has to be measured
against the source, not against the record of success.

### Identity

Counting uses `repo_activity_weekly.DEDUP_KEYS`, the `-102` section 4.1
envelope triple, and derives the hour from `source_id` through the same
`substring_index` split `repo_activity_weekly` applies.  Both are imported
rather than restated: a verifier that dedups differently from the job it
verifies proves nothing.

Duplicate rows are reported, never failed on.  Re-sending is the trade `-102`
section 4.1 chose and the aggregation folds them.  What fails is a *short*
hour.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jobs.repo_activity_weekly import (
    DEDUP_KEYS,
    INPUT_FORMAT_STREAM_PARQUET,
    STREAM_REQUIRED_COLUMNS,
    STREAM_SOURCE,
    expected_stream_hours,
    validate_period,
    validate_stream_hour,
)

SCHEMA_VERSION = "weekly-stream-completeness-report/v1"

# One hour of a week.  `MISSING` and `PARTIAL` are the two the presence-only
# gate conflates; keeping them apart is the point of this job.
HOUR_MISSING = "MISSING"
HOUR_PARTIAL = "PARTIAL"
HOUR_COMPLETE = "COMPLETE"
HOUR_OVERFULL = "OVERFULL_AFTER_DEDUP"
HOUR_UNKNOWN = "UNKNOWN"

HOUR_CLASSIFICATIONS = (
    HOUR_COMPLETE,
    HOUR_PARTIAL,
    HOUR_MISSING,
    HOUR_OVERFULL,
    HOUR_UNKNOWN,
)

# Anything but COMPLETE blocks a recovery run.  `OVERFULL_AFTER_DEDUP` is here
# because distinct identities exceeding the source is not a duplicate -- it
# means the archive holds events the source file does not, which no amount of
# re-publishing explains and an operator has to look at.
BLOCKING_CLASSIFICATIONS = (
    HOUR_MISSING,
    HOUR_PARTIAL,
    HOUR_OVERFULL,
    HOUR_UNKNOWN,
)

MAX_REPORTED_HOURS = 20


class ExpectedCountsUnavailable(ValueError):
    """No usable source of per-hour expected counts was supplied."""


def classify_hour(
    expected: int | None, raw_row_count: int, deduplicated_count: int
) -> str:
    """Classify one hour from its source count and its two archive counts.

    `deduplicated_count` is what the aggregation would actually count, so it is
    the number compared against the source.  `raw_row_count` only ever feeds
    the duplicate figure.
    """

    if raw_row_count < 0 or deduplicated_count < 0:
        raise ValueError("counts must not be negative")
    if deduplicated_count > raw_row_count:
        raise ValueError(
            "deduplicated_count cannot exceed raw_row_count: "
            f"{deduplicated_count} > {raw_row_count}"
        )
    if expected is None:
        return HOUR_UNKNOWN
    if expected < 0:
        raise ValueError("expected must not be negative")
    if deduplicated_count == 0:
        # An hour whose source is genuinely empty is complete at zero; every
        # other zero is an hour that never landed.
        return HOUR_COMPLETE if expected == 0 else HOUR_MISSING
    if deduplicated_count > expected:
        return HOUR_OVERFULL
    if deduplicated_count < expected:
        return HOUR_PARTIAL
    return HOUR_COMPLETE


def normalize_expected_counts(values: Mapping[str, object]) -> dict[str, int]:
    """Validate a ``{hour_key: event_count}`` mapping.

    Hour keys go through `validate_stream_hour` so a typo becomes an error here
    instead of a silently `UNKNOWN` hour later.
    """

    counts: dict[str, int] = {}
    for hour_key, value in values.items():
        validated = validate_stream_hour(hour_key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"expected count for {validated} must be an integer")
        if value < 0:
            raise ValueError(f"expected count for {validated} must not be negative")
        counts[validated] = value
    return counts


def expected_counts_from_publish_checkpoint(
    document: Mapping[str, object],
) -> dict[str, int]:
    """Read per-hour source counts out of the publisher's checkpoint.

    This is canonical runtime metadata and is preferred, with one caveat that
    is the whole reason this verifier exists: it only records hours that
    *finished*.  Hours that failed part-way are absent, so a checkpoint alone
    leaves exactly the at-risk hours `UNKNOWN`.  Supply `--expected-counts`
    alongside it to resolve them.
    """

    published = document.get("published")
    if not isinstance(published, Mapping):
        raise TypeError("publish checkpoint has no 'published' object")
    values: dict[str, object] = {}
    for hour_key, entry in published.items():
        if not isinstance(entry, Mapping):
            raise TypeError(f"publish checkpoint entry is not an object: {hour_key}")
        values[hour_key] = entry.get("events")
    return normalize_expected_counts(values)


def merge_expected_counts(*sources: Mapping[str, int] | None) -> dict[str, int]:
    """Combine expected-count sources, earlier arguments winning.

    Order is the caller's statement of which source it trusts; a later source
    only fills hours an earlier one does not mention.
    """

    merged: dict[str, int] = {}
    for source in sources:
        if not source:
            continue
        for hour_key, value in source.items():
            merged.setdefault(hour_key, value)
    if not merged:
        raise ExpectedCountsUnavailable(
            "no expected per-hour event counts were supplied; completeness "
            "cannot be decided from the archive alone"
        )
    return merged


def build_hour_reports(
    hours: Sequence[str],
    expected_counts: Mapping[str, int],
    observed: Mapping[str, Mapping[str, int]],
) -> tuple[dict[str, object], ...]:
    """One report row per expected hour, in chronological order."""

    reports: list[dict[str, object]] = []
    for hour_key in hours:
        validated = validate_stream_hour(hour_key)
        counts = observed.get(validated) or {}
        raw_row_count = int(counts.get("raw_row_count", 0) or 0)
        deduplicated = int(counts.get("deduplicated_event_count", 0) or 0)
        expected = expected_counts.get(validated)
        classification = classify_hour(expected, raw_row_count, deduplicated)
        reports.append(
            {
                "hour_key": validated,
                "hour_present": deduplicated > 0,
                "expected_event_count": expected,
                "raw_row_count": raw_row_count,
                "deduplicated_event_count": deduplicated,
                "duplicate_count": raw_row_count - deduplicated,
                "coverage_ratio": (
                    None if not expected else round(deduplicated / expected, 6)
                ),
                "classification": classification,
            }
        )
    return tuple(reports)


def summarize_reports(reports: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate the per-hour rows into the PASS/FAIL verdict.

    PASS needs every hour `COMPLETE` *and* the totals to agree.  The second is
    not implied by the first -- it is a cheap guard against a report built from
    a partial observation map -- and both are reported so a failure says which.
    """

    counts = dict.fromkeys(HOUR_CLASSIFICATIONS, 0)
    blocking: list[str] = []
    expected_total = 0
    deduplicated_total = 0
    raw_total = 0
    expected_known = True
    for report in reports:
        classification = str(report["classification"])
        counts[classification] = counts.get(classification, 0) + 1
        if classification in BLOCKING_CLASSIFICATIONS:
            blocking.append(str(report["hour_key"]))
        expected = report["expected_event_count"]
        if expected is None:
            expected_known = False
        else:
            expected_total += int(expected)
        deduplicated_total += int(report["deduplicated_event_count"])
        raw_total += int(report["raw_row_count"])
    totals_match = expected_known and expected_total == deduplicated_total
    passed = bool(reports) and not blocking and totals_match
    return {
        "expected_hour_count": len(reports),
        "classification_counts": counts,
        "blocking_hours": list(blocking[:MAX_REPORTED_HOURS]),
        "blocking_hour_count": len(blocking),
        "expected_event_total": expected_total if expected_known else None,
        "deduplicated_event_total": deduplicated_total,
        "raw_row_total": raw_total,
        "duplicate_row_total": raw_total - deduplicated_total,
        "shortfall_event_total": (
            expected_total - deduplicated_total if expected_known else None
        ),
        "totals_match": totals_match,
        "passed": passed,
    }


def build_verification(
    *,
    period_start: str,
    period_end: str,
    input_uri: str,
    expected_counts: Mapping[str, int],
    observed: Mapping[str, Mapping[str, int]],
) -> dict[str, object]:
    """The whole report for a period the caller has already validated."""

    hours = expected_stream_hours(period_start, period_end)
    reports = build_hour_reports(hours, expected_counts, observed)
    summary = summarize_reports(reports)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": STREAM_SOURCE,
        "dedup_keys": list(DEDUP_KEYS),
        "input": input_uri,
        "period_start": period_start,
        "period_end": period_end,
        "summary": summary,
        "hours": [dict(report) for report in reports],
        "result": "PASS" if summary["passed"] else "FAIL",
    }


def read_observed_counts(
    spark: Any, functions: Any, input_uri: str, hours: Sequence[str]
) -> dict[str, dict[str, int]]:
    """Count raw and deduplicated rows per hour, reading only what is needed.

    Only the identity columns are projected.  `payload` is the bulk of the
    archive and nothing here looks at it, so a columnar read keeps a seven-day
    scan small enough to run on one core beside the streaming archiver.
    """

    archive = spark.read.parquet(input_uri)
    missing_columns = sorted(set(STREAM_REQUIRED_COLUMNS) - set(archive.columns))
    if missing_columns:
        raise RuntimeError(
            f"input is not a C1 archive; missing columns: {missing_columns}"
        )

    scoped = archive.where(functions.col("source") == functions.lit(STREAM_SOURCE))
    if "dt" in archive.columns:
        # Partition pruning only.  Membership is decided by `hour_key` below,
        # the same way `repo_activity_weekly` prunes and then bounds exactly.
        dates = sorted({hour[:10] for hour in hours})
        scoped = scoped.where(functions.col("dt").isin(dates))

    base = scoped.select(
        functions.substring_index(functions.col("source_id"), "/", 1).alias("hour_key"),
        *(functions.col(name) for name in DEDUP_KEYS),
    ).where(functions.col("hour_key").isin(list(hours)))

    raw = base.groupBy("hour_key").agg(
        functions.count(functions.lit(1)).alias("raw_row_count")
    )
    deduplicated = (
        base.dropDuplicates(list(DEDUP_KEYS))
        .groupBy("hour_key")
        .agg(functions.count(functions.lit(1)).alias("deduplicated_event_count"))
    )
    rows = raw.join(deduplicated, "hour_key", "outer").collect()
    return {
        str(row["hour_key"]): {
            "raw_row_count": int(row["raw_row_count"] or 0),
            "deduplicated_event_count": int(row["deduplicated_event_count"] or 0),
        }
        for row in rows
    }


def load_json_document(path: Path) -> Mapping[str, object]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise TypeError(f"expected a JSON object: {path}")
    return document


def resolve_expected_counts(arguments: argparse.Namespace) -> dict[str, int]:
    """Assemble expected counts from the sources the caller named.

    `--expected-counts` wins over the publisher checkpoint because it is how an
    operator supplies the hours the checkpoint is missing -- the failed ones.
    """

    explicit = None
    if getattr(arguments, "expected_counts", None):
        explicit = normalize_expected_counts(
            load_json_document(arguments.expected_counts)
        )
    checkpoint = None
    if getattr(arguments, "publish_checkpoint", None):
        checkpoint = expected_counts_from_publish_checkpoint(
            load_json_document(arguments.publish_checkpoint)
        )
    return merge_expected_counts(explicit, checkpoint)


def run_job(arguments: argparse.Namespace) -> dict[str, object]:
    from pyspark.sql import SparkSession, functions

    validate_period(
        arguments.period_start,
        arguments.period_end,
        input_format=INPUT_FORMAT_STREAM_PARQUET,
    )
    expected_counts = resolve_expected_counts(arguments)
    hours = expected_stream_hours(arguments.period_start, arguments.period_end)

    spark = (
        SparkSession.builder.appName(arguments.app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    try:
        observed = read_observed_counts(spark, functions, arguments.input, hours)
    finally:
        spark.stop()

    return build_verification(
        period_start=arguments.period_start,
        period_end=arguments.period_end,
        input_uri=arguments.input,
        expected_counts=expected_counts,
        observed=observed,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that every UTC hour of a Weekly period is completely "
            "present in the C1 stream archive.  Reads only; writes no HDFS."
        )
    )
    parser.add_argument(
        "--input",
        default="hdfs:///gitjob/parquet/stream/github.events",
        help="C1 stream archive root",
    )
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    parser.add_argument(
        "--publish-checkpoint",
        type=Path,
        help=(
            "GH Archive publisher checkpoint; canonical per-hour source counts "
            "for the hours it finished"
        ),
    )
    parser.add_argument(
        "--expected-counts",
        type=Path,
        help=(
            "{hour_key: event_count} JSON; takes precedence, and is how the "
            "hours absent from the checkpoint are supplied"
        ),
    )
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--app-name", default="gitjob-weekly-stream-verify")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    report = run_job(arguments)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if arguments.report_output:
        Path(arguments.report_output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    # Non-zero on FAIL so a runbook step cannot continue past it by accident.
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
