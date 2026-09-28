"""Current market technology demand over every valid posting, not a role cohort.

The market snapshot answers "what do the postings we hold ask for right now".
It is deliberately not the matching population: a posting that matches no
supported role still competes for the same technologies, so it stays in the
denominator. It is also not a period, so it never promises posting-date
semantics.
"""

import pytest
from job.cohort import CohortCriteria, CohortPurpose, build_cohort
from job.demand import DemandSnapshot, aggregate_demand
from pydantic import ValidationError
from test_job_cohort import batch, posting


def market(**changes):
    return CohortCriteria.model_validate(
        {"purpose": "CURRENT_MARKET", "as_of": "2026-09-08T00:00:00Z", **changes}
    )


def backend(**changes):
    return CohortCriteria.model_validate(
        {
            "target_role": "BACKEND_ENGINEER",
            "as_of": "2026-09-08T00:00:00Z",
            **changes,
        }
    )


def tech(demand, tech_id):
    return next(row for row in demand.technologies if row.tech_id == tech_id)


# --- criteria contract -------------------------------------------------------


def test_market_criteria_reject_a_target_role():
    """A role would make it a role cohort, and the lineage would then lie."""
    with pytest.raises(ValidationError, match="CURRENT_MARKET"):
        market(target_role="BACKEND_ENGINEER")


def test_non_market_criteria_still_require_a_target_role():
    with pytest.raises(ValidationError, match="target_role"):
        CohortCriteria.model_validate({"as_of": "2026-09-08T00:00:00Z"})


def test_market_criteria_reject_a_posting_period():
    """A current snapshot is not a period and must not imply posting dates."""
    with pytest.raises(ValidationError, match="CURRENT_MARKET"):
        market(posted_from="2026-08-01T00:00:00Z", posted_to="2026-09-01T00:00:00Z")


def test_market_criteria_omit_role_from_stored_json():
    """Existing snapshots keep their byte shape; the new field is additive."""
    assert "target_role" not in market().model_dump(mode="json")
    assert backend().model_dump(mode="json")["target_role"] == "BACKEND"


# --- population --------------------------------------------------------------


def test_market_population_keeps_postings_that_match_no_role():
    """The whole point: role mismatch must not shrink the market denominator."""
    inputs = batch(
        posting("kept", required=("Java",)),
        posting(
            "other-role",
            required=("Java",),
            raw_job_category="디자인",
            title="그래픽 디자이너",
        ),
    )
    role_cohort = build_cohort(inputs, backend())
    market_cohort = build_cohort(inputs, market())

    assert any("ROLE_NOT_MATCHED" in row.reasons for row in role_cohort.exclusions)
    assert not any(
        "ROLE_NOT_MATCHED" in row.reasons for row in market_cohort.exclusions
    )
    assert aggregate_demand(market_cohort).denominator == 2


