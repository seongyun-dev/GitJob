"""Read the immutable Repo Activity snapshot for coverage and stratified samples."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_INPUT_ROOT = (
    "hdfs:///gitjob/parquet/github/repo_activity/period=2026-08/"
    "snapshot=s15p21e102-109-20260902"
)
DEFAULT_COVERAGE_N = (20_000, 50_000, 100_000, 200_000, 300_000, 500_000)
DEFAULT_PHASE_TOP_N = 20_000
DEFAULT_STRATA = (
    ("rank_1_100", 1, 100),
    ("around_1k", 951, 1_050),
    ("around_5k", 4_951, 5_050),
    ("around_20k", 19_951, 20_050),
    ("around_50k", 49_951, 50_050),
    ("around_100k", 99_951, 100_050),
    ("around_200k", 199_951, 200_050),
)


def parse_positive_ints(value: str) -> tuple[int, ...]:
    parts = value.split(",")
    if not parts or any(not part.strip() for part in parts):
        raise ValueError("values must be comma-separated positive integers")
    parsed = tuple(sorted({int(part.strip()) for part in parts}))
    if any(item <= 0 for item in parsed):
        raise ValueError("values must be positive")
    return parsed


def stratified_target_ranks(
    sample_size: int,
    strata: Sequence[tuple[str, int, int]] = DEFAULT_STRATA,
) -> tuple[tuple[str, int], ...]:
    if sample_size < 1:
        raise ValueError("sample size must be positive")
    if not strata:
        raise ValueError("at least one stratum is required")
    base, remainder = divmod(sample_size, len(strata))
    targets: list[tuple[str, int]] = []
    for index, (name, start, end) in enumerate(strata):
        if start < 1 or end < start:
            raise ValueError(f"invalid stratum: {name}")
        count = base + (1 if index < remainder else 0)
        if count == 0:
            continue
        width = end - start + 1
        if count > width:
            raise ValueError(f"sample exceeds stratum width: {name}")
        for item_index in range(count):
            rank = start + ((2 * item_index + 1) * width // (2 * count))
            rank = min(rank, end)
            targets.append((name, rank))
    if len({rank for _, rank in targets}) != len(targets):
        raise ValueError("stratified sample produced duplicate ranks")
    return tuple(targets)


def coverage_rows_from_counts(
    top_n_values: Sequence[int],
    selected_counts: Sequence[int],
    event_counts: Sequence[int],
    *,
    valid_event_count: int,
    total_event_count: int,
) -> list[dict[str, int | float]]:
    if not (len(top_n_values) == len(selected_counts) == len(event_counts)):
        raise ValueError("coverage input lengths must match")
    rows: list[dict[str, int | float]] = []
    previous_valid = 0.0
    previous_total = 0.0
    for top_n, selected, events in zip(top_n_values, selected_counts, event_counts):
        valid = events / valid_event_count if valid_event_count else 0.0
        total = events / total_event_count if total_event_count else 0.0
        rows.append(
            {
                "top_n": top_n,
                "selected_repo_count": selected,
                "event_count": events,
                "coverage_valid": valid,
                "coverage_total": total,
                "coverage_delta_valid": valid - previous_valid,
                "coverage_delta_total": total - previous_total,
            }
        )
        previous_valid = valid
        previous_total = total
    return rows


def deduplicate_top_n_rows(
    rows: Sequence[Mapping[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Keep the highest-priority row for each repo id/name and backfill.

    The input ``rank`` is the immutable Repo Activity priority used for
    ordering.  The returned ``rank`` is the contiguous rank of the final
    candidate list required by the Bootstrap contract.
    """

    if limit < 1:
        raise ValueError("top-n limit must be positive")

    ordered = sorted(
        rows,
        key=lambda row: (int(row["rank"]), int(row["repo_id"])),
    )
    selected: list[dict[str, Any]] = []
    seen_repo_ids: set[int] = set()
    seen_repo_names: set[str] = set()

    for row in ordered:
        repo_id = int(row["repo_id"])
        repo_name = str(row["repo_name"])
        repo_name_key = repo_name.casefold()
        if repo_id in seen_repo_ids or repo_name_key in seen_repo_names:
            continue
        selected.append(
            {
                "repo_id": repo_id,
                "repo_name": repo_name,
                "activity_count": int(row["activity_count"]),
                "rank": len(selected) + 1,
                "monthly_event_sha": row.get("monthly_event_sha"),
            }
        )
        seen_repo_ids.add(repo_id)
        seen_repo_names.add(repo_name_key)
        if len(selected) == limit:
            break

    return selected


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = SparkSession.builder.appName("gitjob-repo-fetch-candidates").getOrCreate()
    try:
        input_root = arguments.input_root.rstrip("/")
        activity = spark.read.parquet(f"{input_root}/repo_activity")
        activity_columns = set(activity.columns)

        def candidate_columns() -> list[Any]:
            columns: list[Any] = [
                "repo_id",
                "repo_name",
                "activity_count",
                "rank",
            ]
            if "monthly_event_sha" in activity_columns:
                columns.append("monthly_event_sha")
            else:
                columns.append(F.lit(None).cast("string").alias("monthly_event_sha"))
            return columns
        quality_rows = spark.read.parquet(f"{input_root}/data_quality").collect()
        if len(quality_rows) != 1:
            raise RuntimeError("data_quality must contain exactly one row")
        quality = quality_rows[0]
        valid_events = int(quality["valid_repo_event_count"])
        total_events = int(quality["total_input_events"])

        top_n_values = parse_positive_ints(arguments.coverage_n)
        aggregate_expressions = []
        for top_n in top_n_values:
            predicate = F.col("rank") <= F.lit(top_n)
            aggregate_expressions.extend(
                (
                    F.sum(
                        F.when(predicate, F.col("activity_count")).otherwise(0)
                    ).alias(f"events_{top_n}"),
                    F.sum(F.when(predicate, F.lit(1)).otherwise(0)).alias(
                        f"repos_{top_n}"
                    ),
                )
            )
        aggregate = activity.agg(*aggregate_expressions).collect()[0]
        selected_counts = [int(aggregate[f"repos_{value}"]) for value in top_n_values]
        event_counts = [int(aggregate[f"events_{value}"]) for value in top_n_values]
        coverage = coverage_rows_from_counts(
            top_n_values,
            selected_counts,
            event_counts,
            valid_event_count=valid_events,
            total_event_count=total_events,
        )

        if arguments.candidate_mode == "top-n":
            target_to_stratum = {
                rank: f"phase_top_{arguments.phase_top_n}"
                for rank in range(1, arguments.phase_top_n + 1)
            }
            initial_rows = (
                activity.where(F.col("rank") <= F.lit(arguments.phase_top_n))
                .select(*candidate_columns())
                .orderBy("rank")
                .collect()
            )
            actual_ranks = [int(row["rank"]) for row in initial_rows]
            expected_ranks = list(range(1, arguments.phase_top_n + 1))
            if actual_ranks != expected_ranks:
                raise RuntimeError(
                    "Top-N candidates must contain each contiguous rank exactly once"
                )
            raw_rows = [row.asDict() for row in initial_rows]
            selected_rows = deduplicate_top_n_rows(
                raw_rows, arguments.phase_top_n
            )
            last_source_rank = arguments.phase_top_n
            while len(selected_rows) < arguments.phase_top_n:
                backfill_rows = (
                    activity.where(F.col("rank") > F.lit(last_source_rank))
                    .select(*candidate_columns())
                    .orderBy("rank")
                    .limit(arguments.phase_top_n)
                    .collect()
                )
                if not backfill_rows:
                    raise RuntimeError(
                        "Top-N candidates could not be backfilled to the requested limit"
                    )
                raw_rows.extend(row.asDict() for row in backfill_rows)
                last_source_rank = max(int(row["rank"]) for row in backfill_rows)
                selected_rows = deduplicate_top_n_rows(
                    raw_rows, arguments.phase_top_n
                )
            rows = selected_rows
        else:
            targets = stratified_target_ranks(arguments.sample_size)
            target_to_stratum = {rank: stratum for stratum, rank in targets}
            target_ranks = sorted(target_to_stratum)
            rows = (
                activity.where(F.col("rank").isin(target_ranks))
                .select(*candidate_columns())
                .orderBy("rank")
                .collect()
            )
            if len(rows) != len(target_ranks):
                found = {int(row["rank"]) for row in rows}
                missing = [rank for rank in target_ranks if rank not in found]
                raise RuntimeError(f"missing sampled ranks: {missing}")

        return {
            "schema_version": "repo-fetch-candidates/v1",
            "generated_at": datetime.now(tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "input_root": input_root,
            "valid_repo_event_count": valid_events,
            "total_input_events": total_events,
            "coverage": coverage,
            "candidates": [
                {
                    "repo_id": int(row["repo_id"]),
                    "repo_name": str(row["repo_name"]),
                    "activity_count": int(row["activity_count"]),
                    "rank": int(row["rank"]),
                    "monthly_event_sha": row.get("monthly_event_sha"),
                    "stratum": target_to_stratum[int(row["rank"])],
                }
                for row in rows
            ],
        }
    finally:
        spark.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate extended coverage and a deterministic rank-stratified sample."
    )
    parser.add_argument("--input-root", default=DEFAULT_INPUT_ROOT)
    parser.add_argument(
        "--coverage-n",
        default=",".join(str(value) for value in DEFAULT_COVERAGE_N),
    )
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument(
        "--candidate-mode",
        choices=("stratified", "top-n"),
        default="stratified",
    )
    parser.add_argument("--phase-top-n", type=int, default=DEFAULT_PHASE_TOP_N)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.candidate_mode == "stratified" and arguments.sample_size < 1:
        raise SystemExit("--sample-size must be positive")
    if arguments.phase_top_n < 1:
        raise SystemExit("--phase-top-n must be positive")
    payload = run(arguments)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {
                "input_root": payload["input_root"],
                "coverage": payload["coverage"],
                "sample_size": len(payload["candidates"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
