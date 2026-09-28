"""Deterministic materialization from the already parsed verified union."""

import json
import sys

import pytest
from test_job_cohort import criteria, posting
from test_job_input_union import output

import job.projection as projection_module
import worker.job_projection_shadow as shadow_module
from job.cohort import CohortPurpose
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
from worker.job_projection_shadow import (
    selector_matrix,
    validate_persisted_selectors,
    validate_selectors,
)


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
    assert len(first.market_jobs) == len(first.jobs)
    assert first.build_stats["market_job_count"] == len(first.jobs)
    assert first.build_stats["market_policy_version"] == "job-projection-market/v2"


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


def test_projection_candidate_safety_gate_fails_without_truncating(monkeypatch):
    saramin = posting(
        "shared-s",
        company_name="Example",
        title="백엔드 개발자",
    )
    jobkorea = posting(
        "shared-j",
        source_site="JOBKOREA",
        company_name="Example",
        title="백엔드 개발자",
    )
    prepared = prepare_input_union(
        (
            output(saramin, run="candidate-s"),
            output(jobkorea, source="JOBKOREA", run="candidate-j"),
        ),
        criteria(),
        RegistryMapper(default_registry()),
    )
    monkeypatch.setattr(projection_module, "MAX_MARKET_CANDIDATES_BASE", 0)
    monkeypatch.setattr(projection_module, "MAX_MARKET_CANDIDATES_PER_JOB", 0)

    with pytest.raises(ValueError, match="candidate total"):
        materialize_job_projection(prepared)


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
    assert sum(
        item.purpose is CohortPurpose.ACTIVE_MATCHING for item in selectors
    ) == 80
    assert sum(
        item.purpose is CohortPurpose.CURRENT_MARKET for item in selectors
    ) == 20
    assert any(item.regions == ("전국",) for item in selectors)
    assert any(item.regions == ("원격",) for item in selectors)
    assert any(item.regions == ("경기", "서울") for item in selectors)
    assert any(item.career_levels == ("경력", "신입") for item in selectors)
    assert any(item.career_levels == ("협의",) for item in selectors)
    assert validate_selectors(prepared, projection, selectors) == []


def test_persisted_selector_gate_resumes_completed_results():
    projection = materialize_job_projection(_prepared(posting("resume")))
    selectors = selector_matrix(criteria().as_of)[:2]

    class Store:
        def __init__(self):
            self.demand_calls = []

        def demand(self, selected, *, projection_version_id):
            self.demand_calls.append(selected)
            return aggregate_projection_demand(projection, selected)

        def summary(self, selected, *, projection_version_id):
            return aggregate_projection_demand(projection, selected).snapshot

        def selected_job_keys(self, selected, *, projection_version_id):
            return aggregate_projection_demand(projection, selected).selected_job_ids

    store = Store()
    completed = {
        "0": {
            "criteria": selectors[0].model_dump(mode="json"),
            "fields": [],
        }
    }
    checkpoints = []

    assert validate_persisted_selectors(
        store,
        projection.projection_version_id,
        selectors,
        completed=completed,
        on_result=lambda index, results: checkpoints.append((index, len(results))),
    ) == []
    assert store.demand_calls == [selectors[1]]
    assert checkpoints == [(1, 2)]

    completed["0"]["fields"] = ["denominator"]
    resumed = validate_persisted_selectors(
        store,
        projection.projection_version_id,
        selectors[:1],
        completed=completed,
    )
    assert resumed[0]["fields"] == ("denominator",)


def test_persisted_selector_gate_rejects_foreign_checkpoint(
    monkeypatch, tmp_path
):
    projection_id = "jp-" + "a" * 64
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "projection_version_id": "jp-" + "b" * 64,
                "selector_hash": "wrong",
                "completed": {},
            }
        ),
        encoding="utf-8",
    )

    class Store:
        def head(self):
            return {
                "projection_version_id": projection_id,
                "observed_at": criteria().as_of,
            }

    monkeypatch.setenv("C_COMPUTE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(shadow_module, "JobProjectionStore", lambda _dsn: Store())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "job_projection_shadow",
            "--persisted",
            "--projection-version-id",
            projection_id,
            "--checkpoint",
            str(checkpoint),
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        shadow_module.main()


def test_persisted_selector_gate_rejects_head_change_during_validation(
    monkeypatch, tmp_path
):
    projection_id = "jp-" + "a" * 64
    replacement_id = "jp-" + "b" * 64

    class Store:
        def __init__(self):
            self.head_calls = 0

        def head(self):
            self.head_calls += 1
            return {
                "projection_version_id": (
                    projection_id if self.head_calls == 1 else replacement_id
                ),
                "observed_at": criteria().as_of,
            }

    monkeypatch.setenv("C_COMPUTE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(shadow_module, "JobProjectionStore", lambda _dsn: Store())
    monkeypatch.setattr(
        shadow_module,
        "validate_persisted_selectors",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "job_projection_shadow",
            "--persisted",
            "--projection-version-id",
            projection_id,
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        shadow_module.main()
