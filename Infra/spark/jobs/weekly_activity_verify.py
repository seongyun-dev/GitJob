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
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from jobs.repo_activity_weekly import (
    ACTIVITY_COLUMNS,
    DEDUP_KEYS,
    INPUT_FORMAT_STREAM_PARQUET,
    STREAM_REQUIRED_COLUMNS,
    STREAM_SOURCE,
    aggregate_weekly_rows,
    expected_stream_hours,
    normalize_stream_rows,
    validate_period,
    validate_stream_hour,
)
from jobs.weekly_lineage_verify import (
    summarize_sections,
    verify_c_export_lineage,
    verify_success_manifest,
    verify_trend_lineage,
)

SCHEMA_VERSION = "weekly-stream-completeness-report/v1"
REPORT_SCHEMA_VERSION = "weekly-7day-e2e-report/v1"

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


def recompute_weekly_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Goals 4 and 5: valid repo events, then `(repo_id, week_start)` counts.

    Both rules are `repo_activity_weekly`'s own -- `normalize_stream_rows`
    filters the source and dedups, `aggregate_weekly_rows` drops rows without a
    usable `repo_id`, `repo_name` or `created_at` and applies the renamed
    repository rule.  They are imported, not restated.

    "Independent" in the ticket means independent of the *Spark output*, not of
    the contract: a recomputation that invented its own idea of a valid event
    would report differences that are only disagreements about the rules.
    """

    return aggregate_weekly_rows(normalize_stream_rows(rows))


def valid_repo_event_condition(functions: Any) -> Any:
    """Goal 4 as a Spark predicate, matching `aggregate_weekly_rows`'s filter.

    That function drops an event without a positive integer `repo_id`, without
    a non-blank `repo_name`, or without a parseable `created_at`.  The three
    conditions are spelled out here rather than reused because they run on the
    executors.  `test_invalid_repo_events_are_dropped` pins the same three
    cases against `recompute_weekly_rows`, which goes through the production
    helpers, so a drift in either direction shows up as a test failure.
    """

    repo_id = functions.get_json_object(functions.col("payload"), "$.repo.id").cast(
        "long"
    )
    repo_name = functions.get_json_object(functions.col("payload"), "$.repo.name")
    occurred = functions.to_timestamp(functions.col("occurred_at"))
    return (
        repo_id.isNotNull()
        & (repo_id > functions.lit(0))
        & repo_name.isNotNull()
        & (functions.length(functions.trim(repo_name)) > functions.lit(0))
        & occurred.isNotNull()
    )


def read_weekly_reconciliation(
    spark: Any,
    functions: Any,
    *,
    stream_uri: str,
    weekly_uri: str,
    hours: Sequence[str],
) -> dict[str, object]:
    """Goals 4-6 in Spark, collecting only the disagreements.

    A week's output is one row per repository and can be millions of them, so
    the join happens on the cluster and the driver receives the mismatching
    rows and the totals -- never the week.  This is the same reason
    `repo_activity_weekly.slice_row_digest` sorts in Spark and streams.
    """

    archive = spark.read.parquet(stream_uri)
    scoped = archive.where(functions.col("source") == functions.lit(STREAM_SOURCE))
    if "dt" in archive.columns:
        dates = sorted({hour[:10] for hour in hours})
        scoped = scoped.where(functions.col("dt").isin(dates))
    hour_key = functions.substring_index(functions.col("source_id"), "/", 1)
    scoped = scoped.where(hour_key.isin(list(hours)))

    deduplicated = scoped.dropDuplicates(list(DEDUP_KEYS))
    valid = deduplicated.where(valid_repo_event_condition(functions))
    expected = (
        valid.select(
            functions.get_json_object(functions.col("payload"), "$.repo.id")
            .cast("long")
            .alias("repo_id"),
            functions.date_format(
                functions.date_trunc(
                    "week", functions.to_timestamp(functions.col("occurred_at"))
                ),
                "yyyy-MM-dd",
            ).alias("week_start"),
        )
        .groupBy("repo_id", "week_start")
        .agg(functions.count(functions.lit(1)).alias("expected_event_count"))
    )

    output = spark.read.parquet(weekly_uri)
    missing_columns = sorted(set(ACTIVITY_COLUMNS) - set(output.columns))
    if missing_columns:
        raise RuntimeError(f"weekly output is missing columns: {missing_columns}")
    observed = output.select(
        functions.col("repo_id").cast("long").alias("repo_id"),
        functions.col("week_start").alias("week_start"),
        functions.col("event_count").cast("long").alias("observed_event_count"),
    )

    joined = expected.join(observed, ["repo_id", "week_start"], "full_outer")
    disagreeing = joined.where(
        functions.col("expected_event_count").isNull()
        | functions.col("observed_event_count").isNull()
        | (
            functions.col("expected_event_count")
            != functions.col("observed_event_count")
        )
    )
    mismatches = [
        {
            "repo_id": row["repo_id"],
            "week_start": row["week_start"],
            "expected": row["expected_event_count"],
            "observed": row["observed_event_count"],
        }
        for row in disagreeing.limit(MAX_REPORTED_HOURS).collect()
    ]
    totals = joined.agg(
        functions.count(functions.lit(1)).alias("joined_row_count"),
        functions.sum(
            functions.coalesce(functions.col("expected_event_count"), functions.lit(0))
        ).alias("expected_event_total"),
        functions.sum(
            functions.coalesce(functions.col("observed_event_count"), functions.lit(0))
        ).alias("observed_event_total"),
    ).first()
    mismatch_count = disagreeing.count()

    errors: list[str] = []
    if mismatch_count:
        errors.append(
            f"{mismatch_count} (repo_id, week_start) rows disagree between the "
            "recomputed aggregate and the weekly output"
        )
    expected_total = int(totals["expected_event_total"] or 0)
    observed_total = int(totals["observed_event_total"] or 0)
    if expected_total != observed_total:
        errors.append(
            f"event totals disagree: recomputed {expected_total}, "
            f"weekly output {observed_total}"
        )
    return {
        "section": "weekly_output_reconciliation",
        "checked": True,
        "pass": not errors,
        "errors": errors,
        "joined_row_count": int(totals["joined_row_count"] or 0),
        "mismatch_count": mismatch_count,
        "expected_event_total": expected_total,
        "observed_event_total": observed_total,
        "mismatches": mismatches,
    }


def build_full_report(
    *,
    input_completeness: Mapping[str, object],
    weekly_reconciliation: Mapping[str, object] | None = None,
    success_manifest: Mapping[str, object] | None = None,
    c_export_lineage: Mapping[str, object] | None = None,
    trend_lineage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Compose the ten goals into one PASS/FAIL document.

    `input_completeness` is `build_verification`'s report, wrapped as a section
    so every goal reads the same way.  A section left out is recorded as
    unchecked and fails the whole report, because a chain verified only as far
    as someone remembered to supply evidence is not a verified chain.
    """

    completeness_section = {
        "section": "input_completeness",
        "checked": True,
        "pass": bool(input_completeness["summary"]["passed"]),
        "errors": (
            []
            if input_completeness["summary"]["passed"]
            else ["stream input is not complete for this period"]
        ),
        "report": dict(input_completeness),
    }
    named = (
        ("weekly_output_reconciliation", weekly_reconciliation),
        ("success_manifest", success_manifest),
        ("c_export_lineage", c_export_lineage),
        ("trend_lineage", trend_lineage),
    )
    sections: list[dict[str, object]] = [completeness_section]
    for name, section in named:
        if section is None:
            sections.append(
                {
                    "section": name,
                    "checked": False,
                    "pass": False,
                    "errors": ["no evidence was supplied for this section"],
                }
            )
        else:
            sections.append(dict(section))

    summary = summarize_sections(sections)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "period_start": input_completeness["period_start"],
        "period_end": input_completeness["period_end"],
        "summary": summary,
        "sections": sections,
        "result": "PASS" if summary["passed"] else "FAIL",
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
    weekly_reconciliation = None
    try:
        observed = read_observed_counts(spark, functions, arguments.input, hours)
        if getattr(arguments, "weekly_output", None):
            weekly_reconciliation = read_weekly_reconciliation(
                spark,
                functions,
                stream_uri=arguments.input,
                weekly_uri=arguments.weekly_output,
                hours=hours,
            )
    finally:
        spark.stop()

    completeness = build_verification(
        period_start=arguments.period_start,
        period_end=arguments.period_end,
        input_uri=arguments.input,
        expected_counts=expected_counts,
        observed=observed,
    )
    sections = lineage_sections(arguments)
    if weekly_reconciliation is not None:
        sections["weekly_reconciliation"] = weekly_reconciliation
    return build_full_report(input_completeness=completeness, **sections)


