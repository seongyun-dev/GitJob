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
from common.kafka import (
    MAX_MESSAGE_BYTES,
    KafkaError,
    KafkaTransport,
    transport_from_env,
)

__all__ = [
    "GITHUB_EVENTS_TOPIC",
    "GhArchiveEventPublisher",
    "HourPublishResult",
    "ProgressUnreadable",
    "PublishCheckpoint",
    "PublishProgress",
    "PublishSummary",
    "RejectedEvent",
    "RejectedEventLog",
    "build_event_envelope",
    "iter_hour_messages",
    "publisher_from_env",
]

# The name from `docs/data/README.md` §4, carried unchanged through -102 §2.1.
# Not `gitjob.`-prefixed: the naming split is a live agenda item (-102 §7-③)
# and this module follows the logical contract rather than pre-empting it.
GITHUB_EVENTS_TOPIC = "github.events"

PUBLISH_CHECKPOINT_NAME = "publish-checkpoint.json"
# Resume state for an hour that is started but not finished, and the list
# of events the size contract refused. Separate files, separate lifetimes.
PUBLISH_PROGRESS_NAME = "publish-progress.json"
REJECTED_EVENTS_NAME = "publish-rejected-events.jsonl"


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


@dataclass(frozen=True)
class RejectedEvent:
    """One event the size contract refuses, with enough to find it again.

    Kept apart from `skipped_lines`, which is for a line that would not parse.
    This one parsed and enveloped cleanly; it is simply larger than any broker
    in this deployment will take, and no number of retries changes that.
    """

    hour: str
    source_id: str
    bytes: int
    limit: int
    reason: str = "EVENT_EXCEEDS_MAX_MESSAGE_BYTES"

    def as_dict(self) -> dict[str, object]:
        return {
            "hour": self.hour,
            "source_id": self.source_id,
            "bytes": self.bytes,
            "limit": self.limit,
            "reason": self.reason,
        }


def iter_hour_records(
    path: Path,
    *,
    hour_key: str,
    ingested_at: datetime,
    skipped: list[str] | None = None,
    rejected: list[RejectedEvent] | None = None,
    max_message_bytes: int = MAX_MESSAGE_BYTES,
    start_after_line: int = 0,
) -> Iterator[tuple[int, bytes, bytes]]:
    """`iter_hour_messages`, with the archive line each record came from.

    The line number is the resume cursor. It addresses the *file*, so it stays
    meaningful across a change of size limit, a line that stops parsing, or a
    rejection appearing where there was none — none of which is true of "the
    nth record we sent".

    `start_after_line` skips everything up to and including that line without
    enveloping it. A resumed hour therefore re-reads the gzip from the start
    (it has no random access) but re-sends nothing.
    """

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if number <= start_after_line:
                continue
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
            value = envelope.to_bytes()
            if len(value) > max_message_bytes:
                if rejected is not None:
                    rejected.append(
                        RejectedEvent(
                            hour=hour_key,
                            source_id=envelope.source_id,
                            bytes=len(value),
                            limit=max_message_bytes,
                        )
                    )
                continue
            yield number, _partition_key(event), value


