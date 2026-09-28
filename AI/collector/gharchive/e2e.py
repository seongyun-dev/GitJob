"""Read-only, artifact-based verifier for the GH Archive streaming canary.

The verifier intentionally does not open Kafka, HDFS, Spark, Docker, cron, or
GH Archive.  A canary operator captures immutable snapshots first and then
passes those files here.  Keeping the checker on the artifact side makes a
failed check safe to repeat and makes an E2E result reviewable after the
production window has ended.

The required flow is:

    source gzip -> watch checkpoint -> publisher checkpoint -> Kafka offsets
    -> C1 checkpoint/commit -> Spark Parquet readback

The normalized snapshot formats are documented in
``docs/data/2026-09-14-github-streaming-e2e-canary-runbook.md``.  In
particular, a C1 checkpoint is not a Kafka consumer-group offset: C1 owns its
offset through the Spark checkpoint, so the snapshot must carry both the
checkpoint end offsets and the commit marker.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from common.kafka import MAX_MESSAGE_BYTES

GITHUB_EVENTS_TOPIC = "github.events"
REJECTION_REASON = "EVENT_EXCEEDS_MAX_MESSAGE_BYTES"
DEFAULT_MAX_DUPLICATE_RECORDS = 5_000
CRON_MARKERS = ("gharchive-watch.sh", "gharchive-publish.sh")

__all__ = [
    "ArtifactError",
    "CheckResult",
    "E2EReport",
    "OffsetSnapshot",
    "SourceSnapshot",
    "DEFAULT_MAX_DUPLICATE_RECORDS",
    "GITHUB_EVENTS_TOPIC",
    "MAX_MESSAGE_BYTES",
    "REJECTION_REASON",
    "digest_source_ids",
    "load_offset_snapshot",
    "scan_source_archive",
    "verify_e2e",
]


class ArtifactError(ValueError):
    """An input artifact is absent, malformed, or contract-incompatible."""


@dataclass(frozen=True)
class CheckResult:
    """One fail-closed check in the final report."""

    name: str
    ok: bool
    details: str
    evidence: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": "PASS" if self.ok else "FAIL",
            "details": self.details,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class E2EReport:
    """The complete canary decision."""

    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def status(self) -> str:
        return "PASS" if self.ok else "FAIL"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "checks": [check.as_dict() for check in self.checks],
            "passed": sum(check.ok for check in self.checks),
            "failed": sum(not check.ok for check in self.checks),
        }


@dataclass(frozen=True)
class SourceSnapshot:
    """Counts and identities derived from one immutable GH Archive gzip."""

    hour: str
    total_lines: int
    valid_events: int
    malformed_lines: int
    source_ids: frozenset[str]
    duplicate_source_ids: int
    compressed_sha256: str

    @property
    def source_id_sha256(self) -> str:
        return digest_source_ids(self.source_ids)


@dataclass(frozen=True)
class OffsetSnapshot:
    """A normalized Kafka before or after offset capture."""

    topic: str
    offsets: Mapping[str, int]
    raw: Mapping[str, object]

    @property
    def total(self) -> int:
        return sum(self.offsets.values())


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    if not path.is_file():
        raise ArtifactError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArtifactError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ArtifactError(f"{label} root must be a JSON object: {path}")
    return value


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactError(f"{field_name} must be a non-empty string")
    return value.strip()


def _nonnegative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactError(f"{field_name} must be a non-negative integer")
    return value


def digest_source_ids(source_ids: Sequence[str] | set[str] | frozenset[str]) -> str:
    """Hash sorted source IDs so large ID lists need not be in a report."""

    payload = "\n".join(sorted(source_ids)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_id(event: object, *, hour: str) -> str:
    if not isinstance(event, Mapping):
        raise ValueError("event is not an object")
    event_id = event.get("id")
    event_type = event.get("type")
    created_at = event.get("created_at")
    # Match build_event_envelope(): a falsy required field is malformed.
    if not event_id or not event_type or not created_at:
        raise ValueError("event is missing id, type or created_at")
    timestamp = str(created_at).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        # The publisher accepts a naive timestamp as UTC after parsing it.
        # Keep the source scanner's validity rule identical to the publisher.
        parsed = parsed.replace(tzinfo=UTC)
    return f"{hour}/{event_id}"


def scan_source_archive(path: Path, *, hour: str) -> SourceSnapshot:
    """Read one gzip line stream without changing it or calling the network."""

    if not path.is_file():
        raise ArtifactError(f"source archive is missing: {path}")
    total_lines = 0
    valid_events = 0
    malformed_lines = 0
    source_ids: set[str] = set()
    duplicate_source_ids = 0
    compressed_digest = hashlib.sha256()
    try:
        with path.open("rb") as raw_stream:
            while chunk := raw_stream.read(1024 * 1024):
                compressed_digest.update(chunk)
    except OSError as error:
        raise ArtifactError(f"source archive cannot be read: {path}") from error
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                total_lines += 1
                text = line.strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                    source_id = _source_id(event, hour=hour)
                except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                    malformed_lines += 1
                    continue
                valid_events += 1
                if source_id in source_ids:
                    duplicate_source_ids += 1
                source_ids.add(source_id)
    except (OSError, EOFError) as error:
        raise ArtifactError(f"source archive cannot be read: {path}") from error
    return SourceSnapshot(
        hour=hour,
        total_lines=total_lines,
        valid_events=valid_events,
        malformed_lines=malformed_lines,
        source_ids=frozenset(source_ids),
        duplicate_source_ids=duplicate_source_ids,
        compressed_sha256=compressed_digest.hexdigest(),
    )


def _partition_offsets(value: object, *, field_name: str) -> dict[str, int]:
    """Accept the JSON object/list forms used by the snapshot commands."""

    if isinstance(value, Mapping):
        items: list[tuple[object, object]] = list(value.items())
    elif isinstance(value, list):
        items = []
        for entry in value:
            if not isinstance(entry, Mapping):
                raise ArtifactError(f"{field_name} list entries must be objects")
            items.append((entry.get("partition"), entry.get("offset")))
    else:
        raise ArtifactError(f"{field_name} must be an object or list")

    result: dict[str, int] = {}
    for partition, value_item in items:
        if isinstance(partition, bool) or not isinstance(partition, (str, int)):
            raise ArtifactError(f"{field_name} has an invalid partition")
        key = str(partition)
        if isinstance(value_item, Mapping):
            value_item = value_item.get("offset", value_item.get("end_offset"))
        offset = _nonnegative_int(value_item, field_name=f"{field_name}[{key}]")
        if key in result:
            raise ArtifactError(f"{field_name} contains duplicate partition {key}")
        result[key] = offset
    if not result:
        raise ArtifactError(f"{field_name} must contain at least one partition")
    return result


def load_offset_snapshot(
    path: Path, *, label: str = "Kafka offset snapshot"
) -> OffsetSnapshot:
    """Load a read-only before/after offset artifact."""

    raw = _read_json(path, label=label)
    topic = _required_text(raw.get("topic"), field_name=f"{label}.topic")
    values = raw.get("partitions", raw.get("offsets"))
    offsets = _partition_offsets(values, field_name=f"{label}.partitions")
    return OffsetSnapshot(topic=topic, offsets=offsets, raw=raw)


def _load_rejected(path: Path, *, hour: str) -> tuple[dict[str, object], ...]:
    """Read the durable publisher JSONL log; an absent empty log is valid."""

    if not path.exists():
        return ()
    if not path.is_file():
        raise ArtifactError(f"rejected-event log is not a file: {path}")
    entries: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ArtifactError(f"rejected-event log cannot be read: {path}") from error
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ArtifactError(
                f"rejected-event log line {number} is invalid"
            ) from error
        if not isinstance(value, dict):
            raise ArtifactError(f"rejected-event log line {number} is not an object")
        if value.get("hour") == hour:
            entries.append(value)
    return tuple(entries)


def _load_checkpoint(path: Path, *, label: str) -> dict[str, object]:
    return _read_json(path, label=label)


def _validate_watch_checkpoint(
    raw: Mapping[str, object], *, hour: str
) -> dict[str, object]:
    if str(raw.get("source", "")).lower() != "gharchive":
        raise ArtifactError("watch checkpoint source is not gharchive")
    hours = raw.get("hours")
    if not isinstance(hours, Mapping):
        raise ArtifactError("watch checkpoint hours must be an object")
    entry = hours.get(hour)
    if not isinstance(entry, Mapping):
        raise ArtifactError(f"watch checkpoint has no entry for {hour}")
    if entry.get("status") != "complete":
        raise ArtifactError(f"watch checkpoint entry is not complete for {hour}")
    if entry.get("gzip_valid") is not True:
        raise ArtifactError(f"watch checkpoint is not gzip_valid for {hour}")
    _required_text(entry.get("filename"), field_name="watch filename")
    _required_text(entry.get("sha256"), field_name="watch sha256")
    return dict(entry)


def _validate_publisher_checkpoint(
    raw: Mapping[str, object], *, hour: str, topic: str
) -> dict[str, int | str]:
    if raw.get("topic") != topic:
        raise ArtifactError("publisher checkpoint topic does not match github.events")
    published = raw.get("published")
    if not isinstance(published, Mapping):
        raise ArtifactError("publisher checkpoint published must be an object")
    entry = published.get(hour)
    if not isinstance(entry, Mapping):
        raise ArtifactError(f"publisher checkpoint has no completed entry for {hour}")
    events = _nonnegative_int(entry.get("events"), field_name="publisher events")
    rejected = _nonnegative_int(entry.get("rejected"), field_name="publisher rejected")
    published_at = _required_text(entry.get("published_at"), field_name="published_at")
    return {"events": events, "rejected": rejected, "published_at": published_at}


def _validate_progress(
    path: Path,
    *,
    hour: str,
    publisher_complete: bool,
) -> str:
    if not path.exists():
        return "progress file is absent after a completed publish (cleared)"
    raw = _read_json(path, label="publisher progress")
    if raw.get("topic") != GITHUB_EVENTS_TOPIC:
        raise ArtifactError("publisher progress topic does not match github.events")
    hours = raw.get("hours")
    if not isinstance(hours, Mapping):
        raise ArtifactError("publisher progress hours must be an object")
    entry = hours.get(hour)
    if entry is not None and publisher_complete:
        raise ArtifactError(f"completed hour still has publisher progress: {hour}")
    return "progress file is readable and has no completed canary entry"


def _validate_c1(raw: Mapping[str, object], *, topic: str) -> dict[str, object]:
    if raw.get("topic") != topic:
        raise ArtifactError("C1 snapshot topic does not match github.events")
    _required_text(raw.get("checkpoint_path"), field_name="C1 checkpoint_path")
    if raw.get("committed") is not True:
        raise ArtifactError("C1 snapshot is not committed")
    _nonnegative_int(raw.get("batch_id"), field_name="C1 batch_id")
    _required_text(raw.get("last_commit"), field_name="C1 last_commit")
    start = _partition_offsets(raw.get("start_offsets"), field_name="C1 start_offsets")
    end = _partition_offsets(raw.get("end_offsets"), field_name="C1 end_offsets")
    if set(start) != set(end):
        raise ArtifactError("C1 start/end partitions do not match")
    if "lag" not in raw:
        raise ArtifactError("C1 snapshot must include lag for fail-closed checking")
    lag = raw["lag"]
    if isinstance(lag, Mapping):
        for partition, value in lag.items():
            _nonnegative_int(value, field_name=f"C1 lag[{partition}]")
    else:
        _nonnegative_int(lag, field_name="C1 lag")
    return {"start_offsets": start, "end_offsets": end, "lag": lag}


def _validate_readback(raw: Mapping[str, object], *, topic: str) -> dict[str, object]:
    if raw.get("topic") != topic:
        raise ArtifactError("Parquet readback topic does not match github.events")
    if raw.get("format") != "spark.parquet":
        raise ArtifactError("Parquet readback format must be spark.parquet")
    _required_text(raw.get("archive_path"), field_name="Parquet archive_path")
    row_count = _nonnegative_int(raw.get("row_count"), field_name="Parquet row_count")
    distinct = _nonnegative_int(
        raw.get("distinct_source_id_count"),
        field_name="Parquet distinct_source_id_count",
    )
    duplicate = _nonnegative_int(
        raw.get("duplicate_source_id_count"),
        field_name="Parquet duplicate_source_id_count",
    )
    if row_count - distinct != duplicate:
        raise ArtifactError(
            "Parquet duplicate count does not match row/distinct counts"
        )
    _required_text(raw.get("source_id_sha256"), field_name="Parquet source_id_sha256")
    rejected_rows = _nonnegative_int(
        raw.get("rejected_row_count"), field_name="Parquet rejected_row_count"
    )
    rejected_ids = raw.get("rejected_source_ids", [])
    if not isinstance(rejected_ids, list) or not all(
        isinstance(value, str) and value for value in rejected_ids
    ):
        raise ArtifactError("Parquet rejected_source_ids must be a string list")
    offset_rows = raw.get("offset_rows")
    if not isinstance(offset_rows, Mapping):
        raise ArtifactError("Parquet offset_rows must be an object")
    offset_count = 0
    normalized_offset_rows: dict[str, dict[str, int]] = {}
    for partition, entry in offset_rows.items():
        if not isinstance(entry, Mapping):
            raise ArtifactError(f"Parquet offset_rows[{partition}] must be an object")
        count = _nonnegative_int(
            entry.get("count"), field_name=f"Parquet offset_rows[{partition}].count"
        )
        minimum = _nonnegative_int(
            entry.get("min"), field_name=f"Parquet offset_rows[{partition}].min"
        )
        maximum = _nonnegative_int(
            entry.get("max"), field_name=f"Parquet offset_rows[{partition}].max"
        )
        if maximum < minimum:
            raise ArtifactError(f"Parquet offset_rows[{partition}] min exceeds max")
        offset_count += count
        normalized_offset_rows[str(partition)] = {
            "count": count,
            "min": minimum,
            "max": maximum,
        }
    if offset_count != row_count:
        raise ArtifactError("Parquet offset row count does not match row_count")
    return {
        "row_count": row_count,
        "distinct_source_id_count": distinct,
        "duplicate_source_id_count": duplicate,
        "source_id_sha256": str(raw["source_id_sha256"]),
        "rejected_row_count": rejected_rows,
        "rejected_source_ids": tuple(rejected_ids),
        "offset_rows": normalized_offset_rows,
    }


def _validate_cron(raw: Mapping[str, object]) -> tuple[bool, tuple[str, ...]]:
    active = raw.get("active")
    if not isinstance(active, bool):
        raise ArtifactError("cron snapshot must contain boolean active")
    entries = raw.get("entries", [])
    if not isinstance(entries, list) or not all(
        isinstance(entry, str) for entry in entries
    ):
        raise ArtifactError("cron snapshot entries must be a string list")
    matching = tuple(
        entry
        for entry in entries
        if not entry.lstrip().startswith("#")
        and any(marker in entry for marker in CRON_MARKERS)
    )
    if matching and not active:
        raise ArtifactError(
            "cron snapshot says inactive but has active GH Archive entries"
        )
    return active, matching


def _nonzero_lags(value: object, *, path: str = "snapshot") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        parent_is_lag = path.lower().endswith("lag")
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if (parent_is_lag or "lag" in str(key).lower()) and not isinstance(
                child, (Mapping, list)
            ):
                if isinstance(child, bool):
                    if child:
                        found.append(child_path)
                elif isinstance(child, (int, float)) and child != 0:
                    found.append(child_path)
                elif isinstance(child, str) and child.strip() not in {"", "0", "0.0"}:
                    found.append(child_path)
            found.extend(_nonzero_lags(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_nonzero_lags(child, path=f"{path}[{index}]"))
    return found


def _safe_load(
    checks: list[CheckResult],
    name: str,
    loader: Callable[[], Any],
) -> Any | None:
    try:
        return loader()
    except (ArtifactError, OSError) as error:
        checks.append(CheckResult(name, False, str(error)))
        return None


def verify_e2e(
    *,
    hour: str,
    source_path: Path,
    watch_checkpoint: Path,
    publish_checkpoint: Path,
    publish_progress: Path,
    rejected_log: Path,
    kafka_before: Path,
    kafka_after: Path,
    c1_snapshot: Path,
    parquet_readback: Path,
    cron_snapshot: Path,
    max_message_bytes: int = MAX_MESSAGE_BYTES,
    max_duplicate_records: int = DEFAULT_MAX_DUPLICATE_RECORDS,
) -> E2EReport:
    """Verify one canary using only local, already-captured artifacts."""

    checks: list[CheckResult] = []
    source = _safe_load(
        checks,
        "source_archive_readable",
        lambda: scan_source_archive(source_path, hour=hour),
    )
    watch = _safe_load(
        checks,
        "watch_checkpoint",
        lambda: _validate_watch_checkpoint(
            _load_checkpoint(watch_checkpoint, label="watch checkpoint"), hour=hour
        ),
    )
    publisher = _safe_load(
        checks,
        "publisher_checkpoint",
        lambda: _validate_publisher_checkpoint(
            _load_checkpoint(publish_checkpoint, label="publisher checkpoint"),
            hour=hour,
            topic=GITHUB_EVENTS_TOPIC,
        ),
    )
    progress = _safe_load(
        checks,
        "publisher_progress",
        lambda: _validate_progress(
            publish_progress,
            hour=hour,
            publisher_complete=publisher is not None,
        ),
    )
    rejected = _safe_load(
        checks,
        "rejected_log_readable",
        lambda: _load_rejected(rejected_log, hour=hour),
    )
    before = _safe_load(
        checks,
        "kafka_before_snapshot",
        lambda: load_offset_snapshot(kafka_before, label="Kafka before snapshot"),
    )
    after = _safe_load(
        checks,
        "kafka_after_snapshot",
        lambda: load_offset_snapshot(kafka_after, label="Kafka after snapshot"),
    )
    c1 = _safe_load(
        checks,
        "c1_checkpoint_commit",
        lambda: _validate_c1(
            _load_checkpoint(c1_snapshot, label="C1 snapshot"),
            topic=GITHUB_EVENTS_TOPIC,
        ),
    )
    readback = _safe_load(
        checks,
        "hdfs_parquet_readback",
        lambda: _validate_readback(
            _load_checkpoint(parquet_readback, label="Parquet readback"),
            topic=GITHUB_EVENTS_TOPIC,
        ),
    )
    cron = _safe_load(
        checks,
        "cron_inactive",
        lambda: _validate_cron(
            _load_checkpoint(cron_snapshot, label="cron snapshot")
        ),
    )

    if cron is not None:
        active, matching = cron
        checks.append(
            CheckResult(
                "cron_inactive",
                not active,
                "no GH Archive watch/publish cron is active"
                if not active
                else "GH Archive cron is active; E2E is fail-closed",
                {"active": active, "matching_entries": list(matching)},
            )
        )
    if source is not None:
        checks.append(
            CheckResult(
                "source_contract",
                source.valid_events > 0
                and source.malformed_lines == 0
                and source.duplicate_source_ids == 0,
                "source gzip contains unique, parseable events"
                if source.valid_events > 0
                and source.malformed_lines == 0
                and source.duplicate_source_ids == 0
                else "source gzip is empty, malformed, or has duplicate source IDs",
                {
                    "hour": source.hour,
                    "total_lines": source.total_lines,
                    "valid_events": source.valid_events,
                    "malformed_lines": source.malformed_lines,
                    "duplicate_source_ids": source.duplicate_source_ids,
                },
            )
        )

    if source is not None and watch is not None:
        watch_sha256 = watch.get("sha256")
        source_to_watch_ok = watch_sha256 == source.compressed_sha256
        checks.append(
            CheckResult(
                "source_to_watch",
                source_to_watch_ok,
                "watch checkpoint checksum matches the canary source archive"
                if source_to_watch_ok
                else "watch checkpoint checksum does not match the canary source "
                "archive",
                {
                    "source_sha256": source.compressed_sha256,
                    "watch_sha256": watch_sha256,
                },
            )
        )

    if before is not None and after is not None:
        same_topic = before.topic == after.topic == GITHUB_EVENTS_TOPIC
        same_partitions = set(before.offsets) == set(after.offsets)
        nonnegative = all(
            after.offsets[p] >= before.offsets[p]
            for p in before.offsets
            if p in after.offsets
        )
        delta = sum(
            after.offsets[p] - before.offsets[p]
            for p in before.offsets
            if p in after.offsets
        )
        checks.append(
            CheckResult(
                "kafka_offset_delta",
                same_topic and same_partitions and nonnegative,
                "Kafka before/after snapshots are monotonic for github.events"
                if same_topic and same_partitions and nonnegative
                else "Kafka offset snapshot changed topic/partition or moved backwards",
                {
                    "topic": after.topic,
                    "delta": delta,
                    "partitions": len(after.offsets),
                },
            )
        )

    if source is not None and publisher is not None and rejected is not None:
        rejection_ids: list[str] = []
        rejection_valid = True
        for entry in rejected:
            source_id = entry.get("source_id")
            bytes_value = entry.get("bytes")
            limit = entry.get("limit")
            reason = entry.get("reason")
            try:
                if not isinstance(source_id, str) or not source_id:
                    raise ArtifactError("rejected source_id is missing")
                if source_id not in source.source_ids:
                    raise ArtifactError(
                        f"rejected source_id is absent from source: {source_id}"
                    )
                if source_id in rejection_ids:
                    raise ArtifactError(f"duplicate rejected source_id: {source_id}")
                if not isinstance(bytes_value, int) or bytes_value <= max_message_bytes:
                    raise ArtifactError(
                        f"rejected bytes is not above {max_message_bytes}: {source_id}"
                    )
                if limit != max_message_bytes or reason != REJECTION_REASON:
                    raise ArtifactError(
                        f"rejected lineage contract mismatch: {source_id}"
                    )
                rejection_ids.append(source_id)
            except ArtifactError:
                rejection_valid = False
                break
        c1_rejected_overlap = (
            set(rejection_ids) & set(readback["rejected_source_ids"])
            if readback is not None
            else set()
        )
        rejected_count_matches = len(rejected) == publisher["rejected"]
        checks.append(
            CheckResult(
                "rejected_oversized_lineage",
                rejection_valid and rejected_count_matches and not c1_rejected_overlap,
                "every oversized event has durable, source-locatable lineage"
                if rejection_valid
                and rejected_count_matches
                and not c1_rejected_overlap
                else "oversized rejection lineage is missing, duplicated, or "
                "inconsistent",
                {
                    "source_rejected": len(rejected),
                    "publisher_rejected": publisher["rejected"],
                    "source_ids": rejection_ids[:10],
                    "c1_rejected_overlap": sorted(c1_rejected_overlap),
                },
            )
        )

    if publisher is not None and progress is not None:
        checks.append(CheckResult("publisher_resume_state", True, str(progress)))

    expected_published: int | None = None
    expected_digest: str | None = None
    if source is not None and publisher is not None and rejected is not None:
        rejection_ids = {
            str(entry["source_id"])
            for entry in rejected
            if isinstance(entry.get("source_id"), str)
        }
        expected_published = source.valid_events - len(rejection_ids)
        expected_digest = digest_source_ids(source.source_ids - rejection_ids)
        source_publisher_ok = (
            publisher["events"] == expected_published
            and expected_published == len(source.source_ids - rejection_ids)
        )
        checks.append(
            CheckResult(
                "source_to_publisher",
                source_publisher_ok,
                "publisher checkpoint equals source-valid minus durable rejections"
                if source_publisher_ok
                else "source and publisher counts/identity sets do not reconcile",
                {
                    "source_valid": source.valid_events,
                    "publisher_events": publisher["events"],
                    "publisher_rejected": len(rejection_ids),
                    "expected_published": expected_published,
                    "expected_source_id_sha256": expected_digest,
                },
            )
        )

    if before is not None and after is not None and publisher is not None:
        kafka_delta = sum(
            after.offsets[partition] - before.offsets[partition]
            for partition in before.offsets
            if partition in after.offsets
        )
        checks.append(
            CheckResult(
                "publisher_to_kafka",
                kafka_delta >= publisher["events"],
                "Kafka delta contains at least the publisher's acknowledged events"
                if kafka_delta >= publisher["events"]
                else "Kafka delta is smaller than publisher acknowledged events",
                {"kafka_delta": kafka_delta, "publisher_events": publisher["events"]},
            )
        )
    else:
        kafka_delta = None

    if c1 is not None and before is not None and after is not None:
        start = c1["start_offsets"]
        end = c1["end_offsets"]
        c1_offsets_ok = start == dict(before.offsets) and end == dict(after.offsets)
        checks.append(
            CheckResult(
                "kafka_to_c1",
                c1_offsets_ok,
                "C1 checkpoint covers exactly the Kafka canary offset window"
                if c1_offsets_ok
                else "C1 checkpoint start/end offsets do not match Kafka snapshots",
                {"start_offsets": start, "end_offsets": end},
            )
        )

    if readback is not None and before is not None and after is not None:
        offset_window_ok = True
        for partition, entry in readback["offset_rows"].items():
            if partition not in before.offsets or partition not in after.offsets:
                offset_window_ok = False
                break
            if (
                entry["min"] < before.offsets[partition]
                or entry["max"] >= after.offsets[partition]
            ):
                offset_window_ok = False
                break
        checks.append(
            CheckResult(
                "parquet_offset_window",
                offset_window_ok,
                "Parquet rows are inside the captured Kafka offset window"
                if offset_window_ok
                else "Parquet readback contains rows outside the Kafka canary window",
                {"partitions": sorted(readback["offset_rows"])},
            )
        )

    if readback is not None and c1 is not None:
        readback_ok = (
            readback["rejected_row_count"] == 0
            and readback["row_count"]
            == readback["distinct_source_id_count"]
            + readback["duplicate_source_id_count"]
        )
        checks.append(
            CheckResult(
                "c1_to_hdfs",
                readback_ok,
                "C1 committed records are present in the actual Parquet readback"
                if readback_ok
                else "Parquet readback contains C1 rejects or inconsistent row counts",
                {
                    "parquet_rows": readback["row_count"],
                    "parquet_distinct_source_ids": readback["distinct_source_id_count"],
                    "parquet_rejected_rows": readback["rejected_row_count"],
                },
            )
        )

    if (
        expected_published is not None
        and expected_digest is not None
        and readback is not None
    ):
        identity_ok = (
            readback["distinct_source_id_count"] == expected_published
            and readback["source_id_sha256"] == expected_digest
        )
        checks.append(
            CheckResult(
                "source_identity_in_hdfs",
                identity_ok,
                "Parquet source IDs equal the source sendable identity set"
                if identity_ok
                else "Parquet source ID count or digest differs from source "
                "sendable IDs",
                {
                    "expected_count": expected_published,
                    "actual_distinct_count": readback["distinct_source_id_count"],
                    "expected_sha256": expected_digest,
                    "actual_sha256": readback["source_id_sha256"],
                },
            )
        )

    if (
        kafka_delta is not None
        and readback is not None
        and expected_published is not None
    ):
        duplicate_count = readback["duplicate_source_id_count"]
        duplicate_matches_offsets = duplicate_count == kafka_delta - expected_published
        bounded = duplicate_count <= max_duplicate_records
        checks.append(
            CheckResult(
                "duplicate_amplification",
                duplicate_matches_offsets and bounded,
                "duplicate replay is absent or bounded to one 5,000-event flush window"
                if duplicate_matches_offsets and bounded
                else "duplicate amplification exceeds the configured bounded window",
                {
                    "kafka_delta": kafka_delta,
                    "unique_source_events": expected_published,
                    "duplicate_records": duplicate_count,
                    "max_duplicate_records": max_duplicate_records,
                    "amplification_ratio": (
                        round(kafka_delta / expected_published, 6)
                        if expected_published
                        else 0.0
                    ),
                },
            )
        )

    lag_paths: list[str] = []
    if before is not None:
        lag_paths.extend(_nonzero_lags(before.raw, path="kafka.before"))
    if after is not None:
        lag_paths.extend(_nonzero_lags(after.raw, path="kafka.after"))
    if c1 is not None:
        lag_paths.extend(_nonzero_lags(c1["lag"], path="c1.lag"))
    if before is not None or after is not None or c1 is not None:
        checks.append(
            CheckResult(
                "lag_zero",
                not lag_paths,
                "all captured lag values are zero"
                if not lag_paths
                else "non-zero lag is present; E2E is fail-closed",
                {"nonzero_lags": lag_paths},
            )
        )

    return E2EReport(tuple(checks))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m collector.gharchive.e2e",
        description=(
            "Verify one GH Archive streaming canary from captured artifacts. "
            "This command is read-only and never contacts production."
        ),
    )
    parser.add_argument(
        "--hour", required=True, help="UTC hour, e.g. 2026-09-14T01:00:00Z"
    )
    parser.add_argument(
        "--source", required=True, type=Path, help="one local GH Archive .json.gz"
    )
    parser.add_argument("--watch-checkpoint", required=True, type=Path)
    parser.add_argument("--publish-checkpoint", required=True, type=Path)
    parser.add_argument("--publish-progress", required=True, type=Path)
    parser.add_argument("--rejected-log", required=True, type=Path)
    parser.add_argument("--kafka-before", required=True, type=Path)
    parser.add_argument("--kafka-after", required=True, type=Path)
    parser.add_argument("--c1-snapshot", required=True, type=Path)
    parser.add_argument("--parquet-readback", required=True, type=Path)
    parser.add_argument("--cron-snapshot", required=True, type=Path)
    parser.add_argument("--max-message-bytes", type=int, default=MAX_MESSAGE_BYTES)
    parser.add_argument(
        "--max-duplicate-records",
        type=int,
        default=DEFAULT_MAX_DUPLICATE_RECORDS,
        help="fail when duplicate source rows exceed the bounded retry window",
    )
    parser.add_argument(
        "--pretty", action="store_true", help="pretty-print the JSON report"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.max_message_bytes <= 0:
        raise SystemExit("--max-message-bytes must be positive")
    if arguments.max_duplicate_records < 0:
        raise SystemExit("--max-duplicate-records must be non-negative")
    report = verify_e2e(
        hour=arguments.hour,
        source_path=arguments.source,
        watch_checkpoint=arguments.watch_checkpoint,
        publish_checkpoint=arguments.publish_checkpoint,
        publish_progress=arguments.publish_progress,
        rejected_log=arguments.rejected_log,
        kafka_before=arguments.kafka_before,
        kafka_after=arguments.kafka_after,
        c1_snapshot=arguments.c1_snapshot,
        parquet_readback=arguments.parquet_readback,
        cron_snapshot=arguments.cron_snapshot,
        max_message_bytes=arguments.max_message_bytes,
        max_duplicate_records=arguments.max_duplicate_records,
    )
    print(
        json.dumps(
            report.as_dict(),
            ensure_ascii=False,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
        )
    )
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
