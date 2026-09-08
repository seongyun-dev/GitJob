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
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "KafkaError",
    "KafkaPythonTransport",
    "KafkaTransport",
    "transport_from_env",
]


class KafkaError(RuntimeError):
    """A publish could not be completed."""


@runtime_checkable
class KafkaTransport(Protocol):
    """The two calls a publisher needs."""

    def send(self, topic: str, *, key: bytes | None, value: bytes) -> None:
        """Publish one message, blocking until the broker acknowledges it."""

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
) -> KafkaPythonTransport | None:
    """Build a transport, or `None` when no broker is configured."""

    values = os.environ if env is None else env
    raw = (values.get("KAFKA_BOOTSTRAP_SERVERS") or "").strip()
    if not raw:
        return None
    servers = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not servers:
        return None
    client_id = (values.get("KAFKA_CLIENT_ID") or "gitjob-collector").strip()
    return KafkaPythonTransport(
        bootstrap_servers=servers,
        client_id=client_id or "gitjob-collector",
    )