def test_market_denominator_counts_every_valid_distinct_posting():
    """Postings with no resolvable requirement stay in the denominator."""
    inputs = batch(
        posting("with-tech", required=("Java",)),
        posting("no-tech", required=()),
        posting(
            "unavailable",
            required=(),
            body_status="IMAGE_ONLY",
            raw_artifact_uri="hdfs:///gitjob/raw/jobs/saramin/unavailable.html",
        ),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    assert demand.denominator == 3
    assert tech(demand, "java").total_count == 1
    assert tech(demand, "java").total_ratio == 1 / 3


def test_market_counts_each_posting_once_per_technology():
    """Repeating a technology in one posting is still one posting."""
    inputs = batch(
        posting("dup", required=("Java",), preferred=("Java",)),
        posting("solo", required=("Java",)),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    assert tech(demand, "java").total_count == 2
    assert tech(demand, "java").total_count <= demand.denominator


# --- technology inclusion rule ----------------------------------------------


def test_market_includes_required_and_preferred_only():
    """MENTIONED is a sighting, not a requirement, so it never becomes demand."""
    inputs = batch(
        posting("req", required=("Java",)),
        posting("pref", required=(), preferred=("Python",)),
        posting("mentioned", required=(), general=("Redis",)),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    counted = {row.tech_id for row in demand.technologies}
    assert {"java", "python"} <= counted
    assert "redis" not in counted
    assert all(row.general_count == 0 for row in demand.technologies)


def test_market_excludes_technologies_the_registry_cannot_resolve():
    """An unmapped mention has no tech_id, so it cannot be ranked."""
    demand = aggregate_demand(
        build_cohort(
            batch(posting("unknown", required=("존재하지않는기술",))), market()
        )
    )
    assert demand.denominator == 1
    assert demand.technologies == ()


def test_market_separates_required_and_preferred_counts():
    inputs = batch(
        posting("a", required=("Java",), preferred=("Python",)),
        posting("b", required=("Python",)),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    python = tech(demand, "python")
    assert (python.required_count, python.preferred_count) == (1, 1)
    assert python.total_count == 2


# --- scope filters leave the market, quality gates do not -------------------


def four_sites():
    """One distinct job per site.

    The titles differ on purpose. These are five separate jobs that happen to
    share the fixture's company and region, and since S15P21E102-352 a
    JobKorea/Saramin pair identical in company, title, region and deadline is
    counted once -- which would silently change what the scope-filter tests
    below are measuring.
    """

    return batch(
        posting(
            "jk", required=("Java",), source_site="JOBKOREA", title="백엔드 개발자"
        ),
        posting(
            "sr", required=("Java",), source_site="SARAMIN", title="플랫폼 엔지니어"
        ),
        posting("wn", required=("Java",), source_site="WORKNET", title="서버 개발자"),
        posting(
            "gj", required=("Java",), source_site="GAMEJOB", title="게임 서버 개발자"
        ),
        posting(
            "cr", required=("Java",), source_site="CAREER", title="시스템 엔지니어"
        ),
    )


def test_official_two_sources_leave_the_other_sites_out_of_the_market():
    """A source we do not serve is not part of our market, denominator included."""
    demand = aggregate_demand(
        build_cohort(four_sites(), market(sources=["JOBKOREA", "SARAMIN"]))
    )
    assert demand.denominator == 2
    assert tech(demand, "java").total_count == 2
    assert tech(demand, "java").total_ratio == 1.0


def test_unfiltered_market_still_counts_every_source():
    demand = aggregate_demand(build_cohort(four_sites(), market()))
    assert demand.denominator == 5


def test_region_and_career_filters_also_narrow_the_market():
    """Same rule as sources: the caller's declared scope defines the market."""
    inputs = batch(
        posting("seoul", required=("Java",), region="서울"),
        posting("busan", required=("Java",), region="부산"),
    )
    demand = aggregate_demand(build_cohort(inputs, market(regions=["서울"])))
    assert demand.denominator == 1


def test_observations_after_the_cutoff_are_not_in_the_market():
    """A posting we had not observed yet cannot be in a snapshot of right now."""
    inputs = batch(
        posting("seen", required=("Java",)),
        posting("later", required=("Java",), collected_at="2026-09-09T00:00:00Z"),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    assert demand.denominator == 1


def test_quality_exclusions_stay_in_the_market_denominator():
    """Unreadable or unresolved postings are still postings in this market."""
    inputs = batch(
        posting("ok", required=("Java",)),
        posting("no-tech", required=()),
        posting(
            "no-body",
            required=(),
            body_status="IMAGE_ONLY",
            raw_artifact_uri="hdfs:///gitjob/raw/jobs/saramin/no-body.html",
        ),
        posting("unknown-status", required=("Java",), posting_status="UNKNOWN"),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))
    assert demand.denominator == 4
    assert tech(demand, "java").total_count == 2


def test_market_never_produces_a_role_exclusion():
    """target_role is absent, so ROLE_NOT_MATCHED cannot narrow the market."""
    inputs = batch(
        posting("dev", required=("Java",)),
        posting(
            "designer",
            required=("Java",),
            raw_job_category="디자인",
            title="그래픽 디자이너",
        ),
    )
    cohort = build_cohort(inputs, market())
    assert not any("ROLE_NOT_MATCHED" in row.reasons for row in cohort.exclusions)
    assert aggregate_demand(cohort).denominator == 2


def test_cross_source_duplicates_stay_independent_postings():
    """Company and title alone are not enough to call two sites one job.

    S15P21E102-352 narrowed this: a JobKorea/Saramin pair that also agrees on
    region and deadline is now counted once (see the canonical dedup tests
    below). Everything short of that still stays two postings, which is what
    this pair is -- the deadlines are two weeks apart, so there is no evidence
    they are the same posting rather than two hiring rounds.
    """
    inputs = batch(
        posting(
            "jk-1",
            required=("Java",),
            source_site="JOBKOREA",
            company_name="같은회사",
            title="백엔드 개발자",
            deadline="2026-10-01T00:00:00Z",
        ),
        posting(
            "sr-1",
            required=("Java",),
            source_site="SARAMIN",
            company_name="같은회사",
            title="백엔드 개발자",
            deadline="2026-10-15T00:00:00Z",
        ),
    )
    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )
    assert demand.denominator == 2
    assert tech(demand, "java").total_count == 2


# --- isolation from the other purposes --------------------------------------


def test_market_snapshot_is_rejected_by_the_monthly_trend():
    from pathlib import Path

    from registry.contracts import load_registry
    from trend.contracts import TrendStatus
    from trend.job import job_trend

    registry = load_registry(
        Path(__file__).resolve().parents[1]
        / "registry/data/technology_registry_v1.json",
        repository_root=Path(__file__).resolve().parents[2],
    )
    demand = aggregate_demand(build_cohort(batch(posting()), market()))
    result = job_trend("java", (demand,), registry, periods=("2026-08",))
    assert result.status is TrendStatus.FAILED
    assert result.reasons == ("MONTHLY_DEMAND_COHORT_REQUIRED",)


def test_market_snapshot_is_rejected_by_recommendation():
    """A market aggregate is not a person's comparison set."""
    from recommendation.engine import build_recommendations

    cohort = build_cohort(batch(posting()), market())
    with pytest.raises(ValueError, match="ACTIVE_MATCHING_COHORT_REQUIRED"):
        build_recommendations(cohort, None, user_id="u-1", analysis_id="a-1")


def test_market_and_role_cohorts_get_different_ids():
    inputs = batch(posting())
    assert (
        build_cohort(inputs, market()).cohort_id
        != build_cohort(inputs, backend()).cohort_id
    )


def test_market_demand_roundtrips_through_json():
    demand = aggregate_demand(build_cohort(batch(posting()), market()))
    restored = DemandSnapshot.model_validate_json(demand.model_dump_json())
    assert restored == demand
    assert restored.criteria.purpose is CohortPurpose.CURRENT_MARKET


# --- cross-site canonical dedup, Current Market only (S15P21E102-352) --------


def xsite(identifier, site, required=("Java",), **changes):
    defaults = {
        "source_site": site,
        "company_name": "같은회사",
        "title": "백엔드 개발자",
        "region": "서울 강남구",
        "deadline": "2026-09-30T00:00:00Z",
    }
    defaults.update(changes)
    return posting(identifier, required=required, **defaults)


def test_market_counts_a_high_confidence_cross_site_pair_once():
    """The same job on both sites is one posting in the market population."""
    inputs = batch(
        xsite("jk-1", "JOBKOREA"),
        xsite("sr-1", "SARAMIN", deadline="2026-10-01T00:00:00Z"),
    )

    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )

    assert demand.denominator == 1
    assert tech(demand, "java").total_count == 1


def test_market_keeps_an_ambiguous_cross_site_pair_as_two():
    """Deadlines two weeks apart read as separate posting cycles, not one job."""
    inputs = batch(
        xsite("jk-1", "JOBKOREA", deadline="2026-09-30T00:00:00Z"),
        xsite("sr-1", "SARAMIN", deadline="2026-10-14T00:00:00Z"),
    )

    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )

    assert demand.denominator == 2
    assert tech(demand, "java").total_count == 2


def test_market_keeps_different_roles_at_one_company_as_two():
    inputs = batch(
        xsite("jk-1", "JOBKOREA", title="백엔드 개발자"),
        xsite("sr-1", "SARAMIN", title="프론트엔드 개발자"),
    )

    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )

    assert demand.denominator == 2


