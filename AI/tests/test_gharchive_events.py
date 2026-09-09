"""Publishing downloaded GH Archive hours to `github.events` (S15P21E102-144).

The envelope contract is S15P21E102-102 §4.1/§4.2 and the cases here pin the
three parts of it that are easy to get subtly wrong: `occurred_at` is the
event's own timestamp and not ours, `source_id` includes the hourly file, and
the partition key is the repo id.

The rest of the file is about what happens when an hour only partly
publishes — see `test_a_failed_hour_is_not_recorded_as_published`.

No broker: the transport is a recording double.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collector.gharchive.events import (
    GITHUB_EVENTS_TOPIC,
    GhArchiveEventPublisher,
    PublishCheckpoint,
    build_event_envelope,
    iter_hour_messages,
)
from common.kafka import KafkaError, KafkaTransport

INGESTED = datetime(2026, 9, 9, 6, 0, tzinfo=UTC)
HOUR_KEY = "2026-09-01T00:00:00Z"


def _event(
    event_id: str = "14172383030",
    *,
    event_type: str = "PushEvent",
    created_at: str = "2026-09-01T00:00:01Z",
    repo_id: int | None = 501027541,
) -> dict:
    event: dict = {
        "id": event_id,
        "type": event_type,
        "actor": {"id": 1, "login": "someone"},
        "payload": {"size": 1},
        "public": True,
        "created_at": created_at,
    }
    if repo_id is not None:
        event["repo"] = {"id": repo_id, "name": "owner/repo"}
    return event


@dataclass
class FakeTransport:
    """Records batches, so the batching itself is assertable."""

    batches: list[list[tuple[bytes | None, bytes]]] = field(default_factory=list)
    error: str | None = None
    fail_after: int | None = None

    def send(self, topic: str, *, key: bytes | None, value: bytes) -> None:
        raise AssertionError("github.events must publish in batches, not per message")

    def send_many(self, topic: str, messages) -> int:
        batch: list[tuple[bytes | None, bytes]] = []
        for pair in messages:
            if self.fail_after is not None and len(batch) >= self.fail_after:
                # Mid-stream failure: some records already went out.
                self.batches.append(batch)
                raise KafkaError("broker went away")
            batch.append(pair)
        if self.error:
            raise KafkaError(self.error)
        self.batches.append(batch)
        return len(batch)

    def close(self) -> None:
        return None

    @property
    def values(self) -> list[dict]:
        return [
            json.loads(value.decode("utf-8"))
            for batch in self.batches
            for _key, value in batch
        ]

    @property
    def keys(self) -> list[bytes | None]:
        return [key for batch in self.batches for key, _value in batch]


def _write_hour(root: Path, hour_key: str, events: list[dict]) -> Path:
    """Write an archive where `archive_for_hour` expects to find it."""

    day, hour = hour_key.split("T")[0], int(hour_key.split("T")[1][:2])
    path = root / "raw" / "gharchive" / f"dt={day}" / f"{day}-{hour}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def _publisher(tmp_path: Path, transport: FakeTransport) -> GhArchiveEventPublisher:
    return GhArchiveEventPublisher(output_root=tmp_path, transport=transport)


# --- the envelope contract (-102 §4.1/§4.2) ---------------------------------


def test_occurred_at_is_the_event_timestamp_not_ours():
    """`-103` decided GH Archive's `created_at` is `occurred_at`.

    Using our own clock would make every replayed event look as if it had
    happened at replay time, which is exactly what §4.5 separates the two
    timestamps to measure.
    """

    envelope = build_event_envelope(
        _event(created_at="2026-09-01T00:00:01Z"),
        hour_key=HOUR_KEY,
        ingested_at=INGESTED,
    )

    assert envelope.occurred_at == datetime(2026, 9, 1, 0, 0, 1, tzinfo=UTC)
    assert envelope.ingested_at == INGESTED


def test_source_id_includes_the_hourly_file():
    """§4.2: "hourly 파일 + event id".

    The file is part of the identity because it is what a replay reads back.
    """

    envelope = build_event_envelope(
        _event("999"), hour_key=HOUR_KEY, ingested_at=INGESTED
    )

    assert envelope.source_id == f"{HOUR_KEY}/999"
    assert envelope.event_id == "gharchive-999"
    assert envelope.source == "gharchive"


def test_payload_is_the_raw_event_not_a_pointer():
    """The opposite of `jobs.collected`, which carries a Claim Check.

    Here the event itself is what C1 archives and C2 extracts from.
    """

    event = _event()
    envelope = build_event_envelope(event, hour_key=HOUR_KEY, ingested_at=INGESTED)

    assert envelope.payload == event
    assert envelope.event_type == "PushEvent"


@pytest.mark.parametrize("missing", ["id", "type", "created_at"])
def test_an_event_missing_a_required_field_is_refused(missing):
    event = _event()
    del event[missing]

    with pytest.raises(ValueError, match="missing id, type or created_at"):
        build_event_envelope(event, hour_key=HOUR_KEY, ingested_at=INGESTED)


# --- partitioning -----------------------------------------------------------


def test_the_partition_key_is_the_repo_id(tmp_path: Path):
    """-102 §3.2 keys `github.events` by repo id."""

    _write_hour(tmp_path, HOUR_KEY, [_event(repo_id=501027541)])
    transport = FakeTransport()
    _publisher(tmp_path, transport).publish_hours([HOUR_KEY], ingested_at=INGESTED)

    assert transport.keys == [b"501027541"]


def test_an_event_without_a_repo_falls_back_to_the_event_id(tmp_path: Path):
    """Not `None`: a null key round-robins.

    That would scatter one repository's events across partitions and lose the
    per-repo ordering the key exists to provide.
    """

    _write_hour(tmp_path, HOUR_KEY, [_event("777", repo_id=None)])
    transport = FakeTransport()
    _publisher(tmp_path, transport).publish_hours([HOUR_KEY], ingested_at=INGESTED)

    assert transport.keys == [b"777"]


def test_publishing_uses_the_batched_send(tmp_path: Path):
    """`send` blocks per message; an hour averages 117,600 of them.

    `FakeTransport.send` raises, so this passes only if the publisher never
    reaches for the per-message call.
    """

    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(5)])
    transport = FakeTransport()
    summary = _publisher(tmp_path, transport).publish_hours(
        [HOUR_KEY], ingested_at=INGESTED
    )

    assert summary.event_count == 5
    assert len(transport.batches) == 1


# --- a malformed line is not a reason to stop -------------------------------


def test_a_malformed_line_is_skipped_and_reported(tmp_path: Path):
    """GH Archive files are third-party data.

    Failing the whole hour for one truncated line would block every event
    behind it.
    """

    path = tmp_path / "raw" / "gharchive" / "dt=2026-09-01" / "2026-09-01-0.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(_event("1")) + "\n")
        handle.write("{not json\n")
        handle.write(json.dumps(_event("2")) + "\n")

    transport = FakeTransport()
    summary = _publisher(tmp_path, transport).publish_hours(
        [HOUR_KEY], ingested_at=INGESTED
    )

    assert summary.event_count == 2
    assert len(summary.skipped_lines) == 1
    assert summary.ok


def test_blank_lines_are_not_counted_as_events(tmp_path: Path):
    path = tmp_path / "raw" / "gharchive" / "dt=2026-09-01" / "2026-09-01-0.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(_event("1")) + "\n\n\n")

    messages = list(iter_hour_messages(path, hour_key=HOUR_KEY, ingested_at=INGESTED))

    assert len(messages) == 1


# --- all-or-nothing per hour ------------------------------------------------


def test_a_failed_hour_is_not_recorded_as_published(tmp_path: Path):
    """A part-published hour must be retried, not remembered as done.

    The retry re-sends the part that already landed. That is the intended
    trade: §4.1 makes `(source, source_id, schema_version)` the consumer-side
    dedup key so a repeat is absorbed, and losing events is worse than
    repeating them.
    """

    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(10)])
    transport = FakeTransport(fail_after=4)
    publisher = _publisher(tmp_path, transport)

    summary = publisher.publish_hours([HOUR_KEY], ingested_at=INGESTED)

    assert not summary.ok
    assert summary.failed[0].hour == HOUR_KEY
    assert summary.event_count == 0
    # Nothing recorded, so the next pass sends the hour again.
    assert not publisher.checkpoint_path.exists()


def test_a_published_hour_is_skipped_on_the_next_pass(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event("1")])
    publisher = _publisher(tmp_path, FakeTransport())
    publisher.publish_hours([HOUR_KEY], ingested_at=INGESTED)

    second = FakeTransport()
    summary = _publisher(tmp_path, second).publish_hours(
        [HOUR_KEY], ingested_at=INGESTED
    )

    assert summary.already_published == (HOUR_KEY,)
    assert second.batches == []


def test_an_hour_not_on_disk_is_missing_not_failed(tmp_path: Path):
    """The newest hour is often downloaded a pass later than it is claimed."""

    transport = FakeTransport()
    summary = _publisher(tmp_path, transport).publish_hours(
        [HOUR_KEY], ingested_at=INGESTED
    )

    assert summary.missing == (HOUR_KEY,)
    assert summary.ok
    assert transport.batches == []


def test_max_hours_bounds_one_pass(tmp_path: Path):
    """The first pass after the bootstrap cutoff has 200+ hours to send."""

    hours = ["2026-09-01T00:00:00Z", "2026-09-01T01:00:00Z", "2026-09-01T02:00:00Z"]
    for hour in hours:
        _write_hour(tmp_path, hour, [_event("1")])

    publisher = _publisher(tmp_path, FakeTransport())
    summary = publisher.publish_hours(hours, ingested_at=INGESTED, max_hours=2)

    assert len(summary.published) == 2
    # The third is left for the next pass rather than dropped.
    assert PublishCheckpoint.load(publisher.checkpoint_path).has(hours[2]) is False


# --- the checkpoint ---------------------------------------------------------


def test_the_publish_checkpoint_is_a_separate_file(tmp_path: Path):
    """`watch-checkpoint.json` says what is on disk; this says what was sent.

    One file for both would make a broker outage either re-download
    everything or quietly skip publishing.
    """

    publisher = _publisher(tmp_path, FakeTransport())

    assert publisher.checkpoint_path.name == "publish-checkpoint.json"
    assert publisher.checkpoint_path != tmp_path / "watch-checkpoint.json"


def test_an_unreadable_checkpoint_republishes_rather_than_skipping(tmp_path: Path):
    """A repeat is absorbed by the dedup key; a skipped hour is lost."""

    _write_hour(tmp_path, HOUR_KEY, [_event("1")])
    publisher = _publisher(tmp_path, FakeTransport())
    publisher.checkpoint_path.write_text("{ truncated", encoding="utf-8")

    transport = FakeTransport()
    summary = _publisher(tmp_path, transport).publish_hours(
        [HOUR_KEY], ingested_at=INGESTED
    )

    assert summary.event_count == 1


def test_the_checkpoint_records_the_event_count(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(3)])
    publisher = _publisher(tmp_path, FakeTransport())
    publisher.publish_hours([HOUR_KEY], ingested_at=INGESTED)

    saved = json.loads(publisher.checkpoint_path.read_text(encoding="utf-8"))
    assert saved["topic"] == GITHUB_EVENTS_TOPIC
    assert saved["published"][HOUR_KEY]["events"] == 3


# --- driving a pass from disk ------------------------------------------------


def test_hours_on_disk_are_returned_oldest_first(tmp_path: Path):
    """A catch-up pass has to send hours in order, not in glob order.

    `2026-09-01-10.json.gz` sorts before `-2.json.gz` as a string.
    """

    for hour in (
        "2026-09-01T02:00:00Z",
        "2026-09-01T10:00:00Z",
        "2026-08-31T23:00:00Z",
    ):
        _write_hour(tmp_path, hour, [_event("1")])

    found = _publisher(tmp_path, FakeTransport()).downloaded_hours_on_disk()

    assert found == (
        "2026-08-31T23:00:00Z",
        "2026-09-01T02:00:00Z",
        "2026-09-01T10:00:00Z",
    )


def test_no_archives_on_disk_is_not_an_error(tmp_path: Path):
    assert _publisher(tmp_path, FakeTransport()).downloaded_hours_on_disk() == ()


def test_fake_transport_satisfies_the_protocol():
    assert isinstance(FakeTransport(), KafkaTransport)
