"""Run the weekly snapshot publisher against a Spark run summary (S15P21E102-227).

`-225` built `publish_weekly_snapshot` and stopped there. The function had no
caller outside its tests, so the manifests and completion events it knows how
to produce could not actually be produced by anyone. This module is that
caller, and it is deliberately thin: it reads the summary the Spark job already
writes, builds the two clients, and hands off.

### What this module must not do

**It does not assemble a manifest, call `store_immutable`, or send an event.**
Every one of those decisions — the field set, the byte ordering, the read-back,
the manifest-before-event sequencing, what a `FileExistsError` means — lives in
`weekly_activity_publish`. Re-expressing any of it here would create a second
place for the contract to drift, and the drifting copy is the one C rejects.

So the whole of the work is: parse arguments, read one JSON file, construct a
`WebHdfsClient` and a Kafka transport, call one function, print what happened.

### Why the summary file is the input

`jobs/repo_activity_weekly.py` already reads every week back to verify it and
records `uri`, `row_count` and `row_digest` per week in its `output.weeks_written`
block. Passing that file is therefore not a convenience — it is how the digest
computed at write time reaches the manifest without a second pass over Parquet,
which is the split `Infra/docker/spark` and `Infra/docker/worker` force.

### Dry run

`--dry-run` resolves and validates every week, prints exactly what would be
published, and touches neither WebHDFS nor Kafka. It exists because the first
real run writes immutable objects: a typo in `--dataset-snapshot-id` becomes a
directory nobody meant to create, and `store_immutable` will not let it be
rewritten.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from common.kafka import transport_from_env
from common.webhdfs import WebHdfsClient, parse_datanode_hosts

from github.weekly_activity_publish import (
    WEEKLY_COMPLETED_TOPIC,
    WeeklyPublishError,
    build_manifest,
    manifest_uri_for,
    publish_weekly_snapshot,
    weeks_from_summary,
)

__all__ = ["build_parser", "main"]

WEBHDFS_URL_ENV = "WEBHDFS_URL"
WEBHDFS_USER_ENV = "WEBHDFS_USER"
WEBHDFS_DATANODE_HOSTS_ENV = "WEBHDFS_DATANODE_HOSTS"

# `jobs/repo_activity_weekly.py` prints one JSON object and nothing else, so a
# redirected run is a valid summary file. A truncated one is not, and a bounded
# read keeps a wrong `--summary` from being loaded as a dataset.
MAX_SUMMARY_BYTES = 8 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m github.weekly_activity_publish_cli",
        description=(
            "Publish a weekly Repo Activity snapshot: one _SUCCESS.json manifest "
            "and one completion event per week."
        ),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        required=True,
        help="the JSON `jobs/repo_activity_weekly.py` printed for this run",
    )
    parser.add_argument(
        "--dataset-snapshot-id",
        required=True,
        help="must match the `snapshot=` segment the Spark job wrote to",
    )
    parser.add_argument(
        "--webhdfs-url",
        default=os.environ.get(WEBHDFS_URL_ENV),
        help=f"WebHDFS API base including the version prefix (default: ${WEBHDFS_URL_ENV})",
    )
    parser.add_argument(
        "--webhdfs-user",
        default=os.environ.get(WEBHDFS_USER_ENV, "hadoop"),
        help=f"WebHDFS user.name (default: ${WEBHDFS_USER_ENV} or hadoop)",
    )
    parser.add_argument("--webhdfs-timeout", type=float, default=120.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print, writing nothing and sending nothing",
    )
    return parser


def _read_summary(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise SystemExit(f"summary file not found: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_SUMMARY_BYTES:
        raise SystemExit(
            f"summary file is larger than {MAX_SUMMARY_BYTES} bytes: {path}"
        )
    try:
        summary = json.loads(raw)
    except ValueError as error:
        raise SystemExit(f"summary file is not valid JSON: {error}") from error
    if not isinstance(summary, dict):
        raise SystemExit("summary file must hold a JSON object")
    return summary


def _snapshot_id_matches(dataset_snapshot_id: str, data_uri: str) -> bool:
    """The id has to be the one in the path the Spark job actually wrote to.

    `store_immutable` would otherwise publish a manifest that names a snapshot
    id the directory does not belong to, and nothing downstream would catch it
    — the bytes would be internally consistent and simply wrong.
    """

    return f"snapshot={dataset_snapshot_id}/" in f"{data_uri.rstrip('/')}/"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if not arguments.dry_run and not arguments.webhdfs_url:
        parser.error(f"--webhdfs-url is required (or set ${WEBHDFS_URL_ENV})")

    summary = _read_summary(arguments.summary)
    try:
        weeks = weeks_from_summary(summary)
    except (TypeError, ValueError) as error:
        raise SystemExit(
            f"summary does not describe published weeks: {error}"
        ) from error

    mismatched = [
        week.week_start
        for week in weeks
        if not _snapshot_id_matches(arguments.dataset_snapshot_id, week.data_uri)
    ]
    if mismatched:
        raise SystemExit(
            f"--dataset-snapshot-id {arguments.dataset_snapshot_id} does not appear in "
            f"the data_uri of week(s) {mismatched}; the summary belongs to another snapshot"
        )

    if arguments.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "dataset_snapshot_id": arguments.dataset_snapshot_id,
                    "topic": WEEKLY_COMPLETED_TOPIC,
                    "weeks": [
                        {
                            "week_start": week.week_start,
                            "manifest_uri": manifest_uri_for(week.data_uri),
                            "manifest": build_manifest(
                                arguments.dataset_snapshot_id, week
                            ),
                        }
                        for week in weeks
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    publisher = WebHdfsClient(
        arguments.webhdfs_url,
        user=arguments.webhdfs_user,
        timeout=arguments.webhdfs_timeout,
        datanode_hosts=parse_datanode_hosts(os.environ.get(WEBHDFS_DATANODE_HOSTS_ENV)),
    )
    # `None` when no broker is configured, which the publisher treats as
    # "publish the manifests, announce nothing" rather than as a failure.
    transport = transport_from_env(default_client_id="gitjob-weekly-activity")

    try:
        result = publish_weekly_snapshot(
            arguments.dataset_snapshot_id,
            weeks,
            publisher=publisher,
            transport=transport,
        )
    except WeeklyPublishError as error:
        # Includes the case where the manifest landed but the event did not:
        # the message says so, and a re-run republishes identical bytes.
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if transport is not None:
            transport.close()

    payload = result.as_dict()
    payload["dataset_snapshot_id"] = arguments.dataset_snapshot_id
    payload["broker_configured"] = transport is not None
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