def test_market_keeps_a_many_to_one_cross_site_match_as_three():
    """Two JobKorea reposts against one Saramin posting: no evidence which."""
    inputs = batch(
        xsite("jk-1", "JOBKOREA", deadline="2026-09-30T00:00:00Z"),
        xsite("jk-2", "JOBKOREA", deadline="2026-09-29T00:00:00Z"),
        xsite("sr-1", "SARAMIN", deadline="2026-10-01T00:00:00Z"),
    )

    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )

    assert demand.denominator == 3


def test_market_keeps_same_title_at_different_companies_as_two():
    inputs = batch(
        xsite("jk-1", "JOBKOREA", company_name="회사가"),
        xsite(
            "sr-1", "SARAMIN", company_name="회사나", deadline="2026-10-01T00:00:00Z"
        ),
    )

    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )

    assert demand.denominator == 2


def test_active_matching_keeps_the_same_pair_as_two_postings():
    """S15P21E102-352 changes Current Market only; matching identity is untouched."""
    inputs = batch(
        xsite("jk-1", "JOBKOREA"),
        xsite("sr-1", "SARAMIN", deadline="2026-10-01T00:00:00Z"),
    )

    cohort = build_cohort(inputs, backend(sources=["JOBKOREA", "SARAMIN"]))

    assert len({job.job_id for job in cohort.jobs}) == 2
    assert aggregate_demand(cohort).denominator == 2


