"""Command-line entrypoint for bounded GH Archive historical acquisition."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from collector.gharchive.events import (
    GITHUB_EVENTS_TOPIC,
    publisher_from_env,
)
from collector.gharchive.historical import (
    DEFAULT_BASE_URL,
    DEFAULT_OUTPUT_ROOT,
    HISTORICAL_CUTOFF,
    HISTORICAL_START,
    CheckpointError,
    HistoricalDownloader,
    RangeValidationError,
    expected_archives,
    format_utc_hour,
    parse_utc_hour,
    validate_downloaded_range,
)
from collector.gharchive.sinks import (
    DEFAULT_RAW_ROOT,
    DEFAULT_WEBHDFS_USER,
    HdfsSinkError,
    WebHdfsSink,
    publish_downloaded_range,
)
from collector.gharchive.watch import (
    DEFAULT_PUBLICATION_LAG,
    UNPUBLISHED_GRACE,
    GhArchiveWatcher,
)

WEBHDFS_URL_ENV = "WEBHDFS_URL"
KAFKA_BOOTSTRAP_ENV = "KAFKA_BOOTSTRAP_SERVERS"
RAW_ROOT_ENV = "RAW_ROOT"
WEBHDFS_USER_ENV = "WEBHDFS_USER"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m collector.gharchive",
        description="Download immutable GH Archive UTC-hour files with resume safety.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="print the requested hour plan")
    _add_range_arguments(plan_parser)

    download_parser = subparsers.add_parser(
        "download",
        help="download and validate hourly Raw archives",
    )
    _add_range_arguments(download_parser)
    _add_output_arguments(download_parser)
    download_parser.add_argument("--timeout", type=float, default=30.0)
    download_parser.add_argument("--max-attempts", type=int, default=3)
    download_parser.add_argument("--backoff-seconds", type=float, default=1.0)

    validate_parser = subparsers.add_parser(
        "validate",
        help="validate expected files and report missing UTC hours",
    )
    _add_range_arguments(validate_parser)
    _add_output_arguments(validate_parser)

    upload_parser = subparsers.add_parser(
        "upload",
        help="publish locally validated archives into HDFS Raw over WebHDFS",
    )
    _add_range_arguments(upload_parser)
    _add_output_arguments(upload_parser)
    upload_parser.add_argument(
        "--webhdfs-url",
        default=os.environ.get(WEBHDFS_URL_ENV),
        help=(
            "WebHDFS API base including the version prefix, for example "
            f"http://hdfs-namenode:9870/webhdfs/v1 (default: ${WEBHDFS_URL_ENV})"
        ),
    )
    upload_parser.add_argument(
        "--raw-root",
        default=os.environ.get(RAW_ROOT_ENV, DEFAULT_RAW_ROOT),
        help=f"HDFS Raw root (default: ${RAW_ROOT_ENV} or {DEFAULT_RAW_ROOT})",
    )
    upload_parser.add_argument(
        "--webhdfs-user",
        default=os.environ.get(WEBHDFS_USER_ENV, DEFAULT_WEBHDFS_USER),
        help=f"WebHDFS user.name (default: ${WEBHDFS_USER_ENV} or {DEFAULT_WEBHDFS_USER})",
    )
    upload_parser.add_argument("--timeout", type=float, default=120.0)
    watch_parser = subparsers.add_parser(
        "watch",
        help="download hours published after the bootstrap cutoff",
    )
    _add_output_arguments(watch_parser)
    watch_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    watch_parser.add_argument(
        "--lag-minutes",
        type=int,
        default=int(DEFAULT_PUBLICATION_LAG.total_seconds() // 60),
        help=(
            "hold back an hour this long after it ends. GH Archive served a "
            "just-ended hour 17 minutes late in measurement (2026-09-09)"
        ),
    )
    watch_parser.add_argument(
        "--grace-hours",
        type=int,
        default=int(UNPUBLISHED_GRACE.total_seconds() // 3600),
        help="how long a 404 stays 'not yet published' before it is a gap",
    )

    publish_parser = subparsers.add_parser(
        "publish",
        help=f"publish downloaded hours to {GITHUB_EVENTS_TOPIC}",
    )
    _add_output_arguments(publish_parser)
    publish_parser.add_argument(
        "--topic",
        default=GITHUB_EVENTS_TOPIC,
        help=f"Kafka topic (default: {GITHUB_EVENTS_TOPIC})",
    )
    publish_parser.add_argument(
        "--publish-checkpoint",
        default=None,
        help=(
            "file recording which hours reached the broker; separate from the "
            "download checkpoint on purpose (see events.py)"
        ),
    )
    publish_parser.add_argument(
        "--max-hours",
        type=int,
        default=None,
        help=(
            "publish at most this many hours in one pass. The first watch run "
            "after the bootstrap cutoff fills every hour since it, which was "
            "over 200 on 2026-09-09; the checkpoint lets the next pass "
            "continue where this one stopped"
        ),
    )
    publish_parser.add_argument(
        "--hours",
        default=None,
        help=(
            "comma-separated UTC hours to publish; omit to publish every hour "
            "found on disk, oldest first"
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "watch":
            # The watcher derives its own range from the clock, so the
            # bootstrap range arguments do not apply and are not parsed.
            watcher = GhArchiveWatcher(
                Path(arguments.output_root),
                checkpoint_path=(
                    Path(arguments.checkpoint)
                    if arguments.checkpoint is not None
                    else None
                ),
                base_url=arguments.base_url,
                lag=timedelta(minutes=arguments.lag_minutes),
                grace=timedelta(hours=arguments.grace_hours),
            )
            watch = watcher.poll()
            _print_json(watch.as_dict())
            return 0 if watch.ok else 1

        if arguments.command == "publish":
            # Like `watch`, this is driven by what is on disk rather than by a
            # requested range, so the bootstrap range arguments do not apply.
            publisher = publisher_from_env(
                Path(arguments.output_root),
                checkpoint_path=(
                    Path(arguments.publish_checkpoint)
                    if arguments.publish_checkpoint is not None
                    else None
                ),
                topic=arguments.topic,
            )
            if publisher is None:
                # Not configured is not a failure, the same rule the Raw sink
                # and the alert webhook follow.
                _print_json(
                    {
                        "topic": arguments.topic,
                        "published_hours": [],
                        "reason": f"{KAFKA_BOOTSTRAP_ENV} 미설정",
                    }
                )
                return 0
            hours = (
                tuple(
                    value.strip()
                    for value in arguments.hours.split(",")
                    if value.strip()
                )
                if arguments.hours
                else publisher.downloaded_hours_on_disk()
            )
            summary = publisher.publish_hours(hours, max_hours=arguments.max_hours)
            _print_json(summary.as_dict())
            return 0 if summary.ok else 1

        start, end, historical_start, historical_cutoff = _parsed_range(arguments)
        if arguments.command == "plan":
            archives = expected_archives(
                start,
                end,
                historical_start=historical_start,
                historical_cutoff=historical_cutoff,
                base_url=arguments.base_url,
            )
            payload: dict[str, object] = {
                "historical_start": format_utc_hour(historical_start),
                "historical_cutoff": format_utc_hour(historical_cutoff),
                "requested_start": format_utc_hour(start),
                "requested_end": format_utc_hour(end),
                "expected_files": len(archives),
                "first_filename": archives[0].filename,
                "last_filename": archives[-1].filename,
            }
            _print_json(payload)
            return 0

        output_root = Path(arguments.output_root)
        if arguments.command == "download":
            downloader = HistoricalDownloader(
                output_root,
                checkpoint_path=(
                    Path(arguments.checkpoint)
                    if arguments.checkpoint is not None
                    else None
                ),
                timeout=arguments.timeout,
                max_attempts=arguments.max_attempts,
                backoff_seconds=arguments.backoff_seconds,
                base_url=arguments.base_url,
            )
            summary = downloader.download(
                start,
                end,
                historical_start=historical_start,
                historical_cutoff=historical_cutoff,
            )
            _print_json(summary.as_dict())
            return 0 if not summary.failed and not summary.missing else 1

        if arguments.command == "upload":
            if not arguments.webhdfs_url:
                raise ValueError(
                    "WebHDFS endpoint is required: pass --webhdfs-url or set "
                    f"{WEBHDFS_URL_ENV}"
                )
            sink = WebHdfsSink(
                base_url=arguments.webhdfs_url,
                raw_root=arguments.raw_root,
                user=arguments.webhdfs_user,
                timeout=arguments.timeout,
            )
            publish = publish_downloaded_range(
                sink,
                output_root,
                start,
                end,
                historical_start=historical_start,
                historical_cutoff=historical_cutoff,
                archive_base_url=arguments.base_url,
            )
            _print_json(publish.as_dict())
            if publish.missing or publish.invalid or publish.failed:
                return 1
            return 0

        summary = validate_downloaded_range(
            output_root,
            start,
            end,
            historical_start=historical_start,
            historical_cutoff=historical_cutoff,
            base_url=arguments.base_url,
        )
        _print_json(summary.as_dict())
        return 0 if not summary.missing and not summary.invalid else 1
    except (CheckpointError, HdfsSinkError, RangeValidationError, ValueError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return 2


def _add_range_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--start",
        default=format_utc_hour(HISTORICAL_START),
        help="inclusive requested UTC hour",
    )
    parser.add_argument(
        "--end",
        default=format_utc_hour(HISTORICAL_CUTOFF),
        help="exclusive requested UTC hour",
    )
    parser.add_argument(
        "--historical-start",
        default=format_utc_hour(HISTORICAL_START),
        help="inclusive bootstrap lower bound",
    )
    parser.add_argument(
        "--historical-cutoff",
        default=format_utc_hour(HISTORICAL_CUTOFF),
        help="exclusive bootstrap cutoff shared with the online collector",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--checkpoint")


def _parsed_range(
    arguments: argparse.Namespace,
) -> tuple[datetime, datetime, datetime, datetime]:
    return (
        parse_utc_hour(arguments.start),
        parse_utc_hour(arguments.end),
        parse_utc_hour(arguments.historical_start),
        parse_utc_hour(arguments.historical_cutoff),
    )


def _print_json(
    payload: Mapping[str, object],
    *,
    stream: TextIO | None = None,
) -> None:
    """Resolve the stream at call time so a redirected stdout is honoured."""

    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream or sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
