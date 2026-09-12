"""Historical GH Archive trend joined to A's monthly PushEvent commit lineage.

The existing :mod:`trend.archive` v1 contract deliberately keeps its current-HEAD
semantics.  This module accepts A's additive ``github-repo-snapshot/v1`` lineage
fields and excludes legacy or fallback HEADs from historical observations.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit

from github.contracts import (
    GitHubRepoSnapshot,
    GitHubRepoSnapshotBatch,
    RepoCollectionStatus,
)
from github.public_analysis import PublicBatchResult, PublicRepoResult
from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from registry.contracts import RegistryStatus, TechnologyRegistry
from registry.mapper import MatchStatus

from trend.archive import (
    MAX_EVIDENCE_EXAMPLES,
    ArchiveActivityMetadata,
    ArchiveEvidenceExample,
    ArchiveEvidenceLookup,
    ArchiveModel,
    ArchiveTrendPoint,
    PeriodGranularity,
    _normalize_activity_row,
    _period_index,
    _validate_public_lineage,
    iter_bounded_activity_stream,
)
from trend.contracts import TrendStatus

HISTORICAL_ARCHIVE_TREND_SCHEMA_VERSION = "c-gharchive-historical-trend/v2"
HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION = "c-gharchive-monthly-push-head-join/v2"
HISTORICAL_OBSERVATION_SEMANTICS = (
    "HISTORICAL_MONTHLY_PUSH_HEAD_POSITIVE_OBSERVATIONS_ONLY"
)

_HASH = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
_COMMIT_SHA = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{40}$")]
_ADDITIVE_LINEAGE_FIELDS = frozenset(
    {
        "selected_commit_sha",
        "sha_source",
        "monthly_event_sha",
        "current_default_head",
        "sha_fallback_reason",
        "target_period",
    }
)


class ARepoCommitLineage(ArchiveModel):
    """A's additive v1 lineage contract until A's model reaches this branch.

    Keep the state rules adjacent to the temporary compatibility projection below.
    Once A's additive fields are available on ``GitHubRepoSnapshot``, replace this
    model plus the projection with direct ``GitHubRepoSnapshotBatch`` validation.
    """

    repo_snapshot_id: StrictStr
    github_repo_id: Annotated[StrictInt, Field(gt=0)]
    pinned_commit_sha: _COMMIT_SHA
    selected_commit_sha: _COMMIT_SHA | None = None
    sha_source: Literal["MONTH_EVENT_SHA", "CURRENT_DEFAULT_HEAD"] | None = None
    monthly_event_sha: _COMMIT_SHA | None = None
    current_default_head: _COMMIT_SHA | None = None
    sha_fallback_reason: StrictStr | None = None
    target_period: StrictStr | None = None

    @field_validator("sha_fallback_reason", "target_period")
    @classmethod
    def reject_blank_optional_identifier(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional identifier must not be blank")
        return value

    @model_validator(mode="after")
    def validate_additive_state(self) -> ARepoCommitLineage:
        """Mirror fbebac1's additive ``GitHubRepoSnapshot`` invariants exactly."""

        if (
            self.selected_commit_sha is not None
            and self.selected_commit_sha != self.pinned_commit_sha
        ):
            raise ValueError("selected_commit_sha must equal pinned_commit_sha")
        if self.sha_source == "MONTH_EVENT_SHA":
            if self.monthly_event_sha is None:
                raise ValueError("MONTH_EVENT_SHA requires monthly_event_sha")
            if self.selected_commit_sha != self.monthly_event_sha:
                raise ValueError("MONTH_EVENT_SHA must select monthly_event_sha")
            if self.sha_fallback_reason is not None:
                raise ValueError("MONTH_EVENT_SHA must not have a fallback reason")
        elif self.sha_source == "CURRENT_DEFAULT_HEAD":
            if self.current_default_head is None:
                raise ValueError("CURRENT_DEFAULT_HEAD requires current_default_head")
            if self.selected_commit_sha != self.current_default_head:
                raise ValueError(
                    "CURRENT_DEFAULT_HEAD must select current_default_head"
                )
            if self.sha_fallback_reason is None:
                raise ValueError("CURRENT_DEFAULT_HEAD requires a selection reason")
        elif any(
            value is not None
            for value in (
                self.selected_commit_sha,
                self.monthly_event_sha,
                self.current_default_head,
                self.sha_fallback_reason,
            )
        ):
            raise ValueError("commit lineage fields require sha_source")
        return self


