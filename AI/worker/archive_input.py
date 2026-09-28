"""Read a bounded immutable local export and stored C public analysis for Trend."""

from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

from github.public_analysis import PublicBatchResult
from trend.archive import (
    ARCHIVE_TREND_ALGORITHM_VERSION,
    ArchiveActivityMetadata,
    ArchivePeriodInput,
    PeriodGranularity,
    archive_trend,
    iter_bounded_activity_stream,
)
from trend.archive_v2 import (
    HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION,
    HistoricalArchivePeriodInput,
    archive_historical_trend,
)
from worker.store import Artifact, digest
from worker.trend_streams import archive_trend_stream

MAX_ACTIVITY_BYTES = 32 * 1024 * 1024
MAX_ACTIVITY_ROWS = 50_000
MAX_TOTAL_ACTIVITY_BYTES = 64 * 1024 * 1024
MAX_TOTAL_ACTIVITY_ROWS = 100_000
MAX_A_SNAPSHOT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_HISTORICAL_BYTES = 256 * 1024 * 1024
PUBLICATION_SCHEMA = "c-public-published-result/v1"


class ArchiveInputUnavailable(RuntimeError):
    """A trusted mounted Archive export cannot currently be read."""

    def __init__(self, activity_path: str, cause: OSError):
        super().__init__("archive activity export is unavailable")
        self.activity_path = activity_path
        self.error_type = type(cause).__name__
        self.errno = cause.errno


@dataclass(frozen=True)
class ArchiveInputBudget:
    byte_count: int = 0
    row_count: int = 0

    def include(
        self,
        *,
        byte_count: int,
        row_count: int,
        max_bytes: int | None = None,
    ) -> ArchiveInputBudget:
        byte_limit = MAX_TOTAL_ACTIVITY_BYTES if max_bytes is None else max_bytes
        next_byte_count = self.byte_count + byte_count
        next_row_count = self.row_count + row_count
        if next_byte_count > byte_limit:
            raise ValueError("archive activity inputs exceed total byte limit")
        if next_row_count > MAX_TOTAL_ACTIVITY_ROWS:
            raise ValueError("archive activity inputs exceed total row limit")
        return ArchiveInputBudget(next_byte_count, next_row_count)


class ArchiveInputReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: ArchiveActivityMetadata
    public_snapshot_id: Annotated[str, StringConstraints(pattern=r"^c-[0-9a-f]{64}$")]
    activity_path: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class HistoricalArchiveInputReference(ArchiveInputReference):
    a_snapshot_path: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    a_snapshot_uri: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    a_snapshot_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ArchiveTrendFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tech_id: Annotated[
        str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    ]
    periods: tuple[str, ...] = Field(min_length=1, max_length=48)
    granularity: PeriodGranularity
    archive_version: Literal["v1", "v2"] = "v1"
    inputs: tuple[HistoricalArchiveInputReference | ArchiveInputReference, ...] = Field(
        max_length=48
    )
    include_partial: StrictBool = False

    @model_validator(mode="after")
    def require_versioned_inputs(self) -> ArchiveTrendFields:
        historical = tuple(
            isinstance(reference, HistoricalArchiveInputReference)
            for reference in self.inputs
        )
        if self.archive_version == "v2" and not all(historical):
            raise ValueError("archive v2 inputs require an A snapshot reference")
        if self.archive_version == "v1" and any(historical):
            raise ValueError(
                "archive v1 inputs must not include an A snapshot reference"
            )
        return self


