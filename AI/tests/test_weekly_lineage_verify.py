"""Spark-free tests for the Weekly lineage verifier (-264 goals 4-9).

Each goal gets at least one PASS and one FAIL fixture.  The FAIL cases are the
ones worth reading: they are the shapes that look like a healthy week until the
identity binding is checked.
"""

import hashlib
import json

import pytest
from jobs.repo_activity_weekly import aggregate_weekly_rows, normalize_stream_rows
from jobs.weekly_activity_verify import (
    build_full_report,
    build_verification,
    recompute_weekly_rows,
)
from jobs.weekly_lineage_verify import (
    EXPORT_MANIFEST_SCHEMA,
    EXPORT_METADATA_SCHEMA,
    MANIFEST_SCHEMA,
    ROW_DIGEST_FORMAT,
    canonical_monday,
    parse_weekly_manifest,
    reconcile_weekly_rows,
    summarize_sections,
    verify_c_export_lineage,
    verify_success_manifest,
    verify_trend_lineage,
)

WEEK = "2026-09-07"
SNAPSHOT = "s15p21e102-weekly-20260907-20260917"
PUBLIC = "public-20260917-001"
DIGEST = "a" * 64


def weekly_manifest(**overrides):
    document = {
        "schema_version": MANIFEST_SCHEMA,
        "dataset_snapshot_id": SNAPSHOT,
        "week_start": WEEK,
        "data_uri": f"hdfs:///gitjob/parquet/github/repo_activity_weekly/week={WEEK}",
        "row_count": 2,
        "row_digest": {"format": ROW_DIGEST_FORMAT, "value": DIGEST},
    }
    document.update(overrides)
    return document


def export_artifacts(**metadata_overrides):
    metadata = {
        "source_schema_version": EXPORT_METADATA_SCHEMA,
        "source_version": "1",
        "dataset_snapshot_id": SNAPSHOT,
        "source_uri": f"c-archive-activity://export/{SNAPSHOT}/activity.csv",
        "source_hash": "b" * 64,
        "period": WEEK,
        "granularity": "WEEK",
        "top_n_limit": 1000,
        "selected_repo_count": 2,
        "selected_event_count": 30,
        "valid_event_count": 30,
        "total_active_repo_count": 2,
        "selection_event_coverage": 1.0,
    }
    metadata.update(metadata_overrides)
    metadata_bytes = json.dumps(metadata, sort_keys=True).encode()
    data_bytes = b"repo_id,repo_name,event_count,week_start\n1,a/b,10,2026-09-07\n"
    manifest = {
        "schema_version": EXPORT_MANIFEST_SCHEMA,
        "data_file": "activity.csv",
        "data_sha256": hashlib.sha256(data_bytes).hexdigest(),
        "metadata_file": "metadata.json",
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "record_count": 2,
    }
    return manifest, metadata, data_bytes, metadata_bytes