@dataclass(frozen=True)
class ValidatedARepoLineage:
    snapshot: GitHubRepoSnapshot
    lineage: ARepoCommitLineage


@dataclass(frozen=True)
class HistoricalArchivePeriodInput:
    """Exact immutable bytes for one activity export and its A/C snapshots."""

    metadata: ArchiveActivityMetadata
    activity_bytes: bytes
    activity_suffix: str
    a_snapshot_bytes: bytes
    a_snapshot_uri: str
    a_snapshot_hash: str
    public_analysis: PublicBatchResult
    public_snapshot_payload: Mapping[str, object]
    public_snapshot_uri: str
    public_snapshot_hash: str


class HistoricalArchiveEvidenceExample(ArchiveEvidenceExample):
    evidence_basis: Literal["ARTIFACT"] = "ARTIFACT"
    selected_commit_sha: _COMMIT_SHA
    sha_source: Literal["MONTH_EVENT_SHA"] = "MONTH_EVENT_SHA"
    monthly_event_sha: _COMMIT_SHA
    target_period: StrictStr


class HistoricalArchiveLanguageEvidenceExample(ArchiveModel):
    github_repo_id: Annotated[StrictInt, Field(gt=0)]
    repo_snapshot_id: StrictStr
    pinned_commit_sha: _COMMIT_SHA
    selected_commit_sha: _COMMIT_SHA
    sha_source: Literal["MONTH_EVENT_SHA"] = "MONTH_EVENT_SHA"
    monthly_event_sha: _COMMIT_SHA
    target_period: StrictStr
    evidence_basis: Literal["GITHUB_LANGUAGE"] = "GITHUB_LANGUAGE"
    language: StrictStr
    file_count: Annotated[StrictInt, Field(gt=0)]
    representative_paths: tuple[StrictStr, ...]


class HistoricalArchiveTrendPoint(ArchiveTrendPoint):
    historical_head_matched_repo_count: Annotated[StrictInt, Field(ge=0)] | None = None
    historical_head_matched_event_count: Annotated[StrictInt, Field(ge=0)] | None = None
    historical_head_repo_coverage: float | None = Field(default=None, ge=0, le=1)
    historical_head_event_coverage: float | None = Field(default=None, ge=0, le=1)
    historical_head_unavailable_repo_count: Annotated[StrictInt, Field(ge=0)] | None = (
        None
    )
    historical_head_mismatch_repo_count: Annotated[StrictInt, Field(ge=0)] | None = None
    a_snapshot_uri: str | None = None
    a_snapshot_hash: _HASH | None = None
    evidence_examples: tuple[
        HistoricalArchiveEvidenceExample | HistoricalArchiveLanguageEvidenceExample,
        ...,
    ] = ()

    @model_validator(mode="after")
    def reconcile_historical_head_coverage(self) -> HistoricalArchiveTrendPoint:
        counts = (
            self.historical_head_matched_repo_count,
            self.historical_head_unavailable_repo_count,
            self.historical_head_mismatch_repo_count,
        )
        if all(value is None for value in counts):
            return self
        if any(value is None for value in counts) or self.selected_repo_count is None:
            raise ValueError("historical head counts must be supplied together")
        assert self.historical_head_matched_repo_count is not None
        assert self.historical_head_unavailable_repo_count is not None
        assert self.historical_head_mismatch_repo_count is not None
        historical_total = (
            self.historical_head_matched_repo_count
            + self.historical_head_unavailable_repo_count
            + self.historical_head_mismatch_repo_count
        )
        if historical_total != self.selected_repo_count:
            raise ValueError("historical head counts must reconcile to selected repos")
        if (
            self.sample_repo_count is not None
            and self.sample_repo_count > self.historical_head_matched_repo_count
        ):
            raise ValueError("sample repos exceed matched historical heads")
        if self.historical_head_matched_event_count is None:
            raise ValueError("historical matched event count is required")
        if (
            self.selected_event_count is None
            or self.historical_head_matched_event_count > self.selected_event_count
        ):
            raise ValueError("historical matched events exceed selected events")
        expected_repo_coverage = (
            self.historical_head_matched_repo_count / self.selected_repo_count
            if self.selected_repo_count
            else 0.0
        )
        expected_event_coverage = (
            self.historical_head_matched_event_count / self.selected_event_count
            if self.selected_event_count
            else 0.0
        )
        if (
            self.historical_head_repo_coverage is None
            or abs(self.historical_head_repo_coverage - expected_repo_coverage) > 1e-12
        ):
            raise ValueError("historical head repo coverage is inconsistent")
        if (
            self.historical_head_event_coverage is None
            or abs(self.historical_head_event_coverage - expected_event_coverage)
            > 1e-12
        ):
            raise ValueError("historical head event coverage is inconsistent")
        return self


