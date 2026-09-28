"""Partial matching never converts unknown evidence into missing skill."""

import json
import math
from pathlib import Path

import pytest
from job.cohort import CohortJob, JobCohort, build_cohort
from job.matching import (
    ConditionAssessment,
    MatchingResultTooLarge,
    build_job_matching,
    evaluate_clause,
    matching_storage_rows,
    restore_job_assessment,
    validate_job_matching,
)
from job.requirements import (
    RequirementClause,
    RequirementEvidence,
    RequirementLevel,
    RequirementLevelEvidence,
    RequirementLevelEvidenceSource,
)
from recommendation.evidence import EvidenceAnalysis, HeldStatus
from test_job_cohort import batch, criteria, posting
from test_recommendation_engine import make_analysis


def levelled_analysis(level: str = "L1") -> EvidenceAnalysis:
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["repositories"][0]["technologies"][0]["personal_level"] = level
    return EvidenceAnalysis.model_validate(payload)


def ceiling_analysis(
    level: str = "L2", ceiling: str = "L2", *, partial: bool = False
) -> EvidenceAnalysis:
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v4"
    payload["personal_assessments"] = [
        {
            "tech_id": "java",
            "personal_level": level,
            "assessment_ceiling": ceiling,
            "attribution_status": "COMPLETE",
            "missing_scope": ([] if ceiling == "L3" else ["L3_RULE_NOT_SUPPORTED"]),
        }
    ]
    if partial:
        payload["status"] = "PARTIAL"
        payload["repositories"][0].update(status="PARTIAL", coverage_complete=False)
    return EvidenceAnalysis.model_validate(payload)


def test_partial_result_explains_non_requirement_strict_review_reason():
    cohort = build_cohort(batch(posting(general=("Cobol",))), criteria())
    result = build_job_matching(
        cohort, levelled_analysis("L3"), user_id="user-1", analysis_id="analysis-1"
    )
    row = result.jobs[0]
    assert row.required_status == "FULL"
    assert row.job.strict_match_eligible is False
    assert row.job.strict_review_reasons == ("TECHNOLOGY_REVIEW_REQUIRED",)


@pytest.mark.parametrize(
    ("decisions", "expected"),
    [
        ({"java": HeldStatus.HELD}, "SATISFIED"),
        ({"java": HeldStatus.NOT_HELD, "python": HeldStatus.UNKNOWN}, "UNKNOWN"),
        ({"java": HeldStatus.NOT_HELD, "python": HeldStatus.NOT_HELD}, "UNSATISFIED"),
        ({}, "UNKNOWN"),
    ],
)
def test_or_requires_one_positive_or_all_verified_negatives(decisions, expected):
    clause = RequirementClause(
        operator="ANY_OF",
        tech_ids=("java", "python"),
        evidence_refs=(
            RequirementEvidence(
                source_surface="BODY",
                char_start=0,
                char_end=14,
                text="Java 또는 Python",
                mention_indices=(0, 1),
            ),
        ),
    )
    result = evaluate_clause(clause, decisions)
    assert result.status == expected
    assert set(result.held_tech_ids).isdisjoint(result.unknown_tech_ids)


def test_required_clause_carries_explicit_l1_to_l3_level_contract():
    clause = RequirementClause(
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

    assert clause.required_level is RequirementLevel.L2


def test_v3_personal_level_below_required_is_not_satisfied():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    job = cohort.matching_jobs[0]
    clause = job.requirements.required[0].model_copy(
        update={
            "required_level": RequirementLevel.L2,
            "level_evidence_refs": (
                RequirementLevelEvidence(
                    source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                    level=RequirementLevel.L2,
                    text="fixture L2",
                    mention_indices=(0,),
                ),
            ),
        }
    )
    requirements = job.requirements.model_copy(update={"required": (clause,)})
    cohort = cohort.model_copy(
        update={
            "matching_jobs": (job.model_copy(update={"requirements": requirements}),)
        }
    )
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["repositories"][0]["technologies"][0]["personal_level"] = "L1"

    row = build_job_matching(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    ).jobs[0]

    assert row.required.clauses[0].verdict == "LEVEL_BELOW_REQUIRED"
    assert row.required_status == "NONE"


def test_v2_held_only_compatibility_matches_recommendation_semantics():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())

    row = build_job_matching(
        cohort,
        make_analysis().model_copy(
            update={"registry_version": cohort.registry_version}
        ),
        user_id="user-1",
        analysis_id="analysis-1",
    ).jobs[0]

    assert row.required.clauses[0].verdict == "LEGACY_HELD_MATCH"
    assert row.required_status == "FULL"


