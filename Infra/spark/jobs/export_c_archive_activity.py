"""Export a bounded C archive-trend input from A's Repo Activity Parquet.

The large activity dataset stays in Spark.  Only repository IDs from a bounded
candidate/public snapshot are left-semi joined and streamed to the driver for a
small immutable CSV or NDJSON export consumed below ``C_ARCHIVE_ACTIVITY_ROOT``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

EXPORT_SCHEMA_VERSION = "c-archive-activity-export/v1"
METADATA_SCHEMA_VERSION = "repo-activity/v1"
MAX_ID_FILE_BYTES = 32 * 1024 * 1024
MAX_EXPORT_BYTES = 32 * 1024 * 1024
PUBLISHED_DIRECTORY_MODE = 0o555
PUBLISHED_FILE_MODE = 0o444
_MONTH_PATTERN = re.compile(r"^(?P<year>[0-9]{4})-(0[1-9]|1[0-2])$")
_WEEK_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
UTC = timezone.utc


def validate_period(period: str, granularity: str) -> None:
    if granularity == "MONTH":
        match = _MONTH_PATTERN.fullmatch(period)
        if match is None or int(match["year"]) < 2020:
            raise ValueError("MONTH period must be YYYY-MM and year >= 2020")
        return
    if granularity != "WEEK":
        raise ValueError("granularity must be MONTH or WEEK")
    if not _WEEK_PATTERN.fullmatch(period):
        raise ValueError("WEEK period must be an ISO date")
    try:
        parsed = date.fromisoformat(period)
    except ValueError as exc:
        raise ValueError("WEEK period must be a real ISO date") from exc
    if parsed.year < 2020:
        raise ValueError("WEEK period year must be >= 2020")
    if parsed.weekday() != 0:
        raise ValueError("WEEK period must start on Monday")


def _canonical_utc_hour(value: object) -> str:
    if isinstance(value, datetime):
        parsed = (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )
    elif isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("source period boundary must be an ISO timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        else:
            parsed = parsed.astimezone(UTC)
    else:
        raise TypeError("source period boundary must be a timestamp")
    if any((parsed.minute, parsed.second, parsed.microsecond)):
        raise ValueError("source period boundary must be hour-aligned")
    return parsed.isoformat().replace("+00:00", "Z")


def _month_interval(period: str) -> tuple[str, str]:
    validate_period(period, "MONTH")
    year, month = (int(part) for part in period.split("-"))
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return (
        f"{year:04d}-{month:02d}-01T00:00:00Z",
        f"{end_year:04d}-{end_month:02d}-01T00:00:00Z",
    )


def validate_source_period_binding(
    period: str,
    granularity: str,
    *,
    observed_periods: Iterable[object] | None = None,
    observed_intervals: Iterable[tuple[object, object]] | None = None,
) -> None:
    """Reject relabelling a multi-period aggregate as one requested period."""

    validate_period(period, granularity)
    if observed_periods is not None:
        values = tuple(str(value) for value in observed_periods)
        if values != (period,):
            raise ValueError("source period values do not match requested period")
        return
    if granularity == "MONTH" and observed_intervals is not None:
        intervals = tuple(
            (_canonical_utc_hour(start), _canonical_utc_hour(end))
            for start, end in observed_intervals
        )
        if intervals != (_month_interval(period),):
            raise ValueError("source period interval does not match requested month")
        return
    raise ValueError("Repo Activity source has no verifiable period binding")


def _read_bounded_json(path: Path) -> Mapping[str, object]:
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
    return payload


def load_repo_ids(path: Path, *, max_rows: int) -> tuple[int, ...]:
    """Load only an approved candidate/public-snapshot repository ID envelope."""

    repo_ids, _ = _load_repo_id_source(path, max_rows=max_rows)
    return repo_ids


def _load_repo_id_source(path: Path, *, max_rows: int) -> tuple[tuple[int, ...], bool]:
    """Return IDs and whether a PUBLIC denominator may have inactive repos."""

    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    payload = _read_bounded_json(path)
    schema = payload.get("schema_version")
    if schema == "c-public-published-result/v1":
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise TypeError("published PUBLIC result must be an object")
        payload = result
        schema = payload.get("schema_version")
    public_source = schema in {
        "c-public-repo-analysis/v1",
        "c-public-repo-analysis/v2",
    }
    if schema == "repo-fetch-candidates/v1":
        rows = payload.get("candidates")
        field = "repo_id"
    elif schema == "github-repo-snapshot/v1" or public_source:
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
        if public_source:
            included = row.get("included_in_denominator")
            if not isinstance(included, bool):
                raise TypeError(
                    "PUBLIC repository rows need boolean included_in_denominator"
                )
            if not included:
                continue
        repo_id = row.get(field)
        if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
            raise ValueError("repo_id must be a strict positive integer")
        repo_ids.append(repo_id)
    if not repo_ids:
        raise ValueError("repository ID source must not be empty")
    if len(repo_ids) != len(set(repo_ids)):
        raise ValueError("duplicate repo_id in repository ID source")
    return tuple(sorted(repo_ids)), public_source


def _absolute_uri(value: str) -> str:
    parsed = urlsplit(value)
    if not value.strip() or not parsed.scheme or not parsed.path:
        raise ValueError("source_uri must be an absolute URI")
    return value


def _validate_selected_repository_coverage(
    *, selected_repo_count: int, requested_repo_count: int, public_source: bool
) -> None:
    """PUBLIC denominators may contain repos with no event in one week."""
    if not public_source and selected_repo_count != requested_repo_count:
        raise RuntimeError("candidate repository IDs are missing from Repo Activity")


def build_export_metadata(
    *,
    source_schema_version: str,
    source_version: str,
    dataset_snapshot_id: str,
    source_uri: str,
    source_hash: str,
    upstream_source_uri: str | None = None,
    upstream_source_hash: str | None = None,
    period: str,
    granularity: str,
    top_n_limit: int,
    selected_repo_count: int,
    selected_event_count: int,
    valid_event_count: int,
    total_active_repo_count: int,
    selection_event_coverage: float | None = None,
) -> dict[str, object]:
    validate_period(period, granularity)
    for name, value in (
        ("source_schema_version", source_schema_version),
        ("source_version", source_version),
        ("dataset_snapshot_id", dataset_snapshot_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be blank")
    _absolute_uri(source_uri)
    if not isinstance(source_hash, str) or not _SHA256_PATTERN.fullmatch(source_hash):
        raise ValueError("source_hash must be a lowercase SHA-256")
    if (upstream_source_uri is None) != (upstream_source_hash is None):
        raise ValueError("upstream source URI and hash must be supplied together")
    if upstream_source_uri is not None:
        _absolute_uri(upstream_source_uri)
        if not _SHA256_PATTERN.fullmatch(upstream_source_hash or ""):
            raise ValueError("upstream_source_hash must be a lowercase SHA-256")
    integers = {
        "top_n_limit": top_n_limit,
        "selected_repo_count": selected_repo_count,
        "selected_event_count": selected_event_count,
        "valid_event_count": valid_event_count,
        "total_active_repo_count": total_active_repo_count,
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in integers.values()
    ):
        raise TypeError("metadata counts must be strict integers")
    if top_n_limit < 1:
        raise ValueError("top_n_limit must be positive")
    if any(value < 0 for name, value in integers.items() if name != "top_n_limit"):
        raise ValueError("metadata counts must be nonnegative")
    if selected_repo_count > top_n_limit:
        raise ValueError("selected_repo_count exceeds top_n_limit")
    if selected_repo_count > total_active_repo_count:
        raise ValueError("selected_repo_count exceeds total_active_repo_count")
    if selected_event_count > valid_event_count:
        raise ValueError("selected_event_count exceeds valid_event_count")
    expected_coverage = (
        selected_event_count / valid_event_count if valid_event_count else 0.0
    )
    if (
        selection_event_coverage is not None
        and abs(float(selection_event_coverage) - expected_coverage) > 1e-12
    ):
        raise ValueError("selection_event_coverage must use valid_event_count")
    metadata: dict[str, object] = {
        "source_schema_version": source_schema_version,
        "source_version": source_version,
        "dataset_snapshot_id": dataset_snapshot_id,
        "source_uri": source_uri,
        "source_hash": source_hash,
        "period": period,
        "granularity": granularity,
        "top_n_limit": top_n_limit,
        "selected_repo_count": selected_repo_count,
        "selected_event_count": selected_event_count,
        "valid_event_count": valid_event_count,
        "total_active_repo_count": total_active_repo_count,
        "selection_event_coverage": expected_coverage,
    }
    if upstream_source_uri is not None:
        metadata["upstream_source_uri"] = upstream_source_uri
        metadata["upstream_source_hash"] = upstream_source_hash
    return metadata


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_export_row(
    row: Mapping[str, object], previous_repo_id: int | None
) -> tuple[int, str, int]:
    repo_id = row.get("repo_id")
    repo_name = row.get("repo_name")
    event_count = row.get("event_count")
    if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
        raise ValueError("repo_id must be a strict positive integer")
    if previous_repo_id is not None and repo_id <= previous_repo_id:
        raise ValueError("export rows must have unique ascending repo_id")
    if not isinstance(repo_name, str) or not repo_name.strip():
        raise ValueError("repo_name must be a non-blank string")
    if (
        isinstance(event_count, bool)
        or not isinstance(event_count, int)
        or event_count < 0
    ):
        raise ValueError("event_count must be a strict nonnegative integer")
    return repo_id, repo_name, event_count


def write_bounded_export(
    output: Path,
    rows: Iterable[Mapping[str, object]],
    metadata: Mapping[str, object],
    *,
    output_format: str,
) -> dict[str, object]:
    """Stream selected Top-N rows into a new immutable local export directory."""

    if output_format not in {"csv", "ndjson"}:
        raise ValueError("output_format must be csv or ndjson")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    validated_metadata = build_export_metadata(**dict(metadata))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent))
    )
    data_name = "activity.csv" if output_format == "csv" else "activity.ndjson"
    data_path = temporary / data_name
    metadata_path = temporary / "metadata.json"
    manifest_path = temporary / "manifest.json"
    row_count = 0
    event_sum = 0
    previous_repo_id: int | None = None
    period_field = (
        "period" if validated_metadata["granularity"] == "MONTH" else "week_start"
    )
    try:
        with data_path.open("w", encoding="utf-8", newline="") as stream:
            writer = None
            if output_format == "csv":
                writer = csv.DictWriter(
                    stream,
                    fieldnames=(period_field, "repo_id", "repo_name", "event_count"),
                    lineterminator="\n",
                )
                writer.writeheader()
            for raw in rows:
                repo_id, repo_name, event_count = _validated_export_row(
                    raw, previous_repo_id
                )
                row_count += 1
                if row_count > int(validated_metadata["top_n_limit"]):
                    raise ValueError("export rows exceed top_n_limit")
                rendered = {
                    period_field: validated_metadata["period"],
                    "repo_id": repo_id,
                    "repo_name": repo_name,
                    "event_count": event_count,
                }
                if writer is not None:
                    writer.writerow(rendered)
                else:
                    stream.write(
                        json.dumps(
                            rendered,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        + "\n"
                    )
                previous_repo_id = repo_id
                event_sum += event_count
        if row_count != validated_metadata["selected_repo_count"]:
            raise ValueError("export row count does not match selected_repo_count")
        if event_sum != validated_metadata["selected_event_count"]:
            raise ValueError("export event sum does not match selected_event_count")
        if data_path.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError("bounded activity export exceeds 32 MiB")

        data_hash = _sha256_file(data_path)
        export_source_uri = (
            "c-archive-activity://export/"
            f"{validated_metadata['dataset_snapshot_id']}/{data_name}"
        )
        export_metadata_input = {
            **validated_metadata,
            "source_uri": export_source_uri,
            "source_hash": data_hash,
            "upstream_source_uri": validated_metadata.get("upstream_source_uri")
            or validated_metadata["source_uri"],
            "upstream_source_hash": validated_metadata.get("upstream_source_hash")
            or validated_metadata["source_hash"],
        }
        export_metadata = build_export_metadata(**export_metadata_input)
        metadata_bytes = _canonical_json_bytes(export_metadata)
        metadata_path.write_bytes(metadata_bytes)
        metadata_hash = hashlib.sha256(metadata_bytes).hexdigest()
        manifest: dict[str, object] = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "data_file": data_name,
            "data_sha256": data_hash,
            "metadata_file": metadata_path.name,
            "metadata_sha256": metadata_hash,
            "record_count": row_count,
        }
        manifest_path.write_bytes(_canonical_json_bytes(manifest))
        for published_file in (data_path, metadata_path, manifest_path):
            os.chmod(published_file, PUBLISHED_FILE_MODE)
        os.chmod(temporary, PUBLISHED_DIRECTORY_MODE)
        os.replace(temporary, output)
        return {"metadata": export_metadata, "manifest": manifest}
    except BaseException:
        if temporary.exists():
            os.chmod(temporary, 0o700)
            for published_file in (data_path, metadata_path, manifest_path):
                if published_file.exists():
                    os.chmod(published_file, 0o600)
            shutil.rmtree(temporary)
        raise


def _activity_quality(activity: Any, event_column: str) -> tuple[int, int]:
    from pyspark.sql import functions as F

    row = (
        activity.agg(
            F.count(F.lit(1)).alias("repo_count"),
            F.countDistinct("repo_id").alias("distinct_repo_count"),
            F.sum(F.col(event_column)).alias("event_count"),
            F.sum(
                F.when(
                    F.col("repo_id").isNull()
                    | F.col("repo_name").isNull()
                    | F.col(event_column).isNull(),
                    1,
                ).otherwise(0)
            ).alias("null_count"),
            F.sum(
                F.when(
                    (F.col(event_column) < 0)
                    | (F.length(F.trim(F.col("repo_name"))) == 0),
                    1,
                ).otherwise(0)
            ).alias("invalid_value_count"),
        )
        .first()
        .asDict()
    )
    repo_count = int(row["repo_count"] or 0)
    if int(row["null_count"] or 0):
        raise RuntimeError("Repo Activity contains null required fields")
    if int(row["distinct_repo_count"] or 0) != repo_count:
        raise RuntimeError("Repo Activity contains duplicate repo_id")
    if int(row["invalid_value_count"] or 0):
        raise RuntimeError("Repo Activity contains negative counts or blank names")
    return repo_count, int(row["event_count"] or 0)


def _validate_activity_period(activity: Any, period: str, granularity: str) -> None:
    from pyspark.sql import functions as F

    period_column = "period" if granularity == "MONTH" else "week_start"
    if period_column in activity.columns:
        observed = tuple(
            row["period_value"]
            for row in activity.select(
                F.col(period_column).cast("string").alias("period_value")
            )
            .distinct()
            .limit(2)
            .collect()
        )
        validate_source_period_binding(period, granularity, observed_periods=observed)
        return
    if granularity == "MONTH" and {
        "period_start",
        "period_end",
    }.issubset(activity.columns):
        observed_intervals = tuple(
            (row["period_start"], row["period_end"])
            for row in activity.select("period_start", "period_end")
            .distinct()
            .limit(2)
            .collect()
        )
        validate_source_period_binding(
            period,
            granularity,
            observed_intervals=observed_intervals,
        )
        return
    raise RuntimeError("Repo Activity has no source period columns")


def run_job(arguments: argparse.Namespace) -> dict[str, object]:
    """Run a distributed semi-join; never collect the full activity dataset."""

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import LongType, StructField, StructType

    if arguments.output.exists():
        raise FileExistsError(
            f"refusing to overwrite existing output: {arguments.output}"
        )
    validate_period(arguments.period, arguments.granularity)
    repo_ids, public_source = _load_repo_id_source(
        arguments.repo_ids, max_rows=arguments.top_n_limit
    )
    spark = SparkSession.builder.appName(arguments.app_name).getOrCreate()
    try:
        activity = spark.read.parquet(arguments.input)
        required = {"repo_id", "repo_name"}
        if not required.issubset(activity.columns):
            raise RuntimeError("Repo Activity is missing repo_id or repo_name")
        if "event_count" in activity.columns:
            event_column = "event_count"
        elif "activity_count" in activity.columns:
            event_column = "activity_count"
        else:
            raise RuntimeError("Repo Activity is missing event_count/activity_count")

        _validate_activity_period(activity, arguments.period, arguments.granularity)
        total_repo_count, derived_valid_event_count = _activity_quality(
            activity, event_column
        )
        valid_event_count = (
            arguments.valid_event_count
            if arguments.valid_event_count is not None
            else derived_valid_event_count
        )
        total_active_repo_count = (
            arguments.total_active_repo_count
            if arguments.total_active_repo_count is not None
            else total_repo_count
        )
        if valid_event_count != derived_valid_event_count:
            raise RuntimeError("declared valid_event_count differs from Parquet sum")
        if total_active_repo_count != total_repo_count:
            raise RuntimeError(
                "declared total_active_repo_count differs from Parquet rows"
            )

        ids = spark.createDataFrame(
            [(repo_id,) for repo_id in repo_ids],
            StructType([StructField("repo_id", LongType(), False)]),
        )
        selected = (
            activity.join(F.broadcast(ids), "repo_id", "left_semi")
            .select(
                F.col("repo_id").cast("long").alias("repo_id"),
                F.col("repo_name").cast("string").alias("repo_name"),
                F.col(event_column).cast("long").alias("event_count"),
            )
            .orderBy("repo_id")
        )
        selected_summary = (
            selected.agg(
                F.count(F.lit(1)).alias("repo_count"),
                F.sum("event_count").alias("event_count"),
            )
            .first()
            .asDict()
        )
        selected_repo_count = int(selected_summary["repo_count"] or 0)
        selected_event_count = int(selected_summary["event_count"] or 0)
        _validate_selected_repository_coverage(
            selected_repo_count=selected_repo_count,
            requested_repo_count=len(repo_ids),
            public_source=public_source,
        )

        metadata = build_export_metadata(
            source_schema_version=arguments.source_schema_version,
            source_version=arguments.source_version,
            dataset_snapshot_id=arguments.dataset_snapshot_id,
            source_uri=arguments.source_uri or arguments.input,
            source_hash=arguments.source_hash,
            upstream_source_uri=arguments.upstream_source_uri,
            upstream_source_hash=arguments.upstream_source_hash,
            period=arguments.period,
            granularity=arguments.granularity,
            top_n_limit=arguments.top_n_limit,
            selected_repo_count=selected_repo_count,
            selected_event_count=selected_event_count,
            valid_event_count=valid_event_count,
            total_active_repo_count=total_active_repo_count,
        )
        return write_bounded_export(
            arguments.output,
            (row.asDict() for row in selected.toLocalIterator()),
            metadata,
            output_format=arguments.output_format,
        )
    finally:
        spark.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export bounded C archive trend rows from Repo Activity Parquet."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--repo-ids", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-format", choices=("csv", "ndjson"), default="ndjson")
    parser.add_argument("--period", required=True)
    parser.add_argument("--granularity", choices=("MONTH", "WEEK"), required=True)
    parser.add_argument("--top-n-limit", type=int, required=True)
    parser.add_argument("--source-schema-version", default=METADATA_SCHEMA_VERSION)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--dataset-snapshot-id", required=True)
    parser.add_argument("--source-uri")
    parser.add_argument("--source-hash", required=True)
    # The upstream binding is what a downstream consumer compares against the
    # producing pipeline's own manifest.  Without these it silently falls back
    # to `--source-uri`/`--source-hash`, which describe this export's input
    # rather than the manifest it must be bound to.  Supply both or neither.
    parser.add_argument("--upstream-source-uri")
    parser.add_argument("--upstream-source-hash")
    parser.add_argument("--valid-event-count", type=int)
    parser.add_argument("--total-active-repo-count", type=int)
    parser.add_argument("--app-name", default="gitjob-c-archive-activity-export")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.top_n_limit < 1:
        raise SystemExit("--top-n-limit must be positive")
    result = run_job(arguments)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
