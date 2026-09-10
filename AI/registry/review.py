"""File-backed C-side review queue for unresolved Registry mappings."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictInt,
    StrictStr,
    model_validator,
)

from job.classifier import JobClassificationBatch
from job.contracts import SourceSurface
from registry.contracts import TechId
from registry.mapper import (
    MapperInput,
    MapperResult,
    MapperSource,
    MatchEvidence,
    MatchStatus,
    RegistryMapper,
)

# Compute policy token. This intentionally differs from the file serialization
# schema name ``registry-review-queue/v3`` used by ReviewQueueSnapshot.
REVIEW_QUEUE_VERSION = "c-registry-review-queue/v3"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


class DecisionKind(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"


class ReviewAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempted_at: datetime
    decision_kind: DecisionKind
    registry_version: StrictStr
    match_status: MatchStatus
    tech_id: TechId | None
    candidates: tuple[TechId, ...]
    reason: StrictStr
    mapping_attempts: tuple[MapperResult, ...] = ()
    reviewer: StrictStr | None = None
    note: StrictStr | None = None

    @model_validator(mode="after")
    def require_manual_provenance(self) -> "ReviewAttempt":
        if self.decision_kind is DecisionKind.MANUAL and (
            self.reviewer is None
            or not self.reviewer.strip()
            or self.note is None
            or not self.note.strip()
        ):
            raise ValueError("manual decision requires reviewer and note")
        return self


class ReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: StrictStr
    # Absent on historical v1/v2 rows. New IDs hash the complete immutable
    # source identity that is also used by PostgreSQL idempotency checks.
    review_id_version: Literal["registry-review-id/v3"] | None = None
    # Optional only to validate historical local v1 snapshots. New records always set it.
    source_dataset_snapshot_id: StrictStr | None = None
    mention_index: StrictInt = Field(ge=0)
    source_record_id: StrictStr
    source_site: StrictStr
    source_url: HttpUrl
    source_surface: SourceSurface
    char_start: StrictInt | None = Field(default=None, ge=0)
    char_end: StrictInt | None = Field(default=None, ge=0)
    raw_technology: StrictStr
    mapping_strategy: tuple[MapperSource, ...] = Field(min_length=1)
    context: StrictStr
    evidence_section: StrictStr | None
    evidence_text: StrictStr
    original_match_status: MatchStatus
    candidates: tuple[TechId, ...]
    mapping_evidence: MatchEvidence
    status: ReviewStatus
    resolved_tech_id: TechId | None
    attempts: tuple[ReviewAttempt, ...]

    @model_validator(mode="after")
    def validate_source_identity(self) -> "ReviewRecord":
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("review evidence offsets must both be present or absent")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("review evidence end precedes start")
        if self.review_id_version == "registry-review-id/v3":
            if self.source_dataset_snapshot_id is None:
                raise ValueError(
                    "v3 review identity requires source_dataset_snapshot_id"
                )
            expected = _review_id(review_source_identity(self))
            if self.review_id != expected:
                raise ValueError("review ID does not match immutable source identity")
        return self


class ReviewQueueSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[
        "registry-review-queue/v1",
        "registry-review-queue/v2",
        "registry-review-queue/v3",
    ]
    records: tuple[ReviewRecord, ...]


def _identity_digest(identity: dict[str, Any]) -> str:
    return sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def review_source_identity(record: ReviewRecord) -> dict[str, Any]:
    """Return the complete immutable source identity for IDs and DB hashing."""
    return record.model_dump(
        mode="json",
        include={
            "source_dataset_snapshot_id",
            "mention_index",
            "source_record_id",
            "source_site",
            "source_url",
            "source_surface",
            "char_start",
            "char_end",
            "raw_technology",
            "context",
            "evidence_section",
            "evidence_text",
        },
    )


def review_source_digest(record: ReviewRecord) -> str:
    """Hash the v3 immutable source with the review ID's canonical encoding."""
    return _identity_digest(review_source_identity(record))


def legacy_review_source_identity(record: ReviewRecord) -> dict[str, Any]:
    """Return source fields available in historical v1/v2 queue records."""
    return record.model_dump(
        mode="json",
        include={
            "source_dataset_snapshot_id",
            "mention_index",
            "source_record_id",
            "source_site",
            "source_url",
            "source_surface",
            "raw_technology",
            "context",
            "evidence_section",
            "evidence_text",
        },
    )


