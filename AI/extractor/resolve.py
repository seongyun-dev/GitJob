"""Turn one Kafka message into the records it describes.

This is the file where the three topics stop looking alike. `github.events`
and `so.raw` carry their record in the envelope; `jobs.collected` carries a
pointer to a batch in HDFS and a count (`-103` §4.3). A resolver that treated
them uniformly would store one fact for a whole collection run.

### Reading the Claim Check is a network call inside the consumer loop

That is a deliberate cost, and it is why C2 subscribes to `jobs.collected`
while C1 does not. The alternative — putting several thousand postings in one
Kafka message — is what the Claim Check pattern exists to avoid.

The read goes through `common.webhdfs.WebHdfsClient`, so a consumer running
off the cluster network picks up `WEBHDFS_DATANODE_HOSTS` and reaches the
operational NameNode the same way the collector does.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from common.kafka import ConsumedMessage
from common.webhdfs import WebHdfsClient, WebHdfsError, normalize_hdfs_path

from extractor.contracts import (
    CLAIM_CHECK_TOPICS,
    Envelope,
    MessageOrigin,
    ResolvedRecord,
)

__all__ = [
    "BATCH_FILENAME",
    "RecordResolver",
    "ResolutionError",
    "UnusableMessage",
    "parse_envelope",
]

# The file a run's postings live in. `raw_sink.RUN_FILENAMES` publishes this
# first precisely so a reader that has the manifest can rely on it existing.
BATCH_FILENAME = "job_analysis_input.json"


class ResolutionError(RuntimeError):
    """A message could not be turned into records, and a retry may help."""


class UnusableMessage(ResolutionError):
    """A message will never resolve, however many times it is delivered.

    Separated from its base because the two need opposite handling: a broken
    envelope retried forever holds its partition, while a NameNode that is
    briefly down must not send a run to the DLQ.
    """


def parse_envelope(message: ConsumedMessage) -> Envelope:
    try:
        payload = json.loads(message.value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnusableMessage(f"message value is not JSON: {error}") from error
    if not isinstance(payload, Mapping):
        raise UnusableMessage("envelope is not a JSON object")
    try:
        return Envelope.model_validate(dict(payload))
    except ValueError as error:
        raise UnusableMessage(f"envelope does not match -103 §4.1: {error}") from error


@dataclass
class RecordResolver:
    """Open a message into the records a judgement step should see.

    `client` is only needed for Claim Check topics. Leaving it `None` is how a
    deployment that consumes `github.events` alone avoids requiring a NameNode.
    """

    client: WebHdfsClient | None = None
    batch_filename: str = BATCH_FILENAME

    def resolve(self, message: ConsumedMessage) -> tuple[ResolvedRecord, ...]:
        envelope = parse_envelope(message)
        origin = MessageOrigin(
            topic=message.topic,
            partition=message.partition,
            offset=message.offset,
            envelope_source_id=envelope.source_id,
            event_id=envelope.event_id,
            trace_id=envelope.trace_id,
        )
        if message.topic in CLAIM_CHECK_TOPICS:
            return self._resolve_claim_check(envelope, origin)
        return (
            ResolvedRecord(
                source=envelope.source,
                source_id=envelope.source_id,
                occurred_at=envelope.occurred_at,
                payload=envelope.payload,
                origin=origin,
            ),
        )

    def _resolve_claim_check(
        self,
        envelope: Envelope,
        origin: MessageOrigin,
    ) -> tuple[ResolvedRecord, ...]:
        if self.client is None:
            # Not a data problem: this deployment cannot read the batch at all.
            # Retryable, so the run is not discarded because of a missing
            # configuration that an operator can still supply.
            raise ResolutionError(
                f"{origin.topic} is a Claim Check and no WebHDFS client is "
                "configured; set WEBHDFS_URL"
            )

        run_path = str(envelope.payload.get("run_path") or "").strip()
        if not run_path:
            raise UnusableMessage("Claim Check payload has no run_path")

        try:
            target = normalize_hdfs_path(run_path) / self.batch_filename
        except ValueError as error:
            raise UnusableMessage(f"run_path is not an HDFS path: {error}") from error

        try:
            raw = self.client.read(target)
        except WebHdfsError as error:
            # The NameNode being unreachable is the usual cause, and it is
            # transient. Sending a whole run to the DLQ for it would lose
            # postings that cannot be collected again.
            raise ResolutionError(f"could not read {target}: {error}") from error

        records = _batch_records(raw, target.as_posix())
        declared = envelope.payload.get("record_count")
        _check_count(declared, len(records), target.as_posix())

        return tuple(
            ResolvedRecord(
                source=envelope.source,
                # The posting's id, not the run's — see `contracts` on why the
                # envelope's `source_id` cannot be the deduplication key here.
                source_id=source_record_id,
                occurred_at=envelope.occurred_at,
                payload=record,
                origin=origin,
            )
            for source_record_id, record in records
        )


def _batch_records(raw: bytes, where: str) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    try:
        batch = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnusableMessage(f"{where} is not JSON: {error}") from error
    if not isinstance(batch, Mapping):
        raise UnusableMessage(f"{where} is not a JSON object")

    records = batch.get("records")
    if not isinstance(records, Sequence) or isinstance(records, str | bytes):
        raise UnusableMessage(f"{where} has no records array")

    resolved: list[tuple[str, Mapping[str, Any]]] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise UnusableMessage(f"{where} record {index} is not an object")
        source_record_id = str(record.get("source_record_id") or "").strip()
        if not source_record_id:
            raise UnusableMessage(f"{where} record {index} has no source_record_id")
        resolved.append((source_record_id, record))
    return tuple(resolved)


def _check_count(declared: Any, actual: int, where: str) -> None:
    """The envelope's `record_count` against what the batch holds.

    `-103` §4.3 puts the count in the envelope, so it is free to check and it
    catches the one failure the Claim Check pattern introduces: the pointer and
    the data drifting apart. A truncated upload would otherwise be extracted as
    a smaller run with no sign anything was missing.
    """

    if declared is None:
        return
    try:
        expected = int(declared)
    except (TypeError, ValueError):
        raise UnusableMessage(f"record_count is not a number: {declared!r}") from None
    if expected != actual:
        raise UnusableMessage(
            f"{where} holds {actual} records but the envelope declared "
            f"{expected}; the Claim Check and its batch disagree"
        )
