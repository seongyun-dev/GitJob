"""The Kafka message envelope every source shares (S15P21E102-103).

`github.events`, `so.raw` and `jobs.collected` carry different payloads but the
same wrapper, so a consumer can deduplicate and order without knowing which
topic it is reading. `docs/data/2026-09-08-kafka-topic-consumer-matrix-and-envelope.md`
holds the agreed contract; this module is its executable form.

### Why `occurred_at` and `ingested_at` are separate

`ingested_at - occurred_at` is the source's publication delay plus our polling
interval. Collapsing them into one timestamp makes a replayed event look like
it just happened, which removes the only evidence for whether S15P21E102-144's
polling interval is right. Watermarks and late-event handling in
S15P21E102-112 read `occurred_at`.

### What does not go in here

Tokens, passwords and personal data stay out of `payload`. The envelope is
written to a topic with `retention.ms=-1`, so anything placed in it is kept
indefinitely by design.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

__all__ = ["ENVELOPE_SCHEMA_VERSION", "EventEnvelope"]

# Bump when the envelope's own shape changes. Consumers must then handle the
# older version explicitly rather than guessing.
ENVELOPE_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class EventEnvelope:
    """One Kafka message, before serialization."""

    source: str
    source_id: str
    event_type: str
    occurred_at: datetime
    ingested_at: datetime
    payload: dict[str, object] = field(default_factory=dict)
    event_id: str | None = None
    trace_id: str | None = None
    schema_version: str = ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for label, value in (
            ("source", self.source),
            ("source_id", self.source_id),
            ("event_type", self.event_type),
            ("schema_version", self.schema_version),
        ):
            if not value or not value.strip():
                raise ValueError(f"{label} must not be blank")
        for label, moment in (
            ("occurred_at", self.occurred_at),
            ("ingested_at", self.ingested_at),
        ):
            if moment.tzinfo is None:
                raise ValueError(f"{label} must include a timezone")

    def as_dict(self) -> dict[str, object]:
        body: dict[str, object] = {
            "schema_version": self.schema_version,
            "source": self.source,
            "source_id": self.source_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "payload": self.payload,
        }
        # Optional keys are omitted rather than sent as null, so a consumer can
        # tell "not provided" from "explicitly empty".
        if self.event_id:
            body["event_id"] = self.event_id
        if self.trace_id:
            body["trace_id"] = self.trace_id
        return body

    def to_bytes(self) -> bytes:
        return json.dumps(self.as_dict(), ensure_ascii=False).encode("utf-8")
