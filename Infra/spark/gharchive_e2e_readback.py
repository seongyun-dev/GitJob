"""Read-only Spark readback for one GH Archive canary offset window.

This job only reads the C1 Parquet archive and its sibling rejected path.  It
does not start a streaming query and does not write HDFS.  The JSON printed to
stdout is the ``--parquet-readback`` artifact consumed by
``collector.gharchive.e2e``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from c1_archiver_stream import archive_location, rejected_location


def _load_offsets(path: Path) -> dict[str, int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid offset snapshot: {path}") from error
    if not isinstance(raw, Mapping):
        raise ValueError(f"offset snapshot must be an object: {path}")
    values = raw.get("partitions", raw.get("offsets"))
    if not isinstance(values, Mapping):
        raise ValueError(f"offset snapshot partitions must be an object: {path}")
    result: dict[str, int] = {}
    for partition, value in values.items():
        if isinstance(value, Mapping):
            value = value.get("offset", value.get("end_offset"))
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"invalid offset for partition {partition}: {path}")
        result[str(partition)] = value
    if not result:
        raise ValueError(f"offset snapshot has no partitions: {path}")
    return result


def _window_condition(
    functions: Any, before: Mapping[str, int], after: Mapping[str, int]
):
    condition = functions.lit(False)
    for partition in sorted(set(before) & set(after)):
        condition = condition | (
            (functions.col("kafka_partition") == int(partition))
            & (functions.col("kafka_offset") >= before[partition])
            & (functions.col("kafka_offset") < after[partition])
        )
    return condition


def _digest_source_ids(values: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def _rejected_source_ids(rows: Sequence[Any]) -> list[str]:
    values: list[str] = []
    for row in rows:
        raw = row["raw_value"]
        try:
            envelope = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(envelope, Mapping) and isinstance(envelope.get("source_id"), str):
            values.append(envelope["source_id"])
    return sorted(set(values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read C1 Parquet for one Kafka before/after offset window."
    )
    parser.add_argument("--topic", default="github.events")
    parser.add_argument("--parquet-root", required=True)
    parser.add_argument("--kafka-before", required=True, type=Path)
    parser.add_argument("--kafka-after", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    before = _load_offsets(arguments.kafka_before)
    after = _load_offsets(arguments.kafka_after)
    if set(before) != set(after):
        raise SystemExit("Kafka before/after partitions differ")
    if any(after[p] < before[p] for p in before):
        raise SystemExit("Kafka after offset moved backwards")

    from pyspark.sql import SparkSession, functions as F

    spark = SparkSession.builder.appName("gitjob-gharchive-e2e-readback").getOrCreate()
    try:
        accepted = spark.read.parquet(
            archive_location(arguments.topic, parquet_root=arguments.parquet_root)
        ).where(_window_condition(F, before, after))
        source_ids = [
            str(row["source_id"])
            for row in accepted.select("source_id").collect()
            if row["source_id"] is not None
        ]
        row_count = accepted.count()
        distinct_count = len(set(source_ids))
        offset_rows = {
            str(row["kafka_partition"]): {
                "count": int(row["count"]),
                "min": int(row["min_offset"]),
                "max": int(row["max_offset"]),
            }
            for row in accepted.groupBy("kafka_partition")
            .agg(
                F.count("*").alias("count"),
                F.min("kafka_offset").alias("min_offset"),
                F.max("kafka_offset").alias("max_offset"),
            )
            .collect()
        }

        rejected_rows = 0
        rejected_source_ids: list[str] = []
        try:
            rejected = spark.read.parquet(
                rejected_location(arguments.topic, parquet_root=arguments.parquet_root)
            ).where(_window_condition(F, before, after))
            rejected_rows = rejected.count()
            rejected_source_ids = _rejected_source_ids(
                rejected.select("raw_value").collect()
            )
        except Exception as error:
            # The sibling path is optional when C1 rejected no records.  Do
            # not hide permission, schema, or HDFS errors behind a zero count.
            message = str(error).lower()
            if "path does not exist" not in message and "filenotfound" not in message:
                raise
            rejected_rows = 0

        print(
            json.dumps(
                {
                    "format": "spark.parquet",
                    "topic": arguments.topic,
                    "archive_path": archive_location(
                        arguments.topic, parquet_root=arguments.parquet_root
                    ),
                    "row_count": row_count,
                    "distinct_source_id_count": distinct_count,
                    "duplicate_source_id_count": row_count - distinct_count,
                    "source_id_sha256": _digest_source_ids(source_ids),
                    "offset_rows": offset_rows,
                    "rejected_row_count": rejected_rows,
                    "rejected_source_ids": rejected_source_ids,
                    "read_only": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
