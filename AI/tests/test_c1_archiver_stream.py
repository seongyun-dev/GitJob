"""C1 Archiver envelope and path rules (S15P21E102-112).

No Spark: `c1_archiver_stream` imports `pyspark` inside `main()` only, the same
shape `repo_activity_topn.py` uses, so the decisions worth pinning — what is
accepted, where it lands, whose checkpoint it is — are testable on their own.
`AI/conftest.py` puts `Infra/spark` on the path.
"""

from __future__ import annotations

import json

import pytest
from c1_archiver_stream import (
    ARCHIVE_COLUMNS,
    C1_TOPICS,
    HISTORICAL_CUTOFF,
    REJECTED_COLUMNS,
    archive_location,
    build_parser,
    checkpoint_location,
    envelope_rejection,
    normalize_location,
    parse_utc,
    partition_date,
    rejected_location,
)


def _envelope(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": "1",
        "source": "gharchive",
        "source_id": "2026-09-05-11/12345",
        "event_type": "PushEvent",
        "occurred_at": "2026-09-05T11:04:00Z",
        "ingested_at": "2026-09-05T11:22:31Z",
        "payload": {"repo": {"id": 1}},
    }
    base.update(overrides)
    return base


# --- the subscription is the contract's, not this file's -------------------


def test_c1_does_not_subscribe_to_jobs_collected():
    """`-102` §2.3. That event is published after Raw is already written."""

    assert C1_TOPICS == ("github.events", "so.raw")
    assert "jobs.collected" not in C1_TOPICS


# --- timestamps ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-05T11:04:00Z", "2026-09-05"),
        ("2026-09-05T11:04:00+00:00", "2026-09-05"),
        # 08:30 KST on the 6th is 23:30 UTC on the 5th: the partition follows
        # UTC, the same rule GH Archive's `dt=` already uses.
        ("2026-09-06T08:30:00+09:00", "2026-09-05"),
    ],
)
def test_partition_follows_utc_occurrence(value: str, expected: str):
    assert partition_date(value) == expected


def test_a_naive_timestamp_is_refused_rather_than_assumed_utc():
    with pytest.raises(ValueError, match="timezone"):
        parse_utc("2026-09-05T11:04:00")


# --- what is accepted ------------------------------------------------------


def test_a_complete_envelope_is_accepted():
    assert envelope_rejection(_envelope()) is None


def test_optional_fields_may_be_absent():
    """`-103` §4.1 marks `event_id` and `trace_id` recommended, not required."""

    assert envelope_rejection(_envelope()) is None
    assert envelope_rejection(_envelope(event_id="e1", trace_id="tr_1")) is None


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "source",
        "source_id",
        "event_type",
        "occurred_at",
        "ingested_at",
        "payload",
    ],
)
def test_a_missing_required_field_is_named_in_the_reason(field: str):
    reason = envelope_rejection(_envelope(**{field: None}))

    assert reason is not None and field in reason


def test_a_non_object_message_is_rejected():
    assert envelope_rejection([1, 2, 3]) == "envelope is not a JSON object"


def test_an_unusable_timestamp_is_rejected_not_guessed():
    reason = envelope_rejection(_envelope(occurred_at="not-a-date"))

    assert reason is not None and "occurred_at" in reason


# --- the cutoff guard ------------------------------------------------------


def test_gharchive_history_is_left_to_the_batch_path():
    """`-144`: an hour must not arrive on both paths."""

    reason = envelope_rejection(_envelope(occurred_at="2026-08-31T23:59:59Z"))

    assert reason is not None
    assert "historical cutoff" in reason
    assert "batch path" in reason


def test_gharchive_at_and_after_the_cutoff_is_archived():
    assert envelope_rejection(_envelope(occurred_at=HISTORICAL_CUTOFF)) is None
    assert envelope_rejection(_envelope(occurred_at="2026-09-01T00:00:01Z")) is None


def test_the_cutoff_applies_only_to_sources_with_a_batch_path():
    """Stack Overflow's dump (`-113`) does not publish to `so.raw`."""

    old = _envelope(source="stackexchange", occurred_at="2026-05-01T00:00:00Z")

    assert envelope_rejection(old) is None


def test_the_rejection_is_a_reason_a_person_can_act_on():
    reason = envelope_rejection(_envelope(occurred_at="2026-08-01T00:00:00Z"))

    assert reason is not None
    # It names the instant and the boundary, so a producer whose boundary
    # disagrees can be compared against ours without reading this code.
    assert "2026-08-01" in reason and HISTORICAL_CUTOFF in reason


# --- paths -----------------------------------------------------------------


def test_each_topic_gets_its_own_checkpoint():
    """Separate directories are what make independent progress observable."""

    a = checkpoint_location("github.events")
    b = checkpoint_location("so.raw")

    assert a != b
    assert a == "/gitjob/checkpoints/c1/github.events"


