"""Republish durable repository evidence as one week-scoped PUBLIC snapshot bundle.

`analysis_input/github/repo_snapshot` already holds everything a weekly PUBLIC
publication needs: the repositories a monthly Top-N fetch collected, and their
artifacts. What it does not hold is a *week*. Every record in a monthly
publication carries that month's `target_period` and activity window, and C's
head selection (`worker.store._public_payload_covers_week`) treats those as an
**overlap** test. A month-scoped record therefore satisfies every week of its
month, so several weekly heads match the same week and
`select_public_snapshot` -- which returns the newest match -- can hand a week an
unrelated denominator. The consumer then rejects the export with
"weekly export rows are outside selected PUBLIC_GITHUB", and a rejection
commits the offset: the week is lost, not retried.

This module builds the missing piece and nothing else. It takes a fixed cohort
of already-collected records, keeps the ones that were active in one ISO week,
narrows their period fields to that week, and writes the four objects
`github.snapshot_input.load_published_snapshot` reads. No GitHub call, no new
schema, no artifact copy: the records keep the artifact URIs of the snapshot
that fetched them, which C reads through its own configured namespace.

### Why the rank is recalculated

`snapshot_input._reconcile` requires `disposition.rank == record.activity_rank`
and `_index` refuses a rank above `top_n_limit`. A subset of a monthly
publication keeps that month's ranks, which are neither contiguous nor
meaningful for a week. Ranks are therefore recomputed from the week's own
`event_count`, which is also the only ordering that makes
`activity_count`/`activity_rank` describe the same week as `target_period`.

### Why FAILED collections are not republished

A repository whose fetch failed has no durable evidence to reuse, so it is not
a candidate for this week. Its failure is already recorded in the failures
object of the publication that tried to fetch it; restating it here would
double-count it against a week it was never fetched for.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

WEEKLY_COHORT_SUMMARY_SCHEMA = "github-repo-fetch-run-summary/v1"
WEEKLY_COHORT_FAILURES_SCHEMA = "github-repo-fetch-failures/v1"
WEEKLY_COHORT_MANIFEST_SCHEMA = "github-repo-snapshot-publish-manifest/v1"
SNAPSHOT_SCHEMA = "github-repo-snapshot/v1"

SNAPSHOT_FILE = "snapshot.json"
SUMMARY_FILE = "run-summary.json"
FAILURES_FILE = "failures.json"
MARKER_FILE = "_SUCCESS.json"
PUBLISHED_OBJECTS = (
    ("snapshot", SNAPSHOT_FILE),
    ("summary", SUMMARY_FILE),
    ("failures", FAILURES_FILE),
)

# A fetch that failed produced no artifact to reuse; see the module docstring.
NON_REUSABLE_STATUS = "FAILED"


@dataclass(frozen=True)
class WeeklyCohortPublication:
    """The four objects one published weekly snapshot root must contain."""

    week_start: str
    dataset_snapshot_id: str
    publication_root: str
    files: dict[str, bytes]
    record_count: int


def _canonical(value: object) -> bytes:
    """Serialize deterministically so a republished week is byte-identical.

    `common.webhdfs.store_immutable` compares bytes when the destination
    exists, so a rerun that produces different bytes for the same week fails
    the write instead of being a no-op.
    """

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _monday(week_start: str) -> date:
    try:
        day = date.fromisoformat(week_start)
    except (TypeError, ValueError) as error:
        raise ValueError("week_start must be an ISO date") from error
    if day.isoformat() != week_start or day.weekday() != 0:
        raise ValueError("week_start must be a canonical ISO Monday")
    return day


def _publication_root(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    if (
        parsed.scheme != "hdfs"
        or parsed.query
        or parsed.fragment
        or not path.startswith("/")
        or any(part in {"", ".", ".."} for part in path[1:].split("/"))
    ):
        raise ValueError("publication_root must be a fixed absolute HDFS root")
    return "hdfs://" + parsed.netloc + path


def _within(uri: str, prefixes: Sequence[str]) -> bool:
    return any(uri == prefix or uri.startswith(prefix + "/") for prefix in prefixes)


def _reusable(record: Mapping[str, object]) -> bool:
    """Can this record still contribute evidence to a PUBLIC denominator?

    `github.public_analysis` puts a repository in the denominator when it has a
    readable artifact or a mapped language. A record with neither can only
    enlarge the bundle, so it is not a weekly candidate.
    """

    if record.get("collection_status") == NON_REUSABLE_STATUS:
        return False
    return bool(record.get("artifacts")) or bool(record.get("language_metadata"))


def select_cohort_records(
    sources: Iterable[Sequence[Mapping[str, object]]],
) -> tuple[Mapping[str, object], ...]:
    """Union several publications into one cohort, one record per repository.

    Repository identity is the GitHub repository ID, never the name, because a
    rename changes the name and not the ID. Sources are consumed in the order
    given and the first record for a repository wins, so the caller decides the
    freshness policy instead of this module guessing one.
    """

    selected: dict[int, Mapping[str, object]] = {}
    for source in sources:
        for record in source:
            repo_id = record.get("github_repo_id")
            if (
                not isinstance(repo_id, int)
                or isinstance(repo_id, bool)
                or repo_id <= 0
            ):
                raise ValueError("cohort record needs a positive github_repo_id")
            selected.setdefault(repo_id, record)
    return tuple(selected[key] for key in sorted(selected))


def build_weekly_cohort_publication(
    *,
    week_start: str,
    cohort_records: Sequence[Mapping[str, object]],
    week_activity: Mapping[int, int],
    collection_policy: Mapping[str, object],
    collector_version: str,
    dataset_snapshot_id: str,
    pipeline_run_id: str,
    generated_at: datetime,
    publication_root: str,
    artifact_uri_prefixes: Sequence[str] = (),
) -> WeeklyCohortPublication:
    """Return one week's publication bundle, ready to be stored under its root."""

    monday = _monday(week_start)
    sunday = monday + timedelta(days=6)
    root = _publication_root(publication_root)
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone aware")
    prefixes = tuple(artifact_uri_prefixes)

    candidates = [
        record
        for record in cohort_records
        if record.get("github_repo_id") in week_activity and _reusable(record)
    ]
    candidates.sort(
        key=lambda record: (
            -int(week_activity[record["github_repo_id"]]),
            int(record["github_repo_id"]),
        )
    )
    limit = collection_policy.get("top_n_limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or len(candidates) > limit:
        raise ValueError("weekly candidates exceed collection_policy.top_n_limit")

    records: list[dict[str, object]] = []
    dispositions: list[dict[str, object]] = []
    status_counts: dict[str, int] = {}
    for rank, source in enumerate(candidates, start=1):
        repo_id = int(source["github_repo_id"])
        for artifact in source.get("artifacts") or ():
            uri = artifact.get("uri")
            if prefixes and not (isinstance(uri, str) and _within(uri, prefixes)):
                raise ValueError(
                    "artifact URI is outside the configured namespace: " + str(uri)
                )
        record = dict(source)
        record.update(
            activity_rank=rank,
            activity_count=int(week_activity[repo_id]),
            activity_period_start=monday.isoformat(),
            activity_period_end=sunday.isoformat(),
            target_period=monday.isoformat() + "/" + sunday.isoformat(),
            repo_snapshot_id=str(source["repo_snapshot_id"]) + "-w" + week_start,
        )
        records.append(record)
        status = str(record["collection_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        dispositions.append({"repo_id": repo_id, "rank": rank, "status": status})

    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA,
        "dataset_snapshot_id": dataset_snapshot_id,
        "pipeline_run_id": pipeline_run_id,
        "collector_version": collector_version,
        "generated_at": generated_at.isoformat(),
        "collection_policy": dict(collection_policy),
        "records": records,
    }
    summary = {
        "schema_version": WEEKLY_COHORT_SUMMARY_SCHEMA,
        "dataset_snapshot_id": dataset_snapshot_id,
        "pipeline_run_id": pipeline_run_id,
        "record_count": len(records),
        "status_counts": status_counts,
        "repos": dispositions,
        "snapshot_published": True,
        "stopped_reason": None,
        # The cohort is the candidate pool for this week and every candidate
        # was examined, so the run stopped because it was finished, not short.
        "quota_reached": True,
        "quota_shortfall": 0,
        "candidates_examined": len(records),
    }
    failures = {
        "schema_version": WEEKLY_COHORT_FAILURES_SCHEMA,
        "dataset_snapshot_id": dataset_snapshot_id,
        "failure_count": 0,
        "repos": [],
    }

    files = {
        SNAPSHOT_FILE: _canonical(snapshot),
        SUMMARY_FILE: _canonical(summary),
        FAILURES_FILE: _canonical(failures),
    }
    marker = {
        "schema_version": WEEKLY_COHORT_MANIFEST_SCHEMA,
        "dataset_snapshot_id": dataset_snapshot_id,
        "objects": {
            key: {
                "uri": root + "/" + name,
                "sha256": hashlib.sha256(files[name]).hexdigest(),
            }
            for key, name in PUBLISHED_OBJECTS
        },
    }
    files[MARKER_FILE] = _canonical(marker)
    return WeeklyCohortPublication(
        week_start=week_start,
        dataset_snapshot_id=dataset_snapshot_id,
        publication_root=root,
        files=files,
        record_count=len(records),
    )
