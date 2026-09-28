"""Synthetic shuffle canary for the two-host Spark cluster.

Phase 9 step 1 of S15P21E102-207. The smoke job writes Parquet but never
shuffles, so it cannot show that the two hosts exchange data. This job forces a
real exchange and touches no HDFS path, which isolates the Spark network
boundary from the storage one: if it passes, driver/executor/BlockManager
addressing works; if it fails, there is no point running the HDFS canary yet.

The result is deterministic so two runs on different cluster shapes can be
compared. Row generation and the aggregation are pure functions of --partitions
and --rows-per-partition, and the digest is taken over the aggregate in sorted
key order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
from collections.abc import Iterable, Sequence
from typing import Any


def tag_partition(rows: Iterable[Any]) -> Iterable[tuple[int, str]]:
    """Attach the executor container hostname to rows in the shuffle map stage."""

    hostname = socket.gethostname()
    for row in rows:
        yield int(row["id"]), hostname


def summarize_result(
    rows: Sequence[tuple[int, int, int, Sequence[str]]],
    *,
    total_rows: int,
    expected_groups: int,
    min_hosts: int,
) -> dict[str, object]:
    expected_sum = total_rows * (total_rows - 1) // 2
    observed_rows = sum(row_count for _, row_count, _, _ in rows)
    observed_sum = sum(id_sum for _, _, id_sum, _ in rows)
    source_hosts = sorted(
        {hostname for _, _, _, hostnames in rows for hostname in hostnames}
    )

    digest = hashlib.sha256()
    for grp, row_count, id_sum, _ in rows:
        digest.update(f"{grp}\x1f{row_count}\x1f{id_sum}\n".encode("utf-8"))

    return {
        "groups": len(rows),
        "expected_groups": expected_groups,
        "total_rows": total_rows,
        "observed_rows": observed_rows,
        "observed_id_sum": observed_sum,
        "expected_id_sum": expected_sum,
        "source_hosts": source_hosts,
        "source_host_count": len(source_hosts),
        "min_hosts": min_hosts,
        "groups_match": len(rows) == expected_groups,
        "rows_match": observed_rows == total_rows,
        "sum_match": observed_sum == expected_sum,
        "hosts_match": len(source_hosts) >= min_hosts,
        "content_sha256": digest.hexdigest(),
    }


def validation_errors(result: dict[str, object]) -> list[str]:
    checks = {
        "groups_match": "unexpected group count",
        "rows_match": "shuffle lost or duplicated rows",
        "sum_match": "shuffle changed the id sum",
        "hosts_match": "too few executor hosts participated in the shuffle map stage",
    }
    return [message for key, message in checks.items() if result[key] is not True]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partitions", type=int, default=8)
    parser.add_argument("--rows-per-partition", type=int, default=25_000)
    parser.add_argument("--groups", type=int, default=64)
    parser.add_argument("--min-hosts", type=int, default=2)
    args = parser.parse_args()
    for name in ("partitions", "rows_per_partition", "groups", "min_hosts"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.rows_per_partition < args.groups:
        parser.error(
            "--rows-per-partition must be at least --groups so every shuffle map "
            "partition contributes every key"
        )
    if args.min_hosts > args.partitions:
        parser.error("--min-hosts cannot exceed --partitions")

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = SparkSession.builder.appName("gitjob-shuffle-canary").getOrCreate()
    try:
        total_rows = args.partitions * args.rows_per_partition
        base = spark.range(0, total_rows, numPartitions=args.partitions)
        tagged = spark.createDataFrame(
            base.rdd.mapPartitions(tag_partition),
            schema="id long, source_host string",
        )

        # Every input partition contains every group key. If at least two
        # source hosts appear in collect_set below, each reducer necessarily
        # consumes map output produced on both hosts, proving a remote fetch.
        grouped = (
            tagged.withColumn("grp", F.col("id") % F.lit(args.groups))
            .groupBy("grp")
            .agg(
                F.count(F.lit(1)).alias("row_count"),
                F.sum("id").alias("id_sum"),
                F.collect_set("source_host").alias("source_hosts"),
            )
        )

        rows = sorted(
            (
                int(r["grp"]),
                int(r["row_count"]),
                int(r["id_sum"]),
                tuple(sorted(str(hostname) for hostname in r["source_hosts"])),
            )
            for r in grouped.collect()
        )
        result = summarize_result(
            rows,
            total_rows=total_rows,
            expected_groups=args.groups,
            min_hosts=args.min_hosts,
        )
        result["partitions"] = args.partitions
        print(json.dumps(result, sort_keys=True))
        errors = validation_errors(result)
        if errors:
            raise SystemExit("shuffle canary validation failed: " + "; ".join(errors))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
