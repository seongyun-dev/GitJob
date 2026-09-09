"""Spark batch for GH Archive repo activity, ranking, and coverage.

The job deliberately keeps the Raw layer opaque: it reads the four fields needed
for this aggregation, counts one input row as one activity event, and writes a
new immutable Parquet output.  No repository contents or technology semantics
are inspected here.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

HISTORICAL_START = "2026-08-01T00:00:00Z"
HISTORICAL_CUTOFF = "2026-09-01T00:00:00Z"
# The August MVP remains the default period, while the validated Historical
# Raw window now permits the six-month follow-up without changing that default.
SUPPORTED_HISTORICAL_START = "2026-03-01T00:00:00Z"
SUPPORTED_HISTORICAL_CUTOFF = "2026-09-01T00:00:00Z"
DEFAULT_INPUT = "hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz"
DEFAULT_TOP_N = (100, 500, 1_000, 3_000, 5_000, 10_000, 20_000)


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


def parse_top_n(value: str) -> tuple[int, ...]:
    """Parse comma-separated positive, unique Top-N thresholds."""

    values: list[int] = []
    for raw_value in value.split(","):
        token = raw_value.strip()
        if not token:
            raise ValueError("top-n values must not be empty")
        try:
            parsed = int(token)
        except ValueError as exc:
            raise ValueError(f"top-n value is not an integer: {token}") from exc
        if parsed < 1:
            raise ValueError("top-n values must be positive")
        if parsed in values:
            raise ValueError(f"top-n values must be unique: {parsed}")
        values.append(parsed)
    return tuple(sorted(values))


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


def rank_activity_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Apply the production ordering to a small in-process fixture.

    The Spark job performs the same ordering with ``row_number``.  This helper
    exists only to make the tie policy executable in unit tests; production
    activity data never comes through the Python driver.
    """

    normalized: list[dict[str, object]] = []
    seen: set[int] = set()
    for row in rows:
        repo_id = int(row["repo_id"])
        activity_count = int(row["activity_count"])
        if repo_id in seen:
            raise ValueError(f"duplicate repo_id in fixture: {repo_id}")
        if activity_count < 0:
            raise ValueError("activity_count cannot be negative")
        seen.add(repo_id)
        normalized.append(
            {
                "repo_id": repo_id,
                "repo_name": str(row["repo_name"]),
                "activity_count": activity_count,
            }
        )

    ordered = sorted(
        normalized,
        key=lambda row: (-int(row["activity_count"]), int(row["repo_id"])),
    )
    return [{**row, "rank": rank} for rank, row in enumerate(ordered, start=1)]


def coverage_rows_from_ranked(
    ranked_rows: Sequence[Mapping[str, object]],
    top_n_values: Sequence[int],
    *,
    total_input_events: int,
    valid_repo_event_count: int,
) -> list[dict[str, object]]:
    """Calculate coverage for a small unit-test fixture without Spark."""

    if total_input_events < 0 or valid_repo_event_count < 0:
        raise ValueError("event denominators cannot be negative")
    rows: list[dict[str, object]] = []
    previous_valid = 0.0
    previous_total = 0.0
    for top_n in sorted(top_n_values):
        selected = [row for row in ranked_rows if int(row["rank"]) <= int(top_n)]
        event_count = sum(int(row["activity_count"]) for row in selected)
        valid_coverage = (
            event_count / valid_repo_event_count if valid_repo_event_count else 0.0
        )
        total_coverage = event_count / total_input_events if total_input_events else 0.0
        rows.append(
            {
                "top_n": int(top_n),
                "selected_repo_count": len(selected),
                "event_count": event_count,
                "coverage_valid": valid_coverage,
                "coverage_total": total_coverage,
                "coverage_delta_valid": valid_coverage - previous_valid,
                "coverage_delta_total": total_coverage - previous_total,
            }
        )
        previous_valid = valid_coverage
        previous_total = total_coverage
    return rows


