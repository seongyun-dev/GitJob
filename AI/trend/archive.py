"""Join GH Archive activity with current, pinned public technology evidence.

This module deliberately remains separate from ``trend.github``.  GH Archive
measures repository events while Innovation Graph measures unique pushers; the
two sources are not interchangeable and are never blended here.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, TextIO
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from github.contracts import RepoCollectionStatus
from github.public_analysis import PublicBatchResult, PublicRepoResult
from registry.contracts import RegistryStatus, TechnologyRegistry
from trend.contracts import TrendStatus

ARCHIVE_TREND_SCHEMA_VERSION = "c-gharchive-trend/v1"
ARCHIVE_TREND_ALGORITHM_VERSION = "c-gharchive-current-evidence-join/v1"
MAX_EVIDENCE_EXAMPLES = 20
_FORBIDDEN_ACTIVITY_FIELDS = frozenset(
    {"tech_id", "tech_ids", "technology", "technologies", "observations"}
)
_MONTH_PATTERN = re.compile(r"^(?P<year>[0-9]{4})-(?P<month>0[1-9]|1[0-2])$")
_WEEK_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_HASH = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
_COMMIT_SHA = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{40}$")]


class PeriodGranularity(StrEnum):
    MONTH = "MONTH"
    WEEK = "WEEK"


class ArchiveModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _period_index(period: str, granularity: PeriodGranularity) -> int:
    if granularity is PeriodGranularity.MONTH:
        match = _MONTH_PATTERN.fullmatch(period)
        if match is None or int(match["year"]) < 2020:
            raise ValueError("MONTH period must be YYYY-MM and year >= 2020")
        return int(match["year"]) * 12 + int(match["month"])

    if not _WEEK_PATTERN.fullmatch(period):
        raise ValueError("WEEK period must be an ISO date")
    try:
        parsed = date.fromisoformat(period)
    except ValueError as exc:
        raise ValueError("WEEK period must be a real ISO date") from exc
    if parsed.year < 2020:
        raise ValueError("WEEK period year must be >= 2020")
    if parsed.weekday() != 0:
        raise ValueError("WEEK period must start on Monday")
    return parsed.toordinal() // 7


def _absolute_uri(value: str, field_name: str) -> str:
    parsed = urlsplit(value)
    if not value.strip() or not parsed.scheme or not parsed.path:
        raise ValueError(f"{field_name} must be a non-blank absolute URI")
    return value


class ArchiveActivityMetadata(ArchiveModel):
    """Immutable lineage and denominators for one bounded Top-N export."""

    source_schema_version: StrictStr
    source_version: StrictStr
    dataset_snapshot_id: StrictStr
    source_uri: StrictStr
    source_hash: _HASH
    upstream_source_uri: StrictStr | None = None
    upstream_source_hash: _HASH | None = None
    period: StrictStr
    granularity: PeriodGranularity
    top_n_limit: Annotated[StrictInt, Field(gt=0)]
    selected_repo_count: Annotated[StrictInt, Field(ge=0)]
    selected_event_count: Annotated[StrictInt, Field(ge=0)]
    valid_event_count: Annotated[StrictInt, Field(ge=0)]
    total_active_repo_count: Annotated[StrictInt, Field(ge=0)]
    selection_event_coverage: float = Field(ge=0, le=1)

    @field_validator("source_schema_version", "source_version", "dataset_snapshot_id")
    @classmethod
    def non_blank_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("lineage identifiers must not be blank")
        return value

    @field_validator("source_uri")
    @classmethod
    def valid_source_uri(cls, value: str) -> str:
        return _absolute_uri(value, "source_uri")

    @field_validator("upstream_source_uri")
    @classmethod
    def valid_upstream_source_uri(cls, value: str | None) -> str | None:
        return (
            _absolute_uri(value, "upstream_source_uri") if value is not None else None
        )

    @model_validator(mode="after")
    def reconcile_denominators(self) -> ArchiveActivityMetadata:
        _period_index(self.period, self.granularity)
        if self.selected_repo_count > self.top_n_limit:
            raise ValueError("selected_repo_count exceeds top_n_limit")
        if self.selected_repo_count > self.total_active_repo_count:
            raise ValueError("selected_repo_count exceeds total_active_repo_count")
        if self.selected_event_count > self.valid_event_count:
            raise ValueError("selected_event_count exceeds valid_event_count")
        expected = (
            self.selected_event_count / self.valid_event_count
            if self.valid_event_count
            else 0.0
        )
        if abs(self.selection_event_coverage - expected) > 1e-12:
            raise ValueError("selection_event_coverage must use valid_event_count")
        return self


@dataclass(frozen=True)
class ArchivePeriodInput:
    """One period's bounded activity rows and validated public analysis."""

    metadata: ArchiveActivityMetadata
    activity_rows: Iterable[Mapping[str, object]]
    public_analysis: PublicBatchResult
    public_snapshot_uri: str
    public_snapshot_hash: str


