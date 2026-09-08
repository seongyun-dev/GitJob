"""Observed-union selection precedes job filters and never revives older content."""

from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest
from test_job_cohort import batch, criteria, posting

from job import input_union
from job.cohort import JobCohort
from job.demand import aggregate_demand
from registry.mapper import RegistryMapper
from worker.api import default_registry


@pytest.fixture
def mapper():
    return RegistryMapper(default_registry())


def output(*records, source="SARAMIN", run="run-1", at=None, **changes):
    value = batch(*records).model_copy(
        update={"dataset_snapshot_id": f"dataset-{run}", "pipeline_run_id": run}
    )
    raw = value.model_dump_json(by_alias=True).encode()
    result = {
        "batch": value,
        "occurred_at": at
        or (records[0].collected_at if records else datetime(2026, 9, 7, tzinfo=UTC)),
        "batch_sha256": sha256(raw).hexdigest(),
        "manifest_sha256": sha256(f"manifest-{source}-{run}".encode()).hexdigest(),
        "collection_issues": (),
        "mixed_date_semantics": False,
        "source_site": source,
        "batch_size_bytes": len(raw),
    }
    result.update(changes)
    return SimpleNamespace(**result)


def test_all_sources_share_one_cohort_and_demand(mapper):
    saramin = output(posting("saramin", required=("Java",)), run="saramin")
    worknet = output(
        posting("worknet", source_site="WORKNET", required=("Python",)),
        source="WORKNET",
        run="worknet",
    )
    cohort = input_union.build_input_union((saramin, worknet), criteria(), mapper)
    assert {j.job_id for j in cohort.jobs} == {"SARAMIN:saramin", "WORKNET:worknet"}
    assert cohort.input_count == 2
    assert aggregate_demand(cohort).denominator == 2
    assert {r.tech_id for r in aggregate_demand(cohort).technologies} == {
        "java",
        "python",
    }
    assert {r.pipeline_run_id for r in cohort.input_union.input_batches} == {
        "saramin",
        "worknet",
    }
    assert JobCohort.model_validate_json(cohort.model_dump_json()) == cohort


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"posting_status": "CLOSED"}, "POSTING_CLOSED"),
        (
            {
                "body_status": "MISSING",
                "description_text": None,
                "technology_mentions": (),
            },
            "BODY_UNAVAILABLE",
        ),
        ({"deadline": "2026-09-07T12:00:00Z"}, "DEADLINE_PASSED"),
        (
            {"raw_job_category": "FRONTEND", "title": "프론트엔드 개발자"},
            "ROLE_NOT_MATCHED",
        ),
    ],
)
def test_latest_bad_or_nonmatching_observation_never_falls_back(
    mapper, changes, reason
):
    old = output(posting("same"), run="old")
    new = output(
        posting("same", collected_at="2026-09-07T12:00:00Z", **changes), run="new"
    )
    cohort = input_union.build_input_union((new, old), criteria(), mapper)
    assert not cohort.jobs
    assert reason in cohort.exclusions[0].reasons
    assert cohort.input_union.superseded_record_count == 1
    assert cohort.input_count == 1


def test_new_required_tech_replaces_old_without_source_conflict(mapper):
    old = output(posting("same"), run="old")
    new = output(
        posting("same", required=("Docker",), collected_at="2026-09-07T12:00:00Z"),
        run="new",
    )
    cohort = input_union.build_input_union((old, new), criteria(), mapper)
    assert cohort.jobs[0].required_clauses == (("docker",),)
    assert cohort.review_count == 0
    assert {r.disposition for r in cohort.input_union.observations} == {
        "SELECTED",
        "SUPERSEDED",
    }


def test_equal_latest_conflicts_are_all_reviewed_even_closed_variant(mapper):
    active = output(posting("same"), run="active")
    closed = output(posting("same", posting_status="CLOSED"), run="closed")
    cohort = input_union.build_input_union((active, closed), criteria(), mapper)
    assert not cohort.jobs
    assert cohort.review_count == 2 and cohort.excluded_count == 0
    assert all("SOURCE_RECORD_CONFLICT" in r.reasons for r in cohort.exclusions)
    assert cohort.input_union.conflict_record_count == 2


def test_latest_exact_observation_duplicates_are_counted_and_refs_preserved(mapper):
    one = output(posting("same"), run="one")
    two = output(posting("same"), run="two")
    cohort = input_union.build_input_union((one, two), criteria(), mapper)
    assert len(cohort.jobs) == 1
    assert cohort.input_union.input_record_count == 2
    assert cohort.input_union.duplicate_record_count == 1
    assert {r.disposition for r in cohort.input_union.observations} == {
        "SELECTED",
        "DUPLICATE",
    }


