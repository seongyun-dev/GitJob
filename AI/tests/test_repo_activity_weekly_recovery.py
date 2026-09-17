"""Fail-closed contract for the bounded Weekly raw recovery input."""

from __future__ import annotations

import json
from hashlib import sha256

import pytest
from jobs.repo_activity_weekly import (
    INPUT_FORMAT_RAW_JSON,
    INPUT_FORMAT_RECOVERY_RAW_JSON,
    INPUT_FORMAT_STREAM_PARQUET,
    INPUT_FORMAT_TRANSITION,
    INPUT_FORMATS,
    RECOVERY_MANIFEST_SCHEMA_VERSION,
    load_recovery_manifest,
    reconcile_recovery_inputs,
    validate_period,
)

WEEK_A_START = "2026-08-31T00:00:00Z"
WEEK_A_END = "2026-09-07T00:00:00Z"


def _manifest_entries():
    entries = []
    for index in range(168):
        from datetime import datetime, timedelta, timezone

        moment = datetime(2026, 8, 31, tzinfo=timezone.utc) + timedelta(hours=index)
        hour = moment.isoformat().replace("+00:00", "Z")
        name = f"{moment:%Y-%m-%d}-{moment.hour}.json.gz"
        entries.append(
            {
                "hour": hour,
                "source_uri": f"hdfs:///gitjob/raw/gharchive/source/{name}",
                "source_sha256": sha256(f"source-{hour}".encode()).hexdigest(),
                "source_event_count": 101,
                "uri": f"hdfs:///gitjob/recovery/weekly/week=2026-08-31/{name}",
                "sha256": sha256(f"accepted-{hour}".encode()).hexdigest(),
                "accepted_event_count": 99,
                "rejected_oversized_count": 1,
                "skipped_line_count": 1,
            }
        )
    return entries


def _write_manifest(tmp_path, entries=None, **updates):
    payload = {
        "schema_version": RECOVERY_MANIFEST_SCHEMA_VERSION,
        "period_start": WEEK_A_START,
        "period_end": WEEK_A_END,
        "max_message_bytes": 1_048_576,
        "files": _manifest_entries() if entries is None else entries,
        **updates,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_recovery_manifest_accepts_exactly_one_named_week(tmp_path):
    manifest = load_recovery_manifest(
        _write_manifest(tmp_path),
        period_start=WEEK_A_START,
        period_end=WEEK_A_END,
    )

    assert manifest["schema_version"] == RECOVERY_MANIFEST_SCHEMA_VERSION
    assert len(manifest["files"]) == 168
    assert manifest["files"][0]["hour"] == WEEK_A_START
    assert manifest["files"][-1]["hour"] == "2026-09-06T23:00:00Z"


def test_local_source_provenance_is_allowed_but_runtime_input_stays_hdfs(tmp_path):
    entries = _manifest_entries()
    entries[0]["source_uri"] = "file:///immutable/2026-08-31-0.json.gz"
    manifest = load_recovery_manifest(
        _write_manifest(tmp_path, entries),
        period_start=WEEK_A_START,
        period_end=WEEK_A_END,
    )

    assert manifest["files"][0]["source_uri_path"] == (
        "/immutable/2026-08-31-0.json.gz"
    )
    entries[0]["uri"] = "file:///not-an-hdfs-runtime-input.json.gz"
    with pytest.raises(ValueError, match="must use"):
        load_recovery_manifest(
            _write_manifest(tmp_path, entries),
            period_start=WEEK_A_START,
            period_end=WEEK_A_END,
        )


def test_recovery_mode_is_additive_to_existing_input_formats():
    assert INPUT_FORMATS == (
        INPUT_FORMAT_RAW_JSON,
        INPUT_FORMAT_STREAM_PARQUET,
        INPUT_FORMAT_TRANSITION,
        INPUT_FORMAT_RECOVERY_RAW_JSON,
    )


def test_recovery_period_is_limited_to_the_two_explicit_weeks():
    validate_period(
        WEEK_A_START,
        WEEK_A_END,
        input_format=INPUT_FORMAT_RECOVERY_RAW_JSON,
    )
    validate_period(
        "2026-09-07T00:00:00Z",
        "2026-09-14T00:00:00Z",
        input_format=INPUT_FORMAT_RECOVERY_RAW_JSON,
    )

    with pytest.raises(ValueError, match="recovery period is not allowed"):
        validate_period(
            "2026-09-14T00:00:00Z",
            "2026-09-21T00:00:00Z",
            input_format=INPUT_FORMAT_RECOVERY_RAW_JSON,
        )


def test_missing_hour_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="exactly 168 files"):
        load_recovery_manifest(
            _write_manifest(tmp_path, _manifest_entries()[:-1]),
            period_start=WEEK_A_START,
            period_end=WEEK_A_END,
        )


