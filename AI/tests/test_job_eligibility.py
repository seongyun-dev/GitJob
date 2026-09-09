"""Semantic region and career filters for hiring cohorts."""

from __future__ import annotations

from hashlib import sha256

import pytest

from job.cohort import CohortCriteria, build_cohort
from job.contracts import JobAnalysisInputBatch, JobPostingInput
from job.eligibility import FilterMatch, match_career_level, match_region


@pytest.mark.parametrize(
    ("value", "allowed"),
    [
        ("서울 강남구", ("서울",)),
        ("서울특별시", ("서울",)),
        ("경기도 성남시 / 서울특별시 강남구", ("서울",)),
        ("서울", ("서울특별시",)),
    ],
)
def test_region_variants_and_multi_region_candidates_match(value, allowed):
    assert match_region(value, allowed) is FilterMatch.MATCHED


def test_region_comparison_does_not_match_an_address_substring():
    assert match_region("경기도 광주시 서울로 12", ("서울",)) is FilterMatch.NOT_MATCHED


def test_unknown_region_is_not_a_definite_mismatch():
    assert match_region("원격 협의", ("서울",)) is FilterMatch.UNKNOWN


@pytest.mark.parametrize("value", ["신입", "신입·경력", "경력무관"])
def test_career_labels_that_permit_entry_level_match(value):
    assert match_career_level(value, ("신입",)) is FilterMatch.MATCHED


def test_experienced_only_is_a_definite_entry_level_mismatch():
    assert match_career_level("경력 3년 이상", ("신입",)) is FilterMatch.NOT_MATCHED


def test_unknown_career_is_not_a_definite_mismatch():
    assert match_career_level("협의", ("신입",)) is FilterMatch.UNKNOWN


def test_worknet_labelled_experience_and_preference_are_not_conflated():
    assert (
        match_career_level("경력 (최소 3년 이상) 필수", ("신입",))
        is FilterMatch.NOT_MATCHED
    )
    assert (
        match_career_level("경력 (최소 6개월 이상)", ("경력",)) is FilterMatch.MATCHED
    )
    assert (
        match_career_level("경력 (최소 3년 이상) 우대", ("신입",))
        is FilterMatch.UNKNOWN
    )
    assert (
        match_career_level("신입 , 경력 (최소 3년 이상)", ("신입",))
        is FilterMatch.MATCHED
    )
    assert (
        match_career_level("경력무관(신입불가)", ("신입",)) is FilterMatch.NOT_MATCHED
    )


def _posting(identifier: str, *, region: str, career_level: str) -> JobPostingInput:
    body = "자격요건\nJava 경험 필수"
    return JobPostingInput.model_validate(
        {
            "source_record_id": identifier,
            "source_site": "SARAMIN",
            "source_posting_id": identifier,
            "source_url": f"https://example.com/{identifier}",
            "company_name": "Example",
            "title": "백엔드 개발자",
            "raw_job_category": "BACKEND",
            "career_level": career_level,
            "region": region,
            "description_text": body,
            "body_status": "TEXT_AVAILABLE",
            "posting_status": "ACTIVE",
            "posted_at": "2026-09-01T00:00:00Z",
            "deadline": "2026-10-01T00:00:00Z",
            "collected_at": "2026-09-07T00:00:00Z",
            "content_hash": sha256(f"{identifier}:{body}".encode()).hexdigest(),
            "technology_mentions": [
                {
                    "raw_technology": "Java",
                    "technology_id": None,
                    "requirement_type": "REQUIRED",
                    "source_surface": "BODY",
                    "evidence_section": "자격요건",
                    "evidence_text": "Java 경험 필수",
                    "extraction_method": "TEST",
                }
            ],
        }
    )


def test_cohort_distinguishes_semantic_matches_unknowns_and_mismatches():
    records = (
        _posting("matched", region="서울특별시 강남구", career_level="경력무관"),
        _posting("unknown", region="원격 협의", career_level="협의"),
        _posting("mismatch", region="부산광역시", career_level="경력 3년 이상"),
    )
    cohort = build_cohort(
        JobAnalysisInputBatch(
            schema_version="job-analysis-input/v1",
            dataset_snapshot_id="snapshot-eligibility",
            pipeline_run_id="run-eligibility",
            collector_version="collector/v1",
            records=records,
        ),
        CohortCriteria.model_validate(
            {
                "target_role": "BACKEND",
                "as_of": "2026-09-08T00:00:00Z",
                "regions": ["서울"],
                "career_levels": ["신입"],
            }
        ),
    )

    assert [job.job_id for job in cohort.jobs] == ["matched"]
    reasons = {item.source_record_id: item.reasons for item in cohort.exclusions}
    assert {"REGION_UNKNOWN", "CAREER_LEVEL_UNKNOWN"} <= set(reasons["unknown"])
    assert {"REGION_NOT_MATCHED", "CAREER_LEVEL_NOT_MATCHED"} <= set(
        reasons["mismatch"]
    )
