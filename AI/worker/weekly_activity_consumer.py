"""Runnable weekly Trend consumer with bounded in-process retry backoff."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from common.kafka import consumer_from_env
from common.webhdfs import parse_datanode_hosts
from github.artifact_reader import ReadOnlyWebHdfsReader
from worker.api import configured_database_url, default_registry
from worker.store import ComputeStore
from worker.weekly_activity_intake import (
    WEEKLY_COMPLETED_TOPIC,
    MountedWeeklyExportReader,
    Outcome,
    StorePublicSnapshotSelector,
    WeeklyActivityConsumer,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_RETRY_DELAY_SECONDS = 60
DEFAULT_MAX_RETRY_DELAY_SECONDS = 900
DEFAULT_STATUS_FILE = "/tmp/weekly-activity-consumer-status.json"


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return normalized == "true"


def _datanode_routes() -> dict[str, str]:
    routes = parse_datanode_hosts(os.environ.get("WEBHDFS_DATANODE_HOSTS"))
    scheme = urlsplit(os.environ["WEBHDFS_URL"]).scheme or "http"
    return {
        f"{scheme}://{source}": f"{scheme}://{target}"
        for source, target in routes.items()
    }


def _positive_seconds(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _status_path() -> Path:
    return Path(os.environ.get("WEEKLY_ACTIVITY_STATUS_FILE", DEFAULT_STATUS_FILE))


def _write_status(state: str, *, reason: str | None = None) -> None:
    value = {
        "state": state,
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if reason is not None:
        value["reason"] = reason
    path = _status_path()
    try:
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        LOGGER.error(
            "weekly activity status write failed path=%s error=%s", path, error
        )


def build_from_env() -> WeeklyActivityConsumer:
    dsn = configured_database_url()
    if not dsn:
        raise RuntimeError("C_COMPUTE_DATABASE_URL is required")
    root = Path(os.environ["C_WEEKLY_EXPORT_ROOT"])
    reader = ReadOnlyWebHdfsReader(
        os.environ["WEBHDFS_URL"],
        os.environ.get(
            "C_WEEKLY_HDFS_ROOT", "hdfs:///gitjob/parquet/github/repo_activity_weekly"
        ),
        datanode_routes=_datanode_routes(),
        user=os.environ.get("WEBHDFS_USER", "hadoop"),
    )
    store = ComputeStore(
        dsn, lease_seconds=int(os.environ.get("C_COMPUTE_LEASE_SECONDS", "120"))
    )
    registry = default_registry(dsn=dsn)
    transport = consumer_from_env(
        WEEKLY_COMPLETED_TOPIC,
        os.environ.get("WEEKLY_ACTIVITY_CONSUMER_GROUP", "gitjob-weekly-trend"),
    )
    if transport is None:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS is required")
    return WeeklyActivityConsumer(
        transport,
        store,
        MountedWeeklyExportReader(reader, root),
        StorePublicSnapshotSelector(store),
        registry,
        include_partial=_boolean("C_WEEKLY_INCLUDE_PARTIAL"),
    )


def run(
    factory: Callable[[], WeeklyActivityConsumer] = build_from_env,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    initial_delay = _positive_seconds(
        "WEEKLY_ACTIVITY_RETRY_DELAY_SECONDS", DEFAULT_RETRY_DELAY_SECONDS
    )
    max_delay = _positive_seconds(
        "WEEKLY_ACTIVITY_MAX_RETRY_DELAY_SECONDS", DEFAULT_MAX_RETRY_DELAY_SECONDS
    )
    if max_delay < initial_delay:
        raise ValueError(
            "WEEKLY_ACTIVITY_MAX_RETRY_DELAY_SECONDS must be greater than or equal "
            "to WEEKLY_ACTIVITY_RETRY_DELAY_SECONDS"
        )
    delay = initial_delay
    blocked = False
    consumer: WeeklyActivityConsumer | None = factory()
    # Invalidate a READY file left in the container's writable layer by an
    # earlier process before the first successful Kafka poll.
    _write_status("STARTING")
    try:
        while True:
            outcomes = consumer.run_once()
            if Outcome.RETRY in outcomes:
                reason = consumer.last_retry_code or "WEEKLY_ACTIVITY_RETRY"
                blocked = True
                _write_status("BLOCKED", reason=reason)
                LOGGER.warning(
                    "weekly activity consumer blocked reason=%s retry_in_seconds=%s",
                    reason,
                    delay,
                )
                # Closing and rebuilding is intentional. kafka-python advances its
                # local position after poll even without a commit; a fresh group
                # member resumes from the uncommitted offset and redelivers it.
                consumer.transport.close()
                consumer = None
                sleeper(delay)
                consumer = factory()
                delay = min(delay * 2, max_delay)
                continue
            if outcomes:
                blocked = False
                delay = initial_delay
            # Keep BLOCKED latched across empty polls after reconnect. Readiness
            # only recovers once the failed record has an explicit outcome.
            if not blocked:
                _write_status("READY")
    finally:
        if consumer is not None:
            consumer.transport.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
