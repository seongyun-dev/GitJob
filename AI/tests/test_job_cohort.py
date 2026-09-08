from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from job.cohort import CohortCriteria, JobCohort, build_cohort
from job.collector.technology import extract_technology_mentions
from job.contracts import JobAnalysisInputBatch, JobPostingInput
from registry.contracts import load_registry
from registry.mapper import RegistryMapper


def posting(
    identifier="job-1",
    *,
    required=("Java",),
    preferred=(),
    general=(),
    required_text=None,
    **changes,
):
    lines = []
    mentions = []
    for names, requirement, section in (
        (required, "REQUIRED", "자격요건"),
        (preferred, "PREFERRED", "우대사항"),
        (general, "MENTIONED", "기술스택"),
    ):
        if not names:
            continue
        text = (
            required_text
            if requirement == "REQUIRED" and required_text
            else ", ".join(names)
        )
        lines.extend((section, text))
        mentions.extend(
            {
                "raw_technology": name,
                "technology_id": None,
                "requirement_type": requirement,
                "source_surface": "BODY",
                "evidence_section": section,
                "evidence_text": text,
                "extraction_method": "TEST",
            }
            for name in names
        )
    body = "\n".join(lines) or "채용 안내"
    payload = {
        "source_record_id": identifier,
        "source_site": "SARAMIN",
        "source_posting_id": identifier,
        "source_url": f"https://example.com/{identifier}",
        "company_name": "Example",
        "title": "백엔드 개발자",
        "raw_job_category": "BACKEND",
        "career_level": "신입",
        "region": "서울",
        "description_text": body,
        "body_status": "TEXT_AVAILABLE",
        "posting_status": "ACTIVE",
        "posted_at": "2026-09-01T00:00:00Z",
        "deadline": "2026-10-01T00:00:00Z",
        "collected_at": "2026-09-07T00:00:00Z",
        "content_hash": sha256(body.encode()).hexdigest(),
        "technology_mentions": mentions,
    }
    payload.update(changes)
    return JobPostingInput.model_validate(payload)


def batch(*records):
    return JobAnalysisInputBatch(
        schema_version="job-analysis-input/v1",
        dataset_snapshot_id="snapshot-1",
        pipeline_run_id="run-1",
        collector_version="collector/v1",
        records=records,
    )


def criteria(**changes):
    return CohortCriteria.model_validate(
        {
            "target_role": "BACKEND_ENGINEER",
            "as_of": "2026-09-08T00:00:00Z",
            **changes,
        }
    )


def test_required_and_or_preferred_and_skill_preserve_original_provenance():
    one = posting(
        required=("Java", "Python"),
        required_text="Java 또는 Python 개발 경험",
        preferred=("Redis",),
        general=("Java",),
    )
    two = posting(
        "job-2",
        required=("Java", "Spring Boot"),
        required_text="Java 및 Spring Boot 경험",
    )
    cohort = build_cohort(batch(one, two), criteria())
    assert cohort.status == "READY"
    assert cohort.criteria.target_role == "BACKEND"
    assert cohort.jobs[0].required_clauses == (("java", "python"),)
    assert cohort.jobs[0].preferred_tech_ids == ("redis",)
    assert cohort.jobs[0].general_tech_ids == ("java",)
    assert cohort.jobs[1].required_clauses == (("java",), ("spring-boot",))
    assert cohort.jobs[0].technologies[0].evidence_text == "Java 또는 Python 개발 경험"
    assert JobCohort.model_validate_json(cohort.model_dump_json()) == cohort


@pytest.mark.parametrize(
    "text,names",
    [
        ("Java/Python 경험", ("Java", "Python")),
        ("Java 및 Python 또는 React", ("Java", "Python", "React")),
        ("Java 또는 Cobol", ("Java",)),
        ("Java 또는 Python 또는 Cobol", ("Java", "Python")),
        ("Java 경험 없어도 가능", ("Java",)),
        ("Java, Python 등 기술 경험", ("Java", "Python")),
        ("Java, Cobol, Python 개발 경험", ("Java", "Python")),
    ],
)
def test_ambiguous_or_incomplete_required_expression_is_reviewed(text, names):
    cohort = build_cohort(
        batch(posting(required=names, required_text=text)), criteria()
    )
    assert not cohort.jobs
    assert cohort.review_count == 1
    assert "REQUIREMENT_LOGIC_UNRESOLVED" in cohort.exclusions[0].reasons


