"""Deterministic content digest for a Parquet dataset.

Parquet files are not byte-reproducible across runs: part filenames carry a
random UUID, the footer records a `created_by` build string, and row groups may
be laid out differently by partition count. Comparing `hdfs dfs -checksum`
between two runs of the same job therefore reports a difference even when the
data is identical.

This job digests the *contents* instead. The ordered Spark schema and every row
as canonical JSON are length-framed before hashing, so types, nulls, escaping,
and field boundaries remain distinct while physical Parquet layout is ignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable


DIGEST_FORMAT = "typed-json-v2"
JSON_OPTIONS = {
    "ignoreNullFields": "false",
    "dateFormat": "yyyy-MM-dd",
    "timestampFormat": "yyyy-MM-dd'T'HH:mm:ss.SSSXXX",
    "timeZone": "UTC",
}


def _update_framed(digest: "hashlib._Hash", payload: str) -> None:
    encoded = payload.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
    digest.update(encoded)


def _content_digest_in_order(schema_json: str, rows: Iterable[str]) -> str:
    digest = hashlib.sha256()
    _update_framed(digest, DIGEST_FORMAT)
    _update_framed(digest, schema_json)
    for row in rows:
        _update_framed(digest, row)
    return digest.hexdigest()


def content_digest(schema_json: str, rows: Iterable[str]) -> str:
    # Compatibility API for callers that provide an unordered iterable.
    return _content_digest_in_order(schema_json, sorted(rows))


def content_digest_ordered(schema_json: str, rows: Iterable[str]) -> str:
    # Digest an iterable already globally ordered by canonical row text.
    return _content_digest_in_order(schema_json, rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument(
        "--max-rows",
        type=int,
        default=1_000_000,
        help="refuse datasets larger than this so a digest never streams a full table",
    )
    args = parser.parse_args()
    if args.max_rows < 1:
        parser.error("--max-rows must be positive")

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = SparkSession.builder.appName("gitjob-dataset-digest").getOrCreate()
    try:
        spark.conf.set("spark.sql.session.timeZone", "UTC")
        frame = spark.read.parquet(args.input)
        row_count = frame.count()
        if row_count > args.max_rows:
            raise SystemExit(
                f"dataset has {row_count} rows, above --max-rows {args.max_rows}"
            )

        columns = sorted(frame.columns)
        ordered = frame.select(*[F.col(name) for name in columns])
        schema_json = ordered.schema.json()
        rendered = ordered.select(
            F.to_json(
                F.struct(*[F.col(name).alias(name) for name in columns]),
                options=JSON_OPTIONS,
            ).alias("row")
        )
        canonical_rows = [str(item["row"]) for item in rendered.collect()]

        print(
            json.dumps(
                {
                    "input": args.input,
                    "row_count": row_count,
                    "columns": columns,
                    "digest_format": DIGEST_FORMAT,
                    "schema_sha256": hashlib.sha256(
                        schema_json.encode("utf-8")
                    ).hexdigest(),
                    "content_sha256": content_digest(schema_json, canonical_rows),
                },
                sort_keys=True,
            )
        )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
