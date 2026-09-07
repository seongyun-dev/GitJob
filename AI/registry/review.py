"""File-backed C-side review queue for unresolved Registry mappings."""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Literal

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
    mention_index: StrictInt = Field(ge=0)
    source_record_id: StrictStr
    source_site: StrictStr
    source_url: HttpUrl
    source_surface: SourceSurface
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


class ReviewQueueSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["registry-review-queue/v1"]
    records: tuple[ReviewRecord, ...]


def _review_id(
    *,
    dataset_snapshot_id: str,
    source_record_id: str,
    raw_technology: str,
    evidence_text: str,
    char_start: int | None,
    source_surface: SourceSurface,
    mention_index: int,
) -> str:
    identity = "\x1f".join(
        (
            dataset_snapshot_id,
            source_record_id,
            raw_technology,
            evidence_text,
            "" if char_start is None else str(char_start),
            source_surface.value,
            str(mention_index),
        )
    )
    return f"review-{sha256(identity.encode('utf-8')).hexdigest()[:24]}"


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
        for source_record in batch.records:
            for result in source_record.technologies:
                if result.match_status is MatchStatus.MATCHED:
                    continue
                review_id = _review_id(
                    dataset_snapshot_id=batch.dataset_snapshot_id,
                    source_record_id=source_record.source_record_id,
                    raw_technology=result.raw_technology,
                    evidence_text=result.evidence_text,
                    char_start=result.location.char_start,
                    source_surface=result.location.source_surface,
                    mention_index=result.mention_index,
                )
                existing = self._records.get(review_id)
                if existing is not None:
                    affected.append(existing)
                    continue
                attempt = ReviewAttempt(
                    attempted_at=self._now(),
                    decision_kind=DecisionKind.AUTOMATIC,
                    registry_version=result.registry_version,
                    match_status=result.match_status,
                    tech_id=result.tech_id,
                    candidates=result.candidates,
                    reason=result.mapping_evidence.reason,
                    mapping_attempts=result.mapping_attempts,
                )
                record = ReviewRecord(
                    review_id=review_id,
                    mention_index=result.mention_index,
                    source_record_id=source_record.source_record_id,
                    source_site=source_record.source_site,
                    source_url=source_record.source_url,
                    source_surface=result.location.source_surface,
                    raw_technology=result.raw_technology,
                    mapping_strategy=tuple(
                        attempt.source for attempt in result.mapping_attempts
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
                self._records[review_id] = record
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
        if not mapper.has_active_technology(tech_id):
            raise ValueError(
                f"manual decision requires active Registry tech_id: {tech_id}"
            )
        attempt = ReviewAttempt(
            attempted_at=self._now(),
            decision_kind=DecisionKind.MANUAL,
            registry_version=mapper.registry_version,
            match_status=MatchStatus.MATCHED,
            tech_id=tech_id,
            candidates=(tech_id,),
            reason="explicit manual review decision",
            reviewer=reviewer,
            note=note,
        )
        resolved = record.model_copy(
            update={
                "status": ReviewStatus.RESOLVED,
                "resolved_tech_id": tech_id,
                "candidates": (tech_id,),
                "attempts": (*record.attempts, attempt),
            }
        )
        self._records[review_id] = resolved
        self._save()
        return resolved

    def reprocess_pending(self, mapper: RegistryMapper) -> tuple[ReviewRecord, ...]:
        reprocessed = []
        for record in self.query(ReviewStatus.PENDING):
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
                attempted_at=self._now(),
                decision_kind=DecisionKind.AUTOMATIC,
                registry_version=result.registry_version,
                match_status=result.status,
                tech_id=result.tech_id,
                candidates=result.candidates,
                reason=result.evidence.reason,
                mapping_attempts=tuple(mapping_attempts),
            )
            updated = record.model_copy(
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
            self._records[record.review_id] = updated
            reprocessed.append(updated)
        if reprocessed:
            self._save()
        return tuple(reprocessed)

    def _save(self) -> None:
        snapshot = ReviewQueueSnapshot(
            schema_version="registry-review-queue/v1",
            records=self.query(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        temporary_path.write_text(
            snapshot.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.path)
