"""v8 next-skill impact is about resolved clauses, never full-job eligibility."""

from test_job_cohort import batch, criteria, posting

from job.cohort import build_cohort
from job.requirements import (
    RequirementKind,
    UnresolvedReason,
    UnresolvedRequirement,
)
from recommendation.engine import (
    active_condition_impact,
    condition_impact,
)


def test_partial_conditional_job_counts_both_kinds_without_full_match():
    cohort = build_cohort(
        batch(
            posting("partial", required=("Docker",), preferred=("Docker",)),
            posting("other", required=("Redis",)),
        ),
        criteria(),
    )
    by_id = {job.job_id: job for job in cohort.matching_jobs}
    job = by_id["partial"]
    redis_clause = by_id["other"].requirements.required[0]
    unresolved = UnresolvedRequirement(
        requirement_kind=RequirementKind.REQUIRED,
        reason=UnresolvedReason.LOGIC_UNSUPPORTED,
        known_tech_ids=("docker",),
        evidence=job.requirements.required[0].evidence_refs[0],
    )
    requirements = job.requirements.model_copy(
        update={
            "required": (*job.requirements.required, redis_clause),
            "unresolved": (unresolved,),
        }
    )
    conditional = job.model_copy(
        update={
            "requirements": requirements,
            "eligibility": "CONDITIONAL",
            "eligibility_reasons": ("CAREER_UNCONFIRMED",),
            "strict_match_eligible": False,
            "strict_review_reasons": ("CAREER_UNCONFIRMED",),
        }
    )
    impact = condition_impact(
        (conditional,), frozenset(), {}, "docker", cohort.cohort_id
    )

    assert impact.required_job_ids == ("partial",)
    assert impact.preferred_job_ids == ("partial",)
    assert impact.affected_job_ids == ("partial",)
    assert (impact.required_count, impact.preferred_count, impact.affected_count) == (
        1,
        1,
        1,
    )


def test_or_clause_still_counts_technology_mentioned_as_an_option():
    cohort = build_cohort(
        batch(
            posting(
                "or-job",
                required=("Docker", "Redis"),
                required_text="Docker 또는 Redis",
            )
        ),
        criteria(),
    )
    impact = condition_impact(
        cohort.matching_jobs,
        frozenset({"redis"}),
        {"redis": "L1"},
        "docker",
        cohort.cohort_id,
    )
    assert impact.required_job_ids == ("or-job",)
    assert impact.affected_count == 1


def test_l2_requirement_counts_as_relevant_without_claiming_level_fulfillment():
    cohort = build_cohort(
        batch(
            posting(
                "senior",
                required=("Docker",),
                required_text="Docker 고급 개발 경험",
            )
        ),
        criteria(),
    )
    impact = condition_impact(
        cohort.matching_jobs, frozenset(), {}, "docker", cohort.cohort_id
    )
    assert impact.required_job_ids == ("senior",)
    assert impact.required_count == 1


def test_held_without_personal_level_keeps_required_and_preferred_mentions():
    cohort = build_cohort(
        batch(posting("job", required=("Docker",), preferred=("Docker",))),
        criteria(),
    )
    impact = condition_impact(
        cohort.matching_jobs,
        frozenset({"docker"}),
        {},
        "docker",
        cohort.cohort_id,
    )
    assert impact.required_count == 1
    assert impact.preferred_count == 1
    assert impact.affected_count == 1


def test_live_gate_filters_both_counts_and_lists_without_mutating_snapshot():
    cohort = build_cohort(
        batch(
            posting("a", required=("Docker",), preferred=("Docker",)),
            posting("b", preferred=("Docker",), required=()),
        ),
        criteria(),
    )
    impact = condition_impact(
        cohort.matching_jobs, frozenset(), {}, "docker", cohort.cohort_id
    )
    active = active_condition_impact(impact, {"b"})
    assert impact.affected_count == 2
    assert active.required_job_ids == ()
    assert active.preferred_job_ids == ("b",)
    assert active.affected_job_ids == ("b",)
    assert active.affected_count == 1
