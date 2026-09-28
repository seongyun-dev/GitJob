"""A-team to C-team job-analysis input contract and boundary adapter."""

import re
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

JOB_ANALYSIS_INPUT_SCHEMA_VERSION = "job-analysis-input/v1"

ContentHash = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
TechId = Annotated[
    str,
    StringConstraints(
        strict=True,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
SourceTechnologyId = Annotated[
    str,
    StringConstraints(
        strict=True,
        max_length=80,
        pattern=(
            r"^(?:c#|c\+\+|\.net(?:-maui)?|"
            r"(?:node|next|vue)\.js|"
            r"[a-z0-9]+(?:-[a-z0-9]+)*)$"
        ),
    ),
]

SOURCE_TECHNOLOGY_ID_OVERRIDES: dict[str, TechId] = {
    "c#": "csharp",
    "c++": "cpp",
    ".net": "dotnet",
    ".net-maui": "dotnet-maui",
    "node.js": "nodejs",
    "next.js": "nextjs",
    "vue.js": "vuejs",
}
_SAFE_TECH_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ISO_8601_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]")


class BodyStatus(StrEnum):
    """Availability of a posting body at the A-to-C boundary."""

    TEXT_AVAILABLE = "TEXT_AVAILABLE"
    IMAGE_ONLY = "IMAGE_ONLY"
    BLOCKED = "BLOCKED"
    MISSING = "MISSING"
    PARSE_FAILED = "PARSE_FAILED"


class PostingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class RequirementType(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    MENTIONED = "MENTIONED"


class SourceSurface(StrEnum):
    TITLE = "TITLE"
    BODY = "BODY"


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TechnologyMentionInput(StrictContractModel):
    """A-side mention; no Registry match is inferred at this boundary."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        validate_by_alias=True,
        serialize_by_alias=True,
    )

    raw_technology: StrictStr
    source_technology_id: SourceTechnologyId | None = Field(alias="technology_id")
    requirement_type: RequirementType
    source_surface: SourceSurface
    evidence_section: StrictStr | None = None
    evidence_text: StrictStr
    extraction_method: StrictStr

    @field_validator(
        "raw_technology",
        "evidence_text",
        "extraction_method",
    )
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("source_technology_id")
    @classmethod
    def reject_blank_source_technology_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("technology_id must not be blank")
        return value


class JobPostingFields(StrictContractModel):
    source_record_id: StrictStr
    canonical_job_id: StrictStr | None = None
    source_site: StrictStr
    source_posting_id: StrictStr
    source_url: HttpUrl
    company_name: StrictStr
    title: StrictStr
    raw_job_category: StrictStr | None = None
    career_level: StrictStr | None = None
    region: StrictStr | None = None
    description_text: StrictStr | None = None
    raw_artifact_uri: StrictStr | None = None
    body_status: BodyStatus
    posting_status: PostingStatus = PostingStatus.UNKNOWN
    posted_at: datetime | None = None
    deadline: datetime | None = None
    collected_at: datetime
    content_hash: ContentHash

    @field_validator(
        "source_record_id",
        "source_site",
        "source_posting_id",
        "company_name",
        "title",
    )
    @classmethod
    def require_non_blank_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("canonical_job_id")
    @classmethod
    def reject_blank_canonical_job_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("canonical_job_id must not be blank")
        return value

    @field_validator("collected_at", "posted_at", "deadline", mode="before")
    @classmethod
    def require_iso_datetime_input(
        cls,
        value: object,
    ) -> object:
        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not _ISO_8601_DATETIME_PATTERN.match(value):
            raise ValueError("timestamp must be an ISO 8601 date-time string")
        return value

    @field_validator("collected_at", "posted_at", "deadline")
    @classmethod
    def require_timezone_when_present(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_body_availability(self) -> "JobPostingFields":
        if self.body_status is BodyStatus.TEXT_AVAILABLE and (
            self.description_text is None or not self.description_text.strip()
        ):
            raise ValueError("TEXT_AVAILABLE body_status requires description_text")
        if self.body_status is BodyStatus.IMAGE_ONLY and (
            self.raw_artifact_uri is None or not self.raw_artifact_uri.strip()
        ):
            raise ValueError("IMAGE_ONLY body_status requires raw_artifact_uri")
        return self


class JobPostingInput(JobPostingFields):
    technology_mentions: tuple[TechnologyMentionInput, ...] = ()


class JobAnalysisInputBatch(StrictContractModel):
    schema_version: Literal["job-analysis-input/v1"]
    dataset_snapshot_id: StrictStr
    pipeline_run_id: StrictStr
    collector_version: StrictStr
    records: tuple[JobPostingInput, ...]

    @field_validator(
        "dataset_snapshot_id",
        "pipeline_run_id",
        "collector_version",
    )
    @classmethod
    def require_non_blank_metadata(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class InternalTechnologyMention(StrictContractModel):
    tech_id: TechId | None
    source_technology_id: StrictStr | None
    raw_technology: StrictStr
    requirement_type: RequirementType
    source_surface: SourceSurface
    evidence_section: StrictStr | None = None
    evidence_text: StrictStr
    extraction_method: StrictStr


class JobAnalysisRecord(JobPostingFields):
    technology_mentions: tuple[InternalTechnologyMention, ...] = ()


class JobAnalysisBatch(StrictContractModel):
    schema_version: Literal["job-analysis-input/v1"]
    dataset_snapshot_id: StrictStr
    pipeline_run_id: StrictStr
    collector_version: StrictStr
    records: tuple[JobAnalysisRecord, ...]


def map_source_technology_id(source_technology_id: str) -> TechId:
    """Translate an explicit legacy ID or validate an already-safe ID."""

    mapped_id = SOURCE_TECHNOLOGY_ID_OVERRIDES.get(source_technology_id)
    if mapped_id is not None:
        return mapped_id
    if len(source_technology_id) <= 80 and _SAFE_TECH_ID_PATTERN.fullmatch(
        source_technology_id
    ):
        return source_technology_id
    raise ValueError(
        f"unsafe source technology_id has no explicit mapping: {source_technology_id!r}"
    )


def adapt_job_analysis_input(
    batch: JobAnalysisInputBatch,
) -> JobAnalysisBatch:
    """Adapt field names and IDs without performing Registry classification."""

    records = []
    for record in batch.records:
        mentions = tuple(
            InternalTechnologyMention(
                tech_id=(
                    map_source_technology_id(mention.source_technology_id)
                    if mention.source_technology_id is not None
                    else None
                ),
                source_technology_id=mention.source_technology_id,
                raw_technology=mention.raw_technology,
                requirement_type=mention.requirement_type,
                source_surface=mention.source_surface,
                evidence_section=mention.evidence_section,
                evidence_text=mention.evidence_text,
                extraction_method=mention.extraction_method,
            )
            for mention in record.technology_mentions
        )
        record_fields = record.model_dump(exclude={"technology_mentions"})
        records.append(
            JobAnalysisRecord(
                **record_fields,
                technology_mentions=mentions,
            )
        )

    return JobAnalysisBatch(
        schema_version=batch.schema_version,
        dataset_snapshot_id=batch.dataset_snapshot_id,
        pipeline_run_id=batch.pipeline_run_id,
        collector_version=batch.collector_version,
        records=tuple(records),
    )


def find_semantic_duplicate_groups(
    records: tuple[JobPostingInput, ...],
) -> dict[str, tuple[str, ...]]:
    """Expose upstream duplicate candidates without deleting source records."""

    grouped_source_ids: defaultdict[str, dict[str, None]] = defaultdict(dict)
    for record in records:
        if record.canonical_job_id is not None:
            grouped_source_ids[record.canonical_job_id].setdefault(
                record.source_record_id,
                None,
            )
    return {
        canonical_job_id: tuple(source_record_ids)
        for canonical_job_id, source_record_ids in grouped_source_ids.items()
        if len(source_record_ids) > 1
    }
