"""Publish downloaded GH Archive hours to `github.events` (S15P21E102-144).

`-144` landed detection, download and the cursor and deliberately stopped
short of publishing: `github.events` did not exist, and its partition count
was still open in `-102` (checklist ⑤). The topic now exists at 6 partitions
(`Infra/scripts/kafka-topics.sh`, `-108`), so this is the other half.
`WatchSummary.downloaded` is the seam it reads.

### One message per event, not per hour

S15P21E102-102 §2.1 and §4.2 settle this, and it is worth restating because
the alternative looks cheaper:

    | source      | occurred_at        | source_id            | payload   |
    | gharchive   | event's created_at | hourly file + event id | 원문 event |

So the payload is the **event**, not a pointer to the file. That is the
opposite of `jobs.collected`, which carries a Claim Check because job
postings live in HDFS and must not be duplicated into Kafka. Here the raw
event *is* what C1 archives and C2 extracts from, and `retention.ms=-1` makes
the topic the replay log — §5's "되감기가 설계 근거".

The volume follows from that. `-105` measured 87,516,869 events over 744
hours, about 117,600 an hour on average; one measured hour (2026-09-01T00Z)
held 51,582. An event serializes to roughly 1.3 KB with the envelope.

### Two consequences that shaped this module

**Per-message acknowledgement is not usable.** `KafkaTransport.send` blocks
for each message, which is right for four-a-day `jobs.collected`. At 117,600
an hour it would make publishing slower than downloading, so this uses
`send_many`: enqueue, flush once, then check every future. Durability is
unchanged — the broker has acknowledged everything before a batch returns.

**An hour is published all-or-nothing.** The checkpoint records an hour only
after its whole file went out. A failure part-way therefore leaves the hour
unrecorded and the next run sends it again, producing duplicates for the part
that already landed. That is the intended trade: `-102` §4.1 makes
`(source, source_id, schema_version)` the consumer-side dedup key precisely so
a re-send is absorbed, and losing events is worse than repeating them.

### The publish checkpoint is separate from the download checkpoint

`watch-checkpoint.json` says what is on disk; `publish-checkpoint.json` says
what reached the broker. Merging them would mean a broker outage either
re-downloads everything or silently skips publishing — the same reason
S15P21E102-174 moved the collectors' cursor behind their outputs.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from collector.gharchive.historical import (
    SOURCE,
    RangeValidationError,
    archive_for_hour,
    format_utc_hour,
    parse_utc_hour,
)
from common.events import EventEnvelope
from common.kafka import KafkaError, KafkaTransport, transport_from_env

__all__ = [
    "GITHUB_EVENTS_TOPIC",
    "GhArchiveEventPublisher",
    "HourPublishResult",
    "PublishCheckpoint",
    "PublishSummary",
    "build_event_envelope",
    "iter_hour_messages",
    "publisher_from_env",
]

# The name from `docs/data/README.md` §4, carried unchanged through -102 §2.1.
# Not `gitjob.`-prefixed: the naming split is a live agenda item (-102 §7-③)
# and this module follows the logical contract rather than pre-empting it.
GITHUB_EVENTS_TOPIC = "github.events"

PUBLISH_CHECKPOINT_NAME = "publish-checkpoint.json"


def build_event_envelope(
    event: dict[str, object],
    *,
    hour_key: str,
    ingested_at: datetime,
) -> EventEnvelope:
    """Wrap one GH Archive event in the shared envelope.

    Raises `ValueError` when the event lacks a field the envelope requires. A
    malformed line is the caller's decision to skip or fail on, because the
    difference between one bad line and a changed schema matters.
    """

    event_id = event.get("id")
    event_type = event.get("type")
    created_at = event.get("created_at")
    if not event_id or not event_type or not created_at:
        raise ValueError(
            f"event is missing id, type or created_at: {sorted(event)[:8]}"
        )

    occurred_at = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)

    return EventEnvelope(
        source=SOURCE,
        # -102 §4.2: "hourly 파일 + event id". The file is part of the
        # identity because it is what a replay reads back.
        source_id=f"{hour_key}/{event_id}",
        event_type=str(event_type),
        # The event's own timestamp, not ours — the decision recorded in -103.
        occurred_at=occurred_at,
        ingested_at=ingested_at,
        payload=event,
        event_id=f"{SOURCE}-{event_id}",
    )


def _partition_key(event: dict[str, object]) -> bytes:
    """Key by repo id (-102 §3.2).

    Every event in the measured hour carried `repo.id`, but the fallback is
    the event id rather than `None`: a null key round-robins, which would
    scatter one repository's events across partitions and lose the per-repo
    ordering the key exists to provide.
    """

    repo = event.get("repo")
    if isinstance(repo, dict):
        repo_id = repo.get("id")
        if repo_id is not None:
            return str(repo_id).encode("utf-8")
    return str(event.get("id", "")).encode("utf-8")


def iter_hour_messages(
    path: Path,
    *,
    hour_key: str,
    ingested_at: datetime,
    skipped: list[str] | None = None,
) -> Iterator[tuple[bytes, bytes]]:
    """Stream one hour's archive as `(key, value)` pairs.

    Streamed rather than materialised: an hour holds tens of thousands of
    events and the gzip file is read line by line, so memory stays flat
    regardless of how large the hour is.

    A line that cannot be parsed or enveloped is appended to `skipped` and
    passed over. Failing the whole hour for one bad line would block every
    event behind it, and GH Archive files are third-party data — a single
    truncated line is not a reason to stop collecting a month.
    """

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                envelope = build_event_envelope(
                    event, hour_key=hour_key, ingested_at=ingested_at
                )
            except (json.JSONDecodeError, ValueError, TypeError) as error:
                if skipped is not None:
                    skipped.append(f"{hour_key}:{number}: {error}"[:200])
                continue
            yield _partition_key(event), envelope.to_bytes()


@dataclass
class PublishCheckpoint:
    """Which hours reached the broker.

    Deliberately not merged into `watch-checkpoint.json`. That file answers
    "is this hour on disk"; this one answers "did it reach Kafka". One file
    for both would make a broker outage either re-download everything or
    quietly skip publishing.
    """

    path: Path
    published: dict[str, dict[str, object]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> PublishCheckpoint:
        if not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # An unreadable checkpoint re-publishes rather than skipping.
            # Consumers dedup on `(source, source_id, schema_version)`, so a
            # repeat is absorbed; a wrongly-skipped hour is lost.
            return cls(path=path)
        entries = raw.get("published")
        if not isinstance(entries, dict):
            return cls(path=path)
        return cls(path=path, published=entries)

    def has(self, hour_key: str) -> bool:
        return hour_key in self.published

    def record(self, hour_key: str, *, events: int, at: datetime) -> None:
        self.published[hour_key] = {
            "events": events,
            "published_at": at.isoformat(),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {"topic": GITHUB_EVENTS_TOPIC, "published": self.published},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


@dataclass(frozen=True)
class HourPublishResult:
    hour: str
    events: int = 0
    published: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class PublishSummary:
    """What one publish pass did."""

    topic: str
    published: tuple[HourPublishResult, ...] = ()
    already_published: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    failed: tuple[HourPublishResult, ...] = ()
    skipped_lines: tuple[str, ...] = ()

    @property
    def event_count(self) -> int:
        return sum(result.events for result in self.published)

    @property
    def ok(self) -> bool:
        return not self.failed

    def as_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "published_hours": [result.hour for result in self.published],
            "published_events": self.event_count,
            "already_published": len(self.already_published),
            # Downloaded-but-absent. Reported rather than treated as an error:
            # the newest hour is often not on disk yet.
            "missing": list(self.missing),
            "failed": [
                {"hour": result.hour, "reason": result.reason} for result in self.failed
            ],
            "skipped_lines": len(self.skipped_lines),
            "skipped_line_samples": list(self.skipped_lines[:10]),
        }


@dataclass
class GhArchiveEventPublisher:
    """Publish whole downloaded hours, one hour at a time."""

    output_root: Path
    transport: KafkaTransport
    topic: str = GITHUB_EVENTS_TOPIC
    checkpoint_path: Path | None = None

    def __post_init__(self) -> None:
        self.output_root = Path(self.output_root).resolve()
        if self.checkpoint_path is None:
            self.checkpoint_path = self.output_root / PUBLISH_CHECKPOINT_NAME

    def publish_hours(
        self,
        hours: Sequence[str],
        *,
        ingested_at: datetime | None = None,
        max_hours: int | None = None,
    ) -> PublishSummary:
        """Publish each hour that is on disk and not already published.

        `max_hours` bounds one pass. The first watch run after the bootstrap
        cutoff fills every hour since it, which on 2026-09-09 was over 200 —
        publishing them all in one go would hold a container for a long time
        and give no partial progress. The checkpoint makes the next pass
        continue where this one stopped.
        """

        moment = ingested_at or datetime.now(UTC)
        checkpoint = PublishCheckpoint.load(self.checkpoint_path)

        published: list[HourPublishResult] = []
        already: list[str] = []
        missing: list[str] = []
        failed: list[HourPublishResult] = []
        skipped_lines: list[str] = []

        for hour_key in hours:
            if max_hours is not None and len(published) >= max_hours:
                break
            if checkpoint.has(hour_key):
                already.append(hour_key)
                continue
            try:
                hour = parse_utc_hour(hour_key)
            except RangeValidationError as error:
                failed.append(HourPublishResult(hour=hour_key, reason=str(error)))
                continue

            path = archive_for_hour(hour).final_path(self.output_root)
            if not path.exists():
                missing.append(hour_key)
                continue

            try:
                count = self.transport.send_many(
                    self.topic,
                    iter_hour_messages(
                        path,
                        hour_key=hour_key,
                        ingested_at=moment,
                        skipped=skipped_lines,
                    ),
                )
            except (KafkaError, OSError, gzip.BadGzipFile) as error:
                # The hour stays unrecorded, so the next pass retries it.
                failed.append(HourPublishResult(hour=hour_key, reason=str(error)[:400]))
                continue

            # Recorded only now, after the broker acknowledged the whole hour.
            checkpoint.record(hour_key, events=count, at=moment)
            published.append(
                HourPublishResult(hour=hour_key, events=count, published=True)
            )

        if published:
            checkpoint.save()

        return PublishSummary(
            topic=self.topic,
            published=tuple(published),
            already_published=tuple(already),
            missing=tuple(missing),
            failed=tuple(failed),
            skipped_lines=tuple(skipped_lines),
        )

    def downloaded_hours_on_disk(self) -> tuple[str, ...]:
        """Every hour present under the output root, oldest first.

        Used when a pass is not driven by a `WatchSummary` — after a restart,
        or to catch up hours the watcher downloaded before publishing existed.
        The filenames are the authority here rather than a checkpoint: a file
        on disk is the thing that can actually be published.
        """

        root = self.output_root / "raw" / SOURCE
        if not root.is_dir():
            return ()
        hours: list[datetime] = []
        for path in root.glob("dt=*/*.json.gz"):
            stem = path.name[: -len(".json.gz")]
            try:
                day, hour = stem.rsplit("-", 1)
                hours.append(parse_utc_hour(f"{day}T{int(hour):02d}:00:00Z"))
            except (ValueError, RangeValidationError):
                continue
        return tuple(format_utc_hour(hour) for hour in sorted(hours))


def publisher_from_env(
    output_root: Path,
    *,
    checkpoint_path: Path | None = None,
    topic: str = GITHUB_EVENTS_TOPIC,
) -> GhArchiveEventPublisher | None:
    """Build a publisher, or `None` when no broker is configured.

    `KAFKA_BOOTSTRAP_SERVERS` is the switch, matching `sink_from_env`'s use of
    `WEBHDFS_URL`: a developer without a broker downloads and archives as
    usual and publishes nothing.
    """

    transport = transport_from_env()
    if transport is None:
        return None
    return GhArchiveEventPublisher(
        output_root=output_root,
        transport=transport,
        topic=topic,
        checkpoint_path=checkpoint_path,
    )
