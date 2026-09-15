"""Stable stream identities shared by Trend publishers and read-only resolvers."""

from typing import Literal

from worker.store import digest


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