def test_market_dedup_leaves_source_identity_on_the_cohort_rows():
    """Only the market count collapses; the rows keep both source identities."""
    inputs = batch(
        xsite("jk-1", "JOBKOREA"),
        xsite("sr-1", "SARAMIN", deadline="2026-10-01T00:00:00Z"),
    )

    cohort = build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))

    assert {row.source_site for row in (*cohort.jobs, *cohort.exclusions)} == {
        "JOBKOREA",
        "SARAMIN",
    }
    assert aggregate_demand(cohort).denominator == 1


# --- the merged count must not become a loophole (S15P21E102-352 audit) ------


def test_a_merged_pair_counts_a_shared_technology_once():
    inputs = batch(
        xsite("jk-1", "JOBKOREA", required=("Python",)),
        xsite("sr-1", "SARAMIN", required=("Python",), deadline="2026-10-01T00:00:00Z"),
    )

    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )

    assert demand.denominator == 1
    assert tech(demand, "python").total_count == 1


def test_a_merged_pair_unions_technologies_but_counts_each_once():
    """Two sites describe one job differently; the canonical job holds both."""
    inputs = batch(
        xsite("jk-1", "JOBKOREA", required=("Python",)),
        xsite(
            "sr-1",
            "SARAMIN",
            required=("Python", "Docker"),
            deadline="2026-10-01T00:00:00Z",
        ),
    )

    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )

    assert demand.denominator == 1
    assert tech(demand, "python").total_count == 1
    assert tech(demand, "docker").total_count == 1