class HistoricalArchiveTrendResult(ArchiveModel):
    schema_version: Literal["c-gharchive-historical-trend/v2"] = (
        HISTORICAL_ARCHIVE_TREND_SCHEMA_VERSION
    )
    source: Literal["GITHUB_GH_ARCHIVE"] = "GITHUB_GH_ARCHIVE"
    tech_id: StrictStr
    metric: Literal["gh_archive_event_count"] = "gh_archive_event_count"
    unit: Literal["EVENTS"] = "EVENTS"
    granularity: Literal[PeriodGranularity.MONTH] = PeriodGranularity.MONTH
    status: TrendStatus
    reasons: tuple[str, ...] = ()
    registry_version: StrictStr
    algorithm_version: Literal["c-gharchive-monthly-push-head-join/v2"] = (
        HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION
    )
    observation_semantics: Literal[
        "HISTORICAL_MONTHLY_PUSH_HEAD_POSITIVE_OBSERVATIONS_ONLY"
    ] = HISTORICAL_OBSERVATION_SEMANTICS
    include_partial: StrictBool
    points: tuple[HistoricalArchiveTrendPoint, ...]

    @model_validator(mode="after")
    def validate_result_periods(self) -> HistoricalArchiveTrendResult:
        indices = tuple(
            _period_index(point.period, PeriodGranularity.MONTH)
            for point in self.points
        )
        if indices != tuple(sorted(set(indices))):
            raise ValueError("result periods must be unique and ascending")
        if any(
            point.granularity is not PeriodGranularity.MONTH for point in self.points
        ):
            raise ValueError("historical result must contain monthly points")
        if any(
            point.evidence_lookup is not None
            and point.evidence_lookup.tech_id != self.tech_id
            for point in self.points
        ):
            raise ValueError("evidence lookup tech_id must match result tech_id")
        return self


def _absolute_uri(value: str, field_name: str) -> str:
    parsed = urlsplit(value)
    if not value.strip() or not parsed.scheme or not parsed.path:
        raise ValueError(f"{field_name} must be a non-blank absolute URI")
    return value


def _month_target_period(period: str) -> str:
    year, month = (int(part) for part in period.split("-"))
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = date.fromordinal(next_month.toordinal() - 1)
    return f"{year:04d}-{month:02d}-01/{last_day.isoformat()}"