def lineage_sections(arguments: argparse.Namespace) -> dict[str, object]:
    """Goals 6-9 from whatever artifacts the caller pointed at.

    Each is optional at the command line and absent evidence leaves its section
    unchecked, which fails the report.  That is deliberate: production runs
    supply all four, and a run that cannot is telling the operator something.
    """

    weekly_manifest = None
    if getattr(arguments, "weekly_manifest", None):
        weekly_manifest = load_json_document(arguments.weekly_manifest)

    sections: dict[str, object] = {
        "weekly_reconciliation": None,
        "success_manifest": None,
        "c_export_lineage": None,
        "trend_lineage": None,
    }

    if weekly_manifest is not None:
        sections["success_manifest"] = verify_success_manifest(
            weekly_manifest,
            observed_row_count=getattr(arguments, "observed_row_count", None),
            observed_row_digest=getattr(arguments, "observed_row_digest", None),
        )

    if weekly_manifest is not None and getattr(arguments, "export_manifest", None):
        export_manifest = load_json_document(arguments.export_manifest)
        export_metadata = (
            load_json_document(arguments.export_metadata)
            if getattr(arguments, "export_metadata", None)
            else None
        )
        data_bytes = (
            Path(arguments.export_data).read_bytes()
            if getattr(arguments, "export_data", None)
            else None
        )
        metadata_bytes = (
            Path(arguments.export_metadata).read_bytes()
            if getattr(arguments, "export_metadata", None)
            else None
        )
        sections["c_export_lineage"] = verify_c_export_lineage(
            weekly_manifest=weekly_manifest,
            export_manifest=export_manifest,
            export_metadata=export_metadata,
            data_bytes=data_bytes,
            metadata_bytes=metadata_bytes,
        )
        if getattr(arguments, "trend_records", None):
            trend_document = load_json_document(arguments.trend_records)
            records = trend_document.get("records")
            sections["trend_lineage"] = verify_trend_lineage(
                weekly_manifest=weekly_manifest,
                export_metadata=export_metadata,
                trend_records=records if isinstance(records, list) else None,
                public_snapshot_id=trend_document.get("public_snapshot_id"),
                registry_version=trend_document.get("registry_version"),
            )
    return sections


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

    lineage = parser.add_argument_group(
        "lineage evidence",
        "Goals 6-9.  Each omitted artifact leaves its section unchecked, which "
        "fails the report -- absent evidence is never a PASS.",
    )
    lineage.add_argument(
        "--weekly-output",
        help=(
            "the week directory the aggregation wrote; enables the goal 4-6 "
            "recomputation and comparison"
        ),
    )
    lineage.add_argument(
        "--weekly-manifest", type=Path, help="the week's _SUCCESS.json"
    )
    lineage.add_argument(
        "--observed-row-count",
        type=int,
        help="rows actually in the week directory, for the manifest check",
    )
    lineage.add_argument(
        "--observed-row-digest",
        help="slice_row_digest over the week directory, for the manifest check",
    )
    lineage.add_argument("--export-manifest", type=Path, help="C export manifest.json")
    lineage.add_argument("--export-metadata", type=Path, help="C export metadata.json")
    lineage.add_argument(
        "--export-data", type=Path, help="C export activity.csv or activity.ndjson"
    )
    lineage.add_argument(
        "--trend-records",
        type=Path,
        help=(
            "JSON with public_snapshot_id, registry_version and a records array "
            "of stored TREND rows"
        ),
    )
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
