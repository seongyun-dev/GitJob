"""Current market technology demand over every valid posting, not a role cohort.

The market snapshot answers "what do the postings we hold ask for right now".
It is deliberately not the matching population: a posting that matches no
supported role still competes for the same technologies, so it stays in the
denominator. It is also not a period, so it never promises posting-date
semantics.
"""

import pytest
from job.cohort import CohortCriteria, CohortPurpose, build_cohort
from job.demand import DemandSnapshot, aggregate_demand
from pydantic import ValidationError
from test_job_cohort import batch, posting


def market(**changes):
    return CohortCriteria.model_validate(
        {"purpose": "CURRENT_MARKET", "as_of": "2026-09-08T00:00:00Z", **changes}
    )


def backend(**changes):
    return CohortCriteria.model_validate(
        {
            "target_role": "BACKEND_ENGINEER",
            "as_of": "2026-09-08T00:00:00Z",
            **changes,
        }
    )


def tech(demand, tech_id):
    return next(row for row in demand.technologies if row.tech_id == tech_id)


# --- criteria contract -------------------------------------------------------


def test_market_criteria_reject_a_target_role():
    """A role would make it a role cohort, and the lineage would then lie."""
    with pytest.raises(ValidationError, match="CURRENT_MARKET"):
        market(target_role="BACKEND_ENGINEER")


def test_non_market_criteria_still_require_a_target_role():
    with pytest.raises(ValidationError, match="target_role"):
        CohortCriteria.model_validate({"as_of": "2026-09-08T00:00:00Z"})


def test_market_criteria_reject_a_posting_period():
    """A current snapshot is not a period and must not imply posting dates."""
    with pytest.raises(ValidationError, match="CURRENT_MARKET"):
        market(posted_from="2026-08-01T00:00:00Z", posted_to="2026-09-01T00:00:00Z")


def test_market_criteria_omit_role_from_stored_json():
    """Existing snapshots keep their byte shape; the new field is additive."""
    assert "target_role" not in market().model_dump(mode="json")
    assert backend().model_dump(mode="json")["target_role"] == "BACKEND"


# --- population --------------------------------------------------------------


def test_market_population_keeps_postings_that_match_no_role():
    """The whole point: role mismatch must not shrink the market denominator."""
    inputs = batch(
        posting("kept", required=("Java",)),
        posting(
            "other-role",
            required=("Java",),
            raw_job_category="디자인",
            title="그래픽 디자이너",
        ),
    )
    role_cohort = build_cohort(inputs, backend())
    market_cohort = build_cohort(inputs, market())

    assert any("ROLE_NOT_MATCHED" in row.reasons for row in role_cohort.exclusions)
    assert not any(
        "ROLE_NOT_MATCHED" in row.reasons for row in market_cohort.exclusions
    )
    assert aggregate_demand(market_cohort).denominator == 2


