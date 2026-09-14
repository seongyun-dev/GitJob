"""Offline contract tests for the GH Archive one-hour E2E verifier."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from collector.gharchive.e2e import (
    MAX_MESSAGE_BYTES,
    digest_source_ids,
    load_offset_snapshot,
    verify_e2e,
)

HOUR = "2026-09-14T01:00:00Z"
TOPIC = "github.events"


def _event(event_id: str) -> dict[str, object]:
    return {
        "id": event_id,
        "type": "PushEvent",
        "created_at": "2026-09-14T01:04:00Z",
        "repo": {"id": 1, "name": "example/repo"},
    }


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _write_source(tmp_path: Path, event_ids: list[str]) -> Path:
    path = tmp_path / "2026-09-14-1.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for event_id in event_ids:
            stream.write(json.dumps(_event(event_id)) + "\n")
    return path


def _write_artifacts(
    tmp_path: Path,
    *,
    event_ids: list[str] | None = None,
    rejected_ids: list[str] | None = None,
    before: dict[str, int] | None = None,
    after: dict[str, int] | None = None,
    duplicate_count: int = 0,
    cron_active: bool = False,
    lag: dict[str, int] | None = None,
) -> dict[str, Path]:
    event_ids = event_ids or ["1", "2", "3"]
    rejected_ids = rejected_ids or []
    before = before or {"0": 10}
    sendable = len(event_ids) - len(rejected_ids)
    after = after or {
        partition: value + sendable + duplicate_count
        for partition, value in before.items()
    }
    source = _write_source(tmp_path, event_ids)
    watch = _write_json(
        tmp_path / "watch-checkpoint.json",
        {
            "version": 1,
            "source": "gharchive",
            "historical_start": HOUR,
            "historical_cutoff": "2027-01-01T00:00:00Z",
            "hours": {
                HOUR: {
                    "status": "complete",
                    "filename": "2026-09-14-1.json.gz",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "gzip_valid": True,
                }
            },
        },
    )
    publish = _write_json(
        tmp_path / "publish-checkpoint.json",
        {
            "topic": TOPIC,
            "published": {
                HOUR: {
                    "events": sendable,
                    "rejected": len(rejected_ids),
                    "published_at": "2026-09-14T01:20:00Z",
                }
            },
        },
    )
    progress = _write_json(
        tmp_path / "publish-progress.json", {"topic": TOPIC, "hours": {}}
    )
    rejected = tmp_path / "publish-rejected-events.jsonl"
    if rejected_ids:
        with rejected.open("w", encoding="utf-8", newline="\n") as stream:
            for event_id in rejected_ids:
                stream.write(
                    json.dumps(
                        {
                            "hour": HOUR,
                            "source_id": f"{HOUR}/{event_id}",
                            "bytes": MAX_MESSAGE_BYTES + 1,
                            "limit": MAX_MESSAGE_BYTES,
                            "reason": "EVENT_EXCEEDS_MAX_MESSAGE_BYTES",
                            "recorded_at": "2026-09-14T01:20:00Z",
                        }
                    )
                    + "\n"
                )
    else:
        rejected.write_text("", encoding="utf-8")
    kafka_before = _write_json(
        tmp_path / "kafka-before.json", {"topic": TOPIC, "partitions": before}
    )
    kafka_after = _write_json(
        tmp_path / "kafka-after.json", {"topic": TOPIC, "partitions": after}
    )
    c1 = _write_json(
        tmp_path / "c1.json",
        {
            "topic": TOPIC,
            "checkpoint_path": "hdfs:///gitjob/checkpoints/c1/github.events",
            "batch_id": 7,
            "committed": True,
            "last_commit": "2026-09-14T01:21:00Z",
            "start_offsets": before,
            "end_offsets": after,
            "lag": lag or {partition: 0 for partition in before},
        },
    )
    source_set = {f"{HOUR}/{event_id}" for event_id in event_ids}
    rejected_set = {f"{HOUR}/{event_id}" for event_id in rejected_ids}
    sendable_set = source_set - rejected_set
    readback_rows = sendable + duplicate_count
    readback = _write_json(
        tmp_path / "readback.json",
        {
            "format": "spark.parquet",
            "topic": TOPIC,
            "archive_path": "hdfs:///gitjob/parquet/stream/github.events",
            "row_count": readback_rows,
            "distinct_source_id_count": sendable,
            "duplicate_source_id_count": duplicate_count,
            "source_id_sha256": digest_source_ids(sendable_set),
            "offset_rows": {
                "0": {
                    "count": readback_rows,
                    "min": before["0"],
                    "max": after["0"] - 1,
                }
            },
            "rejected_row_count": 0,
            "rejected_source_ids": [],
            "read_only": True,
        },
    )
    cron = _write_json(
        tmp_path / "cron.json",
        {
            "active": cron_active,
            "entries": ["0 * * * * ./gharchive-watch.sh"] if cron_active else [],
        },
    )
    return {
        "source": source,
        "watch": watch,
        "publish": publish,
        "progress": progress,
        "rejected": rejected,
        "before": kafka_before,
        "after": kafka_after,
        "c1": c1,
        "readback": readback,
        "cron": cron,
    }


def _verify(artifacts: dict[str, Path]):
    return verify_e2e(
        hour=HOUR,
        source_path=artifacts["source"],
        watch_checkpoint=artifacts["watch"],
        publish_checkpoint=artifacts["publish"],
        publish_progress=artifacts["progress"],
        rejected_log=artifacts["rejected"],
        kafka_before=artifacts["before"],
        kafka_after=artifacts["after"],
        c1_snapshot=artifacts["c1"],
        parquet_readback=artifacts["readback"],
        cron_snapshot=artifacts["cron"],
    )


def _check(report, name: str):
    return next(check for check in report.checks if check.name == name)


def test_a_clean_one_hour_canary_reconciles_end_to_end(tmp_path: Path):
    report = _verify(_write_artifacts(tmp_path))

    assert report.ok
    assert _check(report, "source_to_publisher").ok
    assert _check(report, "publisher_to_kafka").ok
    assert _check(report, "kafka_to_c1").ok
    assert _check(report, "c1_to_hdfs").ok
    assert _check(report, "lag_zero").ok


def test_oversized_event_has_durable_lineage_and_is_absent_from_hdfs(tmp_path: Path):
    artifacts = _write_artifacts(
        tmp_path,
        event_ids=["1", "oversized"],
        rejected_ids=["oversized"],
    )
    report = _verify(artifacts)

    assert report.ok
    assert _check(report, "rejected_oversized_lineage").ok
    assert _check(report, "source_identity_in_hdfs").ok


def test_duplicate_replay_is_reported_but_bounded_to_one_flush_window(tmp_path: Path):
    artifacts = _write_artifacts(tmp_path, duplicate_count=2, after={"0": 15})
    report = _verify(artifacts)

    assert report.ok
    duplicate = _check(report, "duplicate_amplification")
    assert duplicate.ok
    assert duplicate.evidence["duplicate_records"] == 2


def test_nonzero_lag_fails_closed(tmp_path: Path):
    artifacts = _write_artifacts(tmp_path, lag={"0": 1})
    report = _verify(artifacts)

    assert not report.ok
    assert not _check(report, "lag_zero").ok


def test_active_cron_fails_closed(tmp_path: Path):
    report = _verify(_write_artifacts(tmp_path, cron_active=True))

    assert not report.ok
    assert not _check(report, "cron_inactive").ok


def test_duplicate_amplification_over_the_flush_window_fails(tmp_path: Path):
    artifacts = _write_artifacts(tmp_path, duplicate_count=1, after={"0": 14})
    report = verify_e2e(
        hour=HOUR,
        source_path=artifacts["source"],
        watch_checkpoint=artifacts["watch"],
        publish_checkpoint=artifacts["publish"],
        publish_progress=artifacts["progress"],
        rejected_log=artifacts["rejected"],
        kafka_before=artifacts["before"],
        kafka_after=artifacts["after"],
        c1_snapshot=artifacts["c1"],
        parquet_readback=artifacts["readback"],
        cron_snapshot=artifacts["cron"],
        max_duplicate_records=0,
    )

    assert not report.ok
    assert not _check(report, "duplicate_amplification").ok


def test_missing_artifact_fails_closed(tmp_path: Path):
    artifacts = _write_artifacts(tmp_path)
    artifacts["c1"].unlink()

    report = _verify(artifacts)

    assert not report.ok
    assert not _check(report, "c1_checkpoint_commit").ok


def test_offset_snapshot_accepts_partition_list(tmp_path: Path):
    path = _write_json(
        tmp_path / "offsets.json",
        {"topic": TOPIC, "partitions": [{"partition": 0, "offset": 12}]},
    )

    snapshot = load_offset_snapshot(path)

    assert snapshot.offsets == {"0": 12}
