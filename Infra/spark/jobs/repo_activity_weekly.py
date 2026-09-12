"""Weekly GH Archive repo activity for the C Trend JOIN (S15P21E102-166).

`repo_activity_topn.py` (-109) collapses a whole period into one row per
repository.  That is the right shape for Top-N selection and the wrong shape
for a trend: it cannot say *when* inside the period a repository was active.
This job keeps the same Raw reading — four fields, one input row is one event,
no repository contents inspected — and adds the time axis the C side joins on.

### The output shape is fixed by the consumer, not chosen here

`jobs/export_c_archive_activity.py` (-203) is the only consumer, and
`AI/trend/archive.py` is what it feeds.  Together they pin four things:

* the columns are `repo_id`, `repo_name`, `event_count` and — for `WEEK` —
  `week_start`.  `event_count` is preferred over -109's `activity_count`
  (`export_c_archive_activity._activity_quality`).
* `week_start` is an ISO date string that must be a **Monday**
  (`archive._period_index`, `WEEK period must start on Monday`).
* one source read must contain **exactly one** distinct `week_start`
  (`export_c_archive_activity._validate_activity_period`).
* within that read there is **one row per `repo_id`**, no nulls, no negative
  counts, no blank names (`_activity_quality`).

The third point is why the weekly data is written as one directory per week
rather than a single dataset: pointing the exporter at the whole output would
fail its period binding.  The fourth is why `week_start` stays a **data**
column.  `partitionBy("week_start")` would satisfy the layout and then delete
the column from the files, so reading one partition directory directly — which
is exactly what the exporter does — would lose the binding it validates.  The
directory is therefore named `week=` and the column is written alongside it.

### What this job does not infer

The ticket also asks for "안정적으로 산출 가능한 이벤트별 count, unique actor 집계".
The event type is in the Raw schema -109 already declares, so per-type counts
are a real aggregate and are written to `weekly_event_type`.  A unique-actor
count is not: no file in this repository — collector, Spark job, contract or
document — names an `actor` field, so its presence, shape and nullability in
the Raw layer are unverified here.  Adding a speculative `actor.id` to the read
schema would silently produce nulls if the guess were wrong, so it is left out
and recorded as the one open item in `docs/data/2026-09-12-repo-activity-weekly.md`.

### Partial weeks are reported, not dropped

A calendar month never starts or ends on a Monday, so the first and last week
of any period are partial.  `week_start` means "the week in which these events
happened", so dropping those weeks would throw away real events and keeping
them silently would let a reader compare a 3-day week against a 7-day one.
Both edge weeks are written, and `weeks` carries `fully_within_period` so the
comparison is a choice the consumer makes with the flag in front of them.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

HISTORICAL_START = "2026-08-01T00:00:00Z"
HISTORICAL_CUTOFF = "2026-09-01T00:00:00Z"
# Same validated Historical Raw window as -109/-193; the August MVP stays the
# default period so a bare invocation reproduces the recorded run.
SUPPORTED_HISTORICAL_START = "2026-03-01T00:00:00Z"
SUPPORTED_HISTORICAL_CUTOFF = "2026-09-01T00:00:00Z"
DEFAULT_INPUT = "hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz"

# Mirrors `jobs/export_c_archive_activity.MAX_ID_FILE_BYTES`: the JOIN cohort
# files are the same bounded envelopes that exporter reads.
MAX_ID_FILE_BYTES = 8 * 1024 * 1024
DEFAULT_JOIN_MAX_ROWS = 200_000

ACTIVITY_COLUMNS = ("repo_id", "repo_name", "event_count", "week_start")


def parse_utc_hour(value: str) -> datetime:
    """Parse an aware, hour-aligned UTC timestamp."""

    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 hour: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    parsed = parsed.astimezone(UTC)
    if any((parsed.minute, parsed.second, parsed.microsecond)):
        raise ValueError(f"timestamp must be aligned to an hour: {value}")
    return parsed


def validate_period(period_start: str, period_end: str) -> None:
    """Validate the explicit UTC period and its exclusive end boundary."""

    start = parse_utc_hour(period_start)
    end = parse_utc_hour(period_end)
    historical_start = parse_utc_hour(SUPPORTED_HISTORICAL_START)
    historical_cutoff = parse_utc_hour(SUPPORTED_HISTORICAL_CUTOFF)
    if start < historical_start:
        raise ValueError("period_start precedes historical_start")
    if end > historical_cutoff:
        raise ValueError("period_end exceeds exclusive historical_cutoff")
    if start >= end:
        raise ValueError("period_start must be before period_end")


def parse_event_timestamp(value: object) -> datetime:
    """Parse a GH Archive ``created_at`` into an aware UTC timestamp.

    GH Archive writes RFC-3339 `Z` timestamps.  A value that carries another
    offset is accepted and converted, because the week a UTC instant falls in
    is a property of the instant; a naive value is rejected, because guessing
    its zone would move events across a week boundary without saying so.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError("created_at must be a non-blank string")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    return parsed.astimezone(UTC)