def test_market_denominator_counts_every_valid_distinct_posting():
    """Postings with no resolvable requirement stay in the denominator."""
    inputs = batch(
        posting("with-tech", required=("Java",)),
        posting("no-tech", required=()),
        posting(
            "unavailable",
            required=(),
            body_status="IMAGE_ONLY",
            raw_artifact_uri="hdfs:///gitjob/raw/jobs/saramin/unavailable.html",
        ),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    assert demand.denominator == 3
    assert tech(demand, "java").total_count == 1
    assert tech(demand, "java").total_ratio == 1 / 3


def test_market_counts_each_posting_once_per_technology():
    """Repeating a technology in one posting is still one posting."""
    inputs = batch(
        posting("dup", required=("Java",), preferred=("Java",)),
        posting("solo", required=("Java",)),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    assert tech(demand, "java").total_count == 2
    assert tech(demand, "java").total_count <= demand.denominator


# --- technology inclusion rule ----------------------------------------------


def test_market_includes_required_and_preferred_only():
    """MENTIONED is a sighting, not a requirement, so it never becomes demand."""
    inputs = batch(
        posting("req", required=("Java",)),
        posting("pref", required=(), preferred=("Python",)),
        posting("mentioned", required=(), general=("Redis",)),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    counted = {row.tech_id for row in demand.technologies}
    assert {"java", "python"} <= counted
    assert "redis" not in counted
    assert all(row.general_count == 0 for row in demand.technologies)


def test_market_excludes_technologies_the_registry_cannot_resolve():
    """An unmapped mention has no tech_id, so it cannot be ranked."""
    demand = aggregate_demand(
        build_cohort(
            batch(posting("unknown", required=("존재하지않는기술",))), market()
        )
    )
    assert demand.denominator == 1
    assert demand.technologies == ()


def test_market_separates_required_and_preferred_counts():
    inputs = batch(
        posting("a", required=("Java",), preferred=("Python",)),
        posting("b", required=("Python",)),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    python = tech(demand, "python")
    assert (python.required_count, python.preferred_count) == (1, 1)
    assert python.total_count == 2


# --- scope filters leave the market, quality gates do not -------------------


def four_sites():
    return batch(
        posting("jk", required=("Java",), source_site="JOBKOREA"),
        posting("sr", required=("Java",), source_site="SARAMIN"),
        posting("wn", required=("Java",), source_site="WORKNET"),
        posting("gj", required=("Java",), source_site="GAMEJOB"),
        posting("cr", required=("Java",), source_site="CAREER"),
    )


def test_official_two_sources_leave_the_other_sites_out_of_the_market():
    """A source we do not serve is not part of our market, denominator included."""
    demand = aggregate_demand(
        build_cohort(four_sites(), market(sources=["JOBKOREA", "SARAMIN"]))
    )
    assert demand.denominator == 2
    assert tech(demand, "java").total_count == 2
    assert tech(demand, "java").total_ratio == 1.0


def test_unfiltered_market_still_counts_every_source():
    demand = aggregate_demand(build_cohort(four_sites(), market()))
    assert demand.denominator == 5


def test_region_and_career_filters_also_narrow_the_market():
    """Same rule as sources: the caller's declared scope defines the market."""
    inputs = batch(
        posting("seoul", required=("Java",), region="서울"),
        posting("busan", required=("Java",), region="부산"),
    )
    demand = aggregate_demand(build_cohort(inputs, market(regions=["서울"])))
    assert demand.denominator == 1


def test_observations_after_the_cutoff_are_not_in_the_market():
    """A posting we had not observed yet cannot be in a snapshot of right now."""
    inputs = batch(
        posting("seen", required=("Java",)),
        posting("later", required=("Java",), collected_at="2026-09-09T00:00:00Z"),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    assert demand.denominator == 1


def test_quality_exclusions_stay_in_the_market_denominator():
    """Unreadable or unresolved postings are still postings in this market."""
    inputs = batch(
        posting("ok", required=("Java",)),
        posting("no-tech", required=()),
        posting(
            "no-body",
            required=(),
            body_status="IMAGE_ONLY",
            raw_artifact_uri="hdfs:///gitjob/raw/jobs/saramin/no-body.html",
        ),
        posting("unknown-status", required=("Java",), posting_status="UNKNOWN"),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    assert demand.denominator == 4
    assert tech(demand, "java").total_count == 2


def test_market_never_produces_a_role_exclusion():
    """target_role is absent, so ROLE_NOT_MATCHED cannot narrow the market."""
    inputs = batch(
        posting("dev", required=("Java",)),
        posting(
            "designer",
            required=("Java",),
            raw_job_category="디자인",
            title="그래픽 디자이너",
        ),
    )
    cohort = build_cohort(inputs, market())
    assert not any("ROLE_NOT_MATCHED" in row.reasons for row in cohort.exclusions)
    assert aggregate_demand(cohort).denominator == 2


def test_cross_source_duplicates_stay_independent_postings():
    """Same company and title on two sites are two postings until canonicalized."""
    inputs = batch(
        posting(
            "jk-1",
            required=("Java",),
            source_site="JOBKOREA",
            company_name="같은회사",
            title="백엔드 개발자",
        ),
        posting(
            "sr-1",
            required=("Java",),
            source_site="SARAMIN",
            company_name="같은회사",
            title="백엔드 개발자",
        ),
    )
    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )
    assert demand.denominator == 2
    assert tech(demand, "java").total_count == 2


# --- isolation from the other purposes --------------------------------------


def test_market_snapshot_is_rejected_by_the_monthly_trend():
    from pathlib import Path

    from registry.contracts import load_registry
    from trend.contracts import TrendStatus
    from trend.job import job_trend

    registry = load_registry(
        Path(__file__).resolve().parents[1]
        / "registry/data/technology_registry_v1.json",
        repository_root=Path(__file__).resolve().parents[2],
    )
    demand = aggregate_demand(build_cohort(batch(posting()), market()))
    result = job_trend("java", (demand,), registry, periods=("2026-08",))
    assert result.status is TrendStatus.FAILED
    assert result.reasons == ("MONTHLY_DEMAND_COHORT_REQUIRED",)


def test_market_snapshot_is_rejected_by_recommendation():
    """A market aggregate is not a person's comparison set."""
    from recommendation.engine import build_recommendations

    cohort = build_cohort(batch(posting()), market())
    with pytest.raises(ValueError, match="ACTIVE_MATCHING_COHORT_REQUIRED"):
        build_recommendations(cohort, None, user_id="u-1", analysis_id="a-1")


def test_market_and_role_cohorts_get_different_ids():
    inputs = batch(posting())
    assert (
        build_cohort(inputs, market()).cohort_id
        != build_cohort(inputs, backend()).cohort_id
    )


def test_market_demand_roundtrips_through_json():
    demand = aggregate_demand(build_cohort(batch(posting()), market()))
    restored = DemandSnapshot.model_validate_json(demand.model_dump_json())
    assert restored == demand
    assert restored.criteria.purpose is CohortPurpose.CURRENT_MARKET
