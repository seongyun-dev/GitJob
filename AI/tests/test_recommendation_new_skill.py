"""S15P21E102-354: next-skill recommendation excludes personally held L1+ technologies.

The product rule this file pins down is "a *new* technology I have not personally
used yet", not "level up something I already use". So eligibility is decided by
the personal level alone:

* ``personalLevel >= L1`` (L1/L2/L3) -- already used, never a candidate, even when
  the posting requires a higher level than the user currently holds.
* ``personalLevel == L0``, no personal assessment at all, or Evidence ``UNKNOWN`` --
  eligible.

Evidence semantics are deliberately untouched: a technology that is UNKNOWN in the
Evidence layer stays UNKNOWN in the snapshot's gap. Only candidate eligibility moved.

Trend-based near-tie ordering is out of scope here (S15P21E102-355); this file only
pins the Top3 *set* and its ``increased_count`` DESC order.
"""

from evidence_fixtures import proof_payload
from test_evidence_consumption import legacy_analysis_payload
from test_job_cohort import batch, criteria, posting

from job.cohort import build_cohort
from recommendation.engine import (
    RecommendationSnapshot,
    build_recommendations,
    list_related_jobs,
)
from recommendation.evidence import EvidenceAnalysis

V7 = "c-recommendation/lexicographic/v7"


def held_technology(tech_id: str, *, personal_level: str | None = None) -> dict:
    """A proof-backed observation of `tech_id`, optionally with a personal level."""
    proofs = [
        proof_payload(kind, tech_id=tech_id, suffix=tech_id)
        for kind in ("DIRECT_DEPENDENCY", "PARTICIPATION", "IMPLEMENTATION")
    ]
    item = {
        "tech_id": tech_id,
        "fact_ids": [proof["fact_id"] for proof in proofs],
        "evidence_level": "L2",
        "direct_dependency": True,
        "implementation_present": True,
        "user_participation": True,
        "implemented_by": "SELF",
        "attribution_status": "COMPLETE",
        "source_refs": [f"https://github.com/example/repo/blob/aaa/{tech_id}"],
        "proofs": proofs,
    }
    if personal_level is not None:
        item["personal_level"] = personal_level
    return item


def make_analysis(
    technologies: list[dict],
    evaluated: list[str],
    *,
    registry_version: str,
    coverage_complete: bool = True,
) -> EvidenceAnalysis:
    payload = legacy_analysis_payload()
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["registry_version"] = registry_version
    repository = payload["repositories"][0]
    repository["technologies"] = technologies
    repository["evaluated_tech_ids"] = sorted(evaluated)
    repository["coverage_complete"] = coverage_complete
    return EvidenceAnalysis.model_validate(payload)


def cohort_of(*postings):
    return build_cohort(batch(*postings), criteria())


def recommend(cohort, analysis):
    return build_recommendations(
        cohort, analysis, user_id="user-1", analysis_id="analysis-1"
    )


def scenario(
    *,
    postings,
    technologies,
    evaluated,
    coverage_complete=True,
):
    cohort = cohort_of(*postings)
    analysis = make_analysis(
        technologies,
        evaluated,
        registry_version=cohort.registry_version,
        coverage_complete=coverage_complete,
    )
    return recommend(cohort, analysis)


def candidate_ids(result) -> list[str]:
    return [item.tech_id for item in result.candidates]


# --------------------------------------------------------------------------
# CASE A / B -- personally held L1+ is never a next-skill candidate
# --------------------------------------------------------------------------


def test_case_a_personal_level_l2_is_excluded():
    result = scenario(
        postings=[posting("python-job", required=("Python",))],
        technologies=[held_technology("python", personal_level="L2")],
        evaluated=["python"],
    )

    assert "python" not in candidate_ids(result)


def test_case_b_personal_level_l1_is_excluded():
    """CASE B. `spring-boot` stands in for Django: this registry fixture has no
    Django alias, and the rule under test is the L1 exclusion, not the name."""
    result = scenario(
        postings=[posting("framework-job", required=("Spring Boot",))],
        technologies=[held_technology("spring-boot", personal_level="L1")],
        evaluated=["spring-boot"],
    )

    assert "spring-boot" not in candidate_ids(result)


def test_case_b2_l1_held_stays_excluded_even_when_posting_requires_more():
    """Level-up recommendations are out of scope for this issue."""
    result = scenario(
        postings=[
            posting(
                "framework-senior",
                required=("Spring Boot",),
                required_text="Spring Boot 고급 개발 경험",
            )
        ],
        technologies=[held_technology("spring-boot", personal_level="L1")],
        evaluated=["spring-boot"],
    )

    assert "spring-boot" not in candidate_ids(result)


