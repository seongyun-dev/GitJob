"""Weekly GH Archive repo activity for the C Trend JOIN (S15P21E102-166).

`repo_activity_topn.py` (-109) collapses a whole period into one row per
repository.  That is the right shape for Top-N selection and the wrong shape
for a trend: it cannot say *when* inside the period a repository was active.
This job keeps the same Raw reading — four fields, one input row is one event,
no repository contents inspected — and adds the time axis the C side joins on.

### The output shape is fixed by the consumer, not chosen here

`jobs/export_c_archive_activity.py` (-203) is the only consumer, and
`AI/trend/archive.py` is what it feeds.  Together they pin four things:

* the columns are `repo_id`, `repo_name`, `event_count` and — for `WEEK` —
  `week_start`.  `event_count` is preferred over -109's `activity_count`
  (`export_c_archive_activity._activity_quality`).
* `week_start` is an ISO date string that must be a **Monday**
  (`archive._period_index`, `WEEK period must start on Monday`).
* one source read must contain **exactly one** distinct `week_start`
  (`export_c_archive_activity._validate_activity_period`).
* within that read there is **one row per `repo_id`**, no nulls, no negative
  counts, no blank names (`_activity_quality`).

The third point is why the weekly data is written as one directory per week
rather than a single dataset: pointing the exporter at the whole output would
fail its period binding.  The fourth is why `week_start` stays a **data**
column.  `partitionBy("week_start")` would satisfy the layout and then delete
the column from the files, so reading one partition directory directly — which
is exactly what the exporter does — would lose the binding it validates.  The
directory is therefore named `week=` and the column is written alongside it.

### What this job does not infer

The ticket also asks for "안정적으로 산출 가능한 이벤트별 count, unique actor 집계".
The event type is in the Raw schema -109 already declares, so per-type counts
are a real aggregate and are written to `weekly_event_type`.  A unique-actor
count is not: no file in this repository — collector, Spark job, contract or
document — names an `actor` field, so its presence, shape and nullability in
the Raw layer are unverified here.  Adding a speculative `actor.id` to the read
schema would silently produce nulls if the guess were wrong, so it is left out
and recorded as the one open item in `docs/data/2026-09-12-repo-activity-weekly.md`.

### Two inputs, one aggregation (S15P21E102-224)

GH Archive reaches HDFS two ways, and `-102` §2.4 draws the line at
`HISTORICAL_CUTOFF`: history goes straight to Raw as untouched hourly files,
and anything at or after the cutoff comes through Kafka and lands as C1's
columnar archive.  Both are the same events, so both owe the C side the same
four columns — the responsibility here is "GH Archive event → weekly repo
activity", and the input format is not a second responsibility.  A separate
job would mean a second copy of `ACTIVITY_COLUMNS`, the quality block, the
coverage block and `assert_week_slice_is_consumable`, and the copy that drifts
is the one the exporter rejects.

So the reader and its completeness gate branch, and everything from `typed`
onward is shared:

    raw-json        spark.read.schema(...).json()     file count == expected
    stream-parquet  spark.read.parquet()              every hour present

Three things are true of the stream input and not of Raw, and each is handled
where it arises rather than by a second job:

* **It can repeat.** The publisher records an hour only after the whole file
  went out, so a failure part-way re-sends the part that already landed
  (`collector/gharchive/events.py`).  `-102` §4.1 makes
  `(source, source_id, schema_version)` the consumer-side dedup key for
  exactly that trade, so this job de-duplicates on those three before it
  counts anything.  Raw has no such path and is left untouched.
* **Its file count means nothing.**  744 hourly `.json.gz` files is a fact
  about Raw; the number of Parquet part-files C1 writes depends on batch sizes
  and partition counts.  The gate is hour coverage instead — see
  `expected_stream_hours`.
* **It sits on the other side of the cutoff.**  `validate_period` now takes the
  input format and holds Raw below the cutoff and the stream at or above it,
  which is what keeps one hour from being counted twice.  A row that disagrees
  with that boundary is counted and reported rather than silently dropped,
  following the same rule `c1_archiver_stream.py` applies to its own guard.

### Partial weeks are reported, not dropped

A calendar month never starts or ends on a Monday, so the first and last week
of any period are partial.  `week_start` means "the week in which these events
happened", so dropping those weeks would throw away real events and keeping
them silently would let a reader compare a 3-day week against a 7-day one.
Both edge weeks are written, and `weeks` carries `fully_within_period` so the
comparison is a choice the consumer makes with the flag in front of them.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

HISTORICAL_START = "2026-08-01T00:00:00Z"
HISTORICAL_CUTOFF = "2026-09-01T00:00:00Z"
# Same validated Historical Raw window as -109/-193; the August MVP stays the
# default period so a bare invocation reproduces the recorded run.
SUPPORTED_HISTORICAL_START = "2026-03-01T00:00:00Z"
SUPPORTED_HISTORICAL_CUTOFF = "2026-09-01T00:00:00Z"
DEFAULT_INPUT = "hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz"

# Mirrors `jobs/export_c_archive_activity.MAX_ID_FILE_BYTES`: the JOIN cohort
# files are the same bounded envelopes that exporter reads.
MAX_ID_FILE_BYTES = 8 * 1024 * 1024
DEFAULT_JOIN_MAX_ROWS = 200_000

ACTIVITY_COLUMNS = ("repo_id", "repo_name", "event_count", "week_start")

INPUT_FORMAT_RAW_JSON = "raw-json"
INPUT_FORMAT_STREAM_PARQUET = "stream-parquet"
INPUT_FORMATS = (INPUT_FORMAT_RAW_JSON, INPUT_FORMAT_STREAM_PARQUET)

# `c1_archiver_stream.archive_location("github.events")` with the default
# parquet root.  Named here rather than imported because `Infra/spark` and
# `Infra/spark/jobs` are separate import roots at submit time.
DEFAULT_STREAM_INPUT = "hdfs:///gitjob/parquet/stream/github.events"

# `collector/gharchive/historical.SOURCE`.  The stream path is topic-scoped, so
# this is a guard against being pointed at another topic's archive, not a
# filter that is expected to remove anything.
STREAM_SOURCE = "gharchive"

# `-102` §4.1.  Not `event_id` alone: the envelope's identity is the triple, and
# inventing a narrower key here would disagree with C2, which dedups on the
# same three.
DEDUP_KEYS = ("source", "source_id", "schema_version")

# The columns this job reads out of C1's archive.  A subset of
# `c1_archiver_stream.ARCHIVE_COLUMNS`; absence means the input is not a C1
# archive and is reported rather than read as nulls.
STREAM_REQUIRED_COLUMNS = (
    "source",
    "source_id",
    "schema_version",
    "event_type",
    "occurred_at",
    "payload",
)

# How many missing hours an error message lists before it truncates.  A whole
# month is 744, and a message that long is unreadable in a Spark log.
MAX_REPORTED_MISSING_HOURS = 20


def parse_utc_hour(value: str) -> datetime:
    """Parse an aware, hour-aligned UTC timestamp."""

    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 hour: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    parsed = parsed.astimezone(UTC)
    if any((parsed.minute, parsed.second, parsed.microsecond)):
        raise ValueError(f"timestamp must be aligned to an hour: {value}")
    return parsed


def validate_input_format(value: str) -> str:
    """Return ``value`` when it names one of the two readers."""

    if value not in INPUT_FORMATS:
        raise ValueError(
            f"input_format must be one of {', '.join(INPUT_FORMATS)}: {value}"
        )
    return value


def resolve_input_path(value: str | None, input_format: str) -> str:
    """The input path, defaulted to the root this format is written to.

    One default cannot serve both readers, and silently reading Raw while
    `--input-format stream-parquet` was asked for would produce a plausible
    result from the wrong half of the pipeline.
    """

    validate_input_format(input_format)
    if value:
        return value
    return (
        DEFAULT_INPUT if input_format == INPUT_FORMAT_RAW_JSON else DEFAULT_STREAM_INPUT
    )


def validate_period(
    period_start: str,
    period_end: str,
    *,
    input_format: str = INPUT_FORMAT_RAW_JSON,
) -> None:
    """Validate the explicit UTC period against the input's side of the cutoff.

    This is where "no hour is counted twice" is actually enforced.  Raw holds
    the history below `SUPPORTED_HISTORICAL_CUTOFF` and the stream holds
    everything from it onward, so a period that reaches across the boundary is
    refused before any reading happens rather than being caught later as a
    surprising row count.
    """

    validate_input_format(input_format)
    start = parse_utc_hour(period_start)
    end = parse_utc_hour(period_end)
    historical_start = parse_utc_hour(SUPPORTED_HISTORICAL_START)
    historical_cutoff = parse_utc_hour(SUPPORTED_HISTORICAL_CUTOFF)
    if start >= end:
        raise ValueError("period_start must be before period_end")
    if input_format == INPUT_FORMAT_RAW_JSON:
        if start < historical_start:
            raise ValueError("period_start precedes historical_start")
        if end > historical_cutoff:
            raise ValueError("period_end exceeds exclusive historical_cutoff")
        return
    # The stream has no upper bound: it is fed by hours that keep arriving.
    if start < historical_cutoff:
        raise ValueError("stream period_start precedes historical_cutoff")


def parse_event_timestamp(value: object) -> datetime:
    """Parse a GH Archive ``created_at`` into an aware UTC timestamp.

    GH Archive writes RFC-3339 `Z` timestamps.  A value that carries another
    offset is accepted and converted, because the week a UTC instant falls in
    is a property of the instant; a naive value is rejected, because guessing
    its zone would move events across a week boundary without saying so.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError("created_at must be a non-blank string")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    return parsed.astimezone(UTC)


