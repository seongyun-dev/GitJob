"""Publish weekly Repo Activity snapshots to C (S15P21E102-225).

`jobs/repo_activity_weekly.py` (-166, -224) writes one immutable directory per
week and refuses to overwrite one that exists. That stops the data from
changing; it does not tell C that a week is *finished*, and it gives C nothing
to verify the bytes against. Until now the only signal was the presence of
files, which a half-written run also has.

This module adds the two things C asked for, in the order that makes them
meaningful:

    DATA WRITE → read-back VERIFY → MANIFEST → COMPLETION EVENT

The Spark job owns the first two. This module owns the last two, and the split
is not a preference — it is what the images allow. `Infra/docker/spark`
copies only `Infra/spark`, so `common.webhdfs` and `common.kafka` do not exist
inside a Spark executor; `Infra/docker/worker` copies all of `AI/` but has no
Spark, no Hadoop CLI and no JRE. So the digest is computed where the rows are
already being read back, and the publishing happens where the clients live.
`repo_snapshot_bootstrap.py` is split the same way for the same reason.

### One manifest and one event per week, not per snapshot

A snapshot can span several weeks. `export_c_archive_activity` binds one read
to exactly one `week_start`, so a week is the unit C actually consumes, and a
single event covering five weeks would tell C nothing about which of them it
may now read. Each week therefore gets its own `_SUCCESS.json` and its own
event.

### The manifest is written last, and the event only after it

`store_immutable` writes to a temporary name and renames, so a manifest either
exists whole or not at all. Publishing it last makes its presence mean "every
byte this manifest names is already there". The event is sent only after the
manifest has been written *and* read back, because an event naming a manifest
that is not readable would send C to a URI that 404s.

If the event fails after the manifest landed, the week is complete but
unannounced — which is the safe direction. Re-running publishes the same
manifest bytes (idempotent) and re-sends the event, and C dedups on
`(dataset_snapshot_id, week_start)`.

### Same id, different data is a failure

`store_immutable` compares bytes when the destination exists: identical content
returns the existing URI, different content raises `FileExistsError`. The
manifest carries the row digest, so a week whose rows changed under the same
`dataset_snapshot_id` cannot be published quietly — the manifest bytes differ
and the write is refused.

A late event that genuinely belongs in an already-published week is therefore
not an update. It is a new `dataset_snapshot_id`, a new manifest and a new
event; the old snapshot stays exactly as C first read it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from common.events import EventEnvelope
from common.kafka import KafkaError, KafkaTransport

__all__ = [
    "COMPLETION_EVENT_TYPE",
    "MANIFEST_NAME",
    "WEEKLY_COMPLETED_TOPIC",
    "WEEKLY_MANIFEST_SCHEMA_VERSION",
    "WEEKLY_SOURCE",
    "WeeklyPublishResult",
    "WeeklySnapshotWeek",
    "build_manifest",
    "completion_envelope",
    "manifest_uri_for",
    "publish_weekly_snapshot",
    "weeks_from_summary",
]

# Follows the `gitjob.` + `.v1` shape `-121` established for
# `gitjob.repository-analysis.*.v1`. `-102` §7-③ records that the project runs
# three naming conventions at once and has not picked one; a completion event
# is the kind of contract that changes, so it carries its version in the name.
WEEKLY_COMPLETED_TOPIC = "gitjob.repo-activity-weekly.completed.v1"

# `collector/gharchive/historical.SOURCE`. The rows being announced are GH
# Archive events however they arrived, so the envelope keeps that source rather
# than inventing one for the aggregation.
WEEKLY_SOURCE = "gharchive"

COMPLETION_EVENT_TYPE = "RepoActivityWeeklySnapshotCompleted"

# The name `AI/github/snapshot_input.load_published_snapshot` already looks for,
# and the one `repo_snapshot_bootstrap` publishes.
MANIFEST_NAME = "_SUCCESS.json"

WEEKLY_MANIFEST_SCHEMA_VERSION = "repo-activity-weekly-publish-manifest/v1"

# `Infra/spark/dataset_digest.DIGEST_FORMAT`. Named, not guessed: Parquet is not
# byte-reproducible across runs (random part-file UUIDs, a `created_by` build
# string), so `hdfs dfs -checksum` reports a difference for identical data. The
# digest hashes the ordered schema and the rows instead.
ROW_DIGEST_FORMAT = "typed-json-v2"

_SHA256_LENGTH = 64


class WeeklyPublishError(RuntimeError):
    """A week could not be published, or was published with different bytes."""


@dataclass(frozen=True)
class WeeklySnapshotWeek:
    """One week directory the Spark job wrote and read back."""

    week_start: str
    data_uri: str
    row_count: int
    row_digest: str

    def __post_init__(self) -> None:
        validate_week_start(self.week_start)
        if not self.data_uri or not self.data_uri.strip():
            raise ValueError("data_uri must not be blank")
        if not isinstance(self.row_count, int) or isinstance(self.row_count, bool):
            raise TypeError("row_count must be an int")
        if self.row_count < 0:
            raise ValueError("row_count must not be negative")
        if (
            not isinstance(self.row_digest, str)
            or len(self.row_digest) != _SHA256_LENGTH
            or not all(character in "0123456789abcdef" for character in self.row_digest)
        ):
            raise ValueError("row_digest must be a lowercase sha256 hex digest")


@dataclass(frozen=True)
class WeeklyPublishResult:
    """What one run published, per week, in the order it happened."""

    manifest_uris: dict[str, str]
    events_published: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "manifest_uris": dict(self.manifest_uris),
            "events_published": list(self.events_published),
            "topic": WEEKLY_COMPLETED_TOPIC,
        }


def validate_week_start(value: object) -> str:
    """`week_start` must be an ISO Monday, the same rule the consumer applies.

    Repeated from `jobs/repo_activity_weekly.validate_week_start` rather than
    imported: that module lives in the Spark image and this one does not. The
    test suite asserts the two agree.
    """

    if not isinstance(value, str):
        raise TypeError(f"week_start must be a string: {value!r}")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError(f"week_start must be an ISO date: {value}") from error
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(f"week_start must be a canonical ISO date: {value}")
    if parsed.weekday() != 0:
        raise ValueError(f"week_start must be a Monday: {value}")
    return value


def manifest_uri_for(data_uri: str) -> str:
    """The manifest sits inside the week directory it describes."""

    return f"{data_uri.rstrip('/')}/{MANIFEST_NAME}"


def build_manifest(
    dataset_snapshot_id: str,
    week: WeeklySnapshotWeek,
) -> dict[str, object]:
    """The bytes C reads to decide whether a week is finished and intact."""

    if not dataset_snapshot_id or not dataset_snapshot_id.strip():
        raise ValueError("dataset_snapshot_id must not be blank")
    return {
        "schema_version": WEEKLY_MANIFEST_SCHEMA_VERSION,
        "dataset_snapshot_id": dataset_snapshot_id,
        "week_start": week.week_start,
        "data_uri": week.data_uri,
        "row_count": week.row_count,
        "row_digest": {"format": ROW_DIGEST_FORMAT, "value": week.row_digest},
    }


def _manifest_bytes(manifest: Mapping[str, object]) -> bytes:
    # Sorted keys so the same snapshot produces the same bytes on a re-run;
    # `store_immutable` compares bytes, and key order must not make an
    # identical publication look like a conflicting one.
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")


def completion_envelope(
    dataset_snapshot_id: str,
    week: WeeklySnapshotWeek,
    manifest_uri: str,
    *,
    ingested_at: datetime,
) -> EventEnvelope:
    """The completion event. Three payload fields, and no statistics.

    `selected_repo_count`, coverage, the Registry walk and the technology trend
    are C's to compute. A reports that the data is final and where it is; a
    number in this payload would be a second place for the same figure to be
    wrong.

    `source_id` is `(dataset_snapshot_id, week_start)` so a re-send is the same
    message: `-102` §4.1 makes `(source, source_id, schema_version)` the
    consumer-side dedup key, and this is the pair C dedups on anyway.
    """

    validate_week_start(week.week_start)
    if not manifest_uri or not manifest_uri.strip():
        raise ValueError("manifest_uri must not be blank")
    occurred_at = datetime.strptime(week.week_start, "%Y-%m-%d").replace(tzinfo=UTC)
    return EventEnvelope(
        source=WEEKLY_SOURCE,
        source_id=f"{dataset_snapshot_id}/{week.week_start}",
        event_type=COMPLETION_EVENT_TYPE,
        occurred_at=occurred_at,
        ingested_at=ingested_at,
        payload={
            "dataset_snapshot_id": dataset_snapshot_id,
            "week_start": week.week_start,
            "manifest_uri": manifest_uri,
        },
    )


def weeks_from_summary(summary: Mapping[str, object]) -> tuple[WeeklySnapshotWeek, ...]:
    """Read the weeks out of `repo_activity_weekly`'s run summary.

    The Spark job already reads every week back to check it; the digest is taken
    during that read rather than by a second pass over the same Parquet.
    """

    # A malformed summary is bad content, not a Python type error, so these stay
    # ValueError; the checks are inverted so that reads as the happy path.
    output = summary.get("output")
    if not isinstance(output, Mapping):
        output = {}
    written = output.get("weeks_written")
    if not isinstance(written, Mapping) or not written:
        raise ValueError("run summary lists no written weeks")

    weeks: list[WeeklySnapshotWeek] = []
    for week_start in sorted(written):
        entry = written[week_start]
        if not isinstance(entry, Mapping):
            entry = {}
        missing = sorted({"uri", "row_count", "row_digest"} - set(entry))
        if missing:
            raise ValueError(f"week {week_start} is missing {missing}")
        weeks.append(
            WeeklySnapshotWeek(
                week_start=str(week_start),
                data_uri=str(entry["uri"]),
                row_count=int(entry["row_count"]),
                row_digest=str(entry["row_digest"]),
            )
        )
    return tuple(weeks)


def publish_weekly_snapshot(
    dataset_snapshot_id: str,
    weeks: Sequence[WeeklySnapshotWeek] | Iterable[WeeklySnapshotWeek],
    *,
    publisher: Any,
    transport: KafkaTransport | None,
    now: datetime | None = None,
) -> WeeklyPublishResult:
    """Publish each week's manifest, then announce it.

    `publisher` is a `common.webhdfs.WebHdfsClient`-shaped object: it needs
    `store_immutable(path, content)` and `read(path)`.

    `transport` may be `None` — the same switch `transport_from_env` returns
    when no broker is configured. The manifests are still published, because a
    missing broker is a reason not to announce, not a reason to leave the data
    unmarked. The result says which weeks were announced.
    """

    ordered = list(weeks)
    if not ordered:
        raise ValueError("no weeks to publish")
    seen = {week.week_start for week in ordered}
    if len(seen) != len(ordered):
        raise ValueError("weeks must not repeat a week_start")

    moment = now or datetime.now(UTC)
    manifest_uris: dict[str, str] = {}
    published_events: list[str] = []

    for week in ordered:
        manifest = build_manifest(dataset_snapshot_id, week)
        content = _manifest_bytes(manifest)
        destination = manifest_uri_for(week.data_uri)
        try:
            uri = publisher.store_immutable(destination, content)
        except FileExistsError as error:
            # Same id, different rows. Republishing would rewrite a week C may
            # already have read; a new `dataset_snapshot_id` is the way forward.
            raise WeeklyPublishError(
                f"week {week.week_start} already published with different content "
                f"under dataset_snapshot_id {dataset_snapshot_id}; publish a new "
                "dataset_snapshot_id instead of overwriting"
            ) from error
        # The event names this URI, so it has to be readable before the event
        # exists. A read-back here is what makes that true rather than assumed.
        if publisher.read(destination) != content:
            raise WeeklyPublishError(
                f"manifest read-back mismatch for week {week.week_start}"
            )
        manifest_uris[week.week_start] = uri

        if transport is None:
            continue
        envelope = completion_envelope(
            dataset_snapshot_id, week, uri, ingested_at=moment
        )
        try:
            transport.send(
                WEEKLY_COMPLETED_TOPIC,
                key=envelope.source_id.encode("utf-8"),
                value=envelope.to_bytes(),
            )
        except KafkaError as error:
            # The manifest is already durable, so the week is complete and only
            # the announcement is missing. Failing loudly keeps that visible;
            # a re-run republishes identical bytes and re-sends the event.
            raise WeeklyPublishError(
                f"week {week.week_start} manifest published at {uri} but its "
                f"completion event could not be sent: {error}"
            ) from error
        published_events.append(week.week_start)

    return WeeklyPublishResult(
        manifest_uris=manifest_uris,
        events_published=tuple(published_events),
    )
