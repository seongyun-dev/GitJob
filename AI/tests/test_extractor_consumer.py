"""C2's commit ordering — the rules that decide whether work is lost or stuck.

No broker: a fake transport records what was polled and committed.
"""

from __future__ import annotations

import json

import pytest
from common.kafka import ConsumedMessage
from extractor.consumer import ExtractorConsumer, Outcome, summarize
from extractor.contracts import FactRecord, ResolvedRecord
from extractor.resolve import RecordResolver, ResolutionError, UnusableMessage


def _message(offset: int = 0, *, value: bytes | None = None) -> ConsumedMessage:
    envelope = {
        "schema_version": "1",
        "source": "gharchive",
        "source_id": f"event-{offset}",
        "event_type": "PushEvent",
        "occurred_at": "2026-09-01T00:00:01Z",
        "ingested_at": "2026-09-09T06:04:17Z",
        "payload": {"repo": {"id": offset}},
    }
    return ConsumedMessage(
        topic="github.events",
        partition=0,
        offset=offset,
        key=None,
        value=value if value is not None else json.dumps(envelope).encode(),
    )


class FakeConsumer:
    def __init__(self, batches: list[list[ConsumedMessage]]):
        self.batches = batches
        self.commits = 0
        self.closed = False

    def poll(self, timeout_ms: int) -> list[ConsumedMessage]:
        return self.batches.pop(0) if self.batches else []

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


class FakeStore:
    def __init__(self) -> None:
        self.written: list[FactRecord] = []
        self.calls = 0

    def upsert(self, facts) -> int:
        self.calls += 1
        self.written.extend(facts)
        return len(facts)


class OneFactSeam:
    """The simplest thing AI팀's side could be."""

    dict_version = "registry-v1"

    def extract(self, record: ResolvedRecord):
        return [
            FactRecord(
                source=record.source,
                source_id=record.source_id,
                dict_version=self.dict_version,
                payload={"seen": True},
                origin=record.origin,
            )
        ]


class SilentSeam:
    def extract(self, record: ResolvedRecord):
        return []


class BrokenResolver(RecordResolver):
    def __init__(self, error: Exception):
        super().__init__()
        self.error = error

    def resolve(self, message):
        raise self.error


def _consumer(**kwargs) -> tuple[ExtractorConsumer, FakeConsumer, FakeStore]:
    transport = kwargs.pop("transport", FakeConsumer([[_message()]]))
    store = kwargs.pop("store", FakeStore())
    consumer = ExtractorConsumer(
        transport=transport,
        resolver=kwargs.pop("resolver", RecordResolver()),
        seam=kwargs.pop("seam", OneFactSeam()),
        store=store,
        **kwargs,
    )
    return consumer, transport, store


# --- the happy path --------------------------------------------------------


def test_a_handled_message_is_stored_then_committed():
    consumer, transport, store = _consumer()

    outcomes = consumer.run_once()

    assert outcomes == (Outcome.EXTRACTED,)
    assert store.calls == 1
    assert transport.commits == 1


def test_the_whole_message_is_one_upsert_call():
    """A message is the unit that gets committed, so it is the unit stored.

    Splitting it would let a crash leave the offset behind a half-written
    message, and the retry would double-write.
    """

    class ThreeFactSeam:
        def extract(self, record: ResolvedRecord):
            return [
                FactRecord(record.source, f"{record.source_id}#{i}", "v1")
                for i in range(3)
            ]

    consumer, _, store = _consumer(seam=ThreeFactSeam())
    consumer.run_once()

    assert store.calls == 1
    assert len(store.written) == 3


def test_the_fact_key_is_the_one_the_contract_names():
    """`-102` §2.2: `(source, source_id, dict_version)`."""

    consumer, _, store = _consumer()
    consumer.run_once()

    assert store.written[0].key == ("gharchive", "event-0", "registry-v1")


# --- nothing found is not a failure ----------------------------------------


def test_a_record_that_yields_no_facts_still_commits():
    """A GH Archive event with no technology signal is the common case."""

    consumer, transport, store = _consumer(seam=SilentSeam())

    assert consumer.run_once() == (Outcome.EMPTY,)
    assert store.calls == 0
    assert transport.commits == 1


