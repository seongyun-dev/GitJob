"""Recovery files must make the same accept/reject decision as publication."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest

from collector.gharchive.recovery import (
    BUILD_SPEC_SCHEMA_VERSION,
    build_manifest,
    build_recovery_file,
)
from common.events import EventEnvelope


def _event(event_id: str, payload: str = "ok") -> dict[str, object]:
    return {
        "id": event_id,
        "type": "PushEvent",
        "created_at": "2026-08-31T00:00:00Z",
        "repo": {"id": 1, "name": "owner/repo"},
        "payload": {"value": payload},
    }


def _write_source(path, lines):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for line in lines:
            stream.write(line + "\n")


def test_builder_keeps_only_records_the_publisher_can_send(tmp_path, monkeypatch):
    source = tmp_path / "source.json.gz"
    output = tmp_path / "output.json.gz"
    valid = _event("1")
    too_large = _event("2", "x" * 2_000)
    _write_source(source, [json.dumps(valid), "not-json", json.dumps(too_large)])

    monkeypatch.setattr("collector.gharchive.recovery.MAX_MESSAGE_BYTES", 800)
    result = build_recovery_file(
        source,
        output,
        hour="2026-08-31T00:00:00Z",
        source_uri="hdfs:///source.json.gz",
        output_uri="hdfs:///recovery.json.gz",
        ingested_at=datetime(2026, 9, 18, 0, 0, 0, 123456, tzinfo=UTC),
    )

    with gzip.open(output, "rt", encoding="utf-8") as stream:
        assert [json.loads(line) for line in stream] == [valid]
    assert result["source_event_count"] == 3
    assert result["accepted_event_count"] == 1
    assert result["rejected_oversized_count"] == 1
    assert result["skipped_line_count"] == 1


def test_builder_refuses_to_replace_an_immutable_output(tmp_path):
    source = tmp_path / "source.json.gz"
    output = tmp_path / "output.json.gz"
    _write_source(source, [json.dumps(_event("1"))])
    output.write_bytes(b"already published")

    with pytest.raises(FileExistsError, match="already exists"):
        build_recovery_file(
            source,
            output,
            hour="2026-08-31T00:00:00Z",
            source_uri="hdfs:///source.json.gz",
            output_uri="hdfs:///recovery.json.gz",
        )


def test_builder_is_deterministic_for_distinct_immutable_outputs(tmp_path):
    source = tmp_path / "source.json.gz"
    first = tmp_path / "first.json.gz"
    second = tmp_path / "second.json.gz"
    _write_source(source, [json.dumps(_event("1")), json.dumps(_event("2"))])

    first_result = build_recovery_file(
        source,
        first,
        hour="2026-08-31T00:00:00Z",
        source_uri="hdfs:///source.json.gz",
        output_uri="hdfs:///first.json.gz",
    )
    second_result = build_recovery_file(
        source,
        second,
        hour="2026-08-31T00:00:00Z",
        source_uri="hdfs:///source.json.gz",
        output_uri="hdfs:///second.json.gz",
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_result["sha256"] == second_result["sha256"]


def test_manifest_builder_rejects_one_source_path_reused_for_multiple_hours(tmp_path):
    source = tmp_path / "source.json.gz"
    _write_source(source, [json.dumps(_event("1"))])
    period_start = datetime(2026, 8, 31, tzinfo=UTC)
    files = []
    for index in range(168):
        moment = period_start + timedelta(hours=index)
        hour = moment.isoformat().replace("+00:00", "Z")
        files.append(
            {
                "hour": hour,
                "source_path": str(source),
                "source_uri": f"hdfs:///raw/{index}.json.gz",
                "output_path": str(tmp_path / "output" / f"{index}.json.gz"),
                "uri": f"hdfs:///recovery/{index}.json.gz",
            }
        )

    with pytest.raises(ValueError, match="duplicate recovery source path"):
        build_manifest(
            {
                "schema_version": BUILD_SPEC_SCHEMA_VERSION,
                "period_start": "2026-08-31T00:00:00Z",
                "period_end": "2026-09-07T00:00:00Z",
                "files": files,
            }
        )

    assert not (tmp_path / "output").exists()


def test_fixed_timestamp_has_publisher_length_and_envelope_contract():
    envelope = EventEnvelope(
        source="gharchive",
        source_id="hour/1",
        event_type="PushEvent",
        occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
        ingested_at=datetime(2026, 9, 18, 0, 0, 0, 123456, tzinfo=UTC),
        payload=_event("1"),
        event_id="gharchive-1",
    )
    assert b"123456" in envelope.to_bytes()