class ArchiveEvidenceExample(ArchiveModel):
    github_repo_id: Annotated[StrictInt, Field(gt=0)]
    repo_snapshot_id: StrictStr
    pinned_commit_sha: _COMMIT_SHA
    path: StrictStr
    uri: StrictStr
    content_hash: _HASH

    @field_validator("path")
    @classmethod
    def safe_repository_path(cls, value: str) -> str:
        if (
            not value.strip()
            or value != value.strip()
            or "\\" in value
            or PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("evidence path must be a safe repository-relative path")
        return value

    @field_validator("uri")
    @classmethod
    def absolute_evidence_uri(cls, value: str) -> str:
        return _absolute_uri(value, "evidence uri")


class ArchiveEvidenceLookup(ArchiveModel):
    public_dataset_snapshot_id: StrictStr
    public_snapshot_uri: StrictStr
    public_snapshot_hash: _HASH
    tech_id: StrictStr
    matching_repo_count: Annotated[StrictInt, Field(ge=0)]
    example_repo_ids: tuple[int, ...]
    examples_truncated: StrictBool

    @field_validator("public_snapshot_uri")
    @classmethod
    def absolute_public_snapshot_uri(cls, value: str) -> str:
        return _absolute_uri(value, "public_snapshot_uri")

    @model_validator(mode="after")
    def validate_examples(self) -> ArchiveEvidenceLookup:
        if (
            len(self.example_repo_ids) > MAX_EVIDENCE_EXAMPLES
            or len(self.example_repo_ids) != len(set(self.example_repo_ids))
            or any(repo_id <= 0 for repo_id in self.example_repo_ids)
            or len(self.example_repo_ids) > self.matching_repo_count
        ):
            raise ValueError("invalid bounded evidence repository examples")
        if self.examples_truncated != (
            self.matching_repo_count > len(self.example_repo_ids)
        ):
            raise ValueError("examples_truncated must reflect matching_repo_count")
        return self


class ArchiveTrendPoint(ArchiveModel):
    period: StrictStr
    granularity: PeriodGranularity
    status: TrendStatus
    event_count: Annotated[StrictInt, Field(ge=0)] | None = None
    active_repo_count: Annotated[StrictInt, Field(ge=0)] | None = None
    sample_repo_count: Annotated[StrictInt, Field(ge=0)] | None = None
    sample_event_count: Annotated[StrictInt, Field(ge=0)] | None = None
    selected_repo_count: Annotated[StrictInt, Field(ge=0)] | None = None
    selected_event_count: Annotated[StrictInt, Field(ge=0)] | None = None
    analyzed_repo_coverage: float | None = Field(default=None, ge=0, le=1)
    analyzed_event_coverage: float | None = Field(default=None, ge=0, le=1)
    selection_event_coverage: float | None = Field(default=None, ge=0, le=1)
    excluded_repo_count: Annotated[StrictInt, Field(ge=0)] | None = None
    failed_repo_count: Annotated[StrictInt, Field(ge=0)] | None = None
    partial_repo_count: Annotated[StrictInt, Field(ge=0)] | None = None
    unresolved_repo_count: Annotated[StrictInt, Field(ge=0)] | None = None
    quality_reasons: tuple[str, ...] = ()
    activity_schema_version: str | None = None
    activity_source_version: str | None = None
    activity_dataset_snapshot_id: str | None = None
    activity_source_uri: str | None = None
    activity_source_hash: _HASH | None = None
    activity_upstream_source_uri: str | None = None
    activity_upstream_source_hash: _HASH | None = None
    public_dataset_snapshot_id: str | None = None
    public_pipeline_run_id: str | None = None
    public_collector_version: str | None = None
    public_collection_policy_version: str | None = None
    public_parser_version: str | None = None
    public_generated_at: str | None = None
    public_snapshot_uri: str | None = None
    public_snapshot_hash: _HASH | None = None
    evidence_lookup: ArchiveEvidenceLookup | None = None
    evidence_examples: tuple[ArchiveEvidenceExample, ...] = ()

    @model_validator(mode="after")
    def reconcile_point(self) -> ArchiveTrendPoint:
        _period_index(self.period, self.granularity)
        population = (
            self.sample_repo_count,
            self.selected_repo_count,
            self.excluded_repo_count,
        )
        if all(value is None for value in population):
            if any(
                value is not None
                for value in (
                    self.event_count,
                    self.active_repo_count,
                    self.sample_event_count,
                    self.selected_event_count,
                    self.evidence_lookup,
                )
            ):
                raise ValueError("missing periods cannot carry numeric observations")
            return self
        if any(value is None for value in population):
            raise ValueError("period population fields must be supplied together")
        assert self.sample_repo_count is not None
        assert self.selected_repo_count is not None
        assert self.excluded_repo_count is not None
        if (
            self.sample_repo_count + self.excluded_repo_count
            != self.selected_repo_count
        ):
            raise ValueError("sample and excluded repositories must reconcile")
        if self.sample_repo_count == 0:
            if self.event_count is not None or self.active_repo_count is not None:
                raise ValueError("empty samples must not serialize false zero metrics")
        elif self.event_count is None or self.active_repo_count is None:
            raise ValueError("non-empty samples require numeric metrics")
        if (
            self.active_repo_count is not None
            and self.active_repo_count > self.sample_repo_count
        ):
            raise ValueError("active_repo_count exceeds sample_repo_count")
        return self


class ArchiveTrendResult(ArchiveModel):
    schema_version: Literal["c-gharchive-trend/v1"] = ARCHIVE_TREND_SCHEMA_VERSION
    source: Literal["GITHUB_GH_ARCHIVE"] = "GITHUB_GH_ARCHIVE"
    tech_id: StrictStr
    metric: Literal["gh_archive_event_count"] = "gh_archive_event_count"
    unit: Literal["EVENTS"] = "EVENTS"
    granularity: PeriodGranularity
    status: TrendStatus
    reasons: tuple[str, ...] = ()
    registry_version: StrictStr
    algorithm_version: Literal["c-gharchive-current-evidence-join/v1"] = (
        ARCHIVE_TREND_ALGORITHM_VERSION
    )
    observation_semantics: Literal["CURRENT_PINNED_POSITIVE_OBSERVATIONS_ONLY"] = (
        "CURRENT_PINNED_POSITIVE_OBSERVATIONS_ONLY"
    )
    include_partial: StrictBool
    points: tuple[ArchiveTrendPoint, ...]

    @model_validator(mode="after")
    def validate_result_periods(self) -> ArchiveTrendResult:
        indices = tuple(
            _period_index(row.period, self.granularity) for row in self.points
        )
        if indices != tuple(sorted(set(indices))):
            raise ValueError("result periods must be unique and ascending")
        if any(row.granularity is not self.granularity for row in self.points):
            raise ValueError("result cannot mix period granularities")
        if any(
            row.evidence_lookup is not None
            and row.evidence_lookup.tech_id != self.tech_id
            for row in self.points
        ):
            raise ValueError("evidence lookup tech_id must match result tech_id")
        return self


@dataclass(frozen=True)
class _ActivityRow:
    period: str
    repo_id: int
    repo_name: str
    event_count: int


def _normalize_activity_row(
    raw: Mapping[str, object], granularity: PeriodGranularity
) -> _ActivityRow:
    lowered = {str(key).casefold() for key in raw}
    if lowered & _FORBIDDEN_ACTIVITY_FIELDS:
        raise ValueError("activity rows must not carry client technology fields")
    period_field = "period" if granularity is PeriodGranularity.MONTH else "week_start"
    period = raw.get(period_field)
    repo_id = raw.get("repo_id")
    repo_name = raw.get("repo_name")
    event_count = raw.get("event_count")
    if not isinstance(period, str):
        raise TypeError(f"activity row requires string {period_field}")
    _period_index(period, granularity)
    if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
        raise ValueError("repo_id must be a strict positive integer")
    if not isinstance(repo_name, str) or not repo_name.strip():
        raise ValueError("repo_name must be a non-blank string")
    if (
        isinstance(event_count, bool)
        or not isinstance(event_count, int)
        or event_count < 0
    ):
        raise ValueError("event_count must be a strict nonnegative integer")
    return _ActivityRow(period, repo_id, repo_name, event_count)


def _payload_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _validate_public_lineage(period_input: ArchivePeriodInput) -> None:
    public = period_input.public_analysis
    payload = public.model_dump(mode="json")
    stored_snapshot_id = "c-" + _payload_digest(
        {"kind": "PUBLIC_GITHUB", "owner": None, "payload": payload}
    )
    expected_uri = f"c-compute://snapshot/{stored_snapshot_id}"
    if period_input.public_snapshot_uri != expected_uri:
        raise ValueError("public_snapshot_uri must identify the stored C snapshot")
    if not re.fullmatch(r"[0-9a-f]{64}", period_input.public_snapshot_hash):
        raise ValueError("public_snapshot_hash must be a lowercase SHA-256")
    expected_hash = _payload_digest(payload)
    if period_input.public_snapshot_hash != expected_hash:
        raise ValueError("public_snapshot_hash does not match the stored payload")


def _evidence_example(record: PublicRepoResult, tech_id: str) -> ArchiveEvidenceExample:
    observations = sorted(
        (row for row in record.observations if row.tech_id == tech_id),
        key=lambda row: (row.path, row.uri, row.content_hash, row.line or 0),
    )
    observation = observations[0]
    return ArchiveEvidenceExample(
        github_repo_id=record.github_repo_id,
        repo_snapshot_id=record.repo_snapshot_id,
        pinned_commit_sha=record.pinned_commit_sha,
        path=observation.path,
        uri=observation.uri,
        content_hash=observation.content_hash,
    )


def _point_for_input(
    tech_id: str,
    period_input: ArchivePeriodInput,
    *,
    include_partial: bool,
) -> ArchiveTrendPoint:
    metadata = period_input.metadata
    public = period_input.public_analysis
    _validate_public_lineage(period_input)
    if public.include_partial != include_partial:
        raise ValueError(
            "public analysis include_partial must match archive trend include_partial"
        )

    activity_by_id: dict[int, _ActivityRow] = {}
    selected_event_count = 0
    for raw in period_input.activity_rows:
        row = _normalize_activity_row(raw, metadata.granularity)
        if row.period != metadata.period:
            raise ValueError("activity row period does not match metadata period")
        if row.repo_id in activity_by_id:
            raise ValueError(f"duplicate repo_id in activity period: {row.repo_id}")
        if len(activity_by_id) >= metadata.top_n_limit:
            raise ValueError("activity rows exceed bounded top_n_limit")
        activity_by_id[row.repo_id] = row
        selected_event_count += row.event_count

    if len(activity_by_id) != metadata.selected_repo_count:
        raise ValueError("activity row count does not match selected_repo_count")
    if selected_event_count != metadata.selected_event_count:
        raise ValueError("activity event sum does not match selected_event_count")

    public_by_id = {record.github_repo_id: record for record in public.records}
    sample_records = tuple(
        record
        for record in public.records
        if record.included_in_denominator and record.github_repo_id in activity_by_id
    )
    sample_repo_count = len(sample_records)
    sample_event_count = sum(
        activity_by_id[record.github_repo_id].event_count for record in sample_records
    )
    selected_repo_count = metadata.selected_repo_count
    excluded_repo_count = selected_repo_count - sample_repo_count
    failed_repo_count = sum(
        record.github_repo_id in activity_by_id
        and (
            record.collection_status is RepoCollectionStatus.FAILED
            or any(
                "FAILED" in reason or "NOT_FOUND" in reason
                for reason in record.exclusion_reasons
            )
        )
        for record in public.records
    )
    partial_repo_count = sum(
        record.collection_status is RepoCollectionStatus.PARTIAL
        for record in sample_records
    )
    unresolved_repo_count = sum(bool(record.unresolved) for record in sample_records)

    positive_records = tuple(
        record
        for record in sample_records
        if any(observation.tech_id == tech_id for observation in record.observations)
    )
    positive_records = tuple(
        sorted(positive_records, key=lambda row: row.github_repo_id)
    )
    event_count = (
        sum(activity_by_id[row.github_repo_id].event_count for row in positive_records)
        if sample_repo_count
        else None
    )
    active_repo_count = (
        sum(
            activity_by_id[row.github_repo_id].event_count > 0
            for row in positive_records
        )
        if sample_repo_count
        else None
    )

    quality: list[str] = []
    if sample_repo_count == 0:
        quality.append("NO_ELIGIBLE_PARSED_REPOSITORIES")
    if excluded_repo_count:
        quality.append("SELECTED_REPOSITORIES_EXCLUDED")
    if any(repo_id not in public_by_id for repo_id in activity_by_id):
        quality.append("ACTIVITY_REPOSITORY_WITHOUT_PUBLIC_RESULT")
    if any(
        record.github_repo_id not in activity_by_id
        for record in public.records
        if record.included_in_denominator
    ):
        quality.append("PUBLIC_REPOSITORY_MISSING_ACTIVITY")
    if any(
        activity_by_id[record.github_repo_id].repo_name.casefold()
        != record.repo_full_name.casefold()
        for record in sample_records
    ):
        quality.append("REPOSITORY_NAME_CHANGED")
    if partial_repo_count:
        quality.append("PARTIAL_COLLECTION_INCLUDED")
    if unresolved_repo_count:
        quality.append("UNRESOLVED_TECHNOLOGY_OBSERVATIONS")
    if any(record.status is not TrendStatus.READY for record in sample_records):
        quality.append("PUBLIC_ANALYSIS_NOT_READY")
    if event_count == 0:
        quality.append("ZERO_MEANS_NO_CURRENT_POSITIVE_OBSERVATION")

    degrading = set(quality) - {
        "ZERO_MEANS_NO_CURRENT_POSITIVE_OBSERVATION",
        "REPOSITORY_NAME_CHANGED",
    }
    status = (
        TrendStatus.READY
        if sample_repo_count and not degrading
        else TrendStatus.INSUFFICIENT_DATA
    )

    example_records = positive_records[:MAX_EVIDENCE_EXAMPLES]
    examples = tuple(_evidence_example(record, tech_id) for record in example_records)
    example_repo_ids = tuple(record.github_repo_id for record in example_records)
    lookup = ArchiveEvidenceLookup(
        public_dataset_snapshot_id=public.dataset_snapshot_id,
        public_snapshot_uri=period_input.public_snapshot_uri,
        public_snapshot_hash=period_input.public_snapshot_hash,
        tech_id=tech_id,
        matching_repo_count=len(positive_records),
        example_repo_ids=example_repo_ids,
        examples_truncated=len(positive_records) > len(example_records),
    )
    return ArchiveTrendPoint(
        period=metadata.period,
        granularity=metadata.granularity,
        status=status,
        event_count=event_count,
        active_repo_count=active_repo_count,
        sample_repo_count=sample_repo_count,
        sample_event_count=sample_event_count,
        selected_repo_count=selected_repo_count,
        selected_event_count=selected_event_count,
        analyzed_repo_coverage=(
            sample_repo_count / selected_repo_count if selected_repo_count else 0.0
        ),
        analyzed_event_coverage=(
            sample_event_count / selected_event_count if selected_event_count else 0.0
        ),
        selection_event_coverage=metadata.selection_event_coverage,
        excluded_repo_count=excluded_repo_count,
        failed_repo_count=failed_repo_count,
        partial_repo_count=partial_repo_count,
        unresolved_repo_count=unresolved_repo_count,
        quality_reasons=tuple(quality),
        activity_schema_version=metadata.source_schema_version,
        activity_source_version=metadata.source_version,
        activity_dataset_snapshot_id=metadata.dataset_snapshot_id,
        activity_source_uri=metadata.source_uri,
        activity_source_hash=metadata.source_hash,
        activity_upstream_source_uri=metadata.upstream_source_uri,
        activity_upstream_source_hash=metadata.upstream_source_hash,
        public_dataset_snapshot_id=public.dataset_snapshot_id,
        public_pipeline_run_id=public.pipeline_run_id,
        public_collector_version=public.collector_version,
        public_collection_policy_version=public.collection_policy_version,
        public_parser_version=public.parser_version,
        public_generated_at=public.generated_at,
        public_snapshot_uri=period_input.public_snapshot_uri,
        public_snapshot_hash=period_input.public_snapshot_hash,
        evidence_lookup=lookup,
        evidence_examples=examples,
    )


def archive_trend(
    tech_id: str,
    period_inputs: Iterable[ArchivePeriodInput],
    registry: TechnologyRegistry,
    *,
    periods: tuple[str, ...],
    granularity: PeriodGranularity | str,
    include_partial: bool = False,
) -> ArchiveTrendResult:
    """Calculate period activity for current positive technology observations.

    Activity rows must already be a bounded Top-N export.  This function never
    accepts a client-supplied technology set and never interprets missing,
    failed, or unresolved repository evidence as technology non-use.
    """

    try:
        period_granularity = PeriodGranularity(granularity)
    except ValueError as exc:
        raise ValueError("granularity must be MONTH or WEEK") from exc
    indices = tuple(_period_index(period, period_granularity) for period in periods)
    if not periods:
        raise ValueError("at least one explicit period is required")
    if indices != tuple(sorted(set(indices))):
        raise ValueError("periods must be unique and ascending")
    if not isinstance(tech_id, str) or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", tech_id
    ):
        raise ValueError("tech_id must use the Registry identifier format")
    technology = next(
        (row for row in registry.technologies if row.tech_id == tech_id), None
    )
    if technology is None or technology.status is not RegistryStatus.ACTIVE:
        raise ValueError("tech_id must reference an active Registry technology")
    if not isinstance(include_partial, bool):
        raise TypeError("include_partial must be boolean")

    inputs_by_period: dict[str, ArchivePeriodInput] = {}
    for period_input in period_inputs:
        metadata = period_input.metadata
        if metadata.granularity is not period_granularity:
            raise ValueError(
                "period input granularity does not match requested granularity"
            )
        if metadata.period not in periods:
            raise ValueError("period input is outside requested periods")
        if metadata.period in inputs_by_period:
            raise ValueError("duplicate period input")
        if period_input.public_analysis.registry_version != registry.registry_version:
            raise ValueError("public analysis registry_version does not match Registry")
        inputs_by_period[metadata.period] = period_input

    points: list[ArchiveTrendPoint] = []
    for period in periods:
        period_input = inputs_by_period.get(period)
        if period_input is None:
            points.append(
                ArchiveTrendPoint(
                    period=period,
                    granularity=period_granularity,
                    status=TrendStatus.INSUFFICIENT_DATA,
                    quality_reasons=("MISSING_PERIOD_INPUT",),
                )
            )
        else:
            points.append(
                _point_for_input(
                    tech_id,
                    period_input,
                    include_partial=include_partial,
                )
            )

    consecutive = all(
        indices[index] == indices[index - 1] + 1 for index in range(1, len(indices))
    )
    ready = (
        len(points) >= 2
        and consecutive
        and all(point.status is TrendStatus.READY for point in points)
    )
    return ArchiveTrendResult(
        tech_id=tech_id,
        granularity=period_granularity,
        status=TrendStatus.READY if ready else TrendStatus.INSUFFICIENT_DATA,
        reasons=() if ready else ("MISSING_PERIOD_BASELINE_OR_QUALITY",),
        registry_version=registry.registry_version,
        include_partial=include_partial,
        points=tuple(points),
    )


