"""Small deterministic PySpark job used to validate the data profile."""

from __future__ import annotations

import argparse
import json

from pyspark.sql import SparkSession


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--worker-count", required=True, type=int)
    parser.add_argument("--dataset-multiplier", type=int, default=1)
    parser.add_argument("--rows-per-multiplier", type=int, default=3)
    args = parser.parse_args()
    if args.dataset_multiplier < 1 or args.rows_per_multiplier < 1:
        parser.error("dataset and row multipliers must be positive")

    spark = SparkSession.builder.appName("gitjob-parquet-smoke").getOrCreate()
    technologies = ("gitjob", "spark", "hdfs")
    row_count_target = args.dataset_multiplier * args.rows_per_multiplier
    rows = [
        (
            args.dataset_id,
            ordinal,
            technologies[(ordinal - 1) % len(technologies)],
        )
        for ordinal in range(1, row_count_target + 1)
    ]
    frame = spark.createDataFrame(rows, ["dataset_id", "ordinal", "technology"])
    row_count = frame.count()
    frame.write.mode("overwrite").parquet(args.output)

    print(
        json.dumps(
            {
                "dataset_id": args.dataset_id,
                "row_count": row_count,
                "spark_version": spark.version,
                "worker_count": args.worker_count,
                "output": args.output,
                "dataset_multiplier": args.dataset_multiplier,
                "rows_per_multiplier": args.rows_per_multiplier,
            },
            sort_keys=True,
        )
    )
    spark.stop()


if __name__ == "__main__":
    main()