def week_start_of(value: object) -> str:
    """Return the Monday, in UTC, of the week containing ``value``.

    ``value`` is a ``created_at`` string or an aware ``datetime``.  The result
    is the `YYYY-MM-DD` form `AI/trend/archive.py` requires.  Spark computes
    the same boundary with ``date_trunc('week', ...)`` under a UTC session
    timezone; this helper exists so the boundary is executable without Spark.
    """

    moment = value if isinstance(value, datetime) else parse_event_timestamp(value)
    if moment.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    day = moment.astimezone(UTC).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def validate_week_start(value: str) -> date:
    """Apply the consumer's `WEEK` period rules to one ``week_start``."""

    if not isinstance(value, str):
        raise TypeError("week_start must be a string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"week_start must be an ISO date: {value}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"week_start must be a canonical ISO date: {value}")
    if parsed.year < 2020:
        raise ValueError("week_start year must be >= 2020")
    if parsed.weekday() != 0:
        raise ValueError(f"week_start must be a Monday: {value}")
    return parsed


def expected_week_starts(period_start: str, period_end: str) -> tuple[str, ...]:
    """Every week a `[period_start, period_end)` event can land in."""

    start = parse_utc_hour(period_start)
    end = parse_utc_hour(period_end)
    if start >= end:
        raise ValueError("period_start must be before period_end")
    first = date.fromisoformat(week_start_of(start))
    # The exclusive end belongs to the previous instant's week.
    last = date.fromisoformat(week_start_of(end - timedelta(microseconds=1)))
    weeks: list[str] = []
    cursor = first
    while cursor <= last:
        weeks.append(cursor.isoformat())
        cursor += timedelta(days=7)
    return tuple(weeks)


def week_is_fully_within_period(
    week_start: str, period_start: str, period_end: str
) -> bool:
    """True when the whole Monday-to-Monday span lies inside the period."""

    monday = validate_week_start(week_start)
    start = parse_utc_hour(period_start)
    end = parse_utc_hour(period_end)
    week_begin = datetime.combine(monday, datetime.min.time(), tzinfo=UTC)
    return week_begin >= start and week_begin + timedelta(days=7) <= end


# --- the stream input -------------------------------------------------------


def format_stream_hour(moment: datetime) -> str:
    """The hour key shape the publisher writes into ``source_id``.

    Identical to `collector/gharchive/historical.format_utc_hour`.  Repeated
    rather than imported because the Spark jobs are submitted with only
    `Infra/spark` on the path; the test suite asserts the two agree.
    """

    if moment.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:00:00Z")


def validate_stream_hour(hour_key: object) -> str:
    """Return ``hour_key`` when it is an hour-aligned UTC hour key."""

    if not isinstance(hour_key, str):
        raise TypeError(f"hour key must be a string: {hour_key!r}")
    if format_stream_hour(parse_utc_hour(hour_key)) != hour_key:
        raise ValueError(f"hour key is not an aligned UTC hour: {hour_key!r}")
    return hour_key


def stream_hour_key(source_id: object) -> str:
    """The hourly file an envelope came from.

    `collector/gharchive/events.build_event_envelope` sets
    ``source_id = f"{hour_key}/{event_id}"``, so the hour an event was
    published under is carried by the envelope itself.  Deriving coverage from
    this rather than from ``occurred_at`` means the gate checks *what the
    publisher accounted for*, which is the same unit its checkpoint records.
    """

    if not isinstance(source_id, str) or "/" not in source_id:
        raise ValueError(f"source_id must be '<hour>/<event id>': {source_id!r}")
    hour_key, _, event_id = source_id.partition("/")
    if not event_id:
        raise ValueError(f"source_id is missing its event id: {source_id!r}")
    # Round-trips through the hour parser so a malformed hour is rejected here
    # rather than becoming a coverage hole with a plausible-looking name.
    return validate_stream_hour(hour_key)


