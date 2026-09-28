"""The oversized-event loop that multiplied `github.events` (S15P21E102-257).

An event larger than the broker's limit used to fail *during* the send, after
earlier records of the same hour were already durable. The hour was then left
unrecorded, so the next cron re-sent all of it — and failed at the same event,
for ever. Production saw the same hour sent 12 times and at least 2.4x the
records the checkpoint accounted for.

These pin the two halves of the fix: an oversized event costs one event rather
than an hour, and a *transient* failure still costs the hour, because that one
is worth retrying.

No broker: the transport is a recording double.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from collector.gharchive.events import (
    GhArchiveEventPublisher,
    PublishCheckpoint,
    RejectedEvent,
    iter_hour_messages,
)
from common.kafka import (
    MAX_MESSAGE_BYTES,
    KafkaError,
    KafkaPythonTransport,
    max_message_bytes_from_env,
    transport_from_env,
)

INGESTED = datetime(2026, 9, 9, 6, 0, tzinfo=UTC)
HOUR_KEY = "2026-09-01T00:00:00Z"
OTHER_HOUR = "2026-09-01T01:00:00Z"

# Small enough to keep fixtures readable; the logic does not care about scale.
LIMIT = 4_096


def _event(event_id: str = "1", *, padding: int = 0, repo_id: int | None = 501027541):
    event: dict = {
        "id": event_id,
        "type": "PushEvent",
        "actor": {"id": 1, "login": "someone"},
        "payload": {"size": 1},
        "public": True,
        "created_at": "2026-09-01T00:00:01Z",
    }
    if padding:
        # One field the envelope carries through, so the serialized record
        # grows the way a real oversized GH Archive event does.
        event["payload"]["commits"] = "x" * padding
    if repo_id is not None:
        event["repo"] = {"id": repo_id, "name": "owner/repo"}
    return event


def _oversized(event_id: str = "big") -> dict:
    return _event(event_id, padding=LIMIT * 2)


@dataclass
class FakeTransport:
    """A broker that acknowledges in chunks and can fail between them.

    `flush_size` mirrors `KafkaPythonTransport.batch_flush_size`: records are
    acknowledged a chunk at a time, and `on_batch_acknowledged` fires only
    after a chunk is durable. That is what makes the resume cursor testable —
    a failure lands between two acknowledgements, exactly as it would in
    production.
    """

    batches: list[list[tuple[bytes | None, bytes]]] = field(default_factory=list)
    # Fail when the call has already enqueued this many records.
    fail_after: int | None = None
    error: str | None = None
    flush_size: int = 10
    calls: int = 0
    # Ids the broker acknowledged, across every call this double has served.
    acked_ids: list[str] = field(default_factory=list)
    # Ids acknowledged before the callback for their chunk ran, so a crash
    # between the two can be simulated.
    crash_after_ack: int | None = None

    def send(self, topic: str, *, key, value) -> None:
        raise AssertionError("github.events publishes in batches")

    def send_many(self, topic: str, messages, *, on_batch_acknowledged=None) -> int:
        self.calls += 1
        acknowledged = 0
        chunk: list[tuple[bytes | None, bytes]] = []
        enqueued = 0

        def ack() -> None:
            nonlocal acknowledged, chunk
            if not chunk:
                return
            self.batches.append(list(chunk))
            for _, value in chunk:
                self.acked_ids.append(json.loads(value.decode())["payload"]["id"])
            acknowledged += len(chunk)
            chunk = []
            if self.crash_after_ack is not None and acknowledged >= self.crash_after_ack:
                # Durable on the broker, but the caller never learns of it.
                raise KafkaError("process died before progress was written")
            if on_batch_acknowledged is not None:
                on_batch_acknowledged(acknowledged)

        for pair in messages:
            if self.fail_after is not None and enqueued >= self.fail_after:
                raise KafkaError("broker went away")
            chunk.append(pair)
            enqueued += 1
            if len(chunk) >= self.flush_size:
                ack()
        ack()
        if self.error:
            raise KafkaError(self.error)
        return acknowledged

    def close(self) -> None:
        return None

    @property
    def sent_ids(self) -> list[str]:
        return list(self.acked_ids)


def _write_hour(root: Path, hour_key: str, events: list[dict]) -> Path:
    day, hour = hour_key.split("T")[0], int(hour_key.split("T")[1][:2])
    path = root / "raw" / "gharchive" / f"dt={day}" / f"{day}-{hour}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def _publisher(tmp_path: Path, transport: FakeTransport) -> GhArchiveEventPublisher:
    return GhArchiveEventPublisher(
        output_root=tmp_path, transport=transport, max_message_bytes=LIMIT
    )


def _checkpoint(tmp_path: Path) -> dict:
    return json.loads(
        (tmp_path / "publish-checkpoint.json").read_text(encoding="utf-8")
    )["published"]


# --- the size contract is one number ---------------------------------------


def test_the_producer_is_given_the_same_limit_callers_check_against():
    transport = transport_from_env({"KAFKA_BOOTSTRAP_SERVERS": "kafka:9092"})

    assert isinstance(transport, KafkaPythonTransport)
    assert transport.max_message_bytes == MAX_MESSAGE_BYTES


def test_the_limit_is_bounded_not_unlimited():
    assert 0 < MAX_MESSAGE_BYTES <= 1_048_588  # the broker's message.max.bytes


def test_the_limit_follows_the_broker_when_it_is_raised():
    assert max_message_bytes_from_env({"KAFKA_MAX_MESSAGE_BYTES": "2097152"}) == 2_097_152


def test_a_malformed_override_falls_back_rather_than_failing_the_run():
    assert max_message_bytes_from_env({"KAFKA_MAX_MESSAGE_BYTES": "huge"}) == (
        MAX_MESSAGE_BYTES
    )
    assert max_message_bytes_from_env({"KAFKA_MAX_MESSAGE_BYTES": "0"}) == (
        MAX_MESSAGE_BYTES
    )


# --- normal hour ------------------------------------------------------------


def test_a_normal_hour_publishes_everything_and_rejects_nothing(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(5)])
    transport = FakeTransport()

    summary = _publisher(tmp_path, transport).publish_hours([HOUR_KEY])

    assert summary.ok
    assert summary.event_count == 5
    assert summary.rejected_count == 0

    recorded = _checkpoint(tmp_path)[HOUR_KEY]
    assert recorded["events"] == 5
    assert recorded["rejected"] == 0


# --- one oversized event ----------------------------------------------------


def test_an_oversized_event_does_not_fail_its_hour(tmp_path: Path):
    """The regression. Before the fix this hour failed and was never recorded."""

    _write_hour(tmp_path, HOUR_KEY, [_event("1"), _oversized("2"), _event("3")])
    transport = FakeTransport()

    summary = _publisher(tmp_path, transport).publish_hours([HOUR_KEY])

    assert summary.ok
    assert not summary.failed
    assert summary.event_count == 2
    assert summary.rejected_count == 1


def test_an_oversized_event_is_never_handed_to_the_producer(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event("1"), _oversized("2")])
    transport = FakeTransport()

    _publisher(tmp_path, transport).publish_hours([HOUR_KEY])

    assert transport.sent_ids == ["1"]
    assert all(len(value) <= LIMIT for batch in transport.batches for _, value in batch)


def test_a_rejection_carries_enough_to_find_the_event(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_oversized("12345")])
    transport = FakeTransport()

    summary = _publisher(tmp_path, transport).publish_hours([HOUR_KEY])

    rejected = summary.rejected_events[0]
    assert rejected.hour == HOUR_KEY
    assert rejected.source_id == f"{HOUR_KEY}/12345"
    assert rejected.bytes > LIMIT
    assert rejected.limit == LIMIT
    assert rejected.reason == "EVENT_EXCEEDS_MAX_MESSAGE_BYTES"


def test_rejections_reach_the_summary_payload(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_oversized("9")])
    transport = FakeTransport()

    payload = _publisher(tmp_path, transport).publish_hours([HOUR_KEY]).as_dict()

    assert payload["rejected_events"] == 1
    assert payload["rejected_event_samples"][0]["source_id"] == f"{HOUR_KEY}/9"
    assert payload["rejected_event_samples"][0]["bytes"] > LIMIT


def test_a_rejection_is_not_a_failed_hour(tmp_path: Path):
    """`failed` means retry. A rejection is deterministic and must not."""

    _write_hour(tmp_path, HOUR_KEY, [_oversized("1")])

    summary = _publisher(tmp_path, FakeTransport()).publish_hours([HOUR_KEY])

    assert summary.failed == ()
    assert summary.ok


# --- several oversized events ----------------------------------------------


def test_several_oversized_events_are_each_reported(tmp_path: Path):
    _write_hour(
        tmp_path,
        HOUR_KEY,
        [_oversized("a"), _event("b"), _oversized("c"), _oversized("d")],
    )
    transport = FakeTransport()

    summary = _publisher(tmp_path, transport).publish_hours([HOUR_KEY])

    assert summary.event_count == 1
    assert summary.rejected_count == 3
    assert [r.source_id for r in summary.rejected_events] == [
        f"{HOUR_KEY}/a",
        f"{HOUR_KEY}/c",
        f"{HOUR_KEY}/d",
    ]
    assert _checkpoint(tmp_path)[HOUR_KEY]["rejected"] == 3


def test_an_hour_that_is_entirely_oversized_still_completes(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_oversized("a"), _oversized("b")])

    summary = _publisher(tmp_path, FakeTransport()).publish_hours([HOUR_KEY])

    assert summary.ok
    assert summary.event_count == 0
    assert HOUR_KEY in _checkpoint(tmp_path)


# --- partial batch success then oversized -----------------------------------


def test_events_before_an_oversized_one_are_published(tmp_path: Path):
    _write_hour(
        tmp_path, HOUR_KEY, [_event("1"), _event("2"), _oversized("3"), _event("4")]
    )
    transport = FakeTransport()

    summary = _publisher(tmp_path, transport).publish_hours([HOUR_KEY])

    assert transport.sent_ids == ["1", "2", "4"]
    assert summary.event_count == 3
    assert summary.rejected_count == 1


# --- transient failure is still a failure -----------------------------------


def test_a_transient_failure_still_leaves_the_hour_unrecorded(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(10)])
    transport = FakeTransport(fail_after=4)

    summary = _publisher(tmp_path, transport).publish_hours([HOUR_KEY])

    assert not summary.ok
    assert summary.failed[0].hour == HOUR_KEY
    assert not (tmp_path / "publish-checkpoint.json").exists()


def test_a_transient_failure_is_retried_on_the_next_pass(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(4)])
    first = FakeTransport(error="broker down")
    publisher = _publisher(tmp_path, first)
    assert not publisher.publish_hours([HOUR_KEY]).ok

    second = FakeTransport()
    summary = _publisher(tmp_path, second).publish_hours([HOUR_KEY])

    assert summary.ok
    assert summary.event_count == 4


def test_rejections_are_reported_even_when_the_hour_then_fails(tmp_path: Path):
    """The operator needs both facts: what was refused and why it stopped."""

    _write_hour(
        tmp_path, HOUR_KEY, [_oversized("big"), *[_event(str(n)) for n in range(8)]]
    )
    transport = FakeTransport(fail_after=3)

    summary = _publisher(tmp_path, transport).publish_hours([HOUR_KEY])

    assert not summary.ok
    assert summary.rejected_count == 1
    assert summary.rejected_events[0].source_id == f"{HOUR_KEY}/big"


# --- rerun and resume: the loop is closed -----------------------------------


def test_a_rerun_does_not_resend_an_hour_that_had_rejections(tmp_path: Path):
    """This is the loop. Before the fix, every rerun re-sent the whole hour."""

    _write_hour(tmp_path, HOUR_KEY, [_event("1"), _oversized("2"), _event("3")])
    first = FakeTransport()
    _publisher(tmp_path, first).publish_hours([HOUR_KEY])
    assert first.sent_ids == ["1", "3"]

    second = FakeTransport()
    summary = _publisher(tmp_path, second).publish_hours([HOUR_KEY])

    assert summary.already_published == (HOUR_KEY,)
    assert second.calls == 0
    assert second.sent_ids == []


def test_duplicates_stay_bounded_across_repeated_runs(tmp_path: Path):
    """Ten passes over an hour holding an oversized event send it once."""

    _write_hour(tmp_path, HOUR_KEY, [_event("1"), _oversized("2"), _event("3")])
    total: list[str] = []

    for _ in range(10):
        transport = FakeTransport()
        _publisher(tmp_path, transport).publish_hours([HOUR_KEY])
        total.extend(transport.sent_ids)

    assert total == ["1", "3"]


def test_resume_continues_with_the_hours_that_are_left(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event("1"), _oversized("2")])
    _write_hour(tmp_path, OTHER_HOUR, [_event("3")])

    first = FakeTransport()
    _publisher(tmp_path, first).publish_hours([HOUR_KEY])

    second = FakeTransport()
    summary = _publisher(tmp_path, second).publish_hours([HOUR_KEY, OTHER_HOUR])

    assert summary.already_published == (HOUR_KEY,)
    assert [r.hour for r in summary.published] == [OTHER_HOUR]
    assert second.sent_ids == ["3"]


def test_the_checkpoint_separates_produced_from_rejected(tmp_path: Path):
    _write_hour(
        tmp_path, HOUR_KEY, [_event("1"), _oversized("2"), _oversized("3"), _event("4")]
    )

    _publisher(tmp_path, FakeTransport()).publish_hours([HOUR_KEY])

    recorded = _checkpoint(tmp_path)[HOUR_KEY]
    assert recorded["events"] == 2
    assert recorded["rejected"] == 2


def test_an_hour_recorded_before_this_fix_is_still_honoured(tmp_path: Path):
    """Old entries have no `rejected` key; they must not be re-sent."""

    path = tmp_path / "publish-checkpoint.json"
    path.write_text(
        json.dumps(
            {
                "topic": "github.events",
                "published": {HOUR_KEY: {"events": 5, "published_at": "2026-09-13"}},
            }
        ),
        encoding="utf-8",
    )
    _write_hour(tmp_path, HOUR_KEY, [_event("1")])
    transport = FakeTransport()

    summary = _publisher(tmp_path, transport).publish_hours([HOUR_KEY])

    assert summary.already_published == (HOUR_KEY,)
    assert transport.calls == 0


# --- the iterator on its own -------------------------------------------------


def test_the_iterator_keeps_rejections_apart_from_unparseable_lines(tmp_path: Path):
    path = _write_hour(tmp_path, HOUR_KEY, [_event("1"), _oversized("2")])
    with gzip.open(path, "at", encoding="utf-8") as handle:
        handle.write("{not json\n")

    skipped: list[str] = []
    rejected: list[RejectedEvent] = []
    produced = list(
        iter_hour_messages(
            path,
            hour_key=HOUR_KEY,
            ingested_at=INGESTED,
            skipped=skipped,
            rejected=rejected,
            max_message_bytes=LIMIT,
        )
    )

    assert len(produced) == 1
    assert len(rejected) == 1
    assert len(skipped) == 1


def test_an_event_exactly_at_the_limit_is_published(tmp_path: Path):
    """The gate is `>`, not `>=`: a record the broker accepts must go."""

    path = _write_hour(tmp_path, HOUR_KEY, [_event("1")])
    messages = list(
        iter_hour_messages(
            path, hour_key=HOUR_KEY, ingested_at=INGESTED, max_message_bytes=99_999
        )
    )
    exact = len(messages[0][1])

    rejected: list[RejectedEvent] = []
    produced = list(
        iter_hour_messages(
            path,
            hour_key=HOUR_KEY,
            ingested_at=INGESTED,
            rejected=rejected,
            max_message_bytes=exact,
        )
    )

    assert len(produced) == 1
    assert rejected == []


def test_checkpoint_record_writes_rejected_even_when_zero(tmp_path: Path):
    checkpoint = PublishCheckpoint(path=tmp_path / "cp.json")
    checkpoint.record(HOUR_KEY, events=3, at=INGESTED)

    assert checkpoint.published[HOUR_KEY]["rejected"] == 0
