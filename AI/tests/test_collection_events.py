"""`jobs.collected` publishing (S15P21E102-102/-103).

No broker and no network: the transport is a fake, so these run in a clean
checkout without `kafka-python` installed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from common.events import EventEnvelope
from common.kafka import KafkaError, KafkaTransport, transport_from_env
from job.collector.events import (
    COLLECTION_EVENT_TYPE,
    JOBS_TOPIC,
    PUBLISH_RECORD,
    CollectionEventPublisher,
    build_collection_event,
    publisher_from_env,
    write_publish_record,
)
from job.collector.raw_sink import RAW_UPLOAD_RECORD


@dataclass
class FakeTransport:
    """Records what would have been sent."""

    sent: list[tuple[str, bytes | None, bytes]] = field(default_factory=list)
    error: str | None = None
    closed: bool = False

    def send(self, topic: str, *, key: bytes | None, value: bytes) -> None:
        if self.error:
            raise KafkaError(self.error)
        self.sent.append((topic, key, value))

    def send_many(self, topic: str, messages, **_) -> int:
        """Batched publish, added for `github.events` (S15P21E102-144).

        `jobs.collected` does not use it — four messages a day need no
        batching — but the fake has to satisfy the whole protocol or
        `test_fake_transport_satisfies_the_protocol` stops meaning anything.
        """

        if self.error:
            raise KafkaError(self.error)
        count = 0
        for key, value in messages:
            self.sent.append((topic, key, value))
            count += 1
        return count

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class FakeRecord:
    """The fields `CollectionEventPublisher` reads off a `RunRecord`."""

    run_name: str = "worknet-morning"
    site: str = "WORKNET"
    status: str = "SUCCESS"
    records: int = 158
    finished_at: str = "2026-09-08T00:32:14+00:00"
    pipeline_run_id: str | None = "WORKNET-20260908T003000Z"


RUN_PATH = "hdfs:///gitjob/raw/worknet/dt=2026-09-08/WORKNET-20260908T003000Z"


def _make_run(
    tmp_path: Path,
    *,
    upload: dict | None = None,
    manifest: dict | None = None,
) -> Path:
    run_dir = tmp_path / "WORKNET-20260908T003000Z"
    run_dir.mkdir(parents=True, exist_ok=True)
    if upload is not None:
        (run_dir / RAW_UPLOAD_RECORD).write_text(json.dumps(upload), encoding="utf-8")
    if manifest is not None:
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def _default_upload() -> dict:
    return {
        "run_path": RUN_PATH,
        "uploaded": [f"{RUN_PATH}/job_analysis_input.json", f"{RUN_PATH}/postings.csv"],
        "unchanged": [f"{RUN_PATH}/manifest.json"],
        "failed": [],
    }


def _default_manifest() -> dict:
    return {
        "source_site": "WORKNET",
        "collector_version": "worknet-collector/v1",
        "dataset_snapshot_id": "WORKNET-2026-09-06-2026-09-08",
        "pipeline_run_id": "WORKNET-20260908T003000Z",
    }


# --- envelope -----------------------------------------------------------


def test_envelope_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone"):
        EventEnvelope(
            source="worknet",
            source_id="RUN",
            event_type=COLLECTION_EVENT_TYPE,
            # Deliberately naive: this is the value under test.
            occurred_at=datetime(2026, 9, 8, 0, 32),  # noqa: DTZ001
            ingested_at=datetime.now(UTC),
        )


def test_envelope_omits_absent_optional_keys() -> None:
    body = EventEnvelope(
        source="worknet",
        source_id="RUN",
        event_type=COLLECTION_EVENT_TYPE,
        occurred_at=datetime.now(UTC),
        ingested_at=datetime.now(UTC),
    ).as_dict()
    assert "event_id" not in body
    assert "trace_id" not in body
    assert body["schema_version"] == "1"


# --- payload assembly ---------------------------------------------------


def test_event_carries_run_identity_and_raw_location(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path, upload=_default_upload(), manifest=_default_manifest()
    )
    envelope, reason = build_collection_event(FakeRecord(), run_dir=run_dir)

    assert reason is None
    assert envelope is not None
    assert envelope.source == "worknet"
    assert envelope.source_id == "WORKNET-20260908T003000Z"
    assert envelope.event_id == "jobs-WORKNET-20260908T003000Z"

    payload = envelope.payload
    assert payload["record_count"] == 158
    assert payload["run_path"] == RUN_PATH
    assert payload["collector_version"] == "worknet-collector/v1"
    assert payload["dataset_snapshot_id"] == "WORKNET-2026-09-06-2026-09-08"
    # Both uploaded and already-present files are addressable by a consumer.
    assert len(payload["files"]) == 3


def test_postings_never_appear_in_the_payload(tmp_path: Path) -> None:
    """Claim Check: the topic carries a pointer, not the postings."""

    run_dir = _make_run(
        tmp_path, upload=_default_upload(), manifest=_default_manifest()
    )
    (run_dir / "job_analysis_input.json").write_text(
        json.dumps({"records": [{"title": "Backend Engineer"}]}), encoding="utf-8"
    )
    envelope, _ = build_collection_event(FakeRecord(), run_dir=run_dir)

    assert envelope is not None
    assert b"Backend Engineer" not in envelope.to_bytes()
    assert "records" not in envelope.payload


def test_ingested_at_is_separate_from_occurred_at(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path, upload=_default_upload(), manifest=_default_manifest()
    )
    later = datetime(2026, 9, 8, 1, 0, tzinfo=UTC)
    envelope, _ = build_collection_event(
        FakeRecord(), run_dir=run_dir, ingested_at=later
    )

    assert envelope is not None
    assert envelope.ingested_at - envelope.occurred_at == timedelta(
        minutes=27, seconds=46
    )


def test_manifest_is_optional(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, upload=_default_upload())
    envelope, reason = build_collection_event(FakeRecord(), run_dir=run_dir)

    assert reason is None
    assert envelope is not None
    assert "collector_version" not in envelope.payload


# --- when nothing is published -----------------------------------------


def test_unarchived_run_publishes_nothing(tmp_path: Path) -> None:
    """No Raw upload means a consumer would chase a path that is not there."""

    run_dir = _make_run(tmp_path, manifest=_default_manifest())
    envelope, reason = build_collection_event(FakeRecord(), run_dir=run_dir)

    assert envelope is None
    assert reason == "run was not archived to Raw"


def test_partial_upload_failure_publishes_nothing(tmp_path: Path) -> None:
    upload = _default_upload()
    upload["failed"] = [{"file": "postings.csv", "error": "boom"}]
    run_dir = _make_run(tmp_path, upload=upload, manifest=_default_manifest())

    envelope, reason = build_collection_event(FakeRecord(), run_dir=run_dir)

    assert envelope is None
    assert reason == "Raw upload reported failures"


def test_run_without_pipeline_run_id_publishes_nothing(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, upload=_default_upload())
    envelope, reason = build_collection_event(
        FakeRecord(pipeline_run_id=None), run_dir=run_dir
    )

    assert envelope is None
    assert reason == "run has no pipeline_run_id"


def test_empty_round_is_still_announced(tmp_path: Path) -> None:
    """Zero postings is a fact. A silent round is indistinguishable from a gap."""

    run_dir = _make_run(
        tmp_path, upload=_default_upload(), manifest=_default_manifest()
    )
    envelope, reason = build_collection_event(
        FakeRecord(status="EMPTY", records=0), run_dir=run_dir
    )

    assert reason is None
    assert envelope is not None
    assert envelope.payload["record_count"] == 0
    assert envelope.payload["status"] == "EMPTY"


# --- publishing ---------------------------------------------------------


def test_publish_sends_one_message_keyed_by_site(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path, upload=_default_upload(), manifest=_default_manifest()
    )
    transport = FakeTransport()
    result = CollectionEventPublisher(transport=transport).publish(
        FakeRecord(), run_dir=run_dir
    )

    assert result.published is True
    assert result.event_id == "jobs-WORKNET-20260908T003000Z"
    assert len(transport.sent) == 1

    topic, key, value = transport.sent[0]
    assert topic == JOBS_TOPIC
    assert key == b"worknet"
    assert json.loads(value)["event_type"] == COLLECTION_EVENT_TYPE


def test_broker_failure_does_not_raise(tmp_path: Path) -> None:
    """The postings are already archived; losing the round over a broker is worse."""

    run_dir = _make_run(
        tmp_path, upload=_default_upload(), manifest=_default_manifest()
    )
    transport = FakeTransport(error="broker down")
    result = CollectionEventPublisher(transport=transport).publish(
        FakeRecord(), run_dir=run_dir
    )

    assert result.published is False
    assert result.reason is not None and "broker down" in result.reason
    assert result.event_id == "jobs-WORKNET-20260908T003000Z"


def test_republishing_a_round_reuses_the_event_id(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path, upload=_default_upload(), manifest=_default_manifest()
    )
    transport = FakeTransport()
    publisher = CollectionEventPublisher(transport=transport)
    first = publisher.publish(FakeRecord(), run_dir=run_dir)
    second = publisher.publish(FakeRecord(), run_dir=run_dir)

    assert first.event_id == second.event_id
    assert len(transport.sent) == 2


def test_publish_record_is_written_beside_the_upload_record(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path, upload=_default_upload(), manifest=_default_manifest()
    )
    result = CollectionEventPublisher(transport=FakeTransport()).publish(
        FakeRecord(), run_dir=run_dir
    )
    path = write_publish_record(run_dir, result)

    assert path.name == PUBLISH_RECORD
    assert json.loads(path.read_text(encoding="utf-8"))["published"] is True


# --- configuration ------------------------------------------------------


def test_no_broker_configured_returns_no_publisher() -> None:
    assert transport_from_env({}) is None
    assert publisher_from_env({}) is None
    assert publisher_from_env({"KAFKA_BOOTSTRAP_SERVERS": "   "}) is None


def test_broker_list_is_split_and_topic_is_overridable() -> None:
    publisher = publisher_from_env(
        {
            "KAFKA_BOOTSTRAP_SERVERS": "a:9092, b:9092",
            "JOBS_COLLECTED_TOPIC": "jobs.collected.dev",
        }
    )

    assert publisher is not None
    assert publisher.topic == "jobs.collected.dev"
    assert publisher.transport.bootstrap_servers == ("a:9092", "b:9092")


def test_fake_transport_satisfies_the_protocol() -> None:
    assert isinstance(FakeTransport(), KafkaTransport)