def trend_record(**overrides):
    record = {
        "tech_id": "python",
        "week_start": WEEK,
        "public_snapshot_id": PUBLIC,
        "dataset_snapshot_id": SNAPSHOT,
        "registry_version": "v1",
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------
# goals 4 and 5 -- valid repo events, then (repo_id, week_start) counts
# --------------------------------------------------------------------------


def stream_row(repo_id, repo_name, occurred_at, source_id):
    return {
        "source": "gharchive",
        "source_id": source_id,
        "schema_version": "1",
        "event_type": "PushEvent",
        "occurred_at": occurred_at,
        "payload": json.dumps(
            {"repo": {"id": repo_id, "name": repo_name}, "created_at": occurred_at}
        ),
    }


def test_recompute_reuses_the_production_rules():
    rows = [
        stream_row(1, "a/b", "2026-09-07T01:00:00Z", "2026-09-07T01:00:00Z/1"),
        stream_row(1, "a/b", "2026-09-07T02:00:00Z", "2026-09-07T02:00:00Z/2"),
        stream_row(2, "c/d", "2026-09-08T01:00:00Z", "2026-09-08T01:00:00Z/3"),
    ]

    assert recompute_weekly_rows(rows) == aggregate_weekly_rows(
        normalize_stream_rows(rows)
    )


def test_invalid_repo_events_are_dropped():
    """Goal 4: no repo_id, blank name, unusable timestamp."""

    rows = [
        stream_row(1, "a/b", "2026-09-07T01:00:00Z", "2026-09-07T01:00:00Z/1"),
        stream_row(None, "a/b", "2026-09-07T01:00:00Z", "2026-09-07T01:00:00Z/2"),
        stream_row(3, "   ", "2026-09-07T01:00:00Z", "2026-09-07T01:00:00Z/3"),
        stream_row(4, "e/f", "not-a-timestamp", "2026-09-07T01:00:00Z/4"),
        stream_row(-1, "g/h", "2026-09-07T01:00:00Z", "2026-09-07T01:00:00Z/5"),
    ]

    recomputed = recompute_weekly_rows(rows)

    assert [row["repo_id"] for row in recomputed] == [1]


def test_duplicate_envelopes_are_counted_once():
    """Goal 5 rides on goal 3's dedup: the same identity twice is one event."""

    duplicate = stream_row(1, "a/b", "2026-09-07T01:00:00Z", "2026-09-07T01:00:00Z/1")
    recomputed = recompute_weekly_rows([duplicate, dict(duplicate)])

    assert recomputed[0]["event_count"] == 1


def test_expected_counts_group_by_repo_and_week():
    rows = [
        stream_row(1, "a/b", "2026-09-07T01:00:00Z", "2026-09-07T01:00:00Z/1"),
        stream_row(1, "a/b", "2026-09-09T01:00:00Z", "2026-09-09T01:00:00Z/2"),
        stream_row(1, "a/b", "2026-09-14T01:00:00Z", "2026-09-14T01:00:00Z/3"),
    ]

    recomputed = recompute_weekly_rows(rows)

    assert {(row["week_start"], row["event_count"]) for row in recomputed} == {
        ("2026-09-07", 2),
        ("2026-09-14", 1),
    }


# --------------------------------------------------------------------------
# goal 6 -- recomputed rows against the weekly output
# --------------------------------------------------------------------------


def weekly_rows(*rows):
    return [
        {"repo_id": r, "repo_name": n, "event_count": c, "week_start": WEEK}
        for r, n, c in rows
    ]


def test_weekly_reconciliation_passes_when_identical():
    rows = weekly_rows((1, "a/b", 10), (2, "c/d", 20))
    section = reconcile_weekly_rows(rows, list(rows))

    assert section["pass"] is True
    assert section["errors"] == []
    assert section["expected_event_total"] == section["observed_event_total"] == 30


def test_weekly_reconciliation_fails_on_count_mismatch():
    expected = weekly_rows((1, "a/b", 10), (2, "c/d", 20))
    observed = weekly_rows((1, "a/b", 10), (2, "c/d", 7))

    section = reconcile_weekly_rows(expected, observed)

    assert section["pass"] is False
    assert section["count_mismatches"] == [
        {"repo_id": 2, "week_start": WEEK, "expected": 20, "observed": 7}
    ]


def test_weekly_reconciliation_fails_on_missing_row():
    expected = weekly_rows((1, "a/b", 10), (2, "c/d", 20))
    observed = weekly_rows((1, "a/b", 10))

    section = reconcile_weekly_rows(expected, observed)

    assert section["pass"] is False
    assert section["missing_rows"] == [{"repo_id": 2, "week_start": WEEK}]


def test_weekly_reconciliation_fails_on_unexpected_row():
    expected = weekly_rows((1, "a/b", 10))
    observed = weekly_rows((1, "a/b", 10), (9, "x/y", 1))

    section = reconcile_weekly_rows(expected, observed)

    assert section["pass"] is False
    assert section["unexpected_rows"] == [{"repo_id": 9, "week_start": WEEK}]


def test_weekly_reconciliation_fails_on_renamed_repository_drift():
    expected = weekly_rows((1, "new/name", 10))
    observed = weekly_rows((1, "old/name", 10))

    section = reconcile_weekly_rows(expected, observed)

    assert section["pass"] is False
    assert section["name_mismatches"][0]["expected"] == "new/name"


# --------------------------------------------------------------------------
# goal 7 -- _SUCCESS.json / digest
# --------------------------------------------------------------------------


def test_success_manifest_passes():
    section = verify_success_manifest(
        weekly_manifest(), observed_row_count=2, observed_row_digest=DIGEST
    )

    assert section["pass"] is True


def test_success_manifest_fails_on_row_count_mismatch():
    section = verify_success_manifest(
        weekly_manifest(), observed_row_count=3, observed_row_digest=DIGEST
    )

    assert section["pass"] is False
    assert "row_count disagrees" in section["errors"][0]


def test_success_manifest_fails_on_digest_mismatch():
    section = verify_success_manifest(
        weekly_manifest(), observed_row_count=2, observed_row_digest="c" * 64
    )

    assert section["pass"] is False
    assert "row_digest disagrees with the data" in section["errors"]


def test_success_manifest_fails_on_wrong_snapshot_identity():
    section = verify_success_manifest(
        weekly_manifest(),
        observed_row_count=2,
        observed_row_digest=DIGEST,
        expected_dataset_snapshot_id="some-other-snapshot",
    )

    assert section["pass"] is False


def test_success_manifest_fails_on_wrong_week():
    section = verify_success_manifest(
        weekly_manifest(),
        observed_row_count=2,
        observed_row_digest=DIGEST,
        expected_week_start="2026-09-14",
    )

    assert section["pass"] is False


def test_success_manifest_without_observations_does_not_pass():
    section = verify_success_manifest(
        weekly_manifest(), observed_row_count=None, observed_row_digest=None
    )

    assert section["pass"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": "repo-activity-weekly-publish-manifest/v2"},
        {"row_digest": {"format": "md5", "value": DIGEST}},
        {"row_digest": {"format": ROW_DIGEST_FORMAT, "value": "nothex"}},
        {"row_count": -1},
        {"week_start": "2026-09-08"},  # a Tuesday
        {"data_uri": ""},
    ],
)
def test_malformed_weekly_manifest_is_refused(overrides):
    with pytest.raises((TypeError, ValueError)):
        parse_weekly_manifest(weekly_manifest(**overrides))