def test_empty_required_and_unknown_do_not_create_vacuously_matching_jobs():
    cohort = build_cohort(
        batch(
            posting(required=(), preferred=("Java",)),
            posting("unknown", required=("Cobol",)),
        ),
        criteria(),
    )
    assert cohort.status == "EMPTY"
    assert cohort.review_count == 2
    assert not cohort.jobs
    assert {reason for item in cohort.exclusions for reason in item.reasons} >= {
        "NO_REQUIRED_TECHNOLOGY",
        "TECHNOLOGY_REVIEW_REQUIRED",
    }
    assert cohort.exclusions[1].technologies[0].raw_technology == "Cobol"


def test_separate_word_evidence_still_uses_full_source_line_for_or():
    original = posting(
        required=("Java", "Python"), required_text="Java 또는 Python 경험"
    )
    payload = original.model_dump(mode="json")
    for item in payload["technology_mentions"]:
        item["evidence_text"] = item["raw_technology"]
    cohort = build_cohort(batch(JobPostingInput.model_validate(payload)), criteria())
    assert cohort.jobs[0].required_clauses == (("java", "python"),)


@pytest.mark.parametrize(
    "prelude",
    [
        "one of the following:",
        "any of the following:",
        "다음 중 하나:",
        "아래 기술 중 하나:\n",
    ],
)
def test_word_mentions_under_adjacent_one_of_prelude_are_reviewed(prelude):
    payload = posting(
        required=("Java", "Python"), required_text=f"{prelude}\nJava\nPython"
    ).model_dump(mode="json")
    for mention in payload["technology_mentions"]:
        mention["evidence_text"] = mention["raw_technology"]
    cohort = build_cohort(batch(JobPostingInput.model_validate(payload)), criteria())
    assert not cohort.jobs
    assert cohort.review_count == 1
    assert "REQUIREMENT_LOGIC_UNRESOLVED" in cohort.exclusions[0].reasons


@pytest.mark.parametrize(
    "text,clauses",
    [
        ("Java, Python 중 하나 경험", (("java", "python"),)),
        ("Java\nPython", (("java",), ("python",))),
        ("One of our product teams is hiring\nJava\nPython", (("java",), ("python",))),
    ],
)
def test_one_of_prelude_guard_preserves_single_line_or_and_ordinary_prose(
    text, clauses
):
    payload = posting(required=("Java", "Python"), required_text=text).model_dump(
        mode="json"
    )
    for mention in payload["technology_mentions"]:
        mention["evidence_text"] = mention["raw_technology"]
    cohort = build_cohort(batch(JobPostingInput.model_validate(payload)), criteria())
    assert cohort.jobs[0].required_clauses == clauses


def test_duplicate_mentions_do_not_turn_located_evidence_into_missing_evidence():
    original = posting()
    payload = original.model_dump(mode="json")
    payload["technology_mentions"] *= 2
    cohort = build_cohort(batch(JobPostingInput.model_validate(payload)), criteria())
    assert cohort.jobs[0].required_clauses == (("java",),)
    assert len(cohort.jobs[0].technologies) == 2


def test_ai_agent_developer_alias_does_not_include_generic_ai_ux_roles():
    cohort = build_cohort(
        batch(
            posting(
                "developer",
                title="[딥테크 선도기업] AI Agent 개발자",
                raw_job_category="AI(인공지능), Python, 소프트웨어개발",
                required=("Python",),
            ),
            posting(
                "designer",
                title="AI 서비스 UX기획자 채용",
                raw_job_category="AI(인공지능), 서비스기획",
                required=("Python",),
            ),
        ),
        criteria(target_role="AI_DATA", min_jobs=2),
    )
    assert [job.job_id for job in cohort.jobs] == ["developer"]
    assert cohort.status == "INSUFFICIENT_DATA"
    assert "ROLE_NOT_MATCHED" in cohort.exclusions[0].reasons


