"""C2 message resolution, where the three topics stop looking alike.

No network: the Claim Check cases drive a fake WebHDFS transport, following
`test_job_raw_sink.py`.
"""

from __future__ import annotations

import json

import pytest
from common.kafka import ConsumedMessage
from common.webhdfs import WebHdfsClient, WebHdfsResponse
from extractor.contracts import C2_TOPICS, CLAIM_CHECK_TOPICS
from extractor.resolve import (
    BATCH_FILENAME,
    RecordResolver,
    ResolutionError,
    UnusableMessage,
    parse_envelope,
)

RUN_PATH = "hdfs:///gitjob/raw/worknet/dt=2026-09-10/WORKNET-20260910T050845Z"


def _envelope(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": "1",
        "source": "gharchive",
        "source_id": "2026-09-01T00:00:00Z/14172383030",
        "event_type": "PushEvent",
        "occurred_at": "2026-09-01T00:00:01Z",
        "ingested_at": "2026-09-09T06:04:17Z",
        "payload": {"repo": {"id": 1}},
    }
    base.update(overrides)
    return base


def _message(envelope: object, *, topic: str = "github.events") -> ConsumedMessage:
    return ConsumedMessage(
        topic=topic,
        partition=3,
        offset=8_840_611,
        key=None,
        value=json.dumps(envelope).encode("utf-8"),
    )


def _claim_check(**payload: object) -> ConsumedMessage:
    body: dict[str, object] = {
        "run_name": "worknet-morning",
        "site": "WORKNET",
        "pipeline_run_id": "WORKNET-20260910T050845Z",
        "record_count": 2,
        "status": "SUCCESS",
        "run_path": RUN_PATH,
    }
    body.update(payload)
    return _message(
        _envelope(
            source="worknet",
            source_id="WORKNET-20260910T050845Z",
            event_type="job.collection.completed",
            payload=body,
        ),
        topic="jobs.collected",
    )


class FakeTransport:
    """Serves one batch file; anything else is a 404."""

    def __init__(self, batch: object | None, *, raw: bytes | None = None):
        self.body = raw if raw is not None else json.dumps(batch).encode("utf-8")
        self.reads: list[str] = []

    def request(self, method, url, *, body=None, timeout):
        assert timeout > 0
        if "op=GETFILESTATUS" in url:
            return WebHdfsResponse(200, {}, b'{"FileStatus":{}}')
        if "op=OPEN" in url:
            self.reads.append(url)
            return WebHdfsResponse(200, {}, self.body)
        raise AssertionError(f"unexpected {method} {url}")


def _resolver(batch: object | None, **kwargs: object) -> RecordResolver:
    transport = FakeTransport(batch, **kwargs)
    client = WebHdfsClient(
        base_url="http://hdfs-namenode:9870/webhdfs/v1", transport=transport
    )
    return RecordResolver(client=client)


def _batch(*ids: str) -> dict[str, object]:
    return {
        "schema_version": "job-analysis-input/v1",
        "pipeline_run_id": "WORKNET-20260910T050845Z",
        "records": [{"source_record_id": i, "title": f"job {i}"} for i in ids],
    }


# --- the subscription differs from C1's ------------------------------------


def test_c2_subscribes_to_all_three_topics():
    """`-102` §2.3. C1 skips `jobs.collected`; C2 must not."""

    assert C2_TOPICS == ("github.events", "so.raw", "jobs.collected")
    assert CLAIM_CHECK_TOPICS == {"jobs.collected"}


# --- inline topics ---------------------------------------------------------


def test_an_inline_topic_yields_exactly_one_record():
    records = RecordResolver().resolve(_message(_envelope()))

    assert len(records) == 1
    assert records[0].source == "gharchive"
    assert records[0].source_id == "2026-09-01T00:00:00Z/14172383030"
    assert records[0].payload == {"repo": {"id": 1}}


def test_the_kafka_position_travels_as_provenance():
    record = RecordResolver().resolve(_message(_envelope()))[0]

    assert record.origin.topic == "github.events"
    assert record.origin.partition == 3
    assert record.origin.offset == 8_840_611


def test_an_inline_topic_needs_no_webhdfs_client():
    """A deployment reading only `github.events` must not require a NameNode."""

    assert RecordResolver(client=None).resolve(_message(_envelope()))


# --- the Claim Check fan-out -----------------------------------------------


def test_a_collection_run_fans_out_to_every_posting():
    """One message, many records. The whole reason C2 differs per topic."""

    records = _resolver(_batch("WORKNET:1", "WORKNET:2")).resolve(_claim_check())

    assert len(records) == 2
    assert [r.source_id for r in records] == ["WORKNET:1", "WORKNET:2"]