def expected_stream_hours(period_start: str, period_end: str) -> tuple[str, ...]:
    """Every UTC hour a `[period_start, period_end)` event can belong to.

    This is the stream's completeness gate and it replaces `--expected-files`.
    A Parquet part-file count says nothing — Spark decides it from batch sizes
    — while GH Archive publishes exactly one file per UTC hour, which is the
    unit `-105` counted (744 for a 31-day month) and the unit the publisher
    checkpoints.  An hour with no row in the archive is an hour that never
    reached Kafka.
    """

    start = parse_utc_hour(period_start)
    end = parse_utc_hour(period_end)
    if start >= end:
        raise ValueError("period_start must be before period_end")
    hours: list[str] = []
    cursor = start
    while cursor < end:
        hours.append(format_stream_hour(cursor))
        cursor += timedelta(hours=1)
    return tuple(hours)


def missing_stream_hours(
    observed: Iterable[str], period_start: str, period_end: str
) -> tuple[str, ...]:
    """Expected hours with no event in the archive, in chronological order."""

    seen = {value for value in observed if isinstance(value, str)}
    return tuple(
        hour
        for hour in expected_stream_hours(period_start, period_end)
        if hour not in seen
    )


def parse_stream_payload(payload: object) -> dict[str, object]:
    """Decode a C1 ``payload`` column into the original GH Archive event.

    C1 carries the event through as the JSON text that arrived and never parses
    it (`c1_archiver_stream`: "the payload stays opaque").  This job is the
    first reader that needs the two fields inside it, so the parsing — and the
    decision about what a malformed one is — happens here.
    """

    if isinstance(payload, Mapping):
        return dict(payload)
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError("payload must be a non-blank JSON object")
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"payload is not valid JSON: {exc}") from exc
    # A GH Archive event is always a JSON object; an array or a bare scalar is
    # a content problem, not a Python type problem, so it stays a ValueError.
    if isinstance(decoded, dict):
        return decoded
    raise ValueError(
        f"payload must decode to a JSON object, got {type(decoded).__name__}"
    )


def normalize_stream_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    cutoff: str = SUPPORTED_HISTORICAL_CUTOFF,
) -> list[dict[str, object]]:
    """Mirror of the Spark stream path, up to `aggregate_weekly_rows`'s input.

    Filters to this job's source, de-duplicates on `DEDUP_KEYS`, lifts
    ``repo.id``/``repo.name`` out of the payload and renames the two promoted
    columns to the names the Raw reader produces.  Rows below the cutoff are
    dropped here because they belong to the Raw path.

    A row whose payload is unusable keeps null identifiers and is passed on:
    `aggregate_weekly_rows` already owns the rule for dropping those, and
    duplicating it would give two places to disagree about what invalid means.
    """

    cutoff_moment = parse_utc_hour(cutoff)
    seen: set[tuple[object, object, object]] = set()
    normalized: list[dict[str, object]] = []
    for row in rows:
        if row.get("source") != STREAM_SOURCE:
            continue
        key = tuple(row.get(field) for field in DEDUP_KEYS)
        if key in seen:
            continue
        seen.add(key)

        occurred_at = row.get("occurred_at")
        try:
            moment = parse_event_timestamp(occurred_at)
        except ValueError:
            moment = None
        if moment is not None and moment < cutoff_moment:
            continue

        try:
            event = parse_stream_payload(row.get("payload"))
        except ValueError:
            event = {}
        repo = event.get("repo")
        repo = repo if isinstance(repo, Mapping) else {}
        repo_id = repo.get("id")
        normalized.append(
            {
                "repo_id": repo_id if isinstance(repo_id, int) else None,
                "repo_name": repo.get("name"),
                "event_type": row.get("event_type"),
                "created_at": occurred_at,
            }
        )
    return normalized