def test_no_technology_can_exceed_the_denominator_at_scale():
    """Many unrelated jobs plus several cross-site duplicates."""
    records = []
    for index in range(40):
        records.append(
            posting(
                f"solo-{index}",
                required=("Java",),
                source_site="WORKNET",
                company_name=f"회사{index}",
                title=f"직무{index}",
            )
        )
    for index in range(8):
        records.append(
            xsite(
                f"jk-{index}",
                "JOBKOREA",
                company_name=f"중복회사{index}",
                required=("Java",),
            )
        )
        records.append(
            xsite(
                f"sr-{index}",
                "SARAMIN",
                company_name=f"중복회사{index}",
                required=("Java",),
                deadline="2026-10-01T00:00:00Z",
            )
        )

    demand = aggregate_demand(build_cohort(batch(*records), market()))

    assert demand.denominator == 48
    assert demand.cross_site_merged_count == 8
    for row in demand.technologies:
        assert row.total_count <= demand.denominator


def test_the_merged_count_cannot_excuse_a_technology_over_count():
    """The per-technology guard never consults `cross_site_merged_count`."""
    inputs = batch(
        xsite("jk-1", "JOBKOREA", required=("Python",)),
        xsite("sr-1", "SARAMIN", required=("Python",), deadline="2026-10-01T00:00:00Z"),
    )
    honest = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )
    payload = honest.model_dump(mode="json")
    # A technology claiming more postings than the market holds, with a large
    # merge count alongside it. The merge count must not buy it any room.
    payload["cross_site_merged_count"] = 40
    payload["technologies"][0]["total_count"] = honest.denominator + 1
    payload["technologies"][0]["required_count"] = honest.denominator + 1

    with pytest.raises(ValidationError, match="total count"):
        DemandSnapshot.model_validate(payload)


def test_the_merged_count_reports_strict_merges_not_every_market_merge():
    """Excluded postings merging must not lend slack to the strict invariant."""
    inputs = batch(
        xsite("jk-1", "JOBKOREA", required=("Python",)),
        xsite("sr-1", "SARAMIN", required=("Python",), deadline="2026-10-01T00:00:00Z"),
    )

    demand = aggregate_demand(
        build_cohort(inputs, market(sources=["JOBKOREA", "SARAMIN"]))
    )

    strict = (
        demand.input_count
        - demand.duplicate_count
        - demand.excluded_count
        - demand.review_count
    )
    assert strict - demand.cross_site_merged_count == demand.denominator


# --- expired postings --------------------------------------------------------
#
# "지금 확보한 유효 공고"가 계약인데 마감 여부를 보지 않으면 분모는 수집한 누적 공고
# 수로 자라기만 한다. 끝난 채용의 요구 기술이 현재 수요로 계속 계산되고, 오래 수집할
# 수록 과거가 현재를 덮는다. 판정은 ACTIVE_MATCHING 과 같은 두 신호만 쓴다 —
# posting_status 와 deadline. 둘 다 입력 계약에 이미 있는 필드다.


def closed(identifier="closed", **changes):
    return posting(identifier, posting_status="CLOSED", **changes)


def test_market_excludes_a_posting_the_site_reports_as_closed():
    inputs = batch(posting("open", required=("Java",)), closed(required=("Java",)))
    demand = aggregate_demand(build_cohort(inputs, market()))

    assert demand.denominator == 1
    assert tech(demand, "java").total_count == 1


def test_market_keeps_an_active_posting():
    demand = aggregate_demand(build_cohort(batch(posting()), market()))

    assert demand.denominator == 1


def test_market_excludes_a_posting_whose_deadline_has_passed():
    """`as_of` 기준이다. 오늘 날짜가 아니라 그 snapshot 이 선 시각으로 판정한다."""
    inputs = batch(
        posting("open", required=("Java",)),
        posting("over", required=("Java",), deadline="2026-09-01T00:00:00Z"),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))

    assert demand.denominator == 1
    assert tech(demand, "java").total_count == 1