@pytest.mark.parametrize(
    ("analysis", "expected_verdict", "expected_status"),
    [
        (ceiling_analysis("L2", "L2"), "EVIDENCE_SCOPE_INCOMPLETE", "UNKNOWN"),
        (ceiling_analysis("L2", "L3"), "LEVEL_BELOW_REQUIRED", "NONE"),
        (
            ceiling_analysis("L2", "L3", partial=True),
            "EVIDENCE_SCOPE_INCOMPLETE",
            "UNKNOWN",
        ),
        (ceiling_analysis("L3", "L3", partial=True), "SATISFIED", "FULL"),
    ],
)
def test_v4_ceiling_and_scope_control_below_level_verdict(
    analysis, expected_verdict, expected_status
):
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    job = cohort.matching_jobs[0]
    clause = job.requirements.required[0].model_copy(
        update={
            "required_level": RequirementLevel.L3,
            "level_evidence_refs": (
                RequirementLevelEvidence(
                    source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                    level=RequirementLevel.L3,
                    text="운영 수준의 Java 경험",
                    mention_indices=(0,),
                ),
            ),
        }
    )
    requirements = job.requirements.model_copy(update={"required": (clause,)})
    cohort = cohort.model_copy(
        update={
            "matching_jobs": (job.model_copy(update={"requirements": requirements}),)
        }
    )

    row = build_job_matching(
        cohort,
        analysis.model_copy(update={"registry_version": cohort.registry_version}),
        user_id="user-1",
        analysis_id="analysis-1",
    ).jobs[0]

    assessed = row.required.clauses[0]
    assert assessed.verdict == expected_verdict
    assert row.required_status == expected_status
    assert assessed.assessment_ceilings == {
        "java": analysis.personal_assessments[0].assessment_ceiling
    }