def test_source_collection_time_affecting_quality_also_changes_identity():
    original = build_cohort(batch(posting()), criteria())
    future = build_cohort(
        batch(posting(collected_at="2026-09-09T00:00:00Z")), criteria()
    )
    assert future.cohort_id != original.cohort_id
    assert "COLLECTED_AFTER_AS_OF" in future.exclusions[0].reasons


def test_unknown_comma_list_tail_is_not_silently_ignored():
    cohort = build_cohort(
        batch(posting(required_text="Java, Cobol 개발 경험")), criteria()
    )
    assert not cohort.jobs
    assert "REQUIREMENT_LOGIC_UNRESOLVED" in cohort.exclusions[0].reasons


def test_later_prose_comma_is_not_a_technology_list_tail():
    cohort = build_cohort(
        batch(
            posting(
                required=("Python",),
                required_text="Python 생태계에 능숙하며, AI Application 개발 경험",
            )
        ),
        criteria(),
    )
    assert cohort.jobs[0].required_clauses == (("python",),)


def test_retries_deduplicate_without_collapsing_canonical_duplicate_candidates():
    first = posting(canonical_job_id="same-candidate")
    second = posting("job-2", canonical_job_id="same-candidate", source_site="WORKNET")
    cohort = build_cohort(batch(second, first, first), criteria())
    assert tuple(job.job_id for job in cohort.jobs) == ("job-1", "job-2")
    assert cohort.input_count == 3
    assert cohort.duplicate_count == 1
    assert cohort.excluded_count == 0
    assert cohort.review_count == 0
    assert all(job.canonical_job_id == "same-candidate" for job in cohort.jobs)
    reordered = build_cohort(batch(first, second), criteria())
    assert cohort.cohort_id == reordered.cohort_id


def test_source_identity_content_conflicts_are_not_arbitrarily_overwritten():
    cohort = build_cohort(batch(posting(), posting(required=("Python",))), criteria())
    assert cohort.review_count == 2
    assert not cohort.jobs
    assert all("SOURCE_RECORD_CONFLICT" in item.reasons for item in cohort.exclusions)


def test_source_id_reused_by_another_site_cannot_collide_in_recommendation_ids():
    cohort = build_cohort(batch(posting(), posting(source_site="WORKNET")), criteria())
    assert cohort.review_count == 2
    assert not cohort.jobs


def test_explicit_filters_and_quality_reasons_are_consistent_and_stable():
    records = (
        posting("valid", raw_job_category="백엔드/서버개발, 펌웨어"),
        posting("closed", posting_status="CLOSED"),
        posting("expired", deadline="2026-09-07T23:59:00Z"),
        posting("unknown", posting_status="UNKNOWN"),
        posting("role", raw_job_category="MY_BACKEND_ENGINEERISH", title="엔지니어"),
        posting("missing-role", raw_job_category=None, title="개발자"),
        posting("body", body_status="BLOCKED", description_text=None),
        posting("region", region=None),
        posting("date", posted_at=None),
    )
    cohort = build_cohort(
        batch(*records),
        criteria(
            sources=("saramin",),
            regions=("서울",),
            career_levels=("신입",),
            posted_from="2026-09-01T00:00:00Z",
            posted_to="2026-09-08T00:00:00Z",
            min_jobs=2,
        ),
    )
    assert [job.job_id for job in cohort.jobs] == ["valid"]
    assert cohort.status == "INSUFFICIENT_DATA"
    reasons = {item.source_record_id: item.reasons for item in cohort.exclusions}
    assert "POSTING_CLOSED" in reasons["closed"]
    assert "DEADLINE_PASSED" in reasons["expired"]
    assert "POSTING_STATUS_UNKNOWN" in reasons["unknown"]
    assert "ROLE_NOT_MATCHED" in reasons["role"]
    assert "ROLE_NOT_MATCHED" in reasons["missing-role"]
    assert "BODY_UNAVAILABLE" in reasons["body"]
    assert "REGION_UNKNOWN" in reasons["region"]
    assert "POSTED_AT_UNKNOWN" in reasons["date"]
    assert (
        cohort.input_count
        == len(cohort.jobs)
        + cohort.excluded_count
        + cohort.review_count
        + cohort.duplicate_count
    )


