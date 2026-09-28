"""Contract rules for the fixed-cohort weekly PUBLIC snapshot bundle generator."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from github.contracts import GitHubRepoSnapshotBatch
from github.snapshot_input import load_published_snapshot
from github.weekly_cohort_snapshot import (
    MARKER_FILE,
    WEEKLY_COHORT_FAILURES_SCHEMA,
    WEEKLY_COHORT_SUMMARY_SCHEMA,
    build_weekly_cohort_publication,
    select_cohort_records,
)
from worker.store import _period_overlaps_week, _target_period_covers_week

FIXTURE = (
    Path(__file__).resolve().parents[1] / "github/fixtures/github_repo_snapshot_v1.json"
)
ROOT = "hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=weekcohort-2026-08-10-v1"
WEEK = "2026-08-10"
GENERATED_AT = datetime(2026, 9, 18, 12, tzinfo=UTC)


def _source() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _records() -> list[dict]:
    return _source()["records"]


def _build(week_activity, *, records=None, week_start=WEEK, **kwargs):
    source = _source()
    return build_weekly_cohort_publication(
        week_start=week_start,
        cohort_records=records if records is not None else source["records"],
        week_activity=week_activity,
        collection_policy=source["collection_policy"],
        collector_version=source["collector_version"],
        dataset_snapshot_id="weekcohort-" + week_start + "-v1",
        pipeline_run_id="weekcohort-" + week_start + "-001",
        generated_at=GENERATED_AT,
        publication_root=ROOT.replace("2026-08-10", week_start),
        **kwargs,
    )


def _batch(publication) -> dict:
    return json.loads(publication.files["snapshot.json"])


def _summary(publication) -> dict:
    return json.loads(publication.files["run-summary.json"])


class _Reader:
    """Serve the generated bundle the way WebHDFS serves a published root."""

    def __init__(self, publication):
        self._files = publication.files
        self._root = publication.publication_root

    def _name(self, uri: str) -> str:
        assert uri.startswith(self._root + "/"), uri
        return uri[len(self._root) + 1 :]

    def read(self, uri: str, *, max_bytes: int) -> bytes:
        return self._files[self._name(uri)][:max_bytes]

    def stat(self, uri: str) -> dict:
        body = self._files[self._name(uri)]
        return {
            "type": "FILE",
            "length": len(body),
            "modificationTime": 1_700_000_000_000,
            "fileId": abs(hash(uri)) % 10**9,
        }


def test_only_repositories_active_in_the_week_become_candidates():
    publication = _build({100001: 40, 100004: 10})

    assert [row["github_repo_id"] for row in _batch(publication)["records"]] == [
        100001,
        100004,
    ]


def test_repository_without_activity_in_the_week_is_dropped():
    publication = _build({100001: 40})

    ids = {row["github_repo_id"] for row in _batch(publication)["records"]}
    assert 100004 not in ids
    assert ids == {100001}


def test_repository_without_reusable_evidence_is_not_a_candidate():
    # 100003 is active but carries neither artifacts nor language metadata,
    # so it can never reach a PUBLIC denominator and must not inflate the bundle.
    publication = _build({100001: 40, 100003: 30})

    assert [row["github_repo_id"] for row in _batch(publication)["records"]] == [100001]


def test_failed_collection_is_not_republished_as_a_weekly_candidate():
    publication = _build({100005: 99, 100001: 40})

    assert [row["github_repo_id"] for row in _batch(publication)["records"]] == [100001]
    failures = json.loads(publication.files["failures.json"])
    assert failures["schema_version"] == WEEKLY_COHORT_FAILURES_SCHEMA
    assert failures["failure_count"] == 0
    assert failures["repos"] == []


def test_target_period_is_narrowed_to_the_iso_week():
    publication = _build({100001: 40})

    record = _batch(publication)["records"][0]
    assert record["target_period"] == "2026-08-10/2026-08-16"


def test_activity_period_is_narrowed_to_the_iso_week():
    publication = _build({100001: 40})

    record = _batch(publication)["records"][0]
    assert record["activity_period_start"] == "2026-08-10"
    assert record["activity_period_end"] == "2026-08-16"


def test_activity_count_becomes_the_weekly_event_count():
    publication = _build({100001: 40})

    assert _batch(publication)["records"][0]["activity_count"] == 40


def test_rank_is_recalculated_from_weekly_activity_and_matches_the_summary():
    publication = _build({100001: 10, 100002: 70, 100004: 30})

    records = _batch(publication)["records"]
    assert [row["github_repo_id"] for row in records] == [100002, 100004, 100001]
    assert [row["activity_rank"] for row in records] == [1, 2, 3]
    dispositions = {
        row["repo_id"]: row["rank"] for row in _summary(publication)["repos"]
    }
    assert dispositions == {
        row["github_repo_id"]: row["activity_rank"] for row in records
    }


def test_summary_uses_the_weekly_run_schema_and_reconciles_its_counts():
    publication = _build({100001: 10, 100002: 70})

    summary = _summary(publication)
    assert summary["schema_version"] == WEEKLY_COHORT_SUMMARY_SCHEMA
    assert summary["record_count"] == 2
    assert summary["quota_reached"] is True
    assert summary["quota_shortfall"] == 0
    assert summary["candidates_examined"] == 2
    assert summary["status_counts"] == {"COMPLETE": 1, "PARTIAL": 1}


def test_identical_input_produces_identical_bytes():
    first = _build({100001: 10, 100002: 70})
    second = _build({100001: 10, 100002: 70})

    assert first.files == second.files


def test_marker_records_the_sha256_of_every_published_object():
    publication = _build({100001: 10})

    marker = json.loads(publication.files[MARKER_FILE])
    for key, name in (
        ("snapshot", "snapshot.json"),
        ("summary", "run-summary.json"),
        ("failures", "failures.json"),
    ):
        assert marker["objects"][key]["uri"] == ROOT + "/" + name
        assert (
            marker["objects"][key]["sha256"]
            == hashlib.sha256(publication.files[name]).hexdigest()
        )


def test_one_week_bundle_does_not_cover_another_week():
    publication = _build({100001: 10})

    record = _batch(publication)["records"][0]
    own = date.fromisoformat(WEEK)
    other = date.fromisoformat("2026-08-31")
    assert _target_period_covers_week(record["target_period"], own)
    assert not _target_period_covers_week(record["target_period"], other)
    start = date.fromisoformat(record["activity_period_start"])
    end = date.fromisoformat(record["activity_period_end"])
    assert _period_overlaps_week(start, end, own)
    assert not _period_overlaps_week(start, end, other)


def test_published_bundle_is_accepted_by_the_public_snapshot_loader():
    publication = _build({100001: 10, 100002: 70, 100004: 30})

    published = load_published_snapshot(
        publication.publication_root, _Reader(publication)
    )

    assert published.batch.dataset_snapshot_id == "weekcohort-2026-08-10-v1"
    assert len(published.batch.records) == 3
    assert published.quality.failure_count == 0
    assert published.quality.candidate_count == 3


def test_generated_batch_still_satisfies_the_shared_snapshot_contract():
    publication = _build({100001: 10, 100002: 70})

    batch = GitHubRepoSnapshotBatch.model_validate(_batch(publication))

    assert batch.pipeline_run_id == "weekcohort-2026-08-10-v1".replace("v1", "001")
    assert {row.github_repo_id for row in batch.records} == {100001, 100002}


def test_week_start_must_be_a_monday():
    with pytest.raises(ValueError, match="Monday"):
        _build({100001: 10}, week_start="2026-08-11")


def test_artifact_uri_prefixes_reject_a_root_outside_the_configured_namespace():
    with pytest.raises(ValueError, match="artifact URI"):
        _build({100001: 10}, artifact_uri_prefixes=("hdfs:///gitjob/elsewhere",))


def test_artifact_uri_prefixes_accept_the_configured_namespace():
    publication = _build(
        {100001: 10}, artifact_uri_prefixes=("hdfs://namenode:9000/gitjob/github",)
    )

    assert len(_batch(publication)["records"]) == 1


def test_cohort_selection_keeps_the_first_source_for_a_repeated_repository():
    fresh = [dict(_records()[0], repo_snapshot_id="fresh")]
    stale = [dict(_records()[0], repo_snapshot_id="stale")]

    selected = select_cohort_records([fresh, stale])

    assert [row["repo_snapshot_id"] for row in selected] == ["fresh"]


def test_cohort_selection_unions_repositories_across_sources():
    first = [_records()[0]]
    second = [_records()[3]]

    selected = select_cohort_records([first, second])

    assert {row["github_repo_id"] for row in selected} == {100001, 100004}