def _coverage_rows_from_counts(
    top_n_values: Sequence[int],
    event_counts: Mapping[int, int],
    repo_counts: Mapping[int, int],
    *,
    total_input_events: int,
    valid_repo_event_count: int,
    period_start: str,
    period_end: str,
) -> list[dict[str, object]]:
    if total_input_events < 0 or valid_repo_event_count < 0:
        raise ValueError("event denominators cannot be negative")
    rows: list[dict[str, object]] = []
    previous_valid = 0.0
    previous_total = 0.0
    for top_n in sorted(top_n_values):
        event_count = int(event_counts.get(top_n, 0))
        valid_coverage = (
            event_count / valid_repo_event_count if valid_repo_event_count else 0.0
        )
        total_coverage = event_count / total_input_events if total_input_events else 0.0
        rows.append(
            {
                "top_n": int(top_n),
                "selected_repo_count": int(repo_counts.get(top_n, 0)),
                "event_count": event_count,
                "coverage_valid": valid_coverage,
                "coverage_total": total_coverage,
                "coverage_delta_valid": valid_coverage - previous_valid,
                "coverage_delta_total": total_coverage - previous_total,
                "period_start": period_start,
                "period_end": period_end,
            }
        )
        previous_valid = valid_coverage
        previous_total = total_coverage
    return rows


