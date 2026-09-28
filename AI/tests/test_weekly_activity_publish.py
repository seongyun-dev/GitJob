"""Weekly Repo Activity snapshot publication (S15P21E102-225).

No HDFS and no broker: a recording fake stands in for `WebHdfsClient` and
another for `KafkaTransport`, following `test_job_raw_sink.py`.  What is
asserted here is the order the two happen in, and what happens when either
fails — the properties C depends on when it treats a manifest as "this week is
final".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from common.kafka import KafkaError
from github.weekly_activity_publish import (
    COMPLETION_EVENT_TYPE,
    MANIFEST_NAME,
    ROW_DIGEST_FORMAT,
    WEEKLY_COMPLETED_TOPIC,
    WEEKLY_MANIFEST_SCHEMA_VERSION,
    WeeklyPublishError,
    WeeklySnapshotWeek,
    build_manifest,
    completion_envelope,
    manifest_uri_for,
    publish_weekly_snapshot,
    validate_week_start,
    weeks_from_summary,
)

SNAPSHOT = "s15p21e102-224-stream-20260912"
MONDAY = "2026-08-31"
NEXT_MONDAY = "2026-09-07"
PERIOD_ROOT = "hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-09"
ROOT = f"{PERIOD_ROOT}/snapshot={SNAPSHOT}"
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
NOW = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


def root_for(snapshot_id):
    """The snapshot id is part of the path, so a new id is a new directory."""

    return f"{PERIOD_ROOT}/snapshot={snapshot_id}"


def week(week_start=MONDAY, digest=DIGEST, rows=3, snapshot_id=SNAPSHOT):
    return WeeklySnapshotWeek(
        week_start=week_start,
        data_uri=f"{root_for(snapshot_id)}/week={week_start}",
        row_count=rows,
        row_digest=digest,
    )


class FakePublisher:
    """`store_immutable` with the semantics `common.webhdfs` implements."""

    def __init__(self, existing=None):
        self.objects = dict(existing or {})
        self.writes = []

    def store_immutable(self, path, content):
        self.writes.append(path)
        if path in self.objects:
            if self.objects[path] != content:
                raise FileExistsError("immutable object exists with different content")
            return f"hdfs://{path}"
        self.objects[path] = content
        return f"hdfs://{path}"

    def read(self, path):
        return self.objects[path]


class FakeTransport:
    def __init__(self, fail_on=None):
        self.sent = []
        self.fail_on = fail_on

    def send(self, topic, *, key, value):
        if self.fail_on is not None and len(self.sent) == self.fail_on:
            raise KafkaError("broker refused")
        self.sent.append((topic, key, json.loads(value)))

    def send_many(self, topic, messages, **_):  # pragma: no cover - unused here
        raise NotImplementedError

    def close(self):  # pragma: no cover - unused here
        pass


# --- the manifest ----------------------------------------------------------


def test_manifest_carries_exactly_the_agreed_fields():
    manifest = build_manifest(SNAPSHOT, week())

    assert manifest == {
        "schema_version": WEEKLY_MANIFEST_SCHEMA_VERSION,
        "dataset_snapshot_id": SNAPSHOT,
        "week_start": MONDAY,
        "data_uri": f"{ROOT}/week={MONDAY}",
        "row_count": 3,
        "row_digest": {"format": ROW_DIGEST_FORMAT, "value": DIGEST},
    }


def test_manifest_carries_no_statistics():
    """`selected_repo_count`, coverage and trend are C's, not A's."""

    manifest = build_manifest(SNAPSHOT, week())

    for forbidden in ("selected_repo_count", "coverage", "tech_id", "trend"):
        assert forbidden not in json.dumps(manifest)


def test_manifest_matches_the_published_contract():
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/data/contracts/repo-activity-weekly-publish-manifest-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema = pytest.importorskip("jsonschema")

    jsonschema.validate(build_manifest(SNAPSHOT, week()), schema)


def test_manifest_sits_inside_the_week_it_describes():
    assert manifest_uri_for(f"{ROOT}/week={MONDAY}") == (
        f"{ROOT}/week={MONDAY}/{MANIFEST_NAME}"
    )
    assert manifest_uri_for(f"{ROOT}/week={MONDAY}/") == (
        f"{ROOT}/week={MONDAY}/{MANIFEST_NAME}"
    )


def test_week_start_must_be_a_monday():
    assert validate_week_start(MONDAY) == MONDAY
    with pytest.raises(ValueError, match="Monday"):
        validate_week_start("2026-09-01")


@pytest.mark.parametrize("value", ["2026-9-7", "20260907", "2026-09-07T00:00:00Z"])
def test_week_start_must_be_a_canonical_iso_date(value):
    with pytest.raises(ValueError):
        validate_week_start(value)


def test_week_start_rule_matches_the_spark_job():
    """The one rule this module repeats instead of importing."""

    from jobs.repo_activity_weekly import validate_week_start as spark_rule

    assert spark_rule(MONDAY).isoformat() == validate_week_start(MONDAY)
    with pytest.raises(ValueError):
        spark_rule("2026-09-01")


@pytest.mark.parametrize("digest", ["", "z" * 64, "A" * 64, "a" * 63, DIGEST[:10]])
def test_a_digest_that_is_not_sha256_is_refused(digest):
    with pytest.raises(ValueError, match="row_digest"):
        week(digest=digest)


def test_a_negative_row_count_is_refused():
    with pytest.raises(ValueError, match="row_count"):
        WeeklySnapshotWeek(MONDAY, f"{ROOT}/week={MONDAY}", -1, DIGEST)


# --- the order: manifest, then event ---------------------------------------


def test_a_week_is_announced_only_after_its_manifest_is_readable():
    publisher = FakePublisher()
    transport = FakeTransport()

    result = publish_weekly_snapshot(
        SNAPSHOT, [week()], publisher=publisher, transport=transport, now=NOW
    )

    assert publisher.writes == [f"{ROOT}/week={MONDAY}/{MANIFEST_NAME}"]
    assert result.events_published == (MONDAY,)
    topic, key, body = transport.sent[0]
    assert topic == WEEKLY_COMPLETED_TOPIC
    assert key == f"{SNAPSHOT}/{MONDAY}".encode()
    assert body["payload"] == {
        "dataset_snapshot_id": SNAPSHOT,
        "week_start": MONDAY,
        "manifest_uri": f"hdfs://{ROOT}/week={MONDAY}/{MANIFEST_NAME}",
    }
    assert body["event_type"] == COMPLETION_EVENT_TYPE


def test_no_event_is_sent_when_the_manifest_cannot_be_published():
    class Refusing(FakePublisher):
        def store_immutable(self, path, content):
            raise OSError("webhdfs is unreachable")

    transport = FakeTransport()

    with pytest.raises(OSError):
        publish_weekly_snapshot(
            SNAPSHOT, [week()], publisher=Refusing(), transport=transport, now=NOW
        )

    assert transport.sent == []


def test_no_event_is_sent_when_the_manifest_does_not_read_back():
    class Lying(FakePublisher):
        def read(self, path):
            return b"{}"

    transport = FakeTransport()

    with pytest.raises(WeeklyPublishError, match="read-back"):
        publish_weekly_snapshot(
            SNAPSHOT, [week()], publisher=Lying(), transport=transport, now=NOW
        )

    assert transport.sent == []


def test_a_failed_event_reports_that_the_manifest_already_landed():
    publisher = FakePublisher()

    with pytest.raises(WeeklyPublishError, match="manifest published"):
        publish_weekly_snapshot(
            SNAPSHOT,
            [week()],
            publisher=publisher,
            transport=FakeTransport(fail_on=0),
            now=NOW,
        )

    assert publisher.objects  # the week is complete, only unannounced


def test_manifests_are_published_without_a_broker():
    """A missing broker is a reason not to announce, not to leave data unmarked."""

    publisher = FakePublisher()

    result = publish_weekly_snapshot(
        SNAPSHOT, [week()], publisher=publisher, transport=None, now=NOW
    )

    assert result.manifest_uris == {
        MONDAY: f"hdfs://{ROOT}/week={MONDAY}/{MANIFEST_NAME}"
    }
    assert result.events_published == ()


# --- one per week, not one per snapshot ------------------------------------


def test_each_week_gets_its_own_manifest_and_its_own_event():
    publisher = FakePublisher()
    transport = FakeTransport()

    result = publish_weekly_snapshot(
        SNAPSHOT,
        [week(MONDAY), week(NEXT_MONDAY, digest=OTHER_DIGEST)],
        publisher=publisher,
        transport=transport,
        now=NOW,
    )

    assert len(publisher.writes) == 2
    assert result.events_published == (MONDAY, NEXT_MONDAY)
    assert [body["payload"]["week_start"] for _, _, body in transport.sent] == [
        MONDAY,
        NEXT_MONDAY,
    ]


def test_the_same_week_twice_in_one_call_is_refused():
    with pytest.raises(ValueError, match="repeat"):
        publish_weekly_snapshot(
            SNAPSHOT,
            [week(), week()],
            publisher=FakePublisher(),
            transport=FakeTransport(),
            now=NOW,
        )


def test_publishing_nothing_is_refused():
    with pytest.raises(ValueError, match="no weeks"):
        publish_weekly_snapshot(
            SNAPSHOT, [], publisher=FakePublisher(), transport=FakeTransport(), now=NOW
        )


# --- replay and immutability -----------------------------------------------


def test_republishing_identical_rows_is_idempotent():
    publisher = FakePublisher()
    first = publish_weekly_snapshot(
        SNAPSHOT, [week()], publisher=publisher, transport=FakeTransport(), now=NOW
    )
    second = publish_weekly_snapshot(
        SNAPSHOT, [week()], publisher=publisher, transport=FakeTransport(), now=NOW
    )

    assert first.manifest_uris == second.manifest_uris
    assert len(publisher.objects) == 1


def test_the_same_snapshot_id_with_different_rows_is_refused():
    publisher = FakePublisher()
    publish_weekly_snapshot(
        SNAPSHOT, [week()], publisher=publisher, transport=FakeTransport(), now=NOW
    )

    with pytest.raises(WeeklyPublishError, match="new dataset_snapshot_id"):
        publish_weekly_snapshot(
            SNAPSHOT,
            [week(digest=OTHER_DIGEST)],
            publisher=publisher,
            transport=FakeTransport(),
            now=NOW,
        )


def test_a_late_event_is_a_new_snapshot_not_an_edit():
    """The late-arrival policy, made executable."""

    publisher = FakePublisher()
    publish_weekly_snapshot(
        SNAPSHOT, [week()], publisher=publisher, transport=FakeTransport(), now=NOW
    )
    before = dict(publisher.objects)

    corrected = "s15p21e102-224-stream-20260913"
    result = publish_weekly_snapshot(
        corrected,
        [week(digest=OTHER_DIGEST, snapshot_id=corrected)],
        publisher=publisher,
        transport=FakeTransport(),
        now=NOW,
    )

    # The original manifest is byte-identical to what C first read.
    for path, content in before.items():
        assert publisher.objects[path] == content
    # The corrected week lives beside it under its own snapshot id, not on top.
    assert result.manifest_uris[MONDAY] == (
        f"hdfs://{root_for(corrected)}/week={MONDAY}/{MANIFEST_NAME}"
    )
    assert len(publisher.objects) == 2


def test_the_event_identity_is_snapshot_and_week():
    """`-102` §4.1 dedups on (source, source_id, schema_version)."""

    envelope = completion_envelope(
        SNAPSHOT, week(), "hdfs:///x/_SUCCESS.json", ingested_at=NOW
    )

    assert envelope.source_id == f"{SNAPSHOT}/{MONDAY}"
    assert envelope.occurred_at == datetime(2026, 8, 31, tzinfo=UTC)


# --- reading the Spark run summary -----------------------------------------


def _summary(**overrides):
    entry = {
        "uri": f"{ROOT}/week={MONDAY}",
        "row_count": 3,
        "row_digest": DIGEST,
        "row_digest_format": ROW_DIGEST_FORMAT,
        "event_count": 9,
        "fully_within_period": True,
    }
    entry.update(overrides)
    return {"output": {"weeks_written": {MONDAY: entry}}}


def test_weeks_are_read_from_the_spark_run_summary():
    weeks = weeks_from_summary(_summary())

    assert weeks == (week(),)


def test_weeks_come_back_in_chronological_order():
    summary = _summary()
    summary["output"]["weeks_written"][NEXT_MONDAY] = {
        "uri": f"{ROOT}/week={NEXT_MONDAY}",
        "row_count": 1,
        "row_digest": OTHER_DIGEST,
    }

    assert [item.week_start for item in weeks_from_summary(summary)] == [
        MONDAY,
        NEXT_MONDAY,
    ]


@pytest.mark.parametrize("field_name", ["uri", "row_count", "row_digest"])
def test_a_summary_missing_a_required_field_is_refused(field_name):
    summary = _summary()
    del summary["output"]["weeks_written"][MONDAY][field_name]

    with pytest.raises(ValueError, match=field_name):
        weeks_from_summary(summary)


@pytest.mark.parametrize(
    "summary", [{}, {"output": {}}, {"output": {"weeks_written": {}}}]
)
def test_a_summary_without_written_weeks_is_refused(summary):
    with pytest.raises(ValueError):
        weeks_from_summary(summary)