def week_start_of(value: object) -> str:
    """Return the Monday, in UTC, of the week containing ``value``.

    ``value`` is a ``created_at`` string or an aware ``datetime``.  The result
    is the `YYYY-MM-DD` form `AI/trend/archive.py` requires.  Spark computes
    the same boundary with ``date_trunc('week', ...)`` under a UTC session
    timezone; this helper exists so the boundary is executable without Spark.
    """

    moment = value if isinstance(value, datetime) else parse_event_timestamp(value)
    if moment.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    day = moment.astimezone(UTC).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def validate_week_start(value: str) -> date:
    """Apply the consumer's `WEEK` period rules to one ``week_start``."""

    if not isinstance(value, str):
        raise TypeError("week_start must be a string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"week_start must be an ISO date: {value}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"week_start must be a canonical ISO date: {value}")
    if parsed.year < 2020:
        raise ValueError("week_start year must be >= 2020")
    if parsed.weekday() != 0:
        raise ValueError(f"week_start must be a Monday: {value}")
    return parsed


def expected_week_starts(period_start: str, period_end: str) -> tuple[str, ...]:
    """Every week a `[period_start, period_end)` event can land in."""

    start = parse_utc_hour(period_start)
    end = parse_utc_hour(period_end)
    if start >= end:
        raise ValueError("period_start must be before period_end")
    first = date.fromisoformat(week_start_of(start))
    # The exclusive end belongs to the previous instant's week.
    last = date.fromisoformat(week_start_of(end - timedelta(microseconds=1)))
    weeks: list[str] = []
    cursor = first
    while cursor <= last:
        weeks.append(cursor.isoformat())
        cursor += timedelta(days=7)
    return tuple(weeks)


def week_is_fully_within_period(
    week_start: str, period_start: str, period_end: str
) -> bool:
    """True when the whole Monday-to-Monday span lies inside the period."""

    monday = validate_week_start(week_start)
    start = parse_utc_hour(period_start)
    end = parse_utc_hour(period_end)
    week_begin = datetime.combine(monday, datetime.min.time(), tzinfo=UTC)
    return week_begin >= start and week_begin + timedelta(days=7) <= end