def build_event_schema() -> Any:
    """Return the explicit minimum GH Archive input schema.

    PySpark is imported lazily so the contract helpers remain testable in the
    repository's normal Python environment, where only the Spark image carries
    PySpark.
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
    """Execute the distributed aggregation and write immutable Parquet data."""

    from pyspark import StorageLevel
    from pyspark.sql import SparkSession, Window
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        DoubleType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    validate_period(arguments.period_start, arguments.period_end)
    started = time.perf_counter()
    spark = (
        SparkSession.builder.appName(arguments.app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    grouped = None
    ranked = None
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

        quality_row = (
            raw.agg(
                F.count(F.lit(1)).alias("total_input_events"),
                F.sum(F.when(F.col("repo.id").isNull(), 1).otherwise(0)).alias(
                    "repo_id_null_count"
                ),
                F.sum(F.when(F.col("repo.name").isNull(), 1).otherwise(0)).alias(
                    "repo_name_null_count"
                ),
                F.sum(
                    F.when(
                        F.col("repo.id").isNull() | F.col("repo.name").isNull(),
                        1,
                    ).otherwise(0)
                ).alias("invalid_repo_event_count"),
                F.sum(
                    F.when(F.col("_corrupt_record").isNotNull(), 1).otherwise(0)
                ).alias("malformed_json_count"),
            )
            .first()
            .asDict()
        )
        total_input_events = _as_int(quality_row["total_input_events"])
        repo_id_null_count = _as_int(quality_row["repo_id_null_count"])
        repo_name_null_count = _as_int(quality_row["repo_name_null_count"])
        invalid_repo_event_count = _as_int(quality_row["invalid_repo_event_count"])
        malformed_json_count = _as_int(quality_row["malformed_json_count"])

        valid = raw.where(
            F.col("repo.id").isNotNull() & F.col("repo.name").isNotNull()
        ).select(
            F.col("repo.id").cast("long").alias("repo_id"),
            F.col("repo.name").alias("repo_name"),
            F.to_timestamp(F.col("created_at")).alias("created_at_ts"),
        )
        grouped = (
            valid.groupBy("repo_id")
            .agg(
                F.count(F.lit(1)).cast("long").alias("activity_count"),
                F.countDistinct("repo_name").cast("long").alias("name_count"),
                F.max(F.struct(F.col("created_at_ts"), F.col("repo_name"))).alias(
                    "latest"
                ),
            )
            .persist(StorageLevel.DISK_ONLY)
        )
        grouped_stats = (
            grouped.agg(
                F.count(F.lit(1)).alias("unique_repo_id_count"),
                F.sum(F.col("activity_count")).alias("valid_repo_event_count"),
                F.sum(F.when(F.col("name_count") > 1, 1).otherwise(0)).alias(
                    "repo_name_collision_count"
                ),
                F.sum(
                    F.when(
                        F.col("name_count") > 1,
                        F.col("activity_count"),
                    ).otherwise(0)
                ).alias("collision_event_count"),
            )
            .first()
            .asDict()
        )
        unique_repo_id_count = _as_int(grouped_stats["unique_repo_id_count"])
        valid_repo_event_count = _as_int(grouped_stats["valid_repo_event_count"])
        repo_name_collision_count = _as_int(grouped_stats["repo_name_collision_count"])
        collision_event_count = _as_int(grouped_stats["collision_event_count"])

        activity = grouped.select(
            F.col("repo_id"),
            F.col("latest.repo_name").alias("repo_name"),
            F.col("activity_count"),
        )
        ranking_window = Window.orderBy(
            F.col("activity_count").desc(),
            F.col("repo_id").asc(),
        )
        ranked = (
            activity.withColumn(
                "rank",
                F.row_number().over(ranking_window).cast("long"),
            )
            .withColumn("period_start", F.lit(arguments.period_start))
            .withColumn("period_end", F.lit(arguments.period_end))
            .select(
                "repo_id",
                "repo_name",
                "activity_count",
                "rank",
                "period_start",
                "period_end",
            )
            .persist(StorageLevel.DISK_ONLY)
        )
        output_rows = ranked.count()

        top_event_exprs: list[Any] = []
        top_repo_exprs: list[Any] = []
        for top_n in arguments.top_n_values:
            selected = F.col("rank") <= F.lit(top_n)
            top_event_exprs.append(
                F.sum(F.when(selected, F.col("activity_count")).otherwise(0)).alias(
                    f"event_count_{top_n}"
                )
            )
            top_repo_exprs.append(
                F.sum(F.when(selected, 1).otherwise(0)).alias(f"repo_count_{top_n}")
            )
        top_row = ranked.agg(*(top_event_exprs + top_repo_exprs)).first().asDict()
        event_counts = {
            top_n: _as_int(top_row[f"event_count_{top_n}"])
            for top_n in arguments.top_n_values
        }
        repo_counts = {
            top_n: _as_int(top_row[f"repo_count_{top_n}"])
            for top_n in arguments.top_n_values
        }
        coverage_rows = _coverage_rows_from_counts(
            arguments.top_n_values,
            event_counts,
            repo_counts,
            total_input_events=total_input_events,
            valid_repo_event_count=valid_repo_event_count,
            period_start=arguments.period_start,
            period_end=arguments.period_end,
        )

        output_root = arguments.output.rstrip("/")
        activity_output = f"{output_root}/repo_activity"
        coverage_output = f"{output_root}/topn_coverage"
        quality_output = f"{output_root}/data_quality"
        ranked.write.mode("errorifexists").parquet(activity_output)

        coverage_schema = StructType(
            [
                StructField("top_n", LongType(), False),
                StructField("selected_repo_count", LongType(), False),
                StructField("event_count", LongType(), False),
                StructField("coverage_valid", DoubleType(), False),
                StructField("coverage_total", DoubleType(), False),
                StructField("coverage_delta_valid", DoubleType(), False),
                StructField("coverage_delta_total", DoubleType(), False),
                StructField("period_start", StringType(), False),
                StructField("period_end", StringType(), False),
            ]
        )
        coverage_df = spark.createDataFrame(
            [
                (
                    row["top_n"],
                    row["selected_repo_count"],
                    row["event_count"],
                    row["coverage_valid"],
                    row["coverage_total"],
                    row["coverage_delta_valid"],
                    row["coverage_delta_total"],
                    row["period_start"],
                    row["period_end"],
                )
                for row in coverage_rows
            ],
            schema=coverage_schema,
        )
        coverage_df.write.mode("errorifexists").parquet(coverage_output)

        collision_ratio = (
            repo_name_collision_count / unique_repo_id_count
            if unique_repo_id_count
            else 0.0
        )
        quality_schema = StructType(
            [
                StructField("input_path", StringType(), False),
                StructField("input_file_count", LongType(), False),
                StructField("period_start", StringType(), False),
                StructField("period_end", StringType(), False),
                StructField("total_input_events", LongType(), False),
                StructField("repo_id_null_count", LongType(), False),
                StructField("repo_name_null_count", LongType(), False),
                StructField("invalid_repo_event_count", LongType(), False),
                StructField("malformed_json_count", LongType(), False),
                StructField("valid_repo_event_count", LongType(), False),
                StructField("unique_repo_id_count", LongType(), False),
                StructField("repo_name_collision_count", LongType(), False),
                StructField("collision_event_count", LongType(), False),
                StructField("repo_name_collision_ratio", DoubleType(), False),
            ]
        )
        quality_df = spark.createDataFrame(
            [
                (
                    arguments.input,
                    len(input_files),
                    arguments.period_start,
                    arguments.period_end,
                    total_input_events,
                    repo_id_null_count,
                    repo_name_null_count,
                    invalid_repo_event_count,
                    malformed_json_count,
                    valid_repo_event_count,
                    unique_repo_id_count,
                    repo_name_collision_count,
                    collision_event_count,
                    collision_ratio,
                )
            ],
            schema=quality_schema,
        )
        quality_df.write.mode("errorifexists").parquet(quality_output)

        readback_activity = spark.read.parquet(activity_output)
        expected_activity_columns = [
            "repo_id",
            "repo_name",
            "activity_count",
            "rank",
            "period_start",
            "period_end",
        ]
        if readback_activity.columns != expected_activity_columns:
            raise RuntimeError(
                "activity output schema mismatch: "
                f"{readback_activity.columns} != {expected_activity_columns}"
            )
        readback_rows = readback_activity.count()
        readback_unique_repos = readback_activity.select("repo_id").distinct().count()
        readback_null_repo_id = readback_activity.where(
            F.col("repo_id").isNull()
        ).count()
        readback_null_activity = readback_activity.where(
            F.col("activity_count").isNull()
        ).count()
        rank_bounds = (
            readback_activity.agg(
                F.min("rank").alias("rank_min"),
                F.max("rank").alias("rank_max"),
            )
            .first()
            .asDict()
        )
        duplicate_rank_count = (
            readback_activity.groupBy("rank").count().where(F.col("count") > 1).count()
        )
        readback_coverage = {
            int(row["top_n"]): row.asDict()
            for row in spark.read.parquet(coverage_output)
            .orderBy("top_n")
            .toLocalIterator()
        }
        for expected in coverage_rows:
            actual = readback_coverage[int(expected["top_n"])]
            if int(actual["event_count"]) != int(expected["event_count"]):
                raise RuntimeError(
                    f"coverage read-back mismatch for top_n={expected['top_n']}"
                )

        output_file_count, output_bytes = _hadoop_path_stats(spark, arguments.output)
        elapsed_seconds = time.perf_counter() - started
        summary = {
            "application_id": spark.sparkContext.applicationId,
            "spark_version": spark.version,
            "spark_master": spark.sparkContext.master,
            "executor_count": _executor_count(spark),
            "default_parallelism": spark.sparkContext.defaultParallelism,
            "shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions"),
            "adaptive_query_execution": spark.conf.get("spark.sql.adaptive.enabled"),
            "input": {
                "path": arguments.input,
                "file_count": len(input_files),
                "total_input_events": total_input_events,
            },
            "data_quality": {
                "repo_id_null_count": repo_id_null_count,
                "repo_name_null_count": repo_name_null_count,
                "invalid_repo_event_count": invalid_repo_event_count,
                "malformed_json_count": malformed_json_count,
                "valid_repo_event_count": valid_repo_event_count,
                "unique_repo_id_count": unique_repo_id_count,
                "repo_name_collision_count": repo_name_collision_count,
                "collision_event_count": collision_event_count,
                "repo_name_collision_ratio": collision_ratio,
            },
            "ranking": {
                "ordering": ["activity_count DESC", "repo_id ASC"],
                "rank_policy": "row_number",
                "top_n": list(arguments.top_n_values),
                "coverage": coverage_rows,
            },
            "output": {
                "root": arguments.output,
                "repo_activity": activity_output,
                "topn_coverage": coverage_output,
                "data_quality": quality_output,
                "row_count": readback_rows,
                "unique_repo_id_count": readback_unique_repos,
                "null_repo_id": readback_null_repo_id,
                "null_activity_count": readback_null_activity,
                "rank_min": _as_int(rank_bounds.get("rank_min")),
                "rank_max": _as_int(rank_bounds.get("rank_max")),
                "duplicate_rank_count": duplicate_rank_count,
                "parquet_file_count": output_file_count,
                "parquet_bytes": output_bytes,
                "readback_top_n_match": True,
            },
            "runtime_seconds": round(elapsed_seconds, 3),
        }
        if output_rows != readback_rows:
            raise RuntimeError(
                f"activity row count changed during read-back: {output_rows} != {readback_rows}"
            )
        return summary
    finally:
        if ranked is not None:
            ranked.unpersist()
        if grouped is not None:
            grouped.unpersist()
        spark.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate GH Archive repo activity and Top-N coverage."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-files", type=int, default=744)
    parser.add_argument(
        "--top-n",
        dest="top_n",
        default=",".join(str(value) for value in DEFAULT_TOP_N),
    )
    parser.add_argument("--period-start", default=HISTORICAL_START)
    parser.add_argument("--period-end", default=HISTORICAL_CUTOFF)
    parser.add_argument(
        "--app-name",
        default="gitjob-s15p21e102-109-repo-activity-topn",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.expected_files < 1:
        parser.error("--expected-files must be positive")
    try:
        arguments.top_n_values = parse_top_n(arguments.top_n)
        validate_period(arguments.period_start, arguments.period_end)
    except ValueError as exc:
        parser.error(str(exc))
    result = run_job(arguments)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
