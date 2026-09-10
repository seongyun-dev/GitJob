"""C2 Extractor (S15P21E102-112).

The skeleton half of `-102` §2.3's second consumer: transport, per-topic
resolution, and the upsert. Technology and requirement judgement is AI팀's and
plugs in at `contracts.ExtractionSeam`.
"""

from extractor.consumer import ExtractorConsumer, Outcome
from extractor.contracts import (
    C2_TOPICS,
    Envelope,
    ExtractionSeam,
    FactRecord,
    FactStore,
    MessageOrigin,
    ResolvedRecord,
)
from extractor.resolve import RecordResolver, ResolutionError, UnusableMessage

__all__ = [
    "C2_TOPICS",
    "Envelope",
    "ExtractionSeam",
    "ExtractorConsumer",
    "FactRecord",
    "FactStore",
    "MessageOrigin",
    "Outcome",
    "RecordResolver",
    "ResolutionError",
    "ResolvedRecord",
    "UnusableMessage",
]
