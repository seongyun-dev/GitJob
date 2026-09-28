"""COHORT/RECOMMENDATION payload에서 mapping_context 반복 저장을 없앤다 · S15P21E102-333.

`mapping_context`는 `title + evidence_section + evidence_text + description_text`를 이어
붙인 문자열이고, 기술 mention 하나마다 한 벌씩 저장돼 왔다. 공고당 평균 2.5개 mention이
있으므로 같은 본문이 공고마다 두세 벌씩 snapshot에 들어간다. 2026-09-18 운영 실측에서
이것이 COHORT payload의 66.4%였다.

그런데 serving은 이 값을 읽지 않는다. BE의 어떤 DTO도 `jobs[].technologies`를 선언하지
않아 Jackson이 통째로 버리고, FE에는 참조가 없다. 값이 필요한 곳은 두 군데뿐이다.

1. `registry.mapper`의 짧은 언어명 판별(`c`/`r`/`go`). 분류 **도중** 메모리에서만 쓴다.
2. `registry_review.record.context`. 사람이 검토하는 비-MATCHED mention의 근거이고,
   `worker.jobs.job_review_records`가 `classify_job_batch`를 따로 호출해 만들므로
   cohort payload와 경로가 다르다.

그래서 분류 결과 객체는 그대로 두고 **cohort에 싣는 사본에서만** 비운다. 필드를 지우지
않는 이유는 기존 snapshot 때문이다. `TechnologyClassification`과 `CohortModel`이
`extra="forbid"`이고 `worker.api`가 과거 payload를 `model_validate`하므로, 필드가 사라지면
이미 저장된 COHORT·RECOMMENDATION을 다시 읽을 수 없다.
"""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from job.classifier import classify_job_batch
from job.cohort import CohortCriteria, JobCohort, build_cohort
from job.contracts import JobAnalysisInputBatch, JobPostingInput
from job.demand import aggregate_demand
from registry.contracts import load_registry
from registry.mapper import RegistryMapper
from registry.review import build_records

AI_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = load_registry(
    AI_ROOT / "registry/data/technology_registry_v1.json",
    repository_root=AI_ROOT.parent,
)

# 본문에만 있고 evidence_text에는 없는 문장. payload에 남아 있으면 본문이 다시 실린 것이다.
BODY_MARKER = "이문장은본문에만있고증거줄에는없다"


def mapper():
    return RegistryMapper(REGISTRY)


def posting(
    identifier="job-1",
    *,
    required=("Java",),
    title="백엔드 개발자",
    evidence=None,
    **changes,
):
    section = "자격요건"
    text = evidence or ", ".join(required)
    body = f"{section}\n{text}\n{BODY_MARKER}"
    payload = {
        "source_record_id": identifier,
        "source_site": "SARAMIN",
        "source_posting_id": identifier,
        "source_url": f"https://example.com/{identifier}",
        "company_name": "Example",
        "title": title,
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
        "technology_mentions": [
            {
                "raw_technology": name,
                "technology_id": None,
                "requirement_type": "REQUIRED",
                "source_surface": "BODY",
                "evidence_section": section,
                "evidence_text": text,
                "extraction_method": "TEST",
            }
            for name in required
        ],
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
        {"target_role": "BACKEND_ENGINEER", "as_of": "2026-09-08T00:00:00Z", **changes}
    )


def technologies_in(items):
    return [technology for item in items for technology in item["technologies"]]


# ---------------------------------------------------------------------------
# 1. 새 snapshot에는 full mapping_context가 없다
# ---------------------------------------------------------------------------


def test_new_cohort_payload_does_not_carry_mapping_context():
    cohort = build_cohort(batch(posting()), criteria(), mapper())
    payload = cohort.model_dump(mode="json")

    technologies = technologies_in(payload["jobs"])
    assert technologies, "테스트가 성립하려면 기술 분류가 하나는 있어야 한다"
    assert all("mapping_context" not in item for item in technologies)


def test_new_cohort_payload_does_not_repeat_the_posting_body():
    cohort = build_cohort(
        batch(posting(required=("Java", "Python"))), criteria(), mapper()
    )

    assert BODY_MARKER not in cohort.model_dump_json()


def test_excluded_postings_also_drop_mapping_context():
    # exclusions가 COHORT payload의 96%를 차지하므로 여기가 본체다.
    cohort = build_cohort(
        batch(posting("job-x", raw_job_category="회계", title="회계 담당자")),
        criteria(),
        mapper(),
    )

    assert cohort.exclusions, "역할 불일치로 제외된 공고가 있어야 한다"
    payload = cohort.model_dump(mode="json")
    technologies = technologies_in(payload["exclusions"])
    assert technologies
    assert all("mapping_context" not in item for item in technologies)
    assert BODY_MARKER not in cohort.model_dump_json()


