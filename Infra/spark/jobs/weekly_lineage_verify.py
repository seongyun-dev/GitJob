"""Offline lineage checks for one Weekly week, from output back to TREND.

S15P21E102-264 goals 6-9.  `weekly_activity_verify` answers whether the input
arrived; this answers whether everything built on top of it still refers to
that input and to nothing else.

The chain each function covers, and the identity that joins two links:

    Weekly output rows      --(row_count, row_digest)-->  _SUCCESS.json
    _SUCCESS.json           --(dataset_snapshot_id,
                               week_start == period)  -->  C export metadata
    C export metadata       --(data_sha256,
                               metadata_sha256)       -->  C export manifest
    PUBLIC_GITHUB head      --(public_snapshot_id,
                               week_start)            -->  TREND record

Nothing here reads Spark or a database.  Every check takes the documents that
were already written and re-derives the binding, so the same code runs against
production artifacts and against fixtures.  It is the verifier half of the
contracts `worker/weekly_activity_intake` enforces at consume time: that module
decides whether to *accept* a week, this one reports *why* a week would be
rejected, for all links at once rather than stopping at the first.

### Evidence that is absent is not evidence of correctness

Every check reports `checked`.  A section that could not run because a document
was not supplied is `checked=false, pass=false` -- never a quiet PASS.  A
recovery decision made from a report that silently skipped its lineage is
worse than no report.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

# `worker/weekly_activity_intake` holds the consume-side copies of these.  They
# are restated rather than imported because `Infra/spark` cannot import `AI`:
# the Spark image carries only this tree.  The tests assert both agree.
MANIFEST_SCHEMA = "repo-activity-weekly-publish-manifest/v1"
ROW_DIGEST_FORMAT = "typed-json-v2"
EXPORT_MANIFEST_SCHEMA = "c-archive-activity-export/v1"
EXPORT_METADATA_SCHEMA = "repo-activity/v1"
EXPORT_DATA_FILES = ("activity.csv", "activity.ndjson")
EXPORT_METADATA_FILE = "metadata.json"

MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "dataset_snapshot_id",
        "week_start",
        "data_uri",
        "row_count",
        "row_digest",
    }
)
EXPORT_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "data_file",
        "data_sha256",
        "metadata_file",
        "metadata_sha256",
        "record_count",
    }
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

MAX_REPORTED_ROWS = 20


def _fail(section: str, errors: Sequence[str], **details: object) -> dict[str, object]:
    return {
        "section": section,
        "checked": True,
        "pass": not errors,
        "errors": list(errors),
        **details,
    }


def _unchecked(section: str, reason: str) -> dict[str, object]:
    """A section that could not run.  Never a PASS."""

    return {
        "section": section,
        "checked": False,
        "pass": False,
        "errors": [reason],
    }


def canonical_monday(value: object) -> str:
    """The ISO Monday `week_start` contract, as `archive._period_index` states it."""

    if not isinstance(value, str):
        raise TypeError("week_start must be canonical ISO Monday")
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("week_start must be canonical ISO Monday") from error
    if day.isoformat() != value or day.weekday() != 0:
        raise ValueError("week_start must be canonical ISO Monday")
    return value


# --------------------------------------------------------------------------
# goal 6 -- the weekly rows we recomputed against the rows the job wrote
# --------------------------------------------------------------------------


def _row_key(row: Mapping[str, object]) -> tuple[int, str]:
    repo_id = row.get("repo_id")
    week_start = row.get("week_start")
    if isinstance(repo_id, bool) or not isinstance(repo_id, int):
        raise TypeError(f"repo_id must be an integer: {repo_id!r}")
    if not isinstance(week_start, str):
        raise TypeError(f"week_start must be a string: {week_start!r}")
    return repo_id, week_start


def reconcile_weekly_rows(
    expected: Iterable[Mapping[str, object]],
    observed: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Compare independently recomputed weekly rows against the job's output.

    `(repo_id, week_start)` is the grouping key `aggregate_weekly_rows` uses, so
    it is the join key here.  `repo_name` is compared too: a renamed repository
    keeps its latest name in the week, and a disagreement there is a real
    difference even when the counts match.
    """

    expected_rows = {_row_key(row): row for row in expected}
    observed_rows = {_row_key(row): row for row in observed}

    missing = sorted(set(expected_rows) - set(observed_rows))
    unexpected = sorted(set(observed_rows) - set(expected_rows))
    count_mismatches: list[dict[str, object]] = []
    name_mismatches: list[dict[str, object]] = []
    for key in sorted(set(expected_rows) & set(observed_rows)):
        want = expected_rows[key]
        got = observed_rows[key]
        if int(want["event_count"]) != int(got["event_count"]):
            count_mismatches.append(
                {
                    "repo_id": key[0],
                    "week_start": key[1],
                    "expected": int(want["event_count"]),
                    "observed": int(got["event_count"]),
                }
            )
        if want.get("repo_name") != got.get("repo_name"):
            name_mismatches.append(
                {
                    "repo_id": key[0],
                    "week_start": key[1],
                    "expected": want.get("repo_name"),
                    "observed": got.get("repo_name"),
                }
            )

    errors: list[str] = []
    if missing:
        errors.append(f"{len(missing)} expected rows absent from the weekly output")
    if unexpected:
        errors.append(f"{len(unexpected)} weekly output rows were not recomputed")
    if count_mismatches:
        errors.append(f"{len(count_mismatches)} rows disagree on event_count")
    if name_mismatches:
        errors.append(f"{len(name_mismatches)} rows disagree on repo_name")

    return _fail(
        "weekly_output_reconciliation",
        errors,
        expected_row_count=len(expected_rows),
        observed_row_count=len(observed_rows),
        expected_event_total=sum(
            int(row["event_count"]) for row in expected_rows.values()
        ),
        observed_event_total=sum(
            int(row["event_count"]) for row in observed_rows.values()
        ),
        missing_rows=[
            {"repo_id": k[0], "week_start": k[1]} for k in missing[:MAX_REPORTED_ROWS]
        ],
        unexpected_rows=[
            {"repo_id": k[0], "week_start": k[1]}
            for k in unexpected[:MAX_REPORTED_ROWS]
        ],
        count_mismatches=count_mismatches[:MAX_REPORTED_ROWS],
        name_mismatches=name_mismatches[:MAX_REPORTED_ROWS],
    )


