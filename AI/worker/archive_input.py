"""Read a bounded immutable local export and stored C public analysis for Trend."""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from github.public_analysis import PublicBatchResult
from trend.archive import (
    ARCHIVE_TREND_ALGORITHM_VERSION,
    ArchiveActivityMetadata,
    ArchivePeriodInput,
    PeriodGranularity,
    archive_trend,
    iter_bounded_activity_stream,
)
from worker.store import Artifact, digest

MAX_ACTIVITY_BYTES = 32 * 1024 * 1024
MAX_ACTIVITY_ROWS = 50_000
MAX_TOTAL_ACTIVITY_BYTES = 64 * 1024 * 1024
MAX_TOTAL_ACTIVITY_ROWS = 100_000


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

    def include(self, *, byte_count: int, row_count: int) -> ArchiveInputBudget:
        next_byte_count = self.byte_count + byte_count
        next_row_count = self.row_count + row_count
        if next_byte_count > MAX_TOTAL_ACTIVITY_BYTES:
            raise ValueError("archive activity inputs exceed total byte limit")
        if next_row_count > MAX_TOTAL_ACTIVITY_ROWS:
            raise ValueError("archive activity inputs exceed total row limit")
        return ArchiveInputBudget(next_byte_count, next_row_count)


class ArchiveInputReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: ArchiveActivityMetadata
    public_snapshot_id: Annotated[str, StringConstraints(pattern=r"^c-[0-9a-f]{64}$")]
    activity_path: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class ArchiveTrendFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tech_id: Annotated[
        str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    ]
    periods: tuple[str, ...] = Field(min_length=1, max_length=48)
    granularity: PeriodGranularity
    inputs: tuple[ArchiveInputReference, ...] = Field(max_length=48)
    include_partial: StrictBool = False


def _verified_activity_export(
    reference: ArchiveInputReference, root: Path
) -> tuple[tuple[dict[str, object], ...], int]:
    relative = reference.activity_path
    if (
        "\\" in relative
        or ":" in relative
        or PurePosixPath(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ValueError("activity_path must be a safe relative export path")
    try:
        resolved_root = root.resolve(strict=True)
        path = (resolved_root / relative).resolve(strict=True)
        if not path.is_relative_to(resolved_root) or not path.is_file():
            raise ValueError("activity export is outside configured root")
        # Hash and parse the very same bounded bytes: replacing the pathname between
        # separate hash/read operations must never publish unverified content.
        with path.open("rb") as stream:
            data = stream.read(MAX_ACTIVITY_BYTES + 1)
    except OSError as exc:
        raise ArchiveInputUnavailable(relative, exc) from exc
    if len(data) > MAX_ACTIVITY_BYTES:
        raise ValueError("activity export exceeds byte limit")
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
    return rows, len(data)


def verified_activity_rows(reference: ArchiveInputReference, root: Path):
    rows, _ = _verified_activity_export(reference, root)
    return rows


def build_archive_artifact(event: ArchiveTrendFields, *, registry, snapshot):
    configured_root = os.getenv("C_ARCHIVE_ACTIVITY_ROOT")
    if event.inputs and not configured_root:
        raise HTTPException(503, "C_ARCHIVE_ACTIVITY_ROOT_NOT_CONFIGURED")
    period_inputs = []
    input_budget = ArchiveInputBudget()
    for reference in event.inputs:
        try:
            rows, byte_count = _verified_activity_export(
                reference, Path(configured_root)
            )
            input_budget = input_budget.include(
                byte_count=byte_count, row_count=len(rows)
            )
        except (UnicodeError, TypeError) as exc:
            raise ValueError("activity export cannot be read") from exc
        payload = snapshot(reference.public_snapshot_id, None, "PUBLIC_GITHUB")[
            "payload"
        ]
        period_inputs.append(
            ArchivePeriodInput(
                metadata=reference.metadata,
                activity_rows=rows,
                public_analysis=PublicBatchResult.model_validate(payload),
                public_snapshot_uri=f"c-compute://snapshot/{reference.public_snapshot_id}",
                public_snapshot_hash=digest(payload),
            )
        )
    result = archive_trend(
        event.tech_id,
        period_inputs,
        registry,
        periods=event.periods,
        granularity=event.granularity,
        include_partial=event.include_partial,
    )
    return Artifact(
        "TREND",
        None,
        result.model_dump(mode="json"),
        digest(
            {
                "source": "GH_ARCHIVE",
                "tech_id": event.tech_id,
                "periods": event.periods,
                "granularity": event.granularity,
                "include_partial": event.include_partial,
                "registry": registry.registry_version,
                "algorithm": ARCHIVE_TREND_ALGORITHM_VERSION,
            }
        ),
    )