def iter_hour_messages(
    path: Path,
    *,
    hour_key: str,
    ingested_at: datetime,
    skipped: list[str] | None = None,
    rejected: list[RejectedEvent] | None = None,
    max_message_bytes: int = MAX_MESSAGE_BYTES,
) -> Iterator[tuple[bytes, bytes]]:
    """Stream one hour's archive as `(key, value)` pairs.

    Streamed rather than materialised: an hour holds tens of thousands of
    events and the gzip file is read line by line, so memory stays flat
    regardless of how large the hour is.

    A line that cannot be parsed or enveloped is appended to `skipped` and
    passed over. Failing the whole hour for one bad line would block every
    event behind it, and GH Archive files are third-party data — a single
    truncated line is not a reason to stop collecting a month.

    ### Size is checked here, before the record is handed to the producer

    An event larger than `max_message_bytes` is appended to `rejected` and not
    yielded. Letting the producer discover it instead is what caused
    S15P21E102-257: the failure surfaced *during* the send, after earlier
    records of the same hour were already durable on the broker, and the hour
    was then left unrecorded so the next run re-sent all of it — for ever,
    because the same file fails the same way every time.

    Rejecting is not a workaround for a limit that could be raised. The
    operational broker takes 1,048,588 bytes and its replicas fetch 1,048,576;
    an event of 1.75 MiB has nowhere to go until those move together. What
    changes here is that one such event costs one event rather than an hour.
    """

    for _line, key, value in iter_hour_records(
        path,
        hour_key=hour_key,
        ingested_at=ingested_at,
        skipped=skipped,
        rejected=rejected,
        max_message_bytes=max_message_bytes,
    ):
        yield key, value


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

    def record(
        self,
        hour_key: str,
        *,
        events: int,
        at: datetime,
        rejected: int = 0,
    ) -> None:
        """Record an hour as done, with what it produced and what it refused.

        `rejected` is written even when zero so the field is always present:
        an hour recorded before S15P21E102-257 has no `rejected` key at all,
        and "absent" must stay distinguishable from "none".
        """

        self.published[hour_key] = {
            "events": events,
            "rejected": rejected,
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


class ProgressUnreadable(RuntimeError):
    """The in-progress file exists but could not be understood."""


@dataclass
class PublishProgress:
    """How far into an hour the broker has acknowledged. Resume state.

    `PublishCheckpoint` answers "is this hour finished". This answers "if it is
    not, where may the next run start". Two files rather than one because they
    fail differently: a finished hour must never be re-sent, while a partial
    one must be resumable, and a single record cannot be missing and present.

    ### Only acknowledged lines are written here

    `advance` is called from `send_many`'s acknowledgement callback, never on
    enqueue. A cursor moved when `producer.send` returns would skip records
    that were still in a buffer when the process died.

    ### An unreadable file is fail-closed

    A corrupt checkpoint may safely re-publish — consumers dedup — but a
    corrupt *progress* file cannot: trusting it could skip records that never
    reached the broker, and ignoring it re-sends an entire hour, which is the
    amplification S15P21E102-257 was. So the hour is failed and an operator
    decides.
    """

    path: Path
    hours: dict[str, dict[str, object]] = field(default_factory=dict)
    unreadable: bool = False

    @classmethod
    def load(cls, path: Path) -> PublishProgress:
        if not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(path=path, unreadable=True)
        hours = raw.get("hours")
        if not isinstance(hours, dict):
            return cls(path=path, unreadable=True)
        return cls(path=path, hours=hours)

    def resume_after(self, hour_key: str, *, limit: int) -> int:
        """The last acknowledged line, or 0 to start the hour over.

        A different size limit restarts the hour. The cursor itself stays
        valid — it addresses the file — but the set of records the limit lets
        through has changed, and an event that was rejected under the old
        limit sits behind the cursor where a resume would never look at it
        again.
        """

        if self.unreadable:
            raise ProgressUnreadable(str(self.path))
        entry = self.hours.get(hour_key)
        if not isinstance(entry, dict):
            return 0
        if entry.get("limit") != limit:
            return 0
        line = entry.get("next_line")
        return line if isinstance(line, int) and line > 0 else 0

    def acknowledged(self, hour_key: str, *, limit: int) -> int:
        entry = self.hours.get(hour_key)
        if not isinstance(entry, dict) or entry.get("limit") != limit:
            return 0
        count = entry.get("acknowledged")
        return count if isinstance(count, int) and count > 0 else 0

    def advance(
        self,
        hour_key: str,
        *,
        line: int,
        acknowledged: int,
        limit: int,
        at: datetime,
    ) -> None:
        self.hours[hour_key] = {
            "next_line": line,
            "acknowledged": acknowledged,
            "limit": limit,
            "updated_at": at.isoformat(),
        }

    def clear(self, hour_key: str) -> None:
        """Drop an hour's resume state once it is finished."""

        self.hours.pop(hour_key, None)

    def save(self) -> None:
        if self.unreadable:
            # Never overwrite a file an operator has not looked at.
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {"topic": GITHUB_EVENTS_TOPIC, "hours": self.hours},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


@dataclass
class RejectedEventLog:
    """Every event the size contract refused, kept where an operator can read it.

    A rejection that only existed in one run's summary would be gone as soon
    as the log rotated, and the hour is checkpointed so it is never re-derived.
    The source data survives in HDFS Raw either way; what needs to survive here
    is the *list* — which events the streaming path does not carry, so that
    raising the broker limit later is a matter of reading a file rather than
    re-scanning a month of archives.

    JSON Lines, appended, keyed by `(hour, source_id)`. A resumed hour meets
    the same rejections again, so an already-recorded one is not written twice.
    """

    path: Path

    def known(self) -> set[tuple[str, str]]:
        if not self.path.exists():
            return set()
        seen: set[tuple[str, str]] = set()
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return seen
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                # One unreadable line does not invalidate the rest; the worst
                # case is that its event is recorded a second time.
                continue
            hour, source_id = entry.get("hour"), entry.get("source_id")
            if isinstance(hour, str) and isinstance(source_id, str):
                seen.add((hour, source_id))
        return seen

    def record(self, events: Sequence[RejectedEvent], *, at: datetime) -> int:
        """Append the ones not already there. Returns how many were written."""

        if not events:
            return 0
        seen = self.known()
        lines: list[str] = []
        for event in events:
            key = (event.hour, event.source_id)
            if key in seen:
                continue
            seen.add(key)
            payload = dict(event.as_dict())
            payload["recorded_at"] = at.isoformat()
            lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        if not lines:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return len(lines)


@dataclass(frozen=True)
class HourPublishResult:
    hour: str
    events: int = 0
    published: bool = False
    reason: str | None = None
    # Events the size contract refused. An hour with rejections still counts as
    # published: everything a broker would accept reached it, and nothing is
    # gained by sending the rest again.
    rejected: int = 0
    # Archive line this pass started after. Non-zero means a previous pass
    # failed part-way and this one carried on rather than starting over.
    resumed_from_line: int = 0


@dataclass(frozen=True)
class PublishSummary:
    """What one publish pass did."""

    topic: str
    published: tuple[HourPublishResult, ...] = ()
    already_published: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    failed: tuple[HourPublishResult, ...] = ()
    skipped_lines: tuple[str, ...] = ()
    rejected_events: tuple[RejectedEvent, ...] = ()

    @property
    def event_count(self) -> int:
        return sum(result.events for result in self.published)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_events)

    @property
    def ok(self) -> bool:
        """Rejections are a reported outcome, not a failure of the pass.

        A rejected event is deterministic: it will be the same size on every
        run. Treating it as a failure would make an hour that can never
        succeed look retryable, which is exactly the loop -257 was.
        """

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
            # Separate from `failed`: these hours completed. The events below
            # are the ones no broker in this deployment can take, listed with
            # enough to find each one in its archive.
            "rejected_events": self.rejected_count,
            "rejected_event_samples": [
                event.as_dict() for event in self.rejected_events[:10]
            ],
        }


