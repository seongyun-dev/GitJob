"""Deterministic materialization from the already parsed verified union."""

import json
import sys

import pytest
from test_job_cohort import criteria, posting
from test_job_input_union import output

from job.demand import aggregate_demand
from job.input_union import build_prepared_input_union, prepare_input_union
from job.projection import (
    aggregate_projection_demand,
    build_projection_cohort,
    canonical_hash,
    materialize_job_projection,
)
from registry.mapper import RegistryMapper
from worker.api import default_registry
from worker.job_projection_backfill import main as backfill_main
from worker.job_projection_shadow import selector_matrix, validate_selectors


@pytest.fixture(autouse=True)
def _file_registry(monkeypatch):
    monkeypatch.setenv("C_REGISTRY_BACKEND", "file")


def _prepared(*records):
    mapper = RegistryMapper(default_registry())
    return prepare_input_union((output(*records),), criteria(), mapper)


def test_projection_is_deterministic_and_contains_no_raw_description():
    prepared = _prepared(
        posting(
            "backend-1",
            title="백엔드 개발자",
            region="서울특별시 강남구",
            career_level="신입·경력",
            required=("Java",),
        )
    )
    first = materialize_job_projection(prepared)
    second = materialize_job_projection(prepared)
    assert first == second
    assert first.projection_version_id.startswith("jp-")
    assert first.jobs[0].job_key == "SARAMIN:backend-1"
    assert first.jobs[0].role_codes == ("BACKEND",)
    assert first.jobs[0].region_codes == ("SEOUL",)
    assert first.jobs[0].career_codes == ("ENTRY", "EXPERIENCED")
    assert first.jobs[0].required_tech_ids == ("java",)
    assert "description_text" not in first.facts[0].payload["record"]
    assert first.facts[0].payload_hash == canonical_hash(first.facts[0].payload)
    assert first.build_stats["active_job_count"] == 1
    assert first.build_stats["closed_job_count"] == 0
    assert first.build_stats["unknown_status_job_count"] == 0
    assert first.build_stats["source_job_counts"] == {"SARAMIN": 1}
    assert first.build_stats["source_input_states"] == {"SARAMIN": "COMPLETE"}


def test_projection_preserves_unknown_and_conflict_quality_without_dropping_job():
    one = output(posting("same", region="원격", career_level="협의"), run="one")
    two = output(
        posting("same", region="원격", career_level="우대", required=("Docker",)),
        run="two",
    )
    prepared = prepare_input_union(
        (one, two), criteria(), RegistryMapper(default_registry())
    )
    projection = materialize_job_projection(prepared)
    assert len(projection.jobs) == 1
    assert projection.jobs[0].region_state == "UNKNOWN"
    assert projection.jobs[0].career_state == "AMBIGUOUS"
    assert "SOURCE_RECORD_CONFLICT" in projection.jobs[0].quality_flags
    assert len(projection.facts) == 2

    restored = build_projection_cohort(projection, criteria())

    assert restored.input_count == 1
    assert restored.duplicate_count == 0
    assert restored.matching_jobs == ()


def test_projection_identity_changes_with_verified_input_signature():
    original = materialize_job_projection(_prepared(posting("one")))
    changed = materialize_job_projection(
        _prepared(posting("one", collected_at="2026-09-07T01:00:00Z"))
    )
    assert original.input_signature != changed.input_signature
    assert original.projection_version_id != changed.projection_version_id


def test_backfill_dry_run_performs_no_database_write(monkeypatch, capsys):
    projection = materialize_job_projection(_prepared(posting("dry-run")))
    monkeypatch.setattr(
        "worker.job_projection_backfill.build_projection", lambda _path: projection
    )
    monkeypatch.setattr(
        "worker.job_projection_backfill.ComputeStore",
        lambda _dsn: pytest.fail("dry-run must not construct a database store"),
    )
    monkeypatch.setattr(
        sys, "argv", ["job_projection_backfill", "--dry-run", "--config", "input.json"]
    )

    backfill_main()

    result = json.loads(capsys.readouterr().out)
    assert result["published"] is False
    assert result["projection_version_id"] == projection.projection_version_id


@pytest.mark.parametrize(
    "selected",
    [
        criteria(),
        criteria(regions=("서울",)),
        criteria(regions=("부산",)),
        criteria(career_levels=("신입",)),
        criteria(career_levels=("경력",)),
        criteria(regions=("원격",), career_levels=("협의",)),
        criteria(target_role="FRONTEND"),
        criteria(min_jobs=20),
        criteria(target_role=None, purpose="CURRENT_MARKET", sources=("SARAMIN",)),
    ],
    ids=[
        "all",
        "region-match",
        "region-empty",
        "career-entry",
        "career-experienced",
        "unknown-filters",
        "other-role",
        "insufficient",
        "current-market",
    ],
)
def test_projection_demand_matches_legacy_selector_semantics(selected):
    records = (
        posting(
            "active",
            required=("Java",),
            preferred=("Redis",),
            general=("Docker",),
        ),
        posting(
            "unknown",
            region="원격",
            career_level="협의",
            posting_status="UNKNOWN",
            required=("Python",),
        ),
        posting(
            "frontend",
            title="프론트엔드 개발자",
            raw_job_category="FRONTEND",
            required=("React",),
        ),
        posting("closed", posting_status="CLOSED", required=("Kotlin",)),
        posting(
            "expired",
            deadline="2026-09-08T00:00:00Z",
            required=("Go",),
        ),
        posting(
            "blocked",
            body_status="BLOCKED",
            description_text=None,
            technology_mentions=(),
        ),
    )
    prepared = _prepared(*records)
    legacy_cohort = build_prepared_input_union(prepared, selected)
    legacy = aggregate_demand(legacy_cohort)
    projected = aggregate_projection_demand(
        materialize_job_projection(prepared), selected
    )

    if selected.purpose.value == "ACTIVE_MATCHING":
        assert projected.selected_job_ids == tuple(
            sorted(job.job_id for job in legacy_cohort.matching_jobs or ())
        )
        assert tuple(
            sorted(job.job_id for job in projected.cohort.matching_jobs or ())
        ) == projected.selected_job_ids
        assert all(
            job.requirements.source_record_id == job.source_record_id
            for job in projected.cohort.matching_jobs or ()
        )
    assert projected.snapshot.status == legacy.status
    assert projected.snapshot.denominator == legacy.denominator
    assert projected.snapshot.matching_count == legacy.matching_count
    assert projected.snapshot.input_count == legacy.input_count
    assert projected.snapshot.duplicate_count == legacy.duplicate_count
    assert projected.snapshot.excluded_count == legacy.excluded_count
    assert projected.snapshot.review_count == legacy.review_count
    assert [row.model_dump() for row in projected.snapshot.technologies] == [
        row.model_dump() for row in legacy.technologies
    ]


def test_fixed_100_selector_shadow_gate_has_no_unexpected_mismatch():
    prepared = _prepared(
        posting("backend", required=("Java",)),
        posting(
            "frontend",
            title="프론트엔드 개발자",
            raw_job_category="FRONTEND",
            required=("React",),
        ),
        posting("unknown", region="원격", career_level="협의", required=("Python",)),
    )
    projection = materialize_job_projection(prepared)
    selectors = selector_matrix(criteria().as_of, market_sources=("SARAMIN",))

    assert len(selectors) == 100
    assert validate_selectors(prepared, projection, selectors) == []
