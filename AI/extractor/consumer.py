"""The poll / resolve / extract / upsert / commit loop for one topic.

### Why this is not Spark, when C1 is

`-112` says Spark Structured Streaming, and C1 is. C2 is not, and the reason
is its sink rather than a preference.

- The output is an **upsert** on `(source, source_id, dict_version)`
  (`-102` §2.2). Spark's JDBC sink appends; an upsert means `foreachBatch` and
  hand-written SQL anyway, so Spark's writer buys nothing.
- `jobs.collected` is a Claim Check, so resolving one message is a **per
  message HDFS read**, not a columnar scan.
- The judgement is `registry.mapper` and `job.collector.technology` — plain
  Python holding the Registry. Running it in executors means shipping the
  registry data with every job and versioning it there too.
- `-121` added `common.kafka.ConsumerTransport` days ago for exactly this
  shape of work, with manual commit and a DLQ.

**This also dissolves the `-108` / `-112` conflict rather than choosing a
side.** `-108` says manual commit and `-112` says checkpoint; they were never
describing the same consumer. C1 archives with a checkpoint, C2 upserts with a
committed consumer group, and the two are independent because they use
different mechanisms entirely. `-108`'s `--describe` check works — for C2.

### Ordering

The rules are `-121`'s, for the same reasons its docstring gives.

**Commit last.** An offset committed before the upsert is a message that
disappears if the process dies mid-work.

**Commit a permanent failure anyway.** A message that will never resolve, left
uncommitted, stops its partition forever. It goes to the DLQ instead.

**Do not commit a transient failure.** A NameNode that is briefly down must
not cost a collection run; job postings cannot be collected again.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from common.kafka import ConsumedMessage, ConsumerTransport, KafkaError, KafkaTransport

from extractor.contracts import ExtractionSeam, FactRecord, FactStore
from extractor.resolve import RecordResolver, ResolutionError, UnusableMessage

__all__ = ["ExtractorConsumer", "Outcome"]

log = logging.getLogger("extractor.consumer")


class Outcome(StrEnum):
    """What happened to one message. Returned so a caller can count."""

    EXTRACTED = "EXTRACTED"
    #: Resolved and judged, but yielded nothing. Not a failure: a GH Archive
    #: event with no technology signal is a normal, common answer.
    EMPTY = "EMPTY"
    #: Permanently unusable. Committed and sent to the DLQ.
    REJECTED = "REJECTED"
    #: Transient. Left uncommitted so the next poll delivers it again.
    RETRY = "RETRY"


@dataclass
class ExtractorConsumer:
    """One topic, one group, one worker."""

    transport: ConsumerTransport
    resolver: RecordResolver
    seam: ExtractionSeam
    store: FactStore
    dlq_topic: str | None = None
    dlq_transport: KafkaTransport | None = None
    poll_timeout_ms: int = 1_000
    #: Counted per outcome for the run, so a caller can report without
    #: re-reading the log.
    tally: dict[str, int] = field(default_factory=dict)

    def handle(self, message: ConsumedMessage) -> Outcome:
        """Resolve, judge and store one message. Does not commit."""

        try:
            records = self.resolver.resolve(message)
        except UnusableMessage as error:
            return self._reject(message, str(error))
        except ResolutionError as error:
            log.warning(
                "retryable resolution failure at %s[%s]@%s: %s",
                message.topic,
                message.partition,
                message.offset,
                error,
            )
            return self._count(Outcome.RETRY)

        facts: list[FactRecord] = []
        for record in records:
            facts.extend(self.seam.extract(record))

        if not facts:
            return self._count(Outcome.EMPTY)

        # One call for the whole message. A message is the unit that gets
        # committed, so it has to be the unit that is stored atomically —
        # otherwise a crash between two upserts leaves the offset behind a
        # partially stored message and the retry double-writes.
        self.store.upsert(facts)
        return self._count(Outcome.EXTRACTED)

    def run_once(self) -> tuple[Outcome, ...]:
        """One poll. Commits only when nothing asked to be retried.

        Committing a batch that contains a retry would advance past it. The
        whole poll is re-delivered instead; the upsert key makes re-storing
        the already-handled messages a replace rather than a duplicate.
        """

        messages = self.transport.poll(self.poll_timeout_ms)
        if not messages:
            return ()
        outcomes = tuple(self.handle(message) for message in messages)
        if Outcome.RETRY not in outcomes:
            self.transport.commit()
        return outcomes

    def _reject(self, message: ConsumedMessage, reason: str) -> Outcome:
        log.error(
            "unusable message at %s[%s]@%s: %s",
            message.topic,
            message.partition,
            message.offset,
            reason,
        )
        self._to_dlq(message, reason)
        return self._count(Outcome.REJECTED)

    def _to_dlq(self, message: ConsumedMessage, reason: str) -> None:
        """Best effort. A DLQ that is down must not block the main topic."""

        if not self.dlq_topic or self.dlq_transport is None:
            return
        try:
            self.dlq_transport.send(
                self.dlq_topic, key=message.key, value=message.value
            )
        except (KafkaError, OSError) as error:
            log.error("could not publish to %s: %s", self.dlq_topic, error)

    def _count(self, outcome: Outcome) -> Outcome:
        self.tally[outcome.value] = self.tally.get(outcome.value, 0) + 1
        return outcome


def summarize(outcomes: Sequence[Outcome]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.value] = counts.get(outcome.value, 0) + 1
    return counts