def test_criteria_and_hash_are_immutable_canonical_and_sensitive_to_filters_and_input():
    query = criteria(sources=("saramin", "WORKNET", "SARAMIN"))
    assert query.sources == ("SARAMIN", "WORKNET")
    with pytest.raises(ValidationError):
        query.target_role = "FRONTEND"
    with pytest.raises(ValidationError):
        criteria(as_of="2026-09-08T00:00:00")
    with pytest.raises(ValidationError):
        criteria(posted_from="2026-09-08T00:00:00Z", posted_to="2026-09-01T00:00:00Z")
    first = build_cohort(batch(posting()), criteria())
    assert (
        first.cohort_id
        != build_cohort(batch(posting(required=("Python",))), criteria()).cohort_id
    )
    assert (
        first.cohort_id
        != build_cohort(
            batch(posting()), criteria(as_of=datetime(2026, 9, 9, tzinfo=UTC))
        ).cohort_id
    )
    assert build_cohort(batch(), criteria()).status == "EMPTY"


def test_cohort_deserialization_rejects_a_ready_status_with_no_jobs():
    payload = build_cohort(batch(), criteria()).model_dump(mode="json")
    payload["status"] = "READY"
    with pytest.raises(ValidationError, match="status"):
        JobCohort.model_validate(payload)


@pytest.mark.parametrize(
    "text,names",
    [
        ("Java and Cobol experience", ("Java",)),
        ("Java 및 Cobol 개발 경험", ("Java",)),
        ("Java + Cobol", ("Java",)),
        ("Cobol and Java experience", ("Java",)),
        ("Java and Cobol and Python experience", ("Java", "Python")),
    ],
)
def test_unmapped_explicit_and_operand_is_not_dropped(text, names):
    cohort = build_cohort(
        batch(posting(required=names, required_text=text)), criteria()
    )
    assert cohort.jobs == ()
    assert cohort.review_count == 1
    assert "REQUIREMENT_LOGIC_UNRESOLVED" in cohort.exclusions[0].reasons


@pytest.mark.parametrize("connector", ["and", "및", "+", "&"])
def test_fully_mapped_explicit_and_remains_supported(connector):
    cohort = build_cohort(
        batch(
            posting(
                required=("Java", "Python"),
                required_text=f"Java {connector} Python experience",
            )
        ),
        criteria(),
    )
    assert cohort.jobs[0].required_clauses == (("java",), ("python",))


@pytest.mark.parametrize(
    "text",
    [
        "Java knowledge is not necessary",
        "Java is not a requirement",
        "Java experience not needed",
        "Java 경험 불필요",
        "Java 경험이 없는 분도 지원 가능",
    ],
)
def test_explicit_optional_negation_does_not_create_a_required_gate(text):
    cohort = build_cohort(batch(posting(required_text=text)), criteria())
    assert cohort.jobs == ()
    assert "REQUIREMENT_LOGIC_UNRESOLVED" in cohort.exclusions[0].reasons


def test_negated_required_word_does_not_create_an_eligible_cohort_job():
    cohort = build_cohort(
        batch(posting(required_text="Java 경험은 필수가 아닙니다")), criteria()
    )
    assert cohort.jobs == ()
    assert "TECHNOLOGY_REVIEW_REQUIRED" in cohort.exclusions[0].reasons


def test_multi_technology_minimum_count_does_not_become_required_and():
    cohort = build_cohort(
        batch(
            posting(
                required=("Java", "Python", "Docker"),
                required_text="Java, Python, Docker 중 2가지 이상",
            )
        ),
        criteria(),
    )
    assert cohort.jobs == ()
    assert "TECHNOLOGY_REVIEW_REQUIRED" in cohort.exclusions[0].reasons


@pytest.mark.parametrize(
    "text,names",
    [
        ("Java 경험은 필수가 아닙니다", ("Java",)),
        ("Java, Python, Docker 중 2가지 이상", ("Java", "Python", "Docker")),
        ("Java, Python 중 10가지 이상", ("Java", "Python")),
        ("Java, Python 중 20개 이상", ("Java", "Python")),
        ("Java, Python 중 12개 이상", ("Java", "Python")),
    ],
)
def test_word_only_a_evidence_still_uses_original_line_requirement_logic(text, names):
    payload = posting(required=names, required_text=text).model_dump(mode="json")
    for mention in payload["technology_mentions"]:
        mention["evidence_text"] = mention["raw_technology"]
    cohort = build_cohort(batch(JobPostingInput.model_validate(payload)), criteria())
    assert cohort.jobs == ()
    assert "REQUIREMENT_LOGIC_UNRESOLVED" in cohort.exclusions[0].reasons