def test_duplicate_hour_is_rejected(tmp_path):
    entries = _manifest_entries()
    entries[-1]["hour"] = entries[0]["hour"]

    with pytest.raises(ValueError, match="duplicate recovery hour"):
        load_recovery_manifest(
            _write_manifest(tmp_path, entries),
            period_start=WEEK_A_START,
            period_end=WEEK_A_END,
        )


def test_duplicate_source_uri_is_rejected_before_spark_starts(tmp_path):
    entries = _manifest_entries()
    entries[-1]["source_uri"] = entries[0]["source_uri"]

    with pytest.raises(ValueError, match="duplicate recovery source URI"):
        load_recovery_manifest(
            _write_manifest(tmp_path, entries),
            period_start=WEEK_A_START,
            period_end=WEEK_A_END,
        )


def test_bad_hash_is_rejected_before_spark_starts(tmp_path):
    entries = _manifest_entries()
    entries[0]["sha256"] = "not-a-sha"

    with pytest.raises(ValueError, match="sha256"):
        load_recovery_manifest(
            _write_manifest(tmp_path, entries),
            period_start=WEEK_A_START,
            period_end=WEEK_A_END,
        )


def test_counts_must_explain_every_source_line(tmp_path):
    entries = _manifest_entries()
    entries[0]["accepted_event_count"] = 100

    with pytest.raises(ValueError, match="source count mismatch"):
        load_recovery_manifest(
            _write_manifest(tmp_path, entries),
            period_start=WEEK_A_START,
            period_end=WEEK_A_END,
        )


def test_runtime_reconciliation_rejects_extra_glob_file(tmp_path):
    manifest = load_recovery_manifest(
        _write_manifest(tmp_path),
        period_start=WEEK_A_START,
        period_end=WEEK_A_END,
    )
    observed = {
        entry["uri"]: {
            "sha256": entry["sha256"],
            "accepted_event_count": entry["accepted_event_count"],
        }
        for entry in manifest["files"]
    }
    observed["hdfs:///gitjob/recovery/weekly/extra.json.gz"] = {
        "sha256": "0" * 64,
        "accepted_event_count": 1,
    }

    with pytest.raises(ValueError, match="unexpected recovery input"):
        reconcile_recovery_inputs(manifest["files"], observed)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sha256", "f" * 64, "hash mismatch"),
        ("accepted_event_count", 98, "accepted count mismatch"),
    ],
)
def test_runtime_reconciliation_rejects_changed_file(tmp_path, field, value, message):
    manifest = load_recovery_manifest(
        _write_manifest(tmp_path),
        period_start=WEEK_A_START,
        period_end=WEEK_A_END,
    )
    observed = {
        entry["uri"]: {
            "sha256": entry["sha256"],
            "accepted_event_count": entry["accepted_event_count"],
        }
        for entry in manifest["files"]
    }
    observed[manifest["files"][0]["uri"]][field] = value

    with pytest.raises(ValueError, match=message):
        reconcile_recovery_inputs(manifest["files"], observed)