def test_extra_manifest_field_is_refused():
    document = weekly_manifest()
    document["extra"] = 1
    with pytest.raises(ValueError):
        parse_weekly_manifest(document)


def test_canonical_monday_rejects_a_tuesday():
    assert canonical_monday("2026-09-07") == "2026-09-07"
    with pytest.raises(ValueError):
        canonical_monday("2026-09-08")


def test_restated_contract_constants_match_the_consumer():
    """`Infra/spark` cannot import `AI`, so the constants are restated there.

    This is the test that keeps the two copies honest -- if the consumer's
    contract moves, the verifier stops agreeing with what production accepts.
    """

    from jobs import weekly_lineage_verify as lineage
    from worker import weekly_activity_intake as intake

    assert lineage.MANIFEST_SCHEMA == intake.MANIFEST_SCHEMA
    assert lineage.ROW_DIGEST_FORMAT == intake.ROW_DIGEST_FORMAT


# --------------------------------------------------------------------------
# goal 8 -- C export manifest / metadata / data lineage
# --------------------------------------------------------------------------


def test_c_export_lineage_passes():
    manifest, metadata, data_bytes, metadata_bytes = export_artifacts()

    section = verify_c_export_lineage(
        weekly_manifest=weekly_manifest(),
        export_manifest=manifest,
        export_metadata=metadata,
        data_bytes=data_bytes,
        metadata_bytes=metadata_bytes,
    )

    assert section["pass"] is True
    assert section["content_binding_checked"] is True


def test_c_export_lineage_fails_on_data_checksum():
    manifest, metadata, _, metadata_bytes = export_artifacts()

    section = verify_c_export_lineage(
        weekly_manifest=weekly_manifest(),
        export_manifest=manifest,
        export_metadata=metadata,
        data_bytes=b"tampered",
        metadata_bytes=metadata_bytes,
    )

    assert section["pass"] is False
    assert "data_sha256 does not match" in " ".join(section["errors"])