def same_legacy_review_source(
    historical: ReviewRecord,
    current: ReviewRecord,
) -> bool:
    """Compare only source fields that both historical and current records store."""
    historical_source = legacy_review_source_identity(historical)
    current_source = legacy_review_source_identity(current)
    if historical.source_dataset_snapshot_id is None:
        # v1 IDs already include the dataset snapshot, although v1 records did
        # not serialize that value. Reaching this record through its derived v1
        # ID proves the missing field while these remaining fields prevent an
        # accidental cross-site/source merge.
        historical_source.pop("source_dataset_snapshot_id")
        current_source.pop("source_dataset_snapshot_id")
    return historical_source == current_source


def _review_id(identity: dict[str, Any]) -> str:
    return f"review-{_identity_digest(identity)[:24]}"


def _legacy_review_id(
    *,
    dataset_snapshot_id: str,
    source_site: str | None,
    source_record_id: str,
    raw_technology: str,
    evidence_text: str,
    char_start: int | None,
    source_surface: SourceSurface,
    mention_index: int,
) -> str:
    parts = [dataset_snapshot_id]
    if source_site is not None:
        parts.append(source_site)
    parts.extend(
        (
            source_record_id,
            raw_technology,
            evidence_text,
            "" if char_start is None else str(char_start),
            source_surface.value,
            str(mention_index),
        )
    )
    identity = "\x1f".join(parts)
    return f"review-{sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def legacy_review_ids(record: ReviewRecord) -> tuple[str, str]:
    """Derive historical v2/site-aware and v1/site-less IDs for DB replay."""
    if record.source_dataset_snapshot_id is None:
        raise ValueError("legacy review identity requires source_dataset_snapshot_id")
    values = {
        "dataset_snapshot_id": record.source_dataset_snapshot_id,
        "source_record_id": record.source_record_id,
        "raw_technology": record.raw_technology,
        "evidence_text": record.evidence_text,
        "char_start": record.char_start,
        "source_surface": record.source_surface,
        "mention_index": record.mention_index,
    }
    return (
        _legacy_review_id(source_site=record.source_site, **values),
        _legacy_review_id(source_site=None, **values),
    )


def build_records(
    batch: JobClassificationBatch,
    *,
    attempted_at: datetime | None = None,
) -> tuple[ReviewRecord, ...]:
    """Build unresolved review records without performing persistence side effects.

    Source collection time is the deterministic default. A caller processing an
    event can provide that event's timezone-aware occurrence time instead.
    """
    if attempted_at is not None and attempted_at.tzinfo is None:
        raise ValueError("review attempt timestamp needs a timezone")
    records = []
    for source_record in batch.records:
        attempt_time = attempted_at or source_record.collected_at
        for result in source_record.technologies:
            if result.match_status is MatchStatus.MATCHED:
                continue
            attempt = ReviewAttempt(
                attempted_at=attempt_time,
                decision_kind=DecisionKind.AUTOMATIC,
                registry_version=result.registry_version,
                match_status=result.match_status,
                tech_id=result.tech_id,
                candidates=result.candidates,
                reason=result.mapping_evidence.reason,
                mapping_attempts=result.mapping_attempts,
            )
            identity = {
                "source_dataset_snapshot_id": batch.dataset_snapshot_id,
                "mention_index": result.mention_index,
                "source_record_id": source_record.source_record_id,
                "source_site": source_record.source_site,
                "source_url": str(source_record.source_url),
                "source_surface": result.location.source_surface.value,
                "char_start": result.location.char_start,
                "char_end": result.location.char_end,
                "raw_technology": result.raw_technology,
                "context": result.mapping_context,
                "evidence_section": result.evidence_section,
                "evidence_text": result.evidence_text,
            }
            record = ReviewRecord(
                review_id=_review_id(identity),
                review_id_version="registry-review-id/v3",
                source_dataset_snapshot_id=batch.dataset_snapshot_id,
                mention_index=result.mention_index,
                source_record_id=source_record.source_record_id,
                source_site=source_record.source_site,
                source_url=source_record.source_url,
                source_surface=result.location.source_surface,
                char_start=result.location.char_start,
                char_end=result.location.char_end,
                raw_technology=result.raw_technology,
                mapping_strategy=tuple(
                    mapping.source for mapping in result.mapping_attempts
                ),
                context=result.mapping_context,
                evidence_section=result.evidence_section,
                evidence_text=result.evidence_text,
                original_match_status=result.match_status,
                candidates=result.candidates,
                mapping_evidence=result.mapping_evidence,
                status=ReviewStatus.PENDING,
                resolved_tech_id=None,
                attempts=(attempt,),
            )
            records.append(record)
    return tuple(records)


