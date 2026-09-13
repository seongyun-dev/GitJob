"""Runnable weekly Trend consumer; RETRY exits so Kafka redelivers on restart."""

from __future__ import annotations

import os
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


def main() -> int:
    consumer = build_from_env()
    try:
        while True:
            outcomes = consumer.run_once()
            if Outcome.RETRY in outcomes:
                return 75
    finally:
        consumer.transport.close()


if __name__ == "__main__":
    raise SystemExit(main())