def aggregate_weekly_rows(
    events: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Aggregate raw events into the weekly rows the Spark job writes.

    The Spark job performs the same aggregation with ``groupBy`` over
    ``(repo_id, week_start)``.  This helper exists to make the grouping key,
    the renamed-repository rule and the invalid-row rule executable in unit
    tests; production Raw never comes through the Python driver.

    Events missing ``repo_id``, ``repo_name`` or a usable ``created_at`` are
    dropped, matching the Spark filter, and counted by the caller through the
    returned row totals.  A repository renamed mid-week keeps the name from its
    latest event in that week, which is -109's rule applied per week.
    """

    buckets: dict[tuple[int, str], dict[str, object]] = {}
    for event in events:
        repo_id = event.get("repo_id")
        repo_name = event.get("repo_name")
        created_at = event.get("created_at")
        if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
            continue
        if not isinstance(repo_name, str) or not repo_name.strip():
            continue
        try:
            moment = parse_event_timestamp(created_at)
        except ValueError:
            continue
        key = (repo_id, week_start_of(moment))
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = {
                "repo_id": repo_id,
                "repo_name": repo_name,
                "event_count": 1,
                "week_start": key[1],
                "_latest": moment,
                "_names": {repo_name},
            }
            continue
        bucket["event_count"] = int(bucket["event_count"]) + 1
        names = bucket["_names"]
        if isinstance(names, set):
            names.add(repo_name)
        latest = bucket["_latest"]
        if isinstance(latest, datetime) and (
            moment > latest
            or (moment == latest and repo_name > str(bucket["repo_name"]))
        ):
            bucket["_latest"] = moment
            bucket["repo_name"] = repo_name

    rows = [
        {
            "repo_id": bucket["repo_id"],
            "repo_name": bucket["repo_name"],
            "event_count": bucket["event_count"],
            "week_start": bucket["week_start"],
            "name_count": len(bucket["_names"])
            if isinstance(bucket["_names"], set)
            else 1,
        }
        for bucket in buckets.values()
    ]
    rows.sort(key=lambda row: (str(row["week_start"]), int(row["repo_id"])))
    return rows


def activity_rows_for_week(
    rows: Sequence[Mapping[str, object]], week_start: str
) -> list[dict[str, object]]:
    """The exact column set one week directory holds, for one week."""

    validate_week_start(week_start)
    return [
        {column: row[column] for column in ACTIVITY_COLUMNS}
        for row in rows
        if row["week_start"] == week_start
    ]


def assert_week_slice_is_consumable(rows: Sequence[Mapping[str, object]]) -> None:
    """Re-apply the consumer's acceptance rules to one week's rows.

    `export_c_archive_activity._activity_quality` and
    `trend.archive._normalize_activity_row` reject the same things.  Checking
    them here means a violation stops this job instead of surfacing days later
    as an export failure with no producer to blame.
    """

    if not rows:
        raise ValueError("week slice must not be empty")
    weeks = {row["week_start"] for row in rows}
    if len(weeks) != 1:
        raise ValueError(
            f"week slice must hold exactly one week_start: {sorted(weeks)}"
        )
    validate_week_start(str(next(iter(weeks))))
    seen: set[int] = set()
    for row in rows:
        repo_id = row["repo_id"]
        repo_name = row["repo_name"]
        event_count = row["event_count"]
        if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
            raise ValueError("repo_id must be a strict positive integer")
        if repo_id in seen:
            raise ValueError(f"duplicate repo_id within one week: {repo_id}")
        seen.add(repo_id)
        if not isinstance(repo_name, str) or not repo_name.strip():
            raise ValueError("repo_name must be a non-blank string")
        if (
            isinstance(event_count, bool)
            or not isinstance(event_count, int)
            or event_count < 0
        ):
            raise ValueError("event_count must be a nonnegative integer")


def parse_join_ids_argument(value: str) -> tuple[str, Path]:
    """Parse one ``LABEL=PATH`` JOIN cohort argument.

    Cohorts are named by the caller rather than hardcoded here.  "Top20k" and
    "COMPLETE" are the two the ticket asks about, but nothing about this job
    depends on those being the cohorts that exist.
    """

    label, separator, path = value.partition("=")
    label = label.strip()
    if not separator or not label or not path.strip():
        raise ValueError("join cohort must be given as LABEL=PATH")
    if any(character.isspace() for character in label):
        raise ValueError("join cohort label must not contain whitespace")
    return label, Path(path.strip())


def load_repo_ids(path: Path, *, max_rows: int) -> tuple[int, ...]:
    """Load a bounded, approved repository ID envelope.

    The accepted envelopes are the ones `jobs/export_c_archive_activity.py`
    already accepts, so a cohort file is usable by both without conversion.
    """

    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    with path.open("rb") as stream:
        content = stream.read(MAX_ID_FILE_BYTES + 1)
    if len(content) > MAX_ID_FILE_BYTES:
        raise ValueError("repository ID input exceeds the bounded file limit")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("repository ID input must be UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise TypeError("repository ID input must be an object")

    schema = payload.get("schema_version")
    if schema == "repo-fetch-candidates/v1":
        rows = payload.get("candidates")
        field = "repo_id"
    elif schema in {"github-repo-snapshot/v1", "c-public-repo-analysis/v1"}:
        rows = payload.get("records")
        field = "github_repo_id"
    else:
        raise ValueError("unsupported repository ID source schema_version")
    if not isinstance(rows, list):
        raise TypeError("repository ID source rows must be an array")
    if len(rows) > max_rows:
        raise ValueError("repository ID source exceeds max_rows")

    repo_ids: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("repository ID row must be an object")
        repo_id = row.get(field)
        if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
            raise ValueError("repo_id must be a strict positive integer")
        repo_ids.append(repo_id)
    if not repo_ids:
        raise ValueError("repository ID source must not be empty")
    if len(repo_ids) != len(set(repo_ids)):
        raise ValueError("duplicate repo_id in repository ID source")
    return tuple(sorted(repo_ids))


def join_coverage_row(
    label: str,
    repo_ids: Sequence[int],
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Coverage of one cohort against the weekly rows.

    ``matched_repo_count`` answers the ticket's JOIN question — how many of the
    cohort's repositories appear anywhere in the weekly data — while
    ``active_week_count`` and ``matched_event_count`` say how much of the time
    axis they actually occupy.  A repository absent from every week is not an
    error: it had no GH Archive event in the period.
    """

    cohort = set(repo_ids)
    if not cohort:
        raise ValueError("join cohort must not be empty")
    matched_rows = [row for row in rows if int(row["repo_id"]) in cohort]
    matched_repos = {int(row["repo_id"]) for row in matched_rows}
    matched_events = sum(int(row["event_count"]) for row in matched_rows)
    return {
        "label": label,
        "cohort_repo_count": len(cohort),
        "matched_repo_count": len(matched_repos),
        "missing_repo_count": len(cohort) - len(matched_repos),
        "coverage_ratio": len(matched_repos) / len(cohort),
        "active_week_count": len({str(row["week_start"]) for row in matched_rows}),
        "matched_row_count": len(matched_rows),
        "matched_event_count": matched_events,
    }


def build_event_schema() -> Any:
    """The four Raw fields this aggregation reads, and nothing else.

    Identical to -109's schema.  `_corrupt_record` measures malformed JSON and
    is never part of a grouping key.
    """

    from pyspark.sql.types import LongType, StringType, StructField, StructType

    return StructType(
        [
            StructField(
                "repo",
                StructType(
                    [
                        StructField("id", LongType(), True),
                        StructField("name", StringType(), True),
                    ]
                ),
                True,
            ),
            StructField("type", StringType(), True),
            StructField("created_at", StringType(), True),
            StructField("_corrupt_record", StringType(), True),
        ]
    )


# `dataset_digest.DIGEST_FORMAT`.  Repeated rather than imported at module
# scope because `spark-submit` puts only the submitted script's own directory
# on `sys.path`; the algorithm itself is imported in `slice_row_digest`, and
# the test suite asserts this string still matches its source.
DIGEST_FORMAT = "typed-json-v2"


def slice_row_digest(spark: Any, F: Any, frame: Any) -> str:
    """The deterministic content digest of one week's rows.

    Parquet is not byte-reproducible across runs — part filenames carry a random
    UUID and the footer records a build string — so `hdfs dfs -checksum` reports
    a difference for identical data.  `dataset_digest` exists for exactly this
    and is reused rather than reimplemented: same `typed-json-v2` framing, same
    JSON options, so a digest taken here and one taken by
    `Infra/scripts/spark-dataset-digest.sh` over the same directory agree.

    Row order does not matter; `content_digest` sorts the rendered rows.
    """

    import sys
    from pathlib import Path as _Path

    # `dataset_digest` sits one directory up, in `Infra/spark`.  The Docker
    # image copies that whole tree, so the relative layout is fixed.
    parent = str(_Path(__file__).resolve().parents[1])
    if parent not in sys.path:
        sys.path.insert(0, parent)
    from dataset_digest import JSON_OPTIONS, content_digest

    columns = sorted(frame.columns)
    ordered = frame.select(*[F.col(name) for name in columns])
    rendered = ordered.select(
        F.to_json(
            F.struct(*[F.col(name).alias(name) for name in columns]),
            options=JSON_OPTIONS,
        ).alias("row")
    )
    return content_digest(
        ordered.schema.json(), [str(item["row"]) for item in rendered.collect()]
    )


def _hadoop_path_exists(spark: Any, uri: str) -> bool:
    path = spark._jvm.org.apache.hadoop.fs.Path(uri)
    filesystem = path.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    return bool(filesystem.exists(path))


def _hadoop_path_stats(spark: Any, uri: str) -> tuple[int, int]:
    """Return (file_count, byte_count) recursively for an HDFS path."""

    path = spark._jvm.org.apache.hadoop.fs.Path(uri)
    filesystem = path.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    if not filesystem.exists(path):
        return 0, 0

    files = 0
    bytes_total = 0
    iterator = filesystem.listFiles(path, True)
    while iterator.hasNext():
        status = iterator.next()
        if status.getPath().getName().endswith(".parquet"):
            files += 1
            bytes_total += int(status.getLen())
    return files, bytes_total


def _executor_count(spark: Any) -> int | None:
    try:
        statuses = spark.sparkContext._jsc.sc().getExecutorMemoryStatus()
        # The driver is included in the map; report workers only.
        return max(0, int(statuses.size()) - 1)
    except Exception:  # noqa: BLE001 - JVM API differs between Spark releases
        return None


def _as_int(value: object) -> int:
    return int(value or 0)


def run_job(arguments: argparse.Namespace) -> dict[str, object]:
    """Execute the distributed weekly aggregation and write immutable Parquet."""

    from pyspark import StorageLevel
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        BooleanType,
        DoubleType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    input_format = validate_input_format(
        getattr(arguments, "input_format", INPUT_FORMAT_RAW_JSON)
    )
    arguments.input_format = input_format
    validate_period(
        arguments.period_start, arguments.period_end, input_format=input_format
    )
    cohorts = {
        label: load_repo_ids(path, max_rows=arguments.join_max_rows)
        for label, path in arguments.join_cohorts
    }
    expected_weeks = expected_week_starts(arguments.period_start, arguments.period_end)
    period_start_ts = parse_utc_hour(arguments.period_start)
    period_end_ts = parse_utc_hour(arguments.period_end)
    historical_cutoff_ts = parse_utc_hour(SUPPORTED_HISTORICAL_CUTOFF)
    period_start_date = period_start_ts.date().isoformat()
    # The exclusive end belongs to the previous instant's date.
    period_end_date = (period_end_ts - timedelta(microseconds=1)).date().isoformat()

    started = time.perf_counter()
    spark = (
        SparkSession.builder.appName(arguments.app_name)
        # Every week boundary in this job is a UTC boundary.  Without this the
        # JVM default zone would decide which week an event belongs to.
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    weekly = None
    in_period = None
    stream_summary: dict[str, object] | None = None
    try:
        if _hadoop_path_exists(spark, arguments.output):
            raise FileExistsError(
                f"output already exists; refusing to overwrite: {arguments.output}"
            )

        if arguments.input_format == INPUT_FORMAT_RAW_JSON:
            raw = spark.read.schema(build_event_schema()).json(arguments.input)
            input_files = tuple(raw.inputFiles())
            if len(input_files) != arguments.expected_files:
                raise RuntimeError(
                    "input file count mismatch: "
                    f"expected {arguments.expected_files}, got {len(input_files)}"
                )

            typed = raw.select(
                F.col("repo.id").cast("long").alias("repo_id"),
                F.col("repo.name").alias("repo_name"),
                F.col("type").alias("event_type"),
                F.to_timestamp(F.col("created_at")).alias("created_at_ts"),
                F.col("_corrupt_record"),
            )
        else:
            archive = spark.read.parquet(arguments.input)
            missing_columns = sorted(
                set(STREAM_REQUIRED_COLUMNS) - set(archive.columns)
            )
            if missing_columns:
                raise RuntimeError(
                    "stream input is not a C1 archive; missing columns: "
                    f"{missing_columns}"
                )
            input_files = tuple(archive.inputFiles())

            scoped = archive.where(F.col("source") == F.lit(STREAM_SOURCE))
            if "dt" in archive.columns:
                # Partition pruning only.  C1 partitions by the `occurred_at`
                # date, so scanning just the dates the period can touch avoids
                # reading the whole topic archive on every run.  Membership is
                # still decided by the exact bound below, not by `dt`.
                scoped = scoped.where(
                    (F.col("dt") >= F.lit(period_start_date))
                    & (F.col("dt") <= F.lit(period_end_date))
                )
            # `-102` §4.1.  The publisher records an hour only after the whole
            # file went out, so a retry re-sends the part that already landed;
            # counting before this would inflate `event_count` on every replay.
            deduped = scoped.dropDuplicates(list(DEDUP_KEYS))

            typed_full = deduped.select(
                F.substring_index(F.col("source_id"), "/", 1).alias("hour_key"),
                F.get_json_object(F.col("payload"), "$.repo.id")
                .cast("long")
                .alias("repo_id"),
                F.get_json_object(F.col("payload"), "$.repo.name").alias("repo_name"),
                F.col("event_type"),
                F.to_timestamp(F.col("occurred_at")).alias("created_at_ts"),
                # `get_json_object(col, '$')` is null exactly when the text does
                # not parse, which is what the Raw reader's `_corrupt_record`
                # means.  Reusing the name keeps the quality block below shared.
                F.when(
                    F.get_json_object(F.col("payload"), "$").isNull(),
                    F.col("payload"),
                ).alias("_corrupt_record"),
            )

            out_of_period = F.col("created_at_ts").isNotNull() & (
                (F.col("created_at_ts") < F.lit(period_start_ts))
                | (F.col("created_at_ts") >= F.lit(period_end_ts))
            )
            # Reported rather than dropped in silence: a publisher whose
            # boundary disagrees with ours must not look like a quiet success.
            # `c1_archiver_stream` makes the same choice for its own guard.
            stream_counts = (
                typed_full.agg(
                    F.count(F.lit(1)).alias("deduplicated_event_count"),
                    F.sum(F.when(out_of_period, 1).otherwise(0)).alias(
                        "out_of_period_event_count"
                    ),
                    F.sum(
                        F.when(
                            F.col("created_at_ts").isNotNull()
                            & (F.col("created_at_ts") < F.lit(historical_cutoff_ts)),
                            1,
                        ).otherwise(0)
                    ).alias("below_cutoff_event_count"),
                )
                .first()
                .asDict()
            )
            below_cutoff_event_count = _as_int(
                stream_counts["below_cutoff_event_count"]
            )
            if below_cutoff_event_count:
                raise RuntimeError(
                    "stream input carries events below "
                    f"{SUPPORTED_HISTORICAL_CUTOFF}: {below_cutoff_event_count}. "
                    "That range belongs to the Historical Raw path and would be "
                    "counted twice."
                )

            in_period = typed_full.where(~out_of_period).persist(StorageLevel.DISK_ONLY)
            observed_hours = sorted(
                str(row["hour_key"])
                for row in in_period.select("hour_key").distinct().collect()
            )
            for hour_key in observed_hours:
                # A malformed `source_id` becomes a coverage hole with a
                # plausible-looking name if it is not rejected here.
                validate_stream_hour(hour_key)
            expected_hours = expected_stream_hours(
                arguments.period_start, arguments.period_end
            )
            absent_hours = missing_stream_hours(
                observed_hours, arguments.period_start, arguments.period_end
            )
            if absent_hours:
                shown = list(absent_hours[:MAX_REPORTED_MISSING_HOURS])
                suffix = (
                    f" (+{len(absent_hours) - len(shown)} more)"
                    if len(absent_hours) > len(shown)
                    else ""
                )
                raise RuntimeError(
                    "stream input is missing "
                    f"{len(absent_hours)} of {len(expected_hours)} "
                    f"expected UTC hours: {shown}{suffix}"
                )

            stream_summary = {
                "source": STREAM_SOURCE,
                "dedup_keys": list(DEDUP_KEYS),
                "deduplicated_event_count": _as_int(
                    stream_counts["deduplicated_event_count"]
                ),
                "out_of_period_event_count": _as_int(
                    stream_counts["out_of_period_event_count"]
                ),
                "below_cutoff_event_count": below_cutoff_event_count,
                "expected_hour_count": len(expected_hours),
                "observed_hour_count": len(observed_hours),
                "missing_hours": [],
            }
            typed = in_period.drop("hour_key")
        quality_row = (
            typed.agg(
                F.count(F.lit(1)).alias("total_input_events"),
                F.sum(F.when(F.col("repo_id").isNull(), 1).otherwise(0)).alias(
                    "repo_id_null_count"
                ),
                F.sum(F.when(F.col("repo_name").isNull(), 1).otherwise(0)).alias(
                    "repo_name_null_count"
                ),
                F.sum(F.when(F.col("created_at_ts").isNull(), 1).otherwise(0)).alias(
                    "created_at_null_count"
                ),
                F.sum(
                    F.when(
                        F.col("repo_id").isNull()
                        | F.col("repo_name").isNull()
                        | F.col("created_at_ts").isNull(),
                        1,
                    ).otherwise(0)
                ).alias("invalid_event_count"),
                F.sum(
                    F.when(F.col("_corrupt_record").isNotNull(), 1).otherwise(0)
                ).alias("malformed_json_count"),
            )
            .first()
            .asDict()
        )
        total_input_events = _as_int(quality_row["total_input_events"])
        invalid_event_count = _as_int(quality_row["invalid_event_count"])

        valid = typed.where(
            F.col("repo_id").isNotNull()
            & F.col("repo_name").isNotNull()
            & F.col("created_at_ts").isNotNull()
        ).withColumn(
            # date_trunc('week') is Monday-based, and the session timezone
            # above makes that Monday a UTC Monday.
            "week_start",
            F.date_format(F.date_trunc("week", F.col("created_at_ts")), "yyyy-MM-dd"),
        )

        grouped = valid.groupBy("repo_id", "week_start").agg(
            F.count(F.lit(1)).cast("long").alias("event_count"),
            F.countDistinct("repo_name").cast("long").alias("name_count"),
            F.max(F.struct(F.col("created_at_ts"), F.col("repo_name"))).alias("latest"),
        )
        weekly = grouped.select(
            F.col("repo_id"),
            F.col("latest.repo_name").alias("repo_name"),
            F.col("event_count"),
            F.col("week_start"),
            F.col("name_count"),
        ).persist(StorageLevel.DISK_ONLY)

        weekly_stats = (
            weekly.agg(
                F.count(F.lit(1)).alias("row_count"),
                F.countDistinct("repo_id").alias("unique_repo_id_count"),
                F.sum(F.col("event_count")).alias("valid_repo_event_count"),
                F.sum(F.when(F.col("name_count") > 1, 1).otherwise(0)).alias(
                    "repo_name_collision_count"
                ),
            )
            .first()
            .asDict()
        )
        row_count = _as_int(weekly_stats["row_count"])
        unique_repo_id_count = _as_int(weekly_stats["unique_repo_id_count"])
        valid_repo_event_count = _as_int(weekly_stats["valid_repo_event_count"])
        repo_name_collision_count = _as_int(weekly_stats["repo_name_collision_count"])

        observed_weeks = sorted(
            str(row["week_start"])
            for row in weekly.select("week_start").distinct().collect()
        )
        for week in observed_weeks:
            validate_week_start(week)
        unexpected = sorted(set(observed_weeks) - set(expected_weeks))
        if unexpected:
            raise RuntimeError(
                f"events fall outside the declared period's weeks: {unexpected}"
            )

        week_row_map = {
            str(row["week_start"]): row.asDict()
            for row in weekly.groupBy("week_start")
            .agg(
                F.count(F.lit(1)).cast("long").alias("row_count"),
                F.countDistinct("repo_id").cast("long").alias("repo_count"),
                F.sum(F.col("event_count")).cast("long").alias("event_count"),
            )
            .collect()
        }
        for week, summary_row in week_row_map.items():
            if int(summary_row["row_count"]) != int(summary_row["repo_count"]):
                raise RuntimeError(
                    f"week {week} holds more than one row per repo_id: "
                    f"{summary_row['row_count']} rows / {summary_row['repo_count']} repos"
                )

        output_root = arguments.output.rstrip("/")
        activity_root = f"{output_root}/repo_activity_weekly"
        week_type_output = f"{output_root}/weekly_event_type"
        weeks_output = f"{output_root}/weeks"
        coverage_output = f"{output_root}/join_coverage"
        quality_output = f"{output_root}/data_quality"

        # One directory per week, `week_start` retained as a data column: the
        # exporter validates that column after reading a single week.
        activity = weekly.select(*ACTIVITY_COLUMNS)
        week_outputs: dict[str, str] = {}
        for week in observed_weeks:
            week_output = f"{activity_root}/week={week}"
            activity.where(F.col("week_start") == F.lit(week)).write.mode(
                "errorifexists"
            ).parquet(week_output)
            week_outputs[week] = week_output

        week_type_schema_rows = (
            valid.groupBy("week_start", "event_type")
            .agg(
                F.count(F.lit(1)).cast("long").alias("event_count"),
                F.countDistinct("repo_id").cast("long").alias("repo_count"),
            )
            .select("week_start", "event_type", "event_count", "repo_count")
        )
        week_type_schema_rows.write.mode("errorifexists").parquet(week_type_output)

        weeks_schema = StructType(
            [
                StructField("week_start", StringType(), False),
                StructField("week_end", StringType(), False),
                StructField("row_count", LongType(), False),
                StructField("repo_count", LongType(), False),
                StructField("event_count", LongType(), False),
                StructField("fully_within_period", BooleanType(), False),
                StructField("period_start", StringType(), False),
                StructField("period_end", StringType(), False),
            ]
        )
        weeks_rows = [
            (
                week,
                (date.fromisoformat(week) + timedelta(days=7)).isoformat(),
                _as_int(week_row_map[week]["row_count"]),
                _as_int(week_row_map[week]["repo_count"]),
                _as_int(week_row_map[week]["event_count"]),
                week_is_fully_within_period(
                    week, arguments.period_start, arguments.period_end
                ),
                arguments.period_start,
                arguments.period_end,
            )
            for week in observed_weeks
        ]
        spark.createDataFrame(weeks_rows, schema=weeks_schema).write.mode(
            "errorifexists"
        ).parquet(weeks_output)

        coverage_summary: list[dict[str, object]] = []
        if cohorts:
            coverage_schema = StructType(
                [
                    StructField("label", StringType(), False),
                    StructField("cohort_repo_count", LongType(), False),
                    StructField("matched_repo_count", LongType(), False),
                    StructField("missing_repo_count", LongType(), False),
                    StructField("coverage_ratio", DoubleType(), False),
                    StructField("active_week_count", LongType(), False),
                    StructField("matched_row_count", LongType(), False),
                    StructField("matched_event_count", LongType(), False),
                    StructField("period_start", StringType(), False),
                    StructField("period_end", StringType(), False),
                ]
            )
            for label, repo_ids in cohorts.items():
                cohort_df = F.broadcast(
                    spark.createDataFrame(
                        [(repo_id,) for repo_id in repo_ids],
                        schema=StructType([StructField("repo_id", LongType(), False)]),
                    )
                )
                matched = weekly.join(cohort_df, on="repo_id", how="inner")
                matched_row = (
                    matched.agg(
                        F.count(F.lit(1)).alias("matched_row_count"),
                        F.countDistinct("repo_id").alias("matched_repo_count"),
                        F.sum(F.col("event_count")).alias("matched_event_count"),
                        F.countDistinct("week_start").alias("active_week_count"),
                    )
                    .first()
                    .asDict()
                )
                matched_repo_count = _as_int(matched_row["matched_repo_count"])
                coverage_summary.append(
                    {
                        "label": label,
                        "cohort_repo_count": len(repo_ids),
                        "matched_repo_count": matched_repo_count,
                        "missing_repo_count": len(repo_ids) - matched_repo_count,
                        "coverage_ratio": matched_repo_count / len(repo_ids),
                        "active_week_count": _as_int(matched_row["active_week_count"]),
                        "matched_row_count": _as_int(matched_row["matched_row_count"]),
                        "matched_event_count": _as_int(
                            matched_row["matched_event_count"]
                        ),
                    }
                )
            spark.createDataFrame(
                [
                    (
                        row["label"],
                        row["cohort_repo_count"],
                        row["matched_repo_count"],
                        row["missing_repo_count"],
                        row["coverage_ratio"],
                        row["active_week_count"],
                        row["matched_row_count"],
                        row["matched_event_count"],
                        arguments.period_start,
                        arguments.period_end,
                    )
                    for row in coverage_summary
                ],
                schema=coverage_schema,
            ).write.mode("errorifexists").parquet(coverage_output)

        quality_schema = StructType(
            [
                StructField("input_path", StringType(), False),
                StructField("input_file_count", LongType(), False),
                StructField("period_start", StringType(), False),
                StructField("period_end", StringType(), False),
                StructField("total_input_events", LongType(), False),
                StructField("repo_id_null_count", LongType(), False),
                StructField("repo_name_null_count", LongType(), False),
                StructField("created_at_null_count", LongType(), False),
                StructField("invalid_event_count", LongType(), False),
                StructField("malformed_json_count", LongType(), False),
                StructField("valid_repo_event_count", LongType(), False),
                StructField("row_count", LongType(), False),
                StructField("unique_repo_id_count", LongType(), False),
                StructField("week_count", LongType(), False),
                StructField("repo_name_collision_count", LongType(), False),
            ]
        )
        spark.createDataFrame(
            [
                (
                    arguments.input,
                    len(input_files),
                    arguments.period_start,
                    arguments.period_end,
                    total_input_events,
                    _as_int(quality_row["repo_id_null_count"]),
                    _as_int(quality_row["repo_name_null_count"]),
                    _as_int(quality_row["created_at_null_count"]),
                    invalid_event_count,
                    _as_int(quality_row["malformed_json_count"]),
                    valid_repo_event_count,
                    row_count,
                    unique_repo_id_count,
                    len(observed_weeks),
                    repo_name_collision_count,
                )
            ],
            schema=quality_schema,
        ).write.mode("errorifexists").parquet(quality_output)

        readback_weeks: dict[str, dict[str, object]] = {}
        readback_rows = 0
        for week, week_output in week_outputs.items():
            slice_df = spark.read.parquet(week_output)
            if tuple(slice_df.columns) != ACTIVITY_COLUMNS:
                raise RuntimeError(
                    f"week {week} schema mismatch: "
                    f"{slice_df.columns} != {list(ACTIVITY_COLUMNS)}"
                )
            slice_stats = (
                slice_df.agg(
                    F.count(F.lit(1)).alias("row_count"),
                    F.countDistinct("repo_id").alias("repo_count"),
                    F.countDistinct("week_start").alias("week_count"),
                    F.sum(F.col("event_count")).alias("event_count"),
                    F.sum(F.when(F.col("repo_id").isNull(), 1).otherwise(0)).alias(
                        "null_repo_id"
                    ),
                    F.sum(F.when(F.col("repo_name").isNull(), 1).otherwise(0)).alias(
                        "null_repo_name"
                    ),
                    F.sum(F.when(F.col("event_count") < 0, 1).otherwise(0)).alias(
                        "negative_event_count"
                    ),
                )
                .first()
                .asDict()
            )
            slice_row_count = _as_int(slice_stats["row_count"])
            problems = {
                "duplicate repo_id": slice_row_count
                != _as_int(slice_stats["repo_count"]),
                "more than one week_start": _as_int(slice_stats["week_count"]) != 1,
                "null repo_id": _as_int(slice_stats["null_repo_id"]) > 0,
                "null repo_name": _as_int(slice_stats["null_repo_name"]) > 0,
                "negative event_count": _as_int(slice_stats["negative_event_count"])
                > 0,
                "row count changed": slice_row_count
                != _as_int(week_row_map[week]["row_count"]),
            }
            failed = sorted(name for name, tripped in problems.items() if tripped)
            if failed:
                raise RuntimeError(f"week {week} read-back rejected: {failed}")
            observed_week = slice_df.select("week_start").first()["week_start"]
            if observed_week != week:
                raise RuntimeError(
                    f"week directory {week} holds week_start {observed_week}"
                )
            readback_rows += slice_row_count
            readback_weeks[week] = {
                "uri": week_output,
                "row_count": slice_row_count,
                "event_count": _as_int(slice_stats["event_count"]),
                "fully_within_period": week_is_fully_within_period(
                    week, arguments.period_start, arguments.period_end
                ),
                # Taken from the slice already in hand.  `-225` publishes this
                # in the week's manifest so C can verify the bytes it reads,
                # and a second pass over the same Parquet would cost a full
                # scan to learn what this read already knows.
                "row_digest": slice_row_digest(spark, F, slice_df),
                "row_digest_format": DIGEST_FORMAT,
            }
        if readback_rows != row_count:
            raise RuntimeError(
                f"weekly row count changed during read-back: {row_count} != {readback_rows}"
            )

        output_file_count, output_bytes = _hadoop_path_stats(spark, arguments.output)
        elapsed_seconds = time.perf_counter() - started
        return {
            "application_id": spark.sparkContext.applicationId,
            "spark_version": spark.version,
            "spark_master": spark.sparkContext.master,
            "executor_count": _executor_count(spark),
            "default_parallelism": spark.sparkContext.defaultParallelism,
            "shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions"),
            "input": {
                "path": arguments.input,
                "format": input_format,
                "file_count": len(input_files),
                "total_input_events": total_input_events,
                # `file_count` is the completeness gate for Raw and is only a
                # scan statistic for the stream, where Spark decides how many
                # part-files a batch becomes.  `stream.observed_hour_count` is
                # the gate there.
                "completeness_gate": (
                    "expected_files"
                    if input_format == INPUT_FORMAT_RAW_JSON
                    else "expected_hours"
                ),
            },
            "stream": stream_summary,
            "week_rule": {
                "week_start": "Monday",
                "timezone": "UTC",
                "boundary": "date_trunc('week', created_at) with session timeZone=UTC",
                "expected_weeks": list(expected_weeks),
                "observed_weeks": observed_weeks,
            },
            "data_quality": {
                "repo_id_null_count": _as_int(quality_row["repo_id_null_count"]),
                "repo_name_null_count": _as_int(quality_row["repo_name_null_count"]),
                "created_at_null_count": _as_int(quality_row["created_at_null_count"]),
                "invalid_event_count": invalid_event_count,
                "malformed_json_count": _as_int(quality_row["malformed_json_count"]),
                "valid_repo_event_count": valid_repo_event_count,
                "row_count": row_count,
                "unique_repo_id_count": unique_repo_id_count,
                "repo_name_collision_count": repo_name_collision_count,
                "duplicate_repo_week_count": 0,
            },
            "join_coverage": coverage_summary,
            "output": {
                "root": arguments.output,
                "repo_activity_weekly": activity_root,
                "weekly_event_type": week_type_output,
                "weeks": weeks_output,
                "join_coverage": coverage_output if cohorts else None,
                "data_quality": quality_output,
                "weeks_written": readback_weeks,
                "row_count": readback_rows,
                "parquet_file_count": output_file_count,
                "parquet_bytes": output_bytes,
                "readback_week_slices_match": True,
            },
            "runtime_seconds": round(elapsed_seconds, 3),
        }
    finally:
        if weekly is not None:
            weekly.unpersist()
        if in_period is not None:
            in_period.unpersist()
        spark.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate GH Archive repo activity into Monday-start weeks."
    )
    parser.add_argument(
        "--input-format",
        choices=list(INPUT_FORMATS),
        default=INPUT_FORMAT_RAW_JSON,
        help=(
            "raw-json reads the Historical Raw hourly files below the cutoff; "
            "stream-parquet reads C1's archive of github.events at or above it"
        ),
    )
    parser.add_argument(
        "--input",
        default=None,
        help=(
            f"default: {DEFAULT_INPUT} for raw-json, "
            f"{DEFAULT_STREAM_INPUT} for stream-parquet"
        ),
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--expected-files",
        type=int,
        default=744,
        help="raw-json only; the stream gate is hour coverage, not file count",
    )
    parser.add_argument("--period-start", default=HISTORICAL_START)
    parser.add_argument("--period-end", default=HISTORICAL_CUTOFF)
    parser.add_argument(
        "--join-ids",
        dest="join_ids",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help=(
            "JOIN coverage cohort, repeatable; PATH is a repo-fetch-candidates/v1, "
            "github-repo-snapshot/v1 or c-public-repo-analysis/v1 envelope."
        ),
    )
    parser.add_argument("--join-max-rows", type=int, default=DEFAULT_JOIN_MAX_ROWS)
    parser.add_argument(
        "--app-name",
        default="gitjob-s15p21e102-166-repo-activity-weekly",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    arguments.input = resolve_input_path(arguments.input, arguments.input_format)
    if arguments.expected_files < 1:
        parser.error("--expected-files must be positive")
    if arguments.join_max_rows < 1:
        parser.error("--join-max-rows must be positive")
    try:
        validate_period(
            arguments.period_start,
            arguments.period_end,
            input_format=arguments.input_format,
        )
        cohorts = [parse_join_ids_argument(value) for value in arguments.join_ids]
    except ValueError as exc:
        parser.error(str(exc))
    labels = [label for label, _ in cohorts]
    if len(labels) != len(set(labels)):
        parser.error("--join-ids labels must be unique")
    arguments.join_cohorts = cohorts
    result = run_job(arguments)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
