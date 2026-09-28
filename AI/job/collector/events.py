"""Publish `jobs.collected` after a run is archived (S15P21E102-102/-103).

### Claim Check — the postings do not travel through Kafka

The run's three files stay in HDFS Raw where `raw_sink.py` put them. What goes
on the topic is the fact that a run finished and where it landed, so a
consumer fetches the bytes itself. A backfill of 4,800 postings is therefore
one message, not 4,800, which is what makes `retention.ms=-1` affordable and
leaves the S15P21E102-107 archive path untouched.

### Why this lives beside the scheduler rather than inside each collector

`schedule.execute_run` starts a collector as a subprocess, and the Raw upload
happens in there. Publishing from the scheduler keeps every site on one code
path, keeps the collector packages free of a Kafka dependency, and matches
what the event means: a *scheduled round* completed. A collector invoked by
hand — a backfill, a smoke run — is not a round and publishes nothing.

### Ordering of the two side effects

The archive happens first and the event second, always. An event that names a
Raw path the consumer cannot read is worse than a late event, so a run whose
upload failed publishes nothing and is left to S15P21E102-107's history and
alert to report.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from common.events import EventEnvelope
from common.kafka import KafkaError, KafkaTransport, transport_from_env
from job.collector.raw_sink import RAW_UPLOAD_RECORD

__all__ = [
    "COLLECTION_EVENT_TYPE",
    "JOBS_TOPIC",
    "PUBLISH_RECORD",
    "CollectionEventPublisher",
    "PublishResult",
    "build_collection_event",
    "publisher_from_env",
    "write_publish_record",
]

JOBS_TOPIC = "jobs.collected"
COLLECTION_EVENT_TYPE = "job.collection.completed"

# Written next to `raw_upload.json`, for the same reason: the run directory
# should say what happened to it without querying a broker.
PUBLISH_RECORD = "kafka_publish.json"


@dataclass(frozen=True)
class PublishResult:
    """What happened to one run's event."""

    published: bool
    topic: str = JOBS_TOPIC
    event_id: str | None = None
    # Why nothing was published. Both a deliberate skip and a broker failure
    # land here; `published` is the only success signal.
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "published": self.published,
            "topic": self.topic,
            "event_id": self.event_id,
            "reason": self.reason,
            "recorded_at": datetime.now(UTC).isoformat(),
        }


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _parse_moment(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def build_collection_event(
    record: object,
    *,
    run_dir: Path,
    ingested_at: datetime | None = None,
) -> tuple[EventEnvelope | None, str | None]:
    """Assemble the envelope, or explain why there is nothing to publish.

    Every value is copied from what the run already wrote — `RunRecord` from
    S15P21E102-107, `raw_upload.json` from the Raw sink, `manifest.json` from
    the collector. Nothing is recomputed here, so the event cannot disagree
    with the archive it points at.
    """

    pipeline_run_id = getattr(record, "pipeline_run_id", None)
    if not pipeline_run_id:
        return None, "run has no pipeline_run_id"

    upload = _read_json(run_dir / RAW_UPLOAD_RECORD)
    if upload is None:
        return None, "run was not archived to Raw"
    if upload.get("failed"):
        return None, "Raw upload reported failures"
    run_path = upload.get("run_path")
    if not isinstance(run_path, str) or not run_path:
        return None, "Raw upload record has no run_path"

    files = [
        uri
        for key in ("uploaded", "unchanged")
        for uri in (upload.get(key) or [])
        if isinstance(uri, str)
    ]

    manifest = _read_json(run_dir / "manifest.json") or {}
    finished = _parse_moment(getattr(record, "finished_at", None))
    if finished is None:
        return None, "run has no timezone-aware finished_at"

    payload: dict[str, object] = {
        "run_name": getattr(record, "run_name", None),
        "site": getattr(record, "site", None),
        "pipeline_run_id": pipeline_run_id,
        "record_count": getattr(record, "records", 0),
        "status": getattr(record, "status", None),
        "run_path": run_path,
        "files": files,
    }
    for key in ("collector_version", "dataset_snapshot_id"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            payload[key] = value

    source = str(getattr(record, "site", "") or "").strip().lower()
    if not source:
        return None, "run has no site"

    envelope = EventEnvelope(
        source=source,
        source_id=str(pipeline_run_id),
        event_type=COLLECTION_EVENT_TYPE,
        # The round's completion is the event's own time; `ingested_at` is when
        # we handed it to the broker.
        occurred_at=finished,
        ingested_at=ingested_at or datetime.now(UTC),
        payload=payload,
        # Republishing the same round must be recognisable downstream. The run
        # id is already unique per round, and the Raw sink treats a repeated
        # run id as `unchanged` rather than a new object, so the two agree.
        event_id=f"jobs-{pipeline_run_id}",
    )
    return envelope, None


@dataclass(frozen=True)
class CollectionEventPublisher:
    """Send one round's event, reporting failure instead of raising.

    The collection already happened and postings cannot be gathered again, so a
    broker outage must not turn a successful round into a failed one — the same
    rule S15P21E102-107 applies to alert delivery.
    """

    transport: KafkaTransport
    topic: str = JOBS_TOPIC

    def publish(
        self,
        record: object,
        *,
        run_dir: Path,
        ingested_at: datetime | None = None,
    ) -> PublishResult:
        envelope, skip_reason = build_collection_event(
            record, run_dir=run_dir, ingested_at=ingested_at
        )
        if envelope is None:
            return PublishResult(False, topic=self.topic, reason=skip_reason)

        # Partition by site so one site's rounds stay ordered relative to each
        # other. Ordering across sites carries no meaning.
        key = envelope.source.encode("utf-8")
        try:
            self.transport.send(self.topic, key=key, value=envelope.to_bytes())
        except KafkaError as error:
            return PublishResult(
                False,
                topic=self.topic,
                event_id=envelope.event_id,
                reason=str(error)[:400],
            )
        return PublishResult(True, topic=self.topic, event_id=envelope.event_id)


def write_publish_record(run_dir: Path, result: PublishResult) -> Path:
    """Leave a local note of whether the round was announced."""

    path = run_dir / PUBLISH_RECORD
    path.write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def publisher_from_env(
    env: Mapping[str, str] | None = None,
) -> CollectionEventPublisher | None:
    """Build a publisher, or `None` when no broker is configured.

    `KAFKA_BOOTSTRAP_SERVERS` is the switch, matching `sink_from_env`'s use of
    `WEBHDFS_URL`: a developer without a broker collects and archives as usual
    and announces nothing.
    """

    values = os.environ if env is None else env
    transport = transport_from_env(values)
    if transport is None:
        return None
    topic = (values.get("JOBS_COLLECTED_TOPIC") or JOBS_TOPIC).strip() or JOBS_TOPIC
    return CollectionEventPublisher(transport=transport, topic=topic)
