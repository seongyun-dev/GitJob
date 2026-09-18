"""Stable stream identities shared by Trend publishers and read-only resolvers."""

from collections.abc import Mapping
from typing import Any, Literal

from job.classifier import JOB_REQUIREMENT_PARSER_VERSION
from job.cohort import JOB_QUALITY_VERSION
from job.demand import JOB_DEMAND_AGGREGATION_VERSION
from worker.store import digest


def source_trend_stream(
    *,
    tech_id: str,
    source: Literal["JOB", "GITHUB"],
    periods: tuple[str, ...],
    versions: Mapping[str, str],
    filters: Mapping[str, Any],
) -> str:
    """Identity used by ``/trends/completed`` before the payload is stored."""
    return digest(
        {
            "tech_id": tech_id,
            "source": source,
            "periods": periods,
            "versions": dict(versions),
            "filters": dict(filters),
        }
    )


def job_trend_filters(
    *,
    target_role: str,
    sources: tuple[str, ...],
    regions: tuple[str, ...],
    career_levels: tuple[str, ...],
    min_jobs: int,
    registry_version: str,
) -> dict[str, Any]:
    """Comparable monthly-demand scope, serialized exactly as a stored result."""
    return {
        "target_role": target_role,
        "sources": list(sources),
        "regions": list(regions),
        "career_levels": list(career_levels),
        "min_jobs": min_jobs,
        "timezone": "Asia/Seoul",
        "month_end": "exclusive",
        "purpose": "MONTHLY_DEMAND",
        "date_basis": "SOURCE_POSTED_OR_MODIFIED",
        "posting_status_policy": "INCLUDE_CLOSED",
        "versions": {
            "registry_version": registry_version,
            "parser_version": JOB_REQUIREMENT_PARSER_VERSION,
            "quality_version": JOB_QUALITY_VERSION,
            "aggregation_version": JOB_DEMAND_AGGREGATION_VERSION,
        },
    }


def job_trend_stream(
    *,
    tech_id: str,
    periods: tuple[str, ...],
    target_role: str,
    sources: tuple[str, ...],
    regions: tuple[str, ...],
    career_levels: tuple[str, ...],
    min_jobs: int,
    registry_version: str,
    versions: Mapping[str, str],
) -> str:
    return source_trend_stream(
        tech_id=tech_id,
        source="JOB",
        periods=periods,
        versions=versions,
        filters=job_trend_filters(
            target_role=target_role,
            sources=sources,
            regions=regions,
            career_levels=career_levels,
            min_jobs=min_jobs,
            registry_version=registry_version,
        ),
    )


def weekly_activity_trend_stream(
    *, tech_id: str, registry_version: str, include_partial: bool
) -> str:
    return digest(
        {
            "source": "WEEKLY_REPO_ACTIVITY",
            "tech_id": tech_id,
            "registry_version": registry_version,
            "include_partial": include_partial,
        }
    )


def archive_trend_stream(
    *,
    archive_version: Literal["v1", "v2"],
    tech_id: str,
    periods: tuple[str, ...],
    granularity: str,
    include_partial: bool,
    registry_version: str,
    algorithm: str,
) -> str:
    identity = {
        "source": "GH_ARCHIVE_HISTORICAL" if archive_version == "v2" else "GH_ARCHIVE",
        "tech_id": tech_id,
        "periods": periods,
        "granularity": granularity,
        "include_partial": include_partial,
        "registry": registry_version,
        "algorithm": algorithm,
    }
    if archive_version == "v2":
        identity["archive_version"] = "v2"
    return digest(identity)