# --------------------------------------------------------------------------
# goal 7 -- _SUCCESS.json against the rows it claims to describe
# --------------------------------------------------------------------------


def parse_weekly_manifest(document: object) -> dict[str, object]:
    """Validate a `_SUCCESS.json` against the v1 contract.

    The same shape `worker/weekly_activity_intake.WeeklyManifest.parse`
    accepts, including the exact field set -- an extra key is a different
    manifest, not a superset of this one.
    """

    if not isinstance(document, Mapping):
        raise TypeError("weekly manifest must be an object")
    if set(document) != MANIFEST_FIELDS:
        raise ValueError("weekly manifest field set does not match the contract")
    if document["schema_version"] != MANIFEST_SCHEMA:
        raise ValueError(f"weekly manifest schema_version must be {MANIFEST_SCHEMA}")
    digest = document["row_digest"]
    if not isinstance(digest, Mapping) or set(digest) != {"format", "value"}:
        raise ValueError("row_digest must hold exactly format and value")
    if digest["format"] != ROW_DIGEST_FORMAT:
        raise ValueError(f"row_digest format must be {ROW_DIGEST_FORMAT}")
    if not isinstance(digest["value"], str) or not SHA256_PATTERN.fullmatch(
        digest["value"]
    ):
        raise ValueError("row_digest value must be a lowercase SHA-256")
    row_count = document["row_count"]
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise ValueError("row_count must be a nonnegative integer")
    if not isinstance(document["data_uri"], str) or not document["data_uri"]:
        raise ValueError("data_uri must not be blank")
    dataset_snapshot_id = document["dataset_snapshot_id"]
    if not isinstance(dataset_snapshot_id, str) or not dataset_snapshot_id:
        raise ValueError("dataset_snapshot_id must not be blank")
    return {
        "dataset_snapshot_id": dataset_snapshot_id,
        "week_start": canonical_monday(document["week_start"]),
        "data_uri": document["data_uri"],
        "row_count": row_count,
        "row_digest": digest["value"],
    }


def verify_success_manifest(
    document: object,
    *,
    observed_row_count: int | None,
    observed_row_digest: str | None,
    expected_week_start: str | None = None,
    expected_dataset_snapshot_id: str | None = None,
) -> dict[str, object]:
    """Check `_SUCCESS.json` against the rows actually present.

    `row_digest` is the contract's own answer to Parquet not being
    byte-reproducible, so it is compared as a value rather than recomputed
    here; the caller supplies what `slice_row_digest` returned for the same
    directory.
    """

    try:
        manifest = parse_weekly_manifest(document)
    except (TypeError, ValueError) as error:
        return _fail("success_manifest", [str(error)])

    errors: list[str] = []
    if observed_row_count is None:
        errors.append("no observed row count was supplied")
    elif observed_row_count != manifest["row_count"]:
        errors.append(
            "row_count disagrees with the data: manifest "
            f"{manifest['row_count']}, observed {observed_row_count}"
        )
    if observed_row_digest is None:
        errors.append("no observed row digest was supplied")
    elif observed_row_digest != manifest["row_digest"]:
        errors.append("row_digest disagrees with the data")
    if (
        expected_week_start is not None
        and manifest["week_start"] != expected_week_start
    ):
        errors.append(
            f"week_start is {manifest['week_start']}, expected {expected_week_start}"
        )
    if (
        expected_dataset_snapshot_id is not None
        and manifest["dataset_snapshot_id"] != expected_dataset_snapshot_id
    ):
        errors.append("dataset_snapshot_id is not the snapshot under verification")

    return _fail(
        "success_manifest",
        errors,
        manifest=manifest,
        observed_row_count=observed_row_count,
        observed_row_digest=observed_row_digest,
    )


