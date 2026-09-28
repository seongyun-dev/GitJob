"""Intra-hour resume after a transient failure (S15P21E102-257, review round 2).

The first fix stopped an *oversized* event from restarting an hour. It did not
stop a *transient* one: 1~50 acknowledged, 51 times out, and the next run began
again at 1 — the same duplicates from a different cause, because the hour-level
checkpoint is written only when the whole hour lands.

These pin the cursor that closes that. The transport double acknowledges in
chunks and can fail between them, so a failure lands where it would in
production: after some records are durable and before others are.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from collector.gharchive.events import GhArchiveEventPublisher
from common.kafka import KafkaError

HOUR_KEY = "2026-09-01T00:00:00Z"
LIMIT = 4_096


def _event(event_id: str, *, padding: int = 0) -> dict:
    event: dict = {
        "id": event_id,
        "type": "PushEvent",
        "actor": {"id": 1, "login": "someone"},
        "payload": {"size": 1},
        "public": True,
        "created_at": "2026-09-01T00:00:01Z",
        "repo": {"id": 501027541, "name": "owner/repo"},
    }
    if padding:
        event["payload"]["commits"] = "x" * padding
    return event


def _oversized(event_id: str) -> dict:
    return _event(event_id, padding=LIMIT * 2)


@dataclass
class ChunkedBroker:
    """Acknowledges `flush_size` records at a time, and can stop between chunks.

    `fail_after` refuses the next record once this call has enqueued that many.
    `crash_after_ack` is the narrower case the design accepts: the chunk is
    durable on the broker, and the process dies before the caller is told.
    """

    flush_size: int = 10
    fail_after: int | None = None
    error: str | None = None
    crash_after_ack: int | None = None
    acked_ids: list[str] = field(default_factory=list)
    calls: int = 0

    def send(self, topic: str, *, key, value) -> None:
        raise AssertionError("github.events publishes in batches")

    def send_many(self, topic: str, messages, *, on_batch_acknowledged=None) -> int:
        self.calls += 1
        acknowledged = 0
        enqueued = 0
        chunk: list[bytes] = []

        def ack() -> None:
            nonlocal acknowledged, chunk
            if not chunk:
                return
            for value in chunk:
                self.acked_ids.append(json.loads(value.decode())["payload"]["id"])
            acknowledged += len(chunk)
            chunk = []
            if (
                self.crash_after_ack is not None
                and acknowledged >= self.crash_after_ack
            ):
                raise KafkaError("process died before progress was written")
            if on_batch_acknowledged is not None:
                on_batch_acknowledged(acknowledged)

        for _key, value in messages:
            if self.fail_after is not None and enqueued >= self.fail_after:
                raise KafkaError("broker went away")
            chunk.append(value)
            enqueued += 1
            if len(chunk) >= self.flush_size:
                ack()
        ack()
        if self.error:
            raise KafkaError(self.error)
        return acknowledged


def _write_hour(root: Path, hour_key: str, events: list[dict]) -> Path:
    day, hour = hour_key.split("T")[0], int(hour_key.split("T")[1][:2])
    path = root / "raw" / "gharchive" / f"dt={day}" / f"{day}-{hour}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def _publisher(
    tmp_path: Path, broker: ChunkedBroker, *, limit: int = LIMIT
) -> GhArchiveEventPublisher:
    return GhArchiveEventPublisher(
        output_root=tmp_path, transport=broker, max_message_bytes=limit
    )


def _checkpoint(tmp_path: Path) -> dict:
    path = tmp_path / "publish-checkpoint.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["published"]


def _progress(tmp_path: Path) -> dict:
    path = tmp_path / "publish-progress.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["hours"]


def _rejected_log(tmp_path: Path) -> list[dict]:
    path = tmp_path / "publish-rejected-events.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --- A: acknowledged records are not sent again -----------------------------


def test_events_acknowledged_before_a_transient_failure_are_not_resent(tmp_path: Path):
    """100 events, 1~50 acknowledged, then a timeout. The rerun re-sends none."""

    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 101)])

    first = ChunkedBroker(fail_after=50)
    assert not _publisher(tmp_path, first).publish_hours([HOUR_KEY]).ok
    assert first.acked_ids == [str(n) for n in range(1, 51)]

    second = ChunkedBroker()
    summary = _publisher(tmp_path, second).publish_hours([HOUR_KEY])

    assert summary.ok
    assert set(second.acked_ids).isdisjoint(set(first.acked_ids))
    assert second.acked_ids == [str(n) for n in range(51, 101)]


def test_the_resumed_hour_records_the_whole_count(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 101)])
    _publisher(tmp_path, ChunkedBroker(fail_after=50)).publish_hours([HOUR_KEY])

    summary = _publisher(tmp_path, ChunkedBroker()).publish_hours([HOUR_KEY])

    assert _checkpoint(tmp_path)[HOUR_KEY]["events"] == 100
    assert summary.published[0].resumed_from_line == 50


# --- B: resume starts after the last acknowledged chunk ---------------------


def test_resume_starts_after_the_last_acknowledged_chunk(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 51)])

    first = ChunkedBroker(fail_after=25)
    _publisher(tmp_path, first).publish_hours([HOUR_KEY])

    # Chunks of ten: 20 acknowledged; 21~25 were enqueued and never acked.
    assert first.acked_ids == [str(n) for n in range(1, 21)]
    assert _progress(tmp_path)[HOUR_KEY]["next_line"] == 20
    assert _progress(tmp_path)[HOUR_KEY]["acknowledged"] == 20

    second = ChunkedBroker()
    _publisher(tmp_path, second).publish_hours([HOUR_KEY])

    assert second.acked_ids[0] == "21"


def test_the_cursor_does_not_move_on_enqueue_alone(tmp_path: Path):
    """Buffered-but-unacknowledged records must be sent again, not skipped."""

    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 51)])

    first = ChunkedBroker(fail_after=25)
    _publisher(tmp_path, first).publish_hours([HOUR_KEY])

    second = ChunkedBroker()
    _publisher(tmp_path, second).publish_hours([HOUR_KEY])

    for event_id in ("21", "22", "23", "24", "25"):
        assert event_id in second.acked_ids


# --- C: the accepted crash window -------------------------------------------


def test_a_crash_between_ack_and_progress_costs_at_most_one_chunk(tmp_path: Path):
    """Durable on the broker, never recorded here. Bounded to one chunk."""

    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 51)])

    first = ChunkedBroker(crash_after_ack=30)
    assert not _publisher(tmp_path, first).publish_hours([HOUR_KEY]).ok
    assert first.acked_ids == [str(n) for n in range(1, 31)]
    # The third chunk's callback never ran, so the cursor stands at the second.
    assert _progress(tmp_path)[HOUR_KEY]["acknowledged"] == 20

    second = ChunkedBroker()
    _publisher(tmp_path, second).publish_hours([HOUR_KEY])

    duplicated = set(second.acked_ids) & set(first.acked_ids)
    assert duplicated == {str(n) for n in range(21, 31)}
    assert len(duplicated) <= first.flush_size


def test_the_duplicate_window_does_not_grow_with_the_hour(tmp_path: Path):
    """Ten times the events, the same bounded window."""

    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 501)])

    first = ChunkedBroker(crash_after_ack=300)
    _publisher(tmp_path, first).publish_hours([HOUR_KEY])
    second = ChunkedBroker()
    _publisher(tmp_path, second).publish_hours([HOUR_KEY])

    duplicated = set(second.acked_ids) & set(first.acked_ids)
    assert len(duplicated) <= first.flush_size


# --- completion clears the resume state -------------------------------------


def test_a_completed_hour_leaves_no_resume_state(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 21)])
    _publisher(tmp_path, ChunkedBroker(fail_after=10)).publish_hours([HOUR_KEY])
    assert HOUR_KEY in _progress(tmp_path)

    _publisher(tmp_path, ChunkedBroker()).publish_hours([HOUR_KEY])

    assert HOUR_KEY not in _progress(tmp_path)


# --- D/E: checkpoint compatibility ------------------------------------------


def test_a_completed_hour_is_skipped_outright(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 11)])
    _publisher(tmp_path, ChunkedBroker()).publish_hours([HOUR_KEY])

    third = ChunkedBroker()
    summary = _publisher(tmp_path, third).publish_hours([HOUR_KEY])

    assert summary.already_published == (HOUR_KEY,)
    assert third.calls == 0


def test_an_old_checkpoint_with_no_progress_file_is_honoured(tmp_path: Path):
    """The pre-fix shape: a completed hour and no progress file at all."""

    (tmp_path / "publish-checkpoint.json").write_text(
        json.dumps(
            {
                "topic": "github.events",
                "published": {HOUR_KEY: {"events": 5, "published_at": "2026-09-13"}},
            }
        ),
        encoding="utf-8",
    )
    _write_hour(tmp_path, HOUR_KEY, [_event("1")])
    broker = ChunkedBroker()

    summary = _publisher(tmp_path, broker).publish_hours([HOUR_KEY])

    assert summary.already_published == (HOUR_KEY,)
    assert broker.calls == 0
    assert not (tmp_path / "publish-progress.json").exists()


def test_no_progress_file_is_written_for_an_hour_that_never_starts(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event("1")])
    _publisher(tmp_path, ChunkedBroker()).publish_hours(["2026-09-02T05:00:00Z"])

    assert _progress(tmp_path) == {}


# --- F: corrupt progress is fail-closed -------------------------------------


def test_a_corrupt_progress_file_fails_closed(tmp_path: Path):
    """Neither trust it nor ignore it. Stop, and let an operator look."""

    (tmp_path / "publish-progress.json").write_text("{not json", encoding="utf-8")
    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 11)])
    broker = ChunkedBroker()

    summary = _publisher(tmp_path, broker).publish_hours([HOUR_KEY])

    assert not summary.ok
    assert summary.failed[0].reason == "PROGRESS_UNREADABLE"
    assert broker.calls == 0


def test_a_corrupt_progress_file_is_left_untouched(tmp_path: Path):
    path = tmp_path / "publish-progress.json"
    path.write_text("{not json", encoding="utf-8")
    _write_hour(tmp_path, HOUR_KEY, [_event("1")])

    _publisher(tmp_path, ChunkedBroker()).publish_hours([HOUR_KEY])

    assert path.read_text(encoding="utf-8") == "{not json"


def test_a_changed_size_limit_restarts_the_hour(tmp_path: Path):
    """The cursor stays valid, but what the limit admits has changed."""

    _write_hour(tmp_path, HOUR_KEY, [_event(str(n)) for n in range(1, 51)])
    _publisher(tmp_path, ChunkedBroker(fail_after=25)).publish_hours([HOUR_KEY])

    summary = _publisher(
        tmp_path, ChunkedBroker(), limit=LIMIT * 4
    ).publish_hours([HOUR_KEY])

    assert summary.published[0].resumed_from_line == 0


# --- G: oversized and transient together ------------------------------------


def test_oversized_and_transient_failure_in_one_hour(tmp_path: Path):
    """1~50 ack, 51 oversized, 52~70 ack, then a timeout. Then resume."""

    events = [_event(str(n)) for n in range(1, 51)]
    events.append(_oversized("51"))
    events.extend(_event(str(n)) for n in range(52, 101))
    _write_hour(tmp_path, HOUR_KEY, events)

    first = ChunkedBroker(fail_after=70)
    assert not _publisher(tmp_path, first).publish_hours([HOUR_KEY]).ok
    assert "51" not in first.acked_ids  # rejected, never offered to the broker

    second = ChunkedBroker()
    summary = _publisher(tmp_path, second).publish_hours([HOUR_KEY])

    assert summary.ok
    assert set(second.acked_ids).isdisjoint(set(first.acked_ids))
    assert "51" not in second.acked_ids
    assert HOUR_KEY in _checkpoint(tmp_path)
    assert HOUR_KEY not in _progress(tmp_path)


# --- rejected events are durable and idempotent -----------------------------


def test_a_rejected_event_is_written_to_a_durable_log(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_event("1"), _oversized("2")])

    _publisher(tmp_path, ChunkedBroker()).publish_hours([HOUR_KEY])

    entries = _rejected_log(tmp_path)
    assert len(entries) == 1
    assert entries[0]["hour"] == HOUR_KEY
    assert entries[0]["source_id"] == f"{HOUR_KEY}/2"
    assert entries[0]["bytes"] > LIMIT
    assert entries[0]["limit"] == LIMIT
    assert entries[0]["reason"] == "EVENT_EXCEEDS_MAX_MESSAGE_BYTES"
    assert "recorded_at" in entries[0]


def test_a_resumed_hour_does_not_log_the_same_rejection_twice(tmp_path: Path):
    events = [_oversized("big")] + [_event(str(n)) for n in range(1, 51)]
    _write_hour(tmp_path, HOUR_KEY, events)

    _publisher(tmp_path, ChunkedBroker(fail_after=25)).publish_hours([HOUR_KEY])
    assert len(_rejected_log(tmp_path)) == 1

    _publisher(tmp_path, ChunkedBroker()).publish_hours([HOUR_KEY])

    assert len(_rejected_log(tmp_path)) == 1


def test_repeated_passes_do_not_grow_the_rejected_log(tmp_path: Path):
    _write_hour(tmp_path, HOUR_KEY, [_oversized("a"), _oversized("b")])

    for _ in range(5):
        _publisher(tmp_path, ChunkedBroker()).publish_hours([HOUR_KEY])

    assert len(_rejected_log(tmp_path)) == 2


def test_rejections_from_a_failed_hour_are_still_recorded(tmp_path: Path):
    """The hour will be retried, but the list is readable now."""

    events = [_oversized("big")] + [_event(str(n)) for n in range(1, 21)]
    _write_hour(tmp_path, HOUR_KEY, events)

    _publisher(tmp_path, ChunkedBroker(error="broker down")).publish_hours([HOUR_KEY])

    assert [entry["source_id"] for entry in _rejected_log(tmp_path)] == [
        f"{HOUR_KEY}/big"
    ]
