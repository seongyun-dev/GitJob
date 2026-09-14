"""CLI for `job.collector.backfill` (S15P21E102-220 follow-up).

    python -m job.collector.backfill_cli --dry-run
    python -m job.collector.backfill_cli --source saramin
    python -m job.collector.backfill_cli --checkpoint ../data/analysis_input_backfill.json

`--dry-run` is the default posture, not a flag to remember: this walks Raw and
reports what it *would* publish, including the byte total, and writes nothing.
Publishing needs `--execute`, so a mistyped command costs a listing rather than
an unplanned write to `analysis_input`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from job.collector.analysis_input import publisher_from_env
from job.collector.backfill import (
    DEFAULT_SOURCES,
    BackfillCheckpoint,
    backfill_runs,
    discover_raw_runs,
)
from job.collector.raw_sink import sink_from_env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m job.collector.backfill_cli",
        description="Publish runs already in HDFS Raw to analysis_input.",
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        choices=list(DEFAULT_SOURCES),
        help="restrict to one source; repeat for several (default: all four)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually publish. Without it this is a dry run that writes nothing",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="resume file; a run recorded here is skipped",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many runs, for a canary pass",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the machine-readable summary instead of the table",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)

    publisher = publisher_from_env()
    sink = sink_from_env()
    if publisher is None or sink is None:
        raise SystemExit(
            "WEBHDFS_URL is not set; this command needs the operational NameNode"
        )

    sources = tuple(arguments.sources or DEFAULT_SOURCES)
    runs = discover_raw_runs(sink.client, sources=sources, raw_root=sink.raw_root)
    if arguments.limit is not None:
        runs = runs[: max(arguments.limit, 0)]

    checkpoint_path = Path(arguments.checkpoint) if arguments.checkpoint else None
    summary = backfill_runs(
        runs,
        reader=sink.client,
        publisher=publisher,
        checkpoint=BackfillCheckpoint.load(checkpoint_path),
        dry_run=not arguments.execute,
    )

    if arguments.json:
        print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))
        return 0 if summary.ok else 1

    counts = summary.as_dict()["counts"]
    mode = "EXECUTE" if arguments.execute else "DRY RUN"
    print(f"[{mode}] runs discovered: {len(runs)}")
    for state in sorted(counts):
        print(f"  {state:<20} {counts[state]}")
    for outcome in summary.outcomes:
        if outcome.state in {"BLOCKED", "FAILED"}:
            print(
                f"  - {outcome.run.key} {outcome.state}: {', '.join(outcome.detail)}"
            )
    return 0 if summary.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