def test_source_filter_excludes_other_inputs_even_from_union_identity(mapper):
    chosen = output(posting("saramin"), run="saramin")
    other = output(
        posting("worknet", source_site="WORKNET"), source="WORKNET", run="worknet"
    )
    expected = input_union.build_input_union(
        (chosen,), criteria(sources=("SARAMIN",)), mapper
    )
    actual = input_union.build_input_union(
        (chosen, other), criteria(sources=("SARAMIN",)), mapper
    )
    assert actual == expected


def test_same_raw_record_id_across_sites_keeps_original_ids_and_distinct_jobs(mapper):
    chosen = output(posting("shared", canonical_job_id="candidate"), run="saramin")
    other = output(
        posting("shared", source_site="WORKNET", canonical_job_id="candidate"),
        source="WORKNET",
        run="worknet",
    )
    cohort = input_union.build_input_union((chosen, other), criteria(), mapper)
    assert len(cohort.jobs) == 2
    assert {r.source_record_id for r in cohort.jobs} == {"shared"}
    assert {r.job_id for r in cohort.jobs} == {"SARAMIN:shared", "WORKNET:shared"}
    assert cohort.review_count == 0


def test_empty_new_batch_does_not_assert_absence_or_delete_previous_observation(mapper):
    old = output(posting("still-observed"), run="old")
    empty = output(run="empty", at=datetime(2026, 9, 7, 12, tzinfo=UTC))
    cohort = input_union.build_input_union((old, empty), criteria(), mapper)
    assert len(cohort.jobs) == 1
    assert len(cohort.input_union.input_batches) == 2
    assert any(r.record_count == 0 for r in cohort.input_union.input_batches)


def test_future_only_observations_are_reported_not_selected_or_used_as_absence(mapper):
    future = output(
        posting("future", collected_at="2026-09-09T00:00:00Z"), run="future"
    )
    cohort = input_union.build_input_union((future,), criteria(), mapper)
    assert cohort.status == "EMPTY" and cohort.input_count == 0
    assert cohort.input_union.after_as_of_record_count == 1
    assert cohort.input_union.sources_without_as_of_observations == ("SARAMIN",)
    assert cohort.input_union.observations[0].disposition == "AFTER_AS_OF"


def test_future_closed_does_not_override_observed_state_at_fixed_as_of(mapper):
    old = output(posting("same"), run="old")
    future = output(
        posting("same", posting_status="CLOSED", collected_at="2026-09-09T00:00:00Z"),
        run="future",
    )
    cohort = input_union.build_input_union((future, old), criteria(), mapper)
    assert len(cohort.jobs) == 1
    assert cohort.input_union.after_as_of_record_count == 1


def test_output_order_and_repeated_delivery_preserve_complete_identity(mapper):
    one = output(posting("one"), run="one")
    two = output(posting("two"), run="two")
    first = input_union.build_input_union((one, two), criteria(), mapper)
    assert input_union.build_input_union((two, one, one), criteria(), mapper) == first
    changed = output(posting("two"), run="two", manifest_sha256="f" * 64)
    assert (
        input_union.build_input_union((one, changed), criteria(), mapper).cohort_id
        != first.cohort_id
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"collection_issues": ("DETAIL_COLLECTION_FAILED",)},
        {"collection_issues": ("UNBOUND_LEGACY_MANIFEST",)},
        {"manifest_sha256": "invalid"},
        {"source_site": "WORKNET"},
    ],
)
def test_invalid_or_incomplete_input_fails_closed(mapper, changes):
    with pytest.raises(ValueError):
        input_union.build_input_union(
            (output(posting(), **changes),), criteria(), mapper
        )


def test_mixed_posting_dates_block_only_date_constrained_union(mapper):
    value = output(posting(), mixed_date_semantics=True)
    assert len(input_union.build_input_union((value,), criteria(), mapper).jobs) == 1
    with pytest.raises(ValueError):
        input_union.build_input_union(
            (value,), criteria(posted_from="2026-09-01T00:00:00Z"), mapper
        )


@pytest.mark.parametrize(
    "constant,limit", [("MAX_INPUT_RECORDS", 1), ("MAX_INPUT_BYTES", 10)]
)
def test_union_bounds_checked_before_classification(
    mapper, monkeypatch, constant, limit
):
    monkeypatch.setattr(input_union, constant, limit)
    with pytest.raises(ValueError, match="limit"):
        input_union.build_input_union(
            (output(posting("one"), posting("two")),), criteria(), mapper
        )