@dataclass
class GhArchiveEventPublisher:
    """Publish whole downloaded hours, one hour at a time."""

    output_root: Path
    transport: KafkaTransport
    topic: str = GITHUB_EVENTS_TOPIC
    checkpoint_path: Path | None = None
    progress_path: Path | None = None
    rejected_path: Path | None = None
    # The same contract the transport hands the broker. Held here too so the
    # gate that rejects an event and the producer that would have sent it read
    # one number; `publisher_from_env` takes both from the environment.
    max_message_bytes: int = MAX_MESSAGE_BYTES

    def __post_init__(self) -> None:
        self.output_root = Path(self.output_root).resolve()
        if self.checkpoint_path is None:
            self.checkpoint_path = self.output_root / PUBLISH_CHECKPOINT_NAME
        if self.progress_path is None:
            self.progress_path = self.output_root / PUBLISH_PROGRESS_NAME
        if self.rejected_path is None:
            self.rejected_path = self.output_root / REJECTED_EVENTS_NAME

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
        progress = PublishProgress.load(self.progress_path)
        rejected_log = RejectedEventLog(path=self.rejected_path)

        published: list[HourPublishResult] = []
        already: list[str] = []
        missing: list[str] = []
        failed: list[HourPublishResult] = []
        skipped_lines: list[str] = []
        rejected_events: list[RejectedEvent] = []

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

            # Per hour, so a rejection can be attributed to the hour it came
            # from even though the summary carries them all together.
            try:
                resume_after = progress.resume_after(
                    hour_key, limit=self.max_message_bytes
                )
            except ProgressUnreadable:
                # Fail closed. Trusting an unreadable cursor could skip records
                # that never reached the broker; ignoring it re-sends the hour,
                # which is the amplification this all exists to stop.
                failed.append(
                    HourPublishResult(hour=hour_key, reason="PROGRESS_UNREADABLE")
                )
                continue

            already_acked = progress.acknowledged(
                hour_key, limit=self.max_message_bytes
            )
            hour_rejected: list[RejectedEvent] = []
            # Filled as records are yielded, so the nth acknowledged record can
            # be mapped back to the archive line it came from.
            lines: list[int] = []

            def _remember(
                source: Iterator[tuple[int, bytes, bytes]],
                sink: list[int] = lines,
            ) -> Iterator[tuple[bytes, bytes]]:
                for line_number, key, value in source:
                    sink.append(line_number)
                    yield key, value

            def _on_acknowledged(
                count: int,
                hour: str = hour_key,
                sink: list[int] = lines,
                base: int = already_acked,
            ) -> None:
                # Called only after the broker acknowledged this chunk, so the
                # cursor never claims a record that was merely enqueued.
                progress.advance(
                    hour,
                    line=sink[count - 1],
                    acknowledged=base + count,
                    limit=self.max_message_bytes,
                    at=moment,
                )
                progress.save()

            try:
                count = self.transport.send_many(
                    self.topic,
                    _remember(
                        iter_hour_records(
                            path,
                            hour_key=hour_key,
                            ingested_at=moment,
                            skipped=skipped_lines,
                            rejected=hour_rejected,
                            max_message_bytes=self.max_message_bytes,
                            start_after_line=resume_after,
                        )
                    ),
                    on_batch_acknowledged=_on_acknowledged,
                )
            except (KafkaError, OSError, gzip.BadGzipFile) as error:
                # What reaches here is transient by construction: an event too
                # large for the broker was already filtered out above. A broker
                # that was down, a socket that dropped, a truncated gzip — all
                # worth retrying. The hour stays unrecorded, but the progress
                # written by the last acknowledged chunk stands, so the next
                # pass resumes from there instead of from the first event.
                rejected_events.extend(hour_rejected)
                rejected_log.record(hour_rejected, at=moment)
                failed.append(HourPublishResult(hour=hour_key, reason=str(error)[:400]))
                continue

            # Recorded now, after the broker acknowledged everything that was
            # sendable. An hour with rejections is still done: the rejected
            # events are deterministic, so re-reading the file would reject
            # them again while re-sending everything else. That re-send is what
            # multiplied `github.events` 2.4x (S15P21E102-257).
            rejected_events.extend(hour_rejected)
            rejected_log.record(hour_rejected, at=moment)
            total = already_acked + count
            checkpoint.record(
                hour_key, events=total, at=moment, rejected=len(hour_rejected)
            )
            # The hour is finished; its resume state is now noise that would
            # only confuse a later reader.
            progress.clear(hour_key)
            progress.save()
            published.append(
                HourPublishResult(
                    hour=hour_key,
                    events=total,
                    published=True,
                    rejected=len(hour_rejected),
                    resumed_from_line=resume_after,
                )
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
            rejected_events=tuple(rejected_events),
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
        # Taken from the transport rather than read again, so an override can
        # never apply to one and not the other.
        max_message_bytes=getattr(transport, "max_message_bytes", MAX_MESSAGE_BYTES),
    )