def _coerce_file_row(
    raw: Mapping[str, object], granularity: PeriodGranularity
) -> dict[str, object]:
    row = dict(raw)
    for field in ("repo_id", "event_count"):
        value = row.get(field)
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            row[field] = int(value)
    normalized = _normalize_activity_row(row, granularity)
    row.update(
        repo_id=normalized.repo_id,
        repo_name=normalized.repo_name,
        event_count=normalized.event_count,
    )
    return row


def iter_bounded_activity_file(
    path: Path,
    *,
    granularity: PeriodGranularity | str,
    max_rows: int,
) -> Iterator[dict[str, object]]:
    """Stream a bounded CSV/NDJSON export without materializing it.

    Parquet is intentionally not decoded in the API runtime.  A's Spark job
    should semi-join candidate IDs and export at most Top-N rows per period.
    """

    try:
        period_granularity = PeriodGranularity(granularity)
    except ValueError as exc:
        raise ValueError("granularity must be MONTH or WEEK") from exc
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    suffix = path.suffix.casefold()
    if suffix == ".parquet":
        raise ValueError(
            "Parquet must be filtered/exported by the existing Spark data path"
        )
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        yield from iter_bounded_activity_stream(
            stream,
            suffix=suffix,
            granularity=period_granularity,
            max_rows=max_rows,
        )


