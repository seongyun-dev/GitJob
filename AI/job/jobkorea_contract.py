"""Shared contract for JobKorea v3 full-active service-role snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

JOBKOREA_V3_DUTY_ROLE_PAIRS = frozenset(
    {
        ("1000229", "BACKEND"),
        ("1000230", "FRONTEND"),
        ("1000236", "AI_DATA"),
        ("1000237", "AI_DATA"),
        ("1000242", "AI_DATA"),
        ("1000417", "AI_DATA"),
        ("1000418", "AI_DATA"),
        ("1000420", "AI_DATA"),
        ("1000422", "AI_DATA"),
        ("1000423", "AI_DATA"),
        ("1000233", "INFRASTRUCTURE"),
        ("1000234", "INFRASTRUCTURE"),
        ("1000235", "INFRASTRUCTURE"),
        ("1000238", "INFRASTRUCTURE"),
        ("1000244", "INFRASTRUCTURE"),
        ("1000232", "MOBILE"),
    }
)
_TERMINAL_SCOPE_REASONS = frozenset({"short_page", "empty_page"})


@dataclass(frozen=True)
class ActiveSnapshotMetadata:
    scope_key: str | None
    complete: bool


def active_snapshot_metadata(
    manifest: Mapping[str, object],
) -> ActiveSnapshotMetadata | None:
    """Validate and identify the fixed 16-duty JobKorea v3 snapshot."""

    source = manifest.get("source")
    if (
        manifest.get("source_site") != "JOBKOREA"
        or manifest.get("collector_version") != "jobkorea-crawler/v3"
        or not isinstance(source, Mapping)
        or source.get("mode") != "active_listing"
    ):
        return None
    scopes = source.get("duty_scopes")
    stats = manifest.get("stats")
    if not isinstance(scopes, list) or not scopes or not isinstance(stats, Mapping):
        return ActiveSnapshotMetadata(None, False)
    normalized: list[tuple[str, str]] = []
    complete = stats.get("scan_stop_reason") == "all_scopes_complete"
    for scope in scopes:
        if not isinstance(scope, Mapping):
            return ActiveSnapshotMetadata(None, False)
        code = scope.get("code")
        role = scope.get("target_role")
        if not isinstance(code, str) or not isinstance(role, str):
            return ActiveSnapshotMetadata(None, False)
        normalized.append((code, role))
        complete = complete and scope.get("scan_stop_reason") in _TERMINAL_SCOPE_REASONS
    pairs = frozenset(normalized)
    complete = (
        complete
        and len(normalized) == len(pairs)
        and pairs == JOBKOREA_V3_DUTY_ROLE_PAIRS
    )
    scope_key = hashlib.sha256(
        json.dumps(sorted(pairs), separators=(",", ":")).encode()
    ).hexdigest()
    return ActiveSnapshotMetadata(scope_key, bool(complete))