def _activity_rows(
    period_input: HistoricalArchivePeriodInput,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(period_input.activity_bytes, bytes):
        raise TypeError("activity_bytes must be bytes")
    actual = hashlib.sha256(period_input.activity_bytes).hexdigest()
    if actual != period_input.metadata.source_hash:
        raise ValueError("activity export checksum mismatch")
    try:
        text = period_input.activity_bytes.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("activity export must be UTF-8") from exc
    return tuple(
        iter_bounded_activity_stream(
            io.StringIO(text),
            suffix=period_input.activity_suffix,
            granularity=PeriodGranularity.MONTH,
            max_rows=period_input.metadata.top_n_limit,
        )
    )


def _a_lineage(
    period_input: HistoricalArchivePeriodInput,
) -> dict[int, ValidatedARepoLineage]:
    if not isinstance(period_input.a_snapshot_bytes, bytes):
        raise TypeError("a_snapshot_bytes must be bytes")
    if not re.fullmatch(r"[0-9a-f]{64}", period_input.a_snapshot_hash):
        raise ValueError("a_snapshot_hash must be a lowercase SHA-256")
    actual = hashlib.sha256(period_input.a_snapshot_bytes).hexdigest()
    if actual != period_input.a_snapshot_hash:
        raise ValueError("A repository snapshot checksum mismatch")
    _absolute_uri(period_input.a_snapshot_uri, "a_snapshot_uri")
    try:
        payload = json.loads(period_input.a_snapshot_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("A repository snapshot must be UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("A repository snapshot must be an object")
    if payload.get("schema_version") != "github-repo-snapshot/v1":
        raise ValueError("unsupported A repository snapshot schema_version")
    if payload.get("dataset_snapshot_id") != (
        period_input.public_analysis.dataset_snapshot_id
    ):
        raise ValueError("A and public dataset_snapshot_id do not match")
    if payload.get("pipeline_run_id") != period_input.public_analysis.pipeline_run_id:
        raise ValueError("A and public pipeline_run_id do not match")
    if payload.get("collector_version") != (
        period_input.public_analysis.collector_version
    ):
        raise ValueError("A and public collector_version do not match")
    collection_policy = payload.get("collection_policy")
    if (
        not isinstance(collection_policy, dict)
        or collection_policy.get("policy_version")
        != period_input.public_analysis.collection_policy_version
    ):
        raise ValueError("A and public collection policy versions do not match")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise TypeError("A repository snapshot records must be an array")

    base_payload = {
        **payload,
        "records": [
            {
                field: value
                for field, value in raw.items()
                if field not in _ADDITIVE_LINEAGE_FIELDS
            }
            if isinstance(raw, dict)
            else raw
            for raw in raw_records
        ],
    }
    base_batch = GitHubRepoSnapshotBatch.model_validate(base_payload)

    fields = tuple(ARepoCommitLineage.model_fields)
    by_id: dict[int, ValidatedARepoLineage] = {}
    for raw, snapshot in zip(raw_records, base_batch.records, strict=True):
        if not isinstance(raw, dict):
            raise TypeError("A repository snapshot record must be an object")
        lineage = ARepoCommitLineage.model_validate(
            {field: raw[field] for field in fields if field in raw}
        )
        if (
            lineage.github_repo_id != snapshot.github_repo_id
            or lineage.repo_snapshot_id != snapshot.repo_snapshot_id
            or lineage.pinned_commit_sha != snapshot.pinned_commit_sha
        ):
            raise ValueError(
                "A base snapshot and commit lineage identities do not match"
            )
        by_id[lineage.github_repo_id] = ValidatedARepoLineage(
            snapshot=snapshot,
            lineage=lineage,
        )
    return by_id


def _historical_head_state(
    record: PublicRepoResult | None,
    validated: ValidatedARepoLineage | None,
    period: str,
) -> Literal["MATCHED", "UNAVAILABLE", "MISMATCH"]:
    if validated is None:
        return "UNAVAILABLE"
    snapshot = validated.snapshot
    lineage = validated.lineage
    if (
        lineage.sha_source != "MONTH_EVENT_SHA"
        or lineage.monthly_event_sha is None
        or lineage.selected_commit_sha is None
    ):
        return "UNAVAILABLE"
    if record is None:
        return "MISMATCH"
    expected_period = _month_target_period(period)
    expected_start, expected_end = expected_period.split("/", 1)
    if (
        snapshot.github_repo_id != lineage.github_repo_id
        or snapshot.repo_snapshot_id != lineage.repo_snapshot_id
        or snapshot.pinned_commit_sha != lineage.pinned_commit_sha
        or snapshot.github_repo_id != record.github_repo_id
        or snapshot.repo_snapshot_id != record.repo_snapshot_id
        or snapshot.pinned_commit_sha != record.pinned_commit_sha
        or snapshot.repo_full_name.casefold() != record.repo_full_name.casefold()
        or snapshot.activity_period_start.isoformat() != expected_start
        or snapshot.activity_period_end.isoformat() != expected_end
        or snapshot.activity_period_start.isoformat() != record.activity_period_start
        or snapshot.activity_period_end.isoformat() != record.activity_period_end
        or lineage.repo_snapshot_id != record.repo_snapshot_id
        or lineage.pinned_commit_sha != record.pinned_commit_sha
        or lineage.selected_commit_sha != lineage.pinned_commit_sha
        or lineage.monthly_event_sha != lineage.selected_commit_sha
        or lineage.target_period != expected_period
        or record.activity_period_start != expected_start
        or record.activity_period_end != expected_end
    ):
        return "MISMATCH"
    return "MATCHED"


def _evidence_example(
    record: PublicRepoResult,
    lineage: ARepoCommitLineage,
    tech_id: str,
) -> HistoricalArchiveEvidenceExample | HistoricalArchiveLanguageEvidenceExample:
    observations = sorted(
        (row for row in record.observations if row.tech_id == tech_id),
        key=lambda row: (row.path, row.uri, row.content_hash, row.line or 0),
    )
    assert lineage.selected_commit_sha is not None
    assert lineage.monthly_event_sha is not None
    assert lineage.target_period is not None
    if not observations:
        languages = sorted(
            (
                row
                for row in record.language_observations
                if row.status is MatchStatus.MATCHED and row.tech_id == tech_id
            ),
            key=lambda row: (row.language, row.representative_paths),
        )
        language = languages[0]
        return HistoricalArchiveLanguageEvidenceExample(
            github_repo_id=record.github_repo_id,
            repo_snapshot_id=record.repo_snapshot_id,
            pinned_commit_sha=record.pinned_commit_sha,
            selected_commit_sha=lineage.selected_commit_sha,
            monthly_event_sha=lineage.monthly_event_sha,
            target_period=lineage.target_period,
            language=language.language,
            file_count=language.file_count,
            representative_paths=language.representative_paths,
        )
    observation = observations[0]
    return HistoricalArchiveEvidenceExample(
        github_repo_id=record.github_repo_id,
        repo_snapshot_id=record.repo_snapshot_id,
        pinned_commit_sha=record.pinned_commit_sha,
        selected_commit_sha=lineage.selected_commit_sha,
        monthly_event_sha=lineage.monthly_event_sha,
        target_period=lineage.target_period,
        path=observation.path,
        uri=observation.uri,
        content_hash=observation.content_hash,
    )


def _point_for_input(
    tech_id: str,
    period_input: HistoricalArchivePeriodInput,
    *,
    include_partial: bool,
) -> HistoricalArchiveTrendPoint:
    metadata = period_input.metadata
    public = period_input.public_analysis
    _validate_public_lineage(period_input)
    if public.include_partial != include_partial:
        raise ValueError(
            "public analysis include_partial must match archive trend include_partial"
        )

    rows = _activity_rows(period_input)
    lineage_by_id = _a_lineage(period_input)
    activity_by_id = {}
    selected_event_count = 0
    for raw in rows:
        row = _normalize_activity_row(raw, PeriodGranularity.MONTH)
        if row.period != metadata.period:
            raise ValueError("activity row period does not match metadata period")
        if row.repo_id in activity_by_id:
            raise ValueError(f"duplicate repo_id in activity period: {row.repo_id}")
        activity_by_id[row.repo_id] = row
        selected_event_count += row.event_count
    if len(activity_by_id) != metadata.selected_repo_count:
        raise ValueError("activity row count does not match selected_repo_count")
    if selected_event_count != metadata.selected_event_count:
        raise ValueError("activity event sum does not match selected_event_count")

    public_by_id = {record.github_repo_id: record for record in public.records}
    state_by_id = {
        repo_id: _historical_head_state(
            public_by_id.get(repo_id), lineage_by_id.get(repo_id), metadata.period
        )
        for repo_id in activity_by_id
    }
    matched_ids = {
        repo_id for repo_id, state in state_by_id.items() if state == "MATCHED"
    }
    unavailable_count = sum(state == "UNAVAILABLE" for state in state_by_id.values())
    mismatch_count = sum(state == "MISMATCH" for state in state_by_id.values())
    matched_event_count = sum(
        activity_by_id[repo_id].event_count for repo_id in matched_ids
    )

    sample_records = tuple(
        record
        for record in public.records
        if record.included_in_denominator and record.github_repo_id in matched_ids
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
        sorted(
            (
                record
                for record in sample_records
                if any(
                    observation.tech_id == tech_id
                    for observation in record.observations
                )
                or any(
                    observation.status is MatchStatus.MATCHED
                    and observation.tech_id == tech_id
                    for observation in record.language_observations
                )
            ),
            key=lambda row: row.github_repo_id,
        )
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
        quality.append("NO_ELIGIBLE_HISTORICAL_REPOSITORIES")
    if unavailable_count:
        quality.append("HISTORICAL_HEAD_UNAVAILABLE")
    if mismatch_count:
        quality.append("HISTORICAL_HEAD_MISMATCH")
    if excluded_repo_count:
        quality.append("SELECTED_REPOSITORIES_EXCLUDED")
    if any(repo_id not in public_by_id for repo_id in activity_by_id):
        quality.append("ACTIVITY_REPOSITORY_WITHOUT_PUBLIC_RESULT")
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
        quality.append("ZERO_MEANS_NO_HISTORICAL_POSITIVE_OBSERVATION")

    degrading = set(quality) - {
        "ZERO_MEANS_NO_HISTORICAL_POSITIVE_OBSERVATION",
        "REPOSITORY_NAME_CHANGED",
    }
    status = (
        TrendStatus.READY
        if sample_repo_count and not degrading
        else TrendStatus.INSUFFICIENT_DATA
    )
    example_records = positive_records[:MAX_EVIDENCE_EXAMPLES]
    examples = tuple(
        _evidence_example(record, lineage_by_id[record.github_repo_id].lineage, tech_id)
        for record in example_records
    )
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
    return HistoricalArchiveTrendPoint(
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
        historical_head_matched_repo_count=len(matched_ids),
        historical_head_matched_event_count=matched_event_count,
        historical_head_repo_coverage=(
            len(matched_ids) / selected_repo_count if selected_repo_count else 0.0
        ),
        historical_head_event_coverage=(
            matched_event_count / selected_event_count if selected_event_count else 0.0
        ),
        historical_head_unavailable_repo_count=unavailable_count,
        historical_head_mismatch_repo_count=mismatch_count,
        quality_reasons=tuple(quality),
        activity_schema_version=metadata.source_schema_version,
        activity_source_version=metadata.source_version,
        activity_dataset_snapshot_id=metadata.dataset_snapshot_id,
        activity_source_uri=metadata.source_uri,
        activity_source_hash=metadata.source_hash,
        activity_upstream_source_uri=metadata.upstream_source_uri,
        activity_upstream_source_hash=metadata.upstream_source_hash,
        a_snapshot_uri=period_input.a_snapshot_uri,
        a_snapshot_hash=period_input.a_snapshot_hash,
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


def archive_historical_trend(
    tech_id: str,
    period_inputs: tuple[HistoricalArchivePeriodInput, ...],
    registry: TechnologyRegistry,
    *,
    periods: tuple[str, ...],
    granularity: PeriodGranularity | str,
    include_partial: bool = False,
) -> HistoricalArchiveTrendResult:
    """Calculate historical monthly activity for matching monthly commit evidence."""

    try:
        period_granularity = PeriodGranularity(granularity)
    except ValueError as exc:
        raise ValueError("granularity must be MONTH") from exc
    if period_granularity is not PeriodGranularity.MONTH:
        raise ValueError("historical archive trend v2 supports MONTH only")
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

    inputs_by_period: dict[str, HistoricalArchivePeriodInput] = {}
    for period_input in period_inputs:
        metadata = period_input.metadata
        if metadata.granularity is not PeriodGranularity.MONTH:
            raise ValueError("period input granularity must be MONTH")
        if metadata.period not in periods:
            raise ValueError("period input is outside requested periods")
        if metadata.period in inputs_by_period:
            raise ValueError("duplicate period input")
        if period_input.public_analysis.registry_version != registry.registry_version:
            raise ValueError("public analysis registry_version does not match Registry")
        inputs_by_period[metadata.period] = period_input

    points = []
    for period in periods:
        period_input = inputs_by_period.get(period)
        if period_input is None:
            points.append(
                HistoricalArchiveTrendPoint(
                    period=period,
                    granularity=PeriodGranularity.MONTH,
                    status=TrendStatus.INSUFFICIENT_DATA,
                    quality_reasons=("MISSING_PERIOD_INPUT",),
                )
            )
        else:
            points.append(
                _point_for_input(tech_id, period_input, include_partial=include_partial)
            )

    consecutive = all(
        indices[index] == indices[index - 1] + 1 for index in range(1, len(indices))
    )
    ready = (
        len(points) >= 2
        and consecutive
        and all(point.status is TrendStatus.READY for point in points)
    )
    return HistoricalArchiveTrendResult(
        tech_id=tech_id,
        status=TrendStatus.READY if ready else TrendStatus.INSUFFICIENT_DATA,
        reasons=() if ready else ("MISSING_PERIOD_BASELINE_OR_QUALITY",),
        registry_version=registry.registry_version,
        include_partial=include_partial,
        points=tuple(points),
    )