def test_v4_restore_rejects_incomplete_verdict_after_ceiling_is_tampered_upward():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    job = cohort.matching_jobs[0]
    clause = job.requirements.required[0].model_copy(
        update={
            "required_level": RequirementLevel.L3,
            "level_evidence_refs": (
                RequirementLevelEvidence(
                    source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                    level=RequirementLevel.L3,
                    text="fixture L3",
                    mention_indices=(0,),
                ),
            ),
        }
    )
    cohort = cohort.model_copy(
        update={
            "matching_jobs": (
                job.model_copy(
                    update={
                        "requirements": job.requirements.model_copy(
                            update={"required": (clause,)}
                        )
                    }
                ),
            )
        }
    )
    result = build_job_matching(
        cohort,
        ceiling_analysis("L2", "L2").model_copy(
            update={"registry_version": cohort.registry_version}
        ),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    stored = matching_storage_rows(result)
    decision = stored["assessments"][0]["assessment"]["required"]["clauses"][0]
    decision["assessment_ceilings"]["java"] = "L3"

    with pytest.raises(ValueError, match="incomplete verdict"):
        restore_job_assessment(
            stored["sources"][0], stored["assessments"][0]["assessment"]
        )


def test_v4_restore_rejects_ceiling_mode_stripping():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    job = cohort.matching_jobs[0]
    clause = job.requirements.required[0].model_copy(
        update={
            "required_level": RequirementLevel.L3,
            "level_evidence_refs": (
                RequirementLevelEvidence(
                    source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                    level=RequirementLevel.L3,
                    text="fixture L3",
                    mention_indices=(0,),
                ),
            ),
        }
    )
    cohort = cohort.model_copy(
        update={
            "matching_jobs": (
                job.model_copy(
                    update={
                        "requirements": job.requirements.model_copy(
                            update={"required": (clause,)}
                        )
                    }
                ),
            )
        }
    )
    result = build_job_matching(
        cohort,
        ceiling_analysis("L2", "L3", partial=True).model_copy(
            update={"registry_version": cohort.registry_version}
        ),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    stored = matching_storage_rows(result)
    assessment = stored["assessments"][0]["assessment"]
    decision = assessment["required"]["clauses"][0]
    decision.pop("assessment_ceilings")
    decision.pop("level_assessment_complete_tech_ids")
    decision.pop("assessment_ceiling_applied")
    decision.update(status="UNSATISFIED", verdict="LEVEL_BELOW_REQUIRED")
    assessment["required"].update(
        satisfied_count=0,
        unsatisfied_count=1,
        unknown_count=0,
    )
    assessment["required_status"] = "NONE"

    with pytest.raises(ValueError, match="v4 stored clause requires"):
        restore_job_assessment(stored["sources"][0], assessment)


def test_cohort_rejects_present_but_not_actually_levelled_clauses():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    job = cohort.jobs[0]
    invalid = job.levelled_required_clauses[0].model_copy(
        update={"level_evidence_refs": ()}
    )

    with pytest.raises(ValueError, match="required level and level evidence"):
        CohortJob(
            **job.model_dump(mode="python", exclude={"levelled_required_clauses"}),
            levelled_required_clauses=(invalid,),
        )


def test_v3_missing_personal_level_is_incomplete_not_evidence_level_fallback():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"

    row = build_job_matching(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    ).jobs[0]

    assert row.required.clauses[0].verdict == "EVIDENCE_SCOPE_INCOMPLETE"
    assert row.required_status == "UNKNOWN"


def test_v3_restore_rejects_tampered_legacy_held_match():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    result = build_job_matching(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    stored = matching_storage_rows(result)
    assessment = stored["assessments"][0]["assessment"]
    clause = assessment["required"]["clauses"][0]
    clause.update(status="SATISFIED", verdict="LEGACY_HELD_MATCH")
    assessment["required"].update(
        satisfied_count=1,
        unsatisfied_count=0,
        unknown_count=0,
    )
    assessment["required_status"] = "FULL"

    with pytest.raises(ValueError, match="requires evidence input v1 or v2"):
        restore_job_assessment(stored["sources"][0], assessment)


def test_v3_partial_scope_keeps_a_proof_supported_positive_personal_level():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["status"] = "PARTIAL"
    payload["repositories"][0].update(status="PARTIAL", coverage_complete=False)
    payload["repositories"][0]["technologies"][0]["personal_level"] = "L1"

    row = build_job_matching(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    ).jobs[0]

    assert row.required.clauses[0].verdict == "SATISFIED"
    assert row.required_status == "FULL"


def test_v3_partial_scope_does_not_confirm_a_below_required_level():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    job = cohort.matching_jobs[0]
    clause = job.requirements.required[0].model_copy(
        update={
            "required_level": RequirementLevel.L2,
            "level_evidence_refs": (
                RequirementLevelEvidence(
                    source=RequirementLevelEvidenceSource.CONSERVATIVE_DEFAULT,
                    level=RequirementLevel.L2,
                    text="fixture L2",
                    mention_indices=(0,),
                ),
            ),
        }
    )
    cohort = cohort.model_copy(
        update={
            "matching_jobs": (
                job.model_copy(
                    update={
                        "requirements": job.requirements.model_copy(
                            update={"required": (clause,)}
                        )
                    }
                ),
            )
        }
    )
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["status"] = "PARTIAL"
    payload["repositories"][0].update(status="PARTIAL", coverage_complete=False)
    payload["repositories"][0]["technologies"][0]["personal_level"] = "L1"

    row = build_job_matching(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    ).jobs[0]

    assert row.required.clauses[0].verdict == "EVIDENCE_SCOPE_INCOMPLETE"
    assert row.required.fulfillment_ratio is None
    assert row.required_status == "UNKNOWN"


def test_restore_rejects_tampered_level_verdict_partition():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    result = build_job_matching(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    stored = matching_storage_rows(result)
    assessment = stored["assessments"][0]["assessment"]
    clause = assessment["required"]["clauses"][0]
    clause.update(
        status="SATISFIED",
        held_tech_ids=[],
        missing_tech_ids=["java"],
        unknown_tech_ids=[],
        verdict="SATISFIED",
        personal_levels={"java": "L3"},
    )

    with pytest.raises(ValueError, match="personal levels require held"):
        restore_job_assessment(stored["sources"][0], assessment)


def test_restore_rejects_omitted_verdict_for_levelled_clause():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["repositories"][0]["technologies"][0]["personal_level"] = "L1"
    result = build_job_matching(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    stored = matching_storage_rows(result)
    assessment = stored["assessments"][0]["assessment"]
    clause = assessment["required"]["clauses"][0]
    clause.pop("verdict")
    clause["status"] = "SATISFIED"
    assessment["required"]["satisfied_count"] = 1
    assessment["required"]["unknown_count"] = 0

    with pytest.raises(ValueError, match="levelled clause requires a verdict"):
        restore_job_assessment(stored["sources"][0], assessment)


def test_restore_rejects_omitted_incomplete_verdict_for_missing_personal_level():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria())
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    result = build_job_matching(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    stored = matching_storage_rows(result)
    assessment = stored["assessments"][0]["assessment"]
    clause = assessment["required"]["clauses"][0]
    assert clause["verdict"] == "EVIDENCE_SCOPE_INCOMPLETE"
    clause.pop("verdict")
    clause["status"] = "SATISFIED"
    assessment["required"].update(
        satisfied_count=1,
        unsatisfied_count=0,
        unknown_count=0,
    )
    assessment["required_status"] = "FULL"

    with pytest.raises(ValueError, match="levelled clause requires a verdict"):
        restore_job_assessment(stored["sources"][0], assessment)


def test_restore_rejects_incomplete_verdict_for_confirmed_missing_technology():
    cohort = build_cohort(batch(posting(required=("Docker",))), criteria())
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    result = build_job_matching(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    stored = matching_storage_rows(result)
    assessment = stored["assessments"][0]["assessment"]
    clause = assessment["required"]["clauses"][0]
    assert clause["verdict"] == "TECHNOLOGY_NOT_HELD"
    clause.update(status="UNKNOWN", verdict="EVIDENCE_SCOPE_INCOMPLETE")
    assessment["required"].update(
        satisfied_count=0,
        unsatisfied_count=0,
        unknown_count=1,
    )
    assessment["required_status"] = "UNKNOWN"

    with pytest.raises(ValueError, match="incomplete verdict does not match evidence"):
        restore_job_assessment(stored["sources"][0], assessment)


def test_partial_and_preferred_separate_from_strict_matching():
    cohort = build_cohort(
        batch(posting(required=("Java", "Docker"), preferred=("Redis",))), criteria()
    )
    result = build_job_matching(
        cohort, levelled_analysis("L3"), user_id="user-1", analysis_id="analysis-1"
    )
    row = result.jobs[0]
    assert row.required.satisfied_count == 1
    assert row.required.unsatisfied_count == 1
    assert row.required.fulfillment_ratio == 0.5
    assert row.required_status == "PARTIAL"
    assert row.preferred.unsatisfied_count == 1
    assert row.preferred.fulfillment_ratio == 0


def test_unresolved_sentence_retains_independent_clause_but_not_total_ratio():
    record = posting(
        required=("Java", "Python", "Docker"),
        required_text="Java 경험\nPython, Docker 등을 활용",
    )
    cohort = build_cohort(batch(record), criteria())
    assert not cohort.jobs
    result = build_job_matching(
        cohort, levelled_analysis("L3"), user_id="user-1", analysis_id="analysis-1"
    )
    row = result.jobs[0]
    assert row.required.satisfied_count == 1
    assert row.required.unresolved
    assert row.required.fulfillment_ratio is None
    assert row.required_status == "PARTIAL"
    assert not row.job.strict_match_eligible


def test_personal_partial_match_ranks_above_fully_parsed_non_match():
    cohort = build_cohort(
        batch(
            posting(
                "partial-with-unresolved",
                required=("Java", "Python", "Docker"),
                required_text="Java 경험\nPython, Docker 등을 활용",
            ),
            posting("fully-parsed-none", required=("Docker",)),
        ),
        criteria(),
    )

    result = build_job_matching(
        cohort, levelled_analysis("L3"), user_id="user-1", analysis_id="analysis-1"
    )

    assert [row.job.job_id for row in result.jobs] == [
        "partial-with-unresolved",
        "fully-parsed-none",
    ]
    assert [row.required_status for row in result.jobs] == ["PARTIAL", "NONE"]
    assert result.jobs[0].required.unresolved


def test_legacy_v2_unresolved_positive_status_remains_readable():
    cohort = build_cohort(
        batch(
            posting(
                required=("Java", "Python", "Docker"),
                required_text="Java 경험\nPython, Docker 등을 활용",
            )
        ),
        criteria(),
    )
    current = build_job_matching(
        cohort, levelled_analysis("L3"), user_id="user-1", analysis_id="analysis-1"
    )
    payload = current.model_dump(mode="json")
    payload["schema_version"] = "job-matching/v2"
    payload.pop("calculation_snapshot_id")
    payload["jobs"][0]["required_status"] = "UNKNOWN"

    legacy = validate_job_matching(payload)

    assert legacy.schema_version == "job-matching/v2"
    assert legacy.jobs[0].required_status == "UNKNOWN"


def test_current_matching_rejects_legacy_unknown_for_positive_partial_match():
    cohort = build_cohort(
        batch(
            posting(
                required=("Java", "Python", "Docker"),
                required_text="Java 경험\nPython, Docker 등을 활용",
            )
        ),
        criteria(),
    )
    payload = build_job_matching(
        cohort, levelled_analysis("L3"), user_id="user-1", analysis_id="analysis-1"
    ).model_dump(mode="json")
    payload.pop("calculation_snapshot_id")
    payload["jobs"][0]["required_status"] = "UNKNOWN"

    with pytest.raises(ValueError, match="required status mismatch"):
        validate_job_matching(payload)


def test_no_required_is_not_perfect_and_no_preferred_is_not_zero():
    cohort = build_cohort(batch(posting(required=(), preferred=("Java",))), criteria())
    row = build_job_matching(
        cohort, make_analysis(), user_id="user-1", analysis_id="analysis-1"
    ).jobs[0]
    assert row.required_status == "NOT_APPLICABLE"
    assert row.required.fulfillment_ratio is None
    assert row.preferred.fulfillment_ratio == 1


def test_closed_and_wrong_role_and_missing_body_are_not_revived():
    cohort = build_cohort(
        batch(
            posting("closed", posting_status="CLOSED"),
            posting("other", title="프론트엔드 개발자", raw_job_category="FRONTEND"),
            posting(
                "nobody",
                body_status="PARSE_FAILED",
                description_text=None,
                technology_mentions=[],
            ),
            posting("valid"),
        ),
        criteria(),
    )
    result = build_job_matching(
        cohort, make_analysis(), user_id="user-1", analysis_id="analysis-1"
    )
    assert [row.job.job_id for row in result.jobs] == ["valid"]


def test_legacy_cohort_has_no_partial_input_instead_of_empty_success():
    raw = build_cohort(batch(posting()), criteria()).model_dump(mode="json")
    raw.pop("matching_jobs")
    cohort = JobCohort.model_validate(raw)
    assert "matching_jobs" not in cohort.model_dump(mode="json")
    with pytest.raises(ValueError, match="MATCHING_INPUT_NOT_PREPARED"):
        build_job_matching(
            cohort, make_analysis(), user_id="user-1", analysis_id="analysis-1"
        )


def test_identity_is_checked_even_for_empty_cohort():
    cohort = build_cohort(batch(), criteria())
    with pytest.raises(PermissionError):
        build_job_matching(
            cohort, make_analysis(), user_id="other", analysis_id="analysis-1"
        )


def _three_clause_ratio_payload(satisfied_count, ratio):
    statuses = ("SATISFIED",) * satisfied_count + ("UNSATISFIED",) * (
        3 - satisfied_count
    )
    return {
        "clauses": [
            {
                "clause": {
                    "tech_ids": [tech],
                    "evidence_refs": [
                        {
                            "source_surface": "BODY",
                            "char_start": 0,
                            "char_end": len(tech),
                            "text": tech,
                            "mention_indices": [index],
                        }
                    ],
                },
                "status": status,
                "held_tech_ids": [tech] if status == "SATISFIED" else [],
                "missing_tech_ids": [tech] if status == "UNSATISFIED" else [],
                "unknown_tech_ids": [],
            }
            for index, (tech, status) in enumerate(
                zip(("java", "python", "docker"), statuses, strict=True)
            )
        ],
        "unresolved": [],
        "satisfied_count": satisfied_count,
        "unsatisfied_count": 3 - satisfied_count,
        "unknown_count": 0,
        "fulfillment_ratio": ratio,
    }


@pytest.mark.parametrize(
    ("satisfied_count", "transport_ratio", "expected"),
    [(0, 0, 0), (1, 0.333333, 1 / 3), (2, 0.666667, 2 / 3), (3, 1, 1)],
)
def test_ratio_accepts_six_decimal_transport_but_canonicalizes_from_integer_counts(
    satisfied_count, transport_ratio, expected
):
    value = ConditionAssessment.model_validate(
        _three_clause_ratio_payload(satisfied_count, transport_ratio)
    )

    assert value.fulfillment_ratio == expected
    assert value.model_dump(mode="json")["fulfillment_ratio"] == expected


@pytest.mark.parametrize("ratio", [0.333334, math.nan, math.inf, -math.inf])
def test_ratio_rejects_outside_tolerance_and_non_finite_values(ratio):
    with pytest.raises(ValueError):
        ConditionAssessment.model_validate(_three_clause_ratio_payload(1, ratio))


def test_unknown_conditions_still_require_null_ratio():
    clause = evaluate_clause(
        RequirementClause(
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
        ),
        {},
    )
    with pytest.raises(ValueError):
        ConditionAssessment(
            clauses=(clause,),
            unresolved=(),
            satisfied_count=0,
            unsatisfied_count=0,
            unknown_count=1,
            fulfillment_ratio=0,
        )


def test_storage_references_shared_source_instead_of_copying_requirements():
    result = build_job_matching(
        build_cohort(
            batch(posting(required=("Java", "Docker"), preferred=("Redis",))),
            criteria(),
        ),
        levelled_analysis(),
        user_id="user-1",
        analysis_id="analysis-1",
    )

    stored = matching_storage_rows(result)
    assert "requirements" in stored["sources"][0]
    assert "requirements" not in stored["assessments"][0]["assessment"]
    assert (
        "clause" not in stored["assessments"][0]["assessment"]["required"]["clauses"][0]
    )
    assert (
        restore_job_assessment(
            stored["sources"][0], stored["assessments"][0]["assessment"]
        )
        == result.jobs[0]
    )
    assert result.calculation_id == result.calculation_snapshot_id
    assert result.model_dump(mode="json")["calculation_snapshot_id"].startswith(
        "matching-"
    )


def test_pre_level_contract_compact_row_remains_readable():
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/job_matching_pre_level_contract.json"
        ).read_text(encoding="utf-8")
    )

    restored = restore_job_assessment(fixture["source"], fixture["assessment"])

    assert restored.job.job_id == "job-1"
    assert restored.required_status == "FULL"


def test_pre_level_contract_embedded_v1_keeps_historical_hash():
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/job_matching_pre_level_contract.json"
        ).read_text(encoding="utf-8")
    )

    restored = validate_job_matching(fixture["embedded_v1"])

    assert restored.calculation_snapshot_id == (
        "matching-4b5d0e14b636479939959b9513409dcb57784142171fe02888c5eac1c6bc46ac"
    )


def test_storage_budget_fails_the_whole_result_without_truncation(monkeypatch):
    result = build_job_matching(
        build_cohort(batch(posting()), criteria()),
        levelled_analysis(),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    monkeypatch.setattr("job.matching.MAX_MATCHING_RESULT_BYTES", 1)

    with pytest.raises(MatchingResultTooLarge):
        matching_storage_rows(result)
    with pytest.raises(MatchingResultTooLarge):
        validate_job_matching(result.model_dump(mode="json"))


def test_tolerated_nested_ratio_rounding_does_not_change_calculation_id():
    result = build_job_matching(
        build_cohort(batch(posting(required=("Java", "Docker", "Redis"))), criteria()),
        levelled_analysis(),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    payload = result.model_dump(mode="json")
    assert payload["jobs"][0]["required"]["fulfillment_ratio"] == 1 / 3
    payload["jobs"][0]["required"]["fulfillment_ratio"] = 0.333333

    restored = validate_job_matching(payload)

    assert restored.calculation_snapshot_id == result.calculation_snapshot_id
    assert restored.model_dump(mode="json") == result.model_dump(mode="json")