# --------------------------------------------------------------------------
# goal 8 -- C export manifest / metadata / data, and what they point back to
# --------------------------------------------------------------------------


def verify_c_export_lineage(
    *,
    weekly_manifest: object,
    export_manifest: object,
    export_metadata: object,
    data_bytes: bytes | None = None,
    metadata_bytes: bytes | None = None,
) -> dict[str, object]:
    """Check the bounded export against its own hashes and its Weekly source.

    Two bindings matter and they are separate failures.  The *content* binding
    is `data_sha256` / `metadata_sha256` -- the manifest naming bytes that are
    really there.  The *identity* binding is
    `metadata.dataset_snapshot_id == weekly.dataset_snapshot_id` and
    `metadata.period == weekly.week_start`, which is what makes this export
    this week's rather than a well-formed export of some other week.
    """

    errors: list[str] = []
    try:
        weekly = parse_weekly_manifest(weekly_manifest)
    except (TypeError, ValueError) as error:
        return _fail("c_export_lineage", [f"weekly manifest: {error}"])

    if not isinstance(export_manifest, Mapping):
        return _fail("c_export_lineage", ["export manifest must be an object"])
    if set(export_manifest) != EXPORT_MANIFEST_FIELDS:
        errors.append("export manifest field set does not match the contract")
    if export_manifest.get("schema_version") != EXPORT_MANIFEST_SCHEMA:
        errors.append(
            f"export manifest schema_version must be {EXPORT_MANIFEST_SCHEMA}"
        )
    if export_manifest.get("data_file") not in EXPORT_DATA_FILES:
        errors.append(f"export data_file must be one of {list(EXPORT_DATA_FILES)}")
    if export_manifest.get("metadata_file") != EXPORT_METADATA_FILE:
        errors.append(f"export metadata_file must be {EXPORT_METADATA_FILE}")
    record_count = export_manifest.get("record_count")
    if isinstance(record_count, bool) or not isinstance(record_count, int):
        errors.append("export record_count must be an integer")
        record_count = None
    for field in ("data_sha256", "metadata_sha256"):
        value = export_manifest.get(field)
        if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
            errors.append(f"export {field} must be a lowercase SHA-256")

    if not isinstance(export_metadata, Mapping):
        return _fail("c_export_lineage", [*errors, "export metadata must be an object"])
    if export_metadata.get("source_schema_version") != EXPORT_METADATA_SCHEMA:
        errors.append(f"export source_schema_version must be {EXPORT_METADATA_SCHEMA}")
    if export_metadata.get("granularity") != "WEEK":
        errors.append("export granularity must be WEEK for a weekly lineage")

    # content binding
    if data_bytes is None:
        errors.append("no export data bytes were supplied; content binding unchecked")
    elif isinstance(export_manifest.get("data_sha256"), str):
        actual = hashlib.sha256(data_bytes).hexdigest()
        if actual != export_manifest["data_sha256"]:
            errors.append("export data_sha256 does not match the data file")
    if metadata_bytes is None:
        errors.append(
            "no export metadata bytes were supplied; content binding unchecked"
        )
    elif isinstance(export_manifest.get("metadata_sha256"), str):
        actual = hashlib.sha256(metadata_bytes).hexdigest()
        if actual != export_manifest["metadata_sha256"]:
            errors.append("export metadata_sha256 does not match metadata.json")

    # identity binding back to the Weekly publication
    if export_metadata.get("dataset_snapshot_id") != weekly["dataset_snapshot_id"]:
        errors.append(
            "export dataset_snapshot_id does not match the weekly manifest: "
            f"{export_metadata.get('dataset_snapshot_id')!r} != "
            f"{weekly['dataset_snapshot_id']!r}"
        )
    if export_metadata.get("period") != weekly["week_start"]:
        errors.append(
            "export period does not match the weekly week_start: "
            f"{export_metadata.get('period')!r} != {weekly['week_start']!r}"
        )

    # internal count reconciliation, the same one the exporter asserts
    selected_repo_count = export_metadata.get("selected_repo_count")
    if record_count is not None and selected_repo_count != record_count:
        errors.append(
            "export record_count does not match selected_repo_count: "
            f"{record_count} != {selected_repo_count}"
        )

    return _fail(
        "c_export_lineage",
        errors,
        dataset_snapshot_id=export_metadata.get("dataset_snapshot_id"),
        period=export_metadata.get("period"),
        record_count=record_count,
        selected_repo_count=selected_repo_count,
        selected_event_count=export_metadata.get("selected_event_count"),
        upstream_source_uri=export_metadata.get("upstream_source_uri"),
        content_binding_checked=data_bytes is not None and metadata_bytes is not None,
    )


