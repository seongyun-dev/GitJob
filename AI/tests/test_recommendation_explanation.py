import pytest
from test_job_cohort import batch, criteria, posting
from test_recommendation_engine import make_analysis, recommend

from job.cohort import build_cohort
from recommendation.engine import (
    EXPANDED_ALGORITHM_VERSIONS,
    build_recommendations,
    list_related_jobs,
)
from recommendation.evidence import EvidenceAnalysis
from recommendation.explanation import Explanation, explain_recommendations


def test_explanation_counts_and_sources_come_from_the_same_snapshot():
    result = recommend()
    explanation = explain_recommendations(result)
    assert explanation.snapshot_id == result.snapshot_id
    assert explanation.mode == "RULE"
    for candidate in result.candidates:
        facts = {
            fact.kind: fact
            for fact in explanation.facts
            if fact.tech_id == candidate.tech_id
        }
        assert facts["DEMAND"].values["denominator"] == result.demand.denominator
        assert facts["DEMAND"].values["total_count"] == candidate.demand.total_count
        what_if = facts["WHAT_IF"]
        assert what_if.values["current_count"] == candidate.what_if.current_count
        assert what_if.values["projected_count"] == candidate.what_if.projected_count
        assert what_if.values["increased_count"] == len(
            candidate.what_if.newly_matched_job_ids
        )
        assert set(what_if.source_refs) == {
            str(job.source_url)
            for job in result.jobs
            if job.job_id in candidate.what_if.newly_matched_job_ids
        }
    assert Explanation.model_validate_json(explanation.model_dump_json()) == explanation


def test_external_plan_cannot_add_text_change_numbers_or_reuse_another_snapshot():
    result = recommend()
    original = explain_recommendations(result)
    plan = {
        "schema_version": "explanation-order/v1",
        "snapshot_id": result.snapshot_id,
        "fact_ids": [fact.fact_id for fact in reversed(original.facts)],
    }
    reordered = explain_recommendations(result, narrative_plan=plan)
    assert reordered.mode == "GROUNDED_SELECTION"
    assert reordered.facts == tuple(reversed(original.facts))
    invalid = [
        {**plan, "text": "합격 확률 100%"},
        {**plan, "snapshot_id": "other"},
        {**plan, "fact_ids": plan["fact_ids"][:-1]},
        {**plan, "fact_ids": plan["fact_ids"] + ["invented"]},
        {**plan, "fact_ids": plan["fact_ids"] + plan["fact_ids"][:1]},
    ]
    for value in invalid:
        fallback = explain_recommendations(result, narrative_plan=value)
        assert fallback.mode == "RULE"
        assert fallback.fallback_reason == "INVALID_NARRATIVE_PLAN"
        assert fallback.facts == original.facts


def test_project_participation_is_not_described_as_self_authorship():
    payload = make_analysis().model_dump(mode="json")
    payload["repositories"][0]["technologies"][0].update(
        evidence_level="L2", implemented_by="OTHER"
    )
    for proof in payload["repositories"][0]["technologies"][0]["proofs"]:
        if proof["kind"] == "IMPLEMENTATION":
            proof["attribution"] = "OTHER"
    result = recommend(analysis=EvidenceAnalysis.model_validate(payload))
    explanation = explain_recommendations(result)
    texts = [fact.text for fact in explanation.facts if fact.kind == "EVIDENCE"]
    assert any("참여한 프로젝트" in text for text in texts)
    assert all("직접 작성" not in text for text in texts)


def test_failed_peer_and_unrelated_fact_never_support_positive_evidence_sentence():
    from copy import deepcopy

    payload = make_analysis().model_dump(mode="json")
    failed = deepcopy(payload["repositories"][0])
    failed.update(
        repository_id="failed-repo",
        repository_analysis_id="failed-analysis",
        status="FAILED",
        coverage_complete=False,
    )
    for proof in failed["technologies"][0]["proofs"]:
        proof.update(
            repository_id="failed-repo",
            repository_analysis_id="failed-analysis",
            source_ref="b-evidence://failed-repo/rejected",
        )
    payload["repositories"].append(failed)
    result = recommend(analysis=EvidenceAnalysis.model_validate(payload))
    fact = next(
        fact
        for fact in explain_recommendations(result).facts
        if fact.kind == "EVIDENCE" and fact.tech_id == "java"
    )
    assert fact.source_refs == ("b-evidence://repo-1/IMPLEMENTATION/1",)
    assert fact.values["fact_ids"] == ["fact-IMPLEMENTATION-1"]
    assert all(
        scope["repository_id"] == "repo-1" for scope in fact.values["supporting_scope"]
    )
    assert (
        len(fact.values["profiles"]) == 2
    )  # rejected scope remains inspectable, not cited


def test_l1_explanation_describes_confirmed_observation_not_self_implementation():
    from test_evidence_profiles import profile_payload

    result = recommend(analysis=EvidenceAnalysis.model_validate(profile_payload("L1")))
    fact = next(
        fact
        for fact in explain_recommendations(result).facts
        if fact.kind == "EVIDENCE" and fact.tech_id == "java"
    )
    assert "직접 의존성" in fact.text
    assert "추천 계산에 포함" in fact.text
    assert "직접 작성" not in fact.text
    assert set(fact.source_refs) == {
        "b-evidence://repo-1/DIRECT_DEPENDENCY/1",
        "b-evidence://repo-1/PARTICIPATION/1",
    }