def _verified_trusted_bytes(
    relative: str,
    root: Path,
    *,
    max_bytes: int,
    label: str,
    exceeds_message: str | None = None,
) -> tuple[Path, bytes]:
    if (
        "\\" in relative
        or ":" in relative
        or PurePosixPath(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ValueError(f"{label} must be a safe relative input path")
    try:
        resolved_root = root.resolve(strict=True)
        path = (resolved_root / relative).resolve(strict=True)
        if not path.is_relative_to(resolved_root) or not path.is_file():
            raise ValueError(f"{label} is outside configured root")
        if path.stat().st_size > max_bytes:
            raise ValueError(exceeds_message or f"{label} exceeds byte limit")
        with path.open("rb") as stream:
            data = stream.read(max_bytes + 1)
    except OSError as exc:
        raise ArchiveInputUnavailable(relative, exc) from exc
    if len(data) > max_bytes:
        raise ValueError(exceeds_message or f"{label} exceeds byte limit")
    return path, data


def _verified_a_snapshot_uri(
    relative_path: str, snapshot_uri: str, configured_root_uri: str
) -> str:
    root = urlsplit(configured_root_uri)
    snapshot = urlsplit(snapshot_uri)
    for parsed, label in (
        (root, "configured A snapshot URI root"),
        (snapshot, "a_snapshot_uri"),
    ):
        if (
            parsed.scheme.casefold() != "hdfs"
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or "\\" in parsed.path
            or "%" in parsed.path
            or any(part in {".", ".."} for part in parsed.path.split("/"))
        ):
            raise ValueError(f"{label} must be a normalized absolute HDFS URI")
    expected_path = root.path.rstrip("/") + "/" + relative_path
    if (
        snapshot.scheme.casefold() != root.scheme.casefold()
        or snapshot.netloc.casefold() != root.netloc.casefold()
        or snapshot.path != expected_path
    ):
        raise ValueError("a_snapshot_uri does not match trusted staging path")
    return snapshot_uri


def _verified_activity_bytes(
    reference: ArchiveInputReference,
    root: Path,
    *,
    max_bytes: int = MAX_ACTIVITY_BYTES,
    exceeds_message: str | None = None,
) -> tuple[bytes, str, tuple[dict[str, object], ...]]:
    path, data = _verified_trusted_bytes(
        reference.activity_path,
        root,
        max_bytes=max_bytes,
        label="activity_path",
        exceeds_message=exceeds_message,
    )
    if hashlib.sha256(data).hexdigest() != reference.metadata.source_hash:
        raise ValueError("activity export checksum mismatch")
    rows = tuple(
        iter_bounded_activity_stream(
            io.StringIO(data.decode("utf-8-sig")),
            suffix=path.suffix,
            granularity=reference.metadata.granularity,
            max_rows=MAX_ACTIVITY_ROWS,
        )
    )
    return data, path.suffix, rows


def _verified_activity_export(
    reference: ArchiveInputReference, root: Path
) -> tuple[tuple[dict[str, object], ...], int]:
    data, _, rows = _verified_activity_bytes(reference, root)
    return rows, len(data)


def verified_activity_rows(reference: ArchiveInputReference, root: Path):
    rows, _ = _verified_activity_export(reference, root)
    return rows


def _public_snapshot(reference: ArchiveInputReference, snapshot):
    payload = snapshot(reference.public_snapshot_id, None, "PUBLIC_GITHUB")["payload"]
    if not isinstance(payload, Mapping):
        raise TypeError("stored public snapshot payload must be an object")
    analysis_payload = payload
    if payload.get("schema_version") == PUBLICATION_SCHEMA:
        publication = payload.get("publication")
        analysis_payload = payload.get("result")
        if not isinstance(publication, Mapping) or not isinstance(
            analysis_payload, Mapping
        ):
            raise TypeError("published public snapshot wrapper is malformed")
    return PublicBatchResult.model_validate(analysis_payload), payload


def _build_current_archive_artifact(event, *, registry, snapshot, root: Path):
    period_inputs = []
    input_budget = ArchiveInputBudget()
    for reference in event.inputs:
        assert isinstance(reference, ArchiveInputReference)
        assert not isinstance(reference, HistoricalArchiveInputReference)
        try:
            rows, byte_count = _verified_activity_export(reference, root)
            input_budget = input_budget.include(
                byte_count=byte_count, row_count=len(rows)
            )
        except (UnicodeError, TypeError) as exc:
            raise ValueError("activity export cannot be read") from exc
        public, payload = _public_snapshot(reference, snapshot)
        period_inputs.append(
            ArchivePeriodInput(
                metadata=reference.metadata,
                activity_rows=rows,
                public_analysis=public,
                public_snapshot_payload=payload,
                public_snapshot_uri=(
                    f"c-compute://snapshot/{reference.public_snapshot_id}"
                ),
                public_snapshot_hash=digest(payload),
            )
        )
    return archive_trend(
        event.tech_id,
        period_inputs,
        registry,
        periods=event.periods,
        granularity=event.granularity,
        include_partial=event.include_partial,
    )


def _build_historical_archive_artifact(
    event, *, registry, snapshot, root: Path, a_snapshot_uri_root: str
):
    period_inputs = []
    input_budget = ArchiveInputBudget()
    for reference in event.inputs:
        assert isinstance(reference, HistoricalArchiveInputReference)
        try:
            remaining_bytes = MAX_TOTAL_HISTORICAL_BYTES - input_budget.byte_count
            if remaining_bytes <= 0:
                raise ValueError("archive historical inputs exceed total byte limit")
            activity_limit = min(MAX_ACTIVITY_BYTES, remaining_bytes)
            activity_bytes, suffix, activity_rows = _verified_activity_bytes(
                reference,
                root,
                max_bytes=activity_limit,
                exceeds_message=(
                    "archive historical inputs exceed total byte limit"
                    if activity_limit < MAX_ACTIVITY_BYTES
                    else None
                ),
            )
            input_budget = input_budget.include(
                byte_count=len(activity_bytes),
                row_count=len(activity_rows),
                max_bytes=MAX_TOTAL_HISTORICAL_BYTES,
            )
            remaining_bytes = MAX_TOTAL_HISTORICAL_BYTES - input_budget.byte_count
            if remaining_bytes <= 0:
                raise ValueError("archive historical inputs exceed total byte limit")
            a_snapshot_limit = min(MAX_A_SNAPSHOT_BYTES, remaining_bytes)
            _, a_snapshot_bytes = _verified_trusted_bytes(
                reference.a_snapshot_path,
                root,
                max_bytes=a_snapshot_limit,
                label="a_snapshot_path",
                exceeds_message=(
                    "archive historical inputs exceed total byte limit"
                    if a_snapshot_limit < MAX_A_SNAPSHOT_BYTES
                    else None
                ),
            )
            if (
                hashlib.sha256(a_snapshot_bytes).hexdigest()
                != reference.a_snapshot_sha256
            ):
                raise ValueError("A repository snapshot checksum mismatch")
            _verified_a_snapshot_uri(
                reference.a_snapshot_path,
                reference.a_snapshot_uri,
                a_snapshot_uri_root,
            )
            input_budget = input_budget.include(
                byte_count=len(a_snapshot_bytes),
                row_count=0,
                max_bytes=MAX_TOTAL_HISTORICAL_BYTES,
            )
        except (UnicodeError, TypeError) as exc:
            raise ValueError("historical archive input cannot be read") from exc
        public, payload = _public_snapshot(reference, snapshot)
        period_inputs.append(
            HistoricalArchivePeriodInput(
                metadata=reference.metadata,
                activity_bytes=activity_bytes,
                activity_suffix=suffix,
                a_snapshot_bytes=a_snapshot_bytes,
                a_snapshot_uri=reference.a_snapshot_uri,
                a_snapshot_hash=reference.a_snapshot_sha256,
                public_analysis=public,
                public_snapshot_payload=payload,
                public_snapshot_uri=(
                    f"c-compute://snapshot/{reference.public_snapshot_id}"
                ),
                public_snapshot_hash=digest(payload),
            )
        )
    return archive_historical_trend(
        event.tech_id,
        tuple(period_inputs),
        registry,
        periods=event.periods,
        granularity=event.granularity,
        include_partial=event.include_partial,
    )


def build_archive_artifact(event: ArchiveTrendFields, *, registry, snapshot):
    configured_root = os.getenv("C_ARCHIVE_ACTIVITY_ROOT")
    if event.inputs and not configured_root:
        raise HTTPException(503, "C_ARCHIVE_ACTIVITY_ROOT_NOT_CONFIGURED")
    configured_a_snapshot_uri_root = os.getenv("C_ARCHIVE_A_SNAPSHOT_URI_ROOT")
    if event.archive_version == "v2" and not configured_a_snapshot_uri_root:
        raise HTTPException(503, "C_ARCHIVE_A_SNAPSHOT_URI_ROOT_NOT_CONFIGURED")
    root = Path(configured_root or ".")
    result = (
        _build_historical_archive_artifact(
            event,
            registry=registry,
            snapshot=snapshot,
            root=root,
            a_snapshot_uri_root=configured_a_snapshot_uri_root,
        )
        if event.archive_version == "v2"
        else _build_current_archive_artifact(
            event, registry=registry, snapshot=snapshot, root=root
        )
    )
    algorithm = (
        HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION
        if event.archive_version == "v2"
        else ARCHIVE_TREND_ALGORITHM_VERSION
    )
    return Artifact(
        "TREND",
        None,
        result.model_dump(mode="json"),
        archive_trend_stream(
            archive_version=event.archive_version,
            tech_id=event.tech_id,
            periods=event.periods,
            granularity=event.granularity,
            include_partial=event.include_partial,
            registry_version=registry.registry_version,
            algorithm=algorithm,
        ),
    )