# --------------------------------------------------------------------------
# CASE C / D -- not personally used yet is eligible
# --------------------------------------------------------------------------


def test_case_c_unknown_evidence_technology_is_a_candidate():
    result = scenario(
        postings=[posting("docker-job", required=("Docker",))],
        technologies=[held_technology("java", personal_level="L2")],
        evaluated=["java"],
    )

    assert "docker" in candidate_ids(result)


def test_case_d_repository_level_without_personal_level_is_a_candidate():
    """CASE D. Observed in the repository (L2) but no personal attribution, so it
    is still a technology the user has not been shown to use. `react` stands in
    for Vue, which this registry fixture does not alias."""
    result = scenario(
        postings=[posting("react-job", required=("React",))],
        technologies=[held_technology("react")],
        evaluated=["react"],
    )

    assert "react" in candidate_ids(result)


def test_case_e_recommending_unknown_does_not_change_evidence_meaning():
    result = scenario(
        postings=[posting("docker-job", required=("Docker",))],
        technologies=[held_technology("java", personal_level="L2")],
        evaluated=["java"],
    )

    assert "docker" in candidate_ids(result)
    # Evidence layer keeps saying "not evaluated", not "not held".
    assert "docker" in result.gap.unknown_tech_ids
    assert "docker" not in result.gap.missing_tech_ids


# --------------------------------------------------------------------------
# CASE F / I -- Top3 set and order come from increased_count
# --------------------------------------------------------------------------


def top3_scenario():
    """docker +3, redis +2, postgresql +1 -- a strict increased_count ordering."""
    postings = [
        *[posting(f"docker-{i}", required=("Docker",)) for i in range(3)],
        *[posting(f"redis-{i}", required=("Redis",)) for i in range(2)],
        posting("pg-0", required=("PostgreSQL",)),
    ]
    return scenario(
        postings=postings,
        technologies=[held_technology("java", personal_level="L2")],
        evaluated=["java"],
    )


def test_case_f_top3_is_ordered_by_increased_count_desc():
    result = top3_scenario()

    assert candidate_ids(result) == ["docker", "redis", "postgresql"]
    assert [item.what_if.increased_count for item in result.candidates] == [3, 2, 1]
    assert [item.rank for item in result.candidates] == [1, 2, 3]


def test_case_i_at_most_three_candidates_are_returned():
    postings = [
        *[posting(f"docker-{i}", required=("Docker",)) for i in range(4)],
        *[posting(f"redis-{i}", required=("Redis",)) for i in range(3)],
        *[posting(f"pg-{i}", required=("PostgreSQL",)) for i in range(2)],
        posting("ts-0", required=("TypeScript",)),
    ]
    result = scenario(
        postings=postings,
        technologies=[held_technology("java", personal_level="L2")],
        evaluated=["java"],
    )

    assert candidate_ids(result) == ["docker", "redis", "postgresql"]
    assert "typescript" not in candidate_ids(result)


# --------------------------------------------------------------------------
# CASE K -- candidates survive incomplete coverage
# --------------------------------------------------------------------------


def test_case_k_incomplete_coverage_keeps_candidates_and_reports_partial():
    result = scenario(
        postings=[posting("docker-job", required=("Docker",))],
        technologies=[held_technology("java", personal_level="L2")],
        evaluated=["java"],
        coverage_complete=False,
    )

    assert "docker" in candidate_ids(result)
    assert result.status == "PARTIAL"


# --------------------------------------------------------------------------
# CASE L -- What-if follows the candidates
# --------------------------------------------------------------------------


def test_case_l_what_if_is_available_for_the_top_candidate():
    result = top3_scenario()
    top = result.candidates[0]

    page = list_related_jobs(result, user_id="user-1", view="WHAT_IF", tech_id="docker")

    assert top.tech_id == "docker"
    assert top.what_if.increased_count == 3
    assert page.total_count == 3
    assert tuple(sorted(item.job_id for item in page.items)) == tuple(
        sorted(top.what_if.newly_matched_job_ids)
    )


# --------------------------------------------------------------------------
# Snapshot contract -- new calculation version, still round-trippable
# --------------------------------------------------------------------------


def test_new_eligibility_uses_its_own_algorithm_version_and_round_trips():
    result = top3_scenario()

    assert result.algorithm_version == V7
    assert (
        RecommendationSnapshot.model_validate_json(result.model_dump_json()) == result
    )