def test_the_fact_key_is_the_posting_not_the_run():
    """The envelope's `source_id` is the run (`-103` §4.2).

    Using it would collapse every posting in a run onto one upsert key.
    """

    records = _resolver(_batch("WORKNET:1", "WORKNET:2")).resolve(_claim_check())

    assert all(
        r.origin.envelope_source_id == "WORKNET-20260910T050845Z" for r in records
    )
    assert {r.source_id for r in records} == {"WORKNET:1", "WORKNET:2"}
    assert "WORKNET-20260910T050845Z" not in {r.source_id for r in records}


def test_the_batch_file_is_the_one_the_collector_publishes_first():
    resolver = _resolver(_batch("WORKNET:1", "WORKNET:2"))
    resolver.resolve(_claim_check())

    assert resolver.client.transport.reads
    assert BATCH_FILENAME in resolver.client.transport.reads[0]


def test_an_empty_run_resolves_to_nothing_without_failing():
    """`-103` §4.4 publishes 0-record runs on purpose: 0 is not a gap."""

    records = _resolver(_batch()).resolve(_claim_check(record_count=0))

    assert records == ()


# --- the Claim Check's own failure mode ------------------------------------


def test_a_count_mismatch_is_refused():
    """The pointer and the data drifting apart is what Claim Check risks."""

    with pytest.raises(UnusableMessage, match="disagree"):
        _resolver(_batch("WORKNET:1")).resolve(_claim_check(record_count=2))


def test_the_mismatch_names_both_numbers():
    with pytest.raises(UnusableMessage) as caught:
        _resolver(_batch("WORKNET:1")).resolve(_claim_check(record_count=9))

    assert "1 records" in str(caught.value) and "9" in str(caught.value)


def test_a_missing_count_is_allowed_but_not_invented():
    records = _resolver(_batch("WORKNET:1")).resolve(_claim_check(record_count=None))

    assert len(records) == 1


# --- transient versus permanent --------------------------------------------


def test_an_unreachable_namenode_is_retryable_not_fatal():
    """Job postings cannot be collected again; a run must not hit the DLQ."""

    class Down:
        def request(self, method, url, *, body=None, timeout):
            return WebHdfsResponse(500, {}, b"namenode is down")

    resolver = RecordResolver(
        client=WebHdfsClient(
            base_url="http://hdfs-namenode:9870/webhdfs/v1", transport=Down()
        )
    )

    with pytest.raises(ResolutionError) as caught:
        resolver.resolve(_claim_check())
    assert not isinstance(caught.value, UnusableMessage)


def test_a_missing_client_is_retryable_because_an_operator_can_fix_it():
    with pytest.raises(ResolutionError) as caught:
        RecordResolver(client=None).resolve(_claim_check())

    assert not isinstance(caught.value, UnusableMessage)
    assert "WEBHDFS_URL" in str(caught.value)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"run_path": ""}, "no run_path"),
        ({"run_path": "not-a-path"}, "not an HDFS path"),
        ({"record_count": "many"}, "not a number"),
    ],
)
def test_a_broken_claim_check_is_permanent(payload: dict, match: str):
    """Retrying these forever would hold the partition."""

    with pytest.raises(UnusableMessage, match=match):
        _resolver(_batch("WORKNET:1")).resolve(_claim_check(**payload))


def test_a_batch_record_without_an_id_is_permanent():
    batch = {"records": [{"title": "no id here"}]}

    with pytest.raises(UnusableMessage, match="source_record_id"):
        _resolver(batch).resolve(_claim_check(record_count=1))


def test_a_batch_that_is_not_json_is_permanent():
    with pytest.raises(UnusableMessage, match="not JSON"):
        _resolver(None, raw=b"<html>404</html>").resolve(_claim_check())


# --- the envelope ----------------------------------------------------------


def test_a_message_that_is_not_json_is_permanent():
    message = ConsumedMessage("github.events", 0, 0, None, b"not json")

    with pytest.raises(UnusableMessage, match="not JSON"):
        parse_envelope(message)


@pytest.mark.parametrize(
    "field",
    ["schema_version", "source", "source_id", "event_type", "occurred_at"],
)
def test_a_missing_envelope_field_is_permanent(field: str):
    broken = _envelope()
    del broken[field]

    with pytest.raises(UnusableMessage, match="4.1"):
        parse_envelope(_message(broken))


def test_an_unknown_envelope_field_is_ignored_not_rejected():
    """A producer's additive change must not stop a partition.

    `schema_version` is the declared way to evolve the envelope, so an extra
    field is a producer bug — but one that costs a paused topic if a consumer
    raises on it.
    """

    envelope = parse_envelope(
        _message(_envelope(some_new_field="from a newer producer"))
    )

    assert envelope.source == "gharchive"


def test_optional_envelope_fields_stay_optional():
    """`-103` §4.1 marks `event_id` and `trace_id` recommended, not required."""

    envelope = parse_envelope(_message(_envelope()))

    assert envelope.event_id is None and envelope.trace_id is None
