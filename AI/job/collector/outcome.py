"""Shared exit-code policy for scheduled job collectors.

The collector output is still written for every run, including a valid run
with no new postings. This module keeps the small amount of policy shared by
the four source CLIs in one place without changing any source parser.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = [
    "collector_exit_code",
    "empty_run_blockers",
    "is_valid_empty_run",
]


def empty_run_blockers(
    manifest: Mapping[str, object],
    *,
    source_site: str | None = None,
) -> tuple[str, ...]:
    """Return reasons a zero-record manifest is not a valid empty run.

    The check is deliberately fail-closed. A missing quality count or run
    identity is not evidence that the request and parser completed normally.
    """

    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        return ("COUNTS_MISSING",)

    blockers: list[str] = []
    records = counts.get("records")
    if type(records) is not int:
        blockers.append("RECORDS_MISSING")
    elif records != 0:
        blockers.append("RECORDS_NONZERO")

    for field, blocker in (
        ("detail_errors", "DETAIL_COLLECTION_FAILED"),
        ("invalid_records", "INVALID_SOURCE_RECORDS"),
    ):
        value = counts.get(field)
        if type(value) is not int:
            blockers.append(f"{blocker}_COUNT_MISSING")
        elif value != 0:
            blockers.append(blocker)

    if not manifest.get("pipeline_run_id"):
        blockers.append("PIPELINE_RUN_ID_MISSING")

    if source_site is not None:
        declared_source = manifest.get("source_site")
        if (
            not isinstance(declared_source, str)
            or declared_source.strip().upper() != source_site.strip().upper()
        ):
            blockers.append("SOURCE_SITE_MISMATCH")

    if manifest.get("stopped_reason"):
        blockers.append("COLLECTOR_STOPPED_EARLY")

    # These keys are optional today, but if a source adds one it must not turn
    # an explicitly fatal manifest into SUCCESS_EMPTY by accident.
    for field in ("fatal_error", "fatal_blocker", "fatal_reason"):
        if manifest.get(field):
            blockers.append(field.upper())

    return tuple(sorted(set(blockers)))


def is_valid_empty_run(
    manifest: Mapping[str, object], *, source_site: str | None = None
) -> bool:
    """Whether manifest proves a normal zero-record collection."""

    return not empty_run_blockers(manifest, source_site=source_site)


def collector_exit_code(
    manifest: Mapping[str, object], *, source_site: str | None = None
) -> int:
    """Return the collector process exit code for a completed manifest.

    Non-empty output keeps the existing contract, including a partial run that
    recorded postings before a later block. A zero-record run is successful
    only when the manifest proves that it was a clean, complete empty run.
    """

    counts = manifest.get("counts")
    records = counts.get("records") if isinstance(counts, Mapping) else None
    if type(records) is int and records > 0:
        return 0
    return 0 if is_valid_empty_run(manifest, source_site=source_site) else 1