def test_c_export_lineage_fails_on_source_snapshot_mismatch():
    """A well-formed export of a different snapshot."""

    manifest, metadata, data_bytes, metadata_bytes = export_artifacts(
        dataset_snapshot_id="some-other-snapshot"
    )

    section = verify_c_export_lineage(
        weekly_manifest=weekly_manifest(),
        export_manifest=manifest,
        export_metadata=metadata,
        data_bytes=data_bytes,
        metadata_bytes=metadata_bytes,
    )

    assert section["pass"] is False
    assert "dataset_snapshot_id does not match" in " ".join(section["errors"])


def test_c_export_lineage_fails_on_period_mismatch():
    manifest, metadata, data_bytes, metadata_bytes = export_artifacts(
        period="2026-09-14"
    )

    section = verify_c_export_lineage(
        weekly_manifest=weekly_manifest(),
        export_manifest=manifest,
        export_metadata=metadata,
        data_bytes=data_bytes,
        metadata_bytes=metadata_bytes,
    )

    assert section["pass"] is False
    assert "period does not match" in " ".join(section["errors"])


def test_c_export_lineage_fails_on_record_count_disagreement():
    manifest, metadata, data_bytes, metadata_bytes = export_artifacts(
        selected_repo_count=5
    )

    section = verify_c_export_lineage(
        weekly_manifest=weekly_manifest(),
        export_manifest=manifest,
        export_metadata=metadata,
        data_bytes=data_bytes,
        metadata_bytes=metadata_bytes,
    )

    assert section["pass"] is False


def test_c_export_lineage_without_bytes_does_not_pass():
    manifest, metadata, _, _ = export_artifacts()

    section = verify_c_export_lineage(
        weekly_manifest=weekly_manifest(),
        export_manifest=manifest,
        export_metadata=metadata,
    )

    assert section["pass"] is False
    assert section["content_binding_checked"] is False


def test_c_export_lineage_fails_on_month_granularity():
    manifest, metadata, data_bytes, metadata_bytes = export_artifacts(
        granularity="MONTH"
    )

    section = verify_c_export_lineage(
        weekly_manifest=weekly_manifest(),
        export_manifest=manifest,
        export_metadata=metadata,
        data_bytes=data_bytes,
        metadata_bytes=metadata_bytes,
    )

    assert section["pass"] is False


# --------------------------------------------------------------------------
# goal 9 -- TREND snapshot / head lineage
# --------------------------------------------------------------------------


def test_trend_lineage_passes():
    _, metadata, _, _ = export_artifacts()

    section = verify_trend_lineage(
        weekly_manifest=weekly_manifest(),
        export_metadata=metadata,
        trend_records=[trend_record()],
        public_snapshot_id=PUBLIC,
        registry_version="v1",
    )

    assert section["pass"] is True


def test_trend_lineage_fails_on_wrong_week():
    _, metadata, _, _ = export_artifacts()

    section = verify_trend_lineage(
        weekly_manifest=weekly_manifest(),
        export_metadata=metadata,
        trend_records=[trend_record(week_start="2026-08-31")],
        public_snapshot_id=PUBLIC,
    )

    assert section["pass"] is False
    assert "is for week" in " ".join(section["errors"])


def test_trend_lineage_fails_on_wrong_public_head():
    _, metadata, _, _ = export_artifacts()

    section = verify_trend_lineage(
        weekly_manifest=weekly_manifest(),
        export_metadata=metadata,
        trend_records=[trend_record(public_snapshot_id="public-other")],
        public_snapshot_id=PUBLIC,
    )

    assert section["pass"] is False


def test_trend_lineage_fails_on_wrong_source_snapshot():
    _, metadata, _, _ = export_artifacts()

    section = verify_trend_lineage(
        weekly_manifest=weekly_manifest(),
        export_metadata=metadata,
        trend_records=[trend_record(dataset_snapshot_id="some-other-snapshot")],
        public_snapshot_id=PUBLIC,
    )

    assert section["pass"] is False


def test_trend_lineage_fails_on_duplicate_logical_result():
    _, metadata, _, _ = export_artifacts()

    section = verify_trend_lineage(
        weekly_manifest=weekly_manifest(),
        export_metadata=metadata,
        trend_records=[trend_record(), trend_record()],
        public_snapshot_id=PUBLIC,
    )

    assert section["pass"] is False
    assert "duplicates an earlier" in " ".join(section["errors"])