def aggregate_weekly_rows(
    events: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Aggregate raw events into the weekly rows the Spark job writes.

    The Spark job performs the same aggregation with ``groupBy`` over
    ``(repo_id, week_start)``.  This helper exists to make the grouping key,
    the renamed-repository rule and the invalid-row rule executable in unit
    tests; production Raw never comes through the Python driver.

    Events missing ``repo_id``, ``repo_name`` or a usable ``created_at`` are
    dropped, matching the Spark filter, and counted by the caller through the
    returned row totals.  A repository renamed mid-week keeps the name from its
    latest event in that week, which is -109's rule applied per week.
    """

    buckets: dict[tuple[int, str], dict[str, object]] = {}
    for event in events:
        repo_id = event.get("repo_id")
        repo_name = event.get("repo_name")
        created_at = event.get("created_at")
        if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
            continue
        if not isinstance(repo_name, str) or not repo_name.strip():
            continue
        try:
            moment = parse_event_timestamp(created_at)
        except ValueError:
            continue
        key = (repo_id, week_start_of(moment))
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = {
                "repo_id": repo_id,
                "repo_name": repo_name,
                "event_count": 1,
                "week_start": key[1],
                "_latest": moment,
                "_names": {repo_name},
            }
            continue
        bucket["event_count"] = int(bucket["event_count"]) + 1
        names = bucket["_names"]
        if isinstance(names, set):
            names.add(repo_name)
        latest = bucket["_latest"]
        if isinstance(latest, datetime) and (
            moment > latest
            or (moment == latest and repo_name > str(bucket["repo_name"]))
        ):
            bucket["_latest"] = moment
            bucket["repo_name"] = repo_name

    rows = [
        {
            "repo_id": bucket["repo_id"],
            "repo_name": bucket["repo_name"],
            "event_count": bucket["event_count"],
            "week_start": bucket["week_start"],
            "name_count": len(bucket["_names"])
            if isinstance(bucket["_names"], set)
            else 1,
        }
        for bucket in buckets.values()
    ]
    rows.sort(key=lambda row: (str(row["week_start"]), int(row["repo_id"])))
    return rows


def activity_rows_for_week(
    rows: Sequence[Mapping[str, object]], week_start: str
) -> list[dict[str, object]]:
    """The exact column set one week directory holds, for one week."""

    validate_week_start(week_start)
    return [
        {column: row[column] for column in ACTIVITY_COLUMNS}
        for row in rows
        if row["week_start"] == week_start
    ]


def assert_week_slice_is_consumable(rows: Sequence[Mapping[str, object]]) -> None:
    """Re-apply the consumer's acceptance rules to one week's rows.

    `export_c_archive_activity._activity_quality` and
    `trend.archive._normalize_activity_row` reject the same things.  Checking
    them here means a violation stops this job instead of surfacing days later
    as an export failure with no producer to blame.
    """

    if not rows:
        raise ValueError("week slice must not be empty")
    weeks = {row["week_start"] for row in rows}
    if len(weeks) != 1:
        raise ValueError(
            f"week slice must hold exactly one week_start: {sorted(weeks)}"
        )
    validate_week_start(str(next(iter(weeks))))
    seen: set[int] = set()
    for row in rows:
        repo_id = row["repo_id"]
        repo_name = row["repo_name"]
        event_count = row["event_count"]
        if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
            raise ValueError("repo_id must be a strict positive integer")
        if repo_id in seen:
            raise ValueError(f"duplicate repo_id within one week: {repo_id}")
        seen.add(repo_id)
        if not isinstance(repo_name, str) or not repo_name.strip():
            raise ValueError("repo_name must be a non-blank string")
        if (
            isinstance(event_count, bool)
            or not isinstance(event_count, int)
            or event_count < 0
        ):
            raise ValueError("event_count must be a nonnegative integer")


def parse_join_ids_argument(value: str) -> tuple[str, Path]:
    """Parse one ``LABEL=PATH`` JOIN cohort argument.

    Cohorts are named by the caller rather than hardcoded here.  "Top20k" and
    "COMPLETE" are the two the ticket asks about, but nothing about this job
    depends on those being the cohorts that exist.
    """

    label, separator, path = value.partition("=")
    label = label.strip()
    if not separator or not label or not path.strip():
        raise ValueError("join cohort must be given as LABEL=PATH")
    if any(character.isspace() for character in label):
        raise ValueError("join cohort label must not contain whitespace")
    return label, Path(path.strip())


def load_repo_ids(path: Path, *, max_rows: int) -> tuple[int, ...]:
    """Load a bounded, approved repository ID envelope.

    The accepted envelopes are the ones `jobs/export_c_archive_activity.py`
    already accepts, so a cohort file is usable by both without conversion.
    """

    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    with path.open("rb") as stream:
        content = stream.read(MAX_ID_FILE_BYTES + 1)
    if len(content) > MAX_ID_FILE_BYTES:
        raise ValueError("repository ID input exceeds the bounded file limit")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("repository ID input must be UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise TypeError("repository ID input must be an object")

    schema = payload.get("schema_version")
    if schema == "repo-fetch-candidates/v1":
        rows = payload.get("candidates")
        field = "repo_id"
    elif schema in {"github-repo-snapshot/v1", "c-public-repo-analysis/v1"}:
        rows = payload.get("records")
        field = "github_repo_id"
    else:
        raise ValueError("unsupported repository ID source schema_version")
    if not isinstance(rows, list):
        raise TypeError("repository ID source rows must be an array")
    if len(rows) > max_rows:
        raise ValueError("repository ID source exceeds max_rows")

    repo_ids: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("repository ID row must be an object")
        repo_id = row.get(field)
        if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
            raise ValueError("repo_id must be a strict positive integer")
        repo_ids.append(repo_id)
    if not repo_ids:
        raise ValueError("repository ID source must not be empty")
    if len(repo_ids) != len(set(repo_ids)):
        raise ValueError("duplicate repo_id in repository ID source")
    return tuple(sorted(repo_ids))


def join_coverage_row(
    label: str,
    repo_ids: Sequence[int],
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Coverage of one cohort against the weekly rows.

    ``matched_repo_count`` answers the ticket's JOIN question — how many of the
    cohort's repositories appear anywhere in the weekly data — while
    ``active_week_count`` and ``matched_event_count`` say how much of the time
    axis they actually occupy.  A repository absent from every week is not an
    error: it had no GH Archive event in the period.
    """

    cohort = set(repo_ids)
    if not cohort:
        raise ValueError("join cohort must not be empty")
    matched_rows = [row for row in rows if int(row["repo_id"]) in cohort]
    matched_repos = {int(row["repo_id"]) for row in matched_rows}
    matched_events = sum(int(row["event_count"]) for row in matched_rows)
    return {
        "label": label,
        "cohort_repo_count": len(cohort),
        "matched_repo_count": len(matched_repos),
        "missing_repo_count": len(cohort) - len(matched_repos),
        "coverage_ratio": len(matched_repos) / len(cohort),
        "active_week_count": len({str(row["week_start"]) for row in matched_rows}),
        "matched_row_count": len(matched_rows),
        "matched_event_count": matched_events,
    }


def build_event_schema() -> Any:
    """The four Raw fields this aggregation reads, and nothing else.

    Identical to -109's schema.  `_corrupt_record` measures malformed JSON and
    is never part of a grouping key.
    """

    from pyspark.sql.types import LongType, StringType, StructField, StructType

    return StructType(
        [
            StructField(
                "repo",
                StructType(
                    [
                        StructField("id", LongType(), True),
                        StructField("name", StringType(), True),
                    ]
                ),
                True,
            ),
            StructField("type", StringType(), True),
            StructField("created_at", StringType(), True),
            StructField("_corrupt_record", StringType(), True),
        ]
    )


def _hadoop_path_exists(spark: Any, uri: str) -> bool:
    path = spark._jvm.org.apache.hadoop.fs.Path(uri)
    filesystem = path.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    return bool(filesystem.exists(path))


def _hadoop_path_stats(spark: Any, uri: str) -> tuple[int, int]:
    """Return (file_count, byte_count) recursively for an HDFS path."""

    path = spark._jvm.org.apache.hadoop.fs.Path(uri)
    filesystem = path.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    if not filesystem.exists(path):
        return 0, 0

    files = 0
    bytes_total = 0
    iterator = filesystem.listFiles(path, True)
    while iterator.hasNext():
        status = iterator.next()
        if status.getPath().getName().endswith(".parquet"):
            files += 1
            bytes_total += int(status.getLen())
    return files, bytes_total


def _executor_count(spark: Any) -> int | None:
    try:
        statuses = spark.sparkContext._jsc.sc().getExecutorMemoryStatus()
        # The driver is included in the map; report workers only.
        return max(0, int(statuses.size()) - 1)
    except Exception:  # noqa: BLE001 - JVM API differs between Spark releases
        return None


def _as_int(value: object) -> int:
    return int(value or 0)


def run_job(arguments: argparse.Namespace) -> dict[str, object]:
    """Execute the distributed weekly aggregation and write immutable Parquet."""

    from pyspark import StorageLevel
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        BooleanType,
        DoubleType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    validate_period(arguments.period_start, arguments.period_end)
    cohorts = {
        label: load_repo_ids(path, max_rows=arguments.join_max_rows)
        for label, path in arguments.join_cohorts
    }
    expected_weeks = expected_week_starts(arguments.period_start, arguments.period_end)

    started = time.perf_counter()
    spark = (
        SparkSession.builder.appName(arguments.app_name)
        # Every week boundary in this job is a UTC boundary.  Without this the
        # JVM default zone would decide which week an event belongs to.
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    weekly = None
    try:
        if _hadoop_path_exists(spark, arguments.output):
            raise FileExistsError(
                f"output already exists; refusing to overwrite: {arguments.output}"
            )

        raw = spark.read.schema(build_event_schema()).json(arguments.input)
        input_files = tuple(raw.inputFiles())
        if len(input_files) != arguments.expected_files:
            raise RuntimeError(
                "input file count mismatch: "
                f"expected {arguments.expected_files}, got {len(input_files)}"
            )

        typed = raw.select(
            F.col("repo.id").cast("long").alias("repo_id"),
            F.col("repo.name").alias("repo_name"),
            F.col("type").alias("event_type"),
            F.to_timestamp(F.col("created_at")).alias("created_at_ts"),
            F.col("_corrupt_record"),
        )
        quality_row = (
            typed.agg(
                F.count(F.lit(1)).alias("total_input_events"),
                F.sum(F.when(F.col("repo_id").isNull(), 1).otherwise(0)).alias(
                    "repo_id_null_count"
                ),
                F.sum(F.when(F.col("repo_name").isNull(), 1).otherwise(0)).alias(
                    "repo_name_null_count"
                ),
                F.sum(F.when(F.col("created_at_ts").isNull(), 1).otherwise(0)).alias(
                    "created_at_null_count"
                ),
                F.sum(
                    F.when(
                        F.col("repo_id").isNull()
                        | F.col("repo_name").isNull()
                        | F.col("created_at_ts").isNull(),
                        1,
                    ).otherwise(0)
                ).alias("invalid_event_count"),
                F.sum(
                    F.when(F.col("_corrupt_record").isNotNull(), 1).otherwise(0)
                ).alias("malformed_json_count"),
            )
            .first()
            .asDict()
        )
        total_input_events = _as_int(quality_row["total_input_events"])
        invalid_event_count = _as_int(quality_row["invalid_event_count"])

        valid = typed.where(
            F.col("repo_id").isNotNull()
            & F.col("repo_name").isNotNull()
            & F.col("created_at_ts").isNotNull()
        ).withColumn(
            # date_trunc('week') is Monday-based, and the session timezone
            # above makes that Monday a UTC Monday.
            "week_start",
            F.date_format(F.date_trunc("week", F.col("created_at_ts")), "yyyy-MM-dd"),
        )

        grouped = valid.groupBy("repo_id", "week_start").agg(
            F.count(F.lit(1)).cast("long").alias("event_count"),
            F.countDistinct("repo_name").cast("long").alias("name_count"),
            F.max(F.struct(F.col("created_at_ts"), F.col("repo_name"))).alias("latest"),
        )
        weekly = grouped.select(
            F.col("repo_id"),
            F.col("latest.repo_name").alias("repo_name"),
            F.col("event_count"),
            F.col("week_start"),
            F.col("name_count"),
        ).persist(StorageLevel.DISK_ONLY)

        weekly_stats = (
            weekly.agg(
                F.count(F.lit(1)).alias("row_count"),
                F.countDistinct("repo_id").alias("unique_repo_id_count"),
                F.sum(F.col("event_count")).alias("valid_repo_event_count"),
                F.sum(F.when(F.col("name_count") > 1, 1).otherwise(0)).alias(
                    "repo_name_collision_count"
                ),
            )
            .first()
            .asDict()
        )
        row_count = _as_int(weekly_stats["row_count"])
        unique_repo_id_count = _as_int(weekly_stats["unique_repo_id_count"])
        valid_repo_event_count = _as_int(weekly_stats["valid_repo_event_count"])
        repo_name_collision_count = _as_int(weekly_stats["repo_name_collision_count"])

        observed_weeks = sorted(
            str(row["week_start"])
            for row in weekly.select("week_start").distinct().collect()
        )
        for week in observed_weeks:
            validate_week_start(week)
        unexpected = sorted(set(observed_weeks) - set(expected_weeks))
        if unexpected:
            raise RuntimeError(
                f"events fall outside the declared period's weeks: {unexpected}"
            )

        week_row_map = {
            str(row["week_start"]): row.asDict()
            for row in weekly.groupBy("week_start")
            .agg(
                F.count(F.lit(1)).cast("long").alias("row_count"),
                F.countDistinct("repo_id").cast("long").alias("repo_count"),
                F.sum(F.col("event_count")).cast("long").alias("event_count"),
            )
            .collect()
        }
        for week, summary_row in week_row_map.items():
            if int(summary_row["row_count"]) != int(summary_row["repo_count"]):
                raise RuntimeError(
                    f"week {week} holds more than one row per repo_id: "
                    f"{summary_row['row_count']} rows / {summary_row['repo_count']} repos"
                )

        output_root = arguments.output.rstrip("/")
        activity_root = f"{output_root}/repo_activity_weekly"
        week_type_output = f"{output_root}/weekly_event_type"
        weeks_output = f"{output_root}/weeks"
        coverage_output = f"{output_root}/join_coverage"
        quality_output = f"{output_root}/data_quality"

        # One directory per week, `week_start` retained as a data column: the
        # exporter validates that column after reading a single week.
        activity = weekly.select(*ACTIVITY_COLUMNS)
        week_outputs: dict[str, str] = {}
        for week in observed_weeks:
            week_output = f"{activity_root}/week={week}"
            activity.where(F.col("week_start") == F.lit(week)).write.mode(
                "errorifexists"
            ).parquet(week_output)
            week_outputs[week] = week_output

        week_type_schema_rows = (
            valid.groupBy("week_start", "event_type")
            .agg(
                F.count(F.lit(1)).cast("long").alias("event_count"),
                F.countDistinct("repo_id").cast("long").alias("repo_count"),
            )
            .select("week_start", "event_type", "event_count", "repo_count")
        )
        week_type_schema_rows.write.mode("errorifexists").parquet(week_type_output)

        weeks_schema = StructType(
            [
                StructField("week_start", StringType(), False),
                StructField("week_end", StringType(), False),
                StructField("row_count", LongType(), False),
                StructField("repo_count", LongType(), False),
                StructField("event_count", LongType(), False),
                StructField("fully_within_period", BooleanType(), False),
                StructField("period_start", StringType(), False),
                StructField("period_end", StringType(), False),
            ]
        )
        weeks_rows = [
            (
                week,
                (date.fromisoformat(week) + timedelta(days=7)).isoformat(),
                _as_int(week_row_map[week]["row_count"]),
                _as_int(week_row_map[week]["repo_count"]),
                _as_int(week_row_map[week]["event_count"]),
                week_is_fully_within_period(
                    week, arguments.period_start, arguments.period_end
                ),
                arguments.period_start,
                arguments.period_end,
            )
            for week in observed_weeks
        ]
        spark.createDataFrame(weeks_rows, schema=weeks_schema).write.mode(
            "errorifexists"
        ).parquet(weeks_output)

        coverage_summary: list[dict[str, object]] = []
        if cohorts:
            coverage_schema = StructType(
                [
                    StructField("label", StringType(), False),
                    StructField("cohort_repo_count", LongType(), False),
                    StructField("matched_repo_count", LongType(), False),
                    StructField("missing_repo_count", LongType(), False),
                    StructField("coverage_ratio", DoubleType(), False),
                    StructField("active_week_count", LongType(), False),
                    StructField("matched_row_count", LongType(), False),
                    StructField("matched_event_count", LongType(), False),
                    StructField("period_start", StringType(), False),
                    StructField("period_end", StringType(), False),
                ]
            )
            for label, repo_ids in cohorts.items():
                cohort_df = F.broadcast(
                    spark.createDataFrame(
                        [(repo_id,) for repo_id in repo_ids],
                        schema=StructType([StructField("repo_id", LongType(), False)]),
                    )
                )
                matched = weekly.join(cohort_df, on="repo_id", how="inner")
                matched_row = (
                    matched.agg(
                        F.count(F.lit(1)).alias("matched_row_count"),
                        F.countDistinct("repo_id").alias("matched_repo_count"),
                        F.sum(F.col("event_count")).alias("matched_event_count"),
                        F.countDistinct("week_start").alias("active_week_count"),
                    )
                    .first()
                    .asDict()
                )
                matched_repo_count = _as_int(matched_row["matched_repo_count"])
                coverage_summary.append(
                    {
                        "label": label,
                        "cohort_repo_count": len(repo_ids),
                        "matched_repo_count": matched_repo_count,
                        "missing_repo_count": len(repo_ids) - matched_repo_count,
                        "coverage_ratio": matched_repo_count / len(repo_ids),
                        "active_week_count": _as_int(matched_row["active_week_count"]),
                        "matched_row_count": _as_int(matched_row["matched_row_count"]),
                        "matched_event_count": _as_int(
                            matched_row["matched_event_count"]
                        ),
                    }
                )
            spark.createDataFrame(
                [
                    (
                        row["label"],
                        row["cohort_repo_count"],
                        row["matched_repo_count"],
                        row["missing_repo_count"],
                        row["coverage_ratio"],
                        row["active_week_count"],
                        row["matched_row_count"],
                        row["matched_event_count"],
                        arguments.period_start,
                        arguments.period_end,
                    )
                    for row in coverage_summary
                ],
                schema=coverage_schema,
            ).write.mode("errorifexists").parquet(coverage_output)

        quality_schema = StructType(
            [
                StructField("input_path", StringType(), False),
                StructField("input_file_count", LongType(), False),
                StructField("period_start", StringType(), False),
                StructField("period_end", StringType(), False),
                StructField("total_input_events", LongType(), False),
                StructField("repo_id_null_count", LongType(), False),
                StructField("repo_name_null_count", LongType(), False),
                StructField("created_at_null_count", LongType(), False),
                StructField("invalid_event_count", LongType(), False),
                StructField("malformed_json_count", LongType(), False),
                StructField("valid_repo_event_count", LongType(), False),
                StructField("row_count", LongType(), False),
                StructField("unique_repo_id_count", LongType(), False),
                StructField("week_count", LongType(), False),
                StructField("repo_name_collision_count", LongType(), False),
            ]
        )
        spark.createDataFrame(
            [
                (
                    arguments.input,
                    len(input_files),
                    arguments.period_start,
                    arguments.period_end,
                    total_input_events,
                    _as_int(quality_row["repo_id_null_count"]),
                    _as_int(quality_row["repo_name_null_count"]),
                    _as_int(quality_row["created_at_null_count"]),
                    invalid_event_count,
                    _as_int(quality_row["malformed_json_count"]),
                    valid_repo_event_count,
                    row_count,
                    unique_repo_id_count,
                    len(observed_weeks),
                    repo_name_collision_count,
                )
            ],
            schema=quality_schema,
        ).write.mode("errorifexists").parquet(quality_output)

        readback_weeks: dict[str, dict[str, object]] = {}
        readback_rows = 0
        for week, week_output in week_outputs.items():
            slice_df = spark.read.parquet(week_output)
            if tuple(slice_df.columns) != ACTIVITY_COLUMNS:
                raise RuntimeError(
                    f"week {week} schema mismatch: "
                    f"{slice_df.columns} != {list(ACTIVITY_COLUMNS)}"
                )
            slice_stats = (
                slice_df.agg(
                    F.count(F.lit(1)).alias("row_count"),
                    F.countDistinct("repo_id").alias("repo_count"),
                    F.countDistinct("week_start").alias("week_count"),
                    F.sum(F.col("event_count")).alias("event_count"),
                    F.sum(F.when(F.col("repo_id").isNull(), 1).otherwise(0)).alias(
                        "null_repo_id"
                    ),
                    F.sum(F.when(F.col("repo_name").isNull(), 1).otherwise(0)).alias(
                        "null_repo_name"
                    ),
                    F.sum(F.when(F.col("event_count") < 0, 1).otherwise(0)).alias(
                        "negative_event_count"
                    ),
                )
                .first()
                .asDict()
            )
            slice_row_count = _as_int(slice_stats["row_count"])
            problems = {
                "duplicate repo_id": slice_row_count
                != _as_int(slice_stats["repo_count"]),
                "more than one week_start": _as_int(slice_stats["week_count"]) != 1,
                "null repo_id": _as_int(slice_stats["null_repo_id"]) > 0,
                "null repo_name": _as_int(slice_stats["null_repo_name"]) > 0,
                "negative event_count": _as_int(slice_stats["negative_event_count"])
                > 0,
                "row count changed": slice_row_count
                != _as_int(week_row_map[week]["row_count"]),
            }
            failed = sorted(name for name, tripped in problems.items() if tripped)
            if failed:
                raise RuntimeError(f"week {week} read-back rejected: {failed}")
            observed_week = slice_df.select("week_start").first()["week_start"]
            if observed_week != week:
                raise RuntimeError(
                    f"week directory {week} holds week_start {observed_week}"
                )
            readback_rows += slice_row_count
            readback_weeks[week] = {
                "uri": week_output,
                "row_count": slice_row_count,
                "event_count": _as_int(slice_stats["event_count"]),
                "fully_within_period": week_is_fully_within_period(
                    week, arguments.period_start, arguments.period_end
                ),
            }
        if readback_rows != row_count:
            raise RuntimeError(
                f"weekly row count changed during read-back: {row_count} != {readback_rows}"
            )

        output_file_count, output_bytes = _hadoop_path_stats(spark, arguments.output)
        elapsed_seconds = time.perf_counter() - started
        return {
            "application_id": spark.sparkContext.applicationId,
            "spark_version": spark.version,
            "spark_master": spark.sparkContext.master,
            "executor_count": _executor_count(spark),
            "default_parallelism": spark.sparkContext.defaultParallelism,
            "shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions"),
            "input": {
                "path": arguments.input,
                "file_count": len(input_files),
                "total_input_events": total_input_events,
            },
            "week_rule": {
                "week_start": "Monday",
                "timezone": "UTC",
                "boundary": "date_trunc('week', created_at) with session timeZone=UTC",
                "expected_weeks": list(expected_weeks),
                "observed_weeks": observed_weeks,
            },
            "data_quality": {
                "repo_id_null_count": _as_int(quality_row["repo_id_null_count"]),
                "repo_name_null_count": _as_int(quality_row["repo_name_null_count"]),
                "created_at_null_count": _as_int(quality_row["created_at_null_count"]),
                "invalid_event_count": invalid_event_count,
                "malformed_json_count": _as_int(quality_row["malformed_json_count"]),
                "valid_repo_event_count": valid_repo_event_count,
                "row_count": row_count,
                "unique_repo_id_count": unique_repo_id_count,
                "repo_name_collision_count": repo_name_collision_count,
                "duplicate_repo_week_count": 0,
            },
            "join_coverage": coverage_summary,
            "output": {
                "root": arguments.output,
                "repo_activity_weekly": activity_root,
                "weekly_event_type": week_type_output,
                "weeks": weeks_output,
                "join_coverage": coverage_output if cohorts else None,
                "data_quality": quality_output,
                "weeks_written": readback_weeks,
                "row_count": readback_rows,
                "parquet_file_count": output_file_count,
                "parquet_bytes": output_bytes,
                "readback_week_slices_match": True,
            },
            "runtime_seconds": round(elapsed_seconds, 3),
        }
    finally:
        if weekly is not None:
            weekly.unpersist()
        spark.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate GH Archive repo activity into Monday-start weeks."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-files", type=int, default=744)
    parser.add_argument("--period-start", default=HISTORICAL_START)
    parser.add_argument("--period-end", default=HISTORICAL_CUTOFF)
    parser.add_argument(
        "--join-ids",
        dest="join_ids",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help=(
            "JOIN coverage cohort, repeatable; PATH is a repo-fetch-candidates/v1, "
            "github-repo-snapshot/v1 or c-public-repo-analysis/v1 envelope."
        ),
    )
    parser.add_argument("--join-max-rows", type=int, default=DEFAULT_JOIN_MAX_ROWS)
    parser.add_argument(
        "--app-name",
        default="gitjob-s15p21e102-166-repo-activity-weekly",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.expected_files < 1:
        parser.error("--expected-files must be positive")
    if arguments.join_max_rows < 1:
        parser.error("--join-max-rows must be positive")
    try:
        validate_period(arguments.period_start, arguments.period_end)
        cohorts = [parse_join_ids_argument(value) for value in arguments.join_ids]
    except ValueError as exc:
        parser.error(str(exc))
    labels = [label for label, _ in cohorts]
    if len(labels) != len(set(labels)):
        parser.error("--join-ids labels must be unique")
    arguments.join_cohorts = cohorts
    result = run_job(arguments)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
