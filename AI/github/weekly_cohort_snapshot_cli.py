"""Build one week's fixed-cohort PUBLIC snapshot bundle from files on disk.

`weekly_cohort_snapshot` owns every contract decision -- which repositories are
candidates, how the week narrows their period fields, how ranks are recomputed,
what the four objects contain. This module is deliberately thin: it reads the
inputs, calls that function once, and writes or reports the result. Restating
any rule here would create a second place for the contract to drift, and the
drifting copy is the one C rejects.

### Why the activity rows arrive as a file

`Infra/docker/spark` copies only `Infra/spark`, and `Infra/docker/worker` has
no Spark or Hadoop CLI, so the process that can read a week's Parquet is not
the process that can build this bundle. The bounded export the Spark side
already produces -- `repo_id`, `event_count`, `week_start` per row -- is the
handoff, exactly as `weekly_activity_publish_cli` takes the Spark run summary
rather than re-reading Parquet.

### Why a rerun is refused instead of overwritten

The bundle is the input to an immutable publication. `store_immutable` compares
bytes and refuses a changed object under an existing name, so a second run that
silently replaced files would only move that failure later, to the point where
it is harder to read. The generator is byte-stable for the same inputs, so a
genuine rerun has nothing to write; a rerun that would write something has
different inputs and needs a different `--dataset-snapshot-id`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from github.weekly_cohort_snapshot import (
    build_weekly_cohort_publication,
    select_cohort_records,
)

MAX_INPUT_BYTES = 256 * 1024 * 1024


def _read_json(path: Path) -> object:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input exceeds the bounded read budget: " + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _cohort_source(path: Path) -> tuple[Sequence[dict], object, object]:
    """Accept a published snapshot object or a bare record array."""

    value = _read_json(path)
    records = value.get("records") if isinstance(value, dict) else value
    if not isinstance(records, list):
        raise TypeError("cohort snapshot must hold a records array: " + str(path))
    policy = value.get("collection_policy") if isinstance(value, dict) else None
    collector = value.get("collector_version") if isinstance(value, dict) else None
    return records, policy, collector


def _week_activity(path: Path, week_start: str) -> dict[int, int]:
    """Read `repo_id`/`event_count` rows and refuse anything from another week."""

    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input exceeds the bounded read budget: " + str(path))
    activity: dict[int, int] = {}
    with path.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError("activity row " + str(number) + " is not an object")
            if str(row.get("week_start")) != week_start:
                raise ValueError(
                    "activity row "
                    + str(number)
                    + " has week_start "
                    + str(row.get("week_start"))
                    + ", expected "
                    + week_start
                )
            repo_id, events = row.get("repo_id"), row.get("event_count")
            for value in (repo_id, events):
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError("activity row " + str(number) + " is not numeric")
            if repo_id in activity:
                raise ValueError("duplicate repo_id in activity rows: " + str(repo_id))
            activity[repo_id] = events
    if not activity:
        raise ValueError("activity rows must not be empty")
    return activity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one week-scoped PUBLIC snapshot bundle from durable evidence"
    )
    parser.add_argument("--week-start", required=True)
    parser.add_argument(
        "--cohort-snapshot",
        required=True,
        action="append",
        type=Path,
        help="published snapshot to draw cohort records from, most preferred first",
    )
    parser.add_argument("--week-activity", required=True, type=Path)
    parser.add_argument("--dataset-snapshot-id", required=True)
    parser.add_argument("--pipeline-run-id", required=True)
    parser.add_argument("--publication-root", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--artifact-uri-prefix",
        action="append",
        default=[],
        help="reject any artifact URI outside these namespaces",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.dry_run and arguments.output_dir is None:
        print("a destination is required: --output-dir or --dry-run", file=sys.stderr)
        return 2
    try:
        loaded = [_cohort_source(path) for path in arguments.cohort_snapshot]
        activity = _week_activity(arguments.week_activity, arguments.week_start)
        sources = [records for records, _, _ in loaded]
        policy, collector = next(
            (
                (policy, collector)
                for _, policy, collector in loaded
                if isinstance(policy, dict) and isinstance(collector, str)
            ),
            (None, None),
        )
        if policy is None:
            raise ValueError(
                "a cohort snapshot must carry collection_policy and collector_version"
            )
        publication = build_weekly_cohort_publication(
            week_start=arguments.week_start,
            cohort_records=select_cohort_records(sources),
            week_activity=activity,
            collection_policy=policy,
            collector_version=collector,
            dataset_snapshot_id=arguments.dataset_snapshot_id,
            pipeline_run_id=arguments.pipeline_run_id,
            generated_at=datetime.fromisoformat(arguments.generated_at),
            publication_root=arguments.publication_root,
            artifact_uri_prefixes=tuple(arguments.artifact_uri_prefix),
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 2

    report = {
        "week_start": publication.week_start,
        "dataset_snapshot_id": publication.dataset_snapshot_id,
        "publication_root": publication.publication_root,
        "record_count": publication.record_count,
        "objects": {
            name: len(body) for name, body in sorted(publication.files.items())
        },
    }
    if arguments.dry_run:
        print(json.dumps({**report, "status": "DRY_RUN"}, ensure_ascii=False))
        return 0
    try:
        arguments.output_dir.mkdir(parents=True)
    except FileExistsError:
        print(
            "refusing to overwrite an existing bundle directory: "
            + str(arguments.output_dir),
            file=sys.stderr,
        )
        return 1
    for name, body in publication.files.items():
        (arguments.output_dir / name).write_bytes(body)
    print(
        json.dumps(
            {**report, "status": "WRITTEN", "output_dir": str(arguments.output_dir)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