# --------------------------------------------------------------------------
# goal 9 -- TREND back to the export, the public head and the week
# --------------------------------------------------------------------------


def verify_trend_lineage(
    *,
    weekly_manifest: object,
    export_metadata: object,
    trend_records: Sequence[Mapping[str, object]] | None,
    public_snapshot_id: str | None,
    registry_version: str | None = None,
) -> dict[str, object]:
    """Check that the stored TREND belongs to this week and this export.

    `worker/weekly_activity_intake` selects a PUBLIC_GITHUB head by
    `(registry_version, include_partial, week_start)` and stores the result
    under that head.  So a TREND row is only this week's if its `week_start`,
    its `public_snapshot_id` and its `dataset_snapshot_id` all agree with the
    documents above -- any one of them drifting is a different week's result
    wearing this week's label.

    `trend_records` being `None` means no TREND evidence was supplied, which is
    reported as unchecked rather than passed.
    """

    try:
        weekly = parse_weekly_manifest(weekly_manifest)
    except (TypeError, ValueError) as error:
        return _fail("trend_lineage", [f"weekly manifest: {error}"])

    if trend_records is None:
        return _unchecked("trend_lineage", "no TREND records were supplied")
    if public_snapshot_id is None:
        return _unchecked("trend_lineage", "no PUBLIC_GITHUB snapshot id was supplied")

    errors: list[str] = []
    if not isinstance(export_metadata, Mapping):
        errors.append("export metadata must be an object")
        export_metadata = {}

    if not trend_records:
        errors.append("no TREND record exists for this week")

    seen_keys: set[tuple[object, object, object]] = set()
    for index, record in enumerate(trend_records):
        if not isinstance(record, Mapping):
            errors.append(f"TREND record {index} is not an object")
            continue
        week = record.get("week_start")
        if week != weekly["week_start"]:
            errors.append(
                f"TREND record {index} is for week {week!r}, "
                f"expected {weekly['week_start']!r}"
            )
        if record.get("public_snapshot_id") != public_snapshot_id:
            errors.append(
                f"TREND record {index} points at PUBLIC_GITHUB "
                f"{record.get('public_snapshot_id')!r}, expected {public_snapshot_id!r}"
            )
        if record.get("dataset_snapshot_id") != weekly["dataset_snapshot_id"]:
            errors.append(
                f"TREND record {index} points at snapshot "
                f"{record.get('dataset_snapshot_id')!r}, "
                f"expected {weekly['dataset_snapshot_id']!r}"
            )
        if registry_version is not None and record.get("registry_version") not in (
            None,
            registry_version,
        ):
            errors.append(
                f"TREND record {index} used registry_version "
                f"{record.get('registry_version')!r}, expected {registry_version!r}"
            )
        # `(tech_id, period)` is C3's snapshot replace key; two rows sharing it
        # are two answers to one question.
        key = (record.get("tech_id"), record.get("week_start"), record.get("period"))
        if key in seen_keys:
            errors.append(
                f"TREND record {index} duplicates an earlier (tech_id, week) result"
            )
        seen_keys.add(key)

    if export_metadata and export_metadata.get("period") != weekly["week_start"]:
        errors.append("export metadata period does not match the weekly week_start")

    return _fail(
        "trend_lineage",
        errors,
        week_start=weekly["week_start"],
        dataset_snapshot_id=weekly["dataset_snapshot_id"],
        public_snapshot_id=public_snapshot_id,
        trend_record_count=len(trend_records),
        distinct_result_count=len(seen_keys),
    )


# --------------------------------------------------------------------------
# the combined verdict
# --------------------------------------------------------------------------


def summarize_sections(sections: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Roll sections into one verdict.  Unchecked never counts as passed."""

    checked = [section for section in sections if section.get("checked")]
    failed = [
        str(section.get("section")) for section in sections if not section.get("pass")
    ]
    return {
        "section_count": len(sections),
        "checked_count": len(checked),
        "unchecked_sections": [
            str(section.get("section"))
            for section in sections
            if not section.get("checked")
        ],
        "failed_sections": failed,
        "passed": bool(sections) and not failed,
    }


def load_json_document(raw: bytes | str) -> object:
    return json.loads(raw)