def test_a_different_consumer_never_shares_a_checkpoint():
    """C1 and C2 read the same topic and must not share progress."""

    assert checkpoint_location("github.events", consumer="c1") != checkpoint_location(
        "github.events", consumer="c2"
    )


def test_the_archive_stays_out_of_the_raw_layer():
    """Raw holds untouched source bytes and `-190` counts files there."""

    location = archive_location("github.events")

    assert location.startswith("/gitjob/parquet/")
    assert "/raw/" not in location


# --- the authority-less scheme this project writes -------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # What `.env.example` and `raw_sink.py` actually write. Spark's
        # checkpoint resolver rejects it: "Uri without authority".
        ("hdfs:///gitjob/parquet", "/gitjob/parquet"),
        ("file:///tmp/out", "/tmp/out"),
        # An authority is a real address; leave it alone.
        ("hdfs://hdfs-namenode:8020/gitjob", "hdfs://hdfs-namenode:8020/gitjob"),
        # No scheme at all already resolves against fs.defaultFS.
        ("/gitjob/parquet", "/gitjob/parquet"),
    ],
)
def test_an_authority_less_scheme_becomes_a_default_fs_path(given: str, expected: str):
    assert normalize_location(given) == expected


def test_a_named_namenode_survives_into_the_checkpoint_path():
    location = checkpoint_location(
        "so.raw", checkpoint_root="hdfs://hdfs-namenode:8020/ckpt"
    )

    assert location == "hdfs://hdfs-namenode:8020/ckpt/c1/so.raw"


def test_rejected_records_land_beside_the_archive_not_inside_it():
    accepted = archive_location("github.events")
    rejected = rejected_location("github.events")

    assert rejected != accepted
    assert not rejected.startswith(f"{accepted}/")


@pytest.mark.parametrize("topic", ["", "   "])
def test_a_blank_topic_is_refused(topic: str):
    with pytest.raises(ValueError, match="topic"):
        archive_location(topic)


# --- the command line ------------------------------------------------------


def test_bootstrap_servers_is_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_defaults_subscribe_to_both_c1_topics():
    arguments = build_parser().parse_args(["--bootstrap-servers", "kafka:9092"])

    assert arguments.topics == "github.events,so.raw"
    assert arguments.starting_offsets == "earliest"
    assert arguments.cutoff == HISTORICAL_CUTOFF


def test_no_group_id_option_is_offered():
    """`-102` §5 option 1: the checkpoint is the only record of progress.

    An option here would invite a second one, which is the state that leaves a
    restart with no rule for which offset to believe.
    """

    help_text = build_parser().format_help()

    assert "group.id" not in help_text
    assert "group-id" not in help_text


def test_the_payload_round_trips_as_text():
    """The archiver stores what arrived; it does not reshape the payload."""

    payload = {"repo": {"id": 1, "name": "a/b"}, "actor": {"login": "누구"}}
    envelope = _envelope(payload=payload)

    assert envelope_rejection(envelope) is None
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


# --- the archive schema is declared, not inferred --------------------------


def test_a_row_carries_exactly_the_declared_columns():
    """Inference broke on the first real run: a batch where every `event_id`
    was absent raised CANNOT_DETERMINE_TYPE. Declaring the schema fixes that
    and also stops the archive's columns drifting with one batch's contents,
    so the row builder and the declaration must not diverge.
    """

    row = _row_for_test()

    assert list(row) == [name for name, _ in ARCHIVE_COLUMNS]


def test_the_offset_travels_with_the_row():
    """`-102` §2.2 makes the event offset C1's deduplication key."""

    row = _row_for_test()

    assert row["kafka_topic"] == "github.events"
    assert row["kafka_partition"] == 3
    assert row["kafka_offset"] == 8_840_611


def test_absent_optional_fields_become_null_not_empty_string():
    """A declared string column distinguishes 'absent' from 'blank'."""

    row = _row_for_test()

    assert row["event_id"] is None
    assert row["trace_id"] is None


def test_the_partition_column_is_last_so_it_matches_partition_by():
    assert ARCHIVE_COLUMNS[-1] == ("dt", "string")


def test_a_rejected_row_keeps_enough_to_locate_the_message():
    names = [name for name, _ in REJECTED_COLUMNS]

    assert {"kafka_topic", "kafka_partition", "kafka_offset"} <= set(names)
    assert "reject_reason" in names
    assert "raw_value" in names


def _row_for_test() -> dict[str, object]:
    from c1_archiver_stream import _row

    return _row(
        _envelope(),
        topic="github.events",
        partition=3,
        offset=8_840_611,
        kafka_timestamp=None,
        raw_value="{}",
    )