def test_trend_lineage_fails_when_no_trend_exists():
    _, metadata, _, _ = export_artifacts()

    section = verify_trend_lineage(
        weekly_manifest=weekly_manifest(),
        export_metadata=metadata,
        trend_records=[],
        public_snapshot_id=PUBLIC,
    )

    assert section["pass"] is False
    assert "no TREND record exists for this week" in section["errors"]


def test_missing_trend_evidence_is_unchecked_not_passed():
    _, metadata, _, _ = export_artifacts()

    section = verify_trend_lineage(
        weekly_manifest=weekly_manifest(),
        export_metadata=metadata,
        trend_records=None,
        public_snapshot_id=PUBLIC,
    )

    assert section["checked"] is False
    assert section["pass"] is False


# --------------------------------------------------------------------------
# goal 10 -- the combined report
# --------------------------------------------------------------------------


def passing_completeness():
    hours = [f"2026-09-07T{hour:02d}:00:00Z" for hour in range(24)]
    return build_verification(
        period_start="2026-09-07T00:00:00Z",
        period_end="2026-09-08T00:00:00Z",
        input_uri="hdfs:///gitjob/parquet/stream/github.events",
        expected_counts=dict.fromkeys(hours, 10),
        observed={
            hour: {"raw_row_count": 10, "deduplicated_event_count": 10}
            for hour in hours
        },
    )


def all_sections():
    manifest, metadata, data_bytes, metadata_bytes = export_artifacts()
    rows = weekly_rows((1, "a/b", 10), (2, "c/d", 20))
    return {
        "weekly_reconciliation": reconcile_weekly_rows(rows, list(rows)),
        "success_manifest": verify_success_manifest(
            weekly_manifest(), observed_row_count=2, observed_row_digest=DIGEST
        ),
        "c_export_lineage": verify_c_export_lineage(
            weekly_manifest=weekly_manifest(),
            export_manifest=manifest,
            export_metadata=metadata,
            data_bytes=data_bytes,
            metadata_bytes=metadata_bytes,
        ),
        "trend_lineage": verify_trend_lineage(
            weekly_manifest=weekly_manifest(),
            export_metadata=metadata,
            trend_records=[trend_record()],
            public_snapshot_id=PUBLIC,
        ),
    }


def test_full_report_passes_when_every_section_passes():
    report = build_full_report(
        input_completeness=passing_completeness(), **all_sections()
    )

    assert report["result"] == "PASS"
    assert report["summary"]["failed_sections"] == []
    assert report["summary"]["unchecked_sections"] == []
    assert len(report["sections"]) == 5


def test_full_report_fails_when_a_section_is_missing():
    sections = all_sections()
    sections["trend_lineage"] = None

    report = build_full_report(input_completeness=passing_completeness(), **sections)

    assert report["result"] == "FAIL"
    assert "trend_lineage" in report["summary"]["unchecked_sections"]
    assert "trend_lineage" in report["summary"]["failed_sections"]


def test_full_report_fails_when_input_is_incomplete():
    hours = [f"2026-09-07T{hour:02d}:00:00Z" for hour in range(24)]
    incomplete = build_verification(
        period_start="2026-09-07T00:00:00Z",
        period_end="2026-09-08T00:00:00Z",
        input_uri="hdfs:///gitjob/parquet/stream/github.events",
        expected_counts=dict.fromkeys(hours, 10),
        observed={
            hour: {"raw_row_count": 4, "deduplicated_event_count": 4} for hour in hours
        },
    )

    report = build_full_report(input_completeness=incomplete, **all_sections())

    assert report["result"] == "FAIL"
    assert "input_completeness" in report["summary"]["failed_sections"]


def test_full_report_is_json_serializable():
    report = build_full_report(
        input_completeness=passing_completeness(), **all_sections()
    )

    assert json.loads(json.dumps(report))["result"] == "PASS"


def test_summarize_sections_never_passes_an_empty_report():
    assert summarize_sections([])["passed"] is False
