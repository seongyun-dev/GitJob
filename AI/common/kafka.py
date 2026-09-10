"""Kafka producer boundary (S15P21E102-103, S15P21E102-108).

Mirrors `common.webhdfs`: a `Protocol` for the transport, one real adapter, and
`*_from_env` returning `None` when the broker is not configured. Tests inject a
fake and never open a socket.

### Why there is a dependency here at all

`collector/gharchive/sinks.py` avoided `requests` because `urllib` already
speaks HTTP. The Kafka wire protocol is binary and versioned, so there is no
standard-library equivalent — `kafka-python` is added instead. It is pure
Python, which matters because the collector image is
`python:3.12-slim-bookworm` with no compiler and no JRE.

The import is deferred to first use, so a checkout without the package still
runs the tests and every code path that does not actually publish.

### Not configured is not a failure

`KAFKA_BOOTSTRAP_SERVERS` is the switch, the same way `WEBHDFS_URL` is for the
Raw sink. A developer without a broker gets a run that collects and archives
normally and simply publishes nothing.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "ConsumedMessage",
    "ConsumerTransport",
    "KafkaError",
    "KafkaPythonConsumer",
    "KafkaPythonTransport",
    "KafkaTransport",
    "consumer_from_env",
    "transport_from_env",
]


class KafkaError(RuntimeError):
    """A publish could not be completed."""


@runtime_checkable
class KafkaTransport(Protocol):
    """The three calls a publisher needs."""

    def send(self, topic: str, *, key: bytes | None, value: bytes) -> None:
        """Publish one message, blocking until the broker acknowledges it."""

    def send_many(
        self,
        topic: str,
        messages: Iterable[tuple[bytes | None, bytes]],
    ) -> int:
        """Publish a batch, blocking once for the whole batch. Returns the count.

        `send` waits for an acknowledgement per message, which is right for
        `jobs.collected` — four messages a day, and the caller writes run
        history from the result. It is the wrong shape for `github.events`:
        S15P21E102-105 measured 87,516,869 events across 744 hours, about
        117,600 an hour on average, and a round trip each would make an hour's
        file take longer to publish than to download.

        This enqueues the batch and blocks once on the flush, so durability is
        unchanged — the broker has acknowledged everything before this returns
        — while the waiting happens once instead of per message.
        """

    def close(self) -> None:
        """Flush and release the connection."""


@dataclass
class KafkaPythonTransport:
    """`kafka-python` adapter.

    `acks="all"` and idempotence are S15P21E102-108's producer settings; a
    message that is only on the leader is not durable, and a retry that
    duplicates would defeat the consumer-side dedup key.
    """

    bootstrap_servers: tuple[str, ...]
    client_id: str = "gitjob-collector"
    request_timeout_ms: int = 20_000
    # How many records `send_many` enqueues before flushing. Bounds the futures
    # held in memory; an hour of `github.events` is ~117,600 records.
    batch_flush_size: int = 5_000
    _producer: object | None = field(default=None, init=False, repr=False)

    def _ensure_producer(self) -> object:
        if self._producer is not None:
            return self._producer
        try:
            from kafka import KafkaProducer
        except ImportError as error:  # pragma: no cover - environment specific
            raise KafkaError(
                "kafka-python is not installed; add it to AI/requirements.txt "
                "or leave KAFKA_BOOTSTRAP_SERVERS unset to run without Kafka"
            ) from error
        try:
            self._producer = KafkaProducer(
                bootstrap_servers=list(self.bootstrap_servers),
                client_id=self.client_id,
                acks="all",
                enable_idempotence=True,
                request_timeout_ms=self.request_timeout_ms,
            )
        except Exception as error:  # pragma: no cover - environment specific
            raise KafkaError(f"could not connect a producer: {error}") from error
        return self._producer

    def send(self, topic: str, *, key: bytes | None, value: bytes) -> None:
        producer = self._ensure_producer()
        try:
            future = producer.send(topic, key=key, value=value)  # type: ignore[attr-defined]
            # Block on the broker acknowledgement. A fire-and-forget send would
            # report success for a message the broker never stored, and the
            # caller writes run history from this result.
            future.get(timeout=self.request_timeout_ms / 1000)
        except Exception as error:
            raise KafkaError(f"publish to {topic} failed: {error}") from error

    def send_many(
        self,
        topic: str,
        messages: Iterable[tuple[bytes | None, bytes]],
    ) -> int:
        """Enqueue a batch, flush once, then check every acknowledgement.

        Chunked rather than sent in one go: the futures are held until the
        flush, so an unbounded batch would hold an hour's worth of them in
        memory at once. `flush()` waits for the broker, and only then is each
        future inspected — a failure anywhere raises, because a partially
        published hour must not be recorded as published.
        """

        producer = self._ensure_producer()
        sent = 0
        pending: list[object] = []

        def drain() -> None:
            nonlocal pending
            if not pending:
                return
            try:
                producer.flush(timeout=self.request_timeout_ms / 1000)  # type: ignore[attr-defined]
            except Exception as error:
                raise KafkaError(f"flush to {topic} failed: {error}") from error
            for future in pending:
                # `flush` returning does not mean every record succeeded; the
                # per-record outcome still lives on its future.
                try:
                    if not future.succeeded():  # type: ignore[attr-defined]
                        raise KafkaError(
                            f"publish to {topic} failed: {future.exception}"  # type: ignore[attr-defined]
                        )
                except AttributeError as error:  # pragma: no cover - client shape
                    raise KafkaError(
                        f"publish to {topic}: unexpected future shape: {error}"
                    ) from error
            pending = []

        try:
            for key, value in messages:
                pending.append(
                    producer.send(topic, key=key, value=value)  # type: ignore[attr-defined]
                )
                sent += 1
                if len(pending) >= self.batch_flush_size:
                    drain()
            drain()
        except KafkaError:
            raise
        except Exception as error:
            raise KafkaError(f"publish to {topic} failed: {error}") from error
        return sent

    def close(self) -> None:
        # Detach first, so a failing close still leaves this transport usable
        # for a fresh producer rather than pinned to a broken one.
        producer, self._producer = self._producer, None
        if producer is None:
            return
        try:
            producer.close()  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - shutdown must not raise
            # The client's close path can fail in ways it does not document.
            # Reported rather than swallowed, but never propagated: the
            # messages were already acknowledged.
            print(f"kafka producer close failed: {error}", file=sys.stderr)


def transport_from_env(
    env: Mapping[str, str] | None = None,
    default_client_id: str = "gitjob-collector",
) -> KafkaPythonTransport | None:
    """Build a transport, or `None` when no broker is configured."""

    values = os.environ if env is None else env
    raw = (values.get("KAFKA_BOOTSTRAP_SERVERS") or "").strip()
    if not raw:
        return None
    servers = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not servers:
        return None
    client_id = (values.get("KAFKA_CLIENT_ID") or default_client_id).strip()
    return KafkaPythonTransport(
        bootstrap_servers=servers,
        client_id=client_id or default_client_id,
    )


# ---------------------------------------------------------------------------
# Consumer side. Deliberately the mirror image of the producer above: a
# Protocol, one real adapter, and a `*_from_env` that returns `None` when no
# broker is configured, so tests inject a fake and never open a socket.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsumedMessage:
    """One message, with the fields a handler and an operator need."""

    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes
    headers: tuple[tuple[str, bytes], ...] = ()

    def header(self, name: str) -> bytes | None:
        for key, value in self.headers:
            if key == name:
                return value
        return None


@runtime_checkable
class ConsumerTransport(Protocol):
    """The three calls a consumer loop needs."""

    def poll(self, timeout_ms: int) -> list[ConsumedMessage]:
        """Return the messages ready now, or an empty list."""

    def commit(self) -> None:
        """Commit the offsets of everything returned so far."""

    def close(self) -> None:
        """Leave the group and release the connection."""


@dataclass
class KafkaPythonConsumer:
    """`kafka-python` adapter for at-least-once consumption.

    Three settings carry the weight and none of them are defaults.

    `enable_auto_commit=False`: the loop commits after the work is done. With
    auto-commit an offset advances on a timer, so a crash mid-work silently
    drops the message.

    `max_poll_records=1`: one unit of work per poll keeps the time between
    polls bounded by a single job rather than a batch.

    `max_poll_interval_ms`: the broker evicts a consumer that does not poll
    within this window and hands its partitions to someone else, who then
    redoes the same work. It has to exceed the slowest job, which for repository
    analysis is a clone, so it is configurable rather than left at five minutes.
    """

    bootstrap_servers: tuple[str, ...]
    topic: str
    group_id: str
    client_id: str = "gitjob-analysis"
    # Above ANALYSIS_CLONE_TIMEOUT_SECONDS (600s) plus parsing. Equal values mean a
    # clone that runs to its timeout loses the partition before it can report.
    max_poll_interval_ms: int = 900_000
    session_timeout_ms: int = 45_000
    _consumer: object | None = field(default=None, init=False, repr=False)

    def _ensure_consumer(self) -> object:
        if self._consumer is not None:
            return self._consumer
        try:
            from kafka import KafkaConsumer
        except ImportError as error:  # pragma: no cover - environment specific
            raise KafkaError(
                "kafka-python is not installed; add it to AI/requirements.txt "
                "or leave KAFKA_BOOTSTRAP_SERVERS unset to run without Kafka"
            ) from error
        try:
            self._consumer = KafkaConsumer(
                self.topic,
                bootstrap_servers=list(self.bootstrap_servers),
                group_id=self.group_id,
                client_id=self.client_id,
                enable_auto_commit=False,
                max_poll_records=1,
                max_poll_interval_ms=self.max_poll_interval_ms,
                session_timeout_ms=self.session_timeout_ms,
                # An analysis request that was published while no consumer
                # existed still has to be processed once one appears.
                auto_offset_reset="earliest",
            )
        except Exception as error:  # pragma: no cover - environment specific
            raise KafkaError(f"could not connect a consumer: {error}") from error
        return self._consumer

    def poll(self, timeout_ms: int) -> list[ConsumedMessage]:
        consumer = self._ensure_consumer()
        try:
            batches = consumer.poll(timeout_ms=timeout_ms)  # type: ignore[attr-defined]
        except Exception as error:
            raise KafkaError(f"poll of {self.topic} failed: {error}") from error
        messages: list[ConsumedMessage] = []
        for records in batches.values():
            for record in records:
                messages.append(
                    ConsumedMessage(
                        topic=record.topic,
                        partition=record.partition,
                        offset=record.offset,
                        key=record.key,
                        value=record.value,
                        headers=tuple(record.headers or ()),
                    )
                )
        return messages

    def commit(self) -> None:
        consumer = self._ensure_consumer()
        try:
            consumer.commit()  # type: ignore[attr-defined]
        except Exception as error:
            # Losing a commit means redelivery, which the handler is built to
            # absorb. Losing it silently would not be.
            raise KafkaError(f"commit on {self.topic} failed: {error}") from error

    def close(self) -> None:
        consumer, self._consumer = self._consumer, None
        if consumer is None:
            return
        try:
            consumer.close()  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - shutdown must not raise
            print(f"kafka consumer close failed: {error}", file=sys.stderr)


def consumer_from_env(
    topic: str,
    group_id: str,
    env: Mapping[str, str] | None = None,
) -> KafkaPythonConsumer | None:
    """Build a consumer, or `None` when no broker is configured."""

    values = os.environ if env is None else env
    raw = (values.get("KAFKA_BOOTSTRAP_SERVERS") or "").strip()
    if not raw:
        return None
    servers = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not servers:
        return None
    return KafkaPythonConsumer(
        bootstrap_servers=servers,
        topic=topic,
        group_id=group_id,
        client_id=(values.get("KAFKA_CLIENT_ID") or "gitjob-analysis").strip()
        or "gitjob-analysis",
        max_poll_interval_ms=_positive_int(
            values.get("KAFKA_MAX_POLL_INTERVAL_MS"), 900_000
        ),
    )


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int((raw or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default