def test_company_introduction_python_skill_does_not_inflate_java_requirement():
    body = (
        "담당업무\nJava 서비스 개발\n회사소개:\n"
        "Python 기반 서비스를 운영하는 회사입니다."
    )
    payload = posting(required=()).model_dump(mode="json")
    payload["description_text"] = body
    payload["content_hash"] = sha256(body.encode()).hexdigest()
    payload["technology_mentions"] = [
        mention.model_dump(mode="json", by_alias=True)
        for mention in extract_technology_mentions("백엔드 개발자", body)
    ]
    cohort = build_cohort(batch(JobPostingInput.model_validate(payload)), criteria())
    assert cohort.jobs[0].required_clauses == (("java",),)
    classes = {
        item.raw_technology: item.requirement_class.value
        for item in cohort.jobs[0].technologies
    }
    assert classes == {"Java": "REQUIRED", "Python": "SKILL"}


@pytest.mark.parametrize(
    "text",
    [
        "Java, Python 등을 활용한 백엔드 개발 경험",
        "Java, Python 등의 기술 경험",
    ],
)
def test_korean_etc_particles_keep_required_technology_logic_unresolved(text):
    cohort = build_cohort(
        batch(posting(required=("Java", "Python"), required_text=text)), criteria()
    )
    assert cohort.jobs == ()
    assert "REQUIREMENT_LOGIC_UNRESOLVED" in cohort.exclusions[0].reasons


@pytest.mark.parametrize("text", ["Java 등록 경험", "Java 등급 이해"])
def test_korean_words_starting_with_deung_are_not_etc_markers(text):
    cohort = build_cohort(batch(posting(required_text=text)), criteria())
    assert cohort.jobs[0].required_clauses == (("java",),)


def test_activity_conjunction_mask_applies_to_later_technology_gap_checks():
    cohort = build_cohort(
        batch(
            posting(
                required=("Java", "Python"),
                required_text="Java 개발 및 운영, Python 개발 경험",
            )
        ),
        criteria(),
    )
    assert cohort.jobs[0].required_clauses == (("java",), ("python",))


@pytest.mark.parametrize(
    "raw,text,tech_id",
    [
        ("MySQL", "- MySQL 개발 및 운영", "mysql"),
        ("Linux", "- Linux 환경 구축 및 운용", "linux"),
        ("React", "- 프론트엔드 영역 설계 및 구현 경험 (React 사용)", "react"),
    ],
)
def test_observed_activity_conjunction_does_not_invent_a_missing_technology(
    raw, text, tech_id
):
    ai_root = Path(__file__).resolve().parents[1]
    mapper = RegistryMapper(
        load_registry(
            ai_root / "registry/data/technology_registry_20260908_1.json",
            repository_root=ai_root.parent,
        )
    )
    cohort = build_cohort(
        batch(posting(required=(raw,), required_text=text)), criteria(), mapper
    )
    assert cohort.jobs[0].required_clauses == ((tech_id,),)
    assert cohort.review_count == 0


@pytest.mark.parametrize(
    "text",
    [
        "Java 개발 및 Cobol 운영",
        "Cobol 개발 및 Java 운영",
        "Java 개발 및 운영 및 Cobol",
        "Java 설계 및 Cobol 구현",
    ],
)
def test_activity_words_do_not_hide_an_unmapped_and_operand(text):
    cohort = build_cohort(batch(posting(required_text=text)), criteria())
    assert not cohort.jobs
    assert "REQUIREMENT_LOGIC_UNRESOLVED" in cohort.exclusions[0].reasons


def test_explicit_ai_development_engineer_title_matches_without_generic_ai_tags():
    cohort = build_cohort(
        batch(
            posting(title="AI 개발 엔지니어 (개발 및 유지관리)", raw_job_category=None)
        ),
        criteria(target_role="AI_DATA"),
    )
    assert len(cohort.jobs) == 1