def iter_bounded_activity_stream(
    stream: TextIO,
    *,
    suffix: str,
    granularity: PeriodGranularity | str,
    max_rows: int,
) -> Iterator[dict[str, object]]:
    """Parse already checksum-verified text bytes without reopening a path."""

    try:
        period_granularity = PeriodGranularity(granularity)
    except ValueError as exc:
        raise ValueError("granularity must be MONTH or WEEK") from exc
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    normalized_suffix = suffix.casefold()
    if normalized_suffix == ".csv":
        reader: Iterable[Mapping[str, object]] = csv.DictReader(stream)
        yield from _yield_bounded(reader, period_granularity, max_rows)
        return
    if normalized_suffix not in {".jsonl", ".ndjson"}:
        raise ValueError("activity stream suffix must be CSV, JSONL, or NDJSON")

    def rows() -> Iterator[Mapping[str, object]]:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid activity NDJSON at line {line_number}"
                ) from exc
            if not isinstance(value, dict):
                raise TypeError("each activity NDJSON row must be an object")
            yield value

    yield from _yield_bounded(rows(), period_granularity, max_rows)


def _yield_bounded(
    rows: Iterable[Mapping[str, object]],
    granularity: PeriodGranularity,
    max_rows: int,
) -> Iterator[dict[str, object]]:
    for index, row in enumerate(rows, start=1):
        if index > max_rows:
            raise ValueError("activity file exceeds max_rows")
        yield _coerce_file_row(row, granularity)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a local immutable export without loading the full file."""

    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
