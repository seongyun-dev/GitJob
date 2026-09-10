"""What C2 consumes, what it hands to judgement, and what it stores.

C2 Extractor is the second of the two consumers `-102` §2.3 defines. It reads
`github.events`, `so.raw` and `jobs.collected`, resolves each message to the
records it actually describes, and upserts the facts a judgement step returns.

### The judgement is not here

`-102` §2.2 splits this consumer: the skeleton is A조's, the technology and
requirement judgement is AI팀's. `ExtractionSeam` is that split written down —
everything on the transport side of it is in this package, and everything that
decides *what a record means* is behind it. `registry.mapper.RegistryMapper`
and `job.collector.technology.extract_technology_mentions` are the existing
implementations that seam is shaped to accept.

### One message is not one record

This is the difference that makes a uniform pipeline wrong.

| topic | one message is | resolution |
|---|---|---|
| `github.events` | one event | payload is the record |
| `so.raw` | one post | payload is the record |
| `jobs.collected` | one **collection run** | Claim Check: read the batch from HDFS, fan out to every posting in it |

`-103` §4.3 makes `jobs.collected` a Claim Check envelope — it carries
`run_path`, `files` and `record_count`, not the postings. A run of 528 postings
is one message. Treating it as one record would store one fact for a whole
day's collection.

### The deduplication key is the record's, not the envelope's

`-102` §2.2 gives C2 `(source, source_id, dict_version)`. For `jobs.collected`
the envelope's own `source_id` is the `pipeline_run_id` (`-103` §4.2), which is
the *run*. The fact's `source_id` has to be the posting's `source_record_id`,
or every posting in a run would collapse onto one key.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

__all__ = [
    "C2_TOPICS",
    "CLAIM_CHECK_TOPICS",
    "Envelope",
    "ExtractionSeam",
    "FactRecord",
    "FactStore",
    "MessageOrigin",
    "ResolvedRecord",
]

# `-102` §2.3. Unlike C1, C2 does subscribe to `jobs.collected`: it reads the
# postings a run produced, where C1 would only re-archive files already in Raw.
C2_TOPICS: tuple[str, ...] = ("github.events", "so.raw", "jobs.collected")

# Topics whose envelope points at the data instead of carrying it.
CLAIM_CHECK_TOPICS: frozenset[str] = frozenset({"jobs.collected"})


class Envelope(BaseModel):
    """The `-103` §4.1 envelope, as a consumer reads it.

    Unknown fields are ignored rather than rejected. `schema_version` is the
    declared evolution mechanism, so a producer adding a field without bumping
    it is a producer bug — but a consumer that raises on one converts that bug
    into a stopped partition. The repository's producer-side contracts forbid
    extras for the opposite and equally good reason: they are the ones that
    must not emit a field nobody agreed to.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    schema_version: StrictStr
    source: StrictStr
    source_id: StrictStr
    event_type: StrictStr
    occurred_at: StrictStr
    ingested_at: StrictStr
    payload: dict[str, Any]
    event_id: StrictStr | None = None
    trace_id: StrictStr | None = None

    @field_validator(
        "schema_version",
        "source",
        "source_id",
        "event_type",
        "occurred_at",
        "ingested_at",
    )
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


@dataclass(frozen=True)
class MessageOrigin:
    """Where a record came from, kept for replay and for auditing a fact.

    The Kafka coordinates are C1's deduplication key (`-102` §2.2); here they
    are provenance. `envelope_source_id` is separate from the record's own id
    because for a Claim Check they differ — the run and the posting.
    """

    topic: str
    partition: int
    offset: int
    envelope_source_id: str
    event_id: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class ResolvedRecord:
    """One thing worth judging, after a message has been opened.

    `payload` is whatever the record is — a GH Archive event, a Stack Overflow
    post, one job posting from a run's batch. It is passed through untouched:
    deciding what it *means* is the seam's, not this package's.
    """

    source: str
    source_id: str
    occurred_at: str
    payload: Mapping[str, Any]
    origin: MessageOrigin


@dataclass(frozen=True)
class FactRecord:
    """One extracted fact, keyed the way `-102` §2.2 requires.

    `(source, source_id, dict_version)` is an upsert key, not an insert key.
    Re-running a registry version over the same record must replace what that
    version said before, and must not touch what a different version said.
    """

    source: str
    source_id: str
    dict_version: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    origin: MessageOrigin | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.source_id, self.dict_version)


@runtime_checkable
class ExtractionSeam(Protocol):
    """AI팀's half of C2 (`-102` §2.2).

    Implementations decide technology, requirements and Registry mapping. They
    are handed one resolved record and return the facts it yields — zero is a
    valid answer, and is not an error.
    """

    def extract(self, record: ResolvedRecord) -> Sequence[FactRecord]:
        """Facts for one record."""


@runtime_checkable
class FactStore(Protocol):
    """Where facts land.

    A Protocol rather than a table: the schema lives in BE's Flyway migrations
    (`BE/src/main/resources/db/migration`), and no table for C2's output exists
    yet. Agreeing that DDL is a separate step from this skeleton — inventing it
    here would put a second owner on BE's schema.
    """

    def upsert(self, facts: Sequence[FactRecord]) -> int:
        """Store facts by their key, replacing any with the same key.

        Returns how many were written. Must be atomic per call: a partially
        applied batch would be committed as if it were whole.
        """