def resolve_record(
    record: ReviewRecord,
    *,
    tech_id: TechId,
    reviewer: str,
    note: str,
    mapper: RegistryMapper,
    attempted_at: datetime,
) -> ReviewRecord:
    """Apply the existing manual-decision policy without persistence."""
    if attempted_at.tzinfo is None:
        raise ValueError("review attempt timestamp needs a timezone")
    if not mapper.has_active_technology(tech_id):
        raise ValueError(f"manual decision requires active Registry tech_id: {tech_id}")
    attempt = ReviewAttempt(
        attempted_at=attempted_at,
        decision_kind=DecisionKind.MANUAL,
        registry_version=mapper.registry_version,
        match_status=MatchStatus.MATCHED,
        tech_id=tech_id,
        candidates=(tech_id,),
        reason="explicit manual review decision",
        reviewer=reviewer,
        note=note,
    )
    return record.model_copy(
        update={
            "status": ReviewStatus.RESOLVED,
            "resolved_tech_id": tech_id,
            "candidates": (tech_id,),
            "attempts": (*record.attempts, attempt),
        }
    )


def reprocess_record(
    record: ReviewRecord,
    mapper: RegistryMapper,
    *,
    attempted_at: datetime,
    reviewer: str | None = None,
    note: str | None = None,
) -> ReviewRecord:
    """Apply the existing ordered Mapper replay policy without persistence."""
    if attempted_at.tzinfo is None:
        raise ValueError("review attempt timestamp needs a timezone")
    mapping_attempts = []
    for source in record.mapping_strategy:
        result = mapper.map(
            MapperInput(
                source=source,
                raw_value=record.raw_technology,
                context=record.context,
            )
        )
        mapping_attempts.append(result)
        if result.status is not MatchStatus.UNKNOWN:
            break
    attempt = ReviewAttempt(
        attempted_at=attempted_at,
        decision_kind=DecisionKind.AUTOMATIC,
        registry_version=result.registry_version,
        match_status=result.status,
        tech_id=result.tech_id,
        candidates=result.candidates,
        reason=result.evidence.reason,
        mapping_attempts=tuple(mapping_attempts),
        reviewer=reviewer,
        note=note,
    )
    return record.model_copy(
        update={
            "status": (
                ReviewStatus.RESOLVED
                if result.status is MatchStatus.MATCHED
                else ReviewStatus.PENDING
            ),
            "resolved_tech_id": result.tech_id,
            "candidates": result.candidates,
            "mapping_evidence": result.evidence,
            "attempts": (*record.attempts, attempt),
        }
    )


class ReviewStore:
    """Persist review records atomically at a caller-owned local path."""

    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self._now = now or (lambda: datetime.now(UTC))
        if path.exists():
            snapshot = ReviewQueueSnapshot.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            self._records = {record.review_id: record for record in snapshot.records}
        else:
            self._records: dict[str, ReviewRecord] = {}

    def query(self, status: ReviewStatus | None = None) -> tuple[ReviewRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self._records.values()
                    if status is None or record.status is status
                ),
                key=lambda record: record.review_id,
            )
        )

    def ingest(self, batch: JobClassificationBatch) -> tuple[ReviewRecord, ...]:
        affected = []
        changed = False
        for record in build_records(batch, attempted_at=self._now()):
            existing = self._records.get(record.review_id)
            if existing is None:
                for legacy_id in legacy_review_ids(record):
                    candidate = self._records.get(legacy_id)
                    if (
                        candidate is not None
                        and candidate.review_id_version is None
                        and same_legacy_review_source(candidate, record)
                    ):
                        existing = candidate
                        break
            if existing is not None:
                affected.append(existing)
                continue
            self._records[record.review_id] = record
            affected.append(record)
            changed = True
        if changed:
            self._save()
        return tuple(affected)

    def resolve_manual(
        self,
        review_id: str,
        *,
        tech_id: TechId,
        reviewer: str,
        note: str,
        mapper: RegistryMapper,
    ) -> ReviewRecord:
        record = self._records[review_id]
        resolved = resolve_record(
            record,
            tech_id=tech_id,
            reviewer=reviewer,
            note=note,
            mapper=mapper,
            attempted_at=self._now(),
        )
        self._records[review_id] = resolved
        self._save()
        return resolved

    def reprocess_pending(self, mapper: RegistryMapper) -> tuple[ReviewRecord, ...]:
        reprocessed = []
        for record in self.query(ReviewStatus.PENDING):
            updated = reprocess_record(record, mapper, attempted_at=self._now())
            self._records[record.review_id] = updated
            reprocessed.append(updated)
        if reprocessed:
            self._save()
        return tuple(reprocessed)

    def _save(self) -> None:
        snapshot = ReviewQueueSnapshot(
            schema_version="registry-review-queue/v3",
            records=self.query(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        temporary_path.write_text(
            snapshot.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.path)
