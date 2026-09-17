import pytest
from job.cohort import build_cohort
from job.collector.technology import extract_technology_mentions
from job.demand import DemandSnapshot, aggregate_demand
from pydantic import ValidationError
from test_job_cohort import batch, criteria, posting


def test_distinct_counts_union_ratios_and_deterministic_ranks_match_hand_counts():
    cohort = build_cohort(
        batch(
            posting(required=("Java",), preferred=("Java", "Redis"), general=("Java",)),
            posting("job-2", required=("Python",), preferred=("Redis",)),
            posting(
                "job-3", required=("Java", "Python"), required_text="Java 또는 Python"
            ),
            posting("excluded", required=()),
        ),
        criteria(),
    )
    demand = aggregate_demand(cohort)
    technologies = {item.tech_id: item for item in demand.technologies}
    assert demand.denominator == 3
    assert demand.review_count == 1
    assert technologies["java"].required_count == 2
    assert technologies["java"].preferred_count == 1
    assert technologies["java"].general_count == 1
    assert technologies["java"].total_count == 2
    assert technologies["java"].total_ratio == 2 / 3
    assert technologies["redis"].preferred_ratio == 2 / 3
    assert technologies["redis"].preferred_rank == 1
    assert technologies["java"].required_rank == 1
    assert technologies["java"].total_rank == technologies["java"].rank
    assert [(item.tech_id, item.rank) for item in demand.technologies] == [
        ("java", 1),
        ("python", 2),
        ("redis", 3),
    ]
    assert all(item.total_count <= demand.denominator for item in demand.technologies)
    assert demand.cohort_id == cohort.cohort_id
    assert demand.criteria == cohort.criteria
    assert DemandSnapshot.model_validate_json(demand.model_dump_json()) == demand


def test_empty_and_insufficient_data_are_observed_states_not_ready_zero_values():
    empty = aggregate_demand(build_cohort(batch(), criteria()))
    assert empty.status == "EMPTY"
    assert empty.denominator == 0
    assert empty.technologies == ()
    insufficient = aggregate_demand(
        build_cohort(batch(posting()), criteria(min_jobs=2))
    )
    assert insufficient.status == "INSUFFICIENT_DATA"
    assert insufficient.denominator == 1
    assert insufficient.technologies[0].required_ratio == 1.0


def test_demand_deserialization_rejects_a_forged_denominator_or_ready_empty_status():
    actual = aggregate_demand(build_cohort(batch(posting()), criteria()))
    payload = actual.model_dump(mode="json")
    payload["technologies"][0]["total_count"] = 2
    with pytest.raises(ValidationError, match="distinct"):
        DemandSnapshot.model_validate(payload)
    payload = aggregate_demand(build_cohort(batch(), criteria())).model_dump(
        mode="json"
    )
    payload["status"] = "READY"
    with pytest.raises(ValidationError, match="status"):
        DemandSnapshot.model_validate(payload)


def test_decorated_real_site_sections_keep_preferred_out_of_required_demand():
    body = "📋 자격요건\n- Java 서비스 개발\n📋 우대사항\n- Redis 검색 기능 경험"
    record = posting(
        description_text=body,
        technology_mentions=extract_technology_mentions("백엔드 개발자", body),
    )
    cohort = build_cohort(batch(record), criteria(min_jobs=2))
    demand = aggregate_demand(cohort)
    assert cohort.jobs[0].required_clauses == (("java",),)
    assert cohort.jobs[0].preferred_tech_ids == ("redis",)
    rows = {item.tech_id: item for item in demand.technologies}
    assert demand.status == "INSUFFICIENT_DATA"
    assert demand.denominator == 1
    assert rows["java"].required_count == rows["redis"].preferred_count == 1
    assert rows["redis"].required_count == 0
    assert rows["redis"].total_count == 1