def test_recommendation_embedded_jobs_carry_no_mapping_context():
    # recommendation snapshot은 cohort.jobs를 그대로 담는다(recommendation/engine.py).
    # cohort 쪽에서 비워지면 recommendation도 함께 줄어든다.
    cohort = build_cohort(batch(posting()), criteria(), mapper())

    dumped = [job.model_dump(mode="json") for job in cohort.jobs]
    technologies = technologies_in(dumped)
    assert technologies
    assert all("mapping_context" not in item for item in technologies)
    assert BODY_MARKER not in str(dumped)


# ---------------------------------------------------------------------------
# 2. 기존 snapshot은 계속 읽힌다
# ---------------------------------------------------------------------------


def test_historical_payload_with_mapping_context_still_validates():
    cohort = build_cohort(batch(posting()), criteria(), mapper())
    payload = cohort.model_dump(mode="json")
    for job in payload["jobs"]:
        for technology in job["technologies"]:
            technology["mapping_context"] = "예전 snapshot에 저장돼 있던 전체 문맥"

    restored = JobCohort.model_validate(payload)

    assert restored.jobs[0].technologies[0].mapping_context == (
        "예전 snapshot에 저장돼 있던 전체 문맥"
    )


def test_historical_exclusion_payload_with_mapping_context_still_validates():
    cohort = build_cohort(
        batch(posting("job-x", raw_job_category="회계", title="회계 담당자")),
        criteria(),
        mapper(),
    )
    payload = cohort.model_dump(mode="json")
    for item in payload["exclusions"]:
        for technology in item["technologies"]:
            technology["mapping_context"] = "예전 값"

    restored = JobCohort.model_validate(payload)

    assert restored.exclusions[0].technologies[0].mapping_context == "예전 값"


# ---------------------------------------------------------------------------
# 3. 분류 결과와 근거는 그대로다
# ---------------------------------------------------------------------------


def test_classification_keeps_the_evidence_fields_serving_actually_uses():
    cohort = build_cohort(batch(posting(required=("Java",))), criteria(), mapper())
    technology = cohort.jobs[0].technologies[0]

    assert technology.tech_id == "java"
    assert technology.match_status.value == "MATCHED"
    assert technology.requirement_class.value == "REQUIRED"
    assert technology.evidence_text == "Java"
    assert technology.evidence_section == "자격요건"
    assert technology.registry_version
    assert technology.parser_version


def test_classify_job_batch_still_computes_mapping_context_in_memory():
    # mapper와 registry review가 이 값을 쓴다. 분류 단계에서 사라지면 안 된다.
    classified = classify_job_batch(batch(posting()), mapper())
    technology = classified.records[0].technologies[0]

    assert BODY_MARKER in technology.mapping_context
    assert technology.evidence_text in technology.mapping_context
    assert "백엔드 개발자" in technology.mapping_context


def test_mapping_context_is_regenerable_from_the_immutable_source():
    source = batch(posting())
    first = classify_job_batch(source, mapper()).records[0].technologies[0]
    second = classify_job_batch(source, mapper()).records[0].technologies[0]

    assert first.mapping_context == second.mapping_context
    assert BODY_MARKER in first.mapping_context


# ---------------------------------------------------------------------------
# 4. 짧은 언어명 판별은 문맥에 의존한다 — 계속 동작해야 한다
# ---------------------------------------------------------------------------


def test_short_language_names_still_resolve_through_the_mapper():
    for raw, expected in (("Go", "go"), ("C", "c"), ("R", "r")):
        classified = classify_job_batch(
            batch(
                posting(f"job-{raw}", required=(raw,), evidence=f"{raw} 언어 개발 경험")
            ),
            mapper(),
        )
        technology = classified.records[0].technologies[0]

        assert technology.raw_technology == raw
        assert technology.tech_id == expected
        assert technology.match_status.value == "MATCHED"


# ---------------------------------------------------------------------------
# 5. registry review의 context는 보존된다
# ---------------------------------------------------------------------------


def test_registry_review_record_still_stores_the_full_context():
    classified = classify_job_batch(
        batch(posting(required=("존재하지않는기술이름",))), mapper()
    )
    records = build_records(classified, attempted_at=datetime(2026, 9, 18, tzinfo=UTC))

    assert records, "MATCHED가 아닌 mention은 review 대상이어야 한다"
    assert BODY_MARKER in records[0].context
    assert records[0].evidence_text == "존재하지않는기술이름"


# ---------------------------------------------------------------------------
# 6. demand 결과는 변하지 않는다
# ---------------------------------------------------------------------------


def test_demand_aggregation_is_unchanged():
    cohort = build_cohort(batch(posting(), posting("job-2")), criteria(), mapper())
    demand = aggregate_demand(cohort)

    assert demand.denominator == len(cohort.jobs)
    assert demand.input_count == 2
    assert demand.excluded_count == 0
    assert any(item.tech_id == "java" for item in demand.technologies)