def test_market_keeps_a_deadline_that_has_not_arrived():
    inputs = batch(posting("later", deadline="2026-12-31T00:00:00Z"))

    assert aggregate_demand(build_cohort(inputs, market())).denominator == 1


def test_market_keeps_a_posting_without_a_deadline():
    """마감일이 없으면 만료를 주장할 근거가 없다. 남기는 것이 기존 정책이다.

    현재 입력 계약에는 "마지막으로 목록에서 보인 시각"이 없어, 목록에서 사라진 것과
    수집이 한 번 실패한 것을 구분할 수 없다. 임의 TTL 로 지우면 collector miss 를
    마감으로 오판한다.
    """
    inputs = batch(posting("no-deadline", deadline=None, posting_status="UNKNOWN"))
    cohort = build_cohort(inputs, market())

    assert aggregate_demand(cohort).denominator == 1
    assert any("POSTING_STATUS_UNKNOWN" in row.reasons for row in cohort.exclusions)


def test_market_requirement_counts_fall_together_with_the_denominator():
    """분모만 줄고 분자가 남으면 비율이 1 을 넘는다."""
    inputs = batch(
        posting("open", required=("Java",)),
        closed("gone", required=("Java", "Python")),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))

    assert demand.denominator == 1
    assert tech(demand, "java").total_count == 1
    assert tech(demand, "java").total_ratio == 1.0
    assert all(row.tech_id != "python" for row in demand.technologies)


def test_an_expired_posting_still_keeps_its_lineage():
    """분모에서 빼는 것이지 기록을 지우는 것이 아니다. 원본과 판정 근거는 남는다."""
    cohort = build_cohort(batch(posting("open"), closed("gone")), market())
    excluded = [row for row in cohort.exclusions if row.source_posting_id == "gone"]

    assert len(excluded) == 1
    assert "POSTING_CLOSED" in excluded[0].reasons
    assert excluded[0].source_site == "SARAMIN"


def test_every_source_follows_the_same_expiry_rule():
    """JobKorea 와 Saramin 에 서로 다른 유효성 정의를 두지 않는다.

    제목을 사이트마다 다르게 둔 것은 의도다. 두 열린 공고가 회사·제목·지역·마감일까지
    같으면 S15P21E102-352 의 cross-site dedup 이 한 건으로 합쳐, 이 테스트가 재려는
    만료 규칙 대신 중복 제거를 재게 된다.
    """
    inputs = batch(
        posting(
            "jk-open",
            source_site="JOBKOREA",
            source_posting_id="jk-open",
            title="백엔드 개발자",
        ),
        closed("jk-closed", source_site="JOBKOREA", source_posting_id="jk-closed"),
        posting(
            "sr-open",
            source_site="SARAMIN",
            source_posting_id="sr-open",
            title="플랫폼 엔지니어",
        ),
        closed("sr-closed", source_site="SARAMIN", source_posting_id="sr-closed"),
    )
    demand = aggregate_demand(build_cohort(inputs, market()))

    assert demand.denominator == 2


def test_monthly_demand_still_counts_a_posting_that_has_since_closed():
    """완료된 달의 수요다. 지금 닫혔다고 빼면 오래된 달일수록 수요가 줄어든다."""
    from test_monthly_demand_policy import august_posting, monthly_criteria

    cohort = build_cohort(
        batch(august_posting(posting_status="CLOSED")), monthly_criteria()
    )

    assert not any(
        "POSTING_CLOSED" in row.reasons or "DEADLINE_PASSED" in row.reasons
        for row in cohort.exclusions
    )


def test_a_malformed_deadline_never_reaches_the_cohort():
    """형식이 깨진 날짜는 입력 검증에서 걸린다. 조용히 '만료 아님'이 되지 않는다."""
    with pytest.raises(ValidationError, match="deadline"):
        posting("bad", deadline="2026-13-01T00:00:00Z")
