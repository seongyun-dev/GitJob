"""Partial matching never converts unknown evidence into missing skill."""

import math

import pytest
from test_job_cohort import batch, criteria, posting
from test_recommendation_engine import make_analysis

from job.cohort import JobCohort, build_cohort
from job.matching import (
    ConditionAssessment,
    MatchingResultTooLarge,
    build_job_matching,
    evaluate_clause,
    matching_storage_rows,
    restore_job_assessment,
    validate_job_matching,
)
from job.requirements import RequirementClause, RequirementEvidence
from recommendation.evidence import HeldStatus


def test_partial_result_explains_non_requirement_strict_review_reason():
    cohort = build_cohort(batch(posting(general=("Cobol",))), criteria())
    result = build_job_matching(
        cohort, make_analysis(), user_id="user-1", analysis_id="analysis-1"
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


def test_partial_and_preferred_separate_from_strict_matching():
    cohort = build_cohort(
        batch(posting(required=("Java", "Docker"), preferred=("Redis",))), criteria()
    )
    result = build_job_matching(
        cohort, make_analysis(), user_id="user-1", analysis_id="analysis-1"
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
        cohort, make_analysis(), user_id="user-1", analysis_id="analysis-1"
    )
    row = result.jobs[0]
    assert row.required.satisfied_count == 1
    assert row.required.unresolved
    assert row.required.fulfillment_ratio is None
    assert row.required_status == "UNKNOWN"
    assert not row.job.strict_match_eligible


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
        make_analysis(),
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


def test_storage_budget_fails_the_whole_result_without_truncation(monkeypatch):
    result = build_job_matching(
        build_cohort(batch(posting()), criteria()),
        make_analysis(),
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
        make_analysis(),
        user_id="user-1",
        analysis_id="analysis-1",
    )
    payload = result.model_dump(mode="json")
    assert payload["jobs"][0]["required"]["fulfillment_ratio"] == 1 / 3
    payload["jobs"][0]["required"]["fulfillment_ratio"] = 0.333333

    restored = validate_job_matching(payload)

    assert restored.calculation_snapshot_id == result.calculation_snapshot_id
    assert restored.model_dump(mode="json") == result.model_dump(mode="json")
