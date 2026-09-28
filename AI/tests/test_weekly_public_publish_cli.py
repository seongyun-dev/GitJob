"""Publication and repo-id source rules for the weekly PUBLIC publish entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from github.weekly_public_publish_cli import (
    MARKER_FILE,
    PublicHeadMissing,
    publish_publication,
    write_repo_id_source,
)

ROOT = "hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=weekcohort-2026-04-06-v1"
WEEK = "2026-04-06"


class FakePublisher:
    """`store_immutable` with the semantics `common.webhdfs` implements."""

    def __init__(self, existing=None, fail_on=None):
        self.objects = dict(existing or {})
        self.writes = []
        self.fail_on = fail_on

    def store_immutable(self, path, content):
        if self.fail_on is not None and len(self.writes) == self.fail_on:
            raise OSError("webhdfs is unreachable")
        self.writes.append(path)
        if path in self.objects:
            if self.objects[path] != content:
                raise FileExistsError("immutable object exists with different content")
            return f"hdfs:/{path}"
        self.objects[path] = content
        return f"hdfs:/{path}"

    def exists(self, path):
        return path in self.objects

    def read(self, path):
        return self.objects[path]


class FakeStore:
    """`select_public_snapshot` with the signature `ComputeStore` exposes."""

    def __init__(self, selection=None):
        self.selection = selection
        self.calls = []

    def select_public_snapshot(self, *, registry_version, include_partial, week_start):
        self.calls.append((registry_version, include_partial, week_start))
        return self.selection


def _publication(files=None):
    class Stub:
        week_start = WEEK
        dataset_snapshot_id = "weekcohort-2026-04-06-v1"
        publication_root = ROOT
        record_count = 3

    Stub.files = files or {
        "snapshot.json": b'{"schema_version":"github-repo-snapshot/v1"}',
        "run-summary.json": b'{"record_count":3}',
        "failures.json": b'{"failure_count":0}',
        MARKER_FILE: b'{"objects":{}}',
    }
    return Stub()


def _public_payload(*, included, excluded=()):
    records = [
        {"github_repo_id": repo_id, "included_in_denominator": True}
        for repo_id in included
    ]
    records += [
        {"github_repo_id": repo_id, "included_in_denominator": False}
        for repo_id in excluded
    ]
    return {
        "schema_version": "c-public-published-result/v1",
        "result": {"schema_version": "c-public-repo-analysis/v1", "records": records},
    }


def test_completion_marker_is_stored_after_every_other_object():
    publisher = FakePublisher()

    publish_publication(_publication(), publisher=publisher)

    assert [Path(path).name for path in publisher.writes] == [
        "snapshot.json",
        "run-summary.json",
        "failures.json",
        MARKER_FILE,
    ]


def test_republishing_identical_bytes_writes_nothing_new():
    publisher = FakePublisher()
    publish_publication(_publication(), publisher=publisher)
    before = dict(publisher.objects)

    result = publish_publication(_publication(), publisher=publisher)

    assert publisher.objects == before
    assert result.republished is True


def test_same_identity_with_different_bytes_is_refused_before_the_marker():
    publisher = FakePublisher()
    publish_publication(_publication(), publisher=publisher)
    changed = dict(_publication().files)
    changed["run-summary.json"] = b'{"record_count":4}'
    marker = publisher.objects[f"/{ROOT.split('///')[1]}/{MARKER_FILE}"]

    with pytest.raises(FileExistsError):
        publish_publication(_publication(changed), publisher=publisher)

    # The marker still names the first publication, so a reader sees one week.
    assert publisher.objects[f"/{ROOT.split('///')[1]}/{MARKER_FILE}"] == marker


def test_failure_before_the_marker_leaves_no_valid_publication():
    publisher = FakePublisher(fail_on=2)

    with pytest.raises(OSError):
        publish_publication(_publication(), publisher=publisher)

    assert not any(path.endswith(MARKER_FILE) for path in publisher.objects)


def test_dry_run_stores_nothing():
    publisher = FakePublisher()

    result = publish_publication(_publication(), publisher=publisher, dry_run=True)

    assert publisher.objects == {}
    assert publisher.writes == []
    assert result.stored_uris == {}


def test_repo_id_source_is_not_written_when_no_public_head_covers_the_week(tmp_path):
    store = FakeStore(selection=None)
    destination = tmp_path / "repo-ids.json"

    with pytest.raises(PublicHeadMissing):
        write_repo_id_source(
            store,
            destination,
            week_start=WEEK,
            registry_version="registry-20260911.4",
            include_partial=False,
        )

    assert not destination.exists()


def test_repo_id_source_holds_the_selected_public_payload(tmp_path):
    payload = _public_payload(included=(11, 22))
    store = FakeStore(selection=("c-abc", payload))
    destination = tmp_path / "repo-ids.json"

    snapshot_id = write_repo_id_source(
        store,
        destination,
        week_start=WEEK,
        registry_version="registry-20260911.4",
        include_partial=False,
    )

    assert snapshot_id == "c-abc"
    assert json.loads(destination.read_text(encoding="utf-8")) == payload
    assert store.calls == [("registry-20260911.4", False, WEEK)]


def test_repo_id_source_keeps_denominator_exclusions_visible_to_the_exporter(tmp_path):
    # The exporter drops `included_in_denominator: false` rows itself, so the
    # source must carry them rather than pre-filtering to ids: a bare id list
    # would lose the flag and put non-denominator repositories in the export,
    # which the weekly consumer rejects and then commits away.
    payload = _public_payload(included=(11,), excluded=(99,))
    store = FakeStore(selection=("c-abc", payload))
    destination = tmp_path / "repo-ids.json"

    write_repo_id_source(
        store,
        destination,
        week_start=WEEK,
        registry_version="registry-20260911.4",
        include_partial=False,
    )

    written = json.loads(destination.read_text(encoding="utf-8"))
    assert written["schema_version"] == "c-public-published-result/v1"
    flags = {
        row["github_repo_id"]: row["included_in_denominator"]
        for row in written["result"]["records"]
    }
    assert flags == {11: True, 99: False}


def test_a_month_scoped_public_cannot_cover_a_week():
    # The whole reason the repo-id source is looked up per week: a MONTH
    # publication overlaps the week but describes a different period, and
    # S15P21E102-337 made the selector refuse it. If this ever loosened, the
    # exporter would be handed a denominator built over the wrong period.
    from datetime import date

    from worker.store import _public_payload_covers_week

    month = {
        "records": [
            {
                "included_in_denominator": True,
                "target_period": "2026-04-01/2026-04-30",
                "activity_period_start": "2026-04-01",
                "activity_period_end": "2026-04-30",
            }
        ]
    }
    week = {
        "records": [
            {
                "included_in_denominator": True,
                "target_period": "2026-04-06/2026-04-12",
                "activity_period_start": "2026-04-06",
                "activity_period_end": "2026-04-12",
            }
        ]
    }

    assert not _public_payload_covers_week(month, date(2026, 4, 6))
    assert _public_payload_covers_week(week, date(2026, 4, 6))


def test_failures_object_matches_the_bytes_published_for_the_b1_weeks():
    # Golden from the 2026-09-20 production publication of 2026-03-09, read
    # back from HDFS. It pins the serialization the published weeks were
    # written with, so a change to `_canonical` cannot silently produce a
    # different publication for the weeks still to be published.
    from github.weekly_cohort_snapshot import (
        WEEKLY_COHORT_FAILURES_SCHEMA,
        _canonical,
    )

    published = (
        b'{"dataset_snapshot_id":"s15p21e102-296-weekcohort-20260309-v1",'
        b'"failure_count":0,"repos":[],'
        b'"schema_version":"github-repo-fetch-failures/v1"}'
    )

    assert (
        _canonical(
            {
                "schema_version": WEEKLY_COHORT_FAILURES_SCHEMA,
                "dataset_snapshot_id": "s15p21e102-296-weekcohort-20260309-v1",
                "failure_count": 0,
                "repos": [],
            }
        )
        == published
    )


def test_repo_id_source_refuses_a_payload_without_a_recognised_schema(tmp_path):
    store = FakeStore(selection=("c-abc", {"records": []}))
    destination = tmp_path / "repo-ids.json"

    with pytest.raises(ValueError, match="schema_version"):
        write_repo_id_source(
            store,
            destination,
            week_start=WEEK,
            registry_version="registry-20260911.4",
            include_partial=False,
        )

    assert not destination.exists()
