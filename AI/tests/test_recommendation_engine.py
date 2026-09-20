"""Exact same-cohort job deltas, uncertainty and deterministic candidate ranks."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from test_evidence_consumption import analysis_payload
from test_job_cohort import batch, criteria, posting

from job.cohort import CohortCriteria, CohortJob, CohortStatus, JobCohort, build_cohort
from job.requirements import (
    RequirementClause,
    RequirementEvidence,
    RequirementLevel,
    RequirementLevelEvidence,
    RequirementLevelEvidenceSource,
)
from recommendation.engine import (
    PrerequisiteRule,
    PrerequisiteSnapshot,
    RecommendationSnapshot,
    build_recommendations,
    list_related_jobs,
    matches_required_clauses,
    simulate_what_if,
)
from recommendation.evidence import EvidenceAnalysis, consume_evidence


def make_job(job_id: str, clauses, preferred=()) -> CohortJob:
    return CohortJob(
        job_id=job_id,
        source_record_id=job_id,
        source_site="FIXTURE",
        source_posting_id=job_id,
        source_url=f"https://example.invalid/jobs/{job_id}",
        company_name="Fixture Ltd",
        title=f"Backend {job_id}",
        collected_at=datetime(2026, 9, 7, tzinfo=UTC),
        content_hash="a" * 64,
        required_clauses=clauses,
        preferred_tech_ids=preferred,
    )


def make_cohort(jobs=None, *, min_jobs=1):
    if jobs is None:
        jobs = (
            make_job("current", (("java",),), ("docker",)),
            make_job("docker-gain", (("java",), ("docker",))),
            make_job("or-gain", (("docker", "redis"),)),
            make_job("two-missing", (("docker",), ("redis",))),
            make_job("redis-gain", (("redis",),)),
        )
    return JobCohort(
        cohort_id="cohort-unit-1",
        status=CohortStatus.EMPTY
        if not jobs
        else CohortStatus.INSUFFICIENT_DATA
        if len(jobs) < min_jobs
        else CohortStatus.READY,
        criteria=CohortCriteria(
            target_role="BACKEND",
            as_of=datetime(2026, 9, 8, tzinfo=UTC),
            min_jobs=min_jobs,
        ),
        dataset_snapshot_id="jobs-unit-1",
        pipeline_run_id="run-unit-1",
        collector_version="collector/unit",
        registry_version="registry-20260901.1",
        parser_version="job-requirement-rules/v2",
        input_count=len(jobs),
        duplicate_count=0,
        excluded_count=0,
        review_count=0,
        jobs=jobs,
        exclusions=(),
    )


def make_analysis():
    payload = analysis_payload()
    payload["repositories"][0]["evaluated_tech_ids"] = [
        "java",
        "docker",
        "redis",
        "spring-boot",
        "python",
        "nodejs",
        "javascript",
        "react",
        "typescript",
    ]
    return EvidenceAnalysis.model_validate(payload)


def recommend(cohort=None, analysis=None, **kwargs):
    return build_recommendations(
        cohort or make_cohort(),
        analysis or make_analysis(),
        user_id="user-1",
        analysis_id="analysis-1",
        **kwargs,
    )


def test_current_and_what_if_use_same_cohort_and_what_if_list_contains_only_added_jobs():
    result = recommend()
    assert result.current_job_ids == ("current",)
    assert result.current_count == 1
    docker = next(item for item in result.candidates if item.tech_id == "docker")
    assert docker.what_if.current_count == 1
    assert docker.what_if.projected_count == 3
    assert docker.what_if.increased_count == 2
    assert docker.what_if.newly_matched_job_ids == ("docker-gain", "or-gain")
    assert "two-missing" not in docker.what_if.projected_job_ids
    page = list_related_jobs(result, user_id="user-1", view="WHAT_IF", tech_id="docker")
    assert page.total_count == 2
    assert (
        tuple(item.job_id for item in page.items)
        == docker.what_if.newly_matched_job_ids
    )
    assert page.snapshot_id == result.snapshot_id
    assert result.demand.denominator == 5
    assert result.gap.missing_tech_ids == ("docker", "redis")


def test_active_recommendation_uses_all_matching_candidates_without_vacuous_matches():
    cohort = build_cohort(
        batch(posting("java", required=("Java",)), posting("no-tech", required=())),
        criteria(),
    )
    payload = make_analysis().model_dump(mode="json")
    payload["registry_version"] = cohort.registry_version

    result = recommend(cohort, EvidenceAnalysis.model_validate(payload))

    assert len(cohort.jobs) == 1
    assert len(cohort.matching_jobs or ()) == 2
    assert result.algorithm_version == "c-recommendation/lexicographic/v7"
    assert result.demand.denominator == 2
    assert result.demand.matching_count == 2
    assert len(result.matching_jobs or ()) == 2
    assert "no-tech" not in result.current_job_ids


def test_valid_l1_and_language_implementation_are_current_not_repeat_candidates():
    from test_evidence_profiles import profile_payload

    cohort = make_cohort((make_job("java-only", (("java",),)),))
    for level in ("L1", "L3"):
        payload = profile_payload(level)
        if level == "L3":
            evidence = payload["repositories"][0]["technologies"][0]
            evidence.update(evidence_level="L0", direct_dependency=False)
            evidence["proofs"] = [
                proof
                for proof in evidence["proofs"]
                if proof["kind"] != "DIRECT_DEPENDENCY"
            ]
        result = recommend(cohort, EvidenceAnalysis.model_validate(payload))
        assert result.current_job_ids == ("java-only",)
        assert result.current_count == 1
        assert result.candidates == ()
        assert (
            RecommendationSnapshot.model_validate_json(result.model_dump_json())
            == result
        )


def test_v3_without_personal_levels_never_falls_back_to_held_only_matching():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["registry_version"] = cohort.registry_version

    result = recommend(cohort, EvidenceAnalysis.model_validate(payload))

    assert result.algorithm_version == "c-recommendation/lexicographic/v7"
    assert result.current_count == 0
    assert result.current_job_ids == ()
    # Held evidence without a personal level still never promotes a job to
    # matching -- that is what this test guards.
    assert "PERSONAL_LEVEL_UNCONFIRMED:java" in result.data_gaps
    # Since S15P21E102-354 the same missing personal level makes java a *next
    # skill* instead of hiding the screen: the user has not been shown to use it.
    assert [item.tech_id for item in result.candidates] == ["java"]
    assert result.candidates[0].evidence_status == "PERSONAL_LEVEL_UNKNOWN"
    assert result.status == "PARTIAL"


def test_v3_mixed_levelled_and_legacy_jobs_keeps_level_aware_matching():
    levelled = RequirementClause(
        tech_ids=("java",),
        evidence_refs=(
            RequirementEvidence(
                source_surface="BODY",
                char_start=0,
                char_end=4,
                text="Java",
                mention_indices=(0,),
            ),
        ),
        required_level=RequirementLevel.L2,
        level_evidence_refs=(
            RequirementLevelEvidence(
                source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                level=RequirementLevel.L2,
                text="fixture L2",
                mention_indices=(0,),
            ),
        ),
    )
    levelled_job = make_job("levelled-l2", (("java",),)).model_copy(
        update={"levelled_required_clauses": (levelled,)}
    )
    cohort = make_cohort((make_job("legacy-duty", (("java",),)), levelled_job))
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["repositories"][0]["technologies"][0]["personal_level"] = "L1"

    result = recommend(cohort, EvidenceAnalysis.model_validate(payload))

    assert result.algorithm_version == "c-recommendation/lexicographic/v4"
    assert result.personal_levels == {"java": "L1"}
    assert result.current_job_ids == ()
    assert result.current_count == 0
    assert "REQUIRED_LEVEL_UNCONFIRMED:legacy-duty" in result.data_gaps
    assert result.status == "INSUFFICIENT_EVIDENCE"


def test_v4_with_only_legacy_jobs_keeps_required_levels_unconfirmed():
    cohort = make_cohort((make_job("legacy-java", (("java",),)),))
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v4"
    payload["personal_assessments"] = [
        {
            "tech_id": "java",
            "personal_level": "L1",
            "assessment_ceiling": "L3",
            "attribution_status": "COMPLETE",
            "missing_scope": [],
        }
    ]

    result = recommend(cohort, EvidenceAnalysis.model_validate(payload))

    assert result.algorithm_version == "c-recommendation/lexicographic/v5"
    assert result.current_job_ids == ()
    assert result.current_count == 0
    assert result.personal_levels == {"java": "L1"}
    assert result.assessment_ceilings == {"java": "L3"}
    assert "REQUIRED_LEVEL_UNCONFIRMED:legacy-java" in result.data_gaps
    assert result.status == "INSUFFICIENT_EVIDENCE"


def test_v3_l0_candidate_projects_only_l1_and_related_page_uses_same_ids():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["registry_version"] = cohort.registry_version
    payload["repositories"][0]["technologies"][0]["personal_level"] = "L0"

    result = recommend(cohort, EvidenceAnalysis.model_validate(payload))
    candidate = result.candidates[0]
    page = list_related_jobs(
        result, user_id="user-1", view="WHAT_IF", tech_id=candidate.tech_id
    )

    assert candidate.tech_id == "java"
    assert candidate.evidence_status == "L0"
    assert candidate.what_if.current_count == 0
    assert candidate.what_if.projected_count == 1
    assert candidate.what_if.newly_matched_job_ids == ("job-1",)
    assert (
        tuple(item.job_id for item in page.items)
        == candidate.what_if.newly_matched_job_ids
    )


def test_v4_ceiling_is_preserved_and_marks_unassessable_requirement():
    levelled = RequirementClause(
        tech_ids=("java",),
        evidence_refs=(
            RequirementEvidence(
                source_surface="BODY",
                char_start=0,
                char_end=4,
                text="Java",
                mention_indices=(0,),
            ),
        ),
        required_level=RequirementLevel.L2,
        level_evidence_refs=(
            RequirementLevelEvidence(
                source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                level=RequirementLevel.L2,
                text="fixture L2",
                mention_indices=(0,),
            ),
        ),
    )
    job = make_job("levelled-l2", (("java",),)).model_copy(
        update={"levelled_required_clauses": (levelled,)}
    )
    cohort = make_cohort((job,))
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v4"
    payload["registry_version"] = cohort.registry_version
    payload["personal_assessments"] = [
        {
            "tech_id": "java",
            "personal_level": "L1",
            "assessment_ceiling": "L1",
            "attribution_status": "COMPLETE",
            "missing_scope": ["L2_L3_RULE_NOT_SUPPORTED"],
        }
    ]

    result = recommend(cohort, EvidenceAnalysis.model_validate(payload))

    assert result.algorithm_version == "c-recommendation/lexicographic/v5"
    assert result.personal_levels == {"java": "L1"}
    assert result.assessment_ceilings == {"java": "L1"}
    assert result.level_assessment_complete_tech_ids == ("java",)
    assert "ASSESSMENT_CEILING_BELOW_REQUIREMENT:java:L2" in result.data_gaps


def test_v5_complete_assessment_ids_must_be_canonical():
    from recommendation.engine import _snapshot_id

    levelled = RequirementClause(
        tech_ids=("java",),
        evidence_refs=(
            RequirementEvidence(
                source_surface="BODY",
                char_start=0,
                char_end=4,
                text="Java",
                mention_indices=(0,),
            ),
        ),
        required_level=RequirementLevel.L1,
        level_evidence_refs=(
            RequirementLevelEvidence(
                source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                level=RequirementLevel.L1,
                text="fixture L1",
                mention_indices=(0,),
            ),
        ),
    )
    cohort = make_cohort(
        (
            make_job("levelled-l1", (("java",),)).model_copy(
                update={"levelled_required_clauses": (levelled,)}
            ),
        )
    )
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v4"
    payload["personal_assessments"] = [
        {
            "tech_id": "java",
            "personal_level": "L1",
            "assessment_ceiling": "L3",
            "attribution_status": "COMPLETE",
            "missing_scope": [],
        }
    ]
    result = recommend(cohort, EvidenceAnalysis.model_validate(payload))
    forged = result.model_dump(mode="json", exclude={"snapshot_id"})
    forged["level_assessment_complete_tech_ids"] = ["java", "java"]
    forged["snapshot_id"] = _snapshot_id(forged)

    with pytest.raises(ValueError, match="unique and sorted"):
        RecommendationSnapshot.model_validate(forged)


def test_preferred_never_gates_and_or_is_not_an_and():
    assert matches_required_clauses((("java",),), frozenset({"java"}))
    assert matches_required_clauses(
        (("java", "python"), ("docker",)), frozenset({"python", "docker"})
    )
    assert not matches_required_clauses((("java",), ("docker",)), frozenset({"java"}))
    assert not matches_required_clauses((), frozenset({"java"}))
    assert not matches_required_clauses(((),), frozenset({"java"}))
    assert recommend().current_count == 1  # current prefers unheld Docker


def test_held_candidate_unknown_and_registry_mismatch_are_rejected():
    cohort = make_cohort()
    selection = consume_evidence(
        make_analysis(),
        user_id="user-1",
        analysis_id="analysis-1",
        tech_ids=("java", "docker"),
    )
    with pytest.raises(ValueError, match="already held"):
        simulate_what_if(cohort, selection, "java")
    with pytest.raises(ValueError, match="unconfirmed"):
        simulate_what_if(cohort, selection, "unsupported")
    mismatch = make_analysis().model_copy(
        update={"registry_version": "registry-20260902.1"}
    )
    with pytest.raises(ValueError, match="Registry"):
        recommend(analysis=mismatch)


def test_unknown_is_not_a_missing_candidate_and_partial_input_keeps_positive_current_jobs():
    payload = make_analysis().model_dump(mode="json")
    payload["status"] = "PARTIAL"
    payload["repositories"][0].update(status="PARTIAL", coverage_complete=False)
    result = recommend(analysis=EvidenceAnalysis.model_validate(payload))
    assert result.current_job_ids == ("current",)
    assert result.candidates == ()
    assert result.gap.missing_tech_ids == ()
    assert result.gap.unknown_tech_ids == ("docker", "redis")
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.data_gaps


def test_zero_increase_is_real_zero_and_multiple_missing_technologies_are_not_auto_added():
    cohort = make_cohort((make_job("needs-both", (("docker",), ("redis",))),))
    result = recommend(cohort)
    assert len(result.candidates) == 2
    for candidate in result.candidates:
        assert candidate.what_if.increased_count == 0
        assert candidate.what_if.projected_count == 0
        assert "NO_IMMEDIATE_JOB_INCREASE" in candidate.reason_codes
        assert candidate.what_if.newly_matched_job_ids == ()


def test_job_gain_precedes_prerequisite_readiness_without_adding_prerequisites():
    cohort = make_cohort(
        (
            make_job("react-gain", (("react",),)),
            make_job("needs-both", (("docker",), ("redis",))),
        )
    )
    result = recommend(cohort)
    first = result.candidates[0]
    assert first.tech_id == "react"
    assert first.what_if.increased_count == 1
    assert first.missing_prerequisite_tech_ids == ("javascript",)
    assert "javascript" not in result.held.held_tech_ids
    assert first.what_if.newly_matched_job_ids == ("react-gain",)
    assert result.algorithm_version == "c-recommendation/lexicographic/v3"
    assert result.tie_break_rule.startswith("gain-desc,prerequisites-ready,")


def test_prerequisite_readiness_breaks_equal_gain_and_legacy_v2_remains_readable():
    from recommendation.engine import _snapshot_id

    result = recommend(
        make_cohort(
            (make_job("react", (("react",),)), make_job("docker", (("docker",),)))
        )
    )
    assert [item.tech_id for item in result.candidates] == ["docker", "react"]
    old = result.model_dump(mode="json", exclude={"snapshot_id"})
    old["algorithm_version"] = "c-recommendation/lexicographic/v2"
    old["tie_break_rule"] = (
        "prerequisites-ready,gain-desc,required-count-desc,"
        "uncertainty-asc,total-count-desc,tech-id-asc"
    )
    old["snapshot_id"] = _snapshot_id(old)
    restored = RecommendationSnapshot.model_validate(old)
    assert restored.model_dump(mode="json") == old


def test_deterministic_rank_max_three_and_json_roundtrip_preserve_snapshot_and_counts():
    cohort = make_cohort(
        tuple(
            make_job(tech, ((tech,),))
            for tech in ("docker", "redis", "python", "java", "typescript")
        )
    )
    result = recommend(cohort)
    reversed_result = recommend(
        cohort.model_copy(update={"jobs": tuple(reversed(cohort.jobs))})
    )
    assert reversed_result == result
    assert [item.rank for item in result.candidates] == [1, 2, 3]
    assert [item.tech_id for item in result.candidates] == ["docker", "python", "redis"]
    restored = RecommendationSnapshot.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.snapshot_id == result.snapshot_id


def test_prerequisite_policy_affects_order_without_adding_prerequisites_to_what_if():
    cohort = make_cohort(
        (
            make_job("python", (("python",),)),
            make_job("framework", (("spring-boot",),)),
            make_job("framework-and-python", (("spring-boot",), ("python",))),
        )
    )
    prerequisites = PrerequisiteSnapshot(
        version="test-prerequisites/v1",
        rules=(
            PrerequisiteRule(
                tech_id="spring-boot",
                required_tech_ids=("python",),
                fact_ids=("rule-framework-python",),
            ),
        ),
    )
    result = recommend(cohort, prerequisites=prerequisites)
    assert [candidate.tech_id for candidate in result.candidates] == [
        "python",
        "spring-boot",
    ]
    candidate = result.candidates[1]
    assert candidate.prerequisite_tech_ids == ("python",)
    assert candidate.missing_prerequisite_tech_ids == ("python",)
    assert candidate.what_if.newly_matched_job_ids == ("framework",)
    assert "rule-framework-python" in candidate.fact_ids
    assert "PREREQUISITES_MISSING" in candidate.reason_codes


def test_no_candidates_and_empty_or_insufficient_cohort_are_distinct():
    no_candidates = recommend(make_cohort((make_job("java", (("java",),)),)))
    assert no_candidates.status == "NO_CANDIDATES"
    assert no_candidates.current_count == 1
    empty = recommend(make_cohort(()))
    assert empty.status == "INSUFFICIENT_DATA"
    assert empty.demand.denominator == 0
    assert empty.candidates == ()
    small = recommend(make_cohort(min_jobs=10))
    assert small.status == "INSUFFICIENT_DATA"
    assert small.demand.denominator == 5
    assert small.candidates == ()


def test_job_page_enforces_snapshot_owner_candidate_and_stable_pagination():
    result = recommend()
    with pytest.raises(PermissionError):
        list_related_jobs(result, user_id="user-2", view="CURRENT")
    with pytest.raises(ValueError, match="candidate"):
        list_related_jobs(result, user_id="user-1", view="WHAT_IF", tech_id="java")
    page = list_related_jobs(
        result, user_id="user-1", view="WHAT_IF", tech_id="docker", offset=1, limit=1
    )
    assert page.total_count == 2
    assert tuple(job.job_id for job in page.items) == ("or-gain",)
    empty_page = list_related_jobs(result, user_id="user-1", view="CURRENT", offset=100)
    assert empty_page.total_count == 1
    assert empty_page.items == ()


def test_active_filter_recomputes_current_and_what_if_counts_before_pagination():
    result = recommend()
    docker = next(item for item in result.candidates if item.tech_id == "docker")
    only_delta = {docker.what_if.newly_matched_job_ids[-1]}

    page = list_related_jobs(
        result,
        user_id="user-1",
        view="WHAT_IF",
        tech_id="docker",
        offset=0,
        limit=1,
        active_job_ids=only_delta,
    )

    assert page.current_count == 0
    assert page.projected_count == 1
    assert page.increased_count == 1
    assert page.total_count == 1
    assert tuple(job.job_id for job in page.items) == tuple(only_delta)

    current = list_related_jobs(
        result,
        user_id="user-1",
        view="CURRENT",
        active_job_ids=frozenset(),
    )
    assert current.current_count == current.projected_count == current.total_count == 0
    assert current.items == ()


def test_empty_required_and_duplicate_job_ids_fail_cohort_validation():
    with pytest.raises(ValidationError):
        make_job("empty", ())
    job = make_job("duplicated", (("java",),))
    with pytest.raises(ValidationError, match="unique"):
        make_cohort((job, job))


def test_serialized_snapshot_rejects_count_or_list_tampering():
    result = recommend()
    payload = result.model_dump(mode="json")
    payload["candidates"][0]["what_if"]["increased_count"] += 1
    with pytest.raises(ValidationError):
        RecommendationSnapshot.model_validate(payload)
    payload = result.model_dump(mode="json")
    payload["current_job_ids"] = ["redis-gain"]
    with pytest.raises(ValidationError):
        RecommendationSnapshot.model_validate(payload)


def test_prerequisite_unknown_is_explicit_and_does_not_become_an_implicit_held_technology():
    cohort = make_cohort((make_job("node", (("nodejs",),)),))
    payload = make_analysis().model_dump(mode="json")
    payload["repositories"][0]["evaluated_tech_ids"].remove("javascript")
    result = recommend(cohort, EvidenceAnalysis.model_validate(payload))
    candidate = result.candidates[0]
    assert candidate.tech_id == "nodejs"
    assert candidate.unknown_prerequisite_tech_ids == ("javascript",)
    assert candidate.missing_prerequisite_tech_ids == ()
    assert "PREREQUISITE_EVIDENCE_UNCONFIRMED" in candidate.reason_codes
    assert result.held.held_tech_ids == ("java",)
    assert result.status == "PARTIAL"


def test_raw_classified_cohort_demand_and_related_lists_agree_through_json_roundtrip():
    current = posting("current", required=("Java",), preferred=("Docker",))
    delta = posting(
        "delta", required=("Java", "Docker"), required_text="Java 및 Docker 구현 경험"
    )
    or_job = posting(
        "alternative",
        required=("Docker", "Redis"),
        required_text="Docker 또는 Redis 경험",
    )
    empty = posting("no-required", required=(), preferred=("Java",))
    cohort = build_cohort(batch(current, delta, or_job, empty, delta), criteria())
    evidence = make_analysis().model_copy(
        update={"registry_version": cohort.registry_version}
    )
    result = recommend(cohort, evidence)
    assert result.demand.denominator == 4
    assert result.demand.duplicate_count == 1
    assert result.demand.review_count == 1
    docker = next(item for item in result.candidates if item.tech_id == "docker")
    assert docker.demand.required_count == 2
    assert docker.demand.preferred_count == 1
    assert docker.demand.total_count == 3
    assert docker.what_if.current_count == 1
    assert docker.what_if.projected_count == 3
    assert docker.what_if.increased_count == 2
    restored = RecommendationSnapshot.model_validate_json(result.model_dump_json())
    page = list_related_jobs(
        restored, user_id="user-1", view="WHAT_IF", tech_id="docker"
    )
    assert page.total_count == docker.what_if.increased_count
    assert {job.job_id for job in page.items} == {"alternative", "delta"}
    assert all(
        job.requirements.required
        and str(job.source_url).startswith("https://example.com/")
        for job in page.items
    )


@pytest.mark.parametrize("field", ["user_id", "analysis_id"])
def test_recommendation_request_identity_is_checked_before_result_is_returned(field):
    payload = make_analysis().model_dump(mode="json")
    payload[field] = "other"
    with pytest.raises(PermissionError):
        recommend(analysis=EvidenceAnalysis.model_validate(payload))


def test_demand_gain_outweighs_total_mentions_and_prerequisite_rule_order_is_stable():
    cohort = make_cohort(
        (
            make_job("gain", (("docker",),), ("redis",)),
            make_job("already-matched-1", (("java",),), ("redis",)),
            make_job("already-matched-2", (("java",),), ("redis",)),
        )
    )
    result = recommend(cohort)
    assert result.candidates[0].tech_id == "docker"
    assert result.candidates[0].what_if.increased_count == 1
    assert result.candidates[1].tech_id == "redis"
    assert result.candidates[1].demand.total_count == 3
    assert result.candidates[1].what_if.increased_count == 0
    first = PrerequisiteRule(
        tech_id="docker", required_tech_ids=(), fact_ids=("p-docker",)
    )
    second = PrerequisiteRule(
        tech_id="redis", required_tech_ids=(), fact_ids=("p-redis",)
    )
    a = recommend(
        cohort,
        prerequisites=PrerequisiteSnapshot(version="test/v1", rules=(first, second)),
    )
    b = recommend(
        cohort,
        prerequisites=PrerequisiteSnapshot(version="test/v1", rules=(second, first)),
    )
    assert a == b