def test_proofless_legacy_input_cannot_generate_positive_source_claims():
    from test_evidence_consumption import legacy_analysis_payload

    result = recommend(
        analysis=EvidenceAnalysis.model_validate(legacy_analysis_payload())
    )
    fact = next(
        fact
        for fact in explain_recommendations(result).facts
        if fact.kind == "EVIDENCE" and fact.tech_id == "java"
    )
    assert "미확정" in fact.text
    assert fact.source_refs == ()
    assert fact.values["fact_ids"] == []


# --- S15P21E102-361: 설명의 공고 조회원은 계산에 쓴 집합과 같아야 한다 -----------
#
# Production 장애 재현. 확장(matching) 경로에서 What-if 의 `newly_matched_job_ids`
# 는 `matching_jobs` 로 계산되는데 설명은 `jobs` 만 조회해 KeyError 로 죽었다.
# 실측: snapshot.jobs 25건 / snapshot.matching_jobs 556건, 문제 공고는 후자에만 존재.


def matching_only_cohort():
    """strict 집합에는 없고 matching 집합에만 있는 공고를 가진 코호트.

    `general` 의 기술이 검토 대상이면 그 공고는 `TECHNOLOGY_REVIEW_REQUIRED` 로
    strict `jobs` 에서 빠지지만, 필수 절은 그대로 남아 `matching_jobs` 에는
    ELIGIBLE 로 들어간다. 그래서 docker 를 더하면 이 공고가 새로 부합한다.
    """
    return build_cohort(
        batch(
            posting("strict-java", required=("Java",)),
            posting(
                "matching-only-docker",
                required=("Docker",),
                general=("Quantum Flux",),
            ),
        ),
        criteria(),
    )


def recommend_for(cohort):
    payload = make_analysis().model_dump(mode="json")
    payload["registry_version"] = cohort.registry_version
    return build_recommendations(
        cohort,
        EvidenceAnalysis.model_validate(payload),
        user_id="user-1",
        analysis_id="analysis-1",
    )


def test_what_if_sources_use_the_job_set_the_counts_were_computed_over():
    cohort = matching_only_cohort()
    result = recommend_for(cohort)
    # 재현 조건이 실제로 성립하는지 먼저 고정한다. 이게 깨지면 아래 검증은 무의미하다.
    assert len(result.jobs) == 1
    assert len(result.matching_jobs or ()) == 2
    docker = next(item for item in result.candidates if item.tech_id == "docker")
    assert docker.impact.affected_job_ids == ("matching-only-docker",)
    assert "matching-only-docker" not in {job.job_id for job in result.jobs}

    fact = next(
        fact
        for fact in explain_recommendations(result).facts
        if fact.kind == "IMPACT" and fact.tech_id == "docker"
    )
    assert fact.values["required_job_ids"] == ["matching-only-docker"]
    assert fact.text == "docker 관련 공고 1건(필수 1건 · 우대 0건)."
    assert "충족" not in fact.text
    # 근거 URL 은 그 공고의 것이어야 한다. 숫자만 맞고 출처가 비면 설명이 아니다.
    matching = {job.job_id: job for job in result.matching_jobs or ()}
    assert fact.source_refs == (str(matching["matching-only-docker"].source_url),)


def test_related_jobs_page_and_explanation_read_the_same_job_set():
    result = recommend_for(matching_only_cohort())
    page = list_related_jobs(result, user_id="user-1", view="IMPACT", tech_id="docker")
    fact = next(
        fact
        for fact in explain_recommendations(result).facts
        if fact.kind == "IMPACT" and fact.tech_id == "docker"
    )
    assert tuple(item.job_id for item in page.items) == tuple(
        fact.values["required_job_ids"]
    )
    assert fact.source_refs == tuple(str(item.source_url) for item in page.items)


def test_legacy_snapshot_explanation_still_reads_the_strict_job_set():
    """확장 입력이 없는 계산은 예전 그대로 `jobs` 를 본다."""
    result = recommend()
    assert result.matching_jobs is None
    assert result.algorithm_version not in EXPANDED_ALGORITHM_VERSIONS
    docker = next(item for item in result.candidates if item.tech_id == "docker")
    jobs = {job.job_id: job for job in result.jobs}
    fact = next(
        fact
        for fact in explain_recommendations(result).facts
        if fact.kind == "WHAT_IF" and fact.tech_id == "docker"
    )
    assert fact.source_refs == tuple(
        str(jobs[job_id].source_url) for job_id in docker.what_if.newly_matched_job_ids
    )


def test_a_job_id_in_neither_set_still_fails_fast():
    """조회원을 넓히는 것이지 없는 공고를 눈감아 주는 것이 아니다.

    계산에 쓴 집합에도 없는 ID 가 나오면 그것은 snapshot 이 깨졌다는 뜻이므로,
    조용히 건너뛰지 않고 지금처럼 그대로 실패해야 한다.
    """
    result = recommend_for(matching_only_cohort())
    lookup = {job.job_id: job for job in result.calculation_jobs}
    with pytest.raises(KeyError):
        lookup["NOWHERE:1"]