# --- permanent failure -----------------------------------------------------


def test_an_unusable_message_is_committed_so_the_partition_moves():
    consumer, transport, _ = _consumer(
        resolver=BrokenResolver(UnusableMessage("envelope is broken"))
    )

    assert consumer.run_once() == (Outcome.REJECTED,)
    assert transport.commits == 1


def test_an_unusable_message_goes_to_the_dlq():
    class Dlq:
        def __init__(self):
            self.sent = []

        def send(self, topic, *, key, value):
            self.sent.append((topic, value))

        def send_many(self, topic, messages, **_):  # pragma: no cover - unused
            raise AssertionError

        def close(self):  # pragma: no cover - unused
            pass

    dlq = Dlq()
    consumer, _, _ = _consumer(
        resolver=BrokenResolver(UnusableMessage("broken")),
        dlq_topic="gitjob.extractor.dlq",
        dlq_transport=dlq,
    )
    consumer.run_once()

    assert [topic for topic, _ in dlq.sent] == ["gitjob.extractor.dlq"]


def test_a_failing_dlq_does_not_block_the_main_topic():
    class Down:
        def send(self, topic, *, key, value):
            raise OSError("dlq is down")

        def send_many(self, topic, messages, **_):  # pragma: no cover - unused
            raise AssertionError

        def close(self):  # pragma: no cover - unused
            pass

    consumer, transport, _ = _consumer(
        resolver=BrokenResolver(UnusableMessage("broken")),
        dlq_topic="gitjob.extractor.dlq",
        dlq_transport=Down(),
    )

    assert consumer.run_once() == (Outcome.REJECTED,)
    assert transport.commits == 1


# --- transient failure -----------------------------------------------------


def test_a_transient_failure_is_not_committed():
    """A NameNode blip must not cost a collection run."""

    consumer, transport, store = _consumer(
        resolver=BrokenResolver(ResolutionError("namenode unreachable"))
    )

    assert consumer.run_once() == (Outcome.RETRY,)
    assert transport.commits == 0
    assert store.calls == 0


def test_one_retry_holds_the_commit_for_the_whole_poll():
    """Committing the batch would advance past the message asking to retry.

    Re-delivering the handled ones is safe: the upsert key makes storing them
    again a replace.
    """

    class SometimesBroken(RecordResolver):
        def resolve(self, message):
            if message.offset == 1:
                raise ResolutionError("transient")
            return super().resolve(message)

    transport = FakeConsumer([[_message(0), _message(1), _message(2)]])
    consumer, transport, _ = _consumer(transport=transport, resolver=SometimesBroken())

    outcomes = consumer.run_once()

    assert outcomes == (Outcome.EXTRACTED, Outcome.RETRY, Outcome.EXTRACTED)
    assert transport.commits == 0


def test_a_transient_failure_never_reaches_the_dlq():
    class Dlq:
        def __init__(self):
            self.sent = []

        def send(self, topic, *, key, value):
            self.sent.append(value)

        def send_many(self, topic, messages, **_):  # pragma: no cover - unused
            raise AssertionError

        def close(self):  # pragma: no cover - unused
            pass

    dlq = Dlq()
    consumer, _, _ = _consumer(
        resolver=BrokenResolver(ResolutionError("transient")),
        dlq_topic="gitjob.extractor.dlq",
        dlq_transport=dlq,
    )
    consumer.run_once()

    assert dlq.sent == []


# --- bookkeeping -----------------------------------------------------------


def test_an_empty_poll_commits_nothing():
    consumer, transport, _ = _consumer(transport=FakeConsumer([[]]))

    assert consumer.run_once() == ()
    assert transport.commits == 0


def test_outcomes_are_tallied_for_reporting():
    transport = FakeConsumer([[_message(0), _message(1)]])
    consumer, _, _ = _consumer(transport=transport)

    consumer.run_once()

    assert consumer.tally == {"EXTRACTED": 2}


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ((), {}),
        (
            (Outcome.EXTRACTED, Outcome.EMPTY, Outcome.EXTRACTED),
            {"EXTRACTED": 2, "EMPTY": 1},
        ),
    ],
)
def test_summarize_counts_by_outcome(outcomes, expected):
    assert summarize(outcomes) == expected
